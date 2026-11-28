"""Round 78 — the Nexus website openers must honour the browse-only domain.

Device finding (2026-11-21): on Cyberpunk 2077 the panel's 最新发布/最近更新/热门
buttons answered E_CAPABILITY_DISABLED "[open_browse_page] nexus_metadata source
disabled", because the descriptor declares the browse-only alias
``download_sources.nexus_game_domain`` (a plain string) while the three
website-page openers read only the API-shaped ``nexus_metadata`` block. Opening
a website page needs no API key, so the alias is now honoured.

Round 88: the API RPCs that did need a stored key are gone, so the alias is
now the ONLY shape anything reads. ``_nexus_domain()`` — the API-shaped reader —
went with them.

The openers are tested with ``deckymod.openurl.open_url`` stubbed: the contract
under test is the URL that would be handed to the browser, not the open itself.
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main
from deckymod import nexus
from deckymod.registry import Registry

_PINNED = None


def setUpModule():
    global _PINNED
    _PINNED = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    if _PINNED is not None:
        os.environ["DECKYMOD_GAME_ID"] = _PINNED


def _descriptor(gid, appid, sources):
    return {
        "schema": "deckymod/game-descriptor@1",
        "id": gid,
        "status": "enabled",
        "engine": "file_drop",
        "identity": {"appid": appid, "name": gid.title(), "status": "enabled"},
        "capabilities": {"network_download": True, "local_import": True},
        "download_sources": sources,
    }


class TestNexusBrowse(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        base = os.path.join(self.tmp, "plugin")
        os.makedirs(os.path.join(base, "registry", "games"), exist_ok=True)
        cases = {
            # stardew shape: API block enabled -> website + API both work
            "apigame": {"nexus_metadata": {"enabled": True,
                                           "game_domain": "stardewvalley"}},
            # cyberpunk shape: browse-only alias, plain string, no API block
            "browsegame": {"nexus_game_domain": "cyberpunk2077"},
            # user-game shape: no domain declared at all
            "nogame": {},
        }
        for gid, sources in cases.items():
            with open(os.path.join(base, "registry", "games", gid + ".json"),
                      "w", encoding="utf-8") as f:
                json.dump(_descriptor(gid, 1000 + len(gid), sources), f)
        with open(os.path.join(base, "registry", "registry.json"), "w",
                  encoding="utf-8") as f:
            json.dump({
                "active_game": "browsegame",
                "capability_gate": {"enabled_game_status": "enabled",
                                    "max_enabled_games_in_mvp": 1,
                                    "refuse_if_status_not_enabled": True},
                "descriptors": {
                    gid: {"file": "registry/games/%s.json" % gid,
                          "status": "enabled"} for gid in cases
                },
                "loader_catalog": {},
            }, f)
        self._real_registry = main.Registry
        main.Registry = lambda: Registry(base)
        self.addCleanup(self._restore)
        self.plugin = main.Plugin()

    def _restore(self):
        main.Registry = self._real_registry
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_browse_only_alias_opens_the_site_page(self):
        with mock.patch("deckymod.openurl.open_url",
                        return_value={"ok": True}) as opened:
            r = asyncio.run(self.plugin.open_browse_page("trending"))
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["data"]["url"],
                         "https://www.nexusmods.com/cyberpunk2077/mods?sort=trending")
        opened.assert_called_once_with(r["data"]["url"])

    def test_api_block_still_wins_when_present(self):
        asyncio.run(self.plugin.switch_game("apigame"))
        with mock.patch("deckymod.openurl.open_url",
                        return_value={"ok": True}):
            r = asyncio.run(self.plugin.open_browse_page("latest_added"))
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["data"]["url"],
                         nexus.browse_page_url("stardewvalley", "latest_added"))

    def test_no_domain_still_refused_with_its_reason(self):
        asyncio.run(self.plugin.switch_game("nogame"))
        r = asyncio.run(self.plugin.open_browse_page("trending"))
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "E_CAPABILITY_DISABLED")
        self.assertIn("no Nexus domain", r.get("detail") or "")

    def test_unknown_sort_still_refused(self):
        r = asyncio.run(self.plugin.open_browse_page("most_downloaded"))
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "E_PATH_INVALID")

    def test_the_key_reading_rpc_is_gone(self):
        # Round 88 removed nexus_recent with the key surface. A browse-only
        # descriptor used to reach it and get "nexus_metadata source disabled";
        # now the RPC does not exist at all, which is the stronger guarantee.
        self.assertFalse(hasattr(self.plugin, "nexus_recent"))

    def test_open_mod_page_accepts_the_browse_only_alias(self):
        with mock.patch("deckymod.openurl.open_url",
                        return_value={"ok": True}):
            r = asyncio.run(self.plugin.open_mod_page(1234))
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["data"]["url"],
                         nexus.mod_page_url("cyberpunk2077", 1234))


class TestCatalogDomainFallback(unittest.TestCase):
    """The catalog prefix must match what the openers accept, or the UI gates
    on a different rule than the backend enforces."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        base = os.path.join(self.tmp, "plugin")
        os.makedirs(os.path.join(base, "registry", "games"), exist_ok=True)
        with open(os.path.join(base, "registry", "games", "browse.json"),
                  "w", encoding="utf-8") as f:
            json.dump(_descriptor("browse", 1091500,
                                  {"nexus_game_domain": "cyberpunk2077"}), f)
        with open(os.path.join(base, "registry", "games", "none.json"),
                  "w", encoding="utf-8") as f:
            json.dump(_descriptor("none", 2000, {}), f)
        with open(os.path.join(base, "registry", "registry.json"), "w",
                  encoding="utf-8") as f:
            json.dump({
                "active_game": "browse",
                "capability_gate": {"enabled_game_status": "enabled",
                                    "max_enabled_games_in_mvp": 1},
                "descriptors": {
                    "browse": {"file": "registry/games/browse.json",
                               "status": "enabled"},
                    "none": {"file": "registry/games/none.json",
                             "status": "enabled"},
                },
                "loader_catalog": {},
            }, f)
        self.registry = Registry(base)
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def test_browse_alias_is_exposed_and_absent_is_none(self):
        cat = {c["id"]: c for c in self.registry.catalog()}
        self.assertEqual(cat["browse"]["nexus_domain"], "cyberpunk2077")
        self.assertIsNone(cat["none"]["nexus_domain"])


if __name__ == "__main__":
    unittest.main()
