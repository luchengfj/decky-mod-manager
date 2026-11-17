"""Round 54: reclaiming quarantine folders that nothing can restore.

The point of this module is what it REFUSES. A folder the journal can still
roll back is data the user can get back; a folder marked ``unknown`` means the
journal could not be read, and spending "I cannot tell" as "nobody owns this"
is the exact shape of a data-loss bug. Both are refused by name, so the caller
can say which folder was kept and why.
"""

import ast
import io
import os
import sys
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deckymod import quarantine  # noqa: E402

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMPBASE = os.path.join(_REPO, ".decky-test-tmp")


def _tmpdir(tag):
    d = os.path.join(_TMPBASE, "r54_%s_%s" % (tag, uuid.uuid4().hex[:8]))
    os.makedirs(d, exist_ok=True)
    return d


class _Journal(object):
    """Minimal stand-in: only read_all() is part of the contract used here."""

    def __init__(self, records=None, boom=False):
        self._records = records or []
        self._boom = boom

    def read_all(self):
        if self._boom:
            raise OSError("[Errno 5] I/O error")
        return self._records


def _uninst(txn, pid="some.mod"):
    return {"event": "MOD_UNINSTALLED", "txn": txn, "packageId": pid}


class TestPlanRefusesWhatItMust(unittest.TestCase):
    """plan_reclaim is the whole safety argument, so it gets the sharpest tests."""

    def _survey(self):
        return {
            "checked": True,
            "exists": True,
            "journal": "readable",
            "entries": [
                {"txn": "keep-restorable", "state": quarantine.RESTORABLE,
                 "bytes": 100, "files": 1, "names": []},
                {"txn": "drop-orphan", "state": quarantine.ORPHAN,
                 "bytes": 200, "files": 2, "names": ["a"]},
                {"txn": "drop-empty", "state": quarantine.ORPHAN,
                 "bytes": 0, "files": 0, "names": []},
            ],
            "dirs": 3, "total_bytes": 300, "restorable": 1, "orphans": 2,
            "empty": 1, "truncated": False,
        }

    def test_only_orphans_are_accepted(self):
        p = quarantine.plan_reclaim(self._survey(), ["drop-orphan"])
        self.assertEqual(p["accepted"], ["drop-orphan"])
        self.assertEqual(p["refused"], {})

    def test_a_restorable_folder_is_refused_by_name(self):
        p = quarantine.plan_reclaim(self._survey(), ["keep-restorable"])
        self.assertEqual(p["accepted"], [])
        self.assertIn("keep-restorable", p["refused"])
        self.assertIn("restorable", p["refused"]["keep-restorable"])

    def test_unknown_is_never_spent_as_orphan(self):
        s = self._survey()
        s["journal"] = "unreadable"
        for e in s["entries"]:
            e["state"] = quarantine.UNKNOWN
        p = quarantine.plan_reclaim(s, ["drop-orphan", "keep-restorable"])
        self.assertEqual(p["accepted"], [])
        self.assertEqual(sorted(p["refused"]), ["drop-orphan", "keep-restorable"])
        self.assertIn("unknown", p["refused"]["drop-orphan"])

    def test_an_id_nobody_knows_is_refused_specifically(self):
        p = quarantine.plan_reclaim(self._survey(), ["nope"])
        self.assertEqual(p["accepted"], [])
        self.assertIn("no such", p["refused"]["nope"])

    def test_duplicate_ids_are_not_counted_twice(self):
        p = quarantine.plan_reclaim(self._survey(), ["drop-orphan", "drop-orphan"])
        self.assertEqual(p["accepted"], ["drop-orphan"])
        self.assertEqual(p["bytes"], 200)

    def test_totals_add_up_over_several_folders(self):
        p = quarantine.plan_reclaim(self._survey(), ["drop-orphan", "drop-empty"])
        self.assertEqual(sorted(p["accepted"]), ["drop-empty", "drop-orphan"])
        self.assertEqual(p["bytes"], 200)
        self.assertEqual(p["files"], 2)


