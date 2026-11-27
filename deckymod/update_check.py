"""Tell the user which installed mods have a newer version published.

Why this exists
---------------
Round 67 answers "is a DEPENDENCY too old". Nothing answered the other
question a mod user actually asks: *is there a new version of the thing I
installed*. `docs/NEXT_FEATURES.md` P2#8 recorded it as missing, and the honest
reason it is not trivial is that the plugin has no right to guess a version:

* A mod's `UpdateKeys` gives a ``nexus:<id>`` — that is a fact the author wrote.
  A mod with no key has no known page, and saying "up to date" about it would be
  a lie of the same shape Round 40 removed from the panel.
* Nexus free accounts cannot download (403 by policy), so this module only ever
  REPORTS. It never fetches, never queues, never touches the mod folder.
* A version string is not a number. ``_version_tuple`` already exists for the
  dependency check and is reused here so both answers compare the same way;
  a version with no digits yields "cannot tell", never "older".

So the shape is: for every installed mod that declares a Nexus id, ask the API
what the newest file's version is, compare, and answer in four states --
``current``, ``outdated``, ``unknown`` (no key / no readable version), and
``error`` (the API refused or the network failed). ``unknown`` is never merged
into ``current``.
"""
from __future__ import annotations

import os

from . import manifest, nexus, updatekeys

#: Never ask the API about more than this many mods in one pass. The Nexus API
#: is rate limited per hour and a 30-mod library would burn the whole budget on
#: a single tap; the cap is reported, not silently applied.
MAX_CHECKS = 25

#: The states this module can return. Kept as constants so the panel and the
#: tests cannot drift on a string literal.
STATE_CURRENT = "current"
STATE_OUTDATED = "outdated"
STATE_UNKNOWN = "unknown"
STATE_ERROR = "error"


def _fail(code: str, detail: str = "", **extra) -> dict:
    out = {"ok": False, "code": code, "detail": detail}
    out.update(extra)
    return out


def _ok(**kw) -> dict:
    out = {"ok": True, "code": None, "detail": ""}
    out.update(kw)
    return out


def nexus_ids(mods) -> dict:
    """Map ``nexus mod id -> [uniqueId, ...]`` from the mods the scan returned.

    One API call per id, not per mod: two mods in one package (a framework and
    its content) legitimately share an id, and asking twice would waste a
    request from a 60/hour budget.
    """
    out: dict = {}
    for row in mods or ():
        uid = str(row.get("uniqueId") or "")
        for key in row.get("update_keys") or ():
            if str(key.get("site") or "").lower() != "nexus":
                continue
            ident = str(key.get("id") or "").strip()
            if not ident.isdigit():
                # A non-numeric Nexus id is not one; dropping it keeps a
                # malformed key from becoming a 404 that reads as "not found".
                continue
            out.setdefault(ident, [])
            if uid and uid not in out[ident]:
                out[ident].append(uid)
    return out


def _newest_version(files) -> str:
    """The version of the most recently uploaded file, or "".

    ``mod_files`` returns every file the author uploaded, including old ones.
    Picking by ``uploaded_timestamp`` (not by sorting version strings) is what
    makes "the newest release" mean what the author means; ``mod_version`` is
    preferred over ``version`` because that is the mod's own version rather than
    the file's packaging revision.
    """
    best = None
    best_ts = -1
    for row in files or ():
        if not isinstance(row, dict):
            continue
        try:
            ts = int(row.get("uploaded_timestamp") or 0)
        except (TypeError, ValueError):
            ts = 0
        if ts < best_ts:
            continue
        ver = str(row.get("mod_version") or row.get("version") or "").strip()
        if not ver:
            continue
        best_ts = ts
        best = ver
    return best or ""


def compare(installed, latest) -> str:
    """One of the four states for a pair of version strings.

    ``_version_tuple`` returns () for "no digits", which must read as unknown:
    the same rule the dependency check uses (round 67) and the same reason --
    a version we cannot parse is not evidence of anything.
    """
    have = manifest._version_tuple(installed)
    want = manifest._version_tuple(latest)
    if not have or not want:
        return STATE_UNKNOWN
    if have < want:
        return STATE_OUTDATED
    return STATE_CURRENT


def check(opener, mods, *, api_key: str, game_domain: str,
          timeout: float = nexus.TIMEOUT) -> dict:
    """Ask Nexus for the newest version of every mod that declares an id.

    ``mods`` is the ``mods`` list from ``manifest.scan_installed_mods``. Nothing
    is written, no archive is opened, and no download is attempted — the caller
    already knows a free account cannot download.

    Returns::

        {"ok": True, "checked": int, "skipped": int, "rows": [...],
         "outdated": [uniqueId...], "errors": {id: code}}
    """
    by_id = nexus_ids(mods)
    if not by_id:
        return _ok(checked=0, skipped=len(mods or ()), rows=[], outdated=[],
                   errors={}, note="no installed mod declares a Nexus id")

    ids = sorted(by_id.keys(), key=lambda s: int(s))[:MAX_CHECKS]
    truncated = max(0, len(by_id) - len(ids))

    rows = []
    errors = {}
    outdated = []
    for ident in ids:
        uids = by_id[ident]
        res = nexus.mod_files(opener, game_domain, int(ident), api_key,
                              timeout=timeout)
        if not res.get("ok"):
            code = str(res.get("code") or "DL_HTTP")
            errors[ident] = code
            for uid in uids:
                rows.append({"uniqueId": uid, "nexusId": ident,
                             "installed": _installed_version(mods, uid),
                             "latest": "", "state": STATE_ERROR,
                             "reason": code})
            continue
        latest = _newest_version(res.get("files"))
        for uid in uids:
            have = _installed_version(mods, uid)
            state = compare(have, latest)
            rows.append({"uniqueId": uid, "nexusId": ident,
                         "installed": have, "latest": latest,
                         "state": state, "reason": ""})
            if state == STATE_OUTDATED:
                outdated.append(uid)

    return _ok(checked=len(ids), skipped=truncated, rows=rows,
               outdated=outdated, errors=errors,
               note=("only the first %d mods were checked; Nexus rate limits "
                     "a free key per hour" % MAX_CHECKS) if truncated else "")


def _installed_version(mods, uid: str) -> str:
    for row in mods or ():
        if str(row.get("uniqueId") or "") == uid:
            return str(row.get("version") or "")
    return ""


def summary(rows) -> str:
    """A one-line answer for the panel, or "" when there is nothing to say."""
    n_out = sum(1 for r in rows or () if r.get("state") == STATE_OUTDATED)
    n_cur = sum(1 for r in rows or () if r.get("state") == STATE_CURRENT)
    n_unk = sum(1 for r in rows or () if r.get("state") == STATE_UNKNOWN)
    n_err = sum(1 for r in rows or () if r.get("state") == STATE_ERROR)
    if not rows:
        return ""
    parts = []
    if n_out:
        parts.append("%d outdated" % n_out)
    if n_cur:
        parts.append("%d current" % n_cur)
    if n_unk:
        parts.append("%d unknown" % n_unk)
    if n_err:
        parts.append("%d failed" % n_err)
    return ", ".join(parts)
