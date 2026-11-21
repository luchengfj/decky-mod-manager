"""Round 43 / P1#5: a SECOND writable game needs one descriptor, no engine code.

`docs/NEXT_FEATURES.md` P1#5 said the recipe for adding a game was unproven:
every writable path in this plugin had only ever been exercised by Stardew
Valley (AppID 413150), and the one other game that reached `FileDropEngine`
(Factorio) is `force_read_only: true`, so it proves the *parser* layer, never
the write path.

This suite builds a synthetic second game whose descriptor differs from the
Stardew one in every dimension the engine could have hard-coded:

  * a different AppID and installdir                       (990001 / "Second Game")
  * a mod folder OUTSIDE the game root                     (${HOME}/.secondgame/mods)
  * a different manifest file name                         (mod.json, not manifest.json)
  * different manifest field names                         (modId/title/semver)
  * a different launcher marker and launch-option token    (SecondGameLoader)
  * its own external-manager marker                        (OtherManager.lock)
  * its own extension policy                               (a .exe is refused, a .dll is not)

and then drives the REAL `FileDropEngine` through the whole lifecycle:
status -> inspect -> install (two-phase) -> disable -> enable -> uninstall ->
rollback. Nothing in `deckymod/` is patched or mocked; the only thing that is
different from production is the registry directory passed as
`Registry(base_dir=...)`.

What this proves: the write path is descriptor-driven, so a second game is a
data change. What it does NOT prove: that any real second game's folder layout,
manifest dialect or launcher semantics match a guess -- and therefore it is not
a claim of 全游戏通用一键装, and it does not close the original G3 (RimWorld
294100), which needs its own real-device sign-off.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deckymod.journal import Journal
from deckymod.registry import Registry
from deckymod.smapi import FileDropEngine

# tests/test_mvp.py pins DECKYMOD_GAME_ID=rimworld at IMPORT time, and unittest
# discovery imports every module before running any. This suite needs the pin
# ABSENT so its own registry decides the active game, so it is saved/popped at
# EXECUTION time only -- a module-level pop would erase the RimWorld pin and
# break test_mvp.py (a mistake this repo has already made three times).
_PREV_GAME_ID = None


def setUpModule():
    global _PREV_GAME_ID
    _PREV_GAME_ID = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    if _PREV_GAME_ID is not None:
        os.environ["DECKYMOD_GAME_ID"] = _PREV_GAME_ID
    else:
        os.environ.pop("DECKYMOD_GAME_ID", None)


APPID = 990001
INSTALLDIR = "Second Game"
LAUNCHER = "SecondGameLoader"
MARKER = "OtherManager.lock"

#: The whole adaptation for the second game. Nothing outside this dict (and the
#: registry wrapper) is game-specific.
DESCRIPTOR = {
    "schema": 1,
    "id": "secondgame",
    "status": "enabled",
    "engine": "file_drop",
    "display_label": "Second Game (synthetic)",
    "identity": {
        "appid": APPID,
        "name": "Second Game",
        "platform": "linux-native",
        "status": "synthetic",
        "note": "Test fixture only. This game does not exist.",
    },
    "paths": {
        "mod_root": "${HOME}/.secondgame/mods",
        "staging": "${HOME}/.secondgame/.decky-staging",
        "quarantine": "${HOME}/.secondgame/.decky-quarantine/${TXN_ID}",
        "disabled": "${HOME}/.secondgame/.decky-disabled",
        "state_file": None,
        "state_staging": None,
    },
    "loader_detection": {
        "patterns": [LAUNCHER],
        "external_manager_markers": [MARKER],
        "launch_options_must_already_be_set": True,
        "launcher_token": LAUNCHER,
        "on_missing_launcher": "E_LOADER_MISSING",
        "running_detection": {"enabled": False},
    },
    "mod_package": {
        "archive_format": "zip",
        "parser": "json_map",
        "manifest_globs": ["mod.json", "*/mod.json"],
        "manifest_format": "json",
        "strip_single_root": True,
        "install_relpath_prefix": "mods/",
        "field_map": {
            "id": "modId",
            "name": "title",
            "version": "semver",
            "author": "creator",
            "dependencies": ["requires"],
            "dependency_id_keys": ["modId"],
        },
        "id_regex": "^[A-Za-z0-9][A-Za-z0-9_.-]*$",
        "id_normalize": "lowercase_for_directory",
        "required_manifest_fields": ["modId", "title", "semver"],
        "install_filename_template": "${id}",
        "install_is_directory": True,
        "limits": {
            "max_compressed_bytes": 33554432,
            "max_uncompressed_bytes": 33554432,
            "max_entries": 512,
            "max_compression_ratio": 100,
            "max_path_depth": 8,
        },
        "reject": ["absolute_paths", "parent_traversal", "symlinks"],
        # Deliberately different from Stardew: this loader does not refuse .dll
        # (its mods are native), and it refuses .exe like everybody else.
        "reject_extensions": [".exe"],
        "allow_extensions": [".dat", ".dll"],
        "conflicts": {"enabled": True, "scope": "per_mod_directory", "ignore": []},
    },
    "state_mutator": {"strategy": "none"},
    "conflict_policy": {"enabled": False},
    "capabilities": {
        "local_import": True,
        "enable_disable": True,
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

MANIFEST = {
    "modId": "Second.Machine",
    "title": "Second Machine",
    "semver": "1.2.3",
    "creator": "someone",
    "requires": ["Second.Core"],
}


def _zip(path, files, wrapper=None):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            nm = (wrapper + "/" + name) if wrapper else name
            z.writestr(nm, data)


def _tmpdir(prefix="second-game-"):
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        ".decky-test-tmp", prefix + os.urandom(6).hex())
    os.makedirs(base, exist_ok=True)
    return base


class SecondTree:
    """A fake Steam library + a private registry for the synthetic game."""

    def __init__(self):
        self.base = _tmpdir()
        self.home = os.path.join(self.base, "home")
        self.xdg = os.path.join(self.base, "xdg")
        self.inbox = os.path.join(self.base, "inbox")
        self.data = os.path.join(self.base, "data")
        self.logs = os.path.join(self.data, "logs")
        for d in (self.home, self.xdg, self.inbox, self.data, self.logs):
            os.makedirs(d, exist_ok=True)
        self.mods = os.path.join(self.home, ".secondgame", "mods")
        os.makedirs(self.mods, exist_ok=True)
        self.steam = os.path.join(self.base, "Steam")
        self.sapps = os.path.join(self.steam, "steamapps")
        self.game = os.path.join(self.sapps, "common", INSTALLDIR)
        os.makedirs(self.game, exist_ok=True)
        with open(os.path.join(self.game, LAUNCHER), "wb") as f:
            f.write(b"ELF")
        ud = os.path.join(self.steam, "userdata", "123", "config")
        os.makedirs(ud, exist_ok=True)
        # Round 79: the fixture now uses the REAL localconfig.vdf shape
        # (UserLocalConfigStore/Software/Valve/Steam/apps/<appid>). The old
        # loose substring check passed anything containing the token; the new
        # parse-based check reads the app's OWN block.
        launch_options = ('"UserLocalConfigStore"\n{\n\t"Software"\n\t{\n'
                          '\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n'
                          '\t\t\t\t"apps"\n\t\t\t\t{\n'
                          '\t\t\t\t\t"%d"\n\t\t\t\t\t{\n'
                          '\t\t\t\t\t\t"LaunchOptions"\t\t"\\"/home/deck/.steam/steam/steamapps/common/%s/%s\\" %%command%%"\n'
                          '\t\t\t\t\t}\n\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n'
                          % (APPID, INSTALLDIR, LAUNCHER))
        with open(os.path.join(ud, "localconfig.vdf"), "w", encoding="utf-8") as f:
            f.write(launch_options)
        # `check_launch_options()` looks in the user's own Steam dirs (it does
        # NOT take DECKYMOD_STEAM_ROOT), so the same file has to exist there for
        # the descriptor's launch-option gate to be exercised for real.
        real_ud = os.path.join(self.home, ".local", "share", "Steam", "userdata",
                               "123", "config")
        os.makedirs(real_ud, exist_ok=True)
        with open(os.path.join(real_ud, "localconfig.vdf"), "w", encoding="utf-8") as f:
            f.write(launch_options)
        with open(os.path.join(self.sapps, "libraryfolders.vdf"), "w", encoding="utf-8") as f:
            f.write('"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"'
                    + self.steam + '"\n\t\t"apps"\n\t\t{\n\t\t}\n\t}\n}\n')
        with open(os.path.join(self.sapps, "appmanifest_%d.acf" % APPID), "w",
                  encoding="utf-8") as f:
            f.write('"AppState"\n{\n\t"appid"\t\t"%d"\n\t"installdir"\t\t"%s"\n}\n'
                    % (APPID, INSTALLDIR))
        # The registry this engine will read: one enabled descriptor.
        self.reg_root = os.path.join(self.base, "pluginroot")
        os.makedirs(os.path.join(self.reg_root, "registry", "games"), exist_ok=True)
        with open(os.path.join(self.reg_root, "registry", "games", "secondgame.json"),
                  "w", encoding="utf-8") as f:
            json.dump(DESCRIPTOR, f, indent=1)
        with open(os.path.join(self.reg_root, "registry", "registry.json"), "w",
                  encoding="utf-8") as f:
            json.dump({
                "schema": 1,
                "version": "0.0.0-secondgame",
                "capability_gate": {
                    "enabled_game_status": "enabled",
                    "max_enabled_games_in_mvp": 1,
                    "refuse_if_status_not_enabled": True,
                    "refuse_if_capability_false": True,
                },
                "descriptors": {"secondgame": {"file": "registry/games/secondgame.json"}},
                "loader_catalog": {},
            }, f, indent=1)

    def descriptor(self, **overrides) -> dict:
        d = json.loads(json.dumps(DESCRIPTOR))
        for key, value in overrides.items():
            if isinstance(value, dict) and isinstance(d.get(key), dict):
                d[key].update(value)
            else:
                d[key] = value
        return d

    def rewrite_descriptor(self, descriptor: dict) -> None:
        with open(os.path.join(self.reg_root, "registry", "games", "secondgame.json"),
                  "w", encoding="utf-8") as f:
            json.dump(descriptor, f, indent=1)

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

    def registry(self) -> Registry:
        return Registry(base_dir=self.reg_root)

    def engine(self) -> FileDropEngine:
        return FileDropEngine(registry=self.registry(),
                              journal=Journal(self.data, self.logs, "secondgame"))

    def cleanup(self):
        shutil.rmtree(self.base, ignore_errors=True)


class _Base(unittest.TestCase):
    def setUp(self):
        self.t = SecondTree()
        self.t.env()

    def tearDown(self):
        self.t.cleanup()

    def _install_fully(self, name="secondmachine.zip", files=None, wrapper="SecondMachine"):
        zp = os.path.join(self.t.inbox, name)
        _zip(zp, files or {"mod.json": json.dumps(MANIFEST), "data.dat": b"\x00\x01"},
             wrapper=wrapper)
        eng = self.t.engine()
        first = eng.install(zp)
        self.assertTrue(first["ok"], first)
        self.assertEqual(first["data"]["phase"], "confirm")
        second = eng.install(zp, after_confirm=True)
        self.assertTrue(second["ok"], second)
        return zp, second


class TestSecondGameIsDescriptorOnly(_Base):
    """One enabled descriptor is enough to make the game active and writable."""

    def test_descriptor_alone_selects_the_game(self):
        reg = self.t.registry()
        self.assertEqual(reg.active_descriptor()[0], "secondgame")
        self.assertEqual(reg.enabled_games(), ["secondgame"])
        self.assertEqual(reg.appid_for("secondgame"), APPID)

    def test_mod_root_comes_from_the_descriptor_not_from_the_code(self):
        r = self.t.engine()._resolve()
        self.assertEqual(os.path.normcase(r.mod_root),
                         os.path.normcase(self.t.mods))
        # The historical hard-code would have resolved this instead:
        self.assertNotEqual(os.path.normcase(r.mod_root),
                            os.path.normcase(os.path.join(self.t.game, "Mods")))
        self.assertEqual(os.path.normcase(r.disabled_root),
                         os.path.normcase(os.path.join(self.t.home, ".secondgame",
                                                       ".decky-disabled")))

    def test_status_writes_nothing_and_reports_the_descriptor(self):
        eng = self.t.engine()
        env = eng.status()
        self.assertTrue(env["ok"], env)
        data = env["data"]
        self.assertEqual(data["game"]["appid"], APPID)
        self.assertEqual(data["state"]["strategy"], "file_drop")
        self.assertFalse(data["state"]["read_only"])
        self.assertEqual(data["state"]["mods"], [])
        # The descriptor's own layout is what status reports as W2.
        self.assertEqual(os.path.normcase(data["paths"]["w2_mod_root"]),
                         os.path.normcase(self.t.mods))
        # The launch-option gate is descriptor-driven and, with the token in
        # place, reports "set" rather than the permissive "unknown".
        self.assertEqual(data["state"]["launch_options"], "set")
        self.assertEqual(os.listdir(self.t.mods), [])


class TestSecondGameManifestIsDescriptorDriven(_Base):
    """The manifest's file name and field names come from `mod_package`."""

    def test_its_own_manifest_name_is_required(self):
        # A Stardew-shaped manifest must NOT satisfy this game's descriptor.
        zp = os.path.join(self.t.inbox, "stardew-shaped.zip")
        _zip(zp, {"manifest.json": json.dumps({
            "Name": "X", "UniqueID": "x.y", "Version": "1.0.0"})}, wrapper="X")
        env = self.t.engine().install(zp)
        self.assertFalse(env["ok"], env)
        self.assertEqual(env["code"], "E_MANIFEST_MISSING", env)

    def test_its_own_field_names_are_read(self):
        _, env = self._install_fully()
        self.assertEqual(env["data"]["uniqueId"], MANIFEST["modId"])
        target = env["data"]["dir"]
        self.assertTrue(os.path.isdir(target))
        self.assertTrue(os.path.isfile(os.path.join(target, "mod.json")))

    def test_directory_name_uses_the_declared_normalisation(self):
        _, env = self._install_fully()
        self.assertEqual(env["data"]["dir_name"], "second.machine")


