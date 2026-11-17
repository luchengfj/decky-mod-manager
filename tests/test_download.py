"""Offline tests for the policy-neutral, UNWIRED Download core (round 3).

STDLIB ONLY. No network, no Steam Deck, no live opener: every network call is
served by a FakeOpener. This module does NOT need DECKYMOD_GAME_ID (it never
constructs a Registry or resolves any game path), so it does not disturb the
import-time pin set by test_mvp.py / test_stardew.py.
"""
import json
import os
import unittest

from deckymod import download
from deckymod.download import _Response, DEFAULT_MAX_BYTES


def _tmpdir(name):
    # os.makedirs (NOT tempfile.mkdtemp: 0o700 DACL -> WinError 5 under sandbox).
    # Anchor at the module's own package dir so the suite is portable between
    # the Windows dev box and the Deck build tree (no hardcoded machine path).
    pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(download.__file__)))
    base = os.path.join(os.environ.get("DECKYMOD_TEST_TMP",
                                       os.path.join(pkg_root, ".decky-test-tmp")), name)
    os.makedirs(base, exist_ok=True)
    return base


def _json_safe(value, path="result"):
    """Assert the value round-trips through the stdlib JSON encoder and has no bytes."""
    assert not isinstance(value, (bytes, bytearray)), path + " has raw bytes"
    json.dumps(value, allow_nan=False, ensure_ascii=False)
    if isinstance(value, dict):
        for k, v in value.items():
            assert isinstance(k, str), path + " has non-str key"
            _json_safe(v, path + "." + k)
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _json_safe(v, path + "[%d]" % i)
    else:
        assert value is None or isinstance(value, (str, int, float, bool)), path + " unsafe leaf"


class FakeOpener:
    """Records every (method, url, headers, timeout) and serves canned responses."""

    def __init__(self, mapping):
        # mapping: url-substring -> _Response (or list of _Response for sequences)
        self.mapping = mapping
        self.calls = []

    def __call__(self, method, url, headers, timeout):
        self.calls.append({"method": method, "url": url,
                           "headers": dict(headers), "timeout": timeout})
        for key, resp in self.mapping.items():
            if key in url:
                if isinstance(resp, list):
                    return resp.pop(0) if len(resp) > 1 else resp[0]
                return resp
        raise AssertionError("FakeOpener: no canned response for " + url)


def _api(url_sub, body, status=200, headers=None):
    return _Response(status, headers or {}, [json.dumps(body).encode("utf-8")])






class TestFetchHardening(unittest.TestCase):
    """_fetch_bytes / download_to_inbox: URL scheme, SSRF floor, size caps."""

    def _inbox(self, name):
        return _tmpdir("legacy_" + name)

    def test_http_rejected(self):
        inbox = self._inbox("http")
        r = download.download_to_inbox(FakeOpener({}), "http://cdn.example/a.zip",
                                    "KEY", inbox, "a.zip")
        self.assertEqual(r["code"], "DL_BAD_URL")

    def test_file_scheme_rejected(self):
        inbox = self._inbox("file")
        r = download.download_to_inbox(FakeOpener({}), "file:///etc/passwd",
                                    "KEY", inbox, "a.zip")
        self.assertEqual(r["code"], "DL_BAD_URL")

    def test_private_host_rejected(self):
        inbox = self._inbox("private")
        for host in ("127.0.0.1", "localhost", "10.0.0.5", "169.254.169.254"):
            r = download.download_to_inbox(FakeOpener({}),
                                        "https://%s/latest/meta-data" % host,
                                        "KEY", inbox, "a.zip")
            self.assertEqual(r["code"], "DL_LOCAL_HOST", host)

    def test_apikey_not_sent_to_cdn(self):
        inbox = self._inbox("noauthcdn")
        op = FakeOpener({"cdn.example": _Response(200, {}, [b"PK\x03\x04data"])})
        r = download.download_to_inbox(op, "https://cdn.example/a.zip",
                                    "SECRETKEY999", inbox, "a.zip")
        _json_safe(r)
        self.assertTrue(r["ok"])
        self.assertNotIn("apikey", op.calls[0]["headers"])
        self.assertNotIn("SECRETKEY999", json.dumps(op.calls, ensure_ascii=False))

    def test_content_length_precheck(self):
        inbox = self._inbox("cl")
        op = FakeOpener({"cdn.example": _Response(200, {"Content-Length": "999999999"}, [b"x"])})
        r = download.download_to_inbox(op, "https://cdn.example/a.zip", "KEY",
                                    inbox, "a.zip", max_bytes=1024)
        self.assertEqual(r["code"], "DL_TOO_LARGE")

    def test_streaming_cap(self):
        inbox = self._inbox("stream")
        op = FakeOpener({"cdn.example": _Response(200, {}, [b"x" * 5000])})
        r = download.download_to_inbox(op, "https://cdn.example/a.zip", "KEY",
                                    inbox, "a.zip", max_bytes=1024, chunk=256)
        self.assertEqual(r["code"], "DL_TOO_LARGE")

    def test_truncation_detected(self):
        inbox = self._inbox("trunc")
        op = FakeOpener({"cdn.example": _Response(200, {"Content-Length": "100"}, [b"short"])})
        r = download.download_to_inbox(op, "https://cdn.example/a.zip", "KEY",
                                    inbox, "a.zip")
        self.assertEqual(r["code"], "DL_TRUNCATED")

    def test_http_error_status(self):
        inbox = self._inbox("status")
        op = FakeOpener({"cdn.example": _Response(503, {}, [b"down"])})
        r = download.download_to_inbox(op, "https://cdn.example/a.zip", "KEY",
                                    inbox, "a.zip")
        self.assertEqual(r["code"], "DL_HTTP")


