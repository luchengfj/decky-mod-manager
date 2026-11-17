"""Tests for the read-only game Mod-directory identification layer (standard 4).

These are synthetic-tree tests. The SAME two templates are ALSO verified on the
real Deck in .decky-probe/r28_template_evidence.py (Cyberpunk 2077's real
archive/pc/content and DAVE THE DIVER's real Unity data directory); synthetic
tests alone are explicitly not accepted for standard 4.
"""

from __future__ import annotations

import os
import shutil
import unittest
import uuid

from deckymod import templates

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP = os.path.join(_ROOT, ".decky-test-tmp")


def _tmpdir() -> str:
    """Workspace-anchored scratch dir (avoids tempfile 0o700 DACL on Windows)."""
    os.makedirs(_TMP, exist_ok=True)
    path = os.path.join(_TMP, "tmpl_" + uuid.uuid4().hex[:8])
    os.makedirs(path, exist_ok=True)
    return path


class TestIdentify(unittest.TestCase):
    def setUp(self) -> None:
        self.root = _tmpdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_cyberpunk_template_points_at_real_archive_dir(self) -> None:
        moddir = os.path.join(self.root, "archive", "pc", "content")
        os.makedirs(moddir, exist_ok=True)
        r = templates.identify(1091500, self.root)
        self.assertTrue(r["adapted"])
        self.assertFalse(r["writable"])  # identification only
        self.assertEqual(len(r["mod_dirs"]), 1)
        self.assertEqual(r["mod_dirs"][0]["path"], moddir)
        self.assertTrue(r["mod_dirs"][0]["exists"])

    def test_dave_template_reports_missing_dir_honestly(self) -> None:
        r = templates.identify(1868140, self.root)
        self.assertTrue(r["adapted"])
        self.assertFalse(r["mod_dirs"][0]["exists"])  # BepInEx not installed

    def test_stardew_template_is_the_only_writable_one(self) -> None:
        os.makedirs(os.path.join(self.root, "Mods"), exist_ok=True)
        r = templates.identify(413150, self.root)
        self.assertTrue(r["adapted"])
        self.assertTrue(r["writable"])
        self.assertTrue(r["mod_dirs"][0]["exists"])

    def test_unknown_game_is_explicitly_not_adapted_and_guesses_nothing(self) -> None:
        r = templates.identify(230410, "/some/warframe")
        self.assertFalse(r["adapted"])
        self.assertEqual(r["note"], "not_adapted")
        self.assertEqual(r["mod_dirs"], [])
        self.assertIsNone(r["loader"])

    def test_bad_appid_never_raises(self) -> None:
        for value in (None, "abc", True, "", -1):
            r = templates.identify(value, "")
            self.assertFalse(r["adapted"])

    def test_known_appids_are_the_three_templates(self) -> None:
        self.assertEqual(templates.known_appids(), [413150, 1091500, 1868140])

    def test_every_template_carries_a_search_hint(self) -> None:
        """Round 36: picking a game must land on a search that can find its mods.

        A hint is metadata, so it has to be non-empty for every adapted game --
        otherwise the UI would fall back to the bare game name and search for
        something that matches nothing.
        """
        for appid in templates.known_appids():
            r = templates.identify(appid, self.root)
            self.assertTrue(r["adapted"], appid)
            hint = r.get("search_hint")
            self.assertIsInstance(hint, str, appid)
            self.assertTrue(hint.strip(), appid)

    def test_an_unadapted_game_gets_no_invented_hint(self) -> None:
        r = templates.identify(230410, self.root)
        self.assertFalse(r["adapted"])
        self.assertIsNone(r["search_hint"])


class TestScanMods(unittest.TestCase):
    """Round 37: "my mods, grouped by game".

    The plugin's journal only knows what IT installed, so a hand-modded game
    showed zero. scan_mods() reads the template directory and reports the
    folder names already present, without writing anything.
    """

    def setUp(self) -> None:
        self.root = _tmpdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_lists_existing_mod_folders_read_only(self) -> None:
        mods = os.path.join(self.root, "Mods")
        os.makedirs(os.path.join(mods, "Automate"), exist_ok=True)
        os.makedirs(os.path.join(mods, "ContentPatcher"), exist_ok=True)
        before = sorted(os.listdir(mods))
        r = templates.scan_mods(413150, self.root)
        self.assertTrue(r["adapted"])
        self.assertEqual(r["total_mods"], 2)
        self.assertEqual(r["mod_dirs"][0]["count"], 2)
        self.assertEqual(r["mod_dirs"][0]["mods"], ["Automate", "ContentPatcher"])
        # read-only: the directory is unchanged
        self.assertEqual(sorted(os.listdir(mods)), before)

    def test_ignores_dot_directories_and_loose_files(self) -> None:
        """Dot dirs are loader-invisible bookkeeping; loose files are not mods."""
        mods = os.path.join(self.root, "Mods")
        os.makedirs(os.path.join(mods, "RealMod"), exist_ok=True)
        os.makedirs(os.path.join(mods, ".decky-staging"), exist_ok=True)
        os.makedirs(os.path.join(mods, ".decky-quarantine"), exist_ok=True)
        with open(os.path.join(mods, "readme.txt"), "w", encoding="utf-8") as f:
            f.write("x")
        r = templates.scan_mods(413150, self.root)
        self.assertEqual(r["mod_dirs"][0]["mods"], ["RealMod"])
        self.assertEqual(r["total_mods"], 1)

    def test_missing_dir_reports_zero_not_an_error(self) -> None:
        r = templates.scan_mods(1868140, self.root)  # BepInEx not installed
        self.assertTrue(r["adapted"])
        self.assertFalse(r["mod_dirs"][0]["exists"])
        self.assertEqual(r["mod_dirs"][0]["mods"], [])
        self.assertEqual(r["mod_dirs"][0]["count"], 0)
        self.assertEqual(r["total_mods"], 0)

    def test_unadapted_game_scans_nothing(self) -> None:
        r = templates.scan_mods(230410, "/some/warframe")
        self.assertFalse(r["adapted"])
        self.assertEqual(r["note"], "not_adapted")
        self.assertEqual(r["mod_dirs"], [])
        self.assertEqual(r["total_mods"], 0)

    def test_a_bad_appid_never_raises(self) -> None:
        for value in (None, "abc", True, "", -1):
            r = templates.scan_mods(value, "")
            self.assertEqual(r["total_mods"], 0)

    def test_truncation_is_reported_rather_than_silent(self) -> None:
        mods = os.path.join(self.root, "Mods")
        os.makedirs(mods, exist_ok=True)
        for i in range(templates.MAX_MODS_PER_DIR + 5):
            os.makedirs(os.path.join(mods, "m%04d" % i), exist_ok=True)
        r = templates.scan_mods(413150, self.root)
        entry = r["mod_dirs"][0]
        self.assertEqual(entry["count"], templates.MAX_MODS_PER_DIR)
        self.assertTrue(entry["truncated"])


class TestListGamesCarriesTheScan(unittest.TestCase):
    def test_summarize_is_wrapped_so_every_game_gets_a_template_scan(self) -> None:
        """The RPC path must attach the scan; a bare summarize() would not.

        This pins the wiring in main.py rather than the helper: the failure it
        guards against is 'the helper exists but nobody calls it', which is how
        the mod list stayed empty for hand-modded games.
        """
        with open(os.path.join(_ROOT, "main.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("from deckymod import templates", src)
        self.assertIn("_with_game_mods(steamlib.summarize())", src)


if __name__ == "__main__":
    unittest.main()
