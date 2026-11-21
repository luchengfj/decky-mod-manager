"""Round 39: the credential store and the Nexus metadata client.

Every behaviour pinned here was measured on the real device before it was
written (see ``.decky-probe/r39_nexus_research.md`` for the raw status codes).
The tests exist because each of these is a place where a plausible-looking
implementation is wrong in a way that only shows up in front of a user:

* an alphanumeric-only key check rejects a real Nexus key (contains ``+ / = -``)
* forwarding ``validate.json`` verbatim ships the key back to the UI
* treating every 403 as "needs premium" hides a deleted mod behind a wrong fix
* returning ``""`` for a missing key turns an authenticated call into a silent
  anonymous one, which surfaces as a confusing 401
* writing the key through a symlink exfiltrates it to a path of someone else's
  choosing

None of these touch a socket: the opener is injected everywhere.
"""

from __future__ import annotations

import json
import os
import shutil
import unittest
import uuid

from deckymod import credentials as cred
from deckymod import nexus

_TMP_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         ".decky-test-tmp")

#: A realistic key: 96 chars, base64 alphabet, all three punctuation characters
#: that an alphanumeric-only check would reject.
REAL_STYLE_KEY = ("aB3dE6gH9jK2mN5pQ8sT1vW4yZ7bC0eF3hI6kL9nO2qR5tU8wX1zA4"
                  "dG7jM0pS3vY6bE9hK2nQ5tW8zC1fI4lO7rU0xY3") + "+/="


def _tmpdir(name: str) -> str:
    path = os.path.join(_TMP_ROOT, "r39%s_%s" % (name, uuid.uuid4().hex[:8]))
    os.makedirs(path, exist_ok=True)
    return path


