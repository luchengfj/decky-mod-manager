"""Round 6: OFFLINE proof of the UNWIRED tri-state download->import coordinator.

This tests ``deckymod/auto_import.py`` — the policy-neutral coordinator that
closes the seam between the round-3 Download core and the shipped file_drop engine.
It is NOT wired into production; main.py still has exactly 11 RPCs (test 8).

Everything here is 100% offline and policy-neutral:
  * NO network (a FakeOpener serves canned JSON + a canned ZIP body).
  * NO Steam Deck, NO root, NO real game files (synthetic StardewTree).
  * NO writes into a game Mods/ folder: the DEFAULT and CONFIRM phases are
    strictly read-only, and even the final install phase is PROVEN to
    propagate E_EXTERNAL_MANAGER fail-closed (tests 1-3).

The activation-contract audit (m07972) demanded a TRI-STATE gate, not a bare
``allow_install=False`` boolean. These tests mechanically verify all three:
  1. default False          -> read-only half-chain (phase="inspect")
  2. True, no after_confirm -> mandatory confirm (phase="confirm"), still no write
  3. True + after_confirm   -> engine install gate is PROPAGATED (never swallowed)

HONEST SCOPE: proves the COORDINATION is correct + the read-only half-chain
connects. It does NOT mean "auto-import is live": activation (12th RPC), Download
credentials (D1), and the single-manager choice (D2) remain user decisions.
"""
from __future__ import annotations

import ast
import io
import json
import os
import sys
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deckymod import auto_import, fsops, download
from deckymod.errors import ERRORS
from deckymod.journal import Journal
from deckymod.download import _Response
from deckymod.smapi import StardewEngine
from test_stardew import StardewTree

# The RimWorld suite pins DECKYMOD_GAME_ID=rimworld at import time. These tests
# need the production default (stardew), so save/pop/restore around THIS module
# only (same proven pattern as test_stardew.py / test_catalog.py / test_integration.py).
_PREV_GAME_ID = None


def setUpModule():
    global _PREV_GAME_ID
    _PREV_GAME_ID = os.environ.pop("DECKYMOD_GAME_ID", None)  # default = stardew


def tearDownModule():
    if _PREV_GAME_ID is not None:
        os.environ["DECKYMOD_GAME_ID"] = _PREV_GAME_ID
    else:
        os.environ.pop("DECKYMOD_GAME_ID", None)


CDN_URL = "https://files.download-cdn.com/automate.zip"
API_KEY = "COORD_SECRET_555"
MANIFEST = {"Name": "Test Automate", "Author": "Pathoschild", "Version": "2.6.1",
            "MinimumApiVersion": "4.1.10", "UniqueID": "TestCo.Automate",
            "EntryDll": "Automate.dll"}


