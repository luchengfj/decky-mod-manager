"""Round 69: a failed install must not leave the new version in place.

Measured on the device before the fix (probe ``r69_failed_upgrade_probe.py``):
an upgrade of ``probe.upgradefail`` 1.0.0 -> 2.0.0 reported

    B_INSTALL2_OK False  B_CODE E_NO_SPACE
    B_VERSION_ON_DISK 2.0.0
    C_STATUS_ROWS [{'dir': 'probe.upgradefail', 'version': '2.0.0'}]

and ``rollback(txn)`` answered ``E_UNKNOWN  nothing to roll back for txn ...
(state=ROLLED_BACK)``. The user was told the upgrade failed, the disk held the
upgrade, and no API could bring the old version back -- while the displaced copy
sat in the quarantine where round 54's ``reclaim_quarantine`` is allowed to
delete it.

The cause was in the ``except`` branch of ``_install_inner``: it cleaned up only
a FIRST install (``not managed``). For an upgrade it did nothing at all, yet it
still recorded ROLLED_BACK. The two renames had already run, so "rolled back"
described a state the disk was not in.

These tests force the failure at the one point that sits after both renames and
before the commit -- ``journal.committed()`` raising ENOSPC -- because that is
the exact window the probe reached on the device.
"""
import io
import json
import os
import re
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

_SAVED_GAME_ID = None


def setUpModule():
    # tests/test_mvp.py pins DECKYMOD_GAME_ID=rimworld at import time, and
    # discovery imports every module before running any of them, so the pin has
    # to be lifted here -- at run time -- rather than at import. Round 47 / 50 /
    # 61 each lost a round to getting this wrong; tests/test_import_order.py now
    # pins the rule.
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
        self.uid = "probe.upgradefail"

    def _restore_env(self):
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _zip(self, version):
        p = os.path.join(self.t.inbox, "UpgradeFail-%s.zip" % version)
        _make_stardew_zip(p, self.uid, version)
        return p

    def _manifest_version(self, base=None):
        man = os.path.join(base or self.t.mods, self.uid, "manifest.json")
        with io.open(man, encoding="utf-8") as f:
            return json.loads(f.read())["Version"]

    def _break_commit(self):
        """Make the commit step fail the way a full disk does."""
        journal = self.eng.journal
        real = journal.committed
        calls = {"n": 0}

        def boom(txn, detail=None):
            calls["n"] += 1
            raise OSError(28, "No space left on device")

        journal.committed = boom
        self.addCleanup(setattr, journal, "committed", real)
        return calls

    def _rows(self):
        """Every journal row this engine wrote, newest last."""
        return self.eng.journal.read_all()


