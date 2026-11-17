"""Round 48: quarantine audit -- unreachable data, and the wiring that shows it."""
import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_SAVED_GAME_ID = None


def setUpModule():
    global _SAVED_GAME_ID
    _SAVED_GAME_ID = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    if _SAVED_GAME_ID is not None:
        os.environ["DECKYMOD_GAME_ID"] = _SAVED_GAME_ID
    else:
        os.environ.pop("DECKYMOD_GAME_ID", None)


import uuid  # noqa: E402

from deckymod import quarantine  # noqa: E402


def _tmpdir(tag):
    base = r"C:\ai\SD\.decky-test-tmp"
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "r48_%s_%s" % (tag, uuid.uuid4().hex[:8]))


def _put(root, rel, data=b"x" * 10):
    full = os.path.join(root, rel)
    d = os.path.dirname(full)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(full, "wb") as f:
        f.write(data)


class _FakeJournal(object):
    """Just enough of Journal for referenced_txns()."""

    def __init__(self, records):
        self._records = records

    def read_all(self):
        return list(self._records)


class _BadJournal(object):
    def read_all(self):
        raise OSError("cannot read journal")


def _rec(txn, event="MOD_UNINSTALLED"):
    return {"event": event, "txn": txn, "packageId": "x"}


class TestReferencedTxns(unittest.TestCase):
    def test_only_uninstall_records_make_a_txn_restorable(self):
        j = _FakeJournal([
            _rec("t1", "MOD_UNINSTALLED"),
            _rec("t2", "COMMITTED"),
            _rec("t3", "MOD_INSTALLED"),
        ])
        got = quarantine.referenced_txns(j)
        self.assertEqual(got, {"t1"})

    def test_a_snapshot_record_does_not_make_a_txn_restorable(self):
        # Restoring a mod needs the original path and quarantine path, which
        # live on the uninstall record; a snapshot is about state files.
        j = _FakeJournal([_rec("t1", "SNAPSHOT")])
        self.assertEqual(quarantine.referenced_txns(j), set())

    def test_an_unreadable_journal_returns_none_not_an_empty_set(self):
        # None means "I cannot tell"; set() would mean "nobody claims these",
        # and only one of those is safe to act on.
        self.assertIsNone(quarantine.referenced_txns(_BadJournal()))

    def test_a_none_journal_returns_none(self):
        self.assertIsNone(quarantine.referenced_txns(None))


