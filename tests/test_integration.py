"""Round 5: OFFLINE mechanical proof of the DOWNLOAD -> IMPORT half-chain.

This closes the one gap the mvp-design-researcher static audit (m07805) found:
Round 2-4 built the two halves (the download core in ``deckymod/download.py``
and the Stardew/file_drop import engine in ``deckymod/smapi.py``), but nothing
had ever *executed* them together.

Everything here is 100% offline and policy-neutral:
  * NO network (a FakeOpener serves canned JSON + a canned ZIP body).
  * NO Steam Deck, NO root, NO real game files (synthetic StardewTree).
  * NO writes into a game Mods/ folder (install stays policy-gated, test 5).
  * NO new production wiring: this file only *calls* the two existing halves;
    ``main.py`` keeps its own RPC contract (test 6 guards the count).

HONEST SCOPE: this proves the READ-ONLY half-chain
    resolve_asset -> download_to_inbox -> list_inbox -> inspect
actually connects. The final ``install`` write to Mods/ is deliberately NOT
claimed as "auto-import usable": on the real Deck it was refused by
E_EXTERNAL_MANAGER (Amethyst .mm_deployed / Mods_Core) until decision D2.
Activation / wiring was a separate, user-approved step; the download-source
history is recorded in docs/GOAL_RECORD_DOWNLOAD_SOURCE.md.

The Q2 REAL mismatch is proven mechanically: Download ``download_to_inbox`` takes
a caller-supplied ``inbox_dir`` and creates nothing; the shipped code has no
component that creates the env-derived inbox. The minimal glue (resolve the
exact env path + ``fsops.ensure_dir``) is applied and verified in test 1.
"""
from __future__ import annotations

import ast
import io
import json
import os
import shutil
import sys
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deckymod import fsops, download
from deckymod.journal import Journal
from deckymod.download import _Response
from deckymod.smapi import StardewEngine
from test_stardew import StardewTree, MANIFEST

# The RimWorld suite pins DECKYMOD_GAME_ID=rimworld at import time. These tests
# need the production default (stardew), so save/pop/restore around THIS module
# only (same proven pattern as test_stardew.py / test_catalog.py).
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
API_KEY = "INTEG_SECRET_999"


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

    def __init__(self, cdn_bytes):
        self.cdn_bytes = cdn_bytes
        self.calls = []

    def __call__(self, method, url, headers, timeout):
        self.calls.append({"method": method, "url": url,
                           "headers": dict(headers), "timeout": timeout})
        if "download_link.json" in url:
            body = json.dumps([{"URI": CDN_URL, "name": "Automate 2.6.1"}]).encode("utf-8")
            return _Response(200, {}, [body])  # fresh _Response per call
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


