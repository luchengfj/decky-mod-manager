"""Round 27: two copies of the same mod must never end up on disk.

The defect this file locks down was found on the device, not by reasoning: a
hand-installed mod sat at ``Mods/DestroyableBushes`` with UniqueID
``Esca.DestroyableBushes``. Asking the plugin to install the same mod from a
GitHub release unpacked a SECOND folder, ``Mods/esca.destroyablebushes``, and
``status()`` then listed both entries with the same UniqueID. SMAPI loads both,
the player gets two half-configured copies, and criterion 3's "detect file
conflicts" was only ever REPORTED, never enforced.

Why the old code missed it: ``install`` compared the incoming ``dir_name``
against existing DIRECTORY NAMES and against the journal. Neither sees a mod
the user installed by hand under a different folder name.

Everything here is offline: a synthetic Steam library, no network.
"""

import json
import os
import shutil
import unittest
import uuid
import zipfile

import deckymod.smapi as smapi_mod
from deckymod.journal import Journal
from deckymod.manifest import scan_installed_mods
from deckymod.smapi import StardewEngine

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP_ROOT = os.path.join(_ROOT, ".decky-test-tmp")

# tests/test_mvp.py pins DECKYMOD_GAME_ID=rimworld at import time because those
# 33 cases are historical-regression truth for the RimWorld engine. A full
# `unittest discover` imports every module FIRST and runs tests second, so that
# pin is already set by the time our setUp runs. This module exercises the
# Stardew engine, which needs the production descriptor (stardew), so save the
# pin and drop it for the duration of this module.
_PREV_GAME_ID = None


def setUpModule():
    global _PREV_GAME_ID
    _PREV_GAME_ID = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    if _PREV_GAME_ID is not None:
        os.environ["DECKYMOD_GAME_ID"] = _PREV_GAME_ID


def _tmpdir(prefix="r27-"):
    # os.makedirs, not tempfile.mkdtemp: mkdtemp creates 0o700, which the
    # Windows sandbox refuses to let this process write into afterwards.
    base = os.path.join(_TMP_ROOT, prefix + uuid.uuid4().hex[:8])
    os.makedirs(base, exist_ok=True)
    return base


def _manifest(uid, name, version="1.5.2", dll="Mod.dll"):
    return {"Name": name, "Author": "Someone", "Version": version,
            "MinimumApiVersion": "4.0.0", "UniqueID": uid, "EntryDll": dll}


def _zip(path, files, wrapper=None):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr((wrapper + "/" + name) if wrapper else name, data)


LAUNCH_OPTIONS = ('"AppState"\n{\n\t"appid"\t\t"413150"\n\t"LaunchOptions"\t\t'
                  '"\"/home/deck/.steam/steam/steamapps/common/Stardew Valley/'
                  'StardewModdingAPI\" %command%"\n}\n')


