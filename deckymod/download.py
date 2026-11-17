"""Shared low-level network + download core (stdlib only).

STATUS: this is the transport layer the plugin actually uses. It was written in
round 3 as a policy-neutral, unwired library; rounds 18-19 wired it up and
the transport is shared by GitHub Releases and a plain-https URL fallback
— see docs/DOWNLOAD_SOURCES.md. What still holds:

  * no ``E_*`` code is added to ``errors.py`` (``error_codes()`` count is 50);
    every ``DL_*`` code is mapped onto an existing ``E_*`` by
    ``auto_import.DL_TO_E`` and kept verbatim in ``detail`` for logs;
  * it writes NOTHING into the game ``Mods/`` folder, installs no loader, edits no
    launch options, touches no Proton prefix, needs no root, toggles no
    read-only filesystem setting, and claims NO universal one-click install;
  * the only filesystem write it can perform is to a CALLER-SUPPLIED inbox path
    (containment-checked), via the project's own ``fsops.atomic_write_bytes``;
  * NO credential is ever attached to a request: the shipped sources (GitHub
    Releases and a plain-https URL) are anonymous, and no API key is stored,
    read, or sent by this layer.

TESTABILITY: every network call goes through an injectable ``opener`` with the
contract ``opener(method, url, headers, timeout) -> ResponseLike`` where
ResponseLike has ``.status`` (int), ``.headers`` (dict-like), ``.read(n)`` and
``.close()``. ``default_opener`` (real stdlib urllib) is what production uses;
all behaviour is also verified offline with a fake opener.

SECURITY POSTURE (defence in depth, all enforced by this core):
  * only ``https://`` URLs are accepted; no userinfo, no non-443 port, and no
    private/loopback LITERAL host (SSRF floor). Hosts are matched by NAME only —
    never by resolved IP, because this device maps github.com to 127.0.0.1 in
    /etc/hosts while a local TLS proxy reaches the real service;
  * ``allowed_hosts`` pins a request to an explicit allow-list (the GitHub signed
    asset host) so a redirect can never wander off-host;
  * downloads are size-capped (default 256 MiB == archive.DEFAULT_LIMITS
    ``max_compressed_bytes``) via Content-Length pre-check AND a streaming ceiling;
  * round 26: ``expected_size`` / ``expected_sha256`` are verified BEFORE the
    bytes are written, so a truncated or substituted file never reaches the
    inbox. The result records which checks actually ran (``verified``) instead of
    implying verification that did not happen;
  * every public result is JSON-safe (str/int/bool/None/list/dict) — raw bytes
    stay in-process and are never put in a result dict.
"""

from __future__ import annotations

import hashlib
import ipaddress
import math
import os
import re
from urllib.parse import urlsplit

from . import fsops
from .errors import ModError

DEFAULT_MAX_BYTES = 268435456  # 256 MiB, matches archive.DEFAULT_LIMITS
DEFAULT_CHUNK = 65536
DEFAULT_TIMEOUT = 30.0
USER_AGENT = "DeckyModManager/0.1 (download-core; policy-neutral)"