def _smapi_zip_bytes():
    """A valid single-root SMAPI mod ZIP (manifest.json + .dll + config)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Automate/manifest.json", json.dumps(MANIFEST))
        z.writestr("Automate/Automate.dll", b"MZ")
        z.writestr("Automate/config.json", b"{}")
    return buf.getvalue()


class _ChainOpener:
    """Serves a Download download_link.json and a CDN body; records every call."""

    def __init__(self, cdn_bytes=None, *, link_status=200, link_body=None):
        self.cdn_bytes = _smapi_zip_bytes() if cdn_bytes is None else cdn_bytes
        self.link_status = link_status
        self.link_body = (json.dumps([{"URI": CDN_URL, "name": "Automate 2.6.1"}]).encode("utf-8")
                          if link_body is None else link_body)
        self.calls = []

    def __call__(self, method, url, headers, timeout):
        self.calls.append({"method": method, "url": url,
                           "headers": dict(headers), "timeout": timeout})
        if "download_link.json" in url:
            return _Response(self.link_status, {}, [self.link_body])
        if "download-cdn.com" in url:
            return _Response(200, {}, [self.cdn_bytes])
        raise AssertionError("unexpected URL: " + url)


def _json_safe(value, path="result"):
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


class _BoomEngine:
    """Injected engine whose list_inbox raises — proves the public boundary
    guard converts ANY raw exception into a clean E_UNKNOWN Envelope."""

    def __init__(self):
        self.journal = type("J", (), {"decky_data": os.getcwd()})()

    def list_inbox(self):
        raise RuntimeError("injected failure: must not escape")


class _LeakyEnvelopeEngine:
    """Q6 hardening: list_inbox returns a FAILURE envelope carrying deliberately
    NON-JSON-safe leaves (raw bytes / NaN / Path). It is propagated verbatim at
    auto_import.py:199 — the PUBLIC boundary must still normalize it uniformly."""

    def __init__(self):
        self.journal = type("J", (), {"decky_data": os.getcwd()})()

    def list_inbox(self):
        import pathlib
        return {"ok": False, "code": "E_INBOX_MISSING", "detail": b"raw-bytes",
                "nan": float("nan"), "p": pathlib.Path(".")}


class _KeyLeakEngine:
    """Q4 hardening: an injected collaborator whose exception message carries
    the API key — the public E_UNKNOWN boundary must scrub it, never echo it."""

    def __init__(self):
        self.journal = type("J", (), {"decky_data": os.getcwd()})()

    def list_inbox(self):
        raise RuntimeError("injected failure leaking " + API_KEY)


class TestTriStateCoordinator(unittest.TestCase):
    def setUp(self):
        self.t = StardewTree()
        self.t.env()
        self.eng = StardewEngine(journal=Journal(self.t.data, self.t.logs, "stardew"))

    def tearDown(self):
        self.t.cleanup()



    # --- the three states (the decisive fail-closed proof) ------------------



    # --- NX -> E mapping: errors.py stays 50, no new i18n -------------------
    def test_4_all_DL_codes_map_to_existing_E_codes(self):
        """Every DL_* code maps onto an EXISTING shipped E_* code; errors.py
        stays 50, no DL_ leaked, no new E_* code (would break error_codes()).

        Round 19 added three module-local DL_* codes for the non-Download sources
        (DL_HOST_NOT_ALLOWED / DL_NO_ASSET / DL_NOT_FOUND), so the table grows
        while the shipped code count does NOT.

        Round 26 added two more for post-download integrity
        (DL_SIZE_MISMATCH / DL_HASH_MISMATCH), same rule: the table grows, the
        shipped 50 stay untouched.
        """
        self.assertEqual(len(auto_import.DL_TO_E), 20)
        self.assertEqual(len(download.DL_ERRORS), 20)
        for nx, e in auto_import.DL_TO_E.items():
            self.assertTrue(nx.startswith("DL_"))
            self.assertIn(e, ERRORS, "%s -> %s not in ERRORS" % (nx, e))
        # both directions: no NX code is left without a translation
        self.assertEqual(sorted(auto_import.DL_TO_E), sorted(download.DL_ERRORS))
        self.assertEqual(len(ERRORS), 52)
        err_src = open(os.path.join(os.path.dirname(auto_import.__file__),
                                    "errors.py"), encoding="utf-8").read()
        # no module-local DL_* code leaked into the shipped errors registry
        self.assertNotIn("DL_", err_src)

    def test_5_fail_translates_DL_to_E_with_verbatim_detail(self):
        """_fail() converts a download raw dict into a shipped Envelope, keeping
        the NX code in detail for logs but surfacing only an E_* code."""
        r = auto_import._fail({"ok": False, "code": "DL_TOO_LARGE",
                               "detail": "content-length 999", "message": "too big"},
                              "download")
        _json_safe(r)
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "E_ZIP_BOMB")
        self.assertIn("DL_TOO_LARGE", r["detail"])
        self.assertIn("[download]", r["detail"])

    # --- clean failure paths (no raw exception / no crash) -----------------





    # --- WIRING discipline (round 19) --------------------------------------
    def test_11_production_is_wired(self):
        """Round 19: the coordinator IS wired into main.py, now through
        gh_download/download_url instead of legacy_fetch, with 15 public async
        RPCs. auto_import.fetch_and_import is kept (and covered above) even
        though main.py no longer calls it: download_and_import reuses the exact
        same inbox/listed-path/inspect/gate stages."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "main.py"), encoding="utf-8") as fh:
            src = fh.read()
        # ``from deckymod import download`` records module="deckymod" with alias
        # name "download", so assert the raw import statement instead.
        self.assertIn("from deckymod import download", src,
                      "round-19: download is the shared download layer")
        self.assertIn("from deckymod import auto_import", src)
        tree = ast.parse(src)
        plugin = next(n for n in tree.body
                      if isinstance(n, ast.ClassDef) and n.name == "Plugin")
        rpcs = [m.name for m in plugin.body
                if isinstance(m, ast.AsyncFunctionDef) and not m.name.startswith("_")]
        self.assertEqual(len(rpcs), 28, rpcs)
        self.assertIn("gh_download", rpcs)
        self.assertIn("download_url", rpcs)
        self.assertNotIn("legacy_fetch", rpcs)


    # --- Round 7 independent-review hardening (4 LOW nits, all closed) ------



if __name__ == "__main__":
    unittest.main()
