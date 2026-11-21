"""Goal item 2: enumerate Steam libraries and the games installed in them.

Why this test exists: ``steamlib`` is the only module that reports on games the
plugin was never told about. Everything else resolves one appid from a
descriptor, so a bug here is invisible to the rest of the suite. It is also the
module most exposed to real-world variance — SD cards, Flakpak Steam, a library
declared in libraryfolders.vdf that is no longer mounted, and an appmanifest that
is half-written.

All synthetic: a fake steam root, a fake SD card root, fake manifests. Nothing
here reads the real Steam installation, so it runs identically on the Windows dev
box and on the Deck.
"""

from __future__ import annotations

import os
import unittest
import uuid

from deckymod import steamlib

# libraryfolders.vdf as Steam actually writes it: a "libraryfolders" block whose
# children are numeric keys, each with a "path" and a "label".
# NOTE: this is filled with str.replace, not str.format — a vdf is full of literal
# braces and .format() would read them as fields.
LIBRARY_FOLDERS = """\"libraryfolders\"
{
\t\"0\"
\t{
\t\t\"path\"\t\t\"@ROOT0@\"
\t\t\"label\"\t\t\"\"
\t\t\"contentid\"\t\t\"0\"
\t}
\t\"1\"
\t{
\t\t\"path\"\t\t\"@ROOT1@\"
\t\t\"label\"\t\t\"SDCARD\"
\t}
}
"""


def _vdf(root0: str, root1: str) -> str:
    return LIBRARY_FOLDERS.replace("@ROOT0@", root0).replace("@ROOT1@", root1)

# A complete manifest, as opposed to the partial one below.
MANIFEST_FULL = """\"AppState\"
{
\t\"appid\"\t\t\"@APPID@\"
\t\"name\"\t\t\"@NAME@\"
\t\"StateFlags\"\t\t\"4\"
\t\"installdir\"\t\t\"@INSTALLDIR@\"
\t\"SizeOnDisk\"\t\t\"123456\"
}
"""


def _tmpdir() -> str:
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        ".decky-test-tmp")
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, "steamlib_" + uuid.uuid4().hex[:8])
    os.makedirs(path, exist_ok=True)
    return path


class _Tree(unittest.TestCase):
    """Two libraries, three games, one of them with a Proton prefix."""

    def setUp(self) -> None:
        self.base = _tmpdir()
        self.home = os.path.join(self.base, "home")
        self.root0 = os.path.join(self.home, ".local", "share", "Steam")
        self.root1 = os.path.join(self.base, "run", "media", "deck", "SDCARD")
        for root in (self.root0, self.root1):
            os.makedirs(os.path.join(root, "steamapps", "common"), exist_ok=True)

        with open(os.path.join(self.root0, "steamapps", "libraryfolders.vdf"),
                  "w", encoding="utf-8") as f:
            f.write(_vdf(self.root0.replace("\\", "/"), self.root1.replace("\\", "/")))

        self._manifest(self.root0, 413150, "Stardew Valley", "Stardew Valley", state=4)
        self._manifest(self.root0, 1091500, "Cyberpunk 2077", "Cyberpunk 2077", state=4)
        self._manifest(self.root1, 892970, "Valheim", "Valheim", state=4)
        # A partially-downloaded title must be surfaced as incomplete, not hidden.
        self._manifest(self.root0, 570, "Dota 2", "dota 2 beta", state=1026)

        # Only one of the three has ever run under Proton.
        os.makedirs(os.path.join(self.root0, "steamapps", "compatdata", "1091500"),
                    exist_ok=True)

        self._saved_home = os.environ.get("DECKY_USER_HOME")
        os.environ["DECKY_USER_HOME"] = self.home
        os.environ.pop("DECKYMOD_STEAM_ROOT", None)

    def tearDown(self) -> None:
        if self._saved_home is None:
            os.environ.pop("DECKY_USER_HOME", None)
        else:
            os.environ["DECKY_USER_HOME"] = self._saved_home

    def _manifest(self, root: str, appid: int, name: str, installdir: str,
                  *, state: int = 4) -> None:
        body = (MANIFEST_FULL.replace("@APPID@", str(appid))
                        .replace("@NAME@", name)
                        .replace("@INSTALLDIR@", installdir))
        if state != 4:
            body = body.replace('"StateFlags"\t\t"4"', '"StateFlags"\t\t"%d"' % state)
        with open(os.path.join(root, "steamapps", "appmanifest_%d.acf" % appid),
                  "w", encoding="utf-8") as f:
            f.write(body)