_SAFE_BASENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# Error codes are MODULE-LOCAL strings (``DL_*``), deliberately NOT registered
# in errors.py. A future, user-approved RPC wiring layer maps them to E_* codes
# and to i18n keys; until then they cannot leak into the shipped UI/error table.
DL_ERRORS = {
    "DL_BAD_URL": "Only https:// URLs are allowed.",
    "DL_LOCAL_HOST": "Private / local hosts are not allowed for downloads.",
    "DL_NETWORK": "The network request failed.",
    "DL_HTTP": "The server returned an error status.",
    "DL_AUTH_REQUIRED": "Authentication is required (HTTP 401).",
    "DL_FORBIDDEN": "The API key was rejected (403).",
    "DL_RATE_LIMIT": "Rate limit reached; retry later.",
    "DL_BAD_JSON": "The server response was not valid JSON.",
    "DL_NO_LINK": "No download URL was found in the response.",
    "DL_TOO_LARGE": "The download exceeds the configured size cap.",
    "DL_TRUNCATED": "The download ended before the advertised length.",
    "DL_INBOX_MISSING": "The caller-supplied inbox directory does not exist.",
    "DL_BAD_FILENAME": "The destination file name is not a safe basename.",
    "DL_PATH_ESCAPE": "The destination escapes the inbox directory.",
    "DL_WRITE_FAILED": "The download could not be written to the inbox.",
    # Round 19 (non-upstream sources). Still MODULE-LOCAL: they are mapped onto the
    # existing 50 E_* codes by auto_import.DL_TO_E, so errors.py is unchanged.
    "DL_HOST_NOT_ALLOWED": "The host is not on the download allow-list.",
    "DL_NO_ASSET": "No usable ZIP asset was found.",
    "DL_NOT_FOUND": "The requested resource was not found (404).",
    # Round 26: post-download integrity. The source declares what the file must
    # be; we compare before handing it to the engine. Still module-local, still
    # mapped onto the existing 50 E_* codes by auto_import.DL_TO_E.
    "DL_SIZE_MISMATCH": "The downloaded file is not the size the source declared.",
    "DL_HASH_MISMATCH": "The downloaded file does not match the expected SHA-256.",
}


class DownloadError(Exception):
    """Internal control-flow error; public functions convert it to a dict."""

    def __init__(self, code: str, *, detail: str = "", **context):
        super().__init__(code)
        self.code = code
        self.message = DL_ERRORS.get(code, "Download core error.")
        self.detail = detail
        self.context = context


def _fail(code: str, *, detail: str = "", **context) -> dict:
    out = {"ok": False, "code": code, "message": DL_ERRORS.get(code, "Download core error.")}
    if detail:
        out["detail"] = _redact(detail)
    for k, v in context.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = _redact(v) if isinstance(v, str) else v
    return out


def _redact(text: str) -> str:
    """Best-effort scrub of a leaked API key from any surfaced string."""
    # Server responses are untrusted: a message body may echo ``apikey=...``.
    # Strip apikey-shaped tokens defensively. Never echo the key verbatim.
    return re.sub(r"(?i)(apikey['\"=:\s]+)[A-Za-z0-9_\-]{6,}", r"\1<redacted>", text)


def _scrub_key(result: dict, api_key: str) -> dict:
    """Remove the caller's exact API key from every string in a result.

    This is the PRIMARY defence: unlike pattern matching it does not depend on
    a surrounding ``apikey=`` label, so a server that echoes the raw key is
    still scrubbed. Applied at every public function boundary.
    """
    def scrub(v, _d: int = 0):
        if _d > 40:
            return v
        if isinstance(v, str):
            return v.replace(api_key, "<redacted>")
        if isinstance(v, dict):
            return {k: scrub(val, _d + 1) for k, val in v.items()}
        if isinstance(v, (list, tuple)):
            return [scrub(x, _d + 1) for x in v]
        return v

    if api_key:
        result = scrub(result)
    # F2: enforce strict JSON-safety at EVERY public boundary (covers _fail()
    # context floats too), not just on the _ok() path.
    return _json_sanitize(result)


