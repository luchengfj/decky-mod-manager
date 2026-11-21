"""Nexus Mods API v1 — metadata only, and honest about it.

================  =========================================================
Measured fact     Consequence for this module
================  =========================================================
anonymous call    401 "Please provide an authentication method" — a key is
                  mandatory, there is no anonymous tier at all
with free key     metadata endpoints return 200 (mod info, file list,
                  latest_added / latest_updated / trending)
download_link     403 for a free account: "you don't have permission to get
                  download links from the API without visting nexusmods.com -
                  this is for premium users only" (sic — their typo)
search endpoint   does not exist: ``mods/search.json`` parses ``search`` as a
                  mod id and returns 422. Keyword search lives only in the
                  website's GraphQL layer, which is not part of this API.
website HTML      403 Cloudflare "Just a moment..." for every page, anonymous
                  or not. Scraping is not a fallback.
validate.json     200, and the JSON body ECHOES THE KEY BACK in a ``key``
                  field. It must never be forwarded verbatim.
================  =========================================================

So the honest product is: **browse and inspect, then hand the actual download
to the user's browser** (a normal HTTPS link they click), or accept a file they
already downloaded. This module never claims to download a mod it cannot.

Why the transport is written out instead of reusing the shared JSON helper:
that helper raises on any non-2xx status *without* keeping the body, and the
body is exactly what distinguishes the several meanings a 403 has here ("needs
premium" vs "Mod not available: 4729" vs "bad key"). The host policy
(``_check_url``) and the key scrubbing are still the shared ones — only the
status handling is local.
"""

from __future__ import annotations

import json
import urllib.parse

from . import download

API_HOST = "api.nexusmods.com"
API_ROOT = "https://api.nexusmods.com/v1"
ALLOWED_HOSTS = frozenset({API_HOST})
TIMEOUT = download.DEFAULT_TIMEOUT
MAX_BODY_BYTES = 4 * 1024 * 1024

#: The API only accepts these header spellings; ``API-Key``, ``x-api-key`` and
#: ``Bearer`` all return 401 (measured), and ``?key=`` in the query string
#: returns 401 as well — never put the secret in a URL.
H_KEY = "apikey"

_HINT_FREE_TIER = ("requires a free Nexus Mods account API key; create one at "
                   "nexusmods.com/users/myaccount?tab=api and paste it here")


def _headers(api_key: str) -> dict:
    return {H_KEY: api_key,
            "User-Agent": download.USER_AGENT,
            "Accept": "application/json"}


def _excerpt(raw: bytes) -> str:
    """A short, scrubbed slice of an error body — enough to classify it."""
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - never let diagnostics raise
        return ""
    text = text.strip()
    if len(text) > 400:
        text = text[:400] + "…"
    return " ".join(text.split())


def _raw(opener, path: str, api_key: str, *, timeout: float) -> dict:
    """One GET against the pinned host. Returns status + body text, never raises.

    Returns ``{"status": int, "text": str, "body": dict|None, "error": str|None}``.
    """
    url = API_ROOT + path
    try:
        download._check_url(url, allowed_hosts=ALLOWED_HOSTS)
    except download.DownloadError as e:
        return {"status": 0, "text": "", "body": None, "error": e.code,
                "error_detail": e.detail}
    try:
        resp = opener("GET", url, _headers(api_key), timeout)
    except Exception as e:  # noqa: BLE001 - converted to a result
        return {"status": 0, "text": "", "body": None, "error": "DL_NETWORK",
                "error_detail": "%s: %s" % (type(e).__name__, e)}

    status = int(getattr(resp, "status", 0) or 0)
    try:
        raw = resp.read(MAX_BODY_BYTES) or b""
    except Exception as e:  # noqa: BLE001
        try:
            resp.close()
        except Exception:  # noqa: BLE001
            pass
        return {"status": status, "text": "", "body": None, "error": "DL_NETWORK",
                "error_detail": "read failed: %s" % type(e).__name__}
    try:
        resp.close()
    except Exception:  # noqa: BLE001 - close is best effort
        pass

    text = _excerpt(raw)
    body = None
    if 200 <= status < 300 and raw:
        try:
            body = json.loads(raw.decode("utf-8", errors="replace"),
                              parse_constant=_reject_constant)
        except (ValueError, UnicodeError):
            return {"status": status, "text": text, "body": None,
                    "error": "DL_BAD_JSON", "error_detail": "not valid JSON"}
    return {"status": status, "text": text, "body": body, "error": None}


def _reject_constant(token):
    raise ValueError("non-finite constant " + token)


def _status_error(code: str, status: int, text: str, *, extra: dict | None = None) -> dict:
    """Build a failure dict from a non-2xx response, keeping the server's words."""
    out = download._fail(code, detail=text or ("HTTP %d" % status), status=status)
    if extra:
        out.update(extra)
    return out


def _is_premium_gate(text: str) -> bool:
    """A 403 here means "needs premium" only when the server says so."""
    return "premium" in text.lower()