class TestSecondGameExtensionPolicyIsDescriptorDriven(_Base):
    """`.dll` was Stardew's relaxation; here the descriptor is the authority."""

    def test_a_dll_is_accepted_because_this_descriptor_allows_it(self):
        _, env = self._install_fully(files={
            "mod.json": json.dumps(MANIFEST), "native.dll": b"MZ"})
        self.assertTrue(env["ok"], env)

    def test_an_exe_is_refused(self):
        zp = os.path.join(self.t.inbox, "with-exe.zip")
        _zip(zp, {"mod.json": json.dumps(MANIFEST), "setup.exe": b"MZ"},
             wrapper="SecondMachine")
        env = self.t.engine().install(zp)
        self.assertFalse(env["ok"], env)
        # The refusal comes from this descriptor's `reject_extensions`, and the
        # wire code is the archive layer's shared one.
        self.assertEqual(env["code"], "E_UNSAFE_ENTRY", env)
        self.assertIn("setup.exe", env["detail"])


class TestSecondGameLifecycle(_Base):
    """The whole write path, on a game the engine has never seen."""

    def test_install_disable_enable_uninstall_rollback(self):
        eng = self.t.engine()
        _, installed = self._install_fully()
        uid = MANIFEST["modId"]
        target = installed["data"]["dir"]
        self.assertTrue(os.path.isdir(target))

        # status agrees the mod is there, and reports it as installed.
        st = eng.status()
        self.assertTrue(st["ok"], st)
        self.assertEqual([m["uniqueId"] for m in st["data"]["state"]["mods"]], [uid])
        self.assertEqual([r["packageId"] for r in st["data"]["installed"]], [uid])

        # disable -> the folder MOVES to the descriptor's disabled root.
        first = eng.set_enabled(uid, False)
        self.assertTrue(first["ok"], first)
        self.assertEqual(first["data"]["phase"], "confirm")
        done = eng.set_enabled(uid, False, after_confirm=True)
        self.assertTrue(done["ok"], done)
        self.assertFalse(os.path.isdir(target))
        parked = os.path.join(self.t.home, ".secondgame", ".decky-disabled", "second.machine")
        self.assertTrue(os.path.isdir(parked))
        st = eng.status()
        self.assertEqual([m["uniqueId"] for m in st["data"]["state"]["disabled_mods"]], [uid])

        # enable -> back into the descriptor's mod_root.
        self.assertTrue(eng.set_enabled(uid, True)["data"]["phase"] == "confirm")
        back = eng.set_enabled(uid, True, after_confirm=True)
        self.assertTrue(back["ok"], back)
        self.assertTrue(os.path.isdir(target))

        # uninstall -> quarantine, never a silent delete.
        self.assertEqual(eng.uninstall(uid)["data"]["phase"], "confirm")
        gone = eng.uninstall(uid, after_confirm=True)
        self.assertTrue(gone["ok"], gone)
        self.assertFalse(os.path.isdir(target))
        self.assertEqual(eng.status()["data"]["state"]["mods"], [])

        # rollback -> the exact folder comes back from quarantine.
        rb = eng.rollback(gone["data"]["txn"])
        self.assertTrue(rb["ok"], rb)
        self.assertTrue(os.path.isdir(target))
        self.assertTrue(os.path.isfile(os.path.join(target, "mod.json")))

    def test_a_second_install_of_the_same_id_is_refused(self):
        eng = self.t.engine()
        self._install_fully()
        zp = os.path.join(self.t.inbox, "again.zip")
        _zip(zp, {"mod.json": json.dumps(MANIFEST), "data.dat": b"x"}, wrapper="SecondMachine")
        # A plain install (no confirmation) is the "just add this" path and must
        # refuse rather than silently replacing the mod the user already has.
        env = eng.install(zp)
        self.assertFalse(env["ok"], env)
        self.assertEqual(env["code"], "E_DUPLICATE", env)
        # With after_confirm it is an explicit UPGRADE, which is allowed -- on
        # this game too, because nothing about upgrades is game-specific.
        up = eng.install(zp, after_confirm=True)
        self.assertTrue(up["ok"], up)
        self.assertTrue(os.path.isdir(up["data"]["dir"]))