class TestAFailedUpgradeUndoesItself(_Base, unittest.TestCase):
    def test_the_old_version_is_still_on_disk(self):
        self.assertTrue(self.eng.install(self._zip("1.0.0"), after_confirm=True)["ok"])
        self.assertEqual(self._manifest_version(), "1.0.0")

        self._break_commit()
        failed = self.eng.install(self._zip("2.0.0"), after_confirm=True)

        self.assertFalse(failed["ok"], failed)
        self.assertEqual(failed["code"], "E_NO_SPACE", failed)
        self.assertEqual(self._manifest_version(), "1.0.0",
                         "a failed upgrade must leave the version the user had")

    def test_it_says_that_it_restored(self):
        self.eng.install(self._zip("1.0.0"), after_confirm=True)
        self._break_commit()
        failed = self.eng.install(self._zip("2.0.0"), after_confirm=True)

        self.assertFalse(failed["ok"], failed)
        self.assertTrue((failed.get("data") or {}).get("restored_old"),
                        "the answer must say the previous copy is back: %r" % (failed,))

    def test_the_journal_agrees_with_the_disk(self):
        self.eng.install(self._zip("1.0.0"), after_confirm=True)
        self._break_commit()
        failed = self.eng.install(self._zip("2.0.0"), after_confirm=True)
        txn = (failed.get("data") or {}).get("txn") or self._failed_txn()

        self.assertEqual(self.eng.journal.state(txn), "ROLLED_BACK", self._rows())
        restored = [r for r in self._rows()
                    if r.get("event") == "MOD_ROLLBACK_RESTORED"
                    and r.get("txn") == txn]
        self.assertEqual(len(restored), 1, self._rows())
        self.assertTrue(restored[0].get("restored_from"), restored[0])
        self.assertEqual(restored[0].get("reason"), "install_failed")

    def test_status_reports_the_old_version_not_the_new_one(self):
        self.eng.install(self._zip("1.0.0"), after_confirm=True)
        self._break_commit()
        self.eng.install(self._zip("2.0.0"), after_confirm=True)

        st = self.eng.status()["data"]["state"]
        rows = [m for m in st["mods"] if m.get("uniqueId") == self.uid]
        self.assertEqual(len(rows), 1, st["mods"])
        self.assertEqual(rows[0]["version"], "1.0.0", rows)

        owned = self.eng.journal.installed()
        self.assertIn(self.uid, owned)
        self.assertEqual(owned[self.uid]["version"], "1.0.0", owned[self.uid])
        # The restored copy is inside Mods/, and for file_drop that IS the
        # enabled state -- a row claiming otherwise contradicts the directory.
        self.assertTrue(owned[self.uid]["enabled"], owned[self.uid])

    def test_a_restored_parked_mod_stays_parked(self):
        """The other half: restoring must not switch a disabled mod on."""
        self.eng.install(self._zip("1.0.0"), after_confirm=True)
        self.assertTrue(self.eng.set_enabled(self.uid, False, after_confirm=True)["ok"])
        self.eng.install(self._zip("2.0.0"), after_confirm=True)
        owned = self.eng.journal.installed()
        self.assertFalse(owned[self.uid]["enabled"], owned[self.uid])

    def test_the_quarantine_folder_is_not_left_behind(self):
        self.eng.install(self._zip("1.0.0"), after_confirm=True)
        self._break_commit()
        failed = self.eng.install(self._zip("2.0.0"), after_confirm=True)
        self.assertFalse(failed["ok"], failed)
        txn = self._failed_txn()

        root = os.path.join(self.eng._resolve().quarantine_root, txn)
        self.assertFalse(os.path.exists(root),
                         "the emptied transaction folder is litter: %s" % root)

    def _failed_txn(self):
        txns = [r.get("txn") for r in self._rows()
                if r.get("event") == "ROLLED_BACK"]
        self.assertTrue(txns, self._rows())
        return txns[-1]


class TestAFailedFirstInstall(_Base, unittest.TestCase):
    def test_nothing_is_left_in_mods(self):
        self._break_commit()
        failed = self.eng.install(self._zip("1.0.0"), after_confirm=True)

        self.assertFalse(failed["ok"], failed)
        self.assertFalse(os.path.exists(os.path.join(self.t.mods, self.uid)),
                         "a failed first install must not leave a folder")
        self.assertFalse((failed.get("data") or {}).get("restored_old"),
                         "there was nothing to restore: %r" % (failed,))

    def test_it_does_not_claim_to_have_restored(self):
        self._break_commit()
        failed = self.eng.install(self._zip("1.0.0"), after_confirm=True)
        txn = [r.get("txn") for r in self._rows() if r.get("event") == "ROLLED_BACK"][-1]
        rows = [r for r in self._rows()
                if r.get("event") == "MOD_ROLLBACK_RESTORED" and r.get("txn") == txn]
        self.assertEqual(len(rows), 1, self._rows())
        self.assertIsNone(rows[0].get("restored_from"), rows[0])

    def test_a_journal_row_without_a_folder_does_not_skip_the_cleanup(self):
        """The journal can name a mod the disk no longer has.

        Measured on the device (round 69b): a journal record from an earlier run
        whose folder was gone made `_existing_managed()` answer "we manage it",
        so a FIRST install took the upgrade path and its failure left the
        half-written folder in Mods/. Cleanup must ask what this transaction
        did, not who it believes owns the mod.
        """
        self.eng.journal.record("MOD_INSTALLED", "seed-txn",
                                packageId=self.uid, uniqueId=self.uid,
                                name="Seed", version="0.9.0",
                                dir=os.path.join(self.t.mods, self.uid))
        self.assertIsNotNone(self.eng._existing_managed(self.uid),
                             "precondition: the journal claims the mod")
        self.assertFalse(os.path.exists(os.path.join(self.t.mods, self.uid)),
                         "precondition: the disk does not have it")

        self._break_commit()
        failed = self.eng.install(self._zip("1.0.0"), after_confirm=True)

        self.assertFalse(failed["ok"], failed)
        self.assertFalse(os.path.exists(os.path.join(self.t.mods, self.uid)),
                         "a failed install must not leave a folder, even when "
                         "the journal claims the mod")