class TestSurvey(unittest.TestCase):
    def setUp(self):
        super(TestSurvey, self).setUp()
        self.root = _tmpdir("survey")
        self.q = os.path.join(self.root, "q")
        os.makedirs(self.q, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    def test_a_missing_quarantine_is_reported_not_failed(self):
        r = quarantine.survey(os.path.join(self.root, "nope"), None)
        self.assertTrue(r["checked"])
        self.assertFalse(r["exists"])
        self.assertEqual(r["reason"], "quarantine_missing")

    def test_a_restorable_folder_is_named_restorable(self):
        _put(self.q, "t1/mod/manifest.json")
        j = _FakeJournal([_rec("t1")])
        r = quarantine.survey(self.q, j)
        self.assertEqual(r["dirs"], 1)
        self.assertEqual(r["restorable"], 1)
        self.assertEqual(r["orphans"], 0)
        self.assertEqual(r["entries"][0]["state"], quarantine.RESTORABLE)
        self.assertTrue(r["entries"][0]["restorable"])

    def test_a_folder_with_no_journal_record_is_an_orphan(self):
        _put(self.q, "t9/mod/X.dll", b"y" * 100)
        j = _FakeJournal([_rec("t1")])
        r = quarantine.survey(self.q, j)
        self.assertEqual(r["orphans"], 1)
        self.assertEqual(r["entries"][0]["txn"], "t9")
        self.assertEqual(r["entries"][0]["state"], quarantine.ORPHAN)
        self.assertEqual(r["entries"][0]["bytes"], 100)

    def test_an_empty_folder_is_counted_but_not_worth_reporting(self):
        os.makedirs(os.path.join(self.q, "t2"))
        r = quarantine.survey(self.q, _FakeJournal([]))
        self.assertEqual(r["empty"], 1)
        self.assertEqual(quarantine.describe(r), "")

    def test_an_unreadable_journal_labels_everything_unknown(self):
        _put(self.q, "t1/mod/X.dll")
        r = quarantine.survey(self.q, _BadJournal())
        self.assertEqual(r["journal"], "unreadable")
        self.assertEqual(r["entries"][0]["state"], quarantine.UNKNOWN)
        self.assertEqual(r["orphans"], 0)
        self.assertEqual(quarantine.describe(r), "",
                         "unknown must never be presented as an orphan")

    def test_orphans_with_content_sort_first(self):
        _put(self.q, "empty_one/placeholder.txt", b"")
        os.remove(os.path.join(self.q, "empty_one", "placeholder.txt"))
        _put(self.q, "small/x.dll", b"a" * 10)
        _put(self.q, "big/x.dll", b"a" * 500)
        r = quarantine.survey(self.q, _FakeJournal([]))
        self.assertEqual(r["entries"][0]["txn"], "big")
        self.assertEqual(r["entries"][1]["txn"], "small")

    def test_rolling_up_totals_match_the_folders(self):
        _put(self.q, "a/x.bin", b"a" * 30)
        _put(self.q, "b/y.bin", b"b" * 20)
        r = quarantine.survey(self.q, _FakeJournal([]))
        self.assertEqual(r["total_bytes"], 50)
        self.assertEqual(r["dirs"], 2)

    def test_symlinked_directories_are_not_walked_into(self):
        # A link points at data this scan does not own; following it would
        # double-count and could walk outside the quarantine entirely.
        os.makedirs(os.path.join(self.root, "outside"))
        _put(self.root, "outside/big.bin", b"z" * 1000)
        txn_dir = os.path.join(self.q, "t1")
        os.makedirs(txn_dir)
        try:
            os.symlink(os.path.join(self.root, "outside"),
                       os.path.join(txn_dir, "link"))
        except (OSError, NotImplementedError, AttributeError):
            self.skipTest("symlink creation unavailable")
        r = quarantine.survey(self.q, _FakeJournal([]))
        self.assertLess(r["total_bytes"], 1000)

    def test_disabled_in_descriptor_short_circuits(self):
        r = quarantine.survey(self.q, None, {"enabled": False})
        self.assertFalse(r["checked"])
        self.assertEqual(r["reason"], "disabled_in_descriptor")

    def test_the_dir_cap_sets_truncated(self):
        for i in range(6):
            _put(self.q, "t%d/x.bin" % i)
        r = quarantine.survey(self.q, _FakeJournal([]), {"max_dirs": 3})
        self.assertTrue(r["truncated"])
        self.assertEqual(r["dirs"], 3)


class TestDescribe(unittest.TestCase):
    def test_only_orphans_holding_bytes_are_named(self):
        result = {"checked": True, "entries": [
            {"txn": "a", "state": "orphan", "bytes": 114308},
            {"txn": "b", "state": "orphan", "bytes": 0},
            {"txn": "c", "state": "restorable", "bytes": 999},
        ]}
        text = quarantine.describe(result)
        self.assertIn("a", text)
        self.assertNotIn("b (", text)
        self.assertNotIn("c", text)
        self.assertIn("114308", text)

    def test_more_than_the_limit_is_summarised(self):
        result = {"checked": True, "entries": [
            {"txn": "a", "state": "orphan", "bytes": 1},
            {"txn": "b", "state": "orphan", "bytes": 1},
            {"txn": "c", "state": "orphan", "bytes": 1},
        ]}
        self.assertIn("+1 more", quarantine.describe(result, limit=2))

    def test_an_unchecked_scan_describes_nothing(self):
        self.assertEqual(quarantine.describe({"checked": False}), "")


class TestModuleShape(unittest.TestCase):
    def _src(self):
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "deckymod", "quarantine.py")
        with io.open(p, encoding="utf-8") as f:
            return f.read()

    def test_module_contains_no_game_specific_literal(self):
        low = self._src().lower()
        for word in ("stardew", "413150", "smapi", "stardewvalley"):
            self.assertNotIn(word, low)

    def test_only_reclaim_may_write_or_delete(self):
        # Round 48's rule was "this module never deletes anything". Round 54
        # added the one path that does -- ``reclaim()`` -- because a folder the
        # journal can no longer restore is a folder the user may legitimately
        # want gone. So the claim narrows rather than disappears: every OTHER
        # function in the module is still read-only, and reclaim() is the only
        # name allowed to touch the filesystem destructively.
        #
        # A plugin that deletes folders it did not create is one bug away from
        # deleting a wanted mod; the point of this test is that the set of such
        # functions is exactly one, and that nobody grew a second one silently.
        import ast
        tree = ast.parse(self._src())
        banned = {"makedirs", "mkdir", "remove", "unlink", "rmtree", "rename",
                  "replace", "chmod", "symlink", "copy", "copy2", "move",
                  "write", "write_text", "write_bytes", "fsync", "truncate"}
        offenders = {}
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            hits = set()
            for inner in ast.walk(node):
                if not isinstance(inner, ast.Call):
                    continue
                f = inner.func
                if isinstance(f, ast.Name) and f.id in banned:
                    hits.add(f.id)
                elif isinstance(f, ast.Attribute) and f.attr in banned:
                    hits.add(f.attr)
            if hits:
                offenders[node.name] = hits
        self.assertEqual(sorted(offenders), ["reclaim"],
                         "only reclaim() may delete: %r" % offenders)
        self.assertNotIn("open", offenders.get("reclaim", set()))


class TestStatusWiring(unittest.TestCase):
    def test_status_carries_the_quarantine_report(self):
        with io.open(os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "deckymod", "smapi.py"),
                encoding="utf-8") as f:
            src = f.read()
        self.assertIn("quarantine.survey", src)
        self.assertIn('"quarantine": quar_info', src)
        self.assertIn("quarantine", src.split("from . import")[1].split("\n")[0])
