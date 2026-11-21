"""Round 76 — root_merge routing rules (Cyberpunk 2077).

The whole safety story of this engine is "where does a file land". These tests
pin that decision for every shape a real Cyberpunk archive takes, plus the two
refusal paths (protected game payload, path escape) that must never regress.

No test here touches a real game folder or the network: the engine's routing
needs only the descriptor, so a temporary registry is enough.
"""
import json
import os
import shutil
import tempfile
import unittest
import zipfile

from deckymod.journal import Journal
from deckymod.registry import Registry
from deckymod.root_merge import RootMergeEngine, _is_unsafe, _norm


_PINNED = None


def setUpModule():
    """Other suites pin DECKYMOD_GAME_ID=rimworld; that pin would hide this
    module's own registry, so it is parked for the duration of these tests."""
    global _PINNED
    _PINNED = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    if _PINNED is not None:
        os.environ["DECKYMOD_GAME_ID"] = _PINNED


def _make_engine(base: str) -> RootMergeEngine:
    """Engine bound to a throwaway registry that contains ONLY cyberpunk."""
    os.makedirs(os.path.join(base, "registry", "games"), exist_ok=True)
    shutil.copy(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "registry", "games", "cyberpunk.json"),
                os.path.join(base, "registry", "games", "cyberpunk.json"))
    with open(os.path.join(base, "registry", "registry.json"), "w", encoding="utf-8") as f:
        json.dump({
            "schema": "deckymod/game-registry@1",
            "version": "0.0.0-test",
            "active_game": "cyberpunk",
            "capability_gate": {"enabled_game_status": "enabled",
                                "max_enabled_games_in_mvp": 1,
                                "refuse_if_status_not_enabled": True,
                                "refuse_if_capability_false": True},
            "descriptors": {"cyberpunk": {"file": "registry/games/cyberpunk.json"}},
            "loader_catalog": {},
        }, f, indent=1)
    data = os.path.join(base, "data")
    journal = Journal(data, os.path.join(data, "logs"), "cyberpunk")
    return RootMergeEngine(registry=Registry(base), journal=journal)


class TestPathNormalisation(unittest.TestCase):
    def test_windows_separators_are_normalised(self):
        self.assertEqual(_norm("archive\\pc\\mod\\a.archive"), "archive/pc/mod/a.archive")

    def test_leading_slash_and_dot_slash_are_stripped(self):
        self.assertEqual(_norm("/mods/x/info.json"), "mods/x/info.json")
        self.assertEqual(_norm("./mods/x/info.json"), "mods/x/info.json")

    def test_traversal_is_unsafe(self):
        self.assertTrue(_is_unsafe("../etc/passwd"))
        self.assertTrue(_is_unsafe("mods/../../x"))
        self.assertTrue(_is_unsafe(""))
        self.assertTrue(_is_unsafe("C:/windows/system32"))

    def test_ordinary_paths_are_safe(self):
        self.assertFalse(_is_unsafe("archive/pc/mod/a.archive"))
        self.assertFalse(_is_unsafe("r6/scripts/x.reds"))