class TestARollbackCanStillUndoAFailedUpgrade(_Base, unittest.TestCase):
    def test_rolled_back_is_no_longer_a_dead_end(self):
        """The state that used to answer 'nothing to roll back'."""
        self.assertTrue(self.eng.install(self._zip("1.0.0"), after_confirm=True))
        self._break_commit()
        failed = self.eng.install(self._zip("2.0.0"), after_confirm=True)
        txn = [r.get("txn") for r in self._rows() if r.get("event") == "ROLLED_BACK"][-1]
        self.assertEqual(self.eng.journal.state(txn), "ROLLED_BACK")

        got = self.eng.rollback(txn)
        # Either it performs a restore or it refuses for a reason it names; what
        # it must never do is answer E_UNKNOWN with nothing to say.
        if got["ok"]:
            self.assertEqual(self._manifest_version(), "1.0.0")
        else:
            self.assertNotIn("nothing to roll back", str(got.get("detail") or ""), got)


class TestTheShapeCannotRegress(unittest.TestCase):
    def _source(self, name):
        with io.open(os.path.join(_REPO, "deckymod", name), encoding="utf-8") as f:
            return f.read()

    def test_the_displaced_name_is_bound_before_the_try(self):
        src = self._source("smapi.py")
        i = src.index("        replaced_qdir = None\n")
        self.assertLess(i, src.index("            archive.extract_to("),
                        "an extract failure must not leave the name unbound")

    def test_the_rollback_branch_accepts_rolled_back(self):
        src = self._source("smapi.py")
        body = src[src.index("        inst = next((e for e in events"):]
        # Round 72: the old anchor was the literal condition line, which this
        # round extended -- so the anchor vanished and the test errored instead
        # of measuring anything. Bound the slice by the function's own final
        # refusal, which is the thing that must stay unreachable for these
        # states.
        body = body[:body.index("raise ModError(\"E_UNKNOWN\", detail=f\"nothing to roll back for txn")]
        self.assertIn('"ROLLED_BACK"', body,
                      "a failed upgrade keeps its replacement on disk; rollback "
                      "must be able to undo it")

    def test_the_failure_path_restores_before_it_reports(self):
        src = self._source("smapi.py")
        i = src.index("        except Exception as e:\n            try:")
        body = src[i:i + 4000]
        self.assertIn("upgrade.undo_install(replaced_qdir, install_at)", body)
        self.assertLess(body.index("upgrade.undo_install(replaced_qdir, install_at)"),
                        body.index("self.journal.rolled_back(txn"),
                        "record the rollback only after the copy is back")

    def test_only_one_place_decides_the_destination(self):
        """Round 72: three rollback cases now share one helper.

        The old assertion counted call sites and broke when a fourth case was
        added; the property worth keeping is that there is exactly ONE place
        that calls ``upgrade.undo_install`` on a rollback, and every branch goes
        through it (round 60: a second copy is a second chance to disagree).
        """
        src = self._source("smapi.py")
        self.assertEqual(src.count("def _restore_displaced(self"), 1)
        # The helper is defined ABOVE _rollback_inner; it is the one place a
        # rollback-side restore calls undo_install. (_install_inner has its own
        # call, in the failure path -- that is not a rollback branch.)
        h = src.index("    def _restore_displaced(")
        hbody = src[h:src.index("    def ", h + 10)]
        self.assertEqual(hbody.count("upgrade.undo_install("), 1,
                         "one place puts a displaced copy back")
        start = src.index("    def _rollback_inner(")
        body = src[start:]
        self.assertEqual(body.count("self._restore_displaced("), 3,
                         "committed upgrade, interrupted install, stuck retry")
        self.assertEqual(body.count("upgrade.undo_install("), 0,
                         "no rollback branch bypasses the helper")


if __name__ == "__main__":
    unittest.main()
