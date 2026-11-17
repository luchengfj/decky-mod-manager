"""Round 26: the download is verified against what the SOURCE declared.

Criterion 4 says "verify file size/hash before install". Before this round the
code measured size/sha256 but never COMPARED them to anything — measuring is not
verifying, so the honest description was "we report a hash", not "we check it".

These tests pin the new behaviour:

  * a body whose length differs from ``expected_size`` is REFUSED and nothing is
    written to the inbox (the check runs before the write, not after);
  * a body whose sha256 differs from ``expected_sha256`` is REFUSED the same way;
  * a malformed ``expected_sha256`` is refused rather than silently skipped —
    otherwise a source could pass junk and still look "verified";
  * when the source declares nothing, the result says ``verified: []`` instead
    of implying a check that never happened;
  * ``asset_metadata`` asks the API for the one asset and reports size, and
    returns ``sha256`` only when GitHub actually published a digest.

Everything is offline: the network is a fake opener with the same contract as
production (``opener(method, url, headers, timeout)`` -> ``.status/.headers/
.read(n)/.close()``).
"""
from __future__ import annotations

import hashlib
import json
import os
import unittest
import uuid

from deckymod import github_source, download

# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #


class _Resp:
    """Stateful response: read(amt) must advance and finally return b""."""

    def __init__(self, status=200, body=b"", headers=None):
        self.status = status
        self.headers = dict(headers or {})
        self._body = body
        self._pos = 0

    def read(self, amt=None):
        if self._pos >= len(self._body):
            return b""
        end = len(self._body) if amt is None else self._pos + amt
        out = self._body[self._pos:end]
        self._pos += len(out)
        return out

    def close(self):
        pass


