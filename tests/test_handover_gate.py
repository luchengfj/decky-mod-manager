"""Round 55: the engine-level proof that handover is reachable and reversible.

A unit test on ``deckymod/handover.py`` proves the moving logic works, but not
that any RPC reaches it, not that the destructive gates run first, and -- the
one that matters most -- not that ``rollback`` actually puts the entries back.
The confirm dialog tells the user "Rollback puts them back"; this file is what
makes that sentence true or reports it broken.

The device currently has nothing to hand over (``read_only = False`` since
Amethyst's markers went away), so the scenario is built here: a marker file and
a symlinked entry inside ``Mods/``, which is exactly the layout Round 44 was
written to refuse.
"""

import json
import os
import unittest

from deckymod import handover
from deckymod.journal import Journal
from deckymod.smapi import StardewEngine

from tests.test_stardew import MANIFEST, StardewTree

_PREV_GAME_ID = None


def setUpModule():
    global _PREV_GAME_ID
    _PREV_GAME_ID = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    if _PREV_GAME_ID is not None:
        os.environ["DECKYMOD_GAME_ID"] = _PREV_GAME_ID
    else:
        os.environ.pop("DECKYMOD_GAME_ID", None)


class _Base(object):
    def setUp(self):
        self.t = StardewTree()
        self.t.env()
        self.eng = StardewEngine(journal=Journal(self.t.data, self.t.logs, "stardew"))
        self.qroot = os.path.join(self.t.game, ".decky-quarantine")

    def _marker(self):
        """Amethyst's 0-byte bookkeeping file: the movable case."""
        p = os.path.join(self.t.mods, ".mm_deployed")
        with open(p, "wb") as f:
            f.write(b"")
        return p


class TestHandoverThroughTheEngine(_Base, unittest.TestCase):
    def test_status_is_read_only_and_the_handover_clears_it(self):
        self._marker()
        before = self.eng.status()
        self.assertTrue(before["data"]["state"]["external_manager"])
        self.assertTrue(before["data"]["state"]["read_only"])

        first = self.eng.handover_mods(after_confirm=False)
        self.assertTrue(first["ok"], first)
        self.assertEqual(first["data"]["phase"], "confirm")
        # Nothing moved yet: the marker is still where the other tool put it.
        self.assertTrue(os.path.isfile(os.path.join(self.t.mods, ".mm_deployed")))

        second = self.eng.handover_mods(after_confirm=True)
        self.assertTrue(second["ok"], second)
        self.assertEqual(second["data"]["phase"], "moved")
        self.assertIn(".mm_deployed", second["data"]["moved"])
        self.assertFalse(os.path.exists(os.path.join(self.t.mods, ".mm_deployed")))

        after = self.eng.status()
        self.assertFalse(after["data"]["state"]["external_manager"])
        self.assertFalse(after["data"]["state"]["read_only"])

    def test_rollback_puts_the_entry_back(self):
        """The dialog's promise. Without this the UI would be lying."""
        self._marker()
        out = self.eng.handover_mods(after_confirm=True)
        self.assertTrue(out["ok"], out)
        txn = out["data"]["txn"]

        back = self.eng.rollback(txn)
        self.assertTrue(back["ok"], back)
        self.assertEqual(back["data"]["restored"], "handover")
        self.assertIn(".mm_deployed", back["data"]["moved"])
        self.assertTrue(os.path.isfile(os.path.join(self.t.mods, ".mm_deployed")))
        self.assertFalse(os.path.exists(os.path.join(self.qroot, txn,
                                                    ".mm_deployed")))
        # And the tree is somebody else's again, because that is the state it
        # was in before the handover.
        self.assertTrue(self.eng.status()["data"]["state"]["read_only"])

    def test_rollback_does_not_overwrite_something_new(self):
        """If the other manager re-deployed in the meantime, refuse that name."""
        self._marker()
        out = self.eng.handover_mods(after_confirm=True)
        txn = out["data"]["txn"]
        with open(os.path.join(self.t.mods, ".mm_deployed"), "wb") as f:
            f.write(b"re-deployed by somebody else\n")

        back = self.eng.rollback(txn)
        self.assertTrue(back["ok"], back)
        self.assertEqual(back["data"]["moved"], [])
        self.assertIn(".mm_deployed", back["data"]["failed"])
        with open(os.path.join(self.t.mods, ".mm_deployed"), "rb") as f:
            self.assertEqual(f.read(), b"re-deployed by somebody else\n")

    def test_nothing_to_hand_over_is_reported_not_silently_ok(self):
        out = self.eng.handover_mods(after_confirm=True)
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "E_CAPABILITY_DISABLED")
        self.assertIn("nothing to hand over", out["detail"])

    def test_a_marker_directory_is_refused_as_a_whole(self):
        # Mods_Core/ is where the other manager's real deployed files live.
        # Moving it would break that deployment in ways this plugin cannot see.
        os.makedirs(os.path.join(self.t.game, "Mods_Core", "deployed"))
        self._marker()
        out = self.eng.handover_mods(after_confirm=True)
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "E_CAPABILITY_DISABLED")
        self.assertIn(handover.R_MARKER_DIR, out["data"]["blocking"])
        # Refused as a whole: the movable marker did not move either.
        self.assertTrue(os.path.isfile(os.path.join(self.t.mods, ".mm_deployed")))


