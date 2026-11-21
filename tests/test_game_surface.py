"""Round 78 — the game-switch / user-game configuration RPC surface.

Round 76/77 added four RPCs (switch_game, game_setup, configure_game,
forget_game) but only the registry layer under them had tests. The RPC layer
is where the user-facing contract lives, so it is pinned here:

  * switch_game moves active_game between enabled descriptors and refuses a
    planned one with E_CAPABILITY_DISABLED;
  * configure_game persists a user game and game_setup then reports it as
    configured (the round-78 affordance: change/remove from the panel);
  * configure_game refuses an anti-cheat game by name;
  * forget_game deletes the record, and — the safety property — when the
    REMOVED game was the active one, the plugin falls back to a built-in
    descriptor instead of being left with no managed game.

Everything runs against a THROWAWAY registry (main.Registry is patched to a
private base dir) so the production registry.json is never written by a test.
The throwaway descriptors are named stardew/cyberpunk because main.forget_game
falls back to those literal ids, matching the shipped registry.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main
from deckymod.registry import Registry

_PINNED = None


def setUpModule():
    """Other suites pin DECKYMOD_GAME_ID=rimworld; that pin would override this
    module's own throwaway registry, so it is parked for the duration."""
    global _PINNED
    _PINNED = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    if _PINNED is not None:
        os.environ["DECKYMOD_GAME_ID"] = _PINNED


def _descriptor(gid: str, appid: int, status: str = "enabled") -> dict:
    return {
        "schema": "deckymod/game-descriptor@1",
        "id": gid,
        "status": status,
        "engine": "root_merge",
        "identity": {"appid": appid, "name": gid.title(), "status": status},
        "capabilities": {"local_import": True, "uninstall_quarantine": True,
                         "rollback": True},
    }


