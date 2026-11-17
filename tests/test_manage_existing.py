"""Round 20: managing (uninstalling) mods that this plugin did NOT install.

Motivation, in the user's own words: the goal is
``能实现下载MOD，一键安装MOD，然后能够一键导入MOD，管理MOD``. Download / one-click
install / one-click import were already proven on the device in earlier rounds.
"Manage" however was half-missing: ``uninstall`` consulted only the journal
(``journal.installed()``), so the user's 27 pre-existing mod directories could be
LISTED in ``status.state.mods`` but never removed -- each attempt returned
``E_DUPLICATE: <id> is not installed/managed``.

This module proves the Round 20 relaxation and, just as importantly, that it did
not weaken anything:

* a plain pre-existing directory can be quarantined and restored;
* traversal, absolute paths, hidden names, symlinks, files-not-directories and
  nested paths are all refused;
* the read-only posture still wins over the new path;
* a journal-managed mod still goes through the original branch;
* the frontend surfaces the button only when writes are allowed.

Everything here is offline: synthetic Steam tree, no network, no real game.
"""

import json
import os
import unittest

from deckymod.journal import Journal
from deckymod.smapi import StardewEngine

from tests.test_stardew import MANIFEST, StardewTree, _zip

# This module must exercise the PRODUCTION descriptor (stardew). tests/test_mvp.py
# pins DECKYMOD_GAME_ID=rimworld at import time to keep the 33 historical RimWorld
# cases intact, and `unittest discover` imports every module before running any of
# them, so without this the engine would resolve RimWorld 294100 and every case
# here would fail with E_GAME_NOT_FOUND. Same idiom as tests/test_stardew.py.
_PREV_GAME_ID = None


def setUpModule():
    global _PREV_GAME_ID
    _PREV_GAME_ID = os.environ.pop("DECKYMOD_GAME_ID", None)  # production default = stardew


def tearDownModule():
    if _PREV_GAME_ID is not None:
        os.environ["DECKYMOD_GAME_ID"] = _PREV_GAME_ID
    else:
        os.environ.pop("DECKYMOD_GAME_ID", None)



def _plain_mod(mods_dir, dir_name, manifest=None):
    """Create a minimal but valid mod directory directly on disk."""
    d = os.path.join(mods_dir, dir_name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest or MANIFEST, f)
    with open(os.path.join(d, "something.dll"), "wb") as f:
        f.write(b"MZ")
    return d


class _Base(unittest.TestCase):
    def setUp(self):
        self.t = StardewTree()
        self.t.env()
        self.eng = StardewEngine(journal=Journal(self.t.data, self.t.logs, "stardew"))

    def tearDown(self):
        self.t.cleanup()


