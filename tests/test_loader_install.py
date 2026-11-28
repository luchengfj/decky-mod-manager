"""Round 79 — loader install for user-configured games.

The user approved lifting the "never install a loader" red line for the games
THEY configure (a loader ZIP extracted into the game's loader root), with the
guardrails that stay in force everywhere else:

  * the descriptor capability ``loader_install`` must be TRUE — built-in
    descriptors keep it false and are refused;
  * two-phase (confirm writes nothing), game-running gate, no pending txn;
  * every file journaled, replaced files backed up, and the EXISTING
    uninstall/rollback machinery removes the loader exactly;
  * Steam launch options are never touched.

Reuses the synthetic Steam tree from test_second_game with a root_merge
descriptor; nothing in deckymod/ is patched or mocked.
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main
from deckymod.journal import Journal
from deckymod.registry import Registry
from deckymod.root_merge import RootMergeEngine
from test_second_game import SecondTree, _zip, APPID, INSTALLDIR

_PREV = None


def setUpModule():
    global _PREV
    _PREV = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    if _PREV is not None:
        os.environ["DECKYMOD_GAME_ID"] = _PREV
    else:
        os.environ.pop("DECKYMOD_GAME_ID", None)


#: A loader ZIP in exactly the shape BepInEx ships: a tree + two bare files
#: that MUST land at the loader root (next to the game executable).
LOADER_ZIP_FILES = {
    "BepInEx/core/BepInEx.dll": b"MZ core",
    "BepInEx/LICENSE.txt": b"MIT",
    "doorstop_config.ini": b"[Doorstop]\nEnabled=true\n",
    "winhttp.dll": b"MZ doorstop",
    "changelog.txt": b"v6 notes",
}


def _descriptor() -> dict:
    return {
        "schema": 1,
        "id": "secondgame",
        "status": "enabled",
        "engine": "root_merge",
        "display_label": "Second Game (synthetic, loader-capable)",
        "identity": {"appid": APPID, "name": "Second Game",
                     "platform": "windows-proton", "status": "synthetic"},
        "paths": {
            "game_root": "${GAME_ROOT}",
            "mod_root": None,
            "write_roots": ["BepInEx/plugins"],
            "root_file_target": "BepInEx/plugins",
            "loader_root": "${GAME_ROOT}",
            "staging": "${GAME_ROOT}/.decky-staging",
            "quarantine": "${GAME_ROOT}/.decky-quarantine/${TXN_ID}",
        },
        # Round 86: root_merge needs no manifest parser (routes by path).
        "mod_package": {"archive_format": "zip",
                        "strip_single_root": True},
        "capabilities": {"local_import": True, "uninstall_quarantine": True,
                         "rollback": True, "loader_install": True,
                         "launch_option_edit": False},
        "safety": {"refuse_if_game_running": False},
        "known_limitations": [],
        "known_limitation_keys": [],
    }


class TestLoaderInstall(unittest.TestCase):
    def setUp(self):
        self.t = SecondTree()
        self.t.rewrite_descriptor(_descriptor())
        self.t.env()
        self.eng = RootMergeEngine(
            registry=self.t.registry(),
            journal=Journal(self.t.data, self.t.logs, "secondgame"))
        self.addCleanup(self.t.cleanup)

    def _loader_zip(self, members=None, name="bepinex.zip"):
        zp = os.path.join(self.t.inbox, name)
        _zip(zp, members if members is not None else LOADER_ZIP_FILES)
        return zp

    def _game_file(self, rel):
        return os.path.join(self.t.game, rel.replace("/", os.sep))

    def test_two_phase_then_files_land_at_the_loader_root(self):
        zp = self._loader_zip()
        plan = self.eng.install_loader(zp)
        self.assertTrue(plan["ok"], plan)
        self.assertEqual(plan["data"]["phase"], "confirm")
        # Confirm phase writes NOTHING — not even the folder.
        self.assertFalse(os.path.exists(self._game_file("BepInEx")))
        done = self.eng.install_loader(zp, after_confirm=True)
        self.assertTrue(done["ok"], done)
        self.assertTrue(done["data"]["packageId"].startswith("loader:"))
        self.assertEqual(done["data"]["files"], len(LOADER_ZIP_FILES))
        for rel in ("BepInEx/core/BepInEx.dll", "winhttp.dll",
                    "doorstop_config.ini", "BepInEx/LICENSE.txt"):
            self.assertTrue(os.path.isfile(self._game_file(rel)), rel)
        self.assertEqual(open(self._game_file("winhttp.dll"), "rb").read(),
                         b"MZ doorstop")

    def test_uninstall_removes_exactly_the_loader_files(self):
        zp = self._loader_zip()
        done = self.eng.install_loader(zp, after_confirm=True)
        self.assertTrue(done["ok"], done)
        pid = done["data"]["packageId"]
        un = self.eng.uninstall(pid, after_confirm=True)
        self.assertTrue(un["ok"], un)
        for rel in ("BepInEx/core/BepInEx.dll", "winhttp.dll",
                    "doorstop_config.ini", "changelog.txt"):
            self.assertFalse(os.path.exists(self._game_file(rel)), rel)

    def test_a_replaced_file_is_backed_up_and_restored_by_uninstall(self):
        # A previous loader version's winhttp.dll is on disk; the new ZIP
        # replaces it, and uninstalling brings the OLD bytes back.
        old = self._game_file("winhttp.dll")
        os.makedirs(os.path.dirname(old), exist_ok=True)
        with open(old, "wb") as f:
            f.write(b"OLD doorstop bytes")
        zp = self._loader_zip()
        done = self.eng.install_loader(zp, after_confirm=True)
        self.assertTrue(done["ok"], done)
        self.assertEqual(done["data"]["replaced"], 1)
        self.assertEqual(open(old, "rb").read(), b"MZ doorstop")
        un = self.eng.uninstall(done["data"]["packageId"], after_confirm=True)
        self.assertTrue(un["ok"], un)
        self.assertEqual(open(old, "rb").read(), b"OLD doorstop bytes")

    def test_a_built_in_descriptor_without_the_capability_is_refused(self):
        self.t.rewrite_descriptor(_descriptor() | {"capabilities": {
            "local_import": True, "uninstall_quarantine": True,
            "rollback": True, "loader_install": False}})
        eng = RootMergeEngine(
            registry=self.t.registry(),
            journal=Journal(self.t.data, self.t.logs, "secondgame"))
        zp = self._loader_zip()
        r = eng.install_loader(zp, after_confirm=True)
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "E_CAPABILITY_DISABLED")
        self.assertFalse(os.path.exists(self._game_file("BepInEx")))

    def test_an_unsafe_member_is_refused_not_written(self):
        zp = self._loader_zip({"BepInEx/core/BepInEx.dll": b"MZ",
                               "../evil.cfg": b"x"})
        r = self.eng.install_loader(zp, after_confirm=True)
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "E_NOT_ALLOWED_ROOT")
        self.assertFalse(os.path.exists(self._game_file("BepInEx")))

    def test_the_running_gate_applies_to_loader_installs(self):
        os.environ["DECKYMOD_GAME_RUNNING"] = "1"
        try:
            zp = self._loader_zip()
            r = self.eng.install_loader(zp, after_confirm=True)
            self.assertFalse(r["ok"])
            self.assertEqual(r["code"], "E_GAME_RUNNING")
            self.assertFalse(os.path.exists(self._game_file("BepInEx")))
        finally:
            os.environ.pop("DECKYMOD_GAME_RUNNING", None)


class TestLoaderPageAndSetup(unittest.TestCase):
    """open_loader_page reads the catalog; game_setup lists the offers."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        base = os.path.join(self.tmp, "plugin")
        os.makedirs(os.path.join(base, "registry", "loaders"), exist_ok=True)
        os.makedirs(os.path.join(base, "registry", "games"), exist_ok=True)
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        shutil.copy(os.path.join(repo, "registry", "loaders", "bepinex5.json"),
                    os.path.join(base, "registry", "loaders", "bepinex5.json"))
        with open(os.path.join(base, "registry", "loaders", "bare.json"),
                  "w", encoding="utf-8") as f:
            json.dump({"schema": "deckymod/loader@1", "id": "bare",
                       "name": "No Page Loader"}, f)
        with open(os.path.join(base, "registry", "games", "secondgame.json"),
                  "w", encoding="utf-8") as f:
            json.dump(_descriptor(), f)
        with open(os.path.join(base, "registry", "registry.json"), "w",
                  encoding="utf-8") as f:
            json.dump({
                "active_game": "secondgame",
                "capability_gate": {"enabled_game_status": "enabled",
                                    "max_enabled_games_in_mvp": 1,
                                    "refuse_if_status_not_enabled": True},
                "descriptors": {"secondgame": {
                    "file": "registry/games/secondgame.json"}},
                "loader_catalog": {
                    "bepinex5": "registry/loaders/bepinex5.json",
                    "bare": "registry/loaders/bare.json",
                },
            }, f)
        self._real = main.Registry
        main.Registry = lambda: Registry(base)
        self.addCleanup(self._restore)
        self.plugin = main.Plugin()

    def _restore(self):
        main.Registry = self._real
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_open_loader_page_hands_the_catalog_url_to_the_browser(self):
        with mock.patch("deckymod.openurl.open_url",
                        return_value={"ok": True}) as opened:
            r = asyncio.run(self.plugin.open_loader_page("bepinex5"))
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["data"]["url"],
                         "https://github.com/BepInEx/BepInEx/releases")
        # The host comes from the catalog itself — the only trust boundary.
        opened.assert_called_once_with(r["data"]["url"],
                                       allowed_hosts={"github.com"})

    def test_an_unknown_loader_id_is_refused(self):
        r = asyncio.run(self.plugin.open_loader_page("not_a_loader"))
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "E_PATH_INVALID")

    def test_a_loader_without_a_page_is_refused_honestly(self):
        r = asyncio.run(self.plugin.open_loader_page("bare"))
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "E_CAPABILITY_DISABLED")

    def test_game_setup_lists_loader_offers(self):
        r = asyncio.run(self.plugin.game_setup(123456))
        self.assertTrue(r["ok"], r)
        loaders = (r["data"] or {}).get("loaders") or []
        ids = [l["id"] for l in loaders]
        self.assertIn("bepinex5", ids)
        self.assertNotIn("bare", ids)          # no browse_url -> nothing to open
        row = next(l for l in loaders if l["id"] == "bepinex5")
        for field in ("name", "browse_url", "hint", "hint_fits", "installed"):
            self.assertIn(field, row)


if __name__ == "__main__":
    unittest.main()