class TestReclaimIsTwoPhase(unittest.TestCase):
    def setUp(self):
        self.root = _tmpdir("two")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.root, ignore_errors=True))
        for txn in ("t1", "t2"):
            d = os.path.join(self.root, txn)
            os.makedirs(d)
            with io.open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as f:
                f.write("{}")
        self.survey = {
            "checked": True, "entries": [
                {"txn": "t1", "state": quarantine.ORPHAN, "bytes": 2, "files": 1},
                {"txn": "t2", "state": quarantine.ORPHAN, "bytes": 2, "files": 1},
            ],
        }

    def test_without_confirm_nothing_is_deleted(self):
        out = quarantine.reclaim(self.root, ["t1"], self.survey, after_confirm=False)
        self.assertEqual(out["phase"], "confirm")
        self.assertTrue(os.path.isdir(os.path.join(self.root, "t1")))
        self.assertEqual(out["bytes"], 2)

    def test_with_confirm_only_the_named_folder_goes(self):
        out = quarantine.reclaim(self.root, ["t1"], self.survey, after_confirm=True)
        self.assertEqual(out["phase"], "removed")
        self.assertEqual(out["removed"], ["t1"])
        self.assertFalse(os.path.exists(os.path.join(self.root, "t1")))
        self.assertTrue(os.path.isdir(os.path.join(self.root, "t2")))

    def test_nothing_to_do_reports_nothing_rather_than_failing(self):
        out = quarantine.reclaim(self.root, [], self.survey, after_confirm=True)
        self.assertEqual(out["phase"], "nothing")
        self.assertTrue(os.path.isdir(os.path.join(self.root, "t1")))

    def test_a_folder_that_vanished_is_reported_not_raised(self):
        out = quarantine.reclaim(self.root, ["gone"], self.survey, after_confirm=True)
        self.assertEqual(out["phase"], "nothing")
        self.assertIn("gone", out["refused"])


class TestReclaimRechecksTheGround(unittest.TestCase):
    """The survey is a snapshot; the filesystem may have moved since."""

    def test_a_directory_that_became_a_link_is_refused(self):
        root = _tmpdir("link")
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        real = os.path.join(root, "real")
        os.makedirs(real)
        target = os.path.join(root, "txn")
        try:
            os.symlink(real, target)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available here")
        survey = {"checked": True, "entries": [
            {"txn": "txn", "state": quarantine.ORPHAN, "bytes": 0, "files": 0}]}
        out = quarantine.reclaim(root, ["txn"], survey, after_confirm=True)
        self.assertEqual(out["removed"], [])
        self.assertIn("symbolic link", out["failed"]["txn"])
        self.assertTrue(os.path.isdir(real))


class TestSurveyNamesTheContents(unittest.TestCase):
    def test_the_first_child_names_are_reported(self):
        root = _tmpdir("names")
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        d = os.path.join(root, "20260101T000000-aaaa")
        os.makedirs(os.path.join(d, "esca.destroyablebushes"))
        s = quarantine.survey(root, _Journal([]))
        entry = s["entries"][0]
        self.assertEqual(entry["names"], ["esca.destroyablebushes"])

    def test_the_preview_is_bounded(self):
        root = _tmpdir("bound")
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        d = os.path.join(root, "txn")
        os.makedirs(d)
        for i in range(quarantine.NAME_PREVIEW + 4):
            os.makedirs(os.path.join(d, "m%02d" % i))
        s = quarantine.survey(root, _Journal([]))
        self.assertEqual(len(s["entries"][0]["names"]), quarantine.NAME_PREVIEW)


class TestModuleShape(unittest.TestCase):
    """The read path must stay free of writes, and the module of game literals."""

    def _src(self):
        with io.open(os.path.join(_REPO, "deckymod", "quarantine.py"),
                     encoding="utf-8") as f:
            return f.read()

    def test_no_game_literals_in_code(self):
        tree = ast.parse(self._src())
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef,
                                 ast.AsyncFunctionDef)):
                d = ast.get_docstring(node)
                if d:
                    docstrings.add(d)
        bad = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in docstrings:
                    continue
                low = node.value.lower()
                for word in ("stardew", "413150", "smapi", "stardewvalley"):
                    if word in low:
                        bad.append(node.value[:40])
        self.assertEqual(bad, [], "game literals in quarantine.py: %r" % (bad,))

    def test_the_read_path_still_never_writes(self):
        """survey()/describe() must not grow a write; reclaim() is the exception."""
        tree = ast.parse(self._src())
        banned = {"makedirs", "mkdir", "remove", "unlink", "rename", "replace",
                  "chmod", "symlink", "copy", "copy2", "move", "write",
                  "write_text", "write_bytes", "fsync", "truncate", "rmtree"}
        offenders = []
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            if node.name in ("reclaim",):
                continue          # the one deliberate exception, documented
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call):
                    continue
                fn = sub.func
                root = None
                if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                    if fn.value.id in ("os", "shutil"):
                        root = fn.attr
                if root in banned:
                    offenders.append("%s() calls %s" % (node.name, root))
                if isinstance(fn, ast.Name) and fn.id == "open":
                    offenders.append("%s() calls open()" % node.name)
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