class TestInboxContainment(unittest.TestCase):
    def _inbox(self, name):
        return _tmpdir("legacy_" + name)

    def _good_opener(self):
        return FakeOpener({"cdn.example": _Response(200, {}, [b"PK\x03\x04ZIPDATA"])})

    def test_happy_path_writes_file_and_is_json_safe(self):
        inbox = self._inbox("happy")
        r = download.download_to_inbox(self._good_opener(),
                                    "https://cdn.example/a.zip", "KEY", inbox, "mod.zip")
        _json_safe(r)
        self.assertTrue(r["ok"])
        self.assertEqual(r["status"], 200)
        self.assertEqual(r["size"], len(b"PK\x03\x04ZIPDATA"))
        self.assertEqual(len(r["sha256"]), 64)
        self.assertEqual(r["capped_at"], DEFAULT_MAX_BYTES)
        with open(r["path"], "rb") as f:
            self.assertEqual(f.read(), b"PK\x03\x04ZIPDATA")

    def test_bad_filename_rejected(self):
        inbox = self._inbox("badfn")
        for fn in ("../escape.zip", "sub/dir.zip", ".hidden", "a b.zip", ""):
            r = download.download_to_inbox(self._good_opener(),
                                        "https://cdn.example/a.zip", "KEY", inbox, fn)
            self.assertEqual(r["code"], "DL_BAD_FILENAME", fn)

    def test_missing_inbox_rejected(self):
        r = download.download_to_inbox(self._good_opener(),
                                    "https://cdn.example/a.zip", "KEY",
                                    os.path.join(_tmpdir("legacy_miss"), "no_such_subdir"),
                                    "a.zip")
        self.assertEqual(r["code"], "DL_INBOX_MISSING")

    def test_bytes_never_in_result(self):
        inbox = self._inbox("nobytes")
        r = download.download_to_inbox(self._good_opener(),
                                    "https://cdn.example/a.zip", "KEY", inbox, "a.zip")
        self.assertNotIn("data", r)
        blob = json.dumps(r, ensure_ascii=False)
        self.assertNotIn("ZIPDATA", blob)
        self.assertNotIn("__b64__", blob)


class _CloseTrackingResponse(_Response):
    """_Response that records close() and can be configured to fail on read()."""

    def __init__(self, *a, **kw):
        self.raise_on_read = kw.pop("raise_on_read", False)
        super().__init__(*a, **kw)

    def read(self, amt=-1):
        if self.raise_on_read:
            raise OSError("simulated read failure")
        return super().read(amt)