class TestLibraryRoots(_Tree):
    def test_reads_both_libraries_out_of_the_vdf(self) -> None:
        roots = steamlib.library_roots(self.home)
        paths = [r["path"] for r in roots]
        self.assertIn(os.path.realpath(self.root0), paths)
        self.assertIn(os.path.realpath(self.root1), paths)

    def test_marks_the_removable_one(self) -> None:
        by_path = {r["path"]: r for r in steamlib.library_roots(self.home)}
        self.assertTrue(by_path[os.path.realpath(self.root1)]["removable"])
        self.assertFalse(by_path[os.path.realpath(self.root0)]["removable"])

    def test_ignores_a_declared_library_that_is_gone(self) -> None:
        with open(os.path.join(self.root0, "steamapps", "libraryfolders.vdf"),
                  "w", encoding="utf-8") as f:
            f.write(_vdf(self.root0.replace("\\", "/"), "/run/media/deck/UNPLUGGED"))
        paths = [r["path"] for r in steamlib.library_roots(self.home)]
        self.assertIn(os.path.realpath(self.root0), paths)
        self.assertNotIn("/run/media/deck/UNPLUGGED", paths)

    def test_no_duplicates_when_the_vdf_repeats_a_root(self) -> None:
        with open(os.path.join(self.root0, "steamapps", "libraryfolders.vdf"),
                  "w", encoding="utf-8") as f:
            f.write(_vdf(self.root0.replace("\\", "/"), self.root0.replace("\\", "/")))
        roots = steamlib.library_roots(self.home)
        self.assertEqual(len(roots), len({r["path"] for r in roots}))


class TestScanGames(_Tree):
    def test_lists_every_manifest_across_libraries(self) -> None:
        games = steamlib.scan_games(self.home)
        self.assertEqual(sorted(g["appid"] for g in games),
                         sorted([570, 892970, 1091500, 413150]))

    def test_surfaces_appid_path_and_prefix(self) -> None:
        games = {g["appid"]: g for g in steamlib.scan_games(self.home)}
        cp = games[1091500]
        self.assertEqual(cp["name"], "Cyberpunk 2077")
        self.assertEqual(cp["installdir"], "Cyberpunk 2077")
        self.assertTrue(cp["install_path"].endswith(os.path.join("common", "Cyberpunk 2077")))
        self.assertTrue(cp["compatdata"])
        self.assertTrue(cp["compatdata"].endswith(os.path.join("compatdata", "1091500")))

    def test_native_game_has_no_prefix_rather_than_an_error(self) -> None:
        games = {g["appid"]: g for g in steamlib.scan_games(self.home)}
        self.assertIsNone(games[413150]["compatdata"])
        self.assertEqual(games[413150]["state"], "installed")

    def test_incomplete_install_is_reported_as_such(self) -> None:
        games = {g["appid"]: g for g in steamlib.scan_games(self.home)}
        self.assertEqual(games[570]["state"], "incomplete")
        self.assertEqual(games[570]["state_flags"], 1026)

    def test_the_sd_card_game_keeps_its_library_and_flag(self) -> None:
        games = {g["appid"]: g for g in steamlib.scan_games(self.home)}
        self.assertTrue(games[892970]["removable"])
        self.assertEqual(games[892970]["library"], os.path.realpath(self.root1))

    def test_folder_without_a_manifest_is_not_a_steam_game(self) -> None:
        # This is the trap: a folder under common/ proves nothing.
        os.makedirs(os.path.join(self.root0, "steamapps", "common", "Orphan Game"),
                    exist_ok=True)
        names = [g["name"] for g in steamlib.scan_games(self.home)]
        self.assertNotIn("Orphan Game", names)

    def test_unreadable_manifest_does_not_abort_the_scan(self) -> None:
        with open(os.path.join(self.root0, "steamapps", "appmanifest_999.acf"),
                  "w", encoding="utf-8") as f:
            f.write("this is not a vdf { { {")
        games = steamlib.scan_games(self.home)
        ids = [g["appid"] for g in games]
        self.assertIn(999, ids)
        self.assertIn(413150, ids)
        self.assertEqual({g["appid"]: g for g in games}[999]["state"], "unknown")

    def test_missing_installdir_falls_back_to_appid_not_empty_name(self) -> None:
        with open(os.path.join(self.root0, "steamapps", "appmanifest_777.acf"),
                  "w", encoding="utf-8") as f:
            f.write('"AppState"\n{\n\t"appid"\t\t"777"\n\t"StateFlags"\t\t"4"\n}\n')
        games = {g["appid"]: g for g in steamlib.scan_games(self.home)}
        self.assertEqual(games[777]["name"], "777")
        self.assertEqual(games[777]["install_path"], "")

    def test_scan_is_read_only(self) -> None:
        before = sorted(os.listdir(os.path.join(self.root0, "steamapps")))
        steamlib.scan_games(self.home)
        after = sorted(os.listdir(os.path.join(self.root0, "steamapps")))
        self.assertEqual(before, after)


