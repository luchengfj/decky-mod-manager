"""Round 52: the two things a first-time user hits before anything works.

Both defects were found on the device, in a synthetic tree, by asking what
happens to somebody who has never installed a mod:

1. F1 -- a game that has never had a mod installed has no ``Mods/`` folder.
   ``os.replace(staged, target)`` fails with ENOENT when the PARENT of the
   target does not exist, so the very first install on a fresh game failed with
   ``E_OP_FAILED`` and a detail naming the staging path. That reads like a
   plugin bug, and it is the one failure a new user is guaranteed to meet.

2. F2 -- "not found" was answered with ``E_DUPLICATE``, whose user-facing
   message is "already installed, use Replace". The opposite of what happened.
   It was reachable from three operations (uninstall / disable / enable) with
   any mistyped name.

Neither test sets DECKYMOD_GAME_ID, so both run against the production default
(stardew). The RimWorld suite pins rimworld at import time; discovery imports
every module before running any of them, so the pop has to happen in
setUpModule, not at module level.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deckymod.errors import ERRORS
from deckymod.journal import Journal
from deckymod.smapi import StardewEngine

_PREV_GAME_ID = None


def setUpModule():
    global _PREV_GAME_ID
    _PREV_GAME_ID = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    if _PREV_GAME_ID is not None:
        os.environ["DECKYMOD_GAME_ID"] = _PREV_GAME_ID
    else:
        os.environ.pop("DECKYMOD_GAME_ID", None)


def _tmpdir(prefix="r52-"):
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        ".decky-test-tmp", prefix + os.urandom(6).hex())
    os.makedirs(base, exist_ok=True)
    return base


MANIFEST = {
    "Name": "First Mod",
    "Author": "Someone",
    "Version": "1.0.0",
    "MinimumApiVersion": "4.0.0",
    "UniqueID": "someone.first",
    "EntryDll": "First.dll",
}
LAUNCH_OPTIONS = (
    '"AppState"\n{\n\t"appid"\t\t"413150"\n\t"LaunchOptions"\t\t'
    '"\"/home/deck/.steam/steam/steamapps/common/Stardew Valley/'
    'StardewModdingAPI\" %command%"\n}\n'
)


class _Tree:
    """A Stardew tree where ``Mods/`` is deliberately NOT created."""

    def __init__(self, with_mods=False):
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
        self.game = os.path.join(self.sapps, "common", "Stardew Valley")
        self.mods = os.path.join(self.game, "Mods")
        os.makedirs(self.game, exist_ok=True)
        if with_mods:
            os.makedirs(self.mods, exist_ok=True)
        # loader markers so the write gate is happy (we never install SMAPI)
        with open(os.path.join(self.game, "StardewModdingAPI"), "wb") as f:
            f.write(b"ELF")
        os.makedirs(os.path.join(self.game, "smapi-internal"), exist_ok=True)
        ud = os.path.join(self.steam, "userdata", "123", "config")
        os.makedirs(ud, exist_ok=True)
        with open(os.path.join(ud, "localconfig.vdf"), "w", encoding="utf-8") as f:
            f.write(LAUNCH_OPTIONS)
        with open(os.path.join(self.sapps, "libraryfolders.vdf"), "w",
                  encoding="utf-8") as f:
            f.write('"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"'
                    + self.steam + '"\n\t\t"apps"\n\t\t{\n\t\t}\n\t}\n}\n')
        with open(os.path.join(self.sapps, "appmanifest_413150.acf"), "w",
                  encoding="utf-8") as f:
            f.write('"AppState"\n{\n\t"appid"\t\t"413150"\n\t"installdir"\t\t'
                    '"Stardew Valley"\n\t"name"\t\t"Stardew Valley"\n}\n')

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
        for k in ("DECKYMOD_GAME_RUNNING", "DECKYMOD_EXTRA_IMPORT_ROOT",
                  "DECKY_USER"):
            os.environ.pop(k, None)

    def cleanup(self):
        import shutil
        shutil.rmtree(self.base, ignore_errors=True)


def _mod_zip(path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("First/manifest.json", json.dumps(MANIFEST))
        z.writestr("First/First.dll", b"MZ")


class TestFirstInstallOnAFreshGame(unittest.TestCase):
    """A game that has never had a mod installed has no Mods/ folder at all."""

    def setUp(self):
        self.t = _Tree(with_mods=False)
        self.t.env()
        self.eng = StardewEngine(journal=Journal(self.t.data, self.t.logs, "stardew"))
        self.zp = os.path.join(self.t.inbox, "first.zip")
        _mod_zip(self.zp)

    def tearDown(self):
        self.t.cleanup()

    def test_mods_folder_does_not_exist_before_the_first_install(self):
        self.assertFalse(os.path.isdir(self.t.mods),
                         "the fixture must start with no Mods/ folder")

    def test_first_install_creates_mods_and_succeeds(self):
        got = self.eng.install(self.zp, after_confirm=True)
        self.assertTrue(got["ok"], got)
        self.assertEqual(got["data"]["packageId"], "someone.first")

    def test_first_install_leaves_a_real_mod_directory(self):
        self.eng.install(self.zp, after_confirm=True)
        landed = os.path.join(self.t.mods, "someone.first")
        self.assertTrue(os.path.isdir(landed), landed)
        self.assertTrue(os.path.isfile(os.path.join(landed, "manifest.json")))

    def test_the_installed_mod_is_then_visible_and_removable(self):
        self.eng.install(self.zp, after_confirm=True)
        st = self.eng.status()
        self.assertTrue(st["ok"], st)
        dirs = [m.get("dir") for m in st["data"]["state"]["mods"]]
        self.assertIn("someone.first", dirs, st["data"]["state"]["mods"])
        gone = self.eng.uninstall("someone.first", after_confirm=True)
        self.assertTrue(gone["ok"], gone)
        self.assertFalse(os.path.isdir(os.path.join(self.t.mods, "someone.first")))

    def test_dry_run_still_writes_nothing_on_a_fresh_game(self):
        before = sorted(os.listdir(self.t.game))
        got = self.eng.install(self.zp, after_confirm=False)
        self.assertTrue(got["ok"], got)
        self.assertEqual(got["data"]["phase"], "confirm")
        self.assertEqual(sorted(os.listdir(self.t.game)), before,
                         "confirm phase must not create anything")


class TestNotInstalledIsItsOwnAnswer(unittest.TestCase):
    """E_DUPLICATE means "already installed". Not-found must not borrow it."""

    def setUp(self):
        self.t = _Tree(with_mods=True)
        self.t.env()
        self.eng = StardewEngine(journal=Journal(self.t.data, self.t.logs, "stardew"))

    def tearDown(self):
        self.t.cleanup()

    def test_the_code_exists_and_says_not_found(self):
        category, message, rollback = ERRORS["E_MOD_NOT_FOUND"]
        self.assertEqual(category, "discovery")
        self.assertIn("No installed mod", message)
        self.assertFalse(rollback)

    def test_error_codes_rpc_reports_it(self):
        import asyncio
        import main as plugin_main
        ec = asyncio.run(plugin_main.Plugin().error_codes())
        codes = [row["code"] for row in ec["data"]["codes"]]
        self.assertIn("E_MOD_NOT_FOUND", codes)
        self.assertEqual(ec["data"]["count"], len(ERRORS))

    def test_uninstall_of_an_unknown_name(self):
        got = self.eng.uninstall("nobody.at.all", after_confirm=False)
        self.assertFalse(got["ok"], got)
        self.assertEqual(got["code"], "E_MOD_NOT_FOUND", got)
        self.assertIn("not installed/managed", got["detail"])

    def test_disable_of_an_unknown_name(self):
        got = self.eng.set_enabled("nobody.at.all", False, after_confirm=False)
        self.assertFalse(got["ok"], got)
        self.assertEqual(got["code"], "E_MOD_NOT_FOUND", got)

    def test_enable_of_something_never_parked(self):
        got = self.eng.set_enabled("nobody.at.all", True, after_confirm=False)
        self.assertFalse(got["ok"], got)
        self.assertEqual(got["code"], "E_MOD_NOT_FOUND", got)
        self.assertIn("not disabled", got["detail"])

    def test_a_real_mod_still_reports_duplicate_when_installed_twice(self):
        # The duplicate answer belongs to the CONFIRM phase: at that point the
        # caller asked "install this" without having been told yet that a
        # managed copy exists, so E_DUPLICATE is exactly right. With
        # after_confirm=True the same call is a deliberate replace, which is
        # also correct. Both are real E_DUPLICATE uses; neither is not-found.
        zp = os.path.join(self.t.inbox, "first.zip")
        _mod_zip(zp)
        self.assertTrue(self.eng.install(zp, after_confirm=True)["ok"])
        again = self.eng.install(zp, after_confirm=False)
        self.assertFalse(again["ok"], again)
        self.assertEqual(again["code"], "E_DUPLICATE", again)

    def test_the_two_answers_are_told_apart(self):
        zp = os.path.join(self.t.inbox, "first.zip")
        _mod_zip(zp)
        self.eng.install(zp, after_confirm=True)
        dup = self.eng.install(zp, after_confirm=False)
        missing = self.eng.uninstall("nobody.at.all", after_confirm=False)
        self.assertEqual(dup["code"], "E_DUPLICATE")
        self.assertEqual(missing["code"], "E_MOD_NOT_FOUND")
        self.assertNotEqual(dup["code"], missing["code"])
        self.assertNotEqual(dup["message"], missing["message"],
                            "the two messages must not say the same thing")


class TestRimworldEngineUsesItToo(unittest.TestCase):
    """The RimWorld engine had the same wrong code in two places."""

    def test_engine_py_never_raises_duplicate_for_not_found(self):
        import ast
        import io
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "deckymod", "engine.py")
        with io.open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        bad = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or node.exc is None:
                continue
            call = node.exc
            if not isinstance(call, ast.Call) or not call.args:
                continue
            first = call.args[0]
            if not (isinstance(first, ast.Constant) and first.value == "E_DUPLICATE"):
                continue
            detail = ""
            for kw in call.keywords:
                if kw.arg == "detail" and isinstance(kw.value, ast.JoinedStr):
                    detail = "".join(
                        str(p.value) for p in kw.value.values
                        if isinstance(p, ast.Constant))
            if "not installed" in detail or "not managed" in detail:
                bad.append((node.lineno, detail))
        self.assertEqual(bad, [], "E_DUPLICATE must not mean not-found: %r" % (bad,))


if __name__ == "__main__":
    unittest.main()
