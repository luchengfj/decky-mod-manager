"""Synthetic tests for P0 (round 2): read-only browse-by-category catalog.

STDLIB ONLY. These verify:
  * Registry.catalog() is GATE-FREE read-only descriptor metadata: every
    descriptor (enabled + planned + unsupported) is returned, with planned /
    unsupported rows marked operable=False. It NEVER calls get_game/require/
    active_descriptor and NEVER resolves mod_root / state_file.
  * The output is strictly JSON-safe (str/int/bool/None/list/dict).
  * main.Plugin().status() ADDITIVELY carries data.catalog but keeps the SAME
    11 positional RPCs (no new RPC).
  * The catalog does not break the existing status() shape (per-key assertions
    in the other suites still pass) and causes ZERO writes.

The RimWorld suite pins DECKYMOD_GAME_ID=rimworld at import time; unittest
discovery imports all modules first, so a module-level pop here would erase that
pin. We save/pop/restore around THIS module's execution only (same pattern as
tests/test_stardew.py), so production default = stardew here.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main
from deckymod.registry import Registry

from test_stardew import StardewTree

_PREV_GAME_ID = None


def setUpModule():
    global _PREV_GAME_ID
    _PREV_GAME_ID = os.environ.pop("DECKYMOD_GAME_ID", None)  # production default = stardew


def tearDownModule():
    if _PREV_GAME_ID is not None:
        os.environ["DECKYMOD_GAME_ID"] = _PREV_GAME_ID
    else:
        os.environ.pop("DECKYMOD_GAME_ID", None)


JSON_SAFE = (str, int, bool, type(None))


def _assert_json_safe(value, path="root"):
    """Recursively assert only JSON-safe primitives / containers."""
    if isinstance(value, dict):
        for k, v in value.items():
            assert isinstance(k, str), f"{path}: non-str dict key {k!r}"
            _assert_json_safe(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _assert_json_safe(v, f"{path}[{i}]")
    else:
        assert isinstance(value, JSON_SAFE), f"{path}: non-JSON-safe value {value!r}"


class TestCatalogReadOnly(unittest.TestCase):
    def setUp(self):
        self.r = Registry()

    def test_catalog_includes_all_descriptors_gate_free(self):
        cat = self.r.catalog()
        ids = [c["id"] for c in cat]
        # enabled + planned + unsupported ALL present (browse plane ≠ write gate)
        self.assertIn("stardew", ids)
        self.assertIn("rimworld", ids)
        self.assertIn("factorio", ids)
        self.assertIn("valheim", ids)
        self.assertEqual(len(cat), len(self.r.descriptors))

    def test_stardew_is_the_only_operable_row(self):
        cat = {c["id"]: c for c in self.r.catalog()}
        self.assertTrue(cat["stardew"]["enabled"])
        self.assertTrue(cat["stardew"]["operable"])
        self.assertTrue(cat["stardew"]["active"])
        self.assertEqual(cat["stardew"]["appid"], 413150)
        self.assertEqual(cat["stardew"]["platform"], "linux-native")
        for gid in ("rimworld", "factorio", "valheim"):
            self.assertFalse(cat[gid]["enabled"], gid)
            self.assertFalse(cat[gid]["operable"], gid)
            self.assertFalse(cat[gid]["active"], gid)

    def test_catalog_is_json_safe(self):
        cat = self.r.catalog()
        _assert_json_safe(cat)
        # survives a real JSON round-trip (the envelope() gateway does this)
        self.assertEqual(json.loads(json.dumps(cat, ensure_ascii=False)), cat)

    def test_catalog_exposes_capabilities_but_no_paths(self):
        for c in self.r.catalog():
            self.assertIsInstance(c["capabilities"], dict)
            self.assertIsInstance(c["loaders"], list)
            # display-only must never carry resolved filesystem paths
            self.assertNotIn("mod_root", c)
            self.assertNotIn("state_file", c)
            self.assertNotIn("game_root", c)

    def test_valheim_dict_shaped_loaders_normalized(self):
        cat = {c["id"]: c for c in self.r.catalog()}
        # valheim descriptor uses dict-shaped loaders; catalog must normalize
        # them to strings rather than leaking dicts into the wire.
        for lid in cat["valheim"]["loaders"]:
            self.assertIsInstance(lid, str)

    def test_catalog_does_not_change_gate_state(self):
        # Reading the catalog must not enable any planned game nor lift the
        # single-active-game write gate.
        before = sorted(self.r.enabled_games())
        self.r.catalog()
        after = sorted(self.r.enabled_games())
        self.assertEqual(before, after)
        self.assertEqual(after, ["stardew"])
        self.assertEqual(self.r.assert_enabled_count(), ["stardew"])


class TestCatalogInStatusEnvelope(unittest.TestCase):
    def setUp(self):
        self.t = StardewTree()
        self.t.env()

    def tearDown(self):
        self.t.cleanup()

    def test_status_carries_additive_catalog(self):
        env = asyncio.run(main.Plugin().status())
        self.assertTrue(env["ok"])
        self.assertIn("catalog", env["data"])
        cat = env["data"]["catalog"]
        self.assertEqual(len(cat), len(Registry().descriptors))
        _assert_json_safe(env)
        # existing status keys intact (per-key assertions elsewhere)
        self.assertEqual(env["data"]["game"]["appid"], 413150)

    def test_rpc_count_is_24_after_round39_nexus_metadata(self):
        # P0 itself added no RPC (catalog rides inside status()).
        # Round 18 added 6 Download RPCs (11 + 6 = 17); round 38 added
        # fetch_dependencies (18); round 39 added the credential surface and
        # three metadata RPCs (18 + 6 = 24).
    # Round 41 added open_mod_page (25); round 43 added open_search_page (26).
        # Round 19 retired those 6 and added 4 source RPCs: 11 + 4 = 15.
        # Round 23 added list_games() for goal item 2 (Steam library scan): 16.
        # Count Plugin public async methods.
        rpc = sorted(
            name for name in dir(main.Plugin)
            if not name.startswith("_") and callable(getattr(main.Plugin, name))
            and asyncio.iscoroutinefunction(getattr(main.Plugin, name))
        )
        self.assertEqual(len(rpc), 26, rpc)
        for name in ("gh_search", "gh_releases", "gh_download", "download_url",
                     "list_games"):
            self.assertIn(name, rpc)

    def test_catalog_is_display_only_zero_write(self):
        # status() (which now attaches the catalog) must not mutate the Mods
        # tree or create any staging/quarantine/state artifacts.
        def snapshot(root):
            out = []
            for dp, dns, fns in os.walk(root):
                for n in sorted(dns):
                    out.append(("d", os.path.relpath(os.path.join(dp, n), root)))
                for n in sorted(fns):
                    out.append(("f", os.path.relpath(os.path.join(dp, n), root)))
            return sorted(out)
        before = snapshot(self.t.game)
        asyncio.run(main.Plugin().status())
        after = snapshot(self.t.game)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
