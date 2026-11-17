"""Report mods that ship the same file (read-only).

Two mods that both ship ``X.dll`` — or the same asset path — overwrite each
other, and the result depends on load order. This plugin does not and will not
solve ordering: that needs per-game knowledge it does not have. But "these two
mods fight over the same path" is a fact about the filesystem, needs no game
knowledge, and is the difference between a user finding out here or finding out
when their game crashes.

**Scope is a property of the loader, not of the filesystem.** A *shared-tree*
loader copies every mod's files into one directory, so two mods shipping
``plugins/X.dll`` really do collide. A *per-mod-directory* loader keeps each mod
in its own folder, so ``config.json`` in twenty mods is twenty unrelated files
and reporting it would be 27 false alarms — measured on a real device, which is
exactly what the first version of this module did before the descriptor could
say which model it is. For those loaders the answer is zero shared paths, and
the honest conflict to report is a duplicate mod id, which the manifest scan
already reports.

Design constraints, the same ones the rest of the read path follows:

* **Read-only.** Names are listed, nothing is opened, nothing is written.
* **Descriptor-driven.** The scope and the ignore list live in the game
  descriptor, so the module contains no game-specific literal. Ignore patterns
  are globs (``i18n/*.json``), because a literal wildcard would silently match
  nothing — the second bug the device found.
* **Bounded.** Each mod contributes at most ``max_files_per_mod`` paths and the
  report stops at ``max_conflicts``. A mod with 40 000 textures must not turn
  every status() call into a full disk walk.
* **Never guesses.** A directory that cannot be listed is skipped and counted,
  not treated as "no conflict". Absence of evidence is not evidence of absence.
* **Skips symlinks** for the same reason `modwatch` does: a link points
  somewhere this scan does not own.
"""

from __future__ import annotations

import fnmatch
import os
from typing import Dict, List

MAX_FILES_PER_MOD = 2000
MAX_CONFLICTS = 50

SCOPE_SHARED_TREE = "shared_tree"
SCOPE_PER_MOD_DIR = "per_mod_directory"
DEFAULT_SCOPE = SCOPE_SHARED_TREE

DEFAULT_IGNORE = [
    "manifest.json",
    "about/about.xml",
    "readme.md",
    "readme.txt",
    "changelog.md",
    "license",
    "license.md",
]


def _norm(rel: str) -> str:
    """Comparison key: forward slashes, lowercase.

    Case-insensitive because these files are ultimately consumed by game and
    framework code that resolves paths case-insensitively on Windows and, for
    asset lookups, often on Linux too. Reporting a conflict that is not one is
    cheaper than missing one that is, and the detail shows both original paths.
    """
    return rel.replace("\\", "/").lower()


def _walk_names(root: str, limit: int) -> tuple:
    """Return (relative paths, truncated) for one mod directory.

    Dot-directories are skipped: they are the plugin's own bookkeeping
    (staging/quarantine live as siblings, but a stray one inside a mod folder
    must still not be read).
    """
    out: List[str] = []
    truncated = False
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for fn in sorted(filenames):
                if fn.startswith("."):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, root).replace("\\", "/")
                out.append(rel)
                if len(out) >= limit:
                    return out, True
    except OSError:
        return out, truncated
    return out, truncated


def _ignored(rel: str, ignore: List[str]) -> bool:
    """Match a relative path against glob patterns.

    ``fnmatch`` rather than string equality: the descriptor writes
    ``i18n/*.json``, and the first version compared it literally, so the
    pattern never matched and every mod's translation files were reported as
    conflicts. A pattern that can never match is worse than no pattern.
    """
    key = _norm(rel)
    base = key.rsplit("/", 1)[-1]
    for pat in ignore:
        p = _norm(pat)
        if fnmatch.fnmatchcase(key, p) or fnmatch.fnmatchcase(base, p):
            return True
        if key.endswith("/" + p):
            return True
    return False


def survey(mod_root: str, mods: List[dict], cfg: dict | None = None) -> dict:
    """Find paths shipped by more than one mod.

    ``mods`` is the list `manifest.scan_installed_mods` already produced, so a
    mod that is installed but has an unreadable manifest still participates --
    its directory is what matters here, not its About/manifest fields.

    Returns ``checked: False`` with a ``reason`` when the descriptor says this
    loader keeps mods in separate directories: there is no shared namespace to
    collide in, and reporting twenty ``config.json`` files as conflicts would
    train the user to ignore the line entirely.
    """
    cfg = cfg or {}
    if cfg.get("enabled") is False:
        return {"checked": False, "reason": "disabled_in_descriptor",
                "conflicts": [], "total": 0, "truncated": False, "mods_scanned": 0}
    scope = str(cfg.get("scope") or DEFAULT_SCOPE)
    if scope == SCOPE_PER_MOD_DIR:
        return {"checked": False, "reason": "per_mod_directory_loader",
                "conflicts": [], "total": 0, "truncated": False,
                "mods_scanned": len(mods or [])}
    ignore = list(cfg.get("ignore") or DEFAULT_IGNORE)
    per_mod = int(cfg.get("max_files_per_mod") or MAX_FILES_PER_MOD)
    cap = int(cfg.get("max_conflicts") or MAX_CONFLICTS)

    owners: Dict[str, List[str]] = {}
    display: Dict[str, str] = {}
    scanned = 0
    truncated = False
    skipped = 0

    for m in mods or []:
        name = m.get("dir")
        if not name:
            continue
        path = os.path.join(mod_root, name)
        if os.path.islink(path) or not os.path.isdir(path):
            skipped += 1
            continue
        scanned += 1
        rels, cut = _walk_names(path, per_mod)
        if cut:
            truncated = True
        for rel in rels:
            if _ignored(rel, ignore):
                continue
            key = _norm(rel)
            bucket = owners.setdefault(key, [])
            if name not in bucket:
                bucket.append(name)
            display.setdefault(key, rel)

    conflicts = []
    for key, dirs in owners.items():
        if len(dirs) < 2:
            continue
        conflicts.append({"path": display[key], "mods": sorted(dirs)})
    conflicts.sort(key=lambda c: (-len(c["mods"]), c["path"].lower()))
    if len(conflicts) > cap:
        truncated = True
        conflicts = conflicts[:cap]

    return {
        "checked": True,
        "conflicts": conflicts,
        "total": len(conflicts),
        "truncated": truncated,
        "mods_scanned": scanned,
        "skipped_symlinked": skipped,
    }


def describe(result: dict, limit: int = 3) -> str:
    """One-line summary for the panel / log."""
    if not result.get("checked"):
        return ""
    n = int(result.get("total") or 0)
    if not n:
        return ""
    names = ", ".join(c["path"] for c in result.get("conflicts", [])[:limit])
    if n > limit:
        names += " (+%d more)" % (n - limit)
    return "%d shared path(s): %s" % (n, names)