class TestSdCardLayouts(unittest.TestCase):
    """The two mount layouts SteamOS actually produces must both be discovered.

    Criterion 1 spells them out:

        /run/media/mmcblk0p1        card mounted directly at the parent
        /run/media/deck/mmcblk0p1   card mounted under the user directory

    Neither may be hard-coded: the label is a device name on one card and a
    user-chosen label on another. This drives ``_sd_card_libraries`` with an
    explicit parent so the assertion is about the scan, not about this machine
    happening to have a card inserted.
    """

    def setUp(self) -> None:
        self.base = _tmpdir()
        self.parent = os.path.join(self.base, "run", "media")
        os.makedirs(self.parent, exist_ok=True)

    def _card(self, *parts: str) -> str:
        root = os.path.join(self.parent, *parts)
        os.makedirs(os.path.join(root, "steamapps", "common"), exist_ok=True)
        return root

    def test_card_mounted_at_the_parent_is_discovered(self) -> None:
        root = self._card("mmcblk0p1")
        found = [os.path.realpath(p) for p in
                 steamlib._sd_card_libraries([self.parent])]
        self.assertIn(os.path.realpath(root), found)

    def test_card_mounted_under_the_user_dir_is_discovered(self) -> None:
        root = self._card("deck", "mmcblk0p1")
        found = [os.path.realpath(p) for p in
                 steamlib._sd_card_libraries([self.parent])]
        self.assertIn(os.path.realpath(root), found)

    def test_both_layouts_at_once_are_both_found(self) -> None:
        flat = self._card("mmcblk0p1")
        nested = self._card("deck", "mmcblk0p1")
        found = {os.path.realpath(p) for p in
                 steamlib._sd_card_libraries([self.parent])}
        self.assertIn(os.path.realpath(flat), found)
        self.assertIn(os.path.realpath(nested), found)

    def test_a_mount_without_steamapps_is_not_a_library(self) -> None:
        os.makedirs(os.path.join(self.parent, "mmcblk0p2", "DCIM"), exist_ok=True)
        found = [os.path.realpath(p) for p in
                 steamlib._sd_card_libraries([self.parent])]
        self.assertNotIn(os.path.realpath(
            os.path.join(self.parent, "mmcblk0p2")), found)

    def test_nested_scan_does_not_confuse_a_game_folder_for_a_library(self) -> None:
        # /run/media/<user>/<label> is one level deep; a stray subdirectory of a
        # mounted card must not be mistaken for its own Steam library.
        self._card("deck", "CARD")
        os.makedirs(os.path.join(self.parent, "deck", "CARD", "steamapps",
                                 "common", "Some Game"), exist_ok=True)
        found = [os.path.realpath(p) for p in
                 steamlib._sd_card_libraries([self.parent])]
        bad = os.path.realpath(os.path.join(self.parent, "deck", "CARD",
                                            "steamapps", "common", "Some Game"))
        self.assertNotIn(bad, found)