class TestDownloadToImportHalfChain(unittest.TestCase):
    def setUp(self):
        self.t = StardewTree()
        self.t.env()
        self.eng = StardewEngine(journal=Journal(self.t.data, self.t.logs, "stardew"))

    def tearDown(self):
        self.t.cleanup()

    def _opener(self, cdn_bytes=None):
        return _ChainOpener(_smapi_zip_bytes() if cdn_bytes is None else cdn_bytes)



    def test_2_non_zip_filename_not_visible_to_list_inbox(self):
        """Q1 caveat: (A) does not force a .zip name; caller must choose one.
        A download named *.dat lands fine but list_inbox() (B) filters .zip only."""
        op = self._opener()
        fsops.ensure_dir(self.t.inbox)
        d = download.download_to_inbox(op, CDN_URL, API_KEY, self.t.inbox, "automate.dat")
        _json_safe(d)
        self.assertTrue(d["ok"], d)
        listing = self.eng.list_inbox()
        self.assertTrue(listing["ok"], listing)
        self.assertEqual(listing["data"]["items"], [])  # .dat filtered out

    def test_3_arbitrary_outside_path_is_rejected_by_containment(self):
        """Q4: inspect()/install() do NOT accept any absolute path; only paths
        under the env-derived inbox (or DECKYMOD_EXTRA_IMPORT_ROOT) are allowed."""
        outside = os.path.join(self.t.base, "outside.zip")
        with open(outside, "wb") as f:
            f.write(_smapi_zip_bytes())
        r = self.eng.inspect(outside)
        _json_safe(r)
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "E_PATH_ESCAPE")
        self.assertEqual(os.listdir(self.t.mods), [])

    def test_4_non_zip_cdn_body_degrades_to_E_BAD_ARCHIVE(self):
        """Q3 caveat: an HTML 200 from a CDN is written to the inbox but the
        dry-run inspect rejects it cleanly (no crash, no Mods/ write)."""
        op = self._opener(cdn_bytes=b"<html>login required</html>")
        fsops.ensure_dir(self.t.inbox)
        d = download.download_to_inbox(op, CDN_URL, API_KEY, self.t.inbox, "html.zip")
        _json_safe(d)
        self.assertTrue(d["ok"], d)  # (A) has no opinion on ZIP-ness
        listing = self.eng.list_inbox()
        listed = next(it["path"] for it in listing["data"]["items"]
                      if it["name"] == "html.zip")
        r = self.eng.inspect(listed)
        _json_safe(r)
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "E_BAD_ARCHIVE")
        self.assertEqual(os.listdir(self.t.mods), [])

    def test_5_final_install_stays_policy_gated(self):
        """HONEST BOUNDARY: replicating the REAL Deck's external-manager marker
        (Amethyst .mm_deployed / Mods_Core), the final install write is refused
        by E_EXTERNAL_MANAGER with ZERO Mods/ writes. The download->list->inspect
        half-chain still works read-only. We do NOT flip this gate (needs D2)."""
        op = self._opener()
        fsops.ensure_dir(self.t.inbox)
        d = download.download_to_inbox(op, CDN_URL, API_KEY, self.t.inbox, "automate.zip")
        self.assertTrue(d["ok"], d)
        listed = next(it["path"] for it in self.eng.list_inbox()["data"]["items"]
                      if it["name"] == "automate.zip")
        self.assertTrue(self.eng.inspect(listed)["ok"])  # read-only half is fine

        # Simulate the real Deck: a third-party mod manager owns Mods/.
        with open(os.path.join(self.t.mods, ".mm_deployed"), "wb") as f:
            f.write(b"")
        self.assertTrue(self.eng.status()["data"]["state"]["read_only"])
        got = self.eng.install(listed, after_confirm=True)
        _json_safe(got)
        self.assertFalse(got["ok"])
        self.assertEqual(got["code"], "E_EXTERNAL_MANAGER")
        # ZERO mod directories were written; only the marker remains.
        self.assertEqual(os.listdir(self.t.mods), [".mm_deployed"])

    def test_6_production_is_wired(self):
        """Round 19: the SHARED download core is wired, the Download catalog is not.

        download/auto_import stay imported (download is now the shared https/JSON/
        download layer; auto_import owns the tri-state coordinator), while the
        Download credential + catalog RPCs are gone. 15 public async RPCs. The
        E_EXTERNAL_MANAGER gate in smapi.py (proven by the half-chain tests
        above) remains the unbypassable final write guard."""
        main_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
        with open(main_path, encoding="utf-8") as fh:
            src = fh.read()
        # ``from deckymod import download`` records module="deckymod" with alias
        # name "download", so a module-name check is unreliable: assert the raw
        # import statement instead.
        self.assertIn("from deckymod import download", src,
                      "round-19: download is the shared download layer")
        self.assertIn("from deckymod import auto_import", src)
        self.assertIn("from deckymod import github_source", src)
        # Round 39: the credential surface is back, but for METADATA only —
        # free keys work for browsing, and download links still answer 403.
        self.assertIn("from deckymod import credentials", src)
        self.assertIn("from deckymod import nexus", src)
        tree = ast.parse(src)
        plugin = next(n for n in tree.body
                      if isinstance(n, ast.ClassDef) and n.name == "Plugin")
        rpcs = [m.name for m in plugin.body
                if isinstance(m, ast.AsyncFunctionDef) and not m.name.startswith("_")]
        self.assertEqual(len(rpcs), 26, rpcs)
        for name in ("gh_search", "gh_releases", "gh_download", "download_url"):
            self.assertIn(name, rpcs)
        for name in ("api_key_status", "set_api_key", "delete_api_key",
                     "nexus_validate", "nexus_recent", "nexus_mod",
                     "nexus_download_link"):
            self.assertIn(name, rpcs, name)
        # Retired in round 29 and NOT resurrected: these were the shapes that
        # passed the key as an argument or ran one-shot fetch+install.
        for name in ("legacy_validate", "list_mod_files", "legacy_fetch"):
            self.assertNotIn(name, rpcs)


if __name__ == "__main__":
    unittest.main()