class _Opener:
    """Prefix-routed opener; records every call so we can assert on requests."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, method, url, headers, timeout):
        self.calls.append((method, url, dict(headers or {})))
        for prefix, resp in self.routes:
            if url.startswith(prefix):
                return resp() if callable(resp) else resp
        raise AssertionError("unexpected URL: %s" % url)


def _inbox():
    while True:
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", ".decky-test-tmp", "r26_" + uuid.uuid4().hex[:8])
        d = os.path.abspath(d)
        if not os.path.exists(d):
            os.makedirs(d)
            return d


BODY = b"PK\x03\x04" + os.urandom(2048)
GOOD_SIZE = len(BODY)
GOOD_HASH = hashlib.sha256(BODY).hexdigest()


# --------------------------------------------------------------------------- #
# size verification
# --------------------------------------------------------------------------- #


class TestSizeVerification(unittest.TestCase):
    def test_matching_size_is_accepted_and_reported(self):
        inbox = _inbox()
        op = _Opener([("https://dl.example.com/", _Resp(200, BODY,
                                                      {"Content-Length": str(GOOD_SIZE)}))])
        res = download.download_to_inbox(op, "https://dl.example.com/m.zip", "", inbox,
                                      "m.zip", expected_size=GOOD_SIZE)
        assert res["ok"] is True
        assert res["verified"] == ["size"]
        assert res["size"] == GOOD_SIZE
        assert os.path.isfile(os.path.join(inbox, "m.zip"))

    def test_size_mismatch_is_refused_and_nothing_is_written(self):
        inbox = _inbox()
        op = _Opener([("https://dl.example.com/", _Resp(200, BODY,
                                                      {"Content-Length": str(GOOD_SIZE)}))])
        res = download.download_to_inbox(op, "https://dl.example.com/m.zip", "", inbox,
                                      "m.zip", expected_size=GOOD_SIZE + 1)
        assert res["ok"] is False
        assert res["code"] == "DL_SIZE_MISMATCH"
        assert not os.path.exists(os.path.join(inbox, "m.zip")), (
            "a file that failed verification must not reach the inbox")

    def test_non_integer_expected_size_is_refused_not_ignored(self):
        inbox = _inbox()
        op = _Opener([("https://dl.example.com/", _Resp(200, BODY))])
        res = download.download_to_inbox(op, "https://dl.example.com/m.zip", "", inbox,
                                      "m.zip", expected_size="2048")
        assert res["ok"] is False
        assert res["code"] == "DL_SIZE_MISMATCH"


# --------------------------------------------------------------------------- #
# hash verification
# --------------------------------------------------------------------------- #


class TestHashVerification(unittest.TestCase):
    def test_matching_hash_is_accepted_and_reported(self):
        inbox = _inbox()
        op = _Opener([("https://dl.example.com/", _Resp(200, BODY))])
        res = download.download_to_inbox(op, "https://dl.example.com/m.zip", "", inbox,
                                      "m.zip", expected_sha256=GOOD_HASH)
        assert res["ok"] is True
        assert res["verified"] == ["sha256"]
        assert res["sha256"] == GOOD_HASH

    def test_hash_mismatch_is_refused_and_nothing_is_written(self):
        inbox = _inbox()
        op = _Opener([("https://dl.example.com/", _Resp(200, BODY))])
        res = download.download_to_inbox(op, "https://dl.example.com/m.zip", "", inbox,
                                      "m.zip", expected_sha256="0" * 64)
        assert res["ok"] is False
        assert res["code"] == "DL_HASH_MISMATCH"
        assert not os.path.exists(os.path.join(inbox, "m.zip"))

    def test_uppercase_hash_is_normalised_before_comparison(self):
        inbox = _inbox()
        op = _Opener([("https://dl.example.com/", _Resp(200, BODY))])
        res = download.download_to_inbox(op, "https://dl.example.com/m.zip", "", inbox,
                                      "m.zip", expected_sha256=GOOD_HASH.upper())
        assert res["ok"] is True
        assert res["verified"] == ["sha256"]

    def test_malformed_expected_hash_is_refused_not_skipped(self):
        inbox = _inbox()
        op = _Opener([("https://dl.example.com/", _Resp(200, BODY))])
        for junk in ("abc", "", "z" * 64, GOOD_HASH + "0"):
            res = download.download_to_inbox(op, "https://dl.example.com/m.zip", "", inbox,
                                          "m.zip", expected_sha256=junk)
            assert res["ok"] is False, junk
            assert res["code"] == "DL_HASH_MISMATCH", junk

    def test_both_checks_report_both(self):
        inbox = _inbox()
        op = _Opener([("https://dl.example.com/", _Resp(200, BODY))])
        res = download.download_to_inbox(op, "https://dl.example.com/m.zip", "", inbox,
                                      "m.zip", expected_size=GOOD_SIZE,
                                      expected_sha256=GOOD_HASH)
        assert res["ok"] is True
        assert res["verified"] == ["size", "sha256"]


# --------------------------------------------------------------------------- #
# honesty: no source declaration means no verification claim
# --------------------------------------------------------------------------- #


class TestNoDeclarationMeansNoClaim(unittest.TestCase):
    def test_without_declaration_verified_is_empty(self):
        inbox = _inbox()
        op = _Opener([("https://dl.example.com/", _Resp(200, BODY))])
        res = download.download_to_inbox(op, "https://dl.example.com/m.zip", "", inbox,
                                      "m.zip")
        assert res["ok"] is True
        assert res["verified"] == [], "must not claim a check that did not run"
        # the measurement is still reported, it is just not a verification
        assert res["size"] == GOOD_SIZE
        assert res["sha256"] == GOOD_HASH


# --------------------------------------------------------------------------- #
# asset metadata (where the declared values come from)
# --------------------------------------------------------------------------- #


def _meta_route(payload):
    body = json.dumps(payload).encode("utf-8")
    return [("https://api.github.com/", _Resp(200, body, {"Content-Type": "application/json"}))]


class TestAssetMetadata(unittest.TestCase):
    def test_reports_declared_size_and_published_digest(self):
        op = _Opener(_meta_route({
            "id": 252770482, "name": "DestroyableBushes.1.5.2.zip",
            "size": 44252, "content_type": "application/x-zip-compressed",
            "digest": "sha256:" + GOOD_HASH,
        }))
        res = github_source.asset_metadata(op, "Esca-MMC", "DestroyableBushes", 252770482)
        assert res["ok"] is True
        assert res["size"] == 44252
        assert res["sha256"] == GOOD_HASH

    def test_null_digest_becomes_none_rather_than_a_fake_hash(self):
        # This is the real-device case: GitHub returns digest: null for release
        # assets, so a hash check CANNOT be claimed for them.
        op = _Opener(_meta_route({
            "id": 7, "name": "x.zip", "size": 1234,
            "content_type": "application/zip", "digest": None,
        }))
        res = github_source.asset_metadata(op, "o", "r", 7)
        assert res["ok"] is True
        assert res["size"] == 1234
        assert res["sha256"] is None

    def test_missing_size_is_none_not_zero(self):
        op = _Opener(_meta_route({"id": 7, "name": "x.zip", "digest": None}))
        res = github_source.asset_metadata(op, "o", "r", 7)
        assert res["ok"] is True
        assert res["size"] is None

    def test_bad_owner_is_refused_without_a_request(self):
        op = _Opener([])
        res = github_source.asset_metadata(op, "../../etc", "r", 7)
        assert res["ok"] is False
        assert res["code"] == "DL_BAD_URL"
        assert op.calls == []

    def test_404_is_reported_as_not_found(self):
        op = _Opener([("https://api.github.com/",
                       _Resp(404, b"{}", {"Content-Type": "application/json"}))])
        res = github_source.asset_metadata(op, "o", "r", 7)
        assert res["ok"] is False
        assert res["code"] == "DL_NOT_FOUND"

    def test_no_credentials_are_sent(self):
        op = _Opener(_meta_route({"id": 7, "name": "x.zip", "size": 1}))
        github_source.asset_metadata(op, "o", "r", 7)
        for _m, _u, headers in op.calls:
            low = {k.lower() for k in headers}
            assert "authorization" not in low
            assert "apikey" not in low
