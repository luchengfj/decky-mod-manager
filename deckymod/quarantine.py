"""Audit the quarantine, and reclaim folders nothing can restore.

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

One orphan held a real mod. Round 48's response was to *report* this and
delete nothing: a plugin that cleans up folders it did not create is one bug
away from deleting a mod the user wanted.

Round 54 adds the other half, because reporting alone left the user holding
data they could never get rid of. ``reclaim()`` deletes orphans -- only
orphans, only ones the caller names, and only after ``after_confirm``.

Design constraints, same as the rest of the read path:

* **Survey is read-only.** ``survey()`` creates, moves and deletes nothing.
  ``reclaim()`` is the single deliberate exception; nothing else writes.
* **Bounded.** At most ``MAX_DIRS`` transaction folders are walked, and the
  per-folder walk stops at ``MAX_FILES``. A quarantine is not worth a slow
  status() call.
* **Never guesses.** If the journal cannot be read, every folder is reported as
  ``unknown`` rather than as an orphan -- "I cannot tell" and "nobody claims
  this" are different answers and only one of them is safe. ``reclaim()``
  inherits that rule and refuses ``unknown`` outright.
* **Symlinks are not followed** when sizing, for the same reason the rest of
  the read path refuses them: a link points at data this scan does not own.
"""

from __future__ import annotations

import os
import shutil
from typing import Dict, List, Optional

MAX_DIRS = 200
MAX_FILES = 5000
# How many child names one entry reports. Enough to recognise a mod, few enough
# that a 200-folder quarantine is still a small JSON payload.
NAME_PREVIEW = 5

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
    states = {}
    for r in records:
        if not isinstance(r, dict):
            continue
        event = r.get("event")
        # Round 68: an install that displaced a previous copy keeps that copy at
        # <quarantine>/<txn>/<dir>.replaced and can put it back -- measured, not
        # assumed: rollback(txn) restores the old version. Counting only
        # MOD_UNINSTALLED made every such folder an "orphan", and orphans are
        # what reclaim_quarantine is allowed to delete, so the audit was
        # offering to delete the one thing the rollback still needs.
        if event in ("PREPARED", "APPLYING", "COMMITTED", "ROLLED_BACK",
                     "ROLLBACK_FAILED"):
            # An install that crashed between its two renames never reached
            # MOD_INSTALLED, so no record names its displaced copy -- but the
            # copy is sitting in that transaction's folder and rollback() puts it
            # back (round 68). A pending transaction therefore claims its folder
            # until it is finished one way or the other.
            txn = r.get("txn")
            if txn:
                states[str(txn)] = event
            continue
        if event == "MOD_UNINSTALLED":
            pass
        elif event == "MOD_INSTALLED":
            if not r.get("replaced_old"):
                continue
        else:
            continue
        txn = r.get("txn")
        if txn:
            out.add(str(txn))
    # Round 72: a ROLLBACK_FAILED transaction keeps its folder too. The audit
    # called that folder "restorable" while rollback() refused to touch it, and
    # the only remaining copy of the old version was one reclaim away.
    out.update(t for t, s in states.items()
               if s in ("PREPARED", "APPLYING", "ROLLBACK_FAILED"))
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
            # Round 54: the first few names inside, so a confirm dialog can say
            # "this folder holds X" instead of only quoting a byte count. An
            # orphan with 114308 B is abstract; an orphan holding
            # `esca.destroyablebushes` is a decision a person can actually make.
            # Bounded, and never the whole listing.
            "names": sorted(str(c) for c in children)[:NAME_PREVIEW],
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


# --------------------------------------------------------------------- reclaim
def _reclaimable(result: dict) -> Dict[str, dict]:
    """The entries a caller may ask to delete, keyed by txn.

    Round 54: this is the whole safety argument of the reclaim path in one
    function. Only ``orphan`` qualifies. ``restorable`` would throw away a mod
    the user can still get back; ``unknown`` means the journal could not be
    read, and "I cannot tell" must never be spent as "nobody owns this" -- the
    same distinction the audit was built around.
    """
    out: Dict[str, dict] = {}
    for d in result.get("entries") or []:
        if d.get("state") == ORPHAN:
            out[str(d.get("txn"))] = d
    return out


