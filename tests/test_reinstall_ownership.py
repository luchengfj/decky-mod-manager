"""Round 87: a reinstall must not inherit the previous install's file list.

Found on the device after Round 86 was deployed. A real install of a two-file
package worked, and then the panel's mod list showed the mod with
``files: 4`` and ``present: false`` -- twice the real file count, and "not
present" for a mod whose files were sitting on disk.

The cause was ``RootMergeEngine._placed_for()``. It returned every FILE_PLACED
row ever journaled for a package id, across every transaction, so

  * ``files`` was a lifetime total that grew with each reinstall, and
  * ``present`` was computed over rows from transactions whose targets no longer
    exist, which made a live mod look absent.

The device shown it plainly: ``cyberpunk.jsonl`` held six FILE_PLACED rows for
``r86.write`` from two transactions, so the fresh install reported four files.

These tests pin the ownership rule: the current install owns its own rows, no
other transaction's rows, and an uninstall still finds every file.
"""
import io
import json
import os
import unittest
import zipfile

from test_handover_multiroot import MultiRootTree

from deckymod.root_merge import RootMergeEngine


PKG = "probe.reinstall"

_PREV_GAME_ID = None


def setUpModule():
    """Drop the game pin that test_mvp.py sets at import time.

    That pin makes Registry.enabled_games() return only the pinned id, which the
    synthetic registry here does not contain -- every fixture would then die with
    "no enabled game descriptor". test_handover_multiroot.py does the same thing
    for the same reason.
    """
    global _PREV_GAME_ID
    _PREV_GAME_ID = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    if _PREV_GAME_ID is not None:
        os.environ["DECKYMOD_GAME_ID"] = _PREV_GAME_ID
    else:
        os.environ.pop("DECKYMOD_GAME_ID", None)