class _Tree:
    """Synthetic Steam library with SMAPI present and no pre-existing mods."""

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
        with open(os.path.join(self.game, "StardewModdingAPI"), "wb") as f:
            f.write(b"ELF")
        os.makedirs(os.path.join(self.game, "smapi-internal"), exist_ok=True)
        ud = os.path.join(self.steam, "userdata", "123", "config")
        os.makedirs(ud, exist_ok=True)
        with open(os.path.join(ud, "localconfig.vdf"), "w", encoding="utf-8") as f:
            f.write(LAUNCH_OPTIONS)
        with open(os.path.join(self.sapps, "libraryfolders.vdf"), "w", encoding="utf-8") as f:
            f.write('"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"'
                    + self.steam + '"\n\t}\n}\n')
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
        os.environ.pop("DECKYMOD_GAME_ID", None)

    def cleanup(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def hand_install(self, dir_name, uid, name="Same Mod", version="1.5.2"):
        """A mod the user put there themselves — no journal entry exists."""
        d = os.path.join(self.mods, dir_name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(_manifest(uid, name, version), f)
        with open(os.path.join(d, "Mod.dll"), "wb") as f:
            f.write(b"MZ")
        return d


class _Base(unittest.TestCase):
    def setUp(self):
        self.t = _Tree()
        self.t.env()
        self.eng = StardewEngine(journal=Journal(self.t.data, self.t.logs, "stardew"))
        self.zp = os.path.join(self.t.inbox, "same.zip")

    def tearDown(self):
        self.t.cleanup()


class TestHandInstalledDuplicateIsRefused(_Base):
    def test_install_refuses_when_the_same_unique_id_is_already_on_disk(self):
        # The user already has this mod, installed by hand, as "DestroyableBushes".
        self.t.hand_install("DestroyableBushes", "Esca.DestroyableBushes",
                            name="Destroyable Bushes")
        # Our zip would land in "esca.destroyablebushes" — a different folder.
        _zip(self.zp, {"manifest.json": json.dumps(
            _manifest("Esca.DestroyableBushes", "Destroyable Bushes")),
            "Mod.dll": b"MZ"}, wrapper="DestroyableBushes")

        before = sorted(os.listdir(self.t.mods))
        res = self.eng.install(self.zp, after_confirm=True)

        self.assertFalse(res["ok"], res)
        self.assertEqual(res["code"], "E_DUPLICATE")
        self.assertIn("already on disk", res["detail"])
        self.assertIn("DestroyableBushes", res["detail"])
        self.assertEqual(sorted(os.listdir(self.t.mods)), before,
                         "a refused install must not touch Mods/")

    def test_refusal_happens_before_the_confirm_plan_is_offered(self):
        """The confirm step must not promise an install that install will refuse."""
        self.t.hand_install("DestroyableBushes", "Esca.DestroyableBushes")
        _zip(self.zp, {"manifest.json": json.dumps(
            _manifest("Esca.DestroyableBushes", "Destroyable Bushes")),
            "Mod.dll": b"MZ"}, wrapper="DestroyableBushes")
        plan = self.eng.install(self.zp, after_confirm=False)
        # inspect reports it so the UI can warn before the user even taps install
        ins = self.eng.inspect(self.zp)
        self.assertTrue(ins["ok"], ins)
        self.assertEqual(ins["data"]["conflict"]["same_unique_id_dirs"],
                         ["DestroyableBushes"])
        self.assertEqual(len(os.listdir(self.t.mods)), 1, "no writes in confirm")

    def test_installing_a_different_mod_still_works(self):
        """The guard must not become a blanket refusal."""
        self.t.hand_install("DestroyableBushes", "Esca.DestroyableBushes")
        _zip(self.zp, {"manifest.json": json.dumps(
            _manifest("Other.Mod", "Other Mod")), "Mod.dll": b"MZ"},
            wrapper="Other")
        res = self.eng.install(self.zp, after_confirm=True)
        self.assertTrue(res["ok"], res)
        self.assertIn("other.mod", os.listdir(self.t.mods))

    def test_upgrading_a_parked_mod_keeps_it_parked(self):
        """Round 57, found on the device.

        The previous version of this test asserted the OPPOSITE: it disabled a
        mod, installed the same UniqueID again, and checked that ``Mods/`` held
        the new copy while ``.decky-disabled/`` still held the old one. That is
        the defect, not the contract --
          * a folder in Mods/ IS enabled in this engine (install == enable), so
            the import silently reversed the user's decision to disable it;
          * two copies declaring one UniqueID sat on disk, which SMAPI loads
            both of;
          * ``status().duplicate_ids`` was empty because it scanned Mods/ only;
          * re-enabling then failed with E_FILE_COLLISION, leaving the user
            wedged with a disabled copy they could no longer turn on.

        The rule the engine needs is: the new bytes go where the old bytes are.
        A parked mod stays parked, and only its version changes.
        """
        # Install 1.0.0 through the plugin so the journal owns it, then park it.
        _zip(self.zp, {"manifest.json": json.dumps(
            _manifest("Esca.DestroyableBushes", "Destroyable Bushes",
                      version="1.0.0")),
            "Mod.dll": b"MZ"}, wrapper="DestroyableBushes")
        first = self.eng.install(self.zp, after_confirm=True)
        self.assertTrue(first["ok"], first)
        folder = os.path.basename(first["data"]["dir"])

        d = self.eng.set_enabled(folder, False, after_confirm=True)
        self.assertTrue(d["ok"], d)
        parked = os.path.join(self.t.base, "Steam", "steamapps", "common",
                              "Stardew Valley", ".decky-disabled")
        self.assertEqual(sorted(os.listdir(parked)), [folder])
        self.assertEqual(sorted(os.listdir(self.t.mods)), [])

        _zip(self.zp, {"manifest.json": json.dumps(
            _manifest("Esca.DestroyableBushes", "Destroyable Bushes",
                      version="2.0.0")),
            "Mod.dll": b"MZ"}, wrapper="DestroyableBushes")
        res = self.eng.install(self.zp, after_confirm=True)
        self.assertTrue(res["ok"], res)
        self.assertFalse(res["data"]["enabled"],
                         "installing over a parked mod must not enable it")
        self.assertTrue(res["data"].get("parked"))
        self.assertEqual(os.path.dirname(res["data"]["dir"]), parked,
                         "the new bytes must land where the old bytes were")

        # It stayed parked, with the NEW version, and Mods/ stayed empty.
        self.assertEqual(sorted(os.listdir(self.t.mods)), [],
                         "the upgrade must not appear in Mods/")
        self.assertEqual(sorted(os.listdir(parked)), [folder])

        st = self.eng.status()["data"]["state"]
        self.assertEqual([m["dir"] for m in st["mods"]], [])
        parked_rows = st["disabled_mods"]
        self.assertEqual([m["dir"] for m in parked_rows], [folder])
        self.assertEqual(parked_rows[0]["version"], "2.0.0",
                         "the parked copy must be the version just imported")
        self.assertEqual(st["duplicate_ids"], [],
                         "one copy, one UniqueID -- nothing duplicated")

        # And the user can still turn it on, which the old behaviour made
        # impossible with E_FILE_COLLISION.
        on = self.eng.set_enabled(folder, True, after_confirm=True)
        self.assertTrue(on["ok"], on)
        self.assertEqual(sorted(os.listdir(self.t.mods)), [folder])
        self.assertEqual(sorted(os.listdir(parked)), [])


class TestDuplicateDetectionIsReadOnly(_Base):
    def test_scan_reports_the_collision_it_would_refuse(self):
        """The detector and the enforcement must agree, or the UI lies."""
        self.t.hand_install("DestroyableBushes", "Esca.DestroyableBushes")
        os.makedirs(os.path.join(self.t.mods, "esca.destroyablebushes"), exist_ok=True)
        with open(os.path.join(self.t.mods, "esca.destroyablebushes", "manifest.json"),
                  "w", encoding="utf-8") as f:
            json.dump(_manifest("Esca.DestroyableBushes", "Destroyable Bushes"), f)
        from deckymod.registry import Registry
        mp = Registry().get_game("stardew")["mod_package"]
        scanned = scan_installed_mods(self.t.mods, mp)
        self.assertEqual(len(scanned["duplicate_ids"]), 1)
        uid, dirs = scanned["duplicate_ids"][0]
        self.assertEqual(uid, "esca.destroyablebushes")
        self.assertEqual(sorted(dirs), ["DestroyableBushes", "esca.destroyablebushes"])

    def test_case_insensitive_match(self):
        """UniqueID casing differs between mods; a match must still be a match."""
        self.t.hand_install("SomeDir", "esca.destroyablebushes")
        _zip(self.zp, {"manifest.json": json.dumps(
            _manifest("Esca.DestroyableBushes", "Destroyable Bushes")),
            "Mod.dll": b"MZ"}, wrapper="x")
        res = self.eng.install(self.zp, after_confirm=True)
        self.assertFalse(res["ok"], res)
        self.assertEqual(res["code"], "E_DUPLICATE")


class TestNoFalsePositives(_Base):
    def test_clean_tree_installs_normally(self):
        _zip(self.zp, {"manifest.json": json.dumps(
            _manifest("Fresh.Mod", "Fresh")), "Mod.dll": b"MZ"}, wrapper="Fresh")
        self.assertTrue(self.eng.inspect(self.zp)["data"]["conflict"]["same_unique_id_dirs"] == [])
        res = self.eng.install(self.zp, after_confirm=True)
        self.assertTrue(res["ok"], res)
        self.assertEqual(os.listdir(self.t.mods), ["fresh.mod"])

    def test_unreadable_manifest_does_not_block_installs(self):
        """One broken folder must not make every install fail."""
        broken = os.path.join(self.t.mods, "Broken")
        os.makedirs(broken, exist_ok=True)
        with open(os.path.join(broken, "manifest.json"), "w", encoding="utf-8") as f:
            f.write("{not json")
        _zip(self.zp, {"manifest.json": json.dumps(
            _manifest("Fresh.Mod", "Fresh")), "Mod.dll": b"MZ"}, wrapper="Fresh")
        res = self.eng.install(self.zp, after_confirm=True)
        self.assertTrue(res["ok"], res)


if __name__ == "__main__":
    unittest.main()