def plan_reclaim(result: dict, txns: List[str]) -> dict:
    """Decide what a reclaim request would do, without touching anything.

    Returns ``{ok, refused, accepted, bytes, files}``. ``refused`` maps txn ->
    reason so the caller can say exactly why a folder was kept instead of
    silently dropping it from the list.
    """
    candidates = _reclaimable(result)
    accepted: List[str] = []
    refused: Dict[str, str] = {}
    total_bytes = 0
    total_files = 0
    seen = set()
    for raw in txns or []:
        txn = str(raw)
        if txn in seen:
            continue
        seen.add(txn)
        if txn not in candidates:
            # Ask why, so the message is the real reason and not "not found".
            hit = next((d for d in result.get("entries") or []
                        if str(d.get("txn")) == txn), None)
            if hit is None:
                refused[txn] = "no such quarantine folder"
            elif hit.get("state") == RESTORABLE:
                refused[txn] = "still restorable with Rollback"
            elif hit.get("state") == UNKNOWN:
                refused[txn] = "journal unreadable, ownership unknown"
            else:
                refused[txn] = "not eligible"
            continue
        accepted.append(txn)
        total_bytes += int(candidates[txn].get("bytes") or 0)
        total_files += int(candidates[txn].get("files") or 0)
    return {
        "ok": True,
        "accepted": accepted,
        "refused": refused,
        "bytes": total_bytes,
        "files": total_files,
    }


def reclaim(quarantine_root: str, txns: List[str], result: dict,
            *, after_confirm: bool = False) -> dict:
    """Delete orphaned quarantine folders, two-phase and never by guess.

    The audit says which folders are unreachable; this is the only way to get
    the disk space back, and it is deliberately the narrowest destructive
    operation in the plugin:

    * the caller must name the transaction ids -- nothing sweeps the directory
      looking for things to delete;
    * ``after_confirm`` must be true, so a single mis-click cannot delete;
    * only ``orphan`` entries qualify (see ``_reclaimable``);
    * symlinked folders and anything that is not a plain directory inside the
      quarantine root are skipped, because this scan does not own what a link
      points at;
    * one failure does not stop the rest, and the result reports both lists.
    """
    plan = plan_reclaim(result, txns)
    if not plan["accepted"]:
        return {
            "ok": True,
            "phase": "nothing",
            "accepted": [],
            "removed": [],
            "failed": {},
            "refused": plan["refused"],
            "bytes": 0,
        }
    if not after_confirm:
        return {
            "ok": True,
            "phase": "confirm",
            "accepted": plan["accepted"],
            "refused": plan["refused"],
            "bytes": plan["bytes"],
            "files": plan["files"],
        }

    removed: List[str] = []
    failed: Dict[str, str] = {}
    freed = 0
    by_txn = _reclaimable(result)
    for txn in plan["accepted"]:
        full = os.path.join(quarantine_root, txn)
        # Re-check the ground under our feet: the survey is a snapshot and the
        # filesystem may have changed since. A link now where a directory was
        # means somebody else is involved.
        if os.path.islink(full):
            failed[txn] = "became a symbolic link; refusing"
            continue
        if not os.path.isdir(full):
            failed[txn] = "already gone"
            continue
        try:
            shutil.rmtree(full)
        except OSError as exc:
            failed[txn] = "%s: %s" % (exc.__class__.__name__, exc)
            continue
        removed.append(txn)
        freed += int(by_txn.get(txn, {}).get("bytes") or 0)

    return {
        "ok": True,
        "phase": "removed",
        "accepted": plan["accepted"],
        "removed": removed,
        "failed": failed,
        "refused": plan["refused"],
        "bytes": freed,
    }
