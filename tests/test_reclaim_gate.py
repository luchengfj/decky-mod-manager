"""Round 54: the engine-level gate for reclaiming quarantine folders.

A unit test on ``deckymod/quarantine.py`` would prove that ``reclaim()`` works
but not that any RPC reaches it, and not that the destructive write gates run
first. Those are the two things that can actually hurt somebody, so they are
checked here against a real engine and a real synthetic tree.

The scenario mirrors the device: a quarantine folder with no journal record
(the 16 orphans measured in Round 48), plus one the journal still references so
the refusal has something real to refuse.
"""

import json
import os
import unittest

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


def _moddir(parent, name):
    d = os.path.join(parent, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(MANIFEST, f)
    return d


class _Base(object):
    def setUp(self):
        self.t = StardewTree()
        self.t.env()
        self.eng = StardewEngine(journal=Journal(self.t.data, self.t.logs, "stardew"))
        self.qroot = os.path.join(self.t.game, ".decky-quarantine")
        os.makedirs(self.qroot, exist_ok=True)
        # An orphan: nothing in the journal names this transaction.
        self.orphan = "20260101T000000-orph0001"
        _moddir(os.path.join(self.qroot, self.orphan), "esca.destroyablebushes")

    def _restorable(self):
        """Make a quarantine folder the journal can still roll back to."""
        txn = "20260101T000001-keep0001"
        qdir = _moddir(os.path.join(self.qroot, txn), "some.kept")
        self.eng.journal.record(
            "MOD_UNINSTALLED", txn, packageId="some.kept",
            quarantine=qdir, from_path=os.path.join(self.t.mods, "some.kept"),
        )
        return txn


class TestReclaimThroughTheEngine(_Base, unittest.TestCase):
    def test_an_orphan_is_reported_then_removed(self):
        st = self.eng.status()
        q = st["data"]["state"]["quarantine"]
        self.assertTrue(q["checked"])
        self.assertGreaterEqual(q["orphans"], 1)
        entry = next(e for e in q["entries"] if e["txn"] == self.orphan)
        self.assertEqual(entry["state"], "orphan")
        self.assertIn("esca.destroyablebushes", entry["names"])

        first = self.eng.reclaim_quarantine([self.orphan], after_confirm=False)
        self.assertTrue(first["ok"])
        self.assertEqual(first["data"]["phase"], "confirm")
        self.assertTrue(os.path.isdir(os.path.join(self.qroot, self.orphan)))

        second = self.eng.reclaim_quarantine([self.orphan], after_confirm=True)
        self.assertTrue(second["ok"])
        self.assertEqual(second["data"]["phase"], "removed")
        self.assertEqual(second["data"]["removed"], [self.orphan])
        self.assertFalse(os.path.exists(os.path.join(self.qroot, self.orphan)))

    def test_a_restorable_folder_survives_and_says_why(self):
        txn = self._restorable()
        out = self.eng.reclaim_quarantine([txn], after_confirm=True)
        self.assertTrue(out["ok"])
        self.assertIn(txn, out["data"]["refused"])
        self.assertIn("restorable", out["data"]["refused"][txn])
        self.assertTrue(os.path.isdir(os.path.join(self.qroot, txn)))

    def test_a_mixed_request_keeps_the_restorable_one(self):
        txn = self._restorable()
        out = self.eng.reclaim_quarantine([self.orphan, txn], after_confirm=True)
        self.assertEqual(out["data"]["removed"], [self.orphan])
        self.assertIn(txn, out["data"]["refused"])
        self.assertTrue(os.path.isdir(os.path.join(self.qroot, txn)))

    def test_an_empty_request_is_refused_rather_than_sweeping(self):
        out = self.eng.reclaim_quarantine([], after_confirm=True)
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "E_PATH_INVALID")
        self.assertTrue(os.path.isdir(os.path.join(self.qroot, self.orphan)))

    def test_two_calls_at_once_are_not_what_this_does(self):
        """The RPC takes a list; passing one id twice must not double-count."""
        out = self.eng.reclaim_quarantine([self.orphan, self.orphan], after_confirm=True)
        self.assertEqual(out["data"]["removed"], [self.orphan])