class TestExistingModUninstall(_Base):
    def test_preexisting_directory_is_listed_then_removable(self):
        """The whole point: it shows up in status, and now it can be uninstalled."""
        d = _plain_mod(self.t.mods, "some.preinstalled.mod")
        st = self.eng.status()
        self.assertTrue(st["ok"], st)
        listed = [m["dir"] for m in st["data"]["state"]["mods"]]
        self.assertIn("some.preinstalled.mod", listed)
        # It is NOT journal-managed: nothing was installed by this plugin.
        self.assertEqual(self.eng.journal.installed(), {})

        confirm = self.eng.uninstall("some.preinstalled.mod", after_confirm=False)
        self.assertTrue(confirm["ok"], confirm)
        self.assertEqual(confirm["data"]["phase"], "confirm")
        self.assertTrue(os.path.isdir(d), "confirm phase must not touch the disk")
        self.assertFalse(confirm["data"]["plan"]["previously_managed"])

        done = self.eng.uninstall("some.preinstalled.mod", after_confirm=True)
        self.assertTrue(done["ok"], done)
        self.assertFalse(os.path.isdir(d), "directory must be gone from Mods/")
        self.assertTrue(os.path.isdir(done["data"]["quarantine"]), "moved, not deleted")
        self.assertIn("some.preinstalled.mod", done["data"]["quarantine"])

        rb = self.eng.rollback(done["data"]["txn"])
        self.assertTrue(rb["ok"], rb)
        self.assertTrue(os.path.isdir(d), "rollback restores the folder")
        self.assertEqual(self.eng.recovery()["data"]["pending"], [])

    def test_journal_managed_mods_still_use_the_original_branch(self):
        """A plugin-installed mod keeps previously_managed=True."""
        zp = os.path.join(self.t.inbox, "automate.zip")
        _zip(zp, {"manifest.json": json.dumps(MANIFEST),
                  "Automate.dll": b"MZ"}, wrapper="Automate")
        self.assertTrue(self.eng.install(zp, after_confirm=True)["ok"])
        confirm = self.eng.uninstall("TestCo.Automate", after_confirm=False)
        self.assertTrue(confirm["ok"], confirm)
        self.assertTrue(confirm["data"]["plan"]["previously_managed"])
        self.assertEqual(confirm["data"]["plan"]["packageId"], "TestCo.Automate")

    def test_second_rollback_of_the_same_txn_is_refused(self):
        """Found on the device: rolling back twice used to report success twice."""
        zp = os.path.join(self.t.inbox, "automate.zip")
        _zip(zp, {"manifest.json": json.dumps(MANIFEST),
                  "Automate.dll": b"MZ"}, wrapper="Automate")
        self.assertTrue(self.eng.install(zp, after_confirm=True)["ok"])
        u = self.eng.uninstall("TestCo.Automate", after_confirm=True)
        self.assertTrue(u["ok"], u)
        first = self.eng.rollback(u["data"]["txn"])
        self.assertTrue(first["ok"], first)
        second = self.eng.rollback(u["data"]["txn"])
        self.assertFalse(second["ok"], "a repeat rollback must not claim success")
        self.assertIn("already rolled back", second["detail"])

    def test_rollback_of_an_unmanaged_uninstall_does_not_claim_ownership(self):
        """Found on the device: undoing the removal of a pre-existing mod used to
        add it to journal.installed(), so the plugin started reporting a mod the
        user installed themselves as one it manages. Rolling the folder back must
        restore the FOLDER only, never the ownership record."""
        mods = self.t.mods
        _plain_mod(mods, "PreExisting")
        before = self.eng.status()
        self.assertEqual(before["data"]["installed"], [])
        u = self.eng.uninstall("PreExisting", after_confirm=True)
        self.assertTrue(u["ok"], u)
        rb = self.eng.rollback(u["data"]["txn"])
        self.assertTrue(rb["ok"], rb)
        self.assertTrue(os.path.isdir(os.path.join(mods, "PreExisting")),
                        "the folder must come back")
        after = self.eng.status()
        self.assertEqual(after["data"]["installed"], [],
                         "rollback must not turn a user-owned mod into a managed one")
        self.assertIn("PreExisting", [m.get("dir") for m in after["data"]["state"]["mods"]],
                      "it is still visible as a detected mod")

    def test_uninstalling_by_directory_name_clears_the_journal_entry(self):
        """Found on the device: the UI passes the DIRECTORY name while the journal
        is keyed by UniqueID. Without the round-20 fix, MOD_UNINSTALLED was written
        under the directory name and a stale record survived forever."""
        zp = os.path.join(self.t.inbox, "automate.zip")
        _zip(zp, {"manifest.json": json.dumps(MANIFEST),
                  "Automate.dll": b"MZ"}, wrapper="Automate")
        self.assertTrue(self.eng.install(zp, after_confirm=True)["ok"])
        self.assertIn("TestCo.Automate", self.eng.journal.installed())
        dir_name = MANIFEST["UniqueID"].lower()
        got = self.eng.uninstall(dir_name, after_confirm=True)   # directory name, not the id
        self.assertTrue(got["ok"], got)
        self.assertEqual(got["data"]["packageId"], "TestCo.Automate",
                         "events must be recorded under the journal's own key")
        self.assertEqual(self.eng.journal.installed(), {},
                         "no stale entry may survive an uninstall")

    def test_unknown_name_still_reports_the_original_error(self):
        got = self.eng.uninstall("no.such.mod", after_confirm=False)
        self.assertFalse(got["ok"])
        self.assertEqual(got["code"], "E_DUPLICATE")
        self.assertIn("not installed/managed", got["detail"])