def _mod_missing(text: str) -> bool:
    return "not available" in text.lower()


def _translate(res: dict, api_key: str) -> dict:
    """Turn a raw transport result into a scrubbed, JSON-safe envelope."""
    if res.get("error"):
        out = download._fail(res["error"], detail=res.get("error_detail") or "")
        return download._scrub_key(out, api_key)
    status = res["status"]
    if 200 <= status < 300:
        return download._scrub_key(
            download._ok(status=status, data=res.get("body")), api_key)
    if status == 401:
        return download._scrub_key(
            _status_error("DL_AUTH_REQUIRED", status, res.get("text") or "",
                          extra={"hint": _HINT_FREE_TIER}), api_key)
    if status == 403:
        return download._scrub_key(
            _status_error("DL_FORBIDDEN", status, res.get("text") or "",
                          extra={"premium_required": _is_premium_gate(res.get("text") or "")}),
            api_key)
    if status == 404:
        return download._scrub_key(
            _status_error("DL_NOT_FOUND", status, res.get("text") or ""), api_key)
    if status == 429:
        return download._scrub_key(
            _status_error("DL_RATE_LIMIT", status, res.get("text") or ""), api_key)
    return download._scrub_key(
        _status_error("DL_HTTP", status, res.get("text") or ""), api_key)


# --------------------------------------------------------------------------
# Account
# --------------------------------------------------------------------------

_VALIDATE_FIELDS = ("name", "is_premium", "is_supporter", "email_verified",
                    "profile_url")


def validate(opener, api_key: str, *, timeout: float = TIMEOUT) -> dict:
    """Check the key against the server. Returns metadata only.

    The server echoes the key in its body, so the payload is scrubbed here AND
    only whitelisted fields are copied out. Two defences, because one is a
    pattern and one is structural.
    """
    res = _raw(opener, "/users/validate.json", api_key, timeout=timeout)
    translated = _translate(res, api_key)
    if not translated.get("ok"):
        return translated

    body = res.get("body") or {}
    # Whitelist: never copy the raw body. ``key`` is one of its fields.
    out = {"ok": True, "status": translated["status"]}
    for field in _VALIDATE_FIELDS:
        if field in body:
            out[field] = body[field]
    out["is_premium"] = bool(body.get("is_premium"))
    out["is_supporter"] = bool(body.get("is_supporter"))
    # The daily/hourly allowance is on the response headers, not the body; the
    # UI shows it so a user cannot silently burn the quota.
    return download._scrub_key(out, api_key)


def key_problem(res: dict) -> str | None:
    """Map a failed validation to one user-facing sentence.

    The server's own wording distinguishes the three cases, and it is more
    accurate than anything guessed locally.
    """
    if res.get("ok"):
        return None
    detail = str(res.get("detail") or "").lower()
    # Order matters: both of these are 401, so the STATUS cannot tell them
    # apart. A malformed key and a missing key produce different sentences, and
    # the user needs the one that matches their situation.
    if "valid api key" in detail:
        return ("the server rejected this string as an API key; copy it again "
                "from nexusmods.com/users/myaccount?tab=api")
    if "authentication method" in detail or res.get("status") == 401:
        return _HINT_FREE_TIER
    return res.get("message") or "the key could not be validated"


# --------------------------------------------------------------------------
# Mods
# --------------------------------------------------------------------------

def mod_info(opener, game_domain: str, mod_id: int, api_key: str,
             *, timeout: float = TIMEOUT) -> dict:
    return _translate(_raw(opener, "/games/%s/mods/%d.json" % (game_domain, mod_id),
                           api_key, timeout=timeout), api_key)


_MOD_FILE_FIELDS = ("file_id", "name", "version", "category_name", "file_name",
                    "size_kb", "uploaded_timestamp", "mod_version")


def mod_files(opener, game_domain: str, mod_id: int, api_key: str,
              *, timeout: float = TIMEOUT) -> dict:
    """List the downloadable files for a mod.

    The response is large (383 KB for one mod), so only the fields the UI needs
    are lifted out — the panel has no use for the dependency blobs.
    """
    translated = _translate(
        _raw(opener, "/games/%s/mods/%d/files.json" % (game_domain, mod_id),
             api_key, timeout=timeout), api_key)
    if not translated.get("ok"):
        return translated

    body = translated.get("data") or {}
    files = []
    for row in body.get("files") or []:
        if not isinstance(row, dict):
            continue
        files.append({f: row.get(f) for f in _MOD_FILE_FIELDS})
    return download._scrub_key(
        download._ok(game_domain=game_domain, mod_id=int(mod_id),
                     count=len(files), files=files,
                     browser_url=mod_page_url(game_domain, mod_id),
                     status=translated["status"]), api_key)


