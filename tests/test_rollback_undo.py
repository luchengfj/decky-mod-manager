"""Round 65: undoing an uninstall must restore the mod or say why it did not.

Found on the device. `_rollback_inner` handled a MOD_UNINSTALLED transaction with:

    if os.path.isdir(qdir) and not os.path.isdir(src):
        os.replace(qdir, src)
    ... record MOD_ROLLBACK_RESTORED ...
    ... committed({"rollback_of": "uninstall"}) ...

Both halves of that guard are silent, and the bookkeeping ran regardless:

    D_VERSION_AFTER '9.9.9'          the user had reinstalled the mod by hand,
    D_SAYS_RESTORED 'probe.reinstall' so the move was skipped -- and the answer
    D_ROLLBACK_OK True               was "restored"

    E_QDIR_REMOVED True              the quarantined copy was gone
    E_MODS_AFTER []                  nothing came back
    E_SAYS_RESTORED 'probe.reinstall'
    E_ROLLBACK_OK True

Two harms, in the order they matter:

1. The caller is told a mod is back when it is not. In case D the mod that is on
   disk is a DIFFERENT version from the one the rollback claims to have restored.
2. The journal now carries MOD_ROLLBACK_RESTORED, so the quarantined bytes look
   owned by a finished transaction -- they become orphans, and round 54's
   `reclaim_quarantine` is allowed to delete orphans. A false success therefore
   hands real user data to a deleter.

The engine (RimWorld) had the same line, and it additionally rewrote
ModsConfig.xml from the snapshot, telling the game to load a folder that is not
there. It is unreachable from the panel today because Stardew is the enabled
game; round 57 is the case study for how "unreachable today" behaves.
"""
import json
import os
import shutil
import unittest
import uuid
import zipfile

import deckymod.engine as xml_engine
import deckymod.smapi as smapi_mod
from deckymod.journal import Journal
from deckymod.smapi import StardewEngine

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP_ROOT = os.path.join(_ROOT, ".decky-test-tmp")

UID = "probe.reinstall"

_SAVED_GAME_ID = None


def setUpModule():
    global _SAVED_GAME_ID
    _SAVED_GAME_ID = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    if _SAVED_GAME_ID is not None:
        os.environ["DECKYMOD_GAME_ID"] = _SAVED_GAME_ID
    else:
        os.environ.pop("DECKYMOD_GAME_ID", None)


def _tmpdir(tag):
    os.makedirs(_TMP_ROOT, exist_ok=True)
    base = os.path.join(_TMP_ROOT, "r65_%s_%s" % (tag, uuid.uuid4().hex[:8]))
    os.makedirs(base, exist_ok=False)
    return base


def _version_in(dirpath):
    mp = os.path.join(dirpath, "manifest.json")
    if not os.path.isfile(mp):
        return None
    with open(mp, encoding="utf-8") as f:
        return json.load(f).get("Version")


def _zip(path, version):
    manifest = {
        "Name": "Probe", "Author": "someone", "Version": version,
        "UniqueID": UID, "EntryDll": "Probe.dll", "MinimumApiVersion": "4.0.0",
    }
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Probe/manifest.json", json.dumps(manifest))
        z.writestr("Probe/Probe.dll", b"MZ")
    return path