class TestExistingModRefusals(_Base):
    """Every shape that must NOT be treated as a removable mod directory."""

    def _assert_refused(self, name):
        got = self.eng.uninstall(name, after_confirm=False)
        self.assertFalse(got["ok"], f"{name!r} must be refused, got {got}")
        self.assertEqual(got["code"], "E_DUPLICATE", got)

    def test_traversal_is_refused(self):
        for name in ("..", "../etc", "../../home/deck", "a/../b", "a/b"):
            self._assert_refused(name)

    def test_absolute_path_is_refused(self):
        outside = os.path.join(self.t.base, "outside-mod")
        os.makedirs(outside, exist_ok=True)
        self._assert_refused(outside)
        self._assert_refused("/home/deck")

    def test_hidden_and_dotted_names_are_refused(self):
        _plain_mod(self.t.mods, ".hidden.mod")
        self._assert_refused(".hidden.mod")
        self._assert_refused(".")
        self._assert_refused("")

    def test_symlink_is_refused(self):
        outside = os.path.join(self.t.base, "outside-target")
        os.makedirs(outside, exist_ok=True)
        link = os.path.join(self.t.mods, "linked.mod")
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable on this platform")
        # Round 44: the layout gate now sees a symlinked entry inside Mods/ and
        # refuses the WHOLE write surface with E_EXTERNAL_MANAGER, before the
        # per-directory resolver can answer E_DUPLICATE. That is the more honest
        # answer: one symlinked entry means somebody else deployed this tree, and
        # the plugin should stop rather than pick off single names in it.
        got = self.eng.uninstall("linked.mod", after_confirm=False)
        self.assertFalse(got["ok"], got)
        self.assertIn(got["code"], ("E_DUPLICATE", "E_EXTERNAL_MANAGER"), got)
        if got["code"] == "E_EXTERNAL_MANAGER":
            self.assertIn("symlink", got["detail"])
        self.assertTrue(os.path.isdir(outside), "target must be untouched")

    def test_a_file_is_not_a_directory(self):
        with open(os.path.join(self.t.mods, "stray.txt"), "w", encoding="utf-8") as f:
            f.write("x")
        self._assert_refused("stray.txt")

    def test_nested_directory_name_is_refused(self):
        deep = os.path.join(self.t.mods, "parent.mod", "child.mod")
        os.makedirs(deep, exist_ok=True)
        self._assert_refused("child.mod")           # not directly under Mods/
        self._assert_refused("parent.mod/child.mod")

    def test_read_only_posture_still_wins(self):
        d = _plain_mod(self.t.mods, "blocked.mod")
        with open(os.path.join(self.t.mods, ".mm_deployed"), "wb") as f:
            f.write(b"")
        try:
            got = self.eng.uninstall("blocked.mod", after_confirm=True)
            self.assertEqual(got["code"], "E_EXTERNAL_MANAGER", got)
            self.assertTrue(os.path.isdir(d), "read-only must never move anything")
        finally:
            os.remove(os.path.join(self.t.mods, ".mm_deployed"))

    def test_game_running_still_blocks(self):
        d = _plain_mod(self.t.mods, "busy.mod")
        os.environ["DECKYMOD_GAME_RUNNING"] = "1"
        try:
            got = self.eng.uninstall("busy.mod", after_confirm=True)
            self.assertEqual(got["code"], "E_GAME_RUNNING", got)
            self.assertTrue(os.path.isdir(d))
        finally:
            os.environ.pop("DECKYMOD_GAME_RUNNING", None)


class TestFrontendOffersTheButton(unittest.TestCase):
    """Static proof that the UI can reach the new capability."""

    def setUp(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "src", "index.tsx"), encoding="utf-8") as f:
            self.src = f.read()

    def test_detected_mod_detail_offers_uninstall(self):
        self.assertIn("doUninstallDir", self.src)
        self.assertIn("BTN_UNINSTALL", self.src)
        # offered only when the engine reports a writable file_drop tree
        self.assertIn("const canRemove = fd && !readOnly;", self.src)

    def test_button_and_confirmation_are_fully_localized(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in ("en.json", "zh-CN.json"):
            with open(os.path.join(root, "src", "i18n", name), encoding="utf-8") as f:
                d = json.load(f)
            for key in ("BTN_UNINSTALL", "CONFIRM_UNINSTALL", "UNINSTALL_OK"):
                self.assertIn(key, d, f"{name} is missing {key}")
                self.assertTrue(d[key].strip(), f"{name}:{key} must not be empty")

    def test_backend_still_has_no_path_shaped_uninstall_rpc(self):
        """The RPC signature stays a single positional string; no paths leak in."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "main.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("async def uninstall(self, package_id: str, after_confirm: bool = False)",
                      src)


if __name__ == "__main__":
    unittest.main()
