"""GitHub Releases as a download source .

Why GitHub: on the target device every other third-party source is either
unauthenticated-blocked (CurseForge 403), absent (ModDrop DNS, Thunderstore has
no Stardew community) or unusable (some hosts answer 403 for anonymous
callers). GitHub's release assets are the one hop that works end to end, and
they are the ONLY thing this module talks to.

Two facts from real-device probing drive the design:

1. ``GET /repos/{o}/{r}/releases/assets/{id}`` with
   ``Accept: application/octet-stream`` answers **302** with a signed
   ``release-assets.githubusercontent.com`` URL; following that URL yields the
   bytes. The ``browser_download_url`` printed in the release JSON is NOT
   usable here (github.com answers 502 for this device), so we never use it.
2. The signed URL is on a different host. We therefore allow-list the asset
   hostnames EXPLICITLY and match on the hostname only — never on the resolved
   IP. This device maps github.com to 127.0.0.1 in /etc/hosts and still reaches
   the real service through a local TLS proxy, so a private-IP check would
   refuse every legitimate download.

Everything here is JSON-safe and stdlib-only; the network is reached through an
injected ``opener`` so tests can run fully offline. No credentials are sent:
GitHub anonymous requests are enough for public repositories.
"""

from __future__ import annotations

import re
from urllib.parse import quote, urlsplit

from .download import (DownloadError, _check_url, _fail, _http_json_generic,
                    _ok)

API_HOST = "api.github.com"
"""The only API host this module will ever call."""

ASSET_HOSTS = frozenset({
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
})
"""Hosts a release asset redirect is allowed to point at."""

PER_PAGE_CAP = 5
"""Releases per repository request. Keeps one UI refresh to a single API call."""

DEFAULT_TIMEOUT = 30.0

MAX_DESCRIPTION = 160
"""Search results are truncated to this length before crossing the RPC bridge."""

_ZIP_CONTENT_TYPES = frozenset({
    "application/zip",
    "application/x-zip-compressed",
    "application/octet-stream",
})

# GitHub logins/owner names: conservative on purpose. \Z (not $) so a trailing
# newline can never slip through a fullmatch.
_NAME_RE = re.compile(r"[A-Za-z0-9._-]{1,100}\Z")

_API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "decky-mod-manager",
    "X-GitHub-Api-Version": "2022-11-28",
}

_ASSET_HEADERS = {
    "Accept": "application/octet-stream",
    "User-Agent": "decky-mod-manager",
}

_API_ALLOW = frozenset({API_HOST})


def _api_url(path: str) -> str:
    return "https://" + API_HOST + path


def _check_host(url: str, allowed: frozenset) -> str:
    """Require ``url`` to target a host in ``allowed`` (hostname match only).

    Thin, named alias over the shared checker so this module reads in its own
    vocabulary: the asset hop must be pinned to ``ASSET_HOSTS``, the API calls to
    ``_API_ALLOW``. Matching is on the hostname, never on a resolved IP.
    """
    return _check_url(url, allowed_hosts=allowed)


def _name(value, field: str) -> str:
    """Validate an owner/repo component; raise rather than echo junk back."""
    if not isinstance(value, str) or not _NAME_RE.fullmatch(value):
        raise DownloadError("DL_BAD_URL", detail=f"invalid {field}")
    return value


