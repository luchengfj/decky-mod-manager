"""Round 50: the running-game gate must be WIRED, not just implemented.

`tests/test_procs.py` proves the detector's decisions against faked primitives.
This file proves the other direction, which is the whole point of the round: the
descriptor has said `safety.refuse_if_game_running: true` since Round 39 while
the only implementation read an environment variable nothing sets. A correct
detector that no write path consults would look exactly the same from the
outside -- the plugin accepting a destructive op mid-game.

So every test here drives the real `StardewEngine` on a real tree and asserts the
error a user would actually see.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deckymod import procs  # noqa: E402
from deckymod.journal import Journal  # noqa: E402
from deckymod.smapi import StardewEngine  # noqa: E402
from tests.test_stardew import StardewTree, _make_stardew_zip  # noqa: E402


def setUpModule():
    """Un-pin the RimWorld regression pin that tests/test_mvp.py sets.

    discovery imports every module BEFORE running any of them, so the pin is
    already in the environment by the time this file is imported; popping it at
    import time would do nothing. ``_SAVED`` is restored in tearDownModule.
    """
    global _SAVED
    _SAVED = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    os.environ.pop("DECKYMOD_GAME_ID", None)
    if _SAVED is not None:
        os.environ["DECKYMOD_GAME_ID"] = _SAVED


def _first_zip(tree):
    for name in sorted(os.listdir(tree.inbox)):
        if name.endswith(".zip"):
            return os.path.join(tree.inbox, name)
    raise AssertionError("no zip in the inbox")


class _RunningPatch(object):
    """Force procs.is_running to one answer for the duration of a block."""

    def __init__(self, state, detail="", pid="4242", match="/x/StardewModdingAPI"):
        self.state = state
        self.detail = detail
        self.pid = pid
        self.match = match
        self._old = None
        self.calls = 0

    def __enter__(self):
        self._old = procs.is_running
        outer = self

        def fake(game_root="", markers=None):
            outer.calls += 1
            return {"state": outer.state, "pid": outer.pid,
                    "match": outer.match, "scanned": 3,
                    "detail": outer.detail}

        procs.is_running = fake
        return self

    def __exit__(self, *exc):
        procs.is_running = self._old
        return False


class TestRunningGate(unittest.TestCase):
    def setUp(self):
        self.t = StardewTree()
        self.t.env()
        self.addCleanup(self.t.cleanup)
        self.addCleanup(lambda: os.environ.pop("DECKYMOD_GAME_RUNNING", None))
        os.environ.pop("DECKYMOD_GAME_RUNNING", None)
        self.eng = StardewEngine(journal=Journal(self.t.data, self.t.logs, "stardew"))
        _make_stardew_zip(os.path.join(self.t.inbox, "Run.zip"))

    def test_a_running_game_refuses_install(self):
        with _RunningPatch("running"):
            r = self.eng.install(_first_zip(self.t), after_confirm=True)
        self.assertFalse(r["ok"], r)
        self.assertEqual(r["code"], "E_GAME_RUNNING")
        self.assertIn("running", r["detail"])
        self.assertIn("StardewModdingAPI", r["detail"])
        self.assertEqual(os.listdir(self.t.mods), [])

    def test_a_running_game_refuses_enable_and_disable(self):
        with _RunningPatch("running"):
            on = self.eng.set_enabled("Some.Mod", True, after_confirm=True)
            off = self.eng.set_enabled("Some.Mod", False, after_confirm=True)
        self.assertEqual(on["code"], "E_GAME_RUNNING")
        self.assertEqual(off["code"], "E_GAME_RUNNING")

    def test_a_running_game_refuses_uninstall(self):
        with _RunningPatch("running"):
            r = self.eng.uninstall("Some.Mod", after_confirm=True)
        self.assertEqual(r["code"], "E_GAME_RUNNING")

    def test_a_running_game_refuses_rollback(self):
        with _RunningPatch("running"):
            r = self.eng.rollback("20260101T000000-deadbeef")
        self.assertEqual(r["code"], "E_GAME_RUNNING")

    def test_a_stopped_game_allows_the_write(self):
        """The gate must not become a wall: with nothing running, install works."""
        with _RunningPatch("stopped") as patch:
            r = self.eng.install(_first_zip(self.t), after_confirm=False)
            self.assertTrue(patch.calls >= 1, "the detector was never consulted")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r.get("data", {}).get("phase"), "confirm")

    def test_unknown_does_not_block(self):
        """A host without /proc must not become write-nothing.

        Refusing on "unknown" would mean the plugin silently does nothing on any
        machine whose /proc is restricted, which is a worse failure than the one
        this round fixes. The journal and post-commit verify cover the rest.
        """
        with _RunningPatch("unknown", detail="/proc lists no processes"):
            r = self.eng.install(_first_zip(self.t), after_confirm=False)
        self.assertTrue(r["ok"], r)

    def test_the_env_marker_still_wins(self):
        """The explicit override is kept: it is what the tests and a user set."""
        os.environ["DECKYMOD_GAME_RUNNING"] = "1"
        try:
            r = self.eng.install(_first_zip(self.t), after_confirm=True)
        finally:
            os.environ.pop("DECKYMOD_GAME_RUNNING", None)
        self.assertEqual(r["code"], "E_GAME_RUNNING")
        self.assertIn("DECKYMOD_GAME_RUNNING", r["detail"])

    def test_status_reports_the_answer_without_refusing(self):
        with _RunningPatch("running"):
            st = self.eng.status()
        self.assertTrue(st["ok"], st)
        self.assertEqual(st["data"]["state"]["running"]["state"], "running")

    def test_status_says_unknown_when_it_cannot_tell(self):
        with _RunningPatch("unknown", detail="no /proc here"):
            st = self.eng.status()
        self.assertTrue(st["ok"], st)
        self.assertEqual(st["data"]["state"]["running"]["state"], "unknown")


if __name__ == "__main__":
    unittest.main()
