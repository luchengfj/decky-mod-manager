"""Round 80 — deleting the source ZIP after a successful install (opt-in).

The user taps "import and delete the ZIP"; the backend half is
``FileDropEngine.delete_source_zip``. Its scope guards are the contract:

  * the path must sit inside a DECLARED import root (inbox / Downloads) —
    anything else is E_PATH_ESCAPE, so this can never become a general file
    deleter;
  * a missing file is E_INBOX_UNREADABLE (honest), not a silent ok;
  * the removal is journaled for traceability.

Reuses the synthetic second-game tree; nothing is mocked.
"""
import json
import os
import shutil
import sys
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deckymod.journal import Journal
from deckymod.registry import Registry
from deckymod.smapi import FileDropEngine
from test_second_game import SecondTree, _zip, MANIFEST

_PREV = None


def setUpModule():
    global _PREV
    _PREV = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    if _PREV is not None:
        os.environ["DECKYMOD_GAME_ID"] = _PREV
    else:
        os.environ.pop("DECKYMOD_GAME_ID", None)


class TestDeleteSourceZip(unittest.TestCase):
    def setUp(self):
        self.t = SecondTree()
        self.t.env()
        self.addCleanup(self.t.cleanup)
        self.eng = self.t.engine()

    def _zip_in_inbox(self, name="mod.zip"):
        zp = os.path.join(self.t.inbox, name)
        _zip(zp, {"mod.json": json.dumps(MANIFEST), "data.dat": b"\x00"}, wrapper="M")
        return zp

    def test_a_zip_inside_a_declared_root_is_removed(self):
        zp = self._zip_in_inbox()
        r = self.eng.delete_source_zip(zp)
        self.assertTrue(r["ok"], r)
        self.assertFalse(os.path.exists(zp))
        # traceability: the journal remembers the removal
        log = open(self.eng.journal.log_path, encoding="utf-8").read()
        self.assertIn("source zip removed", log)
        self.assertIn(os.path.basename(zp), log)

    def test_a_path_outside_every_import_root_is_refused(self):
        outside = os.path.join(self.t.base, "not-a-root", "evil.zip")
        os.makedirs(os.path.dirname(outside), exist_ok=True)
        with open(outside, "wb") as f:
            f.write(b"MZ")
        r = self.eng.delete_source_zip(outside)
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "E_PATH_ESCAPE")
        self.assertTrue(os.path.exists(outside))   # untouched

    def test_a_missing_file_is_honest_not_silent(self):
        r = self.eng.delete_source_zip(os.path.join(self.t.inbox, "gone.zip"))
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "E_INBOX_UNREADABLE")

    def test_an_empty_path_is_refused(self):
        r = self.eng.delete_source_zip("")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "E_PATH_INVALID")

    def test_the_loader_zip_flow_shares_the_same_guards(self):
        # RootMergeEngine inherits delete_source_zip: a loader ZIP extracted
        # via install_loader can be cleaned the same way.
        from deckymod.root_merge import RootMergeEngine
        self.t.rewrite_descriptor({**json.loads(json.dumps({
            "schema": 1, "id": "secondgame", "status": "enabled",
            "engine": "root_merge",
            "identity": {"appid": 990001, "name": "Second Game",
                         "platform": "windows-proton", "status": "synthetic"},
            "paths": {"game_root": "${GAME_ROOT}", "mod_root": None,
                      "write_roots": ["BepInEx/plugins"],
                      "root_file_target": "BepInEx/plugins",
                      "loader_root": "${GAME_ROOT}",
                      "staging": "${GAME_ROOT}/.decky-staging",
                      "quarantine": "${GAME_ROOT}/.decky-quarantine/${TXN_ID}"},
            "mod_package": {"archive_format": "zip", "parser": "path_map",
                            "strip_single_root": True},
            "capabilities": {"local_import": True, "uninstall_quarantine": True,
                             "rollback": True, "loader_install": True},
            "safety": {"refuse_if_game_running": False},
            "known_limitations": [], "known_limitation_keys": [],
        }))})
        eng = RootMergeEngine(
            registry=self.t.registry(),
            journal=Journal(self.t.data, self.t.logs, "secondgame"))
        zp = self._zip_in_inbox("loader.zip")
        r = eng.delete_source_zip(zp)
        self.assertTrue(r["ok"], r)
        self.assertFalse(os.path.exists(zp))


if __name__ == "__main__":
    unittest.main()
