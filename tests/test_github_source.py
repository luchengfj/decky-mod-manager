"""Round 19: unit coverage for deckymod.github_source.

Everything is driven through an injected opener, so this file never opens a
socket. The behaviours pinned here are the ones a wrong implementation would
silently get wrong: the 302 two-hop asset dance, the host allow-list on the
redirect target, the "usable" predicate, and the refusal to put credentials on
any request.
"""

from __future__ import annotations

import json
import os
import unittest

from deckymod import github_source as gs
from deckymod.download import DownloadError

ASSET_HOST = "release-assets.githubusercontent.com"
SIGNED = ("https://" + ASSET_HOST +
          "/github-production-release-asset/1?sp=r&sig=abc&jwt=def")


class _Resp:
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
        self.calls.append({"method": method, "url": url, "headers": dict(headers)})
        for fragment, spec in self.routes.items():
            if fragment in url:
                return _Resp(spec[0], spec[1], spec[2] if len(spec) > 2 else b"")
        return _Resp(404, {}, b"{}")


class TestUrlPolicy(unittest.TestCase):
    def test_plain_http_is_rejected(self):
        with self.assertRaises(DownloadError) as ctx:
            gs._check_host("http://api.github.com/x", gs._API_ALLOW)
        self.assertEqual(ctx.exception.code, "DL_BAD_URL")

    def test_userinfo_is_rejected(self):
        with self.assertRaises(DownloadError) as ctx:
            gs._check_host("https://u:p@api.github.com/x", gs._API_ALLOW)
        self.assertEqual(ctx.exception.code, "DL_BAD_URL")

    def test_non_default_port_is_rejected(self):
        with self.assertRaises(DownloadError) as ctx:
            gs._check_host("https://api.github.com:8443/x", gs._API_ALLOW)
        self.assertEqual(ctx.exception.code, "DL_BAD_URL")

    def test_offhost_is_rejected_with_the_allow_list_code(self):
        with self.assertRaises(DownloadError) as ctx:
            gs._check_host("https://evil.example.com/x", gs._API_ALLOW)
        self.assertEqual(ctx.exception.code, "DL_HOST_NOT_ALLOWED")

    def test_trailing_dot_host_is_normalised_then_matched(self):
        with self.assertRaises(DownloadError) as ctx:
            gs._check_host("https://evil.example.com./x", gs._API_ALLOW)
        self.assertEqual(ctx.exception.code, "DL_HOST_NOT_ALLOWED")

    def test_api_host_passes_with_a_trailing_dot(self):
        self.assertIn("api.github.com",
                      gs._check_host("https://api.github.com./zen", gs._API_ALLOW))


class TestNames(unittest.TestCase):
    def test_valid_names_pass_through(self):
        self.assertEqual(gs._name("Esca-MMC", "owner"), "Esca-MMC")
        self.assertEqual(gs._name("a_b.c-d9", "repo"), "a_b.c-d9")

    def test_traversal_and_empty_names_are_rejected(self):
        for bad in ("../etc", "", "a/b", "a b", "a" * 101, "a\n"):
            with self.assertRaises(DownloadError) as ctx:
                gs._name(bad, "owner")
            self.assertEqual(ctx.exception.code, "DL_BAD_URL", repr(bad))

    def test_ints_parse_and_reject_non_positive(self):
        self.assertEqual(gs._as_int("42", "asset_id"), 42)
        for bad in (0, -3, "abc", None, True):
            with self.assertRaises(DownloadError):
                gs._as_int(bad, "asset_id")


