"""Download -> import COORDINATOR (stdlib only, injected collaborators).

Bridges the shared download core (``deckymod/download.py``) to the shipped
file-drop engine (``smapi.py``). ``download_and_import`` downloads a known URL
into the caller-supplied inbox, inspects it READ-ONLY, then applies a TRI-STATE,
fail-closed gate:

  1. ``allow_install=False`` (DEFAULT) -> ``phase="inspect"``; ZERO Mods/ writes.
  2. ``allow_install=True, after_confirm=False`` -> ``phase="confirm"``; still ZERO writes.
  3. both True -> the engine's own ``install()``; its gate verdict is PROPAGATED
     verbatim (``E_EXTERNAL_MANAGER`` is never swallowed).

SECURITY: no root, no read-only toggle, no loader/launch-option/Proton writes, no
universal one-click claim. The ONLY filesystem write is to the inbox via
``download.download_to_inbox``; the engine's ``install()`` is the sole Mods/ write
path and stays engine-gated. Every result is a JSON-safe dict.

All collaborators are injected, so this module is 100% offline-testable.
"""
from __future__ import annotations

import os

from . import download, fsops
from .envelope import err, ok
from .json_safe import to_json_safe

# Map the 15 unwired DL_* core codes onto the EXISTING, shipped 50-code E_*
# registry. We deliberately add NO new E_* codes, NO new CAT_* and NO new
# ERR_E_* i18n keys: distinct E_* would push errors.py past 50 and break
# the error_codes() contract. The NX code is preserved in `detail` for logs.
DL_TO_E = {
    "DL_BAD_URL": "E_PATH_INVALID",
    "DL_LOCAL_HOST": "E_PATH_ESCAPE",
    "DL_NETWORK": "E_BRIDGE",
    "DL_HTTP": "E_BRIDGE",
    "DL_AUTH_REQUIRED": "E_CAPABILITY_DISABLED",
    "DL_FORBIDDEN": "E_CAPABILITY_DISABLED",
    "DL_RATE_LIMIT": "E_BRIDGE",
    "DL_BAD_JSON": "E_BAD_ARCHIVE",
    "DL_NO_LINK": "E_INBOX_UNREADABLE",
    "DL_TOO_LARGE": "E_ZIP_BOMB",
    "DL_TRUNCATED": "E_INBOX_UNREADABLE",
    "DL_INBOX_MISSING": "E_INBOX_MISSING",
    "DL_BAD_FILENAME": "E_PATH_INVALID",
    "DL_PATH_ESCAPE": "E_PATH_ESCAPE",
    "DL_WRITE_FAILED": "E_ACCESS",
    # Round 19 (non-Download sources): still no new E_* codes.
    "DL_HOST_NOT_ALLOWED": "E_PATH_ESCAPE",
    "DL_NO_ASSET": "E_INBOX_UNREADABLE",
    "DL_NOT_FOUND": "E_INBOX_UNREADABLE",
    # Round 26: integrity failures are corrupt input, not a transport problem.
    "DL_SIZE_MISMATCH": "E_BAD_ARCHIVE",
    "DL_HASH_MISMATCH": "E_BAD_ARCHIVE",
}
_FALLBACK_E = "E_UNKNOWN"


def _fail(result: dict, stage: str) -> dict:
    """Convert a failed download result dict into a shipped Envelope.

    The DL_* code is translated to an existing E_* code (errors.py stays 50)
    but kept verbatim in the human-readable detail for troubleshooting. The
    E_EXTERNAL_MANAGER case is NOT handled here: it can only come from the
    engine's install() gate and is returned UNMODIFIED (see _install).
    """
    dl_code = str(result.get("code") or "DL_NETWORK")
    e_code = DL_TO_E.get(dl_code, _FALLBACK_E)
    detail = "[%s] %s: %s" % (stage, dl_code, result.get("detail") or result.get("message") or "failed")
    return err(e_code, detail=detail)


def _inbox_dir(engine) -> str:
    """Resolve the EXACT inbox path the engine's list_inbox()/inspect() use.

    This is the Q2 glue from the round-5 integration audit: download takes a
    caller-supplied ``inbox_dir`` and creates nothing, while the engine derives
    it from DECKYMOD_INBOX (or journal.decky_data/inbox). Resolve the same path
    and ensure it exists BEFORE downloading. No shape change to either half.
    """
    d = os.environ.get("DECKYMOD_INBOX") or os.path.join(engine.journal.decky_data, "inbox")
    return os.path.abspath(d)


def _listed_path(engine, filename: str):
    """Return the LISTED path for filename (Q5 robust glue).

    Do NOT feed download's realpath `final` straight into inspect(): if the inbox
    is reached through a symlink, comparing abspath(final) against
    abspath(inbox_env) yields E_PATH_ESCAPE. Re-derive from list_inbox().
    """
    listing = engine.list_inbox()
    if not listing.get("ok"):
        return None, listing
    for it in (listing.get("data") or {}).get("items") or []:
        if it.get("name") == filename:
            return it.get("path"), listing
    return None, listing