class TestSecondGameRefusalsAreDescriptorDriven(_Base):
    """The gates fire from descriptor data, not from a game id branch."""

    def test_its_own_external_manager_marker_blocks_writes(self):
        with open(os.path.join(self.t.mods, MARKER), "wb") as f:
            f.write(b"owned by somebody else\n")
        zp = os.path.join(self.t.inbox, "blocked.zip")
        _zip(zp, {"mod.json": json.dumps(MANIFEST)}, wrapper="SecondMachine")
        env = self.t.engine().install(zp)
        self.assertFalse(env["ok"], env)
        self.assertEqual(env["code"], "E_EXTERNAL_MANAGER", env)

    def test_stardews_marker_is_not_a_marker_for_this_game(self):
        # `.mm_deployed` is Stardew's `DEFAULT_EXTERNAL_MARKERS` entry. Because
        # this descriptor names its own list, the Stardew marker must be inert.
        with open(os.path.join(self.t.mods, ".mm_deployed"), "wb") as f:
            f.write(b"{}")
        _, env = self._install_fully()
        self.assertTrue(env["ok"], env)

    def test_a_missing_launcher_uses_the_descriptors_error(self):
        os.remove(os.path.join(self.t.game, LAUNCHER))
        zp = os.path.join(self.t.inbox, "nolauncher.zip")
        _zip(zp, {"mod.json": json.dumps(MANIFEST)}, wrapper="SecondMachine")
        env = self.t.engine().install(zp)
        self.assertFalse(env["ok"], env)
        self.assertEqual(env["code"], "E_LOADER_MISSING", env)

    def test_a_capability_false_still_gates_that_operation(self):
        d = self.t.descriptor()
        d["capabilities"]["local_import"] = False
        self.t.rewrite_descriptor(d)
        zp = os.path.join(self.t.inbox, "gated.zip")
        _zip(zp, {"mod.json": json.dumps(MANIFEST)}, wrapper="SecondMachine")
        env = self.t.engine().install(zp)
        self.assertFalse(env["ok"], env)
        self.assertEqual(env["code"], "E_CAPABILITY_DISABLED", env)


