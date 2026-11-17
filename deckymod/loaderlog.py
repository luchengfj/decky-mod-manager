"""Read the game loader's own log: what actually loaded, versus what is merely on disk.

Why this module exists (``docs/NEXT_FEATURES.md`` item 4): every other part of the
plugin answers "what is in ``Mods/``". None of it answers "what did the game
actually accept". Those are different questions, and the difference is not
academic -- a device run on 2026-11-17 showed 30 mod folders on disk against 22
loaded mods plus 3 content packs, with 4 folders skipped and failure reasons that
only the log knows:

    [18:42:08 ERROR SMAPI]       - (CP) Laundry Machines 1.1.0 because it requires
                                 mods which aren't installed (hxw.tilesheets,
                                 selph.ExtraMachineConfig, selph.FurnitureMachine).
    [18:42:08 ERROR SMAPI]       - Xiddav's Little Red School House 2.3.0 because it
                                 requires mods which aren't installed (Xiddav.tilesheet).

A user who installs a mod, sees it in the panel, and finds it silent in game has
no way to discover "it was skipped because a dependency is missing" from the
plugin. This module closes that gap.

Design constraints, all of which shaped the code below:

  * **Read-only, always.** This never writes, never renames, never fixes a skip.
    Reporting is the whole feature. A parser that "helped" by editing a manifest
    would be a second write path with none of the transaction machinery.
  * **Descriptor-driven, no game literals.** Every pattern, every candidate path
    and the marker string come from the descriptor's ``loader_detection.loader_log``
    block. There is no ``if game ==`` and no loader name constant in the parser.
  * **Fail soft.** A log that is absent, huge, truncated mid-line, or written in an
    unknown dialect yields ``{"ok": False, "reason": ...}``. It must never raise
    into ``status()``, because a missing log is the normal state before the game
    has ever been launched.
  * **Bounded.** ``MAX_LOG_BYTES`` caps the read; a verbose developer-mode log on a
    long play session is megabytes. ``MAX_REPORTED`` caps the row count so a
    pathological log cannot inflate the JSON envelope past what the bridge and the
    Quick Access panel can render.
  * **No invention.** A mod in ``Mods/`` that does not appear in either the loaded
    or the skipped section is reported as ``unknown``, not assumed to work. The log
    only proves what it lists.

**Not an error path.** This module deliberately reports a *reason string*, never an
``E_*`` code. ``deckymod/errors.py`` is a reviewed, closed set of 50 codes that the
frontend has translations for; "the log does not exist yet" is not a user-facing
failure -- it is the state of every device before the first launch. Inventing a
code for it would either grow that set or lie about the category.
"""

from __future__ import annotations

import os
import re

#: A developer-mode log grows fast. 4 MiB is far past any real summary block while
#: still bounded enough to parse inside a QAM panel open.
MAX_LOG_BYTES = 4 * 1024 * 1024

#: Reporting cap per category. The summary block lists every mod, so this only
#: matters when someone points the parser at a log that is not a loader log.
MAX_REPORTED = 500

#: Characters kept from a log line when echoing it back as evidence.
MAX_LINE = 300


def _fail(reason: str, detail: str = "") -> dict:
    return {"ok": False, "reason": reason, "detail": detail}


def _ok(**kw) -> dict:
    d = {"ok": True}
    d.update(kw)
    return d


# ---------------------------------------------------------------- paths

def candidate_paths(game_root: str, user_home: str, xdg_config: str, cfg: dict) -> list:
    """Expand the descriptor's ``candidates`` into concrete absolute paths.

    Templates are ``${GAME_ROOT}``, ``${USER_HOME}`` and ``${XDG_CONFIG}``. An
    unknown token is left literal rather than silently dropped: a typo in a
    descriptor should be visible, not silently produce a path that cannot exist.
    """
    subs = {"${GAME_ROOT}": game_root or "",
            "${USER_HOME}": user_home or "",
            "${XDG_CONFIG}": xdg_config or ""}
    out = []
    for tpl in (cfg.get("candidates") or []):
        p = str(tpl)
        for k, v in subs.items():
            p = p.replace(k, v)
        out.append(p)
    return out


def find_log(paths: list) -> dict:
    """Return the first existing candidate, plus every candidate and why it missed.

    Returns the *first present* file, not the newest: the descriptor lists
    candidates in preference order, and two live logs would mean two installs,
    which is a fact the caller should see rather than a race to resolve here.
    """
    tried = []
    for p in paths:
        row = {"path": p}
        try:
            st = os.stat(p)
        except OSError as exc:
            row["present"] = False
            row["error"] = exc.__class__.__name__
            tried.append(row)
            continue
        if not os.path.isfile(p):
            row["present"] = False
            row["error"] = "not a regular file"
            tried.append(row)
            continue
        row["present"] = True
        row["size"] = st.st_size
        row["mtime"] = int(st.st_mtime)
        tried.append(row)
        return _ok(path=p, size=st.st_size, mtime=int(st.st_mtime), tried=tried)
    return _fail("log_missing", "; ".join(t["path"] for t in tried) or "no candidates")