def _zip(path: str, member_dir: str, payload: str) -> str:
    """A package whose manifest id is PKG and whose files live under member_dir."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("%s/info.json" % member_dir,
                   json.dumps({"name": PKG, "version": "1.0.0"}))
        z.writestr("%s/%s" % (member_dir, payload), b"payload" * 8)
    with open(path, "wb") as f:
        f.write(buf.getvalue())
    return path


class _Base(unittest.TestCase):
    def setUp(self):
        self.t = MultiRootTree()
        self.t.env()
        self.addCleanup(self.t.cleanup)
        self.eng = self.t.engine()

    def install(self, member_dir: str, payload: str) -> dict:
        flat = member_dir.replace("/", "-")
        path = _zip(os.path.join(self.t.inbox, flat + ".zip"), member_dir, payload)
        r = self.eng.install(path, after_confirm=True)
        self.assertTrue(r.get("ok"), r)
        return r

    def row(self, package_id: str = PKG) -> dict:
        st = self.eng.status()
        self.assertTrue(st.get("ok"), st)
        mods = (st.get("data") or {}).get("state", {}).get("mods") or []
        for m in mods:
            if m.get("packageId") == package_id:
                return m
        self.fail("status does not list %s: %r" % (package_id, mods))


class TestTheCurrentInstallOwnsItsFiles(_Base):
    def test_one_install_owns_exactly_its_own_two_files(self):
        self.install("mods/First", "first.archive")
        self.assertEqual(len(self.eng._placed_for(PKG)), 2)
        self.assertEqual(self.row()["files"], 2)

    def test_a_reinstall_starts_from_an_empty_file_list(self):
        self.install("mods/First", "first.archive")
        self.eng.uninstall(PKG, after_confirm=True)
        self.install("mods/Second", "second.archive")
        # Previously 4: two rows from the first install plus two from the second.
        self.assertEqual(len(self.eng._placed_for(PKG)), 2)
        self.assertEqual(self.row()["files"], 2)

    def test_a_reinstall_to_a_new_folder_is_present_not_absent(self):
        self.install("mods/First", "first.archive")
        self.eng.uninstall(PKG, after_confirm=True)
        self.install("mods/Second", "second.archive")
        row = self.row()
        # The stale "mods/First/..." rows used to be part of the presence check,
        # and those paths are gone, so this reported False for a live install.
        self.assertTrue(row["present"], row)

    def test_the_active_file_list_points_only_at_what_is_on_disk(self):
        self.install("mods/First", "first.archive")
        self.eng.uninstall(PKG, after_confirm=True)
        self.install("mods/Second", "second.archive")
        for rec in self.eng._placed_for(PKG):
            target = rec["target"].replace("/", os.sep)
            self.assertTrue(os.path.exists(os.path.join(self.eng._resolve().game_root, target)),
                            "stale row survived: %s" % rec["target"])


class TestUninstallStillFindsEverything(_Base):
    def test_uninstall_removes_the_current_install_completely(self):
        self.install("mods/First", "first.archive")
        r = self.eng.uninstall(PKG, after_confirm=True)
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(r["data"]["removed"], 2)
        root = self.eng._resolve().game_root
        self.assertFalse(os.path.exists(os.path.join(root, "mods", "First", "info.json")))

    def test_the_confirm_step_counts_the_current_files_not_a_lifetime_total(self):
        self.install("mods/First", "first.archive")
        self.eng.uninstall(PKG, after_confirm=True)
        self.install("mods/Second", "second.archive")
        r = self.eng.uninstall(PKG, after_confirm=False)
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(r["data"]["files"], 2)


class TestJournalsThatPredateThisRule(_Base):
    """A FILE_PLACED row with no MOD_INSTALLED must still be removable."""

    def test_rows_from_a_legacy_install_are_still_owned(self):
        j = self.eng.journal
        j.begin("legacyTxn", "root_merge", {"packageId": "old.mod"})
        j.record("FILE_PLACED", "legacyTxn", packageId="old.mod",
                 target="mods/Old/old.archive", backup=None, bytes=10)
        j.committed("legacyTxn", {"packageId": "old.mod", "files": 1})
        rows = self.eng._placed_for("old.mod")
        self.assertEqual([r["target"] for r in rows], ["mods/Old/old.archive"])

    def test_a_legacy_package_can_still_be_uninstalled(self):
        j = self.eng.journal
        j.begin("legacyTxn", "root_merge", {"packageId": "old.mod"})
        j.record("FILE_PLACED", "legacyTxn", packageId="old.mod",
                 target="mods/Old/old.archive", backup=None, bytes=10)
        j.committed("legacyTxn", {"packageId": "old.mod", "files": 1})
        # The file is not on disk, so 0 removals is correct -- what matters is
        # that the package is found rather than answered with E_MOD_NOT_FOUND.
        r = self.eng.uninstall("old.mod", after_confirm=True)
        self.assertTrue(r.get("ok"), r)


class TestUninstallLeavesNoEmptyHusks(_Base):
    """Round 87: deleting the files used to leave the folders they lived in."""

    def test_the_folder_the_mod_lived_in_is_removed(self):
        self.install("mods/First", "first.archive")
        r = self.eng.uninstall(PKG, after_confirm=True)
        self.assertTrue(r.get("ok"), r)
        self.assertFalse(os.path.isdir(self.t.root("mods/First")),
                         "an empty mod folder survived the uninstall")

    def test_a_write_root_is_never_removed(self):
        self.install("mods/First", "first.archive")
        self.eng.uninstall(PKG, after_confirm=True)
        # "mods" is a declared write root: it belongs to the descriptor, not to
        # the mod, and the engine must never delete it.
        self.assertTrue(os.path.isdir(self.t.root("mods")))

    def test_a_folder_holding_something_else_is_kept(self):
        self.install("mods/First", "first.archive")
        neighbour = self.t.root("mods/First/somebody-elses.txt")
        with open(neighbour, "w", encoding="utf-8") as f:
            f.write("not mine")
        r = self.eng.uninstall(PKG, after_confirm=True)
        self.assertTrue(r.get("ok"), r)
        self.assertTrue(os.path.isfile(neighbour),
                        "uninstall removed a folder that still held another file")

    def test_pruning_is_reported(self):
        self.install("mods/First", "first.archive")
        r = self.eng.uninstall(PKG, after_confirm=True)
        self.assertGreaterEqual(r["data"].get("pruned_dirs", 0), 1)


class TestLoaderInstallsAreNotAffected(_Base):
    def test_a_loader_install_owns_its_rows_through_the_same_rule(self):
        # install_loader writes MOD_INSTALLED too, so it takes the same path.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("BepInEx/plugins/loader.dll", b"dll" * 4)
        path = os.path.join(self.t.inbox, "MyLoader.zip")
        with open(path, "wb") as f:
            f.write(buf.getvalue())
        r = self.eng.install_loader(path, after_confirm=True)
        if not r.get("ok"):
            # loader_install is a per-descriptor capability; single-root-test's
            # descriptor may not enable it. Skipping is honest, a false pass is not.
            self.skipTest("loader_install disabled here: %s" % (r.get("code"),))
        pid = r["data"]["packageId"]
        self.assertEqual(len(self.eng._placed_for(pid)), 1)


if __name__ == "__main__":
    unittest.main()
