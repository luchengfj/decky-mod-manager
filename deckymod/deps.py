"""Resolve a mod's required dependencies to downloadable assets (round 38).

Why this module exists: SMAPI refuses to load a mod whose required
dependencies are absent, so "install one mod" could look successful while the
game silently skips it. The user asked whether those dependencies can be
fetched together. This answers it, honestly, including the cases where the
answer is no.

The hard part is not HTTP — it is knowing that the file you downloaded really
is the dependency you asked for. Two facts from the device forced the design:

* A monorepo publishes one release per mod (``furniture-machine/0.0.2`` ->
  ``FurnitureMachine.0.0.2.zip``). So "first usable .zip in the repo" is a
  guess, and a wrong one: selph.ExtraMachineConfig and selph.FurnitureMachine
  share ``zombifier/My_Stardew_Mods``.
* The public SMAPI index does not cover everything. Two of the four
  dependencies actually missing on the test device have no GitHub repo in the
  index at all.

Therefore resolution is two-stage and never trusts a filename:

1. Ask the SMAPI index which GitHub repo (if any) publishes a given id.
2. Download candidates and open their manifest. A candidate is accepted only
   when the manifest's own ``UniqueID`` equals the requested id. Anything else
   is rejected and the next candidate is tried, within a fixed budget.

No credential is sent anywhere; both endpoints are anonymous.
"""

from __future__ import annotations

import json
import os

from . import download
from .errors import ModError

INDEX_URL = "https://smapi.io/api/v2.2/mods"
INDEX_HOST = "smapi.io"
MAX_CANDIDATES_PER_DEP = 4
MAX_DEPS = 20
MAX_INDEX_BYTES = 4 * 1024 * 1024
# How many times the "what is still missing" question may be re-asked after a
# round of installs. A dependency chain is normally one level; three gives room
# for a dependency of a dependency without letting a cycle in the index spin
# forever. The number is reported back so a truncated run is visible.
MAX_ROUNDS = 3
USER_AGENT = "decky-mod-manager"

_ZIP_CONTENT_TYPES = frozenset({
    "application/zip",
    "application/x-zip-compressed",
    "application/octet-stream",
})


def _fail(code: str, detail: str = "") -> dict:
    return {"ok": False, "code": code,
            "message": download.DL_ERRORS.get(code, code), "detail": detail}


def _ok(**kw) -> dict:
    out = {"ok": True}
    out.update(kw)
    return out


def _index_headers() -> dict:
    return {"Accept": "application/json", "User-Agent": USER_AGENT,
            "Content-Type": "application/json"}