class _Tree(object):
    def __init__(self):
        self.base = _tmpdir("tree")
        home = os.path.join(self.base, "home")
        xdg = os.path.join(home, ".config")
        self.steam = os.path.join(self.base, "Steam")
        sapps = os.path.join(self.steam, "steamapps")
        self.game = os.path.join(sapps, "common", "Stardew Valley")
        self.mods = os.path.join(self.game, "Mods")
        self.quarantine = os.path.join(self.game, ".decky-quarantine")
        self.data = os.path.join(self.base, "data")
        self.inbox = os.path.join(self.data, "inbox")
        self.logs = os.path.join(self.base, "logs")
        for d in (xdg, sapps, self.game, self.mods, self.inbox, self.data, self.logs):
            os.makedirs(d, exist_ok=True)
        with open(os.path.join(sapps, "libraryfolders.vdf"), "w",
                  encoding="utf-8") as f:
            f.write('"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n'
                    % self.steam.replace("\\", "\\\\"))
        with open(os.path.join(sapps, "appmanifest_413150.acf"), "w",
                  encoding="utf-8") as f:
            f.write('"AppState"\n{\n\t"appid"\t\t"413150"\n'
                    '\t"installdir"\t\t"Stardew Valley"\n'
                    '\t"StateFlags"\t\t"4"\n}\n')
        with open(os.path.join(self.game, "StardewModdingAPI"), "w",
                  encoding="utf-8") as f:
            f.write("#!/bin/sh\n")
        os.makedirs(os.path.join(self.game, "smapi-internal"), exist_ok=True)
        userdata = os.path.join(self.steam, "userdata", "123", "config")
        os.makedirs(userdata, exist_ok=True)
        with open(os.path.join(userdata, "localconfig.vdf"), "w",
                  encoding="utf-8") as f:
            f.write('"UserLocalConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n'
                    '\t\t{\n\t\t\t"Steam"\n\t\t\t{\n\t\t\t\t"apps"\n\t\t\t\t{\n'
                    '\t\t\t\t\t"413150"\n\t\t\t\t\t{\n'
                    '\t\t\t\t\t\t"LaunchOptions"\t\t"\\"%s/StardewModdingAPI\\" '
                    '%%command%%"\n\t\t\t\t\t}\n\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n'
                    % self.game.replace("\\", "\\\\"))
        self._saved = {k: os.environ.get(k) for k in (
            "DECKYMOD_STEAM_ROOT", "DECKY_USER_HOME", "XDG_CONFIG_HOME",
            "DECKYMOD_DATA", "DECKYMOD_INBOX", "DECKY_PLUGIN_LOG_DIR",
            "DECKYMOD_GAME_RUNNING", "DECKYMOD_GAME_ID")}
        os.environ["DECKYMOD_STEAM_ROOT"] = self.steam
        os.environ["DECKY_USER_HOME"] = home
        os.environ["XDG_CONFIG_HOME"] = xdg
        os.environ["DECKYMOD_DATA"] = self.data
        os.environ["DECKYMOD_INBOX"] = self.inbox
        os.environ["DECKY_PLUGIN_LOG_DIR"] = self.logs
        for k in ("DECKYMOD_GAME_RUNNING", "DECKYMOD_GAME_ID"):
            os.environ.pop(k, None)

    def engine(self):
        return StardewEngine(journal=Journal(self.data, self.logs, "stardew"))

    def cleanup(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.base, ignore_errors=True)


class _Base(unittest.TestCase):
    def setUp(self):
        self.t = _Tree()
        self.eng = self.t.engine()
        self.v1 = _zip(os.path.join(self.t.inbox, "v1.zip"), "1.0.0")
        self.v2 = _zip(os.path.join(self.t.inbox, "v2.zip"), "2.0.0")

    def tearDown(self):
        self.t.cleanup()

    def _install(self, path):
        res = self.eng.install(path, after_confirm=True)
        self.assertTrue(res["ok"], res)
        return res

    def _uninstall(self):
        res = self.eng.uninstall(UID, after_confirm=True)
        self.assertTrue(res["ok"], res)
        return res["data"]["txn"]

    def _qdir(self, txn):
        return os.path.join(self.t.quarantine, txn)


class TestItStillWorks(_Base):
    """The plain case must keep working -- a fix that refuses everything would
    pass the refusal tests and break the feature."""

    def test_the_old_version_comes_back(self):
        self._install(self.v1)
        txn = self._uninstall()
        self.assertEqual(os.listdir(self.t.mods), [])
        res = self.eng.rollback(txn)
        self.assertTrue(res["ok"], res)
        self.assertIn(UID, os.listdir(self.t.mods))
        self.assertEqual(_version_in(os.path.join(self.t.mods, UID)), "1.0.0")

    def test_the_quarantine_folder_is_gone_afterwards(self):
        self._install(self.v1)
        txn = self._uninstall()
        self.assertTrue(os.path.isdir(self._qdir(txn)))
        self.eng.rollback(txn)
        self.assertFalse(os.path.isdir(self._qdir(txn)),
                         "the restored copy must not stay behind in the quarantine")
        # Round 65: os.replace leaves the emptied transaction folder behind, and
        # round 54 makes an unreferenced folder in the quarantine an orphan the
        # sweep may report and a user may delete. Round 56 met this on the
        # upgrade path; an undone uninstall met it too.
        self.assertEqual(os.listdir(self.t.quarantine), [],
                         "the emptied transaction folder is litter the sweep counts")


