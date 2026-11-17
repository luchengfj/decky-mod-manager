"""Audit the quarantine: what is in it, and what can still be restored (read-only).

Uninstalling a mod moves its folder to ``GAME_ROOT/.decky-quarantine/<txn>/``
rather than deleting it, so "uninstall" is really "keep it, out of the way".
Rollback restores such a folder only if the journal still holds the
``MOD_UNINSTALLED`` record for that transaction — the record carries both the
original path and the quarantine path.

That means a quarantine folder can become **unreachable data**: it occupies
space, the user believes it is recoverable, and no code path can ever bring it
back. Measured on the device, that is not hypothetical:

    QUARANTINE_DIRS 45
    REFERENCED_BY_JOURNAL 16
    ORPHANS 29          (13 of them empty)
    ORPHAN 20261115T144322-65429fcd children=1 bytes=114308

One orphan held a real mod. The honest response is to *report* this, not to
silently delete anything: a plugin that cleans up folders it did not create is
one bug away from deleting a mod the user wanted.

Design constraints, same as the rest of the read path:

* **Read-only.** Nothing is created, moved or deleted here. Ever.
* **Bounded.** At most ``MAX_DIRS`` transaction folders are walked, and the
  per-folder walk stops at ``MAX_FILES``. A quarantine is not worth a slow
  status() call.
* **Never guesses.** If the journal cannot be read, every folder is reported as
  ``unknown`` rather than as an orphan -- "I cannot tell" and "nobody claims
  this" are different answers and only one of them is safe.
* **Symlinks are not followed** when sizing, for the same reason the rest of
  the read path refuses them: a link points at data this scan does not own.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

MAX_DIRS = 200
MAX_FILES = 5000

RESTORABLE = "restorable"
ORPHAN = "orphan"
UNKNOWN = "unknown"


def _size_of(path: str, max_files: int = MAX_FILES) -> tuple:
    """(bytes, files, truncated) for one folder, without following symlinks."""
    total = 0
    files = 0
    truncated = False
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            if os.path.islink(full):
                continue
            try:
                total += os.path.getsize(full)
            except OSError:
                continue
            files += 1
            if files >= max_files:
                return total, files, True
    return total, files, truncated


def referenced_txns(journal) -> Optional[set]:
    """Transaction ids the journal can still roll back to.

    Returns ``None`` when the journal cannot be read at all: the caller must
    then report ``unknown`` instead of calling every folder an orphan.
    """
    if journal is None:
        return None
    try:
        records = journal.read_all()
    except Exception:
        return None
    if not isinstance(records, list):
        return None
    out = set()
    for r in records:
        if not isinstance(r, dict):
            continue
        if r.get("event") != "MOD_UNINSTALLED":
            continue
        txn = r.get("txn")
        if txn:
            out.add(str(txn))
    return out


def survey(quarantine_root: str, journal=None, cfg: dict | None = None) -> dict:
    """Describe the quarantine contents and which folders are still restorable."""
    cfg = cfg or {}
    if cfg.get("enabled") is False:
        return {"checked": False, "reason": "disabled_in_descriptor",
                "entries": [], "total_bytes": 0, "dirs": 0,
                "restorable": 0, "orphans": 0, "empty": 0}

    if not quarantine_root or not os.path.isdir(quarantine_root):
        return {"checked": True, "exists": False, "entries": [],
                "total_bytes": 0, "dirs": 0, "restorable": 0, "orphans": 0,
                "empty": 0, "reason": "quarantine_missing"}

    known = referenced_txns(journal)
    journal_state = "readable" if known is not None else "unreadable"

    dirs: List[dict] = []
    truncated = False
    try:
        names = sorted(os.listdir(quarantine_root))
    except OSError as exc:
        return {"checked": False, "reason": "list_failed",
                "detail": "%s: %s" % (exc.__class__.__name__, exc),
                "entries": [], "total_bytes": 0, "dirs": 0,
                "restorable": 0, "orphans": 0, "empty": 0}

    total_bytes = 0
    restorable = orphans = empty = 0
    for name in names:
        if len(dirs) >= int(cfg.get("max_dirs") or MAX_DIRS):
            truncated = True
            break
        full = os.path.join(quarantine_root, name)
        if os.path.islink(full) or not os.path.isdir(full):
            continue
        try:
            children = os.listdir(full)
        except OSError:
            children = []
        n_bytes, n_files, cut = _size_of(full)
        if cut:
            truncated = True
        total_bytes += n_bytes
        if not children:
            empty += 1

        if known is None:
            state = UNKNOWN
        elif name in known:
            state = RESTORABLE
        else:
            state = ORPHAN
        if state == RESTORABLE:
            restorable += 1
        elif state == ORPHAN:
            orphans += 1

        dirs.append({
            "txn": name,
            "state": state,
            "children": len(children),
            "files": n_files,
            "bytes": n_bytes,
            "restorable": state == RESTORABLE,
        })

    # Orphans that actually hold something first: an empty orphan is clutter,
    # an orphan with a mod in it is the case worth telling the user about.
    dirs.sort(key=lambda d: (d["state"] != ORPHAN, -d["bytes"], d["txn"]))
    return {
        "checked": True,
        "exists": True,
        "journal": journal_state,
        "entries": dirs,
        "dirs": len(dirs),
        "total_bytes": total_bytes,
        "restorable": restorable,
        "orphans": orphans,
        "empty": empty,
        "truncated": truncated,
    }


def describe(result: dict, limit: int = 2) -> str:
    """One line for the panel, or "" when there is nothing worth saying."""
    if not result.get("checked"):
        return ""
    held = [d for d in result.get("entries") or [] if d.get("state") == ORPHAN and d.get("bytes")]
    if not held:
        return ""
    parts = ["%s (%d B)" % (d["txn"], d["bytes"]) for d in held[:limit]]
    text = "%d quarantine folder(s) no longer restorable: %s" % (
        len(held), ", ".join(parts))
    if len(held) > limit:
        text += " (+%d more)" % (len(held) - limit)
    return text
