"""Round 19: behavioural coverage for the GitHub / direct-URL download RPCs.

The point of this file is that it EXERCISES the four new RPCs end to end rather
than asserting their names exist. Every collaborator that would touch the
network is replaced by an injected fake opener, so the whole file runs offline
and deterministically, on any platform.

What is NOT proven here (and must not be claimed as proven): that the real
GitHub API answers (round 19 device probes did that, separately), that the
frontend renders, and that the engine's write gate lets a write through — the
device currently refuses every write with E_EXTERNAL_MANAGER by design.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import unittest
import uuid
from unittest import mock

import main
from deckymod import auto_import, github_source, download
from deckymod.envelope import err, ok

ENVELOPE_KEYS = {"ok", "code", "message", "detail", "data",
                 "rollback_available", "log_path", "ts"}
ZIP_BYTES = b"PK\x03\x04" + b"\x00" * 60 + b"PK\x05\x06" + b"\x00" * 18

_PIN = "_r19_saved_game_id"


def setUpModule():
    """Run these cases against the PRODUCTION descriptor (stardew).

    tests/test_mvp.py pins DECKYMOD_GAME_ID=rimworld at import time to keep the
    33 historical RimWorld cases byte-identical. In a full discover run that pin
    is already set when this module executes, and the RimWorld descriptor has no
    ``download_sources`` block, so every download RPC would fail the capability
    gate before reaching the code under test. Save, clear, restore.
    """
    globals()[_PIN] = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    saved = globals().pop(_PIN, None)
    if saved is None:
        os.environ.pop("DECKYMOD_GAME_ID", None)
    else:
        os.environ["DECKYMOD_GAME_ID"] = saved


def _run(coro):
    return asyncio.run(coro)


def _env(test, e, *, ok_value=None, code=None):
    test.assertIsInstance(e, dict)
    test.assertEqual(set(e.keys()), ENVELOPE_KEYS)
    if ok_value is not None:
        test.assertEqual(e["ok"], ok_value, e)
    if code is not None:
        test.assertEqual(e["code"], code, e)
    json.dumps(e, allow_nan=False, ensure_ascii=False)
    return e


class _Resp:
    """Minimal stand-in for download._Response: stateful read(), close()."""

    def __init__(self, status, headers=None, body=b""):
        self.status = status
        self.headers = dict(headers or {})
        self._body = body
        self._pos = 0

    def read(self, amt=None):
        if amt is None:
            amt = len(self._body)
        part = self._body[self._pos:self._pos + amt]
        self._pos += len(part)
        return part

    def close(self):
        pass


class _Opener:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, method, url, headers, timeout):
        self.calls.append((method, url, dict(headers)))
        for fragment, spec in self.routes.items():
            if fragment in url:
                status, hdrs = spec[0], spec[1]
                body = spec[2] if len(spec) > 2 else b""
                return _Resp(status, hdrs, body)
        return _Resp(404, {}, b"{}")


def _search_payload(extra=None):
    items = [{
        "full_name": "Esca-MMC/DestroyableBushes",
        "stargazers_count": 33,
        "description": "d" * 400,
        "updated_at": "2026-02-01T00:00:00Z",
        "archived": False,
    }]
    if extra:
        items.extend(extra)
    return json.dumps({"total_count": len(items), "items": items}).encode()


def _releases_payload():
    return json.dumps([{
        "id": 1,
        "tag_name": "1.5.2",
        "name": "1.5.2",
        "prerelease": False,
        "draft": False,
        "published_at": "2026-02-02T00:00:00Z",
        "body": "release notes " * 200,
        "assets": [
            {"id": 252770482, "name": "DestroyableBushes.1.5.2.zip", "size": 44252,
             "content_type": "application/x-zip-compressed", "download_count": 644},
            {"id": 9, "name": "Setup.exe", "size": 10,
             "content_type": "application/octet-stream", "download_count": 1},
        ],
    }]).encode()


ASSET_LOCATION = ("https://release-assets.githubusercontent.com/"
                  "github-production-release-asset/1?sig=abc")


class _DownloadMixin:
    """Shared fixture: isolated DECKYMOD_DATA + a fake engine + fake opener."""

    def setUp(self):
        base = os.path.join(r"C:\ai\SD\.decky-test-tmp",
                            "r19_" + uuid.uuid4().hex[:8])
        os.makedirs(base, exist_ok=True)
        self.addCleanup(shutil.rmtree, base, True)
        self.base = base
        self.inbox = os.path.join(base, "inbox")
        os.makedirs(self.inbox, exist_ok=True)

        self._saved = {k: os.environ.get(k) for k in
                       ("DECKYMOD_DATA", "DECKYMOD_INBOX", "DECKYMOD_GAME_ID")}
        os.environ["DECKYMOD_DATA"] = base
        os.environ["DECKYMOD_INBOX"] = self.inbox

        self.engine = mock.MagicMock()
        self.engine.journal.decky_data = base

        def _list_inbox():
            items = []
            for name in sorted(os.listdir(self.inbox)):
                p = os.path.join(self.inbox, name)
                if name.lower().endswith(".zip") and os.path.isfile(p):
                    items.append({"name": name, "path": p,
                                  "size": os.path.getsize(p)})
            return ok({"inbox": self.inbox, "items": items, "log_path": "x"})

        self.engine.list_inbox.side_effect = _list_inbox
        self.engine.inspect.side_effect = lambda path: ok(
            {"mod": {"uniqueId": "TestCo.AutoBush", "name": "Auto Bush",
                     "version": "1.5.2", "author": "Tester"}})
        self.p = main.Plugin()
        self.p.engine = self.engine

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _opener(self, *, asset_status=302, asset_body=b"",
                releases_body=None, search_body=None, include_asset=True):
        routes = {
            "/search/repositories": (200, {}, search_body or _search_payload()),
            "/releases?": (200, {}, releases_body or _releases_payload()),
            "release-assets.githubusercontent.com": (200, {}, ZIP_BYTES),
        }
        if include_asset:
            routes["/releases/assets/"] = (asset_status, {"Location": ASSET_LOCATION},
                                           asset_body)
        return _Opener(routes)


class TestSearchRPC(_DownloadMixin, unittest.TestCase):
    def test_search_returns_slimmed_items_and_truncates_description(self):
        opener = self._opener()
        with mock.patch.object(download, "default_opener", opener):
            e = _run(self.p.gh_search("stardew valley mods", 1))
        _env(self, e, ok_value=True)
        data = e["data"]
        self.assertEqual(data["total_count"], 1)
        self.assertEqual(data["page"], 1)
        repo = data["items"][0]
        self.assertEqual(repo["full_name"], "Esca-MMC/DestroyableBushes")
        self.assertEqual(repo["owner"], "Esca-MMC")
        self.assertEqual(repo["repo"], "DestroyableBushes")
        self.assertLessEqual(len(repo["description"]), 160)

    def test_search_rejects_an_empty_query_without_touching_the_network(self):
        opener = self._opener()
        with mock.patch.object(download, "default_opener", opener):
            e = _run(self.p.gh_search("   ", 1))
        _env(self, e, ok_value=False)
        self.assertEqual(e["code"], "E_PATH_INVALID")
        self.assertEqual(opener.calls, [])


class TestReleasesRPC(_DownloadMixin, unittest.TestCase):
    def test_releases_marks_only_zip_assets_usable_and_drops_body(self):
        opener = self._opener()
        with mock.patch.object(download, "default_opener", opener):
            e = _run(self.p.gh_releases("Esca-MMC", "DestroyableBushes"))
        _env(self, e, ok_value=True)
        rel = e["data"]["releases"][0]
        self.assertNotIn("body", rel)
        usable = [a["usable"] for a in rel["assets"]]
        self.assertEqual(usable, [True, False])

    def test_releases_rejects_a_path_traversal_in_the_owner(self):
        opener = self._opener()
        with mock.patch.object(download, "default_opener", opener):
            e = _run(self.p.gh_releases("../../etc", "passwd"))
        _env(self, e, ok_value=False)
        self.assertEqual(e["code"], "E_PATH_INVALID")
        self.assertEqual(opener.calls, [])


class TestDownloadRPCs(_DownloadMixin, unittest.TestCase):
    def test_download_default_phase_is_read_only_inspect(self):
        opener = self._opener()
        with mock.patch.object(download, "default_opener", opener):
            e = _run(self.p.gh_download("Esca-MMC", "DestroyableBushes",
                                        252770482, "bush.zip", False, False))
        _env(self, e, ok_value=True)
        self.assertEqual(e["data"]["phase"], "inspect")
        self.assertFalse(e["data"]["install_allowed"])
        self.engine.install.assert_not_called()
        self.assertTrue(os.path.isfile(os.path.join(self.inbox, "bush.zip")))

    def test_download_with_allow_but_no_confirm_writes_nothing(self):
        opener = self._opener()
        with mock.patch.object(download, "default_opener", opener):
            e = _run(self.p.gh_download("Esca-MMC", "DestroyableBushes",
                                        252770482, "bush.zip", True, False))
        _env(self, e, ok_value=True)
        self.assertEqual(e["data"]["phase"], "confirm")
        self.assertTrue(e["data"]["install_allowed"])
        self.engine.install.assert_not_called()

    def test_download_propagates_the_engine_external_manager_verdict(self):
        opener = self._opener()
        self.engine.install.return_value = err(
            "E_EXTERNAL_MANAGER",
            detail="external mod manager markers in Mods; read-only mode")
        with mock.patch.object(download, "default_opener", opener):
            e = _run(self.p.gh_download("Esca-MMC", "DestroyableBushes",
                                        252770482, "bush.zip", True, True))
        _env(self, e, ok_value=False)
        self.assertEqual(e["code"], "E_EXTERNAL_MANAGER")
        self.engine.install.assert_called_once()

    def test_download_refuses_an_offhost_asset_redirect(self):
        routes = {
            "/releases/assets/": (302, {"Location": "https://evil.example.com/x.zip"}, b""),
        }
        opener = _Opener(routes)
        with mock.patch.object(download, "default_opener", opener):
            e = _run(self.p.gh_download("o", "r", 7, "x.zip", False, False))
        _env(self, e, ok_value=False)
        self.assertEqual(e["code"], "E_PATH_ESCAPE")
        self.assertIn("DL_HOST_NOT_ALLOWED", e["detail"])
        # the off-host redirect must never have been fetched
        self.assertEqual(len(opener.calls), 1)

    def test_download_maps_a_404_asset_to_a_shipped_code(self):
        opener = self._opener(asset_status=404)
        with mock.patch.object(download, "default_opener", opener):
            e = _run(self.p.gh_download("o", "r", 7, "x.zip", False, False))
        _env(self, e, ok_value=False)
        self.assertEqual(e["code"], "E_INBOX_UNREADABLE")
        self.assertIn("DL_NOT_FOUND", e["detail"])


class TestDirectUrlRPC(_DownloadMixin, unittest.TestCase):
    def test_direct_url_downloads_into_the_inbox_only(self):
        opener = _Opener({"example.com/mod.zip": (200, {}, ZIP_BYTES)})
        with mock.patch.object(download, "default_opener", opener):
            e = _run(self.p.download_url("https://example.com/mod.zip",
                                         "direct.zip", False, False))
        _env(self, e, ok_value=True)
        self.assertEqual(e["data"]["phase"], "inspect")
        self.assertEqual(e["data"]["source"], "url")
        self.assertTrue(os.path.isfile(os.path.join(self.inbox, "direct.zip")))
        self.engine.install.assert_not_called()

    def test_direct_url_refuses_plain_http(self):
        opener = _Opener({})
        with mock.patch.object(download, "default_opener", opener):
            e = _run(self.p.download_url("http://example.com/mod.zip",
                                         "direct.zip", False, False))
        _env(self, e, ok_value=False)
        self.assertEqual(e["code"], "E_PATH_INVALID")
        self.assertEqual(opener.calls, [])

    def test_direct_url_refuses_userinfo_and_non_default_port(self):
        for url in ("https://user:pw@example.com/mod.zip",
                    "https://example.com:8443/mod.zip"):
            opener = _Opener({})
            with mock.patch.object(download, "default_opener", opener):
                e = _run(self.p.download_url(url, "d.zip", False, False))
            _env(self, e, ok_value=False)
            self.assertEqual(e["code"], "E_PATH_INVALID", url)
            self.assertEqual(opener.calls, [], url)

    def test_direct_url_refuses_a_private_literal_host(self):
        opener = _Opener({})
        with mock.patch.object(download, "default_opener", opener):
            e = _run(self.p.download_url("https://127.0.0.1/mod.zip",
                                         "d.zip", False, False))
        _env(self, e, ok_value=False)
        self.assertEqual(e["code"], "E_PATH_ESCAPE")


class TestGateAndConfig(_DownloadMixin, unittest.TestCase):
    def test_every_download_rpc_is_gated_by_the_capability(self):
        blocked = err("E_CAPABILITY_DISABLED", detail="gated")
        calls = [
            ("gh_search", ("q", 1)),
            ("gh_releases", ("o", "r")),
            ("gh_download", ("o", "r", 1, "x.zip", False, False)),
            ("download_url", ("https://example.com/m.zip", "x.zip", False, False)),
        ]
        with mock.patch.object(main, "_network_download_gate", return_value=blocked):
            for name, args in calls:
                e = _run(getattr(self.p, name)(*args))
                _env(self, e, ok_value=False)
                self.assertEqual(e["code"], "E_CAPABILITY_DISABLED", name)
                self.assertEqual(e["detail"], "gated", name)

    def test_direct_source_can_be_disabled_by_the_descriptor(self):
        desc = {"capabilities": {"network_download": True},
                "download_sources": {"direct": {"enabled": False}}}
        with mock.patch.object(main, "_network_download_gate", return_value=None), \
                mock.patch.object(main, "_source_cfg",
                                  side_effect=lambda n: (desc["download_sources"].get(n) or {})):
            e = _run(self.p.download_url("https://example.com/m.zip", "x.zip", False, False))
        _env(self, e, ok_value=False)
        self.assertEqual(e["code"], "E_CAPABILITY_DISABLED")
        self.assertIn("direct", e["detail"])

    def test_source_cfg_reads_the_live_descriptor(self):
        cfg = main._source_cfg("github")
        self.assertIsInstance(cfg, dict)
        self.assertTrue(cfg.get("enabled"))
        self.assertIn("release-assets.githubusercontent.com", cfg.get("asset_hosts") or [])

    def test_github_sends_no_credentials(self):
        opener = self._opener()
        with mock.patch.object(download, "default_opener", opener):
            _run(self.p.gh_search("q", 1))
            _run(self.p.gh_releases("Esca-MMC", "DestroyableBushes"))
        self.assertTrue(opener.calls)
        for _method, _url, headers in opener.calls:
            lowered = {k.lower() for k in headers}
            self.assertNotIn("authorization", lowered)
            self.assertNotIn("apikey", lowered)


class TestMapping(_DownloadMixin, unittest.TestCase):
    def test_the_three_new_codes_map_onto_shipped_error_codes(self):
        self.assertEqual(auto_import.DL_TO_E["DL_HOST_NOT_ALLOWED"], "E_PATH_ESCAPE")
        self.assertEqual(auto_import.DL_TO_E["DL_NO_ASSET"], "E_INBOX_UNREADABLE")
        self.assertEqual(auto_import.DL_TO_E["DL_NOT_FOUND"], "E_INBOX_UNREADABLE")
        from deckymod.errors import ERRORS
        self.assertEqual(len(ERRORS), 52)
        for code in ("DL_HOST_NOT_ALLOWED", "DL_NO_ASSET", "DL_NOT_FOUND"):
            self.assertIn(code, download.DL_ERRORS)
            self.assertNotIn(code, ERRORS)

    def test_module_imports_stay_stdlib_only_at_the_top_level(self):
        import ast
        # Path-independent: this suite runs on Windows (dev box) AND on the
        # Deck (Linux build tree), so never hardcode an absolute root.
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = open(os.path.join(root, "deckymod", "github_source.py"),
                   encoding="utf-8").read()
        tree = ast.parse(src)
        tops = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                tops.extend(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                tops.append((node.module or "").split(".")[0])
        allowed = {"__future__", "re", "urllib", "download"}
        self.assertEqual(sorted(set(tops) - allowed), [], tops)


if __name__ == "__main__":
    unittest.main()
