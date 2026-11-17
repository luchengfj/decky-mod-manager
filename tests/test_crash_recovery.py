"""Round 68: an interrupted install must put the old copy back.

`_install_inner` moves the previous copy into the transaction's quarantine
folder (step 3) and only then unpacks the new one (step 4). A crash between the
two -- OOM kill, sleep/resume, power -- leaves the mod ABSENT and the user's
only copy inside `<quarantine>/<txn>/<dir>.replaced`, with the journal holding
nothing but PREPARED/APPLYING.

Measured on the device before this round:

    CRASH_STATE_MODS          []
    CRASH_STATE_Q             ["probe.crashy.replaced"]
    BLOCKED_CODE              E_RECOVERY_PENDING      (correct)
    ROLLBACK_OK               True
    DATA                      {"recovered": true, ...}
    MOD_BACK_AFTER_ROLLBACK   False                    <-- the defect
    QUARANTINE                state "orphan", restorable false

So the write gate was right, the listing was right, and the recovery step
answered "recovered" while the mod stayed missing -- and then classified the
copy it had failed to use as an orphan, which reclaim_quarantine may delete.

Two properties are pinned here:

1. recovery restores the copy (or refuses honestly, never a hollow "recovered");
2. the audit agrees with the rollback about the same folder.
"""
import json
import os
import shutil
import unittest
import zipfile

from deckymod import quarantine
from deckymod.smapi import FileDropEngine

from tests.test_parked_uninstall import _Tree  # reuse the synthetic tree


def _manifest(version):
    return json.dumps({"Name": "Crashy", "Author": "probe", "Version": version,
                       "UniqueID": "probe.crashy", "EntryDll": "Mine.dll"}, indent=2)


class _Base(unittest.TestCase):
    def setUp(self):
        self.t = _Tree()
        self.eng = self.t.engine()

    def tearDown(self):
        self.t.cleanup()

    def _zip(self, version, name=None):
        path = os.path.join(self.t.inbox, name or ("m-%s.zip" % version))
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("Mine/Mine.dll", b"MZ")
            zf.writestr("Mine/manifest.json", _manifest(version))
        return path

    def _live(self):
        return os.path.join(self.t.mods, "probe.crashy")

    def _quarantine_of(self, txn):
        return os.path.join(self.t.quarantine, txn)

    def _interrupt_upgrade(self):
        """Install 1.0.0, then forge the crash window of a 2.0.0 install."""
        self.eng.install(self._zip("1.0.0"), after_confirm=True)
        self.assertTrue(os.path.isdir(self._live()))
        txn = "20260101T120000-crash068"
        j = self.eng.journal
        j.begin(txn, "install", {"op": "install", "packageId": "probe.crashy",
                                 "to": self._live()})
        j.applying(txn)
        qdir = self._quarantine_of(txn)
        os.makedirs(qdir, exist_ok=True)
        os.replace(self._live(), os.path.join(qdir, "probe.crashy.replaced"))
        self.assertFalse(os.path.isdir(self._live()), "the crash window leaves it absent")
        return txn


class TestAnInterruptedInstallCanBeUndone(_Base):
    def test_the_old_version_comes_back(self):
        txn = self._interrupt_upgrade()
        out = self.eng.rollback(txn)
        self.assertTrue(out["ok"], out)
        self.assertTrue(out["data"].get("recovered"))
        self.assertTrue(os.path.isdir(self._live()), "the mod must be back on disk")
        self.assertEqual(self.eng.status()["data"]["state"]["mods"][0]["version"], "1.0.0")

    def test_it_says_what_it_restored(self):
        txn = self._interrupt_upgrade()
        out = self.eng.rollback(txn)
        self.assertIn("restored_from", out["data"])
        self.assertTrue(out["data"]["restored_from"].endswith("probe.crashy.replaced"))

    def test_the_transaction_folder_is_cleaned_up(self):
        txn = self._interrupt_upgrade()
        self.eng.rollback(txn)
        self.assertFalse(os.path.exists(self._quarantine_of(txn)),
                         "an emptied transaction folder is litter (round 54)")

    def test_a_second_recovery_is_refused_not_faked(self):
        txn = self._interrupt_upgrade()
        self.assertTrue(self.eng.rollback(txn)["ok"])
        again = self.eng.rollback(txn)
        self.assertFalse(again["ok"])
        self.assertEqual(again["code"], "E_UNKNOWN")
        self.assertIn("already rolled back", again["detail"])

    def test_nothing_to_restore_still_answers_honestly(self):
        """No displaced copy at all (crash before the first rename)."""
        self.eng.install(self._zip("1.0.0"), after_confirm=True)
        txn = "20260101T120000-crash069"
        j = self.eng.journal
        j.begin(txn, "install", {"op": "install", "packageId": "probe.crashy",
                                 "to": self._live()})
        j.applying(txn)
        out = self.eng.rollback(txn)
        self.assertTrue(out["ok"])
        self.assertTrue(out["data"].get("recovered"))
        self.assertNotIn("restored_from", out["data"])
        self.assertTrue(os.path.isdir(self._live()), "and the live copy is untouched")


class TestTheAuditAgreesWithTheRollback(_Base):
    def test_a_displaced_copy_is_restorable_not_an_orphan(self):
        txn = self._interrupt_upgrade()
        seen = quarantine.survey(self.t.quarantine, self.eng.journal)
        entry = next((e for e in seen["entries"] if e["txn"] == txn), None)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["state"], quarantine.RESTORABLE, entry)
        self.assertFalse(entry["restorable"] is False)
        self.assertEqual(seen["orphans"], 0)

    def test_a_plain_install_creates_nothing_to_restore(self):
        txn = self.eng.install(self._zip("1.0.0"), after_confirm=True)["data"]["txn"]
        seen = quarantine.survey(self.t.quarantine, self.eng.journal)
        entry = next((e for e in seen["entries"] if e["txn"] == txn), None)
        self.assertIsNone(entry, "no replacement means no quarantine folder at all")


class TestTheTwoFactsComeFromOneRecord(unittest.TestCase):
    """Structural: both answers read the journal, and both read the same field."""

    def test_the_audit_counts_replaced_old(self):
        import io
        src = io.open(quarantine.__file__.replace(".pyc", ".py"), encoding="utf-8").read()
        self.assertIn('r.get("replaced_old")', src)
        self.assertIn('event == "MOD_UNINSTALLED"', src)

    def test_the_rollback_looks_for_the_same_suffix(self):
        import io
        p = os.path.join(os.path.dirname(quarantine.__file__), "smapi.py")
        src = io.open(p, encoding="utf-8").read()
        self.assertIn('.replaced")', src)
        self.assertIn("_replaced_copy_for", src)
        # exactly one place builds that path prefix, so it cannot disagree
        self.assertEqual(src.count("endswith(\".replaced\")"), 1)


if __name__ == "__main__":
    unittest.main()