def read_log(path: str, limit: int = MAX_LOG_BYTES) -> dict:
    """Read at most ``limit`` bytes from the START of the log.

    The summary block sits near the top, not the end, so reading the tail would
    miss it. The file can still be gigantic, hence the cap; when the cap bites, the
    trailing partial line is dropped rather than parsed as half a row.
    """
    try:
        with open(path, "rb") as f:
            raw = f.read(limit + 1)
    except OSError as exc:
        return _fail("log_unreadable", f"{exc.__class__.__name__}: {exc}")
    truncated = len(raw) > limit
    if truncated:
        raw = raw[:limit]
    text = raw.decode("utf-8", errors="replace")
    if truncated:
        cut = text.rfind("\n")
        if cut > 0:
            text = text[:cut]
    return _ok(text=text, truncated=truncated)


# ---------------------------------------------------------------- parsing

def _compile(key: str, cfg: dict):
    pat = cfg.get(key)
    if not pat:
        return None
    try:
        return re.compile(pat)
    except re.error:
        return None


def _clip(s) -> str:
    s = " ".join(str(s or "").split())
    return s[:MAX_LINE]


def parse(text: str, cfg: dict) -> dict:
    """Parse a loader log into loaded / content packs / skipped / patched.

    Sections are delimited by header lines, not line numbers, because a mod name
    containing "Loaded" or a path containing "Mods" must not shift the parse. One
    pass with a small state machine: ``current`` names the section the last header
    opened, and a row that matches nothing in that section is ignored.
    """
    hdr_loaded = _compile("loaded_header", cfg)
    row_loaded = _compile("loaded_row", cfg)
    hdr_packs = _compile("content_pack_header", cfg)
    hdr_skipped = _compile("skipped_header", cfg)
    row_skipped = _compile("skipped_row", cfg)
    hdr_patched = _compile("patched_header", cfg)
    row_patched = _compile("patched_row", cfg)
    skip_reason_ids = _compile("skipped_missing_ids", cfg)

    if row_loaded is None:
        return _fail("log_unparsed", "descriptor has no loader_log.loaded_row")

    loaded, packs, skipped, patched = [], [], [], []
    current = None
    counts = {}
    for line in text.splitlines():
        if hdr_loaded is not None:
            m = hdr_loaded.search(line)
            if m:
                current = "loaded"
                try:
                    counts["loaded"] = int(m.group(1))
                except (IndexError, ValueError):
                    pass
                continue
        if hdr_packs is not None:
            m = hdr_packs.search(line)
            if m:
                current = "packs"
                try:
                    counts["content_packs"] = int(m.group(1))
                except (IndexError, ValueError):
                    pass
                continue
        if hdr_skipped is not None and hdr_skipped.search(line):
            current = "skipped"
            continue
        if hdr_patched is not None and hdr_patched.search(line):
            current = "patched"
            continue
        if current == "loaded":
            m = row_loaded.search(line)
            if m:
                gd = m.groupdict()
                loaded.append({"name": _clip(gd.get("name")),
                               "version": _clip(gd.get("version")),
                               "author": _clip(gd.get("author")),
                               "summary": _clip(gd.get("summary"))})
                continue
        if current == "packs":
            m = row_loaded.search(line)
            if m:
                gd = m.groupdict()
                packs.append({"name": _clip(gd.get("name")),
                              "version": _clip(gd.get("version")),
                              "author": _clip(gd.get("author")),
                              "summary": _clip(gd.get("summary"))})
                continue
        if current == "skipped":
            if row_skipped is None:
                continue
            m = row_skipped.search(line)
            if m:
                gd = m.groupdict()
                reason = _clip(gd.get("reason"))
                ids = []
                if skip_reason_ids is not None:
                    mm = skip_reason_ids.search(reason)
                    if mm:
                        ids = [x.strip() for x in mm.group(1).split(",") if x.strip()]
                skipped.append({"name": _clip(gd.get("name")),
                                "version": _clip(gd.get("version")),
                                "reason": reason,
                                "missing_ids": ids})
                continue
        if current == "patched":
            if row_patched is None:
                continue
            m = row_patched.search(line)
            if m:
                gd = m.groupdict()
                patched.append({"name": _clip(gd.get("name"))})
                continue
    return _ok(counts=counts,
               loaded=loaded[:MAX_REPORTED],
               content_packs=packs[:MAX_REPORTED],
               skipped=skipped[:MAX_REPORTED],
               patched=patched[:MAX_REPORTED])


# ---------------------------------------------------------------- correlation

def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


