"""Round 70: a restore must record what is on disk, not what the journal remembered.

Measured on the device (probe ``r70d_registry_probe.py``) before the fix:

    A_INSTALLED   [{"packageId": "probe.alpha", "version": "1.0.0", ...}]
    (the folder's contents are then replaced by a different mod, probe.beta 9.0.0)
    C_UNINSTALL   True  ->  quarantine
    C_ROLLBACK    {"ok": true}
    D_UID_ON_DISK probe.beta        D_VERSION_ON_DISK 9.0.0
    D_INSTALLED   [{"packageId": "probe.alpha", "version": null, ...}]
    D_ROWS        [{"dir": "probe.alpha", "uniqueId": "probe.beta", "version": "9.0.0"}]

Two answers disagreed about one folder: the journal said ``probe.alpha`` was
installed (with no version at all) while the scanner read ``probe.beta 9.0.0``
from the same directory. ``data.installed`` is what the panel renders, so the
UI named a mod that was not on disk.

The cause: the rollback branches moved a folder back by PATH and then recorded
the identity the journal remembered. A path is not a mod. The same shape gave
an upgrade rollback a row with ``version: null``, because
``mod={"name": pid, "dir": dir}`` carried no version either.

So every restore now asks the restored folder who it is, and a folder holding
somebody else is not adopted under the old id (round 21's ownership rule).
"""
import io
import json
import os
import unittest

from deckymod.journal import Journal
from deckymod.smapi import StardewEngine
from tests.test_stardew import StardewTree
from tests.test_upgrade import _make_stardew_zip

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SAVED_GAME_ID = None


def setUpModule():
    # tests/test_mvp.py pins DECKYMOD_GAME_ID=rimworld at import time and
    # discovery imports every module before running any of them. Rounds 47 / 50 /
    # 61 each lost a round to this; tests/test_import_order.py pins the rule.
    global _SAVED_GAME_ID
    _SAVED_GAME_ID = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    if _SAVED_GAME_ID is not None:
        os.environ["DECKYMOD_GAME_ID"] = _SAVED_GAME_ID


class _Base(object):
    def setUp(self):
        self._saved_env = {k: os.environ.get(k) for k in
                           ("DECKYMOD_GAME_ID", "DECKY_USER_HOME", "XDG_CONFIG_HOME",
                            "DECKYMOD_INBOX", "DECKYMOD_DATA", "DECKY_PLUGIN_LOG_DIR",
                            "DECKYMOD_STEAM_ROOT", "DECKY_PLUGIN_RUNTIME_DIR",
                            "DECKYMOD_GAME_RUNNING")}
        self.addCleanup(self._restore_env)
        self.t = StardewTree()
        self.addCleanup(self.t.cleanup)
        self.t.env()
        data = os.path.join(self.t.data, "d")
        os.makedirs(data, exist_ok=True)
        self.eng = StardewEngine(journal=Journal(data, self.t.logs, "stardew"))
        self.uid = "probe.alpha"
        self.other = "probe.beta"

    def _restore_env(self):
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _zip(self, uid, version):
        p = os.path.join(self.t.inbox, "%s-%s.zip" % (uid, version))
        _make_stardew_zip(p, uid, version)
        return p

    def _install(self, uid, version):
        res = self.eng.install(self._zip(uid, version), after_confirm=True)
        self.assertTrue(res["ok"], res)
        return res

    def _swap_contents(self, folder, uid, version):
        """Replace the folder's contents with a different mod, by hand."""
        import shutil
        path = os.path.join(self.t.mods, folder)
        shutil.rmtree(path)
        os.makedirs(path)
        with io.open(os.path.join(path, "manifest.json"), "w",
                     encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"Name": "Beta", "Author": "someone",
                                "Version": version, "UniqueID": uid,
                                "EntryDll": "Beta.dll"}))
        with io.open(os.path.join(path, "Beta.dll"), "wb") as f:
            f.write(b"MZ")

    def _owned(self):
        return self.eng.journal.installed()

    def _reported(self):
        return self.eng.status()["data"].get("installed") or []


