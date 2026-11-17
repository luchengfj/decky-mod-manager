"""Round 58: uninstalling a DISABLED mod must actually remove it.

Found on the device with a synthetic tree: install 1.0.0, disable it (which moves
the folder into ``.decky-disabled/``), then call ``uninstall`` with the directory
name that ``status().state.disabled_mods`` shows. The call returned::

    UNINSTALL_OK      True
    UNINSTALL_CODE    None
    MODS_AFTER        []
    PARKED_AFTER      ['someone.parkuninstall']     # still there
    QUARANTINE_TXNS   ['20261117T185221-0d2dc400']  # a txn was opened
    AFTER_STATUS_DISABLED ['someone.parkuninstall'] # still listed

So the plugin reported a successful uninstall, opened and committed a
transaction, recorded ``MOD_UNINSTALLED``, and moved nothing. ``journal.installed()``
dropped the id while the folder stayed parked -- the plugin forgot a mod it had
not removed, and the panel kept showing it.

Root cause: every lookup in ``_uninstall_inner`` resolved into ``Mods/`` only,
and the execute branch guarded the move with ``if os.path.isdir(src)``. For a
parked source that guard was false, so the move was skipped silently while the
bookkeeping went ahead regardless.

The two requirements this file locks down are therefore:
  * a parked mod IS uninstallable (the panel lists it, so it must work);
  * when the folder cannot be found anywhere, the answer is an error, not a
    success -- a silent no-op that writes MOD_UNINSTALLED is worse than a
    refusal, because it also corrupts the ownership table.
"""

import json
import os
import shutil
import unittest
import uuid
import zipfile

import deckymod.smapi as smapi_mod
from deckymod.journal import Journal
from deckymod.smapi import StardewEngine

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP_ROOT = os.path.join(_ROOT, ".decky-test-tmp")

UID = "someone.parkuninstall"
NAME = "Park Uninstall"

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
    base = os.path.join(_TMP_ROOT, "r58_%s_%s" % (tag, uuid.uuid4().hex[:8]))
    os.makedirs(base, exist_ok=False)
    return base


def _zip(path, version="1.0.0"):
    manifest = {
        "Name": NAME, "Author": "someone", "Version": version,
        "UniqueID": UID, "EntryDll": "ParkUninstall.dll",
        "MinimumApiVersion": "4.0.0",
    }
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("ParkUninstall/manifest.json", json.dumps(manifest))
        z.writestr("ParkUninstall/ParkUninstall.dll", b"MZ")
    return path


class _Tree(object):
    """A synthetic Steam library with SMAPI present, no real game."""

    def __init__(self):
        self.base = _tmpdir("tree")
        home = os.path.join(self.base, "home")
        xdg = os.path.join(home, ".config")
        self.steam = os.path.join(self.base, "Steam")
        sapps = os.path.join(self.steam, "steamapps")
        self.game = os.path.join(sapps, "common", "Stardew Valley")
        self.mods = os.path.join(self.game, "Mods")
        self.parked = os.path.join(self.game, ".decky-disabled")
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


class TestParkedModIsUninstallable(unittest.TestCase):

    def setUp(self):
        self.t = _Tree()
        self.eng = self.t.engine()
        self.zp = _zip(os.path.join(self.t.inbox, "mod.zip"))

    def tearDown(self):
        self.t.cleanup()

    def _install_and_park(self):
        res = self.eng.install(self.zp, after_confirm=True)
        self.assertTrue(res["ok"], res)
        folder = os.path.basename(res["data"]["dir"])
        off = self.eng.set_enabled(folder, False, after_confirm=True)
        self.assertTrue(off["ok"], off)
        self.assertEqual(sorted(os.listdir(self.t.mods)), [])
        self.assertEqual(sorted(os.listdir(self.t.parked)), [folder])
        return folder

    def test_a_parked_mod_can_be_uninstalled(self):
        folder = self._install_and_park()

        u = self.eng.uninstall(folder, after_confirm=True)
        self.assertTrue(u["ok"], u)
        self.assertEqual(sorted(os.listdir(self.t.parked)), [],
                         "the parked folder must actually leave .decky-disabled/")
        self.assertEqual(sorted(os.listdir(self.t.mods)), [])

        st = self.eng.status()["data"]["state"]
        self.assertEqual([m["dir"] for m in st["disabled_mods"]], [],
                         "status must stop listing a mod that is gone")
        self.assertEqual([m["dir"] for m in st["mods"]], [])

    def test_the_uninstalled_parked_folder_really_reaches_the_quarantine(self):
        folder = self._install_and_park()
        u = self.eng.uninstall(folder, after_confirm=True)
        self.assertTrue(u["ok"], u)
        qdir = u["data"]["quarantine"]
        self.assertTrue(os.path.isdir(qdir), qdir)
        self.assertTrue(
            os.path.isfile(os.path.join(qdir, "manifest.json")),
            "the bytes must survive the uninstall, not just the bookkeeping")

    def test_rollback_brings_a_parked_mod_back_where_it_was(self):
        """Undoing the uninstall restores the prior state, and the prior state
        was DISABLED. Rollback reads the recorded from_path, which is now the
        parked location, so the mod comes back parked rather than being dropped
        into Mods/ -- turning it on would silently reverse the user's decision,
        which is the same class of bug as Round 57."""
        folder = self._install_and_park()
        u = self.eng.uninstall(folder, after_confirm=True)
        self.assertTrue(u["ok"], u)
        txn = u["data"]["txn"]

        back = self.eng.rollback(txn)
        self.assertTrue(back["ok"], back)
        self.assertEqual(sorted(os.listdir(self.t.parked)), [folder],
                         "it comes back where it was -- still disabled")
        self.assertEqual(sorted(os.listdir(self.t.mods)), [],
                         "rollback must not enable a mod the user had disabled")

        st = self.eng.status()["data"]["state"]
        self.assertEqual([m["dir"] for m in st["disabled_mods"]], [folder])
        self.assertEqual([m["dir"] for m in st["mods"]], [])

    def test_uninstalling_a_name_that_is_nowhere_is_an_error(self):
        """The silent no-op was the worst part: ok:True plus a MOD_UNINSTALLED
        row that removes the mod from the ownership table while leaving the
        folder on disk."""
        u = self.eng.uninstall("nobody.is.here", after_confirm=True)
        self.assertFalse(u["ok"], u)
        self.assertEqual(u["code"], "E_MOD_NOT_FOUND")
        self.assertTrue(
            not os.path.isdir(self.t.quarantine)
            or os.listdir(self.t.quarantine) == [],
            "a refused uninstall must not open a transaction")


class TestNoSilentSkipInTheSource(unittest.TestCase):
    """A behavioural test cannot reach every guard, so pin the shape too."""

    def test_the_move_is_not_conditional_on_isdir(self):
        import ast
        import io
        path = os.path.join(_ROOT, "deckymod", "smapi.py")
        with io.open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        guarded = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            test = node.test
            if not isinstance(test, ast.Call):
                continue
            if getattr(test.func, "attr", "") != "isdir":
                continue
            body_src = ast.dump(ast.Module(body=node.body, type_ignores=[]))
            if "replace" in body_src and "src" in ast.dump(test):
                guarded.append(node.lineno)
        self.assertEqual(
            guarded, [],
            "os.replace(src, ...) must not sit inside `if os.path.isdir(src):` -- "
            "that is how the uninstall silently did nothing")


if __name__ == "__main__":
    unittest.main()
