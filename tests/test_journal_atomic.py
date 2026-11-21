"""Atomic + durable journal writes (journal-hardener).

A crash / power loss must never leave a truncated JSONL line or a
half-overwritten snapshot. These tests pin the four properties of the
atomic-write helper used by Journal._append() and Journal.write_snapshot():

  * a normal append preserves all prior records and the exact line format;
  * write_snapshot() output stays readable by read_all();
  * if os.replace fails, the original journal bytes are untouched and no
    temp file is left behind;
  * fsync is actually invoked on the temp file, and a directory-fsync
    failure cannot turn a successful write into an error.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import deckymod.journal as journal  # noqa: E402
from deckymod.errors import ModError  # noqa: E402
from deckymod.journal import Journal  # noqa: E402


def _tmpdir(prefix="journal-atomic-"):
    """A temp dir under the repo, NOT tempfile.mkdtemp().

    mkdtemp() creates a 0o700 directory whose DACL rejects the sandboxed
    interpreter's later sub-create on Windows (WinError 5), which is an
    artefact of this dev box, not of Journal. Every other suite in this repo
    anchors its fixture the same way.
    """
    base = os.path.join(ROOT, ".decky-test-tmp", prefix + os.urandom(6).hex())
    os.makedirs(base, exist_ok=True)
    return base


class TestJournalAtomic(unittest.TestCase):
    def setUp(self):
        self.root = _tmpdir()
        self.data = os.path.join(self.root, "decky")
        self.logdir = os.path.join(self.root, "logs")
        self.j = Journal(self.data, self.logdir, "rimworld")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _raw(self):
        with open(self.j.journal_path, "rb") as f:
            return f.read()

    def _temp_names(self):
        return [n for n in os.listdir(self.j.journal_dir)
                if n.startswith(journal._TMP_PREFIX)]

    # 1. normal append preserves prior records
    def test_normal_append_preserves_prior_records_and_format(self):
        self.j.begin("txn1", "install", {"op": "install", "packageId": "a"})
        self.j.committed("txn1")
        self.j.begin("txn2", "uninstall", {"op": "uninstall"})

        rows = self.j.read_all()
        self.assertEqual([r["event"] for r in rows],
                         ["PREPARED", "COMMITTED", "PREPARED"])
        self.assertEqual([r["txn"] for r in rows], ["txn1", "txn1", "txn2"])

        # line format unchanged: one sorted-key JSON object per line
        lines = self._raw().decode("utf-8").splitlines()
        self.assertEqual(len(lines), 3)
        for ln in lines:
            obj = json.loads(ln)
            self.assertEqual(
                ln,
                json.dumps(obj, ensure_ascii=False, allow_nan=False, sort_keys=True),
            )
        self.assertEqual(self._temp_names(), [], "no temp file left after success")

    # 2. write_snapshot stays readable by read_all()
    def test_write_snapshot_stays_readable(self):
        p = self.j.write_snapshot("txn1", "state", b"hello world")
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"hello world")

        rows = self.j.read_all()
        snap = [r for r in rows if r.get("event") == "SNAPSHOT"]
        self.assertEqual(len(snap), 1)
        self.assertEqual(snap[0]["path"], p)
        self.assertEqual(snap[0]["bytes"], len(b"hello world"))
        self.assertEqual(self._temp_names(), [])

    # 3. os.replace failure: original bytes intact, no temp residue
    def test_replace_failure_keeps_original_bytes_and_cleans_temp(self):
        self.j.begin("txn1", "install", {"op": "install"})
        before = self._raw()

        with mock.patch.object(journal.os, "replace", side_effect=OSError("boom")):
            with self.assertRaises(ModError):
                self.j.committed("txn1")

        self.assertEqual(self._raw(), before, "target bytes must be untouched")
        self.assertEqual(self._temp_names(), [], "temp file must be cleaned up")

    # 4a. fsync is actually called (patchable) during an append
    def test_fsync_is_called_on_write(self):
        real_fsync = os.fsync
        with mock.patch.object(journal.os, "fsync", wraps=real_fsync) as fsync_mock:
            self.j.begin("txn1", "install", {"op": "install"})
        self.assertTrue(fsync_mock.called, "os.fsync must run during a journal write")

    # 4b. a directory-fsync failure does not break the write
    def test_directory_fsync_failure_does_not_break_write(self):
        self.j.begin("txn0", "install", {"op": "install"})
        before = self._raw()

        with mock.patch.object(journal, "_fsync_dir", side_effect=OSError("dir fsync fail")):
            self.j.committed("txn0")  # must NOT raise

        self.assertNotEqual(self._raw(), before, "the append must still land")
        self.assertEqual([r["event"] for r in self.j.read_all()],
                         ["PREPARED", "COMMITTED"])
        self.assertEqual(self._temp_names(), [])

    # extra: a malformed pre-existing line is dropped, never duplicated
    def test_malformed_lines_are_skipped_when_rebuilding(self):
        with open(self.j.journal_path, "w", encoding="utf-8") as f:
            f.write('{"event": "PREPARED", "txn": "good"}\n')
            f.write('{"event": "BROKEN"\n')  # truncated JSON
            f.write("\n")
        self.j.committed("good")
        rows = self.j.read_all()
        self.assertEqual([r["event"] for r in rows], ["PREPARED", "COMMITTED"])
        self.assertNotIn("BROKEN", self._raw().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