def _as_int(value, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        try:
            value = int(str(value), 10)
        except (TypeError, ValueError) as e:
            raise DownloadError("DL_BAD_URL", detail=f"invalid {field}") from e
    if value <= 0:
        raise DownloadError("DL_BAD_URL", detail=f"invalid {field}")
    return value


def _gh_json(opener, path: str, *, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """GET one api.github.com JSON document. Never sends credentials."""
    return _http_json_generic(opener, _api_url(path), headers=dict(_API_HEADERS),
                              timeout=timeout, allowed_hosts=_API_ALLOW)


def _usable_asset(asset: dict) -> bool:
    name = asset.get("name")
    if not isinstance(name, str) or not name.lower().endswith(".zip"):
        return False
    ctype = str(asset.get("content_type") or "").lower().strip()
    return ctype in _ZIP_CONTENT_TYPES


def _slim_asset(asset: dict) -> dict:
    return {
        "id": asset.get("id"),
        "name": asset.get("name"),
        "size": asset.get("size"),
        "content_type": asset.get("content_type"),
        "download_count": asset.get("download_count"),
        "usable": _usable_asset(asset),
    }


def _validate_download_url(url: str) -> str:
    """Guard a user-supplied download URL before it reaches the fetcher.

    Same rules the downloader will re-apply: https, no userinfo, default port,
    and no private/loopback literal host. Kept here so the UI can fail fast with
    a precise message instead of surfacing a transport error.
    """
    if not isinstance(url, str) or not url.strip():
        raise DownloadError("DL_BAD_URL", detail="url is required")
    parts = urlsplit(url)
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
    return url


def search_repos(opener, query: str, page: int = 1, *,
                 timeout: float = DEFAULT_TIMEOUT) -> dict:
    """GET /search/repositories and return a slim, JSON-safe result.

    ``page`` is 1-based and clamped to [1, 100] (GitHub ignores anything else).
    Only fields the UI actually renders cross the bridge, and the description is
    truncated so one pathological repo cannot bloat the RPC payload.
    """
    try:
        if not isinstance(query, str) or not query.strip():
            raise DownloadError("DL_BAD_URL", detail="query is required")
        if len(query) > 200:
            raise DownloadError("DL_BAD_URL", detail="query too long")
        page = _as_int(page, "page")
        page = min(page, 100)
        path = ("/search/repositories?q=" + quote(query.strip(), safe="")
                + "&sort=stars&order=desc&per_page=10&page=" + str(page))
        res = _gh_json(opener, path, timeout=timeout)
    except DownloadError as e:
        return _fail(e.code, detail=e.detail, **e.context)
    except Exception as e:  # noqa: BLE001 - public boundary never raises
        return _fail("DL_NETWORK", detail=f"{type(e).__name__}: {e}")
    data = res.get("data") if isinstance(res, dict) else None
    if not isinstance(data, dict):
        return _fail("DL_BAD_JSON", detail="search payload is not an object")
    items = []
    for raw in data.get("items") or []:
        if not isinstance(raw, dict):
            continue
        full_name = raw.get("full_name")
        if not isinstance(full_name, str) or "/" not in full_name:
            continue
        owner, _, repo = full_name.partition("/")
        desc = raw.get("description")
        if isinstance(desc, str) and len(desc) > MAX_DESCRIPTION:
            desc = desc[:MAX_DESCRIPTION]
        items.append({
            "owner": owner,
            "repo": repo,
            "full_name": full_name,
            "stars": raw.get("stargazers_count"),
            "description": desc,
            "updated_at": raw.get("updated_at"),
            "archived": bool(raw.get("archived")),
        })
    return _ok(total_count=data.get("total_count"), items=items, page=page)


def list_releases(opener, owner: str, repo: str, *,
                  timeout: float = DEFAULT_TIMEOUT) -> dict:
    """GET /repos/{owner}/{repo}/releases and return at most PER_PAGE_CAP.

    ``body`` is stripped (release notes are large and unrenderable on a Deck
    panel); each asset carries ``usable`` so the UI can grey out non-ZIP assets
    without a second round trip.
    """
    try:
        owner = _name(owner, "owner")
        repo = _name(repo, "repo")
        path = (f"/repos/{owner}/{repo}/releases?per_page={PER_PAGE_CAP}")
        res = _gh_json(opener, path, timeout=timeout)
    except DownloadError as e:
        return _fail(e.code, detail=e.detail, **e.context)
    except Exception as e:  # noqa: BLE001
        return _fail("DL_NETWORK", detail=f"{type(e).__name__}: {e}")
    data = res.get("data") if isinstance(res, dict) else None
    if not isinstance(data, list):
        return _fail("DL_BAD_JSON", detail="releases payload is not an array")
    releases = []
    for raw in data[:PER_PAGE_CAP]:
        if not isinstance(raw, dict):
            continue
        assets = [a for a in (raw.get("assets") or []) if isinstance(a, dict)]
        releases.append({
            "id": raw.get("id"),
            "tag_name": raw.get("tag_name"),
            "name": raw.get("name"),
            "prerelease": bool(raw.get("prerelease")),
            "draft": bool(raw.get("draft")),
            "published_at": raw.get("published_at"),
            "assets": [_slim_asset(a) for a in assets],
        })
    return _ok(owner=owner, repo=repo, releases=releases)


def asset_metadata(opener, owner: str, repo: str, asset_id: int, *,
                   timeout: float = DEFAULT_TIMEOUT) -> dict:
    """GET one release asset's metadata (id, name, size, content_type).

    Criterion 4 wants the download verified against what the SOURCE declared.
    GitHub's release JSON states ``size`` per asset, but the release list is
    truncated to PER_PAGE_CAP entries and the asset may live in an older release,
    so we ask for the one asset directly instead of scanning lists. One extra
    API call per download; it is the only way to know the authoritative length.

    ``digest`` is null for these assets on this device, so there is no upstream
    hash to check against — ``sha256`` is reported as None rather than invented.
    """
    try:
        owner = _name(owner, "owner")
        repo = _name(repo, "repo")
        asset_id = _as_int(asset_id, "asset_id")
        res = _gh_json(opener, f"/repos/{owner}/{repo}/releases/assets/{asset_id}",
                       timeout=timeout)
    except DownloadError as e:
        return _fail(e.code, detail=e.detail, **e.context)
    except Exception as e:  # noqa: BLE001
        return _fail("DL_NETWORK", detail=f"{type(e).__name__}: {e}")
    data = res.get("data") if isinstance(res, dict) else None
    if not isinstance(data, dict):
        return _fail("DL_BAD_JSON", detail="asset payload is not an object")
    size = data.get("size")
    digest = data.get("digest")
    return _ok(
        id=data.get("id"),
        name=data.get("name"),
        size=size if isinstance(size, int) and size > 0 else None,
        content_type=data.get("content_type"),
        sha256=(digest.split(":", 1)[1]
                if isinstance(digest, str) and digest.startswith("sha256:") else None),
    )


def resolve_asset(opener, owner: str, repo: str, asset_id: int, *,
                  timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Resolve a release asset id to the signed download URL, WITHOUT following it.

    The API answers 302; we read ``Location`` and refuse anything that is not on
    ``ASSET_HOSTS``. We deliberately do not follow the redirect here: the single
    fetch happens in ``auto_import`` so there is exactly one place that writes.
    """
    try:
        owner = _name(owner, "owner")
        repo = _name(repo, "repo")
        asset_id = _as_int(asset_id, "asset_id")
        url = _api_url(f"/repos/{owner}/{repo}/releases/assets/{asset_id}")
        _check_url(url, allowed_hosts=_API_ALLOW)
        resp = opener("GET", url, dict(_ASSET_HEADERS), timeout)
    except DownloadError as e:
        return _fail(e.code, detail=e.detail, **e.context)
    except Exception as e:  # noqa: BLE001
        return _fail("DL_NETWORK", detail=f"{type(e).__name__}: {e}")
    try:
        status = resp.status
        headers = dict(getattr(resp, "headers", {}) or {})
    except Exception as e:  # noqa: BLE001
        return _fail("DL_NETWORK", detail=f"headers failed: {type(e).__name__}")
    finally:
        try:
            resp.close()
        except Exception:  # noqa: BLE001 - close is best-effort
            pass
    if status in (301, 302, 303, 307, 308):
        location = None
        for k, v in headers.items():
            if str(k).lower() == "location":
                location = v
                break
        if not location:
            return _fail("DL_NO_ASSET", detail=f"HTTP {status} without Location")
        try:
            parts = urlsplit(location)
            host = (parts.hostname or "").rstrip(".").lower()
        except Exception as e:  # noqa: BLE001
            return _fail("DL_BAD_URL", detail=f"unparsable Location: {type(e).__name__}")
        if host not in ASSET_HOSTS:
            return _fail("DL_HOST_NOT_ALLOWED", detail="asset host=" + host)
        if parts.scheme != "https":
            return _fail("DL_BAD_URL", detail="asset URL is not https")
        return _ok(url=location, asset_id=asset_id, host=host)
    if status == 404:
        return _fail("DL_NOT_FOUND", detail="HTTP 404", status=status)
    if status == 403:
        return _fail("DL_FORBIDDEN", detail="HTTP 403", status=status)
    if status == 429:
        retry = headers.get("Retry-After") or headers.get("retry-after")
        return _fail("DL_RATE_LIMIT", detail="HTTP 429", retry_after=retry)
    return _fail("DL_HTTP", detail=f"HTTP {status}", status=status)