class _EnvMixin(unittest.TestCase):
    """Point ``DECKYMOD_DATA`` at a scratch *data* directory and restore it.

    The backend applies the journal's rule: a path that does not already end in
    ``data`` gets ``data`` appended, so the credential file lands beside
    ``journal/`` and ``snapshots/``. The scratch dir below follows that rule too,
    which is why the tests assert against ``cred.key_path()`` rather than
    hand-building the path.
    """

    def setUp(self):
        self._saved = os.environ.get("DECKYMOD_DATA")
        self.dir = os.path.join(_tmpdir(self.__class__.__name__), "data")
        os.makedirs(self.dir, exist_ok=True)
        os.environ["DECKYMOD_DATA"] = self.dir
        self.addCleanup(self._restore)

    def _restore(self):
        if self._saved is None:
            os.environ.pop("DECKYMOD_DATA", None)
        else:
            os.environ["DECKYMOD_DATA"] = self._saved
        shutil.rmtree(self.dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# credentials
# ---------------------------------------------------------------------------

class TestKeyFormat(unittest.TestCase):
    def test_real_style_key_with_punctuation_is_accepted(self):
        self.assertIsNone(cred.validate_key_format(REAL_STYLE_KEY))

    def test_alphanumeric_only_assumption_fails_a_real_key(self):
        # This is the shipped-once bug, kept as a test so it cannot come back:
        # if the regex were narrowed, a valid key would be refused here.
        self.assertNotRegex(REAL_STYLE_KEY, r"\A[A-Za-z0-9]+\Z")
        self.assertIsNone(cred.validate_key_format(REAL_STYLE_KEY))

    def test_short_key_is_refused(self):
        self.assertIsNotNone(cred.validate_key_format("abc"))

    def test_key_with_space_is_refused(self):
        self.assertIsNotNone(cred.validate_key_format(REAL_STYLE_KEY + " x"))

    def test_empty_is_refused(self):
        self.assertIsNotNone(cred.validate_key_format("   "))

    def test_non_string_is_refused(self):
        self.assertIsNotNone(cred.validate_key_format(None))


class TestSaveAndRead(_EnvMixin):
    def test_saved_file_is_private_and_holds_the_key(self):
        out = cred.save_key(REAL_STYLE_KEY)
        self.assertTrue(out["stored"])
        self.assertEqual(out["mode_requested"], "0o600")
        st = os.stat(cred.key_path())
        if os.name == "posix":
            self.assertEqual(st.st_mode & 0o777, 0o600)
        with open(cred.key_path(), "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), REAL_STYLE_KEY)

    def test_save_result_never_contains_the_key(self):
        out = cred.save_key(REAL_STYLE_KEY)
        self.assertNotIn(REAL_STYLE_KEY, json.dumps(out))

    def test_roundtrip_returns_the_same_key(self):
        cred.save_key(REAL_STYLE_KEY)
        self.assertEqual(cred.read_key(), REAL_STYLE_KEY)

    def test_surrounding_whitespace_is_stripped_not_stored(self):
        cred.save_key("  " + REAL_STYLE_KEY + "\n")
        self.assertEqual(cred.read_key(), REAL_STYLE_KEY)

    def test_update_replaces_content_without_leaving_temp_files(self):
        first = REAL_STYLE_KEY
        second = REAL_STYLE_KEY[:-1] + "z"
        cred.save_key(first)
        cred.save_key(second)
        self.assertEqual(cred.read_key(), second)
        self.assertFalse(os.path.exists(cred.key_path() + ".tmp"))

    def test_bad_key_is_refused_and_writes_nothing(self):
        with self.assertRaises(ValueError):
            cred.save_key("nope")
        self.assertFalse(os.path.exists(cred.key_path()))


class TestReadFailsClosed(_EnvMixin):
    def test_missing_key_raises_instead_of_returning_empty(self):
        # An empty string would silently downgrade every call to anonymous.
        with self.assertRaises(OSError):
            cred.read_key()

    def test_malformed_file_raises(self):
        os.makedirs(self.dir, exist_ok=True)
        with open(cred.key_path(), "w", encoding="utf-8") as f:
            f.write("not a key !!")
        with self.assertRaises(ValueError):
            cred.read_key()

    def test_data_dir_follows_the_journal_rule(self):
        # A runtime dir without a trailing "data" gets one appended, so the key
        # sits beside journal/ and snapshots/ instead of one level above them.
        self.assertEqual(os.path.basename(self.dir), "data")
        self.assertEqual(os.path.dirname(os.path.dirname(cred.key_path())),
                         os.path.dirname(self.dir))


class TestStatus(_EnvMixin):
    def test_missing_state(self):
        st = cred.key_status()
        self.assertFalse(st["configured"])
        self.assertEqual(st["state"], "missing")

    def test_present_state_and_never_the_value(self):
        cred.save_key(REAL_STYLE_KEY)
        st = cred.key_status()
        self.assertTrue(st["configured"])
        self.assertEqual(st["state"], "present")
        self.assertNotIn(REAL_STYLE_KEY, json.dumps(st))

    def test_world_readable_file_is_reported_unreadable(self):
        if os.name != "posix":
            self.skipTest("POSIX permission bits only")
        cred.save_key(REAL_STYLE_KEY)
        os.chmod(cred.key_path(), 0o644)
        st = cred.key_status()
        self.assertEqual(st["state"], "unreadable")
        self.assertFalse(st["mode_ok"])
        self.assertNotIn(REAL_STYLE_KEY, json.dumps(st))

    def test_status_does_not_open_the_file(self):
        # A stat-only implementation still answers when the file cannot be read.
        if os.name != "posix":
            self.skipTest("POSIX permission bits only")
        cred.save_key(REAL_STYLE_KEY)
        os.chmod(cred.key_path(), 0o000)
        self.addCleanup(os.chmod, cred.key_path(), 0o600)
        st = cred.key_status()
        self.assertTrue(st["configured"])


class TestDelete(_EnvMixin):
    def test_delete_reports_true_when_it_removed_something(self):
        cred.save_key(REAL_STYLE_KEY)
        out = cred.delete_key()
        self.assertTrue(out["deleted"])
        self.assertFalse(os.path.exists(cred.key_path()))

    def test_delete_reports_false_and_says_why(self):
        out = cred.delete_key()
        self.assertFalse(out["deleted"])
        self.assertEqual(out["reason"], "no key was stored")


class TestSymlinkRefusal(_EnvMixin):
    def test_symlinked_credential_path_is_refused(self):
        if os.name != "posix":
            self.skipTest("symlinks on POSIX only")
        target = os.path.join(self.dir, "elsewhere.txt")
        with open(target, "w", encoding="utf-8") as f:
            f.write("x")
        os.symlink(target, cred.key_path())
        with self.assertRaises(PermissionError):
            cred.read_key()
        with self.assertRaises(PermissionError):
            cred.delete_key()


# ---------------------------------------------------------------------------
# nexus
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, status, body=b"", headers=None):
        self.status = status
        self._body = body if isinstance(body, bytes) else body.encode("utf-8")
        self.headers = dict(headers or {})
        self._pos = 0
        self.closed = False

    def read(self, amt=-1):
        if amt is None or amt < 0:
            out, self._pos = self._body[self._pos:], len(self._body)
            return out
        out = self._body[self._pos:self._pos + amt]
        self._pos += len(out)
        return out

    def close(self):
        self.closed = True


class _Opener:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, method, url, headers, timeout):
        self.calls.append({"method": method, "url": url, "headers": dict(headers)})
        for fragment, spec in self.routes.items():
            if fragment in url:
                return _Resp(*spec)
        return _Resp(404, b'{"message":"Not Found"}')