class TestTheNarrowerGatesStillRun(_Base, unittest.TestCase):
    """Handover skips the external-manager gate on purpose. Nothing else."""

    def test_the_game_running_blocks_it(self):
        self._marker()
        os.environ["DECKYMOD_GAME_RUNNING"] = "1"
        try:
            out = self.eng.handover_mods(after_confirm=True)
        finally:
            os.environ.pop("DECKYMOD_GAME_RUNNING", None)
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "E_GAME_RUNNING")
        self.assertTrue(os.path.isfile(os.path.join(self.t.mods, ".mm_deployed")))

    def test_an_unfinished_transaction_blocks_it(self):
        self._marker()
        self.eng.journal.begin("20260101T000000-crash001", "install", {})
        self.eng.journal.applying("20260101T000000-crash001")
        out = self.eng.handover_mods(after_confirm=True)
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "E_RECOVERY_PENDING")
        self.assertTrue(os.path.isfile(os.path.join(self.t.mods, ".mm_deployed")))

    def test_the_descriptor_can_disable_it(self):
        self._marker()
        desc = self.eng._descriptor()
        saved = json.loads(json.dumps(desc["loader_detection"]["handover"]))
        try:
            desc["loader_detection"]["handover"]["enabled"] = False
            out = self.eng.handover_mods(after_confirm=True)
        finally:
            desc["loader_detection"]["handover"] = saved
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "E_CAPABILITY_DISABLED")
        self.assertIn("disabled", out["detail"])

    @unittest.skipUnless(hasattr(os, "symlink"), "no symlink support")
    def test_no_marker_list_means_no_action(self):
        # A descriptor without the key must not inherit another module's
        # default: this operation moves things, so silence means "do nothing".
        self._marker()
        desc = self.eng._descriptor()
        saved = list(desc["loader_detection"].get("external_manager_markers") or [])
        try:
            desc["loader_detection"]["external_manager_markers"] = []
            out = self.eng.handover_mods(after_confirm=True)
        finally:
            desc["loader_detection"]["external_manager_markers"] = saved
        self.assertFalse(out["ok"])
        self.assertIn("nothing to hand over", out["detail"])


class TestTheRpcIsWired(unittest.TestCase):
    def test_the_plugin_exposes_it(self):
        import ast
        import io
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with io.open(os.path.join(root, "main.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        plugin = next(n for n in tree.body
                      if isinstance(n, ast.ClassDef) and n.name == "Plugin")
        fn = next(f for f in plugin.body
                  if isinstance(f, ast.AsyncFunctionDef) and f.name == "handover_mods")
        self.assertEqual([a.arg for a in fn.args.args],
                         ["self", "after_confirm"])

    def test_both_engines_implement_it(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for mod in ("smapi.py", "engine.py"):
            with open(os.path.join(root, "deckymod", mod), encoding="utf-8") as f:
                src = f.read()
            self.assertIn("def handover_mods", src, mod)
            self.assertIn("def _handover_inner", src, mod)
            # The external-manager gate must NOT be in this path, and the
            # comment above it is what keeps the omission from looking like a
            # mistake to the next reader.
            i = src.index("def _handover_inner")
            body = src[i:i + 1400]
            self.assertNotIn("_check_write_allowed", body, mod)

    def _body_of(self, src, name):
        """The real body of a method, not the next N characters.

        Round 65: this used to be ``src[i:i + 4000]``, which stopped covering
        _rollback_inner as soon as that function grew. The assertion then either
        passed by luck or failed for a reason unrelated to what it checks.
        """
        i = src.index("def %s(" % name)
        rest = src[i:]
        out = []
        for line in rest.splitlines(True):
            if out and line.startswith("    def "):
                break
            out.append(line)
        return "".join(out)

    def test_both_rollbacks_know_about_it(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for mod in ("smapi.py", "engine.py"):
            with open(os.path.join(root, "deckymod", mod), encoding="utf-8") as f:
                src = f.read()
            body = self._body_of(src, "_rollback_inner")
            self.assertIn("MODS_HANDOVER", body, mod)
            self.assertIn("handover.restore", body, mod)
            # and the body must actually be the function, not a stray fragment
            self.assertIn("self.journal.state(txn)", body, mod)


if __name__ == "__main__":
    unittest.main()
