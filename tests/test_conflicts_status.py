"""Does status() actually report conflicts? (round 47)

A unit test on deckymod/conflicts.py cannot catch a status() that never calls
it. This drives the real file_drop engine over a real tree.
"""

import io
import os
import sys
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.pop("DECKYMOD_GAME_ID", None)

# test_mvp.py pins DECKYMOD_GAME_ID=rimworld with setdefault at import time, and
# unittest discovery imports every module BEFORE running any of them -- so a
# pop at import time here runs too early and the pin is back by the time a test
# executes (E_GAME_NOT_FOUND: AppID 294100). The pop has to happen at run time.
_SAVED_GAME_ID = None


def setUpModule():
    global _SAVED_GAME_ID
    _SAVED_GAME_ID = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    if _SAVED_GAME_ID is not None:
        os.environ["DECKYMOD_GAME_ID"] = _SAVED_GAME_ID
    else:
        os.environ.pop("DECKYMOD_GAME_ID", None)

from deckymod.journal import Journal  # noqa: E402
from deckymod.smapi import StardewEngine  # noqa: E402

from tests.test_stardew import StardewTree  # noqa: E402


def _put(root, rel, data=b"x"):
    full = os.path.join(root, rel)
    d = os.path.dirname(full)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(full, "wb") as f:
        f.write(data)


class TestConflictsThroughStatus(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in (
            "DECKY_USER_HOME", "XDG_CONFIG_HOME", "DECKYMOD_INBOX",
            "DECKYMOD_DATA", "DECKYMOD_STEAM_ROOT",
            "DECKY_PLUGIN_RUNTIME_DIR", "DECKY_PLUGIN_LOG_DIR")}
        self.tree = StardewTree()
        self.tree.env()  # mutates os.environ, returns None
        self.eng = StardewEngine(
            journal=Journal(self.tree.data, os.path.join(self.tree.data, "logs")))

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _status(self):
        st = self.eng.status()
        self.assertTrue(st.get("ok"), st)
        state = st["data"]["state"]
        self.assertIn("conflicts", state, "status() must carry the conflict scan")
        return state["conflicts"]

    def test_the_shipped_descriptor_declares_a_per_mod_directory_loader(self):
        # The real Stardew descriptor says its loader gives every mod its own
        # folder. Reporting shared relative paths there is meaningless, so
        # status() must say why instead of printing 27 false alarms -- which is
        # exactly what the device measured before this scope existed.
        c = self._status()
        self.assertFalse(c["checked"])
        self.assertEqual(c["reason"], "per_mod_directory_loader")
        self.assertEqual(c["total"], 0)
        self.assertEqual(c["conflicts"], [])

    def test_two_mods_shipping_the_same_file_are_reported_under_a_shared_tree(self):
        # Same tree, but told this loader copies everything into one directory:
        # now a shared path IS a collision and must be reported.
        _put(self.tree.mods, "Alpha/Alpha.dll")
        _put(self.tree.mods, "Beta/Alpha.dll")
        from deckymod import smapi as smod
        real = smod.StardewEngine._mod_package
        smod.StardewEngine._mod_package = lambda self: {
            "conflicts": {"enabled": True, "scope": "shared_tree",
                          "ignore": ["manifest.json"], "max_files_per_mod": 2000,
                          "max_conflicts": 50}}
        try:
            c = self._status()
        finally:
            smod.StardewEngine._mod_package = real
        self.assertTrue(c["checked"])
        self.assertEqual(c["total"], 1, c)
        self.assertEqual(c["conflicts"][0]["mods"], ["Alpha", "Beta"])

    def test_a_mod_with_no_manifest_still_participates(self):
        # The conflict is about the directory contents, not about whether the
        # manifest parses -- an unreadable manifest must not hide a real clash.
        _put(self.tree.mods, "Alpha/Alpha.dll")
        _put(self.tree.mods, "Junk/Alpha.dll")
        from deckymod import smapi as smod
        real = smod.StardewEngine._mod_package
        smod.StardewEngine._mod_package = lambda self: {
            "conflicts": {"enabled": True, "scope": "shared_tree",
                          "ignore": ["manifest.json"]}}
        try:
            c = self._status()
        finally:
            smod.StardewEngine._mod_package = real
        self.assertTrue(c["checked"])
        self.assertEqual(c["total"], 1, c)

    def test_status_stays_ok_when_the_scan_raises(self):
        from deckymod import conflicts as cmod
        real = cmod.survey
        cmod.survey = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            st = self.eng.status()
            self.assertTrue(st.get("ok"), "a failed conflict scan must not fail status")
            got = st["data"]["state"]["conflicts"]
            self.assertFalse(got["checked"])
            self.assertIn("boom", got.get("detail") or "")
        finally:
            cmod.survey = real