def _install(engine, listed_path: str, *, after_confirm: bool) -> dict:
    """FINAL gate. Deliberately thin: call the engine's own install().

    We NEVER inspect/remove .mm_deployed or Mods_Core, NEVER set
    force_read_only/detection_only, and NEVER catch-and-soften ModError. The
    engine's ``_check_write_allowed`` (smapi.py:84-109) returns
    E_EXTERNAL_MANAGER / E_LOADER_MISSING / E_LAUNCH_OPTIONS_MISSING as an
    err() Envelope, which we return byte-for-byte (PROPAGATED, not translated).
    """
    return engine.install(listed_path, after_confirm=after_confirm)


def download_and_import(
    opener,
    engine,
    *,
    url: str,
    filename: str = "mod.zip",
    allow_install: bool = False,
    after_confirm: bool = False,
    max_bytes: int = download.DEFAULT_MAX_BYTES,
    timeout: float = download.DEFAULT_TIMEOUT,
    allowed_hosts=None,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
) -> dict:
    """Round 19: download a KNOWN url into the inbox, inspect it, tri-state gate.

    This is the URL-based counterpart of the download coordinator. It skips the
    "resolve a download link" stage because the caller already holds the URL:
    either a signed GitHub release-asset URL (see ``github_source``) or a
    user-supplied https URL. Everything after the URL is IDENTICAL -- the same
    inbox glue, the same listed-path re-derivation, the same dry-run inspect and
    the same three-phase gate -- so both sources share one write path and one
    set of guarantees.

    ``allowed_hosts`` pins the download to an explicit host allow-list (the
    GitHub asset hosts); omit it for a plain user-supplied URL, which then falls
    back to the default private-literal guard.

    ``expected_size`` / ``expected_sha256`` (round 26) are what criterion 4 means
    by "verify size/hash before install": the source declares them, the download
    is checked against them BEFORE anything is written, and the verified list is
    reported back so the UI can say what was actually proven.

    Phases:
      * ``allow_install=False`` (DEFAULT): read-only half-chain, ``phase="inspect"``.
      * ``allow_install=True, after_confirm=False``: ``phase="confirm"``, still no write.
      * both True: ``engine.install()`` and its gate verdict PROPAGATED unchanged
        (``E_EXTERNAL_MANAGER`` is never swallowed here).
    """
    try:
        if not isinstance(url, str) or not url:
            return err("E_PATH_INVALID", detail="[download] url is required")
        # --- stage 1: inbox glue (same resolver as the Download coordinator) -----
        inbox = _inbox_dir(engine)
        try:
            fsops.ensure_dir(inbox)
        except Exception as e:  # noqa: BLE001
            return err("E_INBOX_MISSING", detail="[inbox] %s: %s" % (type(e).__name__, e))

        # --- stage 2: download (the ONLY write here, and it is inbox-only) ----
        d = download.download_to_inbox(opener, url, "", inbox, filename,
                                    max_bytes=max_bytes, timeout=timeout,
                                    allowed_hosts=allowed_hosts,
                                    expected_size=expected_size,
                                    expected_sha256=expected_sha256)
        if not d.get("ok"):
            return _fail(d, "download")

        # --- stage 3: re-derive the LISTED path (never the realpath) ----------
        listed, listing = _listed_path(engine, filename)
        if not listing.get("ok"):
            return listing
        if listed is None:
            return err("E_INBOX_EMPTY",
                       detail="[list] downloaded file not visible in inbox: %s" % filename)

        # --- stage 4: dry-run inspect (READ-ONLY) ----------------------------
        inspected = engine.inspect(listed)
        if not inspected.get("ok"):
            return inspected
        mod = (inspected.get("data") or {}).get("mod") or {}
        downloaded = {"name": filename, "size": d.get("size"),
                      "sha256": d.get("sha256"),
                      "verified": list(d.get("verified") or [])}

        # --- TRI-STATE GATE --------------------------------------------------
        if not allow_install:
            return ok({
                "phase": "inspect",
                "install_allowed": False,
                "source": "url",
                "downloaded": downloaded,
                "mod": mod,
                "inspect": inspected.get("data"),
                "note": "read-only half-chain; install needs allow_install + after_confirm",
            })
        if not after_confirm:
            return ok({
                "phase": "confirm",
                "install_allowed": True,
                "source": "url",
                "confirm_text": "Import %s into the game's Mods folder? (final write is engine-gated)" % (mod.get("name") or filename),
                "plan": {"from": listed, "uniqueId": mod.get("uniqueId"),
                         "name": mod.get("name"), "version": mod.get("version")},
                "downloaded": downloaded,
                "note": "call again with after_confirm=True; E_EXTERNAL_MANAGER is propagated, never bypassed",
            })

        # --- stage 5 (both flags): engine install, gate PROPAGATED -----------
        result = _install(engine, listed, after_confirm=True)
        return to_json_safe(result) if isinstance(result, dict) else err(
            "E_UNKNOWN", detail="[install] engine returned a non-dict result")
    except Exception as e:  # noqa: BLE001 - public boundary never raises
        return err("E_UNKNOWN", detail="[download] %s: %s" % (type(e).__name__, e))