class TestSearch(unittest.TestCase):
    def _body(self):
        return json.dumps({"total_count": 3, "items": [
            {"full_name": "Esca-MMC/DestroyableBushes", "stargazers_count": 33,
             "description": "d" * 400, "updated_at": "2026-01-01",
             "archived": False},
            {"full_name": "no-slash-here"},
            "not-a-dict",
        ]}).encode()

    def test_search_slims_and_truncates(self):
        opener = _Opener({"/search/repositories": (200, {}, self._body())})
        res = gs.search_repos(opener, "stardew", 1)
        self.assertTrue(res["ok"])
        self.assertEqual(res["total_count"], 3)
        self.assertEqual(len(res["items"]), 1)
        item = res["items"][0]
        self.assertEqual(len(item["description"]), gs.MAX_DESCRIPTION)
        self.assertEqual(item["owner"], "Esca-MMC")

    def test_search_clamps_page_and_encodes_the_query(self):
        opener = _Opener({"/search/repositories": (200, {}, b'{"total_count":0,"items":[]}')})
        gs.search_repos(opener, "a b&c=d", 500)
        url = opener.calls[0]["url"]
        self.assertIn("page=100", url)
        self.assertIn("a%20b%26c%3Dd", url)

    def test_search_rejects_bad_input_without_a_request(self):
        opener = _Opener({})
        for query, page in (("", 1), ("q", 0), ("q", "x"), ("a" * 201, 1)):
            res = gs.search_repos(opener, query, page)
            self.assertFalse(res["ok"], (query[:8], page))
            self.assertEqual(res["code"], "DL_BAD_URL")
        self.assertEqual(opener.calls, [])

    def test_search_reports_a_non_object_payload(self):
        opener = _Opener({"/search/repositories": (200, {}, b"[]")})
        res = gs.search_repos(opener, "q", 1)
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "DL_BAD_JSON")


class TestReleases(unittest.TestCase):
    def _body(self):
        return json.dumps([{
            "id": 1, "tag_name": "1.5.2", "name": "1.5.2", "prerelease": False,
            "draft": False, "published_at": "2026-02-02", "body": "x" * 5000,
            "assets": [
                {"id": 1, "name": "a.zip", "size": 1,
                 "content_type": "application/zip", "download_count": 3},
                {"id": 2, "name": "b.zip", "size": 1,
                 "content_type": "application/x-zip-compressed", "download_count": 4},
                {"id": 3, "name": "c.bin", "size": 1,
                 "content_type": "application/octet-stream", "download_count": 5},
                {"id": 4, "name": "d.exe", "size": 1,
                 "content_type": "application/octet-stream", "download_count": 6},
                {"id": 5, "name": "e.zip", "size": 1,
                 "content_type": "text/html", "download_count": 7},
            ],
        }]).encode()

    def test_only_zip_assets_with_a_binary_content_type_are_usable(self):
        opener = _Opener({"/releases?": (200, {}, self._body())})
        res = gs.list_releases(opener, "o", "r")
        self.assertTrue(res["ok"])
        usable = [(a["id"], a["usable"]) for a in res["releases"][0]["assets"]]
        self.assertEqual(usable, [(1, True), (2, True), (3, False),
                                  (4, False), (5, False)])

    def test_release_body_is_dropped(self):
        opener = _Opener({"/releases?": (200, {}, self._body())})
        rel = gs.list_releases(opener, "o", "r")["releases"][0]
        self.assertNotIn("body", rel)
        self.assertNotIn("browser_download_url", rel["assets"][0])

    def test_releases_request_uses_the_capped_page_size(self):
        opener = _Opener({"/releases?": (200, {}, b"[]")})
        gs.list_releases(opener, "o", "r")
        self.assertIn("per_page=%d" % gs.PER_PAGE_CAP, opener.calls[0]["url"])

    def test_releases_reports_a_non_array_payload(self):
        opener = _Opener({"/releases?": (200, {}, b"{}")})
        res = gs.list_releases(opener, "o", "r")
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "DL_BAD_JSON")