class TestAuditRegressionF1toF5(unittest.TestCase):
    """Regression tests for the mvp-design-researcher SCOPE1 findings F1–F5.

    F1 HIGH  : non-DownloadError exceptions (ValueError/TypeError/AttributeError)
               must never escape a public function; every result is a clean,
               JSON-safe dict.
    F2 MED   : NaN/Infinity must never enter a result (json.dumps(allow_nan=False)).
    F3 MED   : the real opener must NOT auto-follow 3xx; trailing-dot hosts
               must not bypass the private-host SSRF floor.
    F4 MED-LOW: resp.close() must run on EVERY exit path (CL pre-check, read
               failure, non-2xx).
    F5 LOW   : a trailing newline in a filename / domain must be rejected.
    """

    def _inbox(self, name):
        return _tmpdir("legacy_audit_" + name)

    # ---- F1 --------------------------------------------------------------



    def test_f1_nonstr_filename_and_inbox_cannot_escape(self):
        op = FakeOpener({"cdn.example": _Response(200, {}, [b"x"])})
        r1 = download.download_to_inbox(op, "https://cdn.example/a.zip", "KEY",
                                     self._inbox("fn"), 123)
        _json_safe(r1)
        self.assertEqual(r1["code"], "DL_BAD_FILENAME")
        r2 = download.download_to_inbox(op, "https://cdn.example/a.zip", "KEY",
                                     123, "a.zip")
        _json_safe(r2)
        self.assertFalse(r2["ok"])

    def test_f1_malformed_headers_cannot_escape(self):
        class BadHeaders:
            def items(self):
                raise RuntimeError("bad headers object")
        resp = _Response(200, {}, [b"x"])
        resp.headers = BadHeaders()
        op = FakeOpener({"cdn.example": resp})
        r = download.download_to_inbox(op, "https://cdn.example/a.zip", "KEY",
                                    self._inbox("hdr"), "a.zip")
        _json_safe(r)
        self.assertFalse(r["ok"])

    # ---- F2 --------------------------------------------------------------


    def test_f2_json_sanitize_kills_nonfinite_floats(self):
        out = download._json_sanitize({"nan": float("nan"), "inf": float("inf"),
                                    "ok": 1.5, "raw": b"bytes", "nested": [float("-inf")]})
        _json_safe(out)
        self.assertIsNone(out["nan"])
        self.assertIsNone(out["inf"])
        self.assertEqual(out["ok"], 1.5)
        self.assertIsNone(out["raw"])
        self.assertIsNone(out["nested"][0])

    def test_f2_scrub_key_enforces_json_safety_for_fail_context(self):
        # A non-finite float passed through _fail() context must be neutralised
        # at the public boundary, not leak into a dumps(allow_nan=False) result.
        r = download._scrub_key({"ok": False, "ratio": float("nan")}, "KEY")
        _json_safe(r)
        self.assertIsNone(r["ratio"])

    # ---- F3 --------------------------------------------------------------
    def test_f3_trailing_dot_host_still_private(self):
        inbox = self._inbox("dot")
        r = download.download_to_inbox(FakeOpener({}),
                                    "https://localhost./latest/meta-data",
                                    "KEY", inbox, "a.zip")
        self.assertEqual(r["code"], "DL_LOCAL_HOST")


    def test_f3_default_opener_disables_redirects(self):
        import ast
        import deckymod.download as _nx
        with open(_nx.__file__, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        classes = [n for n in ast.walk(tree)
                   if isinstance(n, ast.ClassDef) and n.name == "_NoRedirect"]
        self.assertEqual(len(classes), 1)
        methods = {m.name: m for m in classes[0].body if isinstance(m, ast.FunctionDef)}
        rr = methods["redirect_request"]
        returns_none = any(isinstance(n, ast.Return)
                           and isinstance(n.value, ast.Constant)
                           and n.value.value is None
                           for n in ast.walk(rr))
        self.assertTrue(returns_none, "redirect_request must return None (no follow)")
        dop = next(n for n in tree.body
                   if isinstance(n, ast.FunctionDef) and n.name == "default_opener")
        called = [n.func.attr for n in ast.walk(dop)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
        self.assertIn("build_opener", called)
        self.assertNotIn("urlopen", called)

    # ---- F4 --------------------------------------------------------------

    def test_f4_content_length_precheck_still_closes(self):
        resp = _CloseTrackingResponse(200, {"Content-Length": "999999999"}, [b"x"])
        op = FakeOpener({"cdn.example": resp})
        r = download.download_to_inbox(op, "https://cdn.example/a.zip", "KEY",
                                    self._inbox("clclose"), "a.zip", max_bytes=1024)
        self.assertEqual(r["code"], "DL_TOO_LARGE")
        self.assertTrue(resp.closed, "resp.close() must run on the CL pre-check path")

    def test_f4_stream_read_failure_still_closes(self):
        resp = _CloseTrackingResponse(200, {}, [b"x"], raise_on_read=True)
        op = FakeOpener({"cdn.example": resp})
        r = download.download_to_inbox(op, "https://cdn.example/a.zip", "KEY",
                                    self._inbox("readclose"), "a.zip")
        _json_safe(r)
        self.assertEqual(r["code"], "DL_NETWORK")
        self.assertTrue(resp.closed, "resp.close() must run when stream read() fails")

    def test_f4_non2xx_still_closes(self):
        resp = _CloseTrackingResponse(503, {}, [b"down"])
        op = FakeOpener({"cdn.example": resp})
        r = download.download_to_inbox(op, "https://cdn.example/a.zip", "KEY",
                                    self._inbox("statusclose"), "a.zip")
        self.assertEqual(r["code"], "DL_HTTP")
        self.assertTrue(resp.closed, "resp.close() must run on the non-2xx branch")

    # ---- F5 --------------------------------------------------------------
    def test_f5_trailing_newline_filename_rejected(self):
        inbox = self._inbox("nl")
        op = FakeOpener({"cdn.example": _Response(200, {}, [b"x"])})
        r = download.download_to_inbox(op, "https://cdn.example/a.zip", "KEY",
                                    inbox, "a.zip\n")
        self.assertEqual(r["code"], "DL_BAD_FILENAME")



class TestDefaultOpenerContract(unittest.TestCase):
    def test_default_opener_is_lazy_urllib_only(self):
        # The real opener exists for future wiring but imports urllib lazily,
        # so importing download.py pulls NO third-party dependency.
        import ast
        import deckymod.download as _nx
        with open(_nx.__file__, encoding="utf-8") as fh:
            src = fh.read()
        tree = ast.parse(src)
        top_imports = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                top_imports |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                top_imports.add(node.module)
        # urllib/json must NOT be top-level (imported inside functions)
        self.assertNotIn("urllib.request", top_imports)
        self.assertNotIn("urllib", top_imports)
        self.assertTrue(any(n.name == "default_opener" for n in tree.body
                            if isinstance(n, ast.FunctionDef)))


if __name__ == "__main__":
    unittest.main()