def _redact_tree(value, _depth: int = 0):
    """Recursively scrub apikey-shaped tokens from every string in a result."""
    if _depth > 40:
        return value
    if isinstance(value, str):
        return _redact(value)
    if isinstance(value, dict):
        return {k: _redact_tree(v, _depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_tree(v, _depth + 1) for v in value]
    return value


def _json_sanitize(value, _depth: int = 0):
    """Force any value tree into strict-JSON-safe leaves (no NaN/Infinity, no
    bytes/objects). ``json.dumps(..., allow_nan=False)`` is the shipped gateway
    (envelope.py:50) and the test assertion (test_download.py:30), so the unwired
    core must honour the same contract instead of relying on the wiring layer.
    """
    if _depth > 40:
        return None
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        # bool is handled above; reject non-finite floats that json.loads accepts.
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _json_sanitize(v, _depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_sanitize(v, _depth + 1) for v in value]
    # bytes / bytearray / Path / set / exception objects etc. never surface.
    return None


def _ok(**context) -> dict:
    out = {"ok": True}
    for k, v in context.items():
        out[k] = v
    # Every public result passes through here: scrub server-echoed key material
    # AND enforce strict JSON-safety (F2: json.loads would otherwise admit NaN).
    return _json_sanitize(_redact_tree(out))


def _private_literal(host: str) -> bool:
    if host in ("localhost", "localhost.localdomain", "metadata.google.internal"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


def _check_url(url: str, *, allow_local: bool = False,
               allowed_hosts: frozenset | None = None) -> str:
    """Validate a URL before any request is issued.

    ``allowed_hosts`` (round 19): when supplied, the host must match one of the
    allow-listed names EXACTLY (case-insensitive, trailing dot stripped). This is
    strictly stronger than the default "not a private literal" check and is what
    the GitHub asset hop uses. Crucially we match on the HOSTNAME only -- never
    on a resolved IP -- because this device maps github.com to 127.0.0.1 in
    /etc/hosts and still reaches the real service through a local TLS proxy; a
    private-IP check would refuse every legitimate download here.
    """
    parts = urlsplit(url or "")
    if parts.scheme != "https" or not parts.hostname:
        raise DownloadError("DL_BAD_URL", detail="scheme/host invalid")
    if parts.username or parts.password:
        raise DownloadError("DL_BAD_URL", detail="userinfo is not allowed")
    try:
        port = parts.port
    except ValueError as e:
        raise DownloadError("DL_BAD_URL", detail="malformed port") from e
    if port is not None and port != 443:
        raise DownloadError("DL_BAD_URL", detail=f"non-443 port {port}")
    # F3: a hostname may carry a trailing dot ("localhost.") that bypasses a
    # naive literal comparison; normalise before any host check.
    host = parts.hostname.rstrip(".").lower()
    if allowed_hosts is not None:
        if host not in allowed_hosts:
            raise DownloadError("DL_HOST_NOT_ALLOWED", detail="host=" + host)
        return url
    if not allow_local and _private_literal(host):
        raise DownloadError("DL_LOCAL_HOST", detail="host=" + host)
    return url


def _headers() -> dict:
    """Neutral transport headers. No credential is ever attached."""
    return {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}


class _Response:
    """Uniform response shape returned by an opener (real or fake)."""

    def __init__(self, status: int, headers: dict | None, chunks):
        self.status = int(status)
        self.headers = dict(headers or {})
        self._buf = b"".join(bytes(c) for c in chunks)
        self._pos = 0
        self.closed = False

    def read(self, amt: int = -1) -> bytes:
        if amt is None or amt < 0:
            out, self._pos = self._buf[self._pos:], len(self._buf)
            return out
        out = self._buf[self._pos:self._pos + amt]
        self._pos += len(out)
        return out

    def close(self) -> None:
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _ssl_context():
    """A verifying TLS context that trusts BOTH the system store and certifi.

    Two separate facts, both found on the real device:

    1. Decky runs plugins inside a PyInstaller-frozen interpreter, where
       OpenSSL's compiled-in default CA paths are not consulted, so a bare
       ``urlopen`` dies with ``CERTIFICATE_VERIFY_FAILED: unable to get local
       issuer certificate``. Every network RPC failed inside the live plugin
       while the identical request succeeded from ``/usr/bin/python3``.
    2. This Deck's traffic is intercepted by a local TLS proxy whose CA
       ("QiYou Game CA") is installed in the SYSTEM bundle
       (``/etc/ssl/certs/ca-certificates.crt`` -> 121 certs) but is absent from
       the ``certifi`` bundle shipped with the frozen app (120 certs).

    So preferring certifi - the obvious first choice - silently produces a
    context that cannot verify anything on this device. Instead we build one
    context and *union* every bundle we can find: the distro store, certifi,
    and the frozen app's own copy. Verification is never disabled; if no bundle
    is readable we return the default context and let it fail loudly rather
    than trust everything.
    """
    import ssl

    candidates = []
    # The system store comes FIRST: it is the one that carries locally installed
    # (e.g. proxy/interception) CAs, which a distro-shipped certifi cannot know.
    candidates.extend([
        "/etc/ssl/certs/ca-certificates.crt",
        "/etc/ssl/cert.pem",
        "/etc/pki/tls/certs/ca-bundle.crt",
    ])
    # Then certifi, which is what the frozen bundle necessarily carries.
    try:
        import certifi  # type: ignore[import-not-found]

        candidates.append(certifi.where())
    except Exception:  # noqa: BLE001 - optional dependency
        pass
    # And the frozen app's own copy, discovered relative to the runtime.
    try:
        import sys

        for base in (getattr(sys, "_MEIPASS", None), os.path.dirname(sys.executable)):
            if base:
                candidates.append(os.path.join(base, "certifi", "cacert.pem"))
    except Exception:  # noqa: BLE001
        pass

    ctx = ssl.create_default_context()
    loaded = 0
    seen = set()
    for path in candidates:
        if not path or path in seen or not os.path.isfile(path):
            continue
        seen.add(path)
        try:
            ctx.load_verify_locations(cafile=path)
            loaded += 1
        except Exception:  # noqa: BLE001 - a bad bundle must not break the rest
            continue
    if loaded == 0:
        return ssl.create_default_context()
    return ctx


def default_opener(method: str, url: str, headers: dict, timeout: float,
                   body: "bytes | None" = None) -> _Response:
    """Real stdlib opener used in production.

    Uses ``urllib.request`` with an explicit verifying SSL context (see
    :func:`_ssl_context` — the frozen Decky interpreter cannot find a CA bundle
    on its own). Converts urllib ``HTTPError`` into a normal ``_Response`` so
    the core never deals with exceptions-as-responses.

    ``body`` (round 38) is optional and defaults to None, so every existing
    GET call site keeps its exact behaviour. It exists because the dependency
    resolver has to POST a JSON query to the SMAPI index; that endpoint answers
    405 to GET.
    """
    import urllib.error
    import urllib.request

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        """F3: never auto-follow a 3xx. The core validates the ORIGINAL URL
        only; a redirect must be surfaced as a normal response (not silently
        followed with the apikey header re-sent to an arbitrary target)."""

        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(
        _NoRedirect,
        urllib.request.HTTPSHandler(context=_ssl_context()),
    )
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        raw = opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        return _Response(e.code, dict(e.headers or {}), [e.read()])
    with raw:
        status = getattr(raw, "status", None) or raw.getcode()
        body = raw.read(DEFAULT_MAX_BYTES + 1)  # bounded; streaming cap re-checked by caller
        return _Response(status, dict(raw.headers or {}), [body])


def _http_json_generic(opener, url: str, *, headers: dict, timeout: float,
                       allowed_hosts: frozenset | None = None) -> dict:
    """Round 19: the same JSON fetch, but for any allow-listed https endpoint.

    Used by ``github_source`` for api.github.com. Host policy is decided here by
    ``allowed_hosts`` pins the request to an explicit host allow-list.
    """
    _check_url(url, allowed_hosts=allowed_hosts)
    try:
        resp = opener("GET", url, dict(headers), timeout)
    except DownloadError:
        raise
    except Exception as e:  # noqa: BLE001 - converted to a clean result
        raise DownloadError("DL_NETWORK", detail=f"{type(e).__name__}: {e}") from e
    status = resp.status
    try:
        raw_headers = dict(getattr(resp, "headers", {}) or {})
    except Exception as e:  # noqa: BLE001 - F1: malformed headers must not escape
        raise DownloadError("DL_NETWORK", detail=f"headers failed: {type(e).__name__}") from e
    # F4: always close the response, even when read() raises.
    try:
        try:
            body = resp.read()
        except Exception as e:  # noqa: BLE001
            raise DownloadError("DL_NETWORK", detail=f"read failed: {type(e).__name__}") from e
    finally:
        try:
            resp.close()
        except Exception:  # noqa: BLE001 - close is best-effort
            pass
    if status == 401:
        raise DownloadError("DL_AUTH_REQUIRED", detail="HTTP 401", status=status)
    if status == 403:
        raise DownloadError("DL_FORBIDDEN", detail="HTTP 403", status=status)
    if status == 429:
        retry = raw_headers.get("Retry-After") or raw_headers.get("retry-after")
        raise DownloadError("DL_RATE_LIMIT", detail="HTTP 429", status=status,
                         retry_after=retry)
    if status == 404:
        raise DownloadError("DL_NOT_FOUND", detail="HTTP 404", status=status)
    if not (200 <= status < 300):
        raise DownloadError("DL_HTTP", detail=f"HTTP {status}", status=status)
    import json

    def _reject_constant(token):
        # F2: stdlib json.loads otherwise ADMITS NaN/Infinity/-Infinity, which
        # are not JSON-safe (json.dumps(allow_nan=False) would raise).
        raise ValueError("non-finite constant " + token)

    try:
        data = json.loads(body.decode("utf-8", errors="replace"),
                          parse_constant=_reject_constant)
    except (ValueError, UnicodeError) as e:
        raise DownloadError("DL_BAD_JSON", detail=f"{type(e).__name__}") from e
    return _ok(status=status, data=data)


def _download_meta(resp, max_bytes: int) -> int | None:
    cl = None
    for k, v in (getattr(resp, "headers", {}) or {}).items():
        if str(k).lower() == "content-length":
            try:
                cl = int(v)
            except (TypeError, ValueError):
                cl = None
            break
    if cl is not None and cl > max_bytes:
        raise DownloadError("DL_TOO_LARGE", detail=f"Content-Length={cl}", size=cl)
    return cl


def _fetch_bytes(opener, url: str, *, api_key: str, max_bytes: int,
                 timeout: float, chunk: int,
                 allowed_hosts: frozenset | None = None) -> tuple[dict, bytes]:
    """Return (JSON-safe meta dict, raw bytes). Bytes are NEVER put in the dict.

    ``allowed_hosts`` (round 19) pins the request to an explicit host allow-list
    instead of the default private-literal check; github_source uses it for the
    release-assets hop so a redirected download can never wander off-host.
    """
    _check_url(url, allowed_hosts=allowed_hosts)
    headers = _headers()  # apikey NEVER goes to a CDN
    try:
        resp = opener("GET", url, headers, timeout)
    except DownloadError:
        raise
    except Exception as e:  # noqa: BLE001
        raise DownloadError("DL_NETWORK", detail=f"{type(e).__name__}: {e}") from e
    status = resp.status
    # F4: from the moment we hold resp, EVERY exit path closes it (including the
    # _download_meta DL_TOO_LARGE pre-check and the non-2xx branch).
    try:
        if not (200 <= status < 300):
            raise DownloadError("DL_HTTP", detail=f"HTTP {status}", status=status)
        advertised = _download_meta(resp, max_bytes)
        buf = bytearray()
        while True:
            part = resp.read(chunk)
            if not part:
                break
            buf.extend(part)
            if len(buf) > max_bytes:
                raise DownloadError("DL_TOO_LARGE", detail="stream exceeded cap",
                                 size=len(buf))
    finally:
        try:
            resp.close()
        except Exception:  # noqa: BLE001 - close is best-effort
            pass
    data = bytes(buf)
    if advertised is not None and len(data) != advertised:
        raise DownloadError("DL_TRUNCATED", detail=f"got={len(data)} want={advertised}",
                         size=len(data))
    meta = {
        "status": status,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "capped_at": max_bytes,
    }
    return meta, data


def download_to_inbox(opener, url: str, api_key: str, inbox_dir: str,
                      filename: str, *, max_bytes: int = DEFAULT_MAX_BYTES,
                      timeout: float = DEFAULT_TIMEOUT,
                      chunk: int = DEFAULT_CHUNK,
                      allowed_hosts: frozenset | None = None,
                      expected_size: int | None = None,
                      expected_sha256: str | None = None) -> dict:
    """Fetch ``url`` and land it as ``inbox_dir/filename`` (atomic, contained).

    This is the ONLY function in this module that touches the filesystem, and it
    writes ONLY to the caller-supplied inbox — never to a game Mods/ folder.
    Returns a JSON-safe dict (bytes are not included).

    ``allowed_hosts`` (round 19) is forwarded to ``_fetch_bytes``; it lets the
    GitHub source pin its redirected asset URL to release-assets hostnames.

    ``expected_size`` / ``expected_sha256`` (round 26) are the integrity check
    criterion 4 asks for. When the source declares them we verify BEFORE the
    bytes are written, so a truncated or substituted file never reaches the
    inbox at all. Both are optional: a plain user-supplied URL has no manifest
    to compare against, and pretending it was verified would be a lie.
    """
    # F1: every filesystem/arg operation is inside one broad boundary guard, so
    # a non-str filename/inbox_dir (TypeError) can never escape a public function.
    try:
        # F5: fullmatch + \Z so a trailing newline cannot slip through.
        if not isinstance(filename, str) or not _SAFE_BASENAME.fullmatch(filename):
            return _scrub_key(_fail("DL_BAD_FILENAME", detail="filename must be a safe basename"), api_key)
        base = os.path.realpath(inbox_dir)
        if not os.path.isdir(base):
            return _scrub_key(_fail("DL_INBOX_MISSING", detail="inbox dir not a directory"), api_key)
        final = os.path.realpath(os.path.join(base, filename))
        try:
            contained = os.path.commonpath([base, final]) == base
        except ValueError:  # different drives on Windows
            contained = False
        if not contained or os.path.dirname(final) != base:
            return _scrub_key(_fail("DL_PATH_ESCAPE", detail="destination escapes inbox"), api_key)
    except Exception as e:  # noqa: BLE001
        return _scrub_key(_fail("DL_NETWORK", detail=f"{type(e).__name__}: {e}"), api_key)
    try:
        meta, data = _fetch_bytes(opener, url, api_key=api_key,
                                  max_bytes=max_bytes, timeout=timeout, chunk=chunk,
                                  allowed_hosts=allowed_hosts)
    except DownloadError as e:
        return _scrub_key(_fail(e.code, detail=e.detail, **e.context), api_key)
    except Exception as e:  # noqa: BLE001 - F1: opener/shape failures never escape
        return _scrub_key(_fail("DL_NETWORK", detail=f"{type(e).__name__}: {e}"), api_key)

    # --- round 26: verify BEFORE writing, so a bad file never lands ----------
    # Both checks are only as strong as what the source declared. When the source
    # said nothing (expected_* is None) we do NOT claim verification: the meta
    # dict already carries the measured size/sha256 and add_policy() below
    # records which checks actually ran.
    verified = []
    if expected_size is not None:
        try:
            want_size = int(expected_size)
        except (TypeError, ValueError):
            return _scrub_key(_fail("DL_SIZE_MISMATCH",
                                    detail="expected_size is not an integer"), api_key)
        if meta.get("size") != want_size:
            return _scrub_key(_fail("DL_SIZE_MISMATCH",
                                    detail="got=%s want=%s" % (meta.get("size"), want_size),
                                    size=meta.get("size")), api_key)
        verified.append("size")
    if expected_sha256 is not None:
        want_hash = str(expected_sha256).strip().lower()
        # A hex digest only. Rejecting anything else stops "verified" from being
        # reported for a source that passed junk.
        if not re.fullmatch(r"[0-9a-f]{64}\Z", want_hash):
            return _scrub_key(_fail("DL_HASH_MISMATCH",
                                    detail="expected_sha256 is not a sha256 hex digest"), api_key)
        if meta.get("sha256") != want_hash:
            return _scrub_key(_fail("DL_HASH_MISMATCH",
                                    detail="got=%s want=%s" % (meta.get("sha256"), want_hash)), api_key)
        verified.append("sha256")
    if verified:
        meta["verified"] = verified
        meta["expected_size"] = expected_size
        if expected_sha256 is not None:
            meta["expected_sha256"] = str(expected_sha256).strip().lower()
    else:
        meta["verified"] = []

    try:
        fsops.atomic_write_bytes(final, data)
    except ModError as e:
        return _scrub_key(_fail("DL_WRITE_FAILED", detail=e.detail, errno_code=e.code), api_key)
    except Exception as e:  # noqa: BLE001
        return _scrub_key(_fail("DL_WRITE_FAILED", detail=f"{type(e).__name__}: {e}"), api_key)
    return _scrub_key(_ok(path=final, **meta), api_key)
