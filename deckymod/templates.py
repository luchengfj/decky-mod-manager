"""Read-only Mod-directory templates for games the plugin recognises (standard 4).

Why this module exists: the goal requires at least two real games beyond
Stardew Valley to have their Mod-directory convention *identified on the
device*, and games with no template to be told "not adapted" instead of having
a path guessed for them.

This layer is IDENTIFICATION ONLY. It never writes, never creates directories,
and never claims a second writable engine. ``max_enabled_games_in_mvp`` stays 1,
only Stardew Valley is operable, and there is still no universal one-click
install. Templates simply answer: "if this game had mods, where would they go,
and is that directory actually present here?"

The two non-Stardew templates were verified on the Deck on 2026-11-16:

* 1091500 Cyberpunk 2077 -> ``archive/pc/content`` exists with 34 entries
  (the real REDmod / WolvenKit archive location).
* 1868140 DAVE THE DIVER -> ``BepInEx/plugins`` is the Unity IL2CPP convention;
  the game root and its ``DaveTheDiver_Data`` directory exist on the device,
  while BepInEx itself is not installed (so the candidate reports exists=False).

Warframe (230410) is deliberately left without a template and is used as the
"not adapted" control case.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

# AppID -> read-only template. ``mod_dirs`` are /-separated paths relative to the
# game's install_path. ``writable`` is False for every identification-only
# template: recognition must never be mistaken for write capability.
_TEMPLATES: Dict[int, Dict[str, object]] = {
    413150: {
        "name": "Stardew Valley",
        "mod_dirs": ["Mods"],
        "loader": "SMAPI",
        "writable": True,
        "search_hint": "stardew valley mod",
    },
    1091500: {
        "name": "Cyberpunk 2077",
        "mod_dirs": ["archive/pc/content"],
        "loader": "REDmod / WolvenKit",
        "writable": False,
        "search_hint": "cyberpunk 2077 mod",
    },
    1868140: {
        "name": "DAVE THE DIVER",
        "mod_dirs": ["BepInEx/plugins"],
        "loader": "BepInEx (IL2CPP)",
        "writable": False,
        "search_hint": "dave the diver mod",
    },
}


def known_appids() -> List[int]:
    """Sorted AppIDs with a template (handy for tests and the UI note)."""
    return sorted(_TEMPLATES)


def _as_appid(value: object) -> Optional[int]:
    try:
        if isinstance(value, bool):
            return None
        ivalue = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return ivalue


MAX_MODS_PER_DIR = 200


def scan_mods(appid: object, install_path: str = "") -> Dict[str, object]:
    """List what is already sitting in a recognised game's Mod directory.

    Round 37: the plugin's own list only knows what IT installed, so a game the
    user modded by hand showed zero. This reader answers "which folders are in
    this game's Mod directory right now" without writing, creating, or moving
    anything, and without inventing a path for a game that has no template.

    Each entry is a directory name. Files directly in the Mod directory are not
    listed: every loader this plugin knows about organises mods as one folder
    per mod, and guessing at loose-file layouts would produce a list the user
    cannot act on.
    """
    info = identify(appid, install_path)
    total = 0
    for entry in info["mod_dirs"]:  # type: ignore[union-attr]
        names: List[str] = []
        truncated = False
        path = str(entry.get("path") or "")
        if entry.get("exists") and path:
            try:
                for name in sorted(os.listdir(path)):
                    if name.startswith("."):
                        # Loaders ignore dot-directories; listing them would
                        # show the plugin's own staging/quarantine bookkeeping
                        # as if it were user content.
                        continue
                    if len(names) >= MAX_MODS_PER_DIR:
                        truncated = True
                        break
                    if os.path.isdir(os.path.join(path, name)):
                        names.append(name)
            except OSError:
                # An unreadable directory is reported as empty rather than
                # failing the whole listing: one bad game must not blank the UI.
                names = []
        entry["mods"] = names
        entry["count"] = len(names)
        entry["truncated"] = truncated
        total += len(names)
    info["total_mods"] = total
    return info


def identify(appid: object, install_path: str = "") -> Dict[str, object]:
    """Describe a game's Mod directory without touching it.

    Returns a JSON-safe dict:

    * ``adapted`` False -> no template; ``note="not_adapted"``. The caller must
      show an explicit "not adapted" message and must NOT guess a path.
    * ``adapted`` True -> ``mod_dirs`` is a list of
      ``{"path", "exists"}`` entries, ``loader`` names the expected loader, and
      ``writable`` tells the UI whether this is an operable (engine-backed) game.
    """
    aid = _as_appid(appid)
    template = _TEMPLATES.get(aid) if aid is not None else None
    if template is None:
        return {"adapted": False, "appid": aid, "mod_dirs": [], "loader": None,
                "writable": False, "note": "not_adapted", "search_hint": None}

    dirs: List[Dict[str, object]] = []
    for rel in list(template["mod_dirs"]):  # type: ignore[arg-type]
        parts = str(rel).split("/")
        candidate = os.path.join(install_path, *parts) if install_path else ""
        dirs.append({
            "path": candidate,
            "exists": bool(candidate and os.path.isdir(candidate)),
        })

    return {
        "adapted": True,
        "appid": aid,
        "name": template["name"],
        "mod_dirs": dirs,
        "loader": template["loader"],
        "writable": bool(template["writable"]),
        "note": "writable" if template["writable"] else "identification_only",
        # Round 36: what to type into the GitHub search box to find this
        # game's mods. Metadata only -- nothing here reads or writes a game
        # directory, and a game without a template gets None (no guessing).
        "search_hint": template.get("search_hint"),
    }