def _json(payload) -> bytes:
    return json.dumps(payload).encode("utf-8")


class TestHostPin(unittest.TestCase):
    def test_requests_go_to_the_api_host_only(self):
        op = _Opener({"/users/validate.json": (200, _json({"name": "x"}))})
        nexus.validate(op, REAL_STYLE_KEY)
        self.assertEqual(len(op.calls), 1)
        self.assertTrue(op.calls[0]["url"].startswith("https://api.nexusmods.com/v1/"))

    def test_key_never_appears_in_the_url(self):
        op = _Opener({"/users/validate.json": (200, _json({"name": "x"}))})
        nexus.validate(op, REAL_STYLE_KEY)
        self.assertNotIn(REAL_STYLE_KEY, op.calls[0]["url"])

    def test_key_is_sent_in_the_apikey_header(self):
        op = _Opener({"/users/validate.json": (200, _json({"name": "x"}))})
        nexus.validate(op, REAL_STYLE_KEY)
        self.assertEqual(op.calls[0]["headers"]["apikey"], REAL_STYLE_KEY)


class TestValidateScrubbing(unittest.TestCase):
    def test_echoed_key_never_reaches_the_result(self):
        # The server really does echo the key back in a ``key`` field.
        body = _json({"name": "someone", "is_premium": False, "is_supporter": False,
                      "email_verified": True, "profile_url": "https://x/y",
                      "key": REAL_STYLE_KEY})
        op = _Opener({"/users/validate.json": (200, body)})
        out = nexus.validate(op, REAL_STYLE_KEY)
        self.assertTrue(out["ok"])
        self.assertNotIn(REAL_STYLE_KEY, json.dumps(out))
        self.assertNotIn("key", out)

    def test_only_whitelisted_fields_are_returned(self):
        body = _json({"name": "someone", "is_premium": True, "is_supporter": True,
                      "email_verified": True, "profile_url": "https://x/y",
                      "key": REAL_STYLE_KEY, "unexpected": "drop me"})
        op = _Opener({"/users/validate.json": (200, body)})
        out = nexus.validate(op, REAL_STYLE_KEY)
        self.assertEqual(sorted(out.keys()), 
                         ["email_verified", "is_premium", "is_supporter", "name",
                          "ok", "profile_url", "status"])
        self.assertTrue(out["is_premium"])

    def test_anonymous_401_maps_to_auth_required_with_a_hint(self):
        op = _Opener({"/users/validate.json": (
            401, b'{"message":"Please provide an authentication method"}')})
        out = nexus.validate(op, "")
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "DL_AUTH_REQUIRED")
        self.assertIn("nexusmods.com/users/myaccount", out["hint"])

    def test_junk_key_401_is_explained_not_echoed(self):
        op = _Opener({"/users/validate.json": (
            401, b'{"message":"Please provide a valid API Key"}')})
        out = nexus.validate(op, "garbage-key-value")
        self.assertFalse(out["ok"])
        problem = nexus.key_problem(out)
        self.assertIn("rejected", problem)

    def test_key_problem_returns_none_on_success(self):
        self.assertIsNone(nexus.key_problem({"ok": True}))


class TestDownloadLinkHonesty(unittest.TestCase):
    PREMIUM_403 = (403, b'{"code":403,"message":"You don\'t have permission to get '
                        b'download links from the API without visting nexusmods.com -\\n '
                        b'this is for premium users only."}')

    def test_premium_gate_is_reported_as_such_with_a_browser_url(self):
        op = _Opener({"/download_link.json": self.PREMIUM_403})
        out = nexus.download_link(op, "stardewvalley", 2400, 12345, REAL_STYLE_KEY)
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "DL_FORBIDDEN")
        self.assertTrue(out["premium_required"])
        self.assertEqual(out["browser_url"],
                         "https://www.nexusmods.com/stardewvalley/mods/2400")
        self.assertIn("premium", out["detail"].lower())

    def test_missing_mod_403_is_not_reported_as_premium(self):
        op = _Opener({"/download_link.json": (
            403, b'{"code":403,"message":"Mod not available: 4729"}')})
        out = nexus.download_link(op, "stardewvalley", 4729, 1, REAL_STYLE_KEY)
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "DL_NOT_FOUND")
        self.assertFalse(out.get("premium_required", False))

    def test_success_carries_the_page_url_for_free_users(self):
        op = _Opener({"/download_link.json": (200, _json([{"URI": "https://x/y"}]))})
        out = nexus.download_link(op, "stardewvalley", 2400, 1, REAL_STYLE_KEY)
        self.assertTrue(out["ok"])
        self.assertEqual(out["browser_url"],
                         "https://www.nexusmods.com/stardewvalley/mods/2400")