class TestItRefusesWhenItCannot(_Base):

    def test_the_folder_came_back_while_undone(self):
        # The user reinstalled the mod after uninstalling it.
        self._install(self.v1)
        txn = self._uninstall()
        self._install(self.v2)
        res = self.eng.rollback(txn)
        self.assertFalse(res["ok"], "must not claim a restore that did not happen")
        self.assertEqual(res["code"], "E_FILE_COLLISION")
        self.assertIn("already exists again", res["detail"])
        # and it must not have quietly replaced the user's newer version
        self.assertEqual(_version_in(os.path.join(self.t.mods, UID)), "2.0.0")

    def test_the_saved_copy_is_gone(self):
        self._install(self.v1)
        txn = self._uninstall()
        shutil.rmtree(self._qdir(txn), ignore_errors=True)
        res = self.eng.rollback(txn)
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "E_MOD_NOT_FOUND")
        self.assertEqual(os.listdir(self.t.mods), [])

    def test_the_restore_target_is_a_symlink(self):
        """Refused -- but not necessarily by the guard this file is about.

        On the Deck (Linux) a symlinked entry inside ``Mods/`` is caught earlier
        by round 44's structural second-writer check, so the answer there is
        ``E_EXTERNAL_MANAGER``; on Windows the symlink cannot be created at all
        and the case skips. The rollback's own ``E_PATH_INVALID`` is the
        defence-in-depth layer behind that gate. Both are refusals and neither
        may write through the link, which is the property worth pinning; the
        exact code depends on which guard sees it first.
        """
        self._install(self.v1)
        txn = self._uninstall()
        outside = os.path.join(self.t.base, "outside")
        os.makedirs(outside, exist_ok=True)
        if not hasattr(os, "symlink"):
            self.skipTest("no symlink support")
        try:
            os.symlink(outside, os.path.join(self.t.mods, UID))
        except (OSError, NotImplementedError):
            # Windows refuses os.symlink without developer mode (WinError 1314).
            # The refusal still matters -- it runs on the Deck -- so it must be
            # visible as a skip rather than silently absent.
            self.skipTest("symlinks need privileges this platform does not grant")
        res = self.eng.rollback(txn)
        self.assertFalse(res["ok"])
        self.assertIn(res["code"], ("E_PATH_INVALID", "E_EXTERNAL_MANAGER"))
        # nothing may have been written through the link
        self.assertEqual(os.listdir(outside), [])

    def test_a_refused_rollback_does_not_erase_the_transaction(self):
        """A refusal must leave the recovery possible: the saved copy stays, and
        a later rollback (after the user moves the folder away) still works."""
        self._install(self.v1)
        txn = self._uninstall()
        self._install(self.v2)
        self.assertFalse(self.eng.rollback(txn)["ok"])
        self.assertTrue(os.path.isdir(self._qdir(txn)),
                        "the refusal must not delete the only copy")
        shutil.rmtree(os.path.join(self.t.mods, UID))
        res = self.eng.rollback(txn)
        self.assertTrue(res["ok"], res)
        self.assertEqual(_version_in(os.path.join(self.t.mods, UID)), "1.0.0")

    def test_no_event_is_recorded_when_it_refuses(self):
        self._install(self.v1)
        txn = self._uninstall()
        shutil.rmtree(self._qdir(txn), ignore_errors=True)
        self.assertFalse(self.eng.rollback(txn)["ok"])
        events = self.eng.journal.events(txn)
        self.assertFalse([e for e in events if e.get("event") == "MOD_ROLLBACK_RESTORED"])


class TestTheEngineAgrees(_Base):
    """The RimWorld engine had the same line. It also rewrites the game's state
    file, so a silent skip there points the game at a folder that is not there."""

    def test_the_engine_has_the_same_three_refusals(self):
        path = os.path.join(_ROOT, "deckymod", "engine.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        i = src.index("def _rollback_inner")
        body = src[i:]
        cut = body.find("\n    def ", 1)
        body = body if cut < 0 else body[:cut]
        for code in ("E_MOD_NOT_FOUND", "E_PATH_INVALID", "E_FILE_COLLISION"):
            self.assertIn(code, body, code)
        # the old silent guard must be gone from the rollback path
        self.assertNotIn("if os.path.isdir(qdir) and not os.path.isdir(src)", body)


class TestTheShapeCannotComeBack(unittest.TestCase):
    """Both engines must decide *before* recording success, not after."""

    def test_both_engines_check_before_recording(self):
        root = _ROOT
        for mod in ("smapi.py", "engine.py"):
            with open(os.path.join(root, "deckymod", mod), encoding="utf-8") as f:
                src = f.read()
            i = src.index("def _rollback_inner")
            body = src[i:]
            cut = body.find("\n    def ", 1)
            body = body if cut < 0 else body[:cut]
            guard = body.find("E_FILE_COLLISION")
            record = body.find('journal.record("MOD_ROLLBACK_RESTORED"')
            self.assertTrue(guard > 0, mod)
            self.assertTrue(record > 0, mod)
            self.assertLess(guard, record,
                            "%s records the restore before checking it can happen" % mod)


if __name__ == "__main__":
    unittest.main()
