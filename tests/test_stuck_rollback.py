"""Round 72: E_ROLLBACK_FAILED must not be a dead end.

Measured on the device before the fix (probe ``r72_rollback_failed_probe.py``,
12/12): an upgrade whose commit failed AND whose automatic restore also failed
produced

    B_INSTALL2 {"ok": false, "code": "E_ROLLBACK_FAILED", ...}
    D_RECOVERY_DATA {"pending": []}                  <- not listed
    E_QUARANTINE_ENTRY [{"state": "restorable", "restorable": true, ...}]
    F_ROLLBACK {"ok": false, "code": "E_UNKNOWN",
                "detail": "nothing to roll back for txn ... (state=ROLLBACK_FAILED)"}

Three surfaces disagreed. The error message tells the user their data is
preserved and points at the log; ``errors.py`` marks the code
``rollback_available=True``; the audit calls the folder restorable -- and the
one API that could undo the transaction answered "nothing to roll back". The
old version stayed in the quarantine with no supported way to get it back.

The cause was set membership: every restore branch in ``_rollback_inner``
listed PREPARED / APPLYING / COMMITTED / ROLLED_BACK, and ROLLBACK_FAILED was
in none of them -- so a transaction whose rollback *failed* was less
recoverable than one that was merely interrupted.

Two kinds of test here:

* behaviour -- build the state a stuck upgrade leaves on disk (2.0.0 live,
  1.0.0 in ``<quarantine>/<txn>/<dir>.replaced``, journal says ROLLBACK_FAILED)
  and check that rollback now restores it, that recovery() lists it, that the
  audit protects the folder, and that it does not block other writes.
* shape -- the two branches that can restore it both have to accept the state,
  and ``stuck()`` must not be folded into the write gate.
"""
import io
import json
import os
import shutil
import unittest

from deckymod.journal import Journal
from deckymod.smapi import StardewEngine
from tests.test_stardew import StardewTree
from tests.test_upgrade import _make_stardew_zip

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENV_KEYS = (
    "DECKYMOD_GAME_ID", "DECKY_USER_HOME", "DECKYMOD_STEAM_ROOT",
    "XDG_CONFIG_HOME", "DECKYMOD_INBOX", "DECKYMOD_DATA", "DECKYMOD_LOG_DIR",
    "DECKYMOD_GAME_RUNNING",
)
_TXN = "20260101T000000-stuck001"

_SAVED_GAME_ID = None


def setUpModule():
    # tests/test_mvp.py pins DECKYMOD_GAME_ID=rimworld at import time and
    # discovery imports every module before running any of them, so the pin has
    # to be lifted at run time. tests/test_import_order.py enforces this shape.
    global _SAVED_GAME_ID
    _SAVED_GAME_ID = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    if _SAVED_GAME_ID is not None:
        os.environ["DECKYMOD_GAME_ID"] = _SAVED_GAME_ID


class _Base(object):
    def setUp(self):
        self._saved_env = {k: os.environ.get(k) for k in _ENV_KEYS}
        self.addCleanup(self._restore_env)
        self.t = StardewTree()
        self.addCleanup(self.t.cleanup)
        self.t.env()
        data = os.path.join(self.t.data, "d")
        os.makedirs(data, exist_ok=True)
        self.eng = StardewEngine(journal=Journal(data, self.t.logs, "stardew"))
        self.uid = "probe.stuck"

    def _restore_env(self):
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _manifest_version(self, base=None, uid=None):
        man = os.path.join(base or self.t.mods, uid or self.uid, "manifest.json")
        with io.open(man, encoding="utf-8") as f:
            return json.loads(f.read())["Version"]

    def _stage(self, version, uid=None):
        """Unpack a fresh copy of the mod into a scratch dir and return it."""
        uid = uid or self.uid
        p = os.path.join(self.t.inbox, "Stuck-%s-%s.zip" % (uid, version))
        _make_stardew_zip(p, uid, version)
        dest = os.path.join(self.t.data, "stage-%s-%s" % (uid, version))
        shutil.rmtree(dest, ignore_errors=True)
        os.makedirs(dest, exist_ok=True)
        import zipfile
        with zipfile.ZipFile(p) as z:
            z.extractall(dest)
        # _make_stardew_zip wraps the mod in "MyMod/", so the payload is not
        # named after the UniqueID. Find the directory that actually holds the
        # manifest instead of assuming a name.
        for name in sorted(os.listdir(dest)):
            inner = os.path.join(dest, name)
            if os.path.isfile(os.path.join(inner, "manifest.json")):
                return inner
        raise AssertionError("no manifest under %s: %s" % (dest, os.listdir(dest)))

    def _make_stuck(self):
        """Build exactly what a stuck upgrade leaves behind, byte for byte.

        Doing it by hand rather than by failing a live install keeps the state
        unambiguous: this is the disk layout the probe measured, not a
        simulation of the code that produces it.
        """
        journal = self.eng.journal
        r = self.eng._resolve()
        target = os.path.join(r.mod_root, self.uid)
        os.makedirs(r.mod_root, exist_ok=True)

        # the live copy is the NEW version
        shutil.copytree(self._stage("2.0.0"), target, dirs_exist_ok=True)
        # the old version sits in the transaction's quarantine, named `.replaced`
        qdir = os.path.join(r.quarantine_root, _TXN)
        os.makedirs(qdir, exist_ok=True)
        old = os.path.join(qdir, self.uid + ".replaced")
        shutil.copytree(self._stage("1.0.0"), old, dirs_exist_ok=True)
        # the journal records the install and then the failed rollback
        journal.begin(_TXN, "install",
                      {"packageId": self.uid, "name": "Stuck Probe",
                       "version": "2.0.0", "to": target})
        journal.applying(_TXN)
        journal.record("MOD_INSTALLED", _TXN, packageId=self.uid,
                       name="Stuck Probe", version="2.0.0", dir=target,
                       replaced_old=old)
        journal.rollback_failed(_TXN, {"reason": "no space left on device"})
        return _TXN