class TestRouting(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.eng = _make_engine(self.tmp)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_a_bare_archive_goes_to_archive_pc_mod(self):
        self.assertEqual(self.eng._route("CoolMod.archive"),
                         "archive/pc/mod/CoolMod.archive")

    def test_a_bare_reds_goes_to_r6_scripts(self):
        self.assertEqual(self.eng._route("tweak.reds"), "r6/scripts/tweak.reds")

    def test_an_explicit_path_under_a_write_root_is_kept(self):
        self.assertEqual(self.eng._route("archive/pc/mod/A/x.archive"),
                         "archive/pc/mod/A/x.archive")
        self.assertEqual(self.eng._route("mods/MyMod/info.json"),
                         "mods/MyMod/info.json")
        self.assertEqual(self.eng._route("bin/x64/plugins/cyber_engine_tweaks/mods/X/init.lua"),
                         "bin/x64/plugins/cyber_engine_tweaks/mods/X/init.lua")
        self.assertEqual(self.eng._route("r6/scripts/Foo.reds"), "r6/scripts/Foo.reds")

    def test_an_unroutable_file_is_refused_not_guessed(self):
        # A .dll at the archive root could mean CET, RED4ext or something else;
        # guessing would write into the game root. Refuse instead.
        self.assertIsNone(self.eng._route("plugin.dll"))
        self.assertIsNone(self.eng._route("content/data.archive"))

    def test_protected_paths_are_recognised(self):
        self.assertTrue(self.eng._is_protected("archive/pc/content/basegame_1_archive"))
        self.assertTrue(self.eng._is_protected("archive/pc/ep1/x.archive"))
        self.assertTrue(self.eng._is_protected("engine/config.ini"))
        self.assertFalse(self.eng._is_protected("archive/pc/mod/x.archive"))
        self.assertFalse(self.eng._is_protected("mods/X/info.json"))

    def test_junk_and_root_docs_are_ignored(self):
        self.assertTrue(self.eng._is_junk("__MACOSX/._x.archive"))
        self.assertTrue(self.eng._is_junk(".DS_Store"))
        self.assertTrue(self.eng._is_root_doc("readme.txt"))
        self.assertFalse(self.eng._is_root_doc("archive/pc/mod/readme.txt"))


class TestUserDefinedPackage(unittest.TestCase):
    """A user-added game receives ordinary "one folder + loader tree" zips."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.eng = _make_engine(self.tmp)
        # Turn it into a user-defined shape: one root, strip enabled.
        self.eng.registry.descriptors[self.eng.game_id]["paths"] = {
            "game_root": "${GAME_ROOT}", "mod_root": None,
            "write_roots": ["BepInEx/plugins"],
            "root_file_target": "BepInEx/plugins",
        }
        self.eng.registry.descriptors[self.eng.game_id]["mod_package"] = {
            "parser": "path_map", "strip_single_root": True}
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _zip(self, members):
        path = os.path.join(self.tmp, "mod.zip")
        with zipfile.ZipFile(path, "w") as zf:
            for name, data in members.items():
                zf.writestr(name, data)
        return path

    def test_a_one_folder_package_keeps_its_folder_under_the_target(self):
        # The root-level readme is normal for Nexus uploads and must not stop
        # the single-root detection (found on device).
        z = self._zip({"DeckyTest/DeckyTest.dll": b"MZ", "DeckyTest/readme.md": b"x",
                       "readme.txt": b"install me"})
        plan = self.eng._plan_archive(z)
        self.assertEqual(sorted(f["target"] for f in plan["files"]),
                         ["BepInEx/plugins/DeckyTest/DeckyTest.dll",
                          "BepInEx/plugins/DeckyTest/readme.md"])
        self.assertEqual(plan["refused"], [])
        self.assertIn("readme.txt", plan["skipped"])

    def test_a_bare_file_lands_directly_in_the_target(self):
        z = self._zip({"Solo.dll": b"MZ"})
        plan = self.eng._plan_archive(z)
        self.assertEqual([f["target"] for f in plan["files"]],
                         ["BepInEx/plugins/Solo.dll"])

    def test_structural_top_levels_are_not_stripped(self):
        # BepInEx/... is a real loader tree, not a mod name: it must not be
        # prefixed again, or files would land in BepInEx/plugins/BepInEx/...
        z = self._zip({"BepInEx/plugins/Other/Other.dll": b"MZ"})
        plan = self.eng._plan_archive(z)
        self.assertEqual([f["target"] for f in plan["files"]],
                         ["BepInEx/plugins/Other/Other.dll"])


class TestPlanArchive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.eng = _make_engine(self.tmp)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _zip(self, members):
        path = os.path.join(self.tmp, "pkg.zip")
        with zipfile.ZipFile(path, "w") as zf:
            for name, data in members.items():
                zf.writestr(name, data)
        return path

    def test_a_normal_package_routes_and_ignores_docs(self):
        z = self._zip({
            "CoolMod.archive": b"x" * 10,
            "readme.txt": b"docs",
            "__MACOSX/._CoolMod.archive": b"junk",
        })
        plan = self.eng._plan_archive(z)
        self.assertEqual([f["target"] for f in plan["files"]],
                         ["archive/pc/mod/CoolMod.archive"])
        self.assertIn("readme.txt", plan["skipped"])
        self.assertEqual(plan["refused"], [])
        self.assertEqual(plan["total_bytes"], 10)

    def test_protected_member_is_refused(self):
        z = self._zip({"archive/pc/content/basegame_1_archive": b"x"})
        plan = self.eng._plan_archive(z)
        self.assertEqual(plan["files"], [])
        self.assertEqual(plan["refused"], [("archive/pc/content/basegame_1_archive", "protected")])

    def test_traversal_member_is_refused(self):
        z = self._zip({"../../etc/passwd": b"x"})
        plan = self.eng._plan_archive(z)
        self.assertEqual(plan["files"], [])
        self.assertEqual(plan["refused"][0][1], "path_escape")

    def test_redmod_package_names_itself_from_info_json(self):
        z = self._zip({
            "mods/MyMod/info.json": json.dumps({"name": "My Mod", "version": "1.2.3"}).encode(),
            "mods/MyMod/archives/MyMod.archive": b"x" * 5,
        })
        plan = self.eng._plan_archive(z)
        pid, name, version = self.eng._package_id(z, plan)
        self.assertEqual((pid, name, version), ("My Mod", "My Mod", "1.2.3"))


if __name__ == "__main__":
    unittest.main()