class TestLaunchOptionsParsing(_Base):
    """Round 79 device finding: the old substring-anywhere check reported
    "set" while the active account's app block had NO launch option — which
    is exactly the state that starts the game without SMAPI. The check now
    parses the VDF and reads the app's OWN LaunchOptions."""

    def _lc_dir(self, uid):
        d = os.path.join(self.t.home, ".local", "share", "Steam", "userdata",
                         uid, "config")
        os.makedirs(d, exist_ok=True)
        return d

    def _write(self, uid, body):
        with open(os.path.join(self._lc_dir(uid), "localconfig.vdf"), "w",
                  encoding="utf-8") as f:
            f.write(body)

    def _read(self):
        from deckymod.file_drop import check_launch_options
        return check_launch_options(self.t.home, appid=str(APPID),
                                    launcher_token=LAUNCHER)

    def test_the_app_block_launch_option_is_set(self):
        self.assertEqual(self._read(), "set")

    def test_an_app_block_without_launch_options_is_missing(self):
        self._write("123", '"UserLocalConfigStore"\n{\n\t"Software"\n\t{\n'
                           '\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n'
                           '\t\t\t\t"apps"\n\t\t\t\t{\n'
                           '\t\t\t\t\t"%d"\n\t\t\t\t\t{\n'
                           '\t\t\t\t\t}\n\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n'
                           % APPID)
        self.assertEqual(self._read(), "missing")

    def test_the_token_in_another_apps_block_is_not_set(self):
        # The regression that actually bit on device: the token existed in the
        # file (another account / another app) while the game's own block had
        # no launch option. That must read "missing", not "set".
        self._write("123", '"UserLocalConfigStore"\n{\n\t"Software"\n\t{\n'
                           '\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n'
                           '\t\t\t\t"apps"\n\t\t\t\t{\n'
                           '\t\t\t\t\t"%d"\n\t\t\t\t\t{\n'
                           '\t\t\t\t\t}\n'
                           '\t\t\t\t\t"999999"\n\t\t\t\t\t{\n'
                           '\t\t\t\t\t\t"LaunchOptions"\t\t"%s %%command%%"\n'
                           '\t\t\t\t\t}\n\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n'
                           % (APPID, LAUNCHER))
        self.assertEqual(self._read(), "missing")

    def test_a_garbled_localconfig_is_unknown_not_fatal(self):
        self._write("123", "{ not a vdf ")
        self.assertEqual(self._read(), "unknown")


if __name__ == "__main__":
    unittest.main()