class TestModFiles(unittest.TestCase):
    def test_large_response_is_trimmed_to_ui_fields(self):
        rows = [{"file_id": 1, "name": "Main", "version": "1.0",
                 "category_name": "MAIN", "file_name": "main.zip", "size_kb": 10,
                 "uploaded_timestamp": 1, "mod_version": "1.0",
                 "dependencies": [{"huge": "blob"}], "uid": 99}]
        op = _Opener({"/files.json": (200, _json({"files": rows}))})
        out = nexus.mod_files(op, "stardewvalley", 2400, REAL_STYLE_KEY)
        self.assertTrue(out["ok"])
        self.assertEqual(out["count"], 1)
        self.assertNotIn("dependencies", out["files"][0])
        self.assertNotIn("uid", out["files"][0])
        self.assertEqual(out["files"][0]["file_id"], 1)


class TestNoKeywordSearch(unittest.TestCase):
    def test_module_exposes_no_search_function(self):
        # The endpoint does not exist; a search UI would be a lie.
        self.assertFalse(hasattr(nexus, "search"))

    def test_unknown_listing_kind_is_refused_locally(self):
        op = _Opener({})
        out = nexus.recent(op, "stardewvalley", "search", REAL_STYLE_KEY)
        self.assertFalse(out["ok"])
        self.assertEqual(op.calls, [])

    def test_each_supported_kind_builds_the_documented_path(self):
        for kind in ("latest_added", "latest_updated", "trending"):
            op = _Opener({"/mods/%s.json" % kind: (200, _json([
                {"mod_id": 5, "name": "M", "author": "A"}]))})
            out = nexus.recent(op, "stardewvalley", kind, REAL_STYLE_KEY)
            self.assertTrue(out["ok"], kind)
            self.assertEqual(out["count"], 1)
            self.assertEqual(out["mods"][0]["mod_page_url"],
                             "https://www.nexusmods.com/stardewvalley/mods/5")

    def test_response_is_strict_json_safe(self):
        op = _Opener({"/mods/trending.json": (200, _json([
            {"mod_id": 5, "endorsement_count": 1.5}]))})
        out = nexus.recent(op, "stardewvalley", "trending", REAL_STYLE_KEY)
        json.dumps(out, allow_nan=False)


class TestTransport(unittest.TestCase):
    def test_bad_json_is_a_clean_failure(self):
        op = _Opener({"/users/validate.json": (200, b"{not json")})
        out = nexus.validate(op, REAL_STYLE_KEY)
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "DL_BAD_JSON")

    def test_network_exception_is_a_clean_failure(self):
        def boom(*a, **k):
            raise OSError("no route to host")

        out = nexus.validate(boom, REAL_STYLE_KEY)
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "DL_NETWORK")
        self.assertNotIn(REAL_STYLE_KEY, json.dumps(out))

    def test_rate_limit_is_distinguished(self):
        op = _Opener({"/users/validate.json": (429, b'{"message":"slow down"}')})
        out = nexus.validate(op, REAL_STYLE_KEY)
        self.assertEqual(out["code"], "DL_RATE_LIMIT")

    def test_failure_envelope_is_json_safe(self):
        op = _Opener({"/users/validate.json": (500, b"boom")})
        out = nexus.validate(op, REAL_STYLE_KEY)
        json.dumps(out, allow_nan=False)


class TestNoKeyBrowseUrl(unittest.TestCase):
    """Round 73: Trending/Newest/Updated open a website page, no API key.

    The caller passes a sort KEY, never a URL; the address is built from the
    game domain so nothing can make the client open an arbitrary site.
    """

    def test_sort_keys_map_to_website_params(self):
        self.assertEqual(
            nexus.browse_page_url("stardewvalley", "trending"),
            "https://www.nexusmods.com/stardewvalley/mods?sort=trending")
        self.assertEqual(
            nexus.browse_page_url("stardewvalley", "latest_added"),
            "https://www.nexusmods.com/stardewvalley/mods?sort=newest")
        self.assertEqual(
            nexus.browse_page_url("stardewvalley", "latest_updated"),
            "https://www.nexusmods.com/stardewvalley/mods?sort=updated")

    def test_unknown_sort_is_refused(self):
        self.assertIsNone(nexus.browse_page_url("stardewvalley", "https://evil"))
        self.assertIsNone(nexus.browse_page_url("stardewvalley", ""))

    def test_domain_is_embedded_verbatim(self):
        self.assertIn("valheim", nexus.browse_page_url("valheim", "trending"))


if __name__ == "__main__":
    unittest.main()
