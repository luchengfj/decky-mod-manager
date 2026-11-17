"""Synthetic-tree self-tests for selection B (Stardew Valley / SMAPI, detect-only).

STDLIB ONLY, on a Windows dev box AND on SteamOS. These build a FAKE Steam
library under a temp dir and inject it through the documented env overrides
(DECKYMOD_STEAM_ROOT / DECKY_USER_HOME / XDG_CONFIG_HOME / DECKYMOD_INBOX /
DECKYMOD_DATA). No Decky runtime, no network, no real game files, no root, and
no writes outside the temp tree.

Key differences from the RimWorld suite (tests/test_mvp.py):
  * AppID 413150, installdir "Stardew Valley".
  * NO ModsConfig.xml / W1 state file (paths.resolve(..., no_state_file=True)).
  * Mods are DIRECTORIES with a JSON manifest.json (UniqueID/Name/Version).
  * install == enable (file_drop); there is NO separate set_enabled step.
  * .dll/.so/.dylib are ALLOWED for SMAPI; the other 8 forbidden extensions,
    zip-slip, symlink entries, encryption, and zip-bomb guards stay in force.
  * DETECT-ONLY: if a third-party mod manager owns Mods/ (.mm_deployed /
    Mods_Core), every write returns E_EXTERNAL_MANAGER. SMAPI launcher and
    the user's already-set launch options must be present for writes.

Regression pin: these tests DO NOT set DECKYMOD_GAME_ID (production default =
stardew). The RimWorld suite sets DECKYMOD_GAME_ID=rimworld.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main
from deckymod import file_drop, paths
from deckymod.errors import ERRORS
from deckymod.journal import Journal
from deckymod.smapi import StardewEngine

# The RimWorld suite pins DECKYMOD_GAME_ID=rimworld at IMPORT time. unittest
# discovery imports ALL modules first, so a module-level pop here would erase
# that pin before any test runs. Instead we save/pop/restore around THIS module
# only (setUpModule/tearDownModule run at execution time), so both suites can
# share one process without interfering.
_PREV_GAME_ID = None


def setUpModule():
    global _PREV_GAME_ID
    _PREV_GAME_ID = os.environ.pop("DECKYMOD_GAME_ID", None)  # production default = stardew


def tearDownModule():
    if _PREV_GAME_ID is not None:
        os.environ["DECKYMOD_GAME_ID"] = _PREV_GAME_ID
    else:
        os.environ.pop("DECKYMOD_GAME_ID", None)


MANIFEST = {
    "Name": "Test Automate",
    "Author": "Pathoschild",
    "Version": "2.6.1",
    "MinimumApiVersion": "4.1.10",
    "UniqueID": "TestCo.Automate",
    "EntryDll": "Automate.dll",
}
MANIFEST2 = {
    "Name": "Collide Mod",
    "Author": "Someone",
    "Version": "1.0.0",
    "UniqueID": "Other.Collide",
    "EntryDll": "Collide.dll",
}
LAUNCH_OPTIONS = ('"AppState"\n{\n\t"appid"\t\t"413150"\n\t"LaunchOptions"\t\t'
                  '"\"/home/deck/.steam/steam/steamapps/common/Stardew Valley/'
                  'StardewModdingAPI\" %command%"\n}\n')


def _zip(path, files, wrapper=None):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            nm = (wrapper + "/" + name) if wrapper else name
            z.writestr(nm, data)


def _tmpdir(prefix="stardew-mvp-"):
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        ".decky-test-tmp", prefix + os.urandom(6).hex())
    os.makedirs(base, exist_ok=True)
    return base


class StardewTree:
    def __init__(self):
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
        os.makedirs(self.mods, exist_ok=True)
        # SMAPI detection-ONLY markers (we must NEVER install SMAPI)
        with open(os.path.join(self.game, "StardewModdingAPI"), "wb") as f:
            f.write(b"ELF")
        os.makedirs(os.path.join(self.game, "smapi-internal"), exist_ok=True)
        # user's already-set Steam launch options for AppID 413150
        ud = os.path.join(self.steam, "userdata", "123", "config")
        os.makedirs(ud, exist_ok=True)
        with open(os.path.join(ud, "localconfig.vdf"), "w", encoding="utf-8") as f:
            f.write(LAUNCH_OPTIONS)
        # fake Steam library + ACF
        with open(os.path.join(self.sapps, "libraryfolders.vdf"), "w", encoding="utf-8") as f:
            f.write('"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"'
                    + self.steam + '"\n\t\t"apps"\n\t\t{\n\t\t}\n\t}\n}\n')
        with open(os.path.join(self.sapps, "appmanifest_413150.acf"), "w", encoding="utf-8") as f:
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
        for k in ("DECKYMOD_GAME_RUNNING", "DECKYMOD_EXTRA_IMPORT_ROOT", "DECKY_USER"):
            os.environ.pop(k, None)

    def cleanup(self):
        import shutil
        shutil.rmtree(self.base, ignore_errors=True)


class TestStardewRegistry(unittest.TestCase):
    def test_active_is_stardew(self):
        from deckymod.registry import Registry
        r = Registry()
        self.assertEqual(r.active_descriptor()[0], "stardew")
        self.assertEqual(r.appid_for("stardew"), 413150)
        self.assertEqual(r.enabled_games(), ["stardew"])

    def test_error_codes_extended(self):
        import asyncio
        for code in ("E_LOADER_MISSING", "E_LAUNCH_OPTIONS_MISSING",
                     "E_EXTERNAL_MANAGER", "E_MANIFEST_UNSAFE"):
            self.assertIn(code, ERRORS)
        ec = asyncio.run(main.Plugin().error_codes())
        self.assertEqual(ec["data"]["count"], len(ERRORS))


class TestStardewPaths(unittest.TestCase):
    def setUp(self):
        self.t = StardewTree(); self.t.env()

    def tearDown(self):
        self.t.cleanup()

    def test_no_state_file(self):
        r = paths.resolve(413150, preflight=True, no_state_file=True)
        self.assertEqual(r.appid, 413150)
        self.assertEqual(r.install_dir, "Stardew Valley")
        self.assertEqual(r.state_file, "")          # SMAPI has NO ModsConfig.xml
        self.assertFalse(r.flatpak)
        self.assertNotEqual(os.path.commonpath(
            [os.path.realpath(r.staging), os.path.realpath(r.mod_root)]),
            os.path.realpath(r.mod_root))


class TestStardewLifecycle(unittest.TestCase):
    def setUp(self):
        self.t = StardewTree(); self.t.env()
        self.eng = StardewEngine(journal=Journal(self.t.data, self.t.logs, "stardew"))
        self.zp = os.path.join(self.t.inbox, "automate.zip")
        _zip(self.zp, {"manifest.json": json.dumps(MANIFEST),
                       "Automate.dll": b"MZ",
                       "config.json": b"{}"}, wrapper="Automate")

    def tearDown(self):
        self.t.cleanup()

    def test_status_readonly_clean(self):
        st = self.eng.status()
        self.assertTrue(st["ok"])
        self.assertEqual(st["data"]["game"]["appid"], 413150)
        self.assertIsNone(st["data"]["paths"]["w1_state_file"])
        self.assertTrue(st["data"]["state"]["loader_detected"])
        self.assertEqual(st["data"]["state"]["launch_options"], "unknown")
        self.assertFalse(st["data"]["state"]["read_only"])

    def test_inspect_dry_run_dll_allowed(self):
        r = self.eng.inspect(self.zp)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["data"]["mod"]["uniqueId"], "TestCo.Automate")
        self.assertEqual(r["data"]["mod"]["dir_name"], "testco.automate")
        self.assertIn("Automate.dll", r["data"]["mod"]["members"])
        self.assertEqual(len(os.listdir(self.t.mods)), 0)  # no writes

    def test_full_install_uninstall_rollback(self):
        c = self.eng.install(self.zp, after_confirm=False)
        self.assertEqual(c["data"]["phase"], "confirm")
        self.assertEqual(len(os.listdir(self.t.mods)), 0)
        i = self.eng.install(self.zp, after_confirm=True)
        self.assertTrue(i["ok"], i)
        self.assertTrue(i["data"]["enabled"])            # install == enable
        target = os.path.join(self.t.mods, "testco.automate")
        self.assertTrue(os.path.isfile(os.path.join(target, "manifest.json")))
        self.assertTrue(os.path.isfile(os.path.join(target, "Automate.dll")))
        # duplicate guard
        self.assertEqual(self.eng.install(self.zp, after_confirm=False)["code"], "E_DUPLICATE")
        # Round 25: file_drop now has a REAL enable/disable step. Disabling moves
        # the folder out of Mods/ into the sibling .decky-disabled/ (nothing is
        # deleted), and enabling moves it back.
        dc = self.eng.set_enabled("testco.automate", False, after_confirm=False)
        self.assertEqual(dc["data"]["phase"], "confirm")
        self.assertTrue(os.path.isdir(target), "confirm must not move anything")
        d = self.eng.set_enabled("testco.automate", False, after_confirm=True)
        self.assertTrue(d["ok"], d)
        self.assertFalse(d["data"]["enabled"])
        self.assertFalse(os.path.isdir(target), "disabled mod must leave Mods/")
        parked = os.path.join(self.t.game, ".decky-disabled", "testco.automate")
        self.assertTrue(os.path.isdir(parked), "disabled mod must land in .decky-disabled/")
        st = self.eng.status()["data"]
        self.assertEqual([m.get("dir") for m in st["state"]["disabled_mods"]], ["testco.automate"])
        self.assertEqual(st["state"]["mods"], [], "disabled mod is not in state.mods")
        # enable moves it back and restores visibility
        e = self.eng.set_enabled("testco.automate", True, after_confirm=True)
        self.assertTrue(e["ok"], e)
        self.assertTrue(os.path.isdir(target))
        self.assertFalse(os.path.isdir(parked))
        self.assertEqual([m.get("dir") for m in self.eng.status()["data"]["state"]["mods"]],
                         ["testco.automate"])
        # uninstall -> quarantine (not deleted) -> rollback restores
        uc = self.eng.uninstall("TestCo.Automate", after_confirm=False)
        self.assertEqual(uc["data"]["phase"], "confirm")
        u = self.eng.uninstall("TestCo.Automate", after_confirm=True)
        self.assertTrue(u["ok"], u)
        self.assertFalse(os.path.isdir(target))
        self.assertTrue(os.path.isdir(u["data"]["quarantine"]))
        rb = self.eng.rollback(u["data"]["txn"])
        self.assertTrue(rb["ok"], rb)
        self.assertTrue(os.path.isdir(target))
        self.assertEqual(self.eng.recovery()["data"]["pending"], [])

    def test_forbidden_exe_still_blocked(self):
        bad = os.path.join(self.t.inbox, "bad.exe.zip")
        _zip(bad, {"manifest.json": json.dumps(MANIFEST), "run.exe": b"MZ"})
        self.assertEqual(self.eng.inspect(bad)["code"], "E_UNSAFE_ENTRY")

    def test_path_escape(self):
        outside = os.path.join(self.t.base, "outside.zip")
        _zip(outside, {"manifest.json": json.dumps(MANIFEST)})
        self.assertEqual(self.eng.inspect(outside)["code"], "E_PATH_ESCAPE")

    def test_bad_archive(self):
        bad = os.path.join(self.t.inbox, "bad.zip")
        with open(bad, "wb") as f:
            f.write(b"not a zip")
        self.assertEqual(self.eng.inspect(bad)["code"], "E_BAD_ARCHIVE")

    def test_external_manager_is_readonly(self):
        with open(os.path.join(self.t.mods, ".mm_deployed"), "wb") as f:
            f.write(b"")
        st = self.eng.status()
        self.assertTrue(st["data"]["state"]["external_manager"])
        self.assertTrue(st["data"]["state"]["read_only"])
        checks = [
            self.eng.install(self.zp, after_confirm=True),
            self.eng.uninstall("TestCo.Automate", after_confirm=True),
            self.eng.rollback("no-such-txn"),
        ]
        for got in checks:
            self.assertEqual(got["code"], "E_EXTERNAL_MANAGER", got)
        self.assertEqual(len(os.listdir(self.t.mods)), 1)  # only .mm_deployed

    def test_loader_missing_blocks_writes(self):
        os.remove(os.path.join(self.t.game, "StardewModdingAPI"))
        import shutil
        shutil.rmtree(os.path.join(self.t.game, "smapi-internal"), ignore_errors=True)
        got = self.eng.install(self.zp, after_confirm=True)
        self.assertEqual(got["code"], "E_LOADER_MISSING")

    def test_game_running_guard(self):
        os.environ["DECKYMOD_GAME_RUNNING"] = "1"
        try:
            self.assertEqual(self.eng.install(self.zp, after_confirm=True)["code"],
                             "E_GAME_RUNNING")
        finally:
            os.environ.pop("DECKYMOD_GAME_RUNNING", None)


class TestStardewPluginRPC(unittest.TestCase):
    def setUp(self):
        self.t = StardewTree(); self.t.env()

    def tearDown(self):
        self.t.cleanup()

    def test_plugin_dispatches_to_stardew(self):
        import asyncio
        p = main.Plugin()
        asyncio.run(p._main())
        self.assertIsInstance(p._engine(), StardewEngine)
        st = asyncio.run(p.status())
        self.assertTrue(st["ok"], st)
        self.assertEqual(st["data"]["game"]["appid"], 413150)


class TestLoaderLogInStatus(unittest.TestCase):
    """The point of Round 40 is that status() TELLS you what loaded.

    unit-testing deckymod/loaderlog.py alone would not prove the wiring: the
    plugin could parse a log perfectly and never put the result in the envelope.
    These tests go through Engine.status(), which is what the panel actually reads.
    """

    LOG = (
        "[18:42:08 INFO  SMAPI] Loaded 2 mods:\n"
        "[18:42:08 INFO  SMAPI]    Test Automate 2.6.1 by Pathoschild | automates things\n"
        "[18:42:08 INFO  SMAPI]    Collide Mod 1.0.0 by Someone | collides\n"
        "[18:42:08 INFO  SMAPI] Loaded 0 content packs:\n"
        "[18:42:08 ERROR SMAPI]    Skipped mods\n"
        "[18:42:08 ERROR SMAPI]       - Broken Thing 1.0.0 because it requires mods which"
        " aren't installed (Missing.Dep).\n"
    )

    def setUp(self):
        self.t = StardewTree(); self.t.env()
        self.eng = StardewEngine(journal=Journal(self.t.data, self.t.logs, "stardew"))
        self.logdir = os.path.join(self.t.home, ".config", "StardewValley", "ErrorLogs")
        os.makedirs(self.logdir, exist_ok=True)
        self.logfile = os.path.join(self.logdir, "SMAPI-latest.txt")

    def tearDown(self):
        self.t.cleanup()

    def _install(self, uid, name):
        zp = os.path.join(self.t.inbox, uid.replace(".", "_") + ".zip")
        _zip(zp, {"manifest.json": json.dumps({
            "Name": name, "Author": "x", "Version": "1.0.0",
            "UniqueID": uid, "EntryDll": uid.split(".")[-1] + ".dll"}),
            "x.dll": b"MZ"}, wrapper=uid.replace(".", "_"))
        self.eng.install(zp, after_confirm=True)

    def test_no_log_yet_is_reported_not_failed(self):
        st = self.eng.status()
        self.assertTrue(st["ok"], "a missing log must never fail status()")
        block = st["data"]["loader_log"]
        self.assertFalse(block["available"])
        self.assertEqual(block["reason"], "log_missing")
        # and the plain on-disk view still works
        self.assertEqual(st["data"]["state"]["mods"], [])

    def test_loaded_mod_is_marked_loaded(self):
        self._install("TestCo.Automate", "Test Automate")
        with open(self.logfile, "w", encoding="utf-8") as f:
            f.write(self.LOG)
        st = self.eng.status()["data"]
        mod = st["state"]["mods"][0]
        self.assertEqual(mod["load_status"], "loaded")
        self.assertEqual(mod["load_version"], "2.6.1")
        self.assertEqual(st["loader_log"]["loaded"], 2)

    def test_installed_but_absent_from_log_is_unknown(self):
        """The whole feature: 'in Mods/' must not silently look like 'working'."""
        self._install("Ghost.Absent", "Ghost Absent")
        with open(self.logfile, "w", encoding="utf-8") as f:
            f.write(self.LOG)
        mod = self.eng.status()["data"]["state"]["mods"][0]
        self.assertEqual(mod["load_status"], "unknown")
        self.assertIn("not listed", mod["load_note"])

    def test_skipped_mod_surfaces_its_missing_dependency(self):
        self._install("Broken.Thing", "Broken Thing")
        with open(self.logfile, "w", encoding="utf-8") as f:
            f.write(self.LOG)
        mod = self.eng.status()["data"]["state"]["mods"][0]
        self.assertEqual(mod["load_status"], "skipped")
        self.assertIn("Missing.Dep", mod["load_missing_ids"])

    def test_parked_mod_is_not_annotated_as_unknown(self):
        """A disabled mod is absent from the log BY CONSTRUCTION.

        Reporting it as 'unknown' would look like a fault when it is the user's
        own choice, so disabled_mods keep the plain on-disk shape.
        """
        self._install("TestCo.Automate", "Test Automate")
        self.eng.set_enabled("TestCo.Automate", False, after_confirm=True)
        with open(self.logfile, "w", encoding="utf-8") as f:
            f.write(self.LOG)
        st = self.eng.status()["data"]
        parked = st["state"]["disabled_mods"][0]
        self.assertNotIn("load_status", parked)
        self.assertEqual(st["state"]["mods"], [])

    def test_corrupt_log_degrades_to_a_reason(self):
        with open(self.logfile, "wb") as f:
            f.write(b"\xff\xfe\x00 not text\n")
        st = self.eng.status()
        self.assertTrue(st["ok"], "an unreadable log must not fail status()")
        self.assertFalse(st["data"]["loader_log"]["available"])

    def test_giant_log_is_capped(self):
        with open(self.logfile, "w", encoding="utf-8") as f:
            f.write(self.LOG)
            f.write("[18:42:09 TRACE SMAPI] padding\n" * 40000)
        st = self.eng.status()
        self.assertTrue(st["ok"])
        self.assertTrue(st["data"]["loader_log"]["available"])



if __name__ == "__main__":
    unittest.main()