class TestGameSurface(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._saved_data = os.environ.get("DECKYMOD_DATA")
        os.environ["DECKYMOD_DATA"] = os.path.join(self.tmp, "data")
        # A private registry with the two fallback names, so forget_game's
        # built-in fallback has something to fall back to.
        base = os.path.join(self.tmp, "plugin")
        os.makedirs(os.path.join(base, "registry", "games"), exist_ok=True)
        for gid, appid in (("stardew", 413150), ("cyberpunk", 1091500)):
            with open(os.path.join(base, "registry", "games", gid + ".json"),
                      "w", encoding="utf-8") as f:
                json.dump(_descriptor(gid, appid), f)
        with open(os.path.join(base, "registry", "games", "planned.json"),
                  "w", encoding="utf-8") as f:
            json.dump(_descriptor("planned", 999999, status="planned"), f)
        with open(os.path.join(base, "registry", "registry.json"), "w",
                  encoding="utf-8") as f:
            json.dump({
                "active_game": "stardew",
                "capability_gate": {"enabled_game_status": "enabled",
                                    "max_enabled_games_in_mvp": 1,
                                    "refuse_if_status_not_enabled": True},
                "descriptors": {
                    "stardew": {"file": "registry/games/stardew.json",
                                "status": "enabled", "appid": 413150},
                    "cyberpunk": {"file": "registry/games/cyberpunk.json",
                                  "status": "enabled", "appid": 1091500},
                    "planned": {"file": "registry/games/planned.json",
                                "status": "planned", "appid": 999999},
                },
                "loader_catalog": {},
            }, f)
        # main.py constructs Registry() with no argument; route it to the
        # throwaway base so no test ever writes the production registry.
        self._real_registry = main.Registry
        main.Registry = lambda: Registry(base)
        self.addCleanup(self._restore)

    def _restore(self):
        main.Registry = self._real_registry
        if self._saved_data is None:
            os.environ.pop("DECKYMOD_DATA", None)
        else:
            os.environ["DECKYMOD_DATA"] = self._saved_data
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _plugin(self):
        return main.Plugin()

    def test_switch_game_moves_the_active_game(self):
        r = asyncio.run(self._plugin().switch_game("cyberpunk"))
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["data"]["changed"])
        self.assertEqual(r["data"]["previous"], "stardew")
        self.assertEqual(main.Registry().raw.get("active_game"), "cyberpunk")

    def test_switch_to_the_same_game_is_a_noop(self):
        r = asyncio.run(self._plugin().switch_game("stardew"))
        self.assertTrue(r["ok"], r)
        self.assertFalse(r["data"]["changed"])

    def test_switch_game_refuses_a_planned_descriptor(self):
        r = asyncio.run(self._plugin().switch_game("planned"))
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "E_CAPABILITY_DISABLED")
        self.assertEqual(main.Registry().raw.get("active_game"), "stardew")

    def test_switch_game_refuses_an_unknown_id(self):
        r = asyncio.run(self._plugin().switch_game("no_such_game"))
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "E_CAPABILITY_DISABLED")

    def test_configure_game_persists_and_game_setup_reports_it(self):
        p = self._plugin()
        r = asyncio.run(p.configure_game(1868140, "DAVE THE DIVER",
                                         ["BepInEx/plugins"]))
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["data"]["write_roots"], ["BepInEx/plugins"])
        s = asyncio.run(p.game_setup(1868140))
        self.assertTrue(s["ok"], s)
        self.assertTrue(s["data"]["configured"])
        self.assertEqual(s["data"]["write_roots"], ["BepInEx/plugins"])
        self.assertFalse(s["data"]["refused"])
        # The saved game is selectable in the catalog as an enabled descriptor.
        cat = {c["id"]: c for c in main.Registry().catalog()}
        self.assertTrue(cat["user_1868140"]["enabled"])

    def test_configure_game_refuses_an_anticheat_game(self):
        r = asyncio.run(self._plugin().configure_game(230410, "Warframe",
                                                      ["mods"]))
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "E_NOT_ALLOWED_ROOT")

    def test_configure_game_refuses_a_built_in_game(self):
        # Round 79 (device finding): re-configuring Stardew Valley generated a
        # second root_merge descriptor that shadowed its SMAPI management.
        r = asyncio.run(self._plugin().configure_game(413150, "Stardew Valley",
                                                      ["Mods"]))
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "E_NOT_ALLOWED_ROOT")
        self.assertIn("built-in descriptor", r.get("detail") or "")
        # The throwaway config must not exist afterwards.
        from deckymod import user_games
        self.assertNotIn(413150, user_games.load_all())

    def test_configure_game_still_accepts_an_ordinary_game(self):
        r = asyncio.run(self._plugin().configure_game(1868140, "DAVE THE DIVER",
                                                      ["BepInEx/plugins"]))
        self.assertTrue(r["ok"], r)

    def test_forget_a_non_active_user_game_just_deletes_it(self):
        p = self._plugin()
        asyncio.run(p.configure_game(1868140, "DAVE THE DIVER",
                                     ["BepInEx/plugins"]))
        r = asyncio.run(p.forget_game(1868140))
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["data"]["deleted"])
        self.assertIsNone(r["data"]["switched_to"])
        self.assertEqual(main.Registry().raw.get("active_game"), "stardew")

    def test_forgetting_the_active_user_game_falls_back_to_a_builtin(self):
        p = self._plugin()
        asyncio.run(p.configure_game(1868140, "DAVE THE DIVER",
                                     ["BepInEx/plugins"]))
        sw = asyncio.run(p.switch_game("user_1868140"))
        self.assertTrue(sw["ok"], sw)
        self.assertEqual(main.Registry().raw.get("active_game"), "user_1868140")
        r = asyncio.run(p.forget_game(1868140))
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["data"]["deleted"])
        # The safety property: the plugin is never left with no managed game.
        self.assertEqual(r["data"]["switched_to"], "stardew")
        self.assertEqual(main.Registry().raw.get("active_game"), "stardew")
        self.assertTrue(main.Registry().enabled_games())

    def test_forget_an_unconfigured_game_is_honest(self):
        r = asyncio.run(self._plugin().forget_game(123123))
        self.assertTrue(r["ok"], r)
        self.assertFalse(r["data"]["deleted"])


if __name__ == "__main__":
    unittest.main()