class TestResolveAsset(unittest.TestCase):
    def test_signed_redirect_resolves_without_following(self):
        opener = _Opener({"/releases/assets/": (302, {"Location": SIGNED}, b"")})
        res = gs.resolve_asset(opener, "o", "r", 252770482)
        self.assertTrue(res["ok"])
        self.assertEqual(res["host"], ASSET_HOST)
        self.assertEqual(res["url"], SIGNED)
        self.assertEqual(len(opener.calls), 1)

    def test_asset_request_asks_for_octet_stream(self):
        opener = _Opener({"/releases/assets/": (302, {"Location": SIGNED}, b"")})
        gs.resolve_asset(opener, "o", "r", 1)
        headers = opener.calls[0]["headers"]
        self.assertEqual(headers.get("Accept"), "application/octet-stream")

    def test_asset_redirect_to_an_offhost_target_is_refused(self):
        opener = _Opener({"/releases/assets/": (
            302, {"Location": "https://evil.example.com/x.zip"}, b"")})
        res = gs.resolve_asset(opener, "o", "r", 1)
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "DL_HOST_NOT_ALLOWED")
        self.assertEqual(len(opener.calls), 1)

    def test_asset_redirect_must_stay_https(self):
        opener = _Opener({"/releases/assets/": (
            302, {"Location": "http://" + ASSET_HOST + "/x.zip"}, b"")})
        res = gs.resolve_asset(opener, "o", "r", 1)
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "DL_BAD_URL")

    def test_missing_location_is_reported_as_no_asset(self):
        opener = _Opener({"/releases/assets/": (302, {}, b"")})
        res = gs.resolve_asset(opener, "o", "r", 1)
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "DL_NO_ASSET")

    def test_status_codes_map_to_distinct_codes(self):
        expect = {404: "DL_NOT_FOUND", 403: "DL_FORBIDDEN",
                  429: "DL_RATE_LIMIT", 500: "DL_HTTP"}
        for status, code in expect.items():
            opener = _Opener({"/releases/assets/": (status, {}, b"{}")})
            res = gs.resolve_asset(opener, "o", "r", 1)
            self.assertFalse(res["ok"], status)
            self.assertEqual(res["code"], code, status)

    def test_no_credentials_ever_reach_the_wire(self):
        opener = _Opener({"/releases/assets/": (302, {"Location": SIGNED}, b"")})
        gs.resolve_asset(opener, "o", "r", 1)
        headers = opener.calls[0]["headers"]
        for banned in ("Authorization", "apikey", "X-Api-Key"):
            self.assertNotIn(banned, headers)

    def test_unparsable_redirect_is_contained(self):
        opener = _Opener({"/releases/assets/": (302, {"Location": "https://"}, b"")})
        res = gs.resolve_asset(opener, "o", "r", 1)
        self.assertFalse(res["ok"])
        self.assertIn(res["code"], {"DL_HOST_NOT_ALLOWED", "DL_BAD_URL"})


class TestDirectUrlValidation(unittest.TestCase):
    def test_good_https_url_passes(self):
        self.assertEqual(gs._validate_download_url("https://example.com/a.zip"),
                         "https://example.com/a.zip")

    def test_bad_urls_are_rejected(self):
        for bad in ("", None, "http://example.com/a.zip", "https://u:p@example.com/a.zip",
                    "https://example.com:8443/a.zip", "https:///a.zip", 12345):
            with self.assertRaises(DownloadError) as ctx:
                gs._validate_download_url(bad)
            self.assertEqual(ctx.exception.code, "DL_BAD_URL", repr(bad))


class TestHostConstants(unittest.TestCase):
    def test_asset_hosts_are_https_github_infrastructure(self):
        self.assertIn(ASSET_HOST, gs.ASSET_HOSTS)
        self.assertEqual(gs.API_HOST, "api.github.com")
        self.assertLessEqual(gs.PER_PAGE_CAP, 10)

    def test_module_has_no_credentials_surface(self):
        """No credential-bearing identifier may be referenced by real CODE.

        Checked through the AST rather than by raw substring: the module's own
        docstring legitimately says "No credentials are sent", and a text search
        would fail on that prose while telling us nothing about the code.
        """
        import ast
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "deckymod", "github_source.py")
        tree = ast.parse(open(path, encoding="utf-8").read())
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    names.add(alias.name)
                    if alias.asname:
                        names.add(alias.asname)
            elif isinstance(node, ast.alias):
                names.add(node.name)
        banned = {"credentials", "api_key", "apikey", "Authorization",
                  "load_key", "save_key", "auth", "bearer"}
        self.assertEqual(sorted(names & banned), [])
        # ``urlsplit().password`` IS expected: it exists only to REFUSE URLs that
        # carry userinfo. Pin that it is never read out into a header or result.
        src = open(path, encoding="utf-8").read()
        self.assertIn("parts.password", src)
        self.assertIn("userinfo is not allowed", src)
        self.assertNotIn("headers=\"Authorization", src)
        # And the one header we do send must be the octet-stream Accept.
        self.assertIn("application/octet-stream", src)


if __name__ == "__main__":
    unittest.main()