class TestSummarize(_Tree):
    def test_counts_match_the_listing(self) -> None:
        s = steamlib.summarize(self.home)
        self.assertEqual(s["game_count"], 4)
        self.assertEqual(s["library_count"], 2)
        self.assertEqual(s["removable_count"], 1)
        self.assertEqual(s["with_prefix_count"], 1)
        self.assertEqual(len(s["games"]), 4)

    def test_empty_home_yields_empty_lists_not_an_exception(self) -> None:
        lonely = os.path.join(self.base, "nobody")
        os.makedirs(lonely, exist_ok=True)
        s = steamlib.summarize(lonely)
        self.assertEqual(s["games"], [])
        self.assertEqual(s["game_count"], 0)


class TestRuntimeFiltering(_Tree):
    """Steam ships Proton / the Linux Runtime as appmanifests; they are tools,
    not games. They must never appear in the game list or counts. Regression
    for the device showing 29 "games" of which 8 were Steam infrastructure.
    """

    RUNTIMES = [
        (228980, "Steamworks Common Redistributables", "Steamworks Shared"),
        (1070560, "Steam Linux Runtime 1.0 (scout)", "SteamLinuxRuntime"),
        (1391110, "Steam Linux Runtime 2.0 (soldier)", "SteamLinuxRuntime_soldier"),
        (1628350, "Steam Linux Runtime 3.0 (sniper)", "SteamLinuxRuntime_sniper"),
        (4183110, "Steam Linux Runtime 4.0", "SteamLinuxRuntime_4"),
        (1493710, "Proton Experimental", "Proton - Experimental"),
        (3658110, "Proton 10.0", "Proton 10.0"),
        (4628710, "Proton 11.0", "Proton 11.0"),
    ]

    def test_known_runtime_appids_are_filtered(self):
        for appid, name, installdir in self.RUNTIMES:
            self._manifest(self.root0, appid, name, installdir, state=4)
        games = {g["appid"]: g for g in steamlib.scan_games(self.home)}
        for appid, _, _ in self.RUNTIMES:
            self.assertNotIn(appid, games, "runtime %s must be filtered" % appid)
        # Real games from the tree are all still there.
        for appid in (413150, 1091500, 892970, 570):
            self.assertIn(appid, games)

    def test_prefix_filters_future_runtime_versions(self):
        # A future Proton 99 with an unknown AppID is still caught by prefix.
        self._manifest(self.root0, 9999999, "Proton 99.0", "Proton 99.0", state=4)
        self._manifest(self.root0, 9999998, "Steam Linux Runtime 9.0",
                       "SteamLinuxRuntime_9", state=4)
        ids = {g["appid"] for g in steamlib.scan_games(self.home)}
        self.assertNotIn(9999999, ids)
        self.assertNotIn(9999998, ids)

    def test_prefix_does_not_drop_a_real_game_mentioning_proton(self):
        # A game whose NAME merely contains "Proton" must survive: filtering
        # uses startswith on specific runtime prefixes, not substring.
        self._manifest(self.root0, 5555555, "Proton Glow Racing",
                       "Proton Glow Racing", state=4)
        ids = {g["appid"] for g in steamlib.scan_games(self.home)}
        self.assertIn(5555555, ids)

    def test_summarize_counts_only_real_games_with_runtimes_present(self):
        for appid, name, installdir in self.RUNTIMES:
            self._manifest(self.root0, appid, name, installdir, state=4)
        s = steamlib.summarize(self.home)
        self.assertEqual(s["game_count"], 4, "runtimes must not inflate the count")
        self.assertEqual(len(s["games"]), 4)


if __name__ == "__main__":
    unittest.main()