def download_link(opener, game_domain: str, mod_id: int, file_id: int,
                  api_key: str, *, timeout: float = TIMEOUT) -> dict:
    """Report what the download link would be — and refuse to pretend.

    For a free account this reliably returns 403. Rather than masking that as a
    generic failure, the result says so explicitly and carries the URL a human
    should open in a browser instead, which is the outcome that actually lets
    them get the file.
    """
    path = "/games/%s/mods/%d/files/%d/download_link.json" % (
        game_domain, mod_id, file_id)
    res = _raw(opener, path, api_key, timeout=timeout)
    page = mod_page_url(game_domain, mod_id)

    if res.get("status") == 403 and res.get("text"):
        text = res["text"]
        if _is_premium_gate(text):
            return download._scrub_key(download._fail(
                "DL_FORBIDDEN",
                detail=("the Nexus API only issues download links to premium "
                        "accounts; open the mod page in a browser and download "
                        "there, then import the ZIP"),
                status=403, premium_required=True, browser_url=page,
                server_message=text), api_key)
        if _mod_missing(text):
            return download._scrub_key(download._fail(
                "DL_NOT_FOUND", detail=text, status=403, premium_required=False,
                browser_url=page), api_key)

    translated = _translate(res, api_key)
    if not translated.get("ok"):
        translated["browser_url"] = page
        return download._scrub_key(translated, api_key)
    return download._scrub_key(
        download._ok(status=translated["status"], links=translated.get("data"),
                     browser_url=page), api_key)


_RECENT_KINDS = ("latest_added", "latest_updated", "trending")


def recent(opener, game_domain: str, kind: str, api_key: str,
           *, timeout: float = TIMEOUT) -> dict:
    """The only listing the API actually offers.

    There is no keyword search, so "browse by game" is the honest framing.
    """
    if kind not in _RECENT_KINDS:
        return download._scrub_key(download._fail(
            "DL_BAD_URL", detail="unknown listing kind %r; expected one of %s"
            % (kind, ", ".join(_RECENT_KINDS))), api_key)
    translated = _translate(
        _raw(opener, "/games/%s/mods/%s.json" % (game_domain, kind), api_key,
             timeout=timeout), api_key)
    if not translated.get("ok"):
        return translated

    rows = translated.get("data") or []
    mods = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        mods.append({
            "mod_id": row.get("mod_id"),
            "name": row.get("name"),
            "version": row.get("version"),
            "author": row.get("author"),
            "summary": row.get("summary"),
            "endorsement_count": row.get("endorsement_count"),
            "mod_page_url": mod_page_url(game_domain, row.get("mod_id")),
        })
    return download._scrub_key(
        download._ok(game_domain=game_domain, kind=kind, count=len(mods),
                     mods=mods, status=translated["status"]), api_key)


def mod_page_url(game_domain: str, mod_id) -> str:
    """The human-facing mod page — the deliverable a free account can use."""
    if mod_id is None:
        return "https://www.nexusmods.com/%s" % game_domain
    return "https://www.nexusmods.com/%s/mods/%s" % (game_domain, mod_id)


#: A search keyword is a user string that ends up in a URL another program
#: opens, so it is bounded and stripped of anything that could change the
#: meaning of the address.
MAX_QUERY_CHARS = 64


def clean_query(query) -> tuple[str, str | None]:
    """Return ``(query, problem)``; problem is None when the query is usable."""
    if not isinstance(query, str):
        return "", "query must be text"
    text = query.strip()
    if not text:
        return "", "query is empty"
    if len(text) > MAX_QUERY_CHARS:
        return "", "query is longer than %d characters" % MAX_QUERY_CHARS
    for ch in text:
        if ch in "\r\n\t" or ord(ch) < 0x20 or ord(ch) == 0x7F:
            return "", "query contains a control character"
    return text, None


def search_page_url(game_domain: str, query: str) -> str:
    """The WEBSITE search page for a keyword.

    The API has no keyword search (``mods/search.json`` parses ``search`` as a
    mod id and answers 422), so the only real search is the site's own. This
    builds that address; opening it is ``openurl``'s job. Nothing here fetches.
    """
    return "https://www.nexusmods.com/%s/search/?gsearch=%s" % (
        game_domain, urllib.parse.quote(query, safe=""))


#: Sort values the website's /mods listing accepts. The caller passes one of
#: these KEYS (never a URL); we map to the site's own parameter so a free
#: account can browse "trending / newest / updated" with no API key at all.
_BROWSE_SORTS = {
    "trending": "trending",
    "latest_added": "newest",
    "latest_updated": "updated",
}


def browse_page_url(game_domain: str, sort: str) -> str | None:
    """WEBSITE browse/sort page for a game. Returns None for an unknown sort.

    This is the no-key replacement for the API's recent() endpoint: the site
    already shows Trending / Newest / Updated, and the browser is signed in.
    Nothing is fetched here — the caller hands the URL to openurl.
    """
    param = _BROWSE_SORTS.get(sort)
    if param is None:
        return None
    return "https://www.nexusmods.com/%s/mods?sort=%s" % (game_domain, param)
