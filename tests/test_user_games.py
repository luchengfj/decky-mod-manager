"""Round 77 — user-defined game folders.

"Every game" is only honest if the plugin can be pointed at a folder the user
chose, without ever widening where it may write. These tests pin the contract:
safe roots are accepted, dangerous ones are refused, online games are refused,
and the generated descriptor is the same shape the built-in ones use.
"""
import json
import os
import shutil
import tempfile
import unittest

from deckymod import user_games
from deckymod.registry import Registry


_PINNED = None


def setUpModule():
    """Other suites pin DECKYMOD_GAME_ID=rimworld; that pin would hide this
    module's own throwaway registry, so it is parked for the duration."""
    global _PINNED
    _PINNED = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    if _PINNED is not None:
        os.environ["DECKYMOD_GAME_ID"] = _PINNED


class _TmpEnv(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._saved = os.environ.get("DECKYMOD_DATA")
        os.environ["DECKYMOD_DATA"] = os.path.join(self.tmp, "data")
        self.addCleanup(self._restore)

    def _restore(self):
        if self._saved is None:
            os.environ.pop("DECKYMOD_DATA", None)
        else:
            os.environ["DECKYMOD_DATA"] = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestValidation(_TmpEnv):
    def test_an_ordinary_folder_is_accepted(self):
        rec = user_games.save(1868140, "DAVE THE DIVER", ["BepInEx/plugins"])
        self.assertEqual(rec["write_roots"], ["BepInEx/plugins"])

    def test_a_traversing_root_is_refused(self):
        with self.assertRaises(Exception):
            user_games.save(1, "X", ["../escape"])

    def test_an_empty_root_is_refused(self):
        with self.assertRaises(Exception):
            user_games.save(1, "X", ["   "])

    def test_a_game_payload_folder_is_refused(self):
        with self.assertRaises(Exception):
            user_games.save(1, "X", ["MonoBleedingEdge"])

    def test_an_online_game_is_refused_by_name(self):
        self.assertTrue(user_games.is_refused_game("Warframe"))
        self.assertTrue(user_games.is_refused_game("ELDEN RING NIGHTREIGN"))
        self.assertFalse(user_games.is_refused_game("Stardew Valley"))
        with self.assertRaises(Exception):
            user_games.save(230410, "Warframe", ["mods"])

    def test_duplicate_roots_collapse_case_insensitively(self):
        rec = user_games.save(2, "X", ["Mods", "mods", "Mods"])
        self.assertEqual(rec["write_roots"], ["Mods"])


class TestPersistence(_TmpEnv):
    def test_saved_config_is_reloaded(self):
        user_games.save(7, "Some Game", ["Mods"])
        got = user_games.load_all()
        self.assertIn(7, got)
        self.assertEqual(got[7]["write_roots"], ["Mods"])

    def test_forget_removes_it(self):
        user_games.save(7, "Some Game", ["Mods"])
        self.assertTrue(user_games.forget(7))
        self.assertNotIn(7, user_games.load_all())

    def test_a_corrupt_file_is_skipped_not_fatal(self):
        os.makedirs(user_games.data_root(), exist_ok=True)
        with open(os.path.join(user_games.data_root(), "9.json"), "w",
                  encoding="utf-8") as f:
            f.write("{not json")
        user_games.save(8, "Good Game", ["mods"])
        got = user_games.load_all()
        self.assertIn(8, got)
        self.assertNotIn(9, got)


class TestDescriptorShape(_TmpEnv):
    def test_descriptor_uses_root_merge_and_the_chosen_roots(self):
        rec = user_games.save(1868140, "DAVE THE DIVER", ["BepInEx/plugins"])
        d = user_games.descriptor_for(rec)
        self.assertEqual(d["engine"], "root_merge")
        self.assertEqual(d["paths"]["write_roots"], ["BepInEx/plugins"])
        # A bare file at the archive root lands in the user's only folder.
        self.assertEqual(d["paths"]["root_file_target"], "BepInEx/plugins")
        self.assertEqual(d["identity"]["appid"], 1868140)
        self.assertTrue(d["capabilities"]["local_import"])
        self.assertFalse(d["capabilities"]["enable_disable"])
        # Round 79 (user-approved): loader ZIPs may be extracted for
        # user-configured games; built-in descriptors keep this false.
        self.assertTrue(d["capabilities"]["loader_install"])
        self.assertEqual(d["paths"]["loader_root"], "${GAME_ROOT}")
        # The declaration that matters: launch options are still never edited.
        self.assertFalse(d["capabilities"]["launch_option_edit"])


class TestRegistryMerge(_TmpEnv):
    def _registry(self):
        """A throwaway registry with ONE built-in descriptor."""
        base = os.path.join(self.tmp, "plugin")
        os.makedirs(os.path.join(base, "registry", "games"), exist_ok=True)
        with open(os.path.join(base, "registry", "games", "builtin.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"schema": "deckymod/game-descriptor@1", "id": "builtin",
                       "status": "enabled", "engine": "root_merge",
                       "identity": {"appid": 1, "name": "Builtin"},
                       "capabilities": {"local_import": True}}, f)
        with open(os.path.join(base, "registry", "registry.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"active_game": "builtin",
                       "capability_gate": {"enabled_game_status": "enabled",
                                           "max_enabled_games_in_mvp": 1,
                                           "refuse_if_status_not_enabled": True},
                       "descriptors": {"builtin": {"file": "registry/games/builtin.json",
                                                   "status": "enabled", "appid": 1}},
                       "loader_catalog": {}}, f)
        return Registry(base)

    def test_a_user_game_becomes_a_selectable_descriptor(self):
        user_games.save(1868140, "DAVE THE DIVER", ["BepInEx/plugins"])
        r = self._registry()
        gid = user_games.game_id(1868140)
        self.assertIn(gid, r.descriptors)
        self.assertEqual(r.descriptors[gid]["identity"]["name"], "DAVE THE DIVER")

    def test_switching_to_a_user_game_works(self):
        user_games.save(1868140, "DAVE THE DIVER", ["BepInEx/plugins"])
        r = self._registry()
        gid = user_games.game_id(1868140)
        r.switch_active_game(gid)
        self.assertEqual(Registry(r.base_dir).active_descriptor()[0], gid)

    def test_the_catalog_lists_it_as_enabled(self):
        user_games.save(1868140, "DAVE THE DIVER", ["BepInEx/plugins"])
        cat = {c["id"]: c for c in self._registry().catalog()}
        self.assertTrue(cat[user_games.game_id(1868140)]["enabled"])


if __name__ == "__main__":
    unittest.main()