class TestARestoreRecordsWhatIsActuallyThere(_Base, unittest.TestCase):
    def test_a_swapped_folder_is_not_registered_as_the_old_mod(self):
        self._install(self.uid, "1.0.0")
        self._swap_contents(self.uid, self.other, "9.0.0")
        un = self.eng.uninstall(self.uid, after_confirm=True)
        self.assertTrue(un["ok"], un)
        rb = self.eng.rollback(un["data"]["txn"])
        self.assertTrue(rb["ok"], rb)

        owned = self._owned()
        self.assertNotIn(self.uid, owned,
                         "the folder came back holding %s; the journal must not "
                         "claim %s is installed: %r" % (self.other, self.uid, owned))

    def test_the_panel_list_does_not_name_a_mod_that_is_absent(self):
        self._install(self.uid, "1.0.0")
        self._swap_contents(self.uid, self.other, "9.0.0")
        un = self.eng.uninstall(self.uid, after_confirm=True)
        self.eng.rollback(un["data"]["txn"])

        reported = self._reported()
        ids = [str(m.get("packageId") or "").lower() for m in reported]
        self.assertNotIn(self.uid.lower(), ids,
                         "data.installed is what the panel renders: %r" % (reported,))
        # And the scanner still tells the truth about the folder itself.
        rows = self.eng.status()["data"]["state"]["mods"]
        mine = [m for m in rows if m.get("dir") == self.uid]
        self.assertEqual(len(mine), 1, rows)
        self.assertEqual(mine[0]["uniqueId"], self.other, mine)
        self.assertEqual(mine[0]["version"], "9.0.0", mine)

    def test_the_answer_says_the_folder_holds_something_else(self):
        self._install(self.uid, "1.0.0")
        self._swap_contents(self.uid, self.other, "9.0.0")
        un = self.eng.uninstall(self.uid, after_confirm=True)
        rb = self.eng.rollback(un["data"]["txn"])

        data = rb.get("data") or {}
        self.assertEqual(data.get("restored"), self.uid, data)
        self.assertEqual(data.get("expected_uid"), self.uid, data)
        self.assertEqual(data.get("restored_uid"), self.other, data)
        self.assertIn("note", data, data)
        self.assertIn(self.other, data["note"], data)

    def test_a_normal_restore_still_registers_the_mod_with_its_version(self):
        self._install(self.uid, "1.0.0")
        un = self.eng.uninstall(self.uid, after_confirm=True)
        rb = self.eng.rollback(un["data"]["txn"])
        self.assertTrue(rb["ok"], rb)

        owned = self._owned()
        self.assertIn(self.uid, owned, owned)
        self.assertEqual(owned[self.uid]["version"], "1.0.0", owned[self.uid])
        self.assertTrue(owned[self.uid]["enabled"], owned[self.uid])
        self.assertEqual((rb.get("data") or {}).get("restored_uid"), self.uid, rb)

    def test_an_upgrade_rollback_reports_the_version_that_came_back(self):
        """The same shape, one branch over: no version at all was recorded."""
        self._install(self.uid, "1.0.0")
        self._install(self.uid, "2.0.0")
        txn = [r.get("txn") for r in self.eng.journal.read_all()
               if r.get("event") == "MOD_INSTALLED"][-1]
        rb = self.eng.rollback(txn)
        self.assertTrue(rb["ok"], rb)

        owned = self._owned()
        self.assertIn(self.uid, owned, owned)
        self.assertEqual(owned[self.uid]["version"], "1.0.0",
                         "the restored row must name the version on disk: %r"
                         % (owned[self.uid],))


class TestOnePlaceAsksTheDisk(_Base, unittest.TestCase):
    def _src(self):
        p = os.path.join(_REPO, "deckymod", "smapi.py")
        with io.open(p, encoding="utf-8") as f:
            return f.read()

    def test_the_helper_exists_once(self):
        src = self._src()
        self.assertEqual(src.count("def _read_dir_identity(self"), 1)
        self.assertEqual(src.count("self._read_dir_identity("), 3,
                         "every restore branch asks the folder: uninstall, "
                         "upgrade and the interrupted install")

    def test_no_branch_records_a_remembered_identity_for_a_restore(self):
        src = self._src()
        # The pre-fix literals: a name taken from the journal instead of disk.
        self.assertNotIn('mod={"name": pid, "dir": src}', src)
        self.assertNotIn('mod={"name": inst.get("packageId"), "dir": inst.get("dir")}', src)

    def test_the_helper_reads_a_manifest_and_writes_nothing(self):
        src = self._src()
        i = src.index("def _read_dir_identity(self")
        body = src[i:src.index("    def ", i + 10)]
        self.assertIn("manifest._find_manifest_in_dir(", body)
        self.assertIn("parser.parse(", body)
        # A read helper that writes is how a status() call starts changing the
        # disk. The list is the same one tests/test_lifecycle_hooks.py bans.
        for banned in ("os.remove", "os.unlink", "shutil.rmtree", "os.makedirs",
                       "os.replace", "os.rename", "os.chmod", "os.symlink"):
            self.assertNotIn(banned, body, "a read helper must not write: " + banned)


if __name__ == "__main__":
    unittest.main()