class TestAFailedRollbackCanStillBeUndone(_Base, unittest.TestCase):
    def test_the_old_version_comes_back(self):
        txn = self._make_stuck()
        self.assertEqual(self._manifest_version(), "2.0.0", "precondition")

        got = self.eng.rollback(txn)

        self.assertTrue(got["ok"], got)
        self.assertEqual(self._manifest_version(), "1.0.0",
                         "the retry must put the old version back")

    def test_it_says_what_it_restored(self):
        txn = self._make_stuck()
        got = self.eng.rollback(txn)
        self.assertTrue(got["ok"], got)
        self.assertEqual(got["data"]["restored"], self.uid, got)
        self.assertIn("restored_from", got["data"], got)

    def test_the_quarantine_folder_is_gone_afterwards(self):
        txn = self._make_stuck()
        qdir = os.path.join(self.eng._resolve().quarantine_root, txn)
        self.assertTrue(os.path.isdir(qdir), "precondition")
        self.assertTrue(self.eng.rollback(txn)["ok"])
        self.assertFalse(os.path.exists(qdir),
                         "a finished transaction must not leave an empty folder "
                         "behind for the audit to count")

    def test_a_second_attempt_is_refused_not_faked(self):
        txn = self._make_stuck()
        self.assertTrue(self.eng.rollback(txn)["ok"])
        again = self.eng.rollback(txn)
        self.assertFalse(again["ok"], again)
        self.assertEqual(self._manifest_version(), "1.0.0")


class TestTheUserCanSeeIt(_Base, unittest.TestCase):
    def test_recovery_lists_the_stuck_transaction(self):
        txn = self._make_stuck()
        got = self.eng.recovery()
        self.assertTrue(got["ok"], got)
        self.assertIn(txn, got["data"]["stuck"],
                      "a stuck rollback must be visible somewhere; before this "
                      "round it was in no list at all")
        self.assertNotIn(txn, got["data"]["pending"],
                         "stuck is not the write gate")

    def test_a_stuck_transaction_does_not_block_other_writes(self):
        self._make_stuck()
        other = os.path.join(self.t.inbox, "Unrelated.zip")
        _make_stardew_zip(other, "probe.unrelated", "1.0.0")
        got = self.eng.install(other, after_confirm=True)
        self.assertTrue(got["ok"], got)

    def test_the_audit_does_not_offer_the_folder_as_litter(self):
        txn = self._make_stuck()
        q = self.eng.status()["data"]["state"]["quarantine"]
        rows = {e["txn"]: e for e in q.get("entries") or []}
        self.assertIn(txn, rows, rows)
        self.assertTrue(rows[txn]["restorable"],
                        "the folder holds the only copy of the old version, so "
                        "reclaim_quarantine must not be invited to delete it")


class TestTheShapeCannotRegress(unittest.TestCase):
    def _source(self, name):
        with io.open(os.path.join(_REPO, "deckymod", name), encoding="utf-8") as f:
            return f.read()

    def test_both_restore_branches_accept_a_failed_rollback(self):
        src = self._source("smapi.py")
        start = src.index("    def _rollback_inner(")
        body = src[start:src.rindex("nothing to roll back for txn")]
        # ROLLBACK_FAILED has its OWN branch now (patch4): folding it into the
        # PREPARED/APPLYING branch made a stuck transaction with no displaced
        # copy fall into that branch's "nothing displaced -> mark recovered"
        # fallback and answer ok(recovered=True) -- the Round 68 lie again.
        self.assertIn('"ROLLED_BACK", "ROLLBACK_FAILED"', body,
                      "the committed-upgrade branch must accept a failed "
                      "rollback: the replacement is on disk and the old copy "
                      "is still in the quarantine")
        self.assertIn('if state == "ROLLBACK_FAILED":', body,
                      "the stuck case needs its own branch so it can refuse "
                      "honestly when there is nothing to put back")
        self.assertNotIn('"PREPARED", "APPLYING", "ROLLBACK_FAILED"', body,
                         "a stuck transaction must not share the interrupted "
                         "branch's optimistic fallback")
        self.assertIn("there is no copy left to restore", body,
                      "and it must say why, naming the quarantine folder")

    def test_stuck_is_not_the_write_gate(self):
        src = self._source("journal.py")
        body = src[src.index("    def stuck(self)"):src.index("    def pending(self)")]
        self.assertIn("ROLLBACK_FAILED", body)
        pend = src[src.index("    def pending(self)"):]
        pend = pend[:pend.index("    def _txn_states(self)")]
        self.assertNotIn("ROLLBACK_FAILED", pend,
                         "pending() blocks every write; a restore that already "
                         "failed once must not do that forever")

    def test_the_audit_counts_a_stuck_folder(self):
        src = self._source("quarantine.py")
        i = src.index("def referenced_txns")
        body = src[i:src.index("def survey(")]
        self.assertIn('"ROLLBACK_FAILED"))', body)