def annotate(mods: list, report: dict) -> list:
    """Attach ``load_status`` to each installed mod directory.

    Matching is by normalized display name first, then by the same normalization of
    the directory name. That order matters: the log prints the manifest's ``Name``
    ("Better Ranching"), while a folder is often the id tail ("BetterRanching").
    Normalizing both and comparing is the only rule that survives both spellings
    without a per-game lookup table.

    A mod absent from every section is ``unknown`` with an explicit note. It is NOT
    reported as working: the log only proves what it lists, and the most common
    cause of absence is that the log predates the install.

    Two details a real log forced (both were silent mismatches before):
      * the scan gives us ``dir`` (there is no ``dir_name`` key), so the folder
        fallback must read ``dir`` or it never matches anything;
      * SMAPI reports a skipped *subfolder* as ``LookupAnything/i18n``, which
        normalizes to a different string than the folder ``LookupAnything``. A
        row whose name contains "/" therefore also offers its first segment as a
        key, which is what the loader means by that syntax.
    """
    def _keys(raw) -> list:
        out = [_norm(raw)]
        if isinstance(raw, str) and "/" in raw:
            head = raw.split("/", 1)[0]
            out.append(_norm(head))
        return [k for k in out if k]

    if not report or not report.get("ok"):
        return [dict(m, load_status="unknown", load_note="no log to compare against")
                for m in mods]

    by_name = {}
    for row in (report.get("loaded") or []) + (report.get("content_packs") or []):
        for k in _keys(row.get("name")):
            by_name.setdefault(k, row)
    skip_by_name = {}
    for row in report.get("skipped") or []:
        for k in _keys(row.get("name")):
            skip_by_name.setdefault(k, row)

    out = []
    for m in mods:
        name_key = _norm(m.get("name"))
        dir_key = _norm(m.get("dir") or m.get("dir_name"))
        cands = [k for k in (name_key, dir_key) if k]
        hit = next((by_name[k] for k in cands if k in by_name), None)
        if hit:
            out.append(dict(m, load_status="loaded",
                            load_version=hit.get("version") or "",
                            load_author=hit.get("author") or ""))
            continue
        miss = next((skip_by_name[k] for k in cands if k in skip_by_name), None)
        if miss:
            out.append(dict(m, load_status="skipped",
                            load_reason=miss.get("reason") or "",
                            load_missing_ids=miss.get("missing_ids") or []))
            continue
        out.append(dict(m, load_status="unknown",
                        load_note="not listed in the log (installed after the last launch?)"))
    return out


def summarize(report: dict, mods_annotated: list) -> dict:
    """Compact counts for the panel header."""
    if not report or not report.get("ok"):
        return {"available": False,
                "reason": (report or {}).get("reason") or "no report"}
    counts = report.get("counts") or {}
    return {
        "available": True,
        "loaded": counts.get("loaded", len(report.get("loaded") or [])),
        "content_packs": counts.get("content_packs", len(report.get("content_packs") or [])),
        "skipped": len(report.get("skipped") or []),
        "patched": len(report.get("patched") or []),
        "unknown": sum(1 for m in mods_annotated if m.get("load_status") == "unknown"),
        "truncated": bool(report.get("truncated")),
    }


def inspect(game_root: str, user_home: str, xdg_config: str, cfg: dict,
            mods: list) -> dict:
    """One call for the engine: find, read, parse, correlate. Never raises.

    Returns ``{"ok": True, "report", "mods", "summary"}`` or
    ``{"ok": False, "reason", "detail"}``. Runs inside ``status()``, so a missing
    log -- the normal state before the first launch -- must be a value, not a throw.
    """
    if not cfg or not cfg.get("enabled"):
        return _fail("not_configured", "descriptor declares no loader_log")
    if not (cfg.get("candidates") or []):
        return _fail("log_unparsed", "descriptor declares no loader_log.candidates")
    try:
        paths = candidate_paths(game_root, user_home, xdg_config, cfg)
        found = find_log(paths)
        if not found.get("ok"):
            return found
        got = read_log(found["path"])
        if not got.get("ok"):
            return got
        report = parse(got["text"], cfg)
        if not report.get("ok"):
            return report
        # A readable file with no recognisable section is NOT a log we understand.
        # Reporting it as "available, 0 loaded" would read to a user as "every mod
        # failed", which is a much worse lie than admitting we could not parse it.
        # An empty log (game never launched) lands here too, and that is correct:
        # absence of evidence must not be dressed up as evidence of absence.
        if not report.get("counts") and not any(report.get(k) for k in
                                                ("loaded", "content_packs",
                                                 "skipped", "patched")):
            return _fail("log_unrecognized",
                         "%d bytes read, no loader summary section found" % len(got["text"]))
    except Exception as exc:                      # noqa: BLE001 - status must survive
        return _fail("log_unreadable", f"{exc.__class__.__name__}: {exc}")
    report["path"] = found["path"]
    report["size"] = found.get("size")
    report["mtime"] = found.get("mtime")
    report["truncated"] = got.get("truncated")
    annotated = annotate(mods or [], report)
    return _ok(report=report, mods=annotated, summary=summarize(report, annotated))
