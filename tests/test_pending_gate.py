"""Round 51: an unfinished transaction must block the NEXT one.

`status()` has reported `recovery_needed` since the first release, and
`E_RECOVERY_PENDING` has been in `errors.py` with `rollback=True` since then too.
`journal.py`'s own docstring says:

    If a PREPARED/APPLYING transaction is found on open -> E_RECOVERY_PENDING

Nothing raised it. A device-shaped probe found the consequence: with an
`APPLYING` transaction in the journal, `install()` started a second one. Two
transactions then interleave and a later rollback undoes states in the wrong
order -- the journal is the only record of what happened, so a confused journal
is unrecoverable by inspection.

Two invariants are tested here:

1. A new transaction is refused while one is unfinished.
2. `rollback()` is NOT refused -- it is the recovery, and gating it would leave
   a stuck journal with no way out through the plugin.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deckymod.journal import Journal  # noqa: E402
from deckymod.smapi import StardewEngine  # noqa: E402
from tests.test_stardew import StardewTree, _make_stardew_zip  # noqa: E402

CRASH = "20260101T000000-crash001"


def setUpModule():
    """Un-pin the RimWorld regression pin set by tests/test_mvp.py.

    discovery imports every module before running any of them, so popping the
    variable at import time would be too early to matter here.
    """
    global _SAVED
    _SAVED = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    os.environ.pop("DECKYMOD_GAME_ID", None)
    if _SAVED is not None:
        os.environ["DECKYMOD_GAME_ID"] = _SAVED


class TestPendingBlocksNewTransactions(unittest.TestCase):
    def setUp(self):
        self.t = StardewTree()
        self.t.env()
        self.addCleanup(self.t.cleanup)
        self.eng = StardewEngine(journal=Journal(self.t.data, self.t.logs, "stardew"))
        _make_stardew_zip(os.path.join(self.t.inbox, "One.zip"))

    def _zip(self):
        return os.path.join(self.t.inbox, "One.zip")

    def _forge_crash(self, apply_step=True):
        """Leave the journal exactly as a crash mid-install would."""
        j = self.eng.journal
        j.begin(CRASH, "install", {"target": "somewhere", "mod": "x"})
        if apply_step:
            j.applying(CRASH)

    def test_a_clean_journal_accepts_writes(self):
        self.assertEqual(self.eng.journal.pending(), [])
        r = self.eng.install(self._zip(), after_confirm=False)
        self.assertTrue(r["ok"], r)
        self.assertEqual((r.get("data") or {}).get("phase"), "confirm")

    def test_install_is_refused_while_an_install_is_pending(self):
        self._forge_crash()
        r = self.eng.install(self._zip(), after_confirm=False)
        self.assertFalse(r["ok"], r)
        self.assertEqual(r["code"], "E_RECOVERY_PENDING")
        self.assertIn(CRASH, r["detail"])
        self.assertIn("Recover", r["detail"])
        # The refusal must be honest about what is rollback-able.
        self.assertTrue(r["rollback_available"])

    def test_the_second_transaction_is_not_started(self):
        """The point is not the error code -- it is that no txn was opened."""
        self._forge_crash()
        before = len(self.eng.journal.events(CRASH))
        self.eng.install(self._zip(), after_confirm=False)
        self.assertEqual(self.eng.journal.pending(), [CRASH])
        self.assertEqual(len(self.eng.journal.events(CRASH)), before)

    def test_enable_and_disable_are_refused(self):
        self._forge_crash()
        on = self.eng.set_enabled("any.mod", True, after_confirm=True)
        off = self.eng.set_enabled("any.mod", False, after_confirm=True)
        self.assertEqual(on["code"], "E_RECOVERY_PENDING")
        self.assertEqual(off["code"], "E_RECOVERY_PENDING")

    def test_uninstall_is_refused(self):
        self._forge_crash()
        r = self.eng.uninstall("any.mod", after_confirm=True)
        self.assertEqual(r["code"], "E_RECOVERY_PENDING")

    def test_a_prepared_only_transaction_also_blocks(self):
        """PREPARED is as unfinished as APPLYING."""
        self._forge_crash(apply_step=False)
        r = self.eng.install(self._zip(), after_confirm=False)
        self.assertEqual(r["code"], "E_RECOVERY_PENDING")

    def test_rollback_is_not_blocked(self):
        """Rollback IS the recovery: gating it would make a stuck journal final."""
        self._forge_crash()
        r = self.eng.rollback(CRASH)
        self.assertTrue(r["ok"], r)
        self.assertTrue((r.get("data") or {}).get("recovered"))
        self.assertEqual(self.eng.journal.pending(), [])

    def test_writes_work_again_after_the_pending_one_is_cleared(self):
        """The gate must open again, or this round would wedge the plugin."""
        self._forge_crash()
        self.assertEqual(self.eng.install(self._zip(), after_confirm=False)["code"],
                         "E_RECOVERY_PENDING")
        self.assertTrue(self.eng.rollback(CRASH)["ok"])
        r = self.eng.install(self._zip(), after_confirm=False)
        self.assertTrue(r["ok"], r)
        self.assertEqual((r.get("data") or {}).get("phase"), "confirm")

    def test_the_error_code_already_existed(self):
        """E_RECOVERY_PENDING is not new: error_codes() must stay at 50."""
        from deckymod.errors import ERRORS
        self.assertIn("E_RECOVERY_PENDING", ERRORS)
        self.assertEqual(ERRORS["E_RECOVERY_PENDING"][2], True)
        self.assertEqual(len(ERRORS), 50)

    def test_an_unreadable_journal_does_not_block_writes(self):
        """A read failure must not become 'the plugin is stuck forever'."""
        def boom():
            raise OSError("journal unreadable")

        original = self.eng.journal.pending
        self.eng.journal.pending = boom
        try:
            r = self.eng.install(self._zip(), after_confirm=False)
        finally:
            self.eng.journal.pending = original
        self.assertTrue(r["ok"], r)


class TestRimworldEngineHasTheSameGate(unittest.TestCase):
    """The RimWorld engine had the same hole; assert the wiring textually.

    A real tree would need a Steam library fixture, and the point here is only
    that the guard is present in all three write paths of the OTHER engine too.
    """

    def test_all_three_write_paths_call_the_guard(self):
        import io
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "deckymod", "engine.py")
        with io.open(path, encoding="utf-8") as f:
            src = f.read()
        self.assertEqual(src.count("self._check_no_pending()"), 3)
        self.assertIn("def _check_no_pending", src)

    def test_rollback_is_the_only_write_path_without_it(self):
        import ast
        import io
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "deckymod", "engine.py")
        with io.open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        guarded = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Attribute)
                        and inner.func.attr == "_check_no_pending"):
                    guarded.add(node.name)
        self.assertEqual(guarded,
                         {"_install_inner", "_set_enabled_inner", "_uninstall_inner"})
        self.assertNotIn("_rollback_inner", guarded)


if __name__ == "__main__":
    unittest.main()
