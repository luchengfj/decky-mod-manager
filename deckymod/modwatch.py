"""Detect a *foreign* deployment of the mod folder, without trusting markers.

Round 44. `docs/NEXT_FEATURES.md` P0 item 1 said the second-writer check is
"Stardew-specific and marker-based": it looked for Amethyst's `.mm_deployed` and
`Mods_Core/`. Every other mod manager — and Amethyst itself after the user flips
one of its switches — is invisible, so the plugin would happily write into a tree
that another program owns and believes it succeeded.

The marker list is the wrong shape of fix: it can only ever recognise the tools
somebody thought of. The *layout* is the durable signal, and it is observable
with `lstat` alone:

1. `Mods/` is itself a symlink. A manager that keeps the real folder elsewhere
   and links it into the game root (Amethyst's VFS mode, `stow`, hand-rolled
   setups) always shows this. Writing through it mutates a tree whose lifecycle
   is owned by somebody else, and uninstalling by `rmtree` would delete through
   the link.
2. An entry *inside* `Mods/` is a symlink. Same story one level down; this is
   what a deployed-per-mod VFS looks like, and it is also how a user "installs"
   a mod they keep on another disk. Either way the plugin must not move, rename
   or remove that entry — `os.replace` on a symlink moves the link, but a later
   `rmtree` of the *target* is one bug away.
3. `Mods/` lives on a different device than the game root. This is the honest
   generalisation of the microSD case: a mod folder bind-mounted or on another
   filesystem cannot be atomically replaced from the plugin's staging directory,
   and it is a configuration the user built outside this plugin.

False positives matter as much as misses: a user who hand-copies folders into
`Mods/` must keep working, and on the reference device all 30 folders are plain
directories on the same filesystem. So nothing here inspects mtimes, names, or
counts — only the three structural facts above, each of which has exactly one
explanation.

This module is read-only and stdlib-only. It never creates, follows or fixes
anything: `os.lstat` on the directory itself, `os.scandir` with
`follow_symlinks=False` for the entries.
"""

from __future__ import annotations

import os

#: Reason codes, stable strings on the wire (the UI maps them to sentences).
R_MODS_SYMLINK = "mods_dir_is_symlink"
R_SYMLINKED_ENTRY = "symlinked_entry"
R_OTHER_DEVICE = "mods_on_other_device"
R_MODS_MISSING = "mods_dir_missing"

#: Human-readable explanation for each reason, used in error details.
_EXPLAIN = {
    R_MODS_SYMLINK: "the mod folder is a symlink, so another tool owns the real one",
    R_SYMLINKED_ENTRY: "the mod folder contains symlinked entries (a deployed mod tree)",
    R_OTHER_DEVICE: "the mod folder is on a different filesystem than the game",
    R_MODS_MISSING: "the mod folder does not exist yet",
}

#: Caps how many entry names are returned, so a 5000-folder Mods/ cannot inflate
#: an error message or a status payload. The COUNT is always exact.
MAX_NAMED = 20


def _entry_names(names):
    names = sorted(names)
    return names[:MAX_NAMED]


def survey(game_root: str, mod_root: str) -> dict:
    """Structural facts about the mod folder. Never raises, never writes.

    Returns::

        {
          "checked": True,
          "exists": bool,
          "is_symlink": bool,
          "device": int|None,          # mod_root's st_dev
          "game_device": int|None,     # game_root's st_dev
          "entries": int,              # plain child count actually scanned
          "symlinked": [names],        # capped at MAX_NAMED
          "symlinked_count": int,
          "reasons": [code, ...],
          "explain": "sentence, sentence"   # "" when clean
        }

    A directory that cannot be listed is reported as zero entries, not as an
    error: "I could not look" must not be reported as "another tool owns it".
    """
    out = {
        "checked": True, "exists": False, "is_symlink": False,
        "device": None, "game_device": None, "entries": 0,
        "symlinked": [], "symlinked_count": 0,
        "reasons": [], "explain": "",
    }

    try:
        st = os.lstat(mod_root)
        out["exists"] = True
        out["is_symlink"] = os.path.islink(mod_root)
        out["device"] = getattr(st, "st_dev", None)
    except OSError:
        out["reasons"].append(R_MODS_MISSING)
        out["explain"] = _EXPLAIN[R_MODS_MISSING]
        return out

    try:
        gst = os.lstat(game_root)
        out["game_device"] = getattr(gst, "st_dev", None)
    except OSError:
        out["game_device"] = None

    if out["is_symlink"]:
        out["reasons"].append(R_MODS_SYMLINK)

    # Only walk the real directory. Following the symlink would describe the
    # other tool's tree and could be arbitrarily large.
    if not out["is_symlink"]:
        symlinked = []
        count = 0
        try:
            with os.scandir(mod_root) as it:
                for de in it:
                    count += 1
                    try:
                        if de.is_symlink():
                            symlinked.append(de.name)
                    except OSError:
                        continue
        except OSError:
            pass
        out["entries"] = count
        out["symlinked_count"] = len(symlinked)
        out["symlinked"] = _entry_names(symlinked)
        if symlinked:
            out["reasons"].append(R_SYMLINKED_ENTRY)

    if (out["device"] is not None and out["game_device"] is not None
            and out["device"] != out["game_device"]):
        out["reasons"].append(R_OTHER_DEVICE)

    out["explain"] = "; ".join(_EXPLAIN[r] for r in out["reasons"])
    return out


def is_foreign(survey_result: dict) -> bool:
    """True when a write by this plugin would touch somebody else's tree.

    `mods_dir_missing` is deliberately NOT foreign: the plugin creates the
    folder itself on first install, and refusing there would make a clean
    install impossible.
    """
    reasons = set(survey_result.get("reasons") or ())
    reasons.discard(R_MODS_MISSING)
    return bool(reasons)


def describe(survey_result: dict) -> str:
    """A one-line, user-facing explanation of why writes are refused."""
    parts = []
    for r in survey_result.get("reasons") or ():
        if r == R_MODS_MISSING:
            continue
        if r == R_SYMLINKED_ENTRY:
            names = survey_result.get("symlinked") or []
            total = survey_result.get("symlinked_count") or len(names)
            extra = "" if total <= len(names) else " (+%d more)" % (total - len(names))
            parts.append("%s: %s%s" % (_EXPLAIN[r], ", ".join(names), extra))
        else:
            parts.append(_EXPLAIN[r])
    return "; ".join(parts)