def _gh_headers() -> dict:
    return {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28"}


def _segments(uid: str) -> str:
    """Last dotted segment of a mod id, lowercased: 'selph.FurnitureMachine'
    -> 'furnituremachine'. Used only to ORDER candidates, never to accept one."""
    return str(uid or "").strip().split(".")[-1].lower()


def lookup_index(opener, ids, *, timeout=download.DEFAULT_TIMEOUT) -> dict:
    """Map each mod id to the GitHub repo the SMAPI index names for it.

    The index answers a POST with an object array; a string array is silently
    treated as "no metadata" (returns []), so the shape here matters.
    """
    wanted = [str(i) for i in ids][:MAX_DEPS]
    if not wanted:
        return _ok(entries={})
    try:
        download._check_url(INDEX_URL, allowed_hosts=frozenset({INDEX_HOST}))
    except download.DownloadError as e:
        return _fail(e.code, e.detail or "")
    body = json.dumps({
        "mods": [{"id": i} for i in wanted],
        "includeExtendedMetadata": True,
    }).encode("utf-8")
    try:
        resp = opener("POST", INDEX_URL, _index_headers(), timeout, body)
    except Exception as e:
        return _fail("DL_NETWORK", "%s: %s" % (type(e).__name__, e))
    try:
        chunks = []
        total = 0
        while True:
            block = resp.read(download.DEFAULT_CHUNK)
            if not block:
                break
            total += len(block)
            if total > MAX_INDEX_BYTES:
                return _fail("DL_TOO_LARGE", "index response over %d bytes" % MAX_INDEX_BYTES)
            chunks.append(block)
        raw = b"".join(chunks)
    except Exception as e:
        return _fail("DL_NETWORK", "%s: %s" % (type(e).__name__, e))
    finally:
        try:
            resp.close()
        except Exception:
            pass
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        return _fail("DL_BAD_JSON", str(e))
    if not isinstance(data, list):
        return _fail("DL_BAD_JSON", "index returned %s, expected a list" % type(data).__name__)

    entries = {}
    for rec in data:
        if not isinstance(rec, dict):
            continue
        meta = rec.get("metadata") if isinstance(rec.get("metadata"), dict) else {}
        id_list = meta.get("id") if isinstance(meta.get("id"), list) else []
        uid = str(id_list[0]) if id_list else str(rec.get("id") or "")
        if not uid:
            continue
        repo = meta.get("gitHubRepo")
        entries[uid.lower()] = {
            "id": uid,
            "gitHubRepo": str(repo) if repo else None,
        }
    return _ok(entries=entries)


def candidate_assets(opener, repo: str, wanted_uid: str,
                     *, timeout=download.DEFAULT_TIMEOUT) -> dict:
    """Usable .zip assets in ``repo``, best match for ``wanted_uid`` first.

    Ordering is a hint; acceptance happens in :func:`verify_candidate` by
    reading the manifest. A repo that publishes many mods will therefore not
    yield the wrong one just because its name came first.
    """
    if "/" not in str(repo):
        return _fail("DL_BAD_URL", "repo must be owner/name")
    url = "https://api.github.com/repos/%s/releases?per_page=20" % repo
    try:
        res = download._http_json_generic(
            opener, url, headers=_gh_headers(), timeout=timeout,
            allowed_hosts=frozenset({"api.github.com"}))
    except download.DownloadError as e:
        return _fail(e.code, e.detail or "")
    if not res.get("ok"):
        return res
    payload = res.get("data")
    if not isinstance(payload, list):
        return _fail("DL_BAD_JSON", "releases was %s" % type(payload).__name__)

    want = _segments(wanted_uid)
    matched, other = [], []
    for rel in payload:
        if not isinstance(rel, dict):
            continue
        tag = str(rel.get("tag_name") or "")
        for a in rel.get("assets") or []:
            if not isinstance(a, dict):
                continue
            name = str(a.get("name") or "")
            ct = str(a.get("content_type") or "")
            aid = a.get("id")
            size = a.get("size")
            if not name.lower().endswith(".zip") or ct not in _ZIP_CONTENT_TYPES:
                continue
            if not isinstance(aid, int) or aid <= 0:
                continue
            item = {
                "asset_id": aid,
                "name": name,
                "size": size if isinstance(size, int) and size > 0 else None,
                "tag": tag,
            }
            flat = name.lower().replace("-", "").replace("_", "").replace(".", "")
            if want and want.replace(".", "") in flat:
                matched.append(item)
            else:
                other.append(item)
    return _ok(assets=(matched + other)[:MAX_CANDIDATES_PER_DEP],
               matched=len(matched))


def verify_candidate(engine, zip_path: str, wanted_uid: str) -> dict:
    """Accept a downloaded zip only if its manifest names ``wanted_uid``.

    This is the whole point of the module: a filename is not evidence, and the
    manifest is the same authority the game's loader uses.
    """
    try:
        env = engine.inspect(zip_path)
    except ModError as e:
        return _fail(e.code, e.detail or "")
    if not env.get("ok"):
        return env
    data = env.get("data") or {}
    mod = data.get("mod") if isinstance(data.get("mod"), dict) else {}
    got = str(mod.get("uniqueId") or mod.get("packageId") or "")
    if got.strip().lower() != str(wanted_uid).strip().lower():
        return _fail("DL_BAD_ARCHIVE",
                     "asset declares %r, expected %r" % (got, wanted_uid))
    return _ok(mod=mod)


def to_json_safe(obj):
    """Envelope-safe copy; the shared layer already scrubs, this only guards
    against a non-serialisable value slipping in from a parsed manifest."""
    try:
        json.dumps(obj, allow_nan=False)
        return obj
    except (TypeError, ValueError):
        return {"error": "not_json_safe"}


def plan(missing_ids, *, lookup, candidates_for, limit=MAX_DEPS) -> dict:
    """Pure planning step: which dependencies can be fetched, and why not.

    Split out from the network code so every branch is testable without HTTPS:
    the caller injects ``lookup(ids) -> {id: repo}`` and
    ``candidates_for(repo, uid) -> [assets]``.
    """
    ids = []
    for i in list(missing_ids or []):
        s = str(i).strip()
        if s and s.lower() not in [x.lower() for x in ids]:
            ids.append(s)
    ids = ids[:limit]
    if not ids:
        return _ok(deps=[], fetchable=0, total=0)

    resolved = lookup(ids) or {}
    deps = []
    fetchable = 0
    for uid in ids:
        row = {
            "uniqueId": uid,
            "repo": None,
            "resolvable": False,
            "reason": "",
            "candidates": [],
        }
        meta = (resolved.get(uid.lower()) or {}) if isinstance(resolved, dict) else {}
        repo = meta.get("gitHubRepo")
        if not repo:
            # The index knows the mod but names no repository we can download
            # from: it is published somewhere this plugin does not fetch.
            row["reason"] = "no_repo_in_index"
            deps.append(row)
            continue
        row["repo"] = repo
        cands = candidates_for(repo, uid) or []
        row["candidates"] = list(cands)[:MAX_CANDIDATES_PER_DEP]
        if row["candidates"]:
            row["resolvable"] = True
            fetchable += 1
        else:
            row["reason"] = "no_zip_asset"
        deps.append(row)
    return _ok(deps=deps, fetchable=fetchable, total=len(ids))


def _inbox_path(engine, filename: str) -> str:
    env = engine.list_inbox()
    if not env.get("ok"):
        raise ModError("E_INBOX_UNREADABLE", detail="list_inbox failed")
    data = env.get("data") or {}
    for item in data.get("items") or []:
        if isinstance(item, dict) and str(item.get("name")) == filename:
            return str(item.get("path") or "")
    raise ModError("E_INBOX_UNREADABLE", detail="%s missing from inbox" % filename)


def run(opener, engine, *, missing_ids, allow_install=False,
        after_confirm=False, max_bytes=download.DEFAULT_MAX_BYTES,
        timeout=download.DEFAULT_TIMEOUT, lookup=None, candidates_for=None,
        fetch=None, rescan=None, max_rounds=MAX_ROUNDS) -> dict:
    """TRI-STATE, same shape as the other download RPCs.

    ``allow_install=False`` -> plan only, zero writes.
    ``allow_install=True, after_confirm=False`` -> the plan plus a confirmation
    sentence; still zero writes.
    Both True -> download + manifest-verify + install each dependency, then
    report one row per dependency. A dependency that cannot be fetched is
    reported as such; it is never silently skipped and never replaced by a
    wrong file.

    Round 45: the install loop is now DEPTH-AWARE. ``missing_ids`` is what the
    game reports missing right now, but a dependency that gets installed can
    itself depend on something else, and that second-level gap is invisible
    until the scan is re-run. After each round the caller-supplied ``rescan``
    (by default ``engine.status()``'s own ``missing_dependencies``) is asked
    again, and anything new is resolved in the next round, bounded by
    ``max_rounds`` so a dependency cycle cannot spin forever. Every row carries
    the ``round`` it was resolved in, so the UI can say "two levels deep, then
    stopped".

    ``lookup`` / ``candidates_for`` / ``fetch`` / ``rescan`` are injection
    points for tests: the network calls stay in this module, but every decision
    is reachable offline.
    """
    if lookup is None:
        def lookup(ids):
            got = lookup_index(opener, ids, timeout=timeout)
            return got.get("entries") or {}

    if candidates_for is None:
        def candidates_for(repo, uid):
            got = candidate_assets(opener, repo, uid, timeout=timeout)
            return got.get("assets") or []

    if rescan is None:
        def rescan():
            try:
                st = engine.status()
            except Exception:
                return []
            data = st.get("data") or {}
            state = data.get("state") or {}
            return [str(x) for x in (state.get("missing_dependencies") or [])]

    try:
        made = plan(missing_ids, lookup=lookup,
                    candidates_for=candidates_for, limit=MAX_DEPS)
    except Exception as e:
        return _fail("DL_NETWORK", "%s: %s" % (type(e).__name__, e))
    if not made.get("ok"):
        return made

    deps = made.get("deps") or []
    base = {
        "deps": deps,
        "fetchable": made.get("fetchable", 0),
        "total": made.get("total", 0),
        "install_allowed": bool(allow_install),
    }

    if not allow_install:
        out = _ok(phase="inspect", **base)
        out["note"] = "read-only half-chain; nothing was downloaded"
        return to_json_safe(out)

    if not after_confirm:
        out = _ok(phase="confirm", **base)
        out["confirm_text"] = (
            "Download and install %d of %d required dependencies?" %
            (made.get("fetchable", 0), made.get("total", 0)))
        out["warnings"] = [
            "a dependency is accepted only when the manifest inside the "
            "downloaded zip names the same UniqueID",
            "a dependency may itself require others; the scan is re-run after "
            "each round, up to %d rounds" % max_rounds]
        return to_json_safe(out)

    if fetch is None:
        def fetch(repo, asset_id, filename):
            return auto_download(opener, engine, repo, asset_id, filename,
                                 max_bytes=max_bytes, timeout=timeout)

    results = []
    installed = 0
    seen = set()
    rounds_run = 0
    pending = deps

    for round_no in range(1, int(max_rounds) + 1):
        rounds_run = round_no
        any_attempted = False
        for dep in pending:
            uid = str(dep.get("uniqueId") or "")
            key = uid.lower()
            if key in seen:
                continue
            seen.add(key)
            any_attempted = True
            row = {"uniqueId": uid, "installed": False, "reason": "",
                   "repo": dep.get("repo"), "asset": None, "detail": "",
                   "round": round_no}
            if not dep.get("resolvable"):
                row["reason"] = dep.get("reason") or "unresolvable"
                results.append(row)
                continue
            for asset in dep.get("candidates") or []:
                name = str(asset.get("name") or "")
                try:
                    got = fetch(dep["repo"], asset["asset_id"], name)
                except Exception as e:
                    row["detail"] = "%s: %s" % (type(e).__name__, e)
                    continue
                if not got.get("ok"):
                    row["detail"] = str(got.get("detail") or got.get("code") or "")
                    continue
                path = str(got.get("path") or "")
                # A filename is not evidence: open the zip and read its manifest.
                verdict = verify_candidate(engine, path, uid)
                if not verdict.get("ok"):
                    row["detail"] = str(verdict.get("detail") or "")
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                    continue
                try:
                    inst = engine.install(path, after_confirm=True)
                except Exception as e:
                    # An engine that raises must not take the whole batch down.
                    row["detail"] = "%s: %s" % (type(e).__name__, e)
                    row["reason"] = "install_raised"
                    break
                if not inst.get("ok"):
                    row["detail"] = str(
                        inst.get("detail") or inst.get("code") or "install failed")
                    row["reason"] = "install_refused"
                    break
                row["installed"] = True
                row["asset"] = name
                installed += 1
                break
            if not row["installed"] and not row["reason"]:
                row["reason"] = ("candidate_failed" if row["detail"]
                                 else "no_candidate_matched")
            results.append(row)
            # Keep going: the dependencies are independent, so one that cannot
            # be obtained must not block the others. A device run proved the
            # cost of stopping early — selph.ExtraMachineConfig failed and its
            # sibling selph.FurnitureMachine was never even attempted, even
            # though it was downloadable. Partial progress is strictly better
            # here, and every failure is reported by name.

        if not any_attempted:
            break
        # Depth: what is STILL missing now that this round's installs landed.
        try:
            still = [str(x) for x in (rescan() or [])]
        except Exception:
            still = []
        fresh = [x for x in still if x.lower() not in seen]
        if not fresh:
            break
        try:
            nxt = plan(fresh, lookup=lookup,
                       candidates_for=candidates_for, limit=MAX_DEPS)
        except Exception:
            break
        if not nxt.get("ok"):
            break
        pending = nxt.get("deps") or []
        if not pending:
            break

    out = _ok(phase="installed", deps=results,
              installed=installed, attempted=len(results),
              rounds=rounds_run, max_rounds=int(max_rounds))
    try:
        remaining = [str(x) for x in (rescan() or [])]
    except Exception:
        remaining = []
    out["still_missing"] = remaining
    if remaining:
        # Two honest reasons to stop with gaps left, and they mean different
        # things to the user: we ran out of rounds, or the next scan offered
        # nothing this plugin can fetch. Saying "nothing publishes them" when
        # we simply hit the cap would be a lie; saying nothing at all would
        # hide that the install is incomplete.
        if rounds_run >= int(max_rounds):
            out["note"] = ("stopped after %d rounds; %d dependencies are still "
                           "missing" % (rounds_run, len(remaining)))
        else:
            out["note"] = ("%d dependencies are still missing and nothing on "
                           "the index offers them" % len(remaining))
    return to_json_safe(out)


def auto_download(opener, engine, repo: str, asset_id: int, filename: str,
                  *, max_bytes=download.DEFAULT_MAX_BYTES,
                  timeout=download.DEFAULT_TIMEOUT) -> dict:
    """Fetch one GitHub asset into the engine's inbox; the caller verifies it.

    Kept separate from :func:`github_source.resolve_asset` usage elsewhere so
    this module has exactly one network write path to reason about.
    """
    from . import github_source
    owner, _, name = str(repo).partition("/")
    if not owner or not name:
        return _fail("DL_BAD_URL", "repo must be owner/name")
    resolved = github_source.resolve_asset(opener, owner, name, int(asset_id),
                                           timeout=timeout)
    if not resolved.get("ok"):
        return resolved
    url = str(resolved.get("url") or "")
    inbox = _inbox_dir(engine)
    got = download.download_to_inbox(
        opener, url, "", inbox, filename,
        max_bytes=max_bytes, timeout=timeout,
        allowed_hosts=github_source.ASSET_HOSTS)
    if not got.get("ok"):
        return got
    try:
        path = _inbox_path(engine, filename)
    except ModError as e:
        return _fail(e.code, e.detail or "")
    return _ok(path=path, url=url)


def _inbox_dir(engine) -> str:
    from . import auto_import
    return auto_import._inbox_dir(engine)