class TestTheGatesRunFirst(_Base, unittest.TestCase):
    """Reclaim deletes files. Every gate that guards uninstall must guard it."""

    def test_the_game_running_blocks_it(self):
        os.environ["DECKYMOD_GAME_RUNNING"] = "1"
        try:
            out = self.eng.reclaim_quarantine([self.orphan], after_confirm=True)
        finally:
            os.environ.pop("DECKYMOD_GAME_RUNNING", None)
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "E_GAME_RUNNING")
        self.assertTrue(os.path.isdir(os.path.join(self.qroot, self.orphan)))

    def test_an_unfinished_transaction_blocks_it(self):
        self.eng.journal.begin("20260101T000000-crash001", "install", {})
        self.eng.journal.applying("20260101T000000-crash001")
        out = self.eng.reclaim_quarantine([self.orphan], after_confirm=True)
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "E_RECOVERY_PENDING")
        self.assertTrue(os.path.isdir(os.path.join(self.qroot, self.orphan)))

    def test_a_foreign_mods_tree_blocks_it(self):
        # The Round 44 structural signal: a symlinked entry in Mods/ means the
        # tree belongs to another manager, so nothing here may be deleted.
        try:
            os.symlink(os.path.join(self.t.mods, ".."), os.path.join(self.t.mods, "linked"))
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available here")
        out = self.eng.reclaim_quarantine([self.orphan], after_confirm=True)
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "E_EXTERNAL_MANAGER")
        self.assertTrue(os.path.isdir(os.path.join(self.qroot, self.orphan)))

    def test_the_descriptor_can_forbid_it_entirely(self):
        desc = self.eng._descriptor()
        saved = json.loads(json.dumps(desc.get("mod_package", {}).get("quarantine") or {}))
        try:
            self.eng._descriptor()["mod_package"]["quarantine"]["allow_reclaim"] = False
            out = self.eng.reclaim_quarantine([self.orphan], after_confirm=True)
        finally:
            self.eng._descriptor()["mod_package"]["quarantine"] = saved
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "E_CAPABILITY_DISABLED")
        self.assertTrue(os.path.isdir(os.path.join(self.qroot, self.orphan)))

    def test_over_the_per_call_limit_is_refused(self):
        desc = self.eng._descriptor()
        saved = desc["mod_package"]["quarantine"].get("max_reclaim")
        try:
            desc["mod_package"]["quarantine"]["max_reclaim"] = 1
            out = self.eng.reclaim_quarantine([self.orphan, "another"], after_confirm=True)
        finally:
            if saved is None:
                desc["mod_package"]["quarantine"].pop("max_reclaim", None)
            else:
                desc["mod_package"]["quarantine"]["max_reclaim"] = saved
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "E_PATH_INVALID")
        self.assertIn("at most", out["detail"])


class TestTheRpcIsWired(unittest.TestCase):
    def test_the_plugin_exposes_it(self):
        import ast
        import io
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with io.open(os.path.join(root, "main.py"), encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
        names = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "Plugin":
                names = [f.name for f in node.body
                         if isinstance(f, ast.AsyncFunctionDef) and not f.name.startswith("_")]
        self.assertIn("reclaim_quarantine", names)
        fn = next(f for node in tree.body if isinstance(node, ast.ClassDef)
                  and node.name == "Plugin" for f in node.body
                  if isinstance(f, ast.AsyncFunctionDef)
                  and f.name == "reclaim_quarantine")
        self.assertEqual([a.arg for a in fn.args.args], ["self", "txns", "after_confirm"])

    def test_a_reclaim_is_recorded_in_the_journal(self):
        t = StardewTree()
        t.env()
        eng = StardewEngine(journal=Journal(t.data, t.logs, "stardew"))
        qroot = os.path.join(t.game, ".decky-quarantine")
        os.makedirs(qroot, exist_ok=True)
        _moddir(os.path.join(qroot, "txn-a"), "a.mod")
        out = eng.reclaim_quarantine(["txn-a"], after_confirm=True)
        self.assertTrue(out["ok"])
        events = [r for r in eng.journal.read_all()
                  if r.get("event") == "QUARANTINE_RECLAIMED"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["removed"], ["txn-a"])
