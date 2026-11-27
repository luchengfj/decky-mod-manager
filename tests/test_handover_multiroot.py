"""Round 81: handing over a game whose mods are NOT one folder.

Round 55 gave ``FileDropEngine`` a way out of "another manager owns ``Mods/``":
move the symlinked entries and marker files into the quarantine, reversibly.
``RootMergeEngine`` inherited the *refusal* (Round 44's ``E_EXTERNAL_MANAGER``)
but not the *exit* -- ``handover_mods`` returned
``E_CAPABILITY_DISABLED / "handover is not implemented for this game"``. So a
Cyberpunk 2077 player whose files are deployed by Vortex, or a user-configured
game deployed by MO2, saw "read-only" with no way forward. That is exactly the
dead end ``docs/HANDOVER.md`` was written to remove, still present on the engine
that has no single ``Mods/`` at all.

This engine has no ``mod_root``: files land in ``archive/pc/mod``, ``mods``,
``bin/x64/plugins``, ``r6/scripts`` and ``red4ext``, and a user-configured game
declares one or more folders of its own. So the takeover has to survey every
declared write root, refuse as a whole if any one of them cannot be undone in
one step, and -- the part that would silently corrupt if done carelessly --
record one journal event per folder so ``rollback`` puts ALL of them back rather
than only the first.

No test here touches a real game folder or the network.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest

from deckymod.journal import Journal
from deckymod.registry import Registry
from deckymod.root_merge import RootMergeEngine
from deckymod.smapi import _slug

_PREV_GAME_ID = None


def setUpModule():
    global _PREV_GAME_ID
    _PREV_GAME_ID = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    if _PREV_GAME_ID is not None:
        os.environ["DECKYMOD_GAME_ID"] = _PREV_GAME_ID
    else:
        os.environ.pop("DECKYMOD_GAME_ID", None)


APPID = 990777
INSTALLDIR = "Multi Root Game"
MARKER = "OtherManager.lock"

#: Two write roots, deliberately of different shapes: a plain folder and a
#: nested one. A single-root fixture would pass even if the engine only ever
#: looked at ``write_roots[0]``.
DESCRIPTOR = {
    "schema": 1,
    "id": "multiroot",
    "status": "enabled",
    "engine": "root_merge",
    "display_label": "Multi Root Game (synthetic)",
    "identity": {
        "appid": APPID,
        "name": "Multi Root Game",
        "platform": "linux-native",
        "status": "synthetic",
        "note": "Test fixture only. This game does not exist.",
    },
    "paths": {
        "game_root": "${GAME_ROOT}",
        "mod_root": None,
        "write_roots": ["mods", "bin/x64/plugins"],
        "protected": ["engine"],
        "staging": "${GAME_ROOT}/.decky-staging",
        "quarantine": "${GAME_ROOT}/.decky-quarantine/${TXN_ID}",
        "state_file": None,
        "state_staging": None,
    },
    "loader_detection": {
        "external_manager_markers": [MARKER],
        "running_detection": {"enabled": False},
    },
    "mod_package": {
        "archive_format": "zip",
        "parser": "path_map",
        "manifest_globs": ["mods/*/info.json"],
        "manifest_format": "json",
        "strip_single_root": False,
    },
    "capabilities": {
        "local_import": True,
        "detection_only": False,
        "enable_disable": False,
        "uninstall_quarantine": True,
        "rollback": True,
        "loader_install": False,
        "launch_option_edit": False,
        "proton_prefix_write": False,
        "exe_installer": False,
        "requires_root": False,
        "universal_one_click": False,
    },
    "safety": {"refuse_if_game_running": False},
    "known_limitations": [],
    "known_limitation_keys": [],
}


def _tmpdir(prefix="multiroot-"):
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        ".decky-test-tmp", prefix + os.urandom(6).hex())
    os.makedirs(base, exist_ok=True)
    return base


class MultiRootTree:
    """A fake Steam library plus a private registry for the synthetic game."""

    def __init__(self, write_roots=None):
        self.base = _tmpdir()
        self.home = os.path.join(self.base, "home")
        self.xdg = os.path.join(self.base, "xdg")
        self.inbox = os.path.join(self.base, "inbox")
        self.data = os.path.join(self.base, "data")
        self.logs = os.path.join(self.data, "logs")
        for d in (self.home, self.xdg, self.inbox, self.data, self.logs):
            os.makedirs(d, exist_ok=True)

        self.steam = os.path.join(self.base, "Steam")
        self.sapps = os.path.join(self.steam, "steamapps")
        self.game = os.path.join(self.sapps, "common", INSTALLDIR)
        os.makedirs(self.game, exist_ok=True)
        with open(os.path.join(self.sapps, "libraryfolders.vdf"), "w",
                  encoding="utf-8") as f:
            f.write('"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"'
                    + self.steam + '"\n\t\t"apps"\n\t\t{\n\t\t}\n\t}\n}\n')
        with open(os.path.join(self.sapps, "appmanifest_%d.acf" % APPID), "w",
                  encoding="utf-8") as f:
            f.write('"AppState"\n{\n\t"appid"\t\t"%d"\n\t"installdir"\t\t"%s"\n}\n'
                    % (APPID, INSTALLDIR))

        self.reg_root = os.path.join(self.base, "pluginroot")
        os.makedirs(os.path.join(self.reg_root, "registry", "games"), exist_ok=True)
        descriptor = json.loads(json.dumps(DESCRIPTOR))
        if write_roots is not None:
            descriptor["paths"]["write_roots"] = list(write_roots)
        with open(os.path.join(self.reg_root, "registry", "games", "multiroot.json"),
                  "w", encoding="utf-8") as f:
            json.dump(descriptor, f, indent=1)
        with open(os.path.join(self.reg_root, "registry", "registry.json"), "w",
                  encoding="utf-8") as f:
            json.dump({
                "schema": 1,
                "version": "0.0.0-multiroot",
                "capability_gate": {
                    "enabled_game_status": "enabled",
                    "max_enabled_games_in_mvp": 1,
                    "refuse_if_status_not_enabled": True,
                    "refuse_if_capability_false": True,
                },
                "descriptors": {"multiroot": {"file": "registry/games/multiroot.json"}},
                "loader_catalog": {},
            }, f, indent=1)

    def env(self):
        os.environ.update({
            "DECKY_USER_HOME": self.home,
            "XDG_CONFIG_HOME": self.xdg,
            "DECKYMOD_INBOX": self.inbox,
            "DECKYMOD_DATA": self.data,
            "DECKYMOD_STEAM_ROOT": self.steam,
            "DECKY_PLUGIN_RUNTIME_DIR": self.data,
            "DECKY_PLUGIN_LOG_DIR": self.logs,
        })
        for k in ("DECKYMOD_GAME_RUNNING", "DECKYMOD_EXTRA_IMPORT_ROOT", "DECKY_USER"):
            os.environ.pop(k, None)

    def engine(self) -> RootMergeEngine:
        return RootMergeEngine(registry=Registry(base_dir=self.reg_root),
                               journal=Journal(self.data, self.logs, "multiroot"))

    def root(self, rel):
        return os.path.join(self.game, rel.replace("/", os.sep))

    def cleanup(self):
        shutil.rmtree(self.base, ignore_errors=True)


class _Base(unittest.TestCase):
    def setUp(self):
        self.t = MultiRootTree()
        self.t.env()
        self.eng = self.t.engine()
        self.addCleanup(self.t.cleanup)

    def _marker_in(self, rel):
        """A 0-byte marker file inside a write root: the movable case."""
        root = self.t.root(rel)
        os.makedirs(root, exist_ok=True)
        p = os.path.join(root, MARKER)
        with open(p, "wb") as f:
            f.write(b"")
        return p


class TestSlug(unittest.TestCase):
    """The quarantine subfolder name has to be safe on every filesystem."""

    def test_a_posix_path_becomes_flat(self):
        self.assertEqual(_slug("/games/Foo/mods"), "games_Foo_mods")

    def test_a_windows_path_becomes_flat(self):
        self.assertEqual(_slug("C:\\games\\Foo\\mods"), "C__games_Foo_mods")

    def test_the_same_basename_in_two_places_does_not_collide(self):
        self.assertNotEqual(_slug("/a/mods"), _slug("/b/mods"))

    def test_an_empty_path_still_yields_a_name(self):
        self.assertTrue(_slug(""))
        self.assertTrue(_slug("/"))


class TestRoots(_Base, unittest.TestCase):
    def test_every_write_root_is_surveyed_not_just_the_first(self):
        roots = self.eng._handover_roots(self.eng._resolve())
        self.assertEqual(len(roots), 2)
        self.assertTrue(roots[0].endswith(os.path.join("Multi Root Game", "mods")), roots)
        self.assertTrue(roots[1].endswith(
            os.path.join("Multi Root Game", "bin", "x64", "plugins")), roots)

    def test_the_roots_are_absolute_so_st_dev_can_be_compared(self):
        for root in self.eng._handover_roots(self.eng._resolve()):
            self.assertTrue(os.path.isabs(root), root)


class TestHandoverThroughTheEngine(_Base, unittest.TestCase):
    def test_a_marker_in_the_second_root_is_found(self):
        # Deliberately the SECOND root: an engine that only ever looked at
        # write_roots[0] would answer "nothing to hand over".
        marker = self._marker_in("bin/x64/plugins")
        plan = self.eng.handover_mods()
        self.assertTrue(plan["ok"], plan)
        self.assertEqual(plan["data"]["phase"], "confirm")
        self.assertEqual(plan["data"]["count"], 1)
        self.assertTrue(os.path.isfile(marker))

    def test_the_confirm_writes_nothing(self):
        self._marker_in("mods")
        self.eng.handover_mods()
        qroot = self.t.root(".decky-quarantine")
        self.assertFalse(os.path.isdir(qroot) and os.listdir(qroot))

    def test_both_roots_are_moved_in_one_operation(self):
        a = self._marker_in("mods")
        b = self._marker_in("bin/x64/plugins")
        done = self.eng.handover_mods(after_confirm=True)
        self.assertTrue(done["ok"], done)
        self.assertEqual(sorted(done["data"]["moved"]), [MARKER, MARKER])
        self.assertFalse(os.path.exists(a))
        self.assertFalse(os.path.exists(b))

    def test_each_root_gets_its_own_quarantine_subfolder(self):
        self._marker_in("mods")
        self._marker_in("bin/x64/plugins")
        done = self.eng.handover_mods(after_confirm=True)
        qdir = done["data"]["quarantine"]
        subs = sorted(os.listdir(qdir))
        self.assertEqual(len(subs), 2, subs)
        for sub in subs:
            self.assertTrue(os.path.isfile(os.path.join(qdir, sub, MARKER)), sub)

    def test_one_journal_event_per_root(self):
        # This is what makes rollback restore BOTH: with a single event only
        # the first folder's names would come back and the other would be
        # abandoned in the quarantine.
        self._marker_in("mods")
        self._marker_in("bin/x64/plugins")
        done = self.eng.handover_mods(after_confirm=True)
        events = [e for e in self.eng.journal.events(done["data"]["txn"])
                  if e.get("event") == "MODS_HANDOVER"]
        self.assertEqual(len(events), 2, events)
        from_paths = sorted(e.get("from_path") or "" for e in events)
        self.assertEqual(len(set(from_paths)), 2, from_paths)

    def test_rollback_puts_back_every_root_not_only_the_first(self):
        a = self._marker_in("mods")
        b = self._marker_in("bin/x64/plugins")
        done = self.eng.handover_mods(after_confirm=True)
        back = self.eng.rollback(done["data"]["txn"])
        self.assertTrue(back["ok"], back)
        self.assertEqual(back["data"]["restored"], "handover")
        self.assertEqual(back["data"]["failed"], {})
        self.assertTrue(os.path.isfile(a), "first root was not restored")
        self.assertTrue(os.path.isfile(b), "second root was not restored")

    def test_a_single_root_keeps_the_historical_flat_layout(self):
        # Byte-for-byte the Round 55 shape: <quarantine>/<txn>/<name>, no slug
        # subfolder. A one-folder game must not gain a nesting level.
        self._marker_in("mods")
        done = self.eng.handover_mods(after_confirm=True)
        qdir = done["data"]["quarantine"]
        self.assertTrue(os.path.isfile(os.path.join(qdir, MARKER)), os.listdir(qdir))

    def test_nothing_to_hand_over_is_refused_honestly(self):
        got = self.eng.handover_mods()
        self.assertFalse(got["ok"])
        self.assertIn("nothing to hand over", got["detail"])

    def test_a_missing_write_root_is_not_a_failure(self):
        # A fresh install has none of these folders yet. "I could not look" must
        # not read as "you must act", and it must not crash the survey either.
        self._marker_in("mods")
        plan = self.eng.handover_mods()
        self.assertTrue(plan["ok"], plan)
        self.assertEqual(plan["data"]["count"], 1)


class TestRefusalIsWholeOperation(_Base, unittest.TestCase):
    def test_a_symlinked_root_blocks_every_root(self):
        # `mods` is fine, `bin/x64/plugins` is a symlink. Moving only the first
        # would leave the other manager's deployment half dismantled, so the
        # answer must be a refusal that names the blocking reason.
        self._marker_in("mods")
        target = os.path.join(self.t.base, "elsewhere")
        os.makedirs(target, exist_ok=True)
        plugins = self.t.root("bin/x64/plugins")
        os.makedirs(os.path.dirname(plugins), exist_ok=True)
        try:
            os.symlink(target, plugins, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks need a privilege this runner does not have")

        got = self.eng.handover_mods()
        self.assertFalse(got["ok"])
        self.assertIn("cannot be handed over safely", got["detail"])
        self.assertIn("mods_dir_is_symlink", got["detail"])

    def test_the_refusal_names_the_reason_in_data(self):
        self._marker_in("mods")
        target = os.path.join(self.t.base, "elsewhere2")
        os.makedirs(target, exist_ok=True)
        plugins = self.t.root("bin/x64/plugins")
        os.makedirs(os.path.dirname(plugins), exist_ok=True)
        try:
            os.symlink(target, plugins, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks need a privilege this runner does not have")
        got = self.eng.handover_mods()
        self.assertEqual(got["data"]["blocking"], ["mods_dir_is_symlink"])
        self.assertEqual(got["data"]["movable"], [])


class TestDescriptorGate(_Base, unittest.TestCase):
    def test_handover_can_still_be_switched_off_by_the_descriptor(self):
        path = os.path.join(self.t.reg_root, "registry", "games", "multiroot.json")
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        d.setdefault("loader_detection", {})["handover"] = {"enabled": False}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1)

        self._marker_in("mods")
        eng = self.t.engine()
        got = eng.handover_mods()
        self.assertFalse(got["ok"])
        self.assertEqual(got["code"], "E_CAPABILITY_DISABLED")
        self.assertIn("disabled in the descriptor", got["detail"])


class TestFileDropIsUnchanged(unittest.TestCase):
    """The hook must not change the one-folder engine's answers."""

    def test_file_drop_reports_exactly_one_root(self):
        from deckymod.smapi import FileDropEngine

        class _R:
            mod_root = os.path.join("x", "Mods")

        self.assertEqual(FileDropEngine._handover_roots(None, _R()), [_R.mod_root])


if __name__ == "__main__":
    unittest.main()
