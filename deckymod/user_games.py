"""Round 77 — user-defined game descriptors.

WHY
---
Built-in descriptors cover games whose mod layout we verified on a device
(Stardew: Mods/; Cyberpunk: archive/pc/mod + framework roots). The user asked
for "every game", and the honest answer for the rest is: the plugin can move
files for ANY game, but only the user knows where that game's loader looks.

So a game the plugin does not ship a descriptor for can be configured once:

    data/games/<appid>.json  ->  {appid, name, write_roots, ...}

and from then on it is managed by the same root_merge engine with the SAME
guarantees: write only inside the declared roots, journal every file, back up
anything replaced.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
It never installs a loader (BepInEx, MelonLoader, UE4SS). A BepInEx mod put in
an empty folder loads nothing; telling the user that is kinder than pretending.
Online games with anti-cheat are refused outright: modding them risks a ban,
which no UI warning can undo.
"""
from __future__ import annotations

import json
import os
import time

from .errors import ModError

# Games where dropping files is not a mod, it is a ban. Checked by display name
# fragment (the only stable key available before an install path exists).
ONLINE_OR_ANTICHEAT = (
    "warframe",
    "elden ring",
    "road to empress",
    "destiny 2",
    "apex legends",
    "counter-strike",
    "valorant",
    "lost ark",
    "new world",
)

# Directory names that are the game's own payload, never a mod root.
_PROTECTED_SEGMENTS = {
    "engine", "binaries", "content", "data", "assets", "resources",
    "monobleedingedge", "monobleedingedge", "d3d12", "swiftshader",
}

# Candidate mod roots, relative to the game folder. Ordered by how common they
# are so the first match is usually right.
CANDIDATES = (
    "BepInEx/plugins",
    "BepInEx",
    "mods",
    "Mods",
    "plugins",
    "mod",
    "Game/Content/Paks/~mods",
    "Content/Paks/~mods",
    "Binaries/Win64/Mods",
)


def data_root() -> str:
    """Where user game configs live (same tree as the journal)."""
    data = os.environ.get("DECKYMOD_DATA") or os.environ.get("DECKY_PLUGIN_RUNTIME_DIR") or ""
    if data and not data.rstrip("/\\").endswith("data"):
        data = os.path.join(data, "data")
    if not data:
        data = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            ".decky-data")
    return os.path.join(data, "games")


def path_for(appid: int) -> str:
    return os.path.join(data_root(), "%d.json" % int(appid))


def _clean_root(value: str) -> str:
    """Normalise and validate one write root. Raises ModError when unsafe."""
    raw = str(value or "").strip().replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    raw = raw.strip("/")
    if not raw:
        raise ModError("E_PATH_INVALID", detail="an empty folder cannot be a mod root")
    parts = raw.split("/")
    if any(p in ("", ".", "..") for p in parts) or ":" in parts[0]:
        raise ModError("E_PATH_INVALID", detail="%r is not a relative folder" % value)
    if len(parts) == 1 and parts[0].lower() in _PROTECTED_SEGMENTS:
        raise ModError("E_NOT_ALLOWED_ROOT",
                       detail="%r is game payload, not a mod folder" % raw)
    return raw


def is_refused_game(name: str) -> bool:
    low = str(name or "").lower()
    return any(frag in low for frag in ONLINE_OR_ANTICHEAT)


def load_all() -> dict:
    """{appid: record}. Unreadable files are skipped, never fatal."""
    out = {}
    root = data_root()
    try:
        names = os.listdir(root)
    except OSError:
        return out
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(root, name), encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict):
            continue
        try:
            appid = int(rec.get("appid"))
        except (TypeError, ValueError):
            continue
        roots = [r for r in (rec.get("write_roots") or []) if isinstance(r, str)]
        if not roots:
            continue
        rec["appid"] = appid
        rec["write_roots"] = roots
        out[appid] = rec
    return out


def save(appid: int, name: str, write_roots, label: str | None = None) -> dict:
    """Create or replace one game's config. Validates every root."""
    try:
        appid = int(appid)
    except (TypeError, ValueError):
        raise ModError("E_PATH_INVALID", detail="appid must be a number")
    pretty = str(name or "").strip() or ("App %d" % appid)
    if is_refused_game(pretty):
        raise ModError("E_NOT_ALLOWED_ROOT",
                       detail="%s is an online game with anti-cheat: modding it "
                              "risks a ban" % pretty)
    roots = []
    for r in (write_roots or []):
        c = _clean_root(r)
        if c.lower() not in [x.lower() for x in roots]:
            roots.append(c)
    if not roots:
        raise ModError("E_PATH_INVALID", detail="at least one mod folder is required")
    rec = {
        "appid": appid,
        "name": pretty,
        "display_label": str(label or "").strip() or pretty,
        "write_roots": roots,
        "engine": "root_merge",
        "source": "user",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    os.makedirs(data_root(), exist_ok=True)
    dest = path_for(appid)
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, dest)
    return rec


def forget(appid: int) -> bool:
    try:
        os.remove(path_for(appid))
        return True
    except OSError:
        return False


def candidate_roots(install_path: str) -> list:
    """Which of the common mod folders already exist, plus the rest as offers."""
    out = []
    for rel in CANDIDATES:
        full = os.path.join(str(install_path or ""), rel.replace("/", os.sep))
        out.append({"path": rel, "exists": bool(install_path) and os.path.isdir(full)})
    return out


def game_id(appid: int) -> str:
    return "user_%d" % int(appid)


def descriptor_for(rec: dict) -> dict:
    """A full descriptor for a user-defined game, shaped like a built-in one."""
    appid = int(rec.get("appid"))
    name = str(rec.get("name") or ("App %d" % appid))
    roots = list(rec.get("write_roots") or [])
    first = roots[0] if roots else "mods"
    return {
        "schema": "deckymod/game-descriptor@1",
        "id": game_id(appid),
        "status": "enabled",
        "engine": "root_merge",
        "display_label": "%s / user folders" % name,
        "user_defined": True,
        "engine_note": "User-defined: the mod folders below were chosen by the "
                       "user. root_merge writes only inside them, journals every "
                       "file and backs up anything it replaces.",
        "identity": {
            "appid": appid,
            "name": name,
            "platform": "user-defined",
            "status": "enabled",
            "note": "Configured in the panel. No loader is installed by this plugin.",
        },
        "paths": {
            "game_root": "${GAME_ROOT}",
            "mod_root": None,
            "write_roots": roots,
            "root_file_target": first,
            "protected": [],
            "protected_note": "Empty on purpose: write_roots alone bounds every "
                              "write, so a path outside them is refused before it "
                              "reaches the disk.",
            "state_file": None,
            "state_staging": None,
            "staging": "${GAME_ROOT}/.decky-staging",
            "quarantine": "${GAME_ROOT}/.decky-quarantine/${TXN_ID}",
            "journal": "${DECKY_DATA}/journal/%s.jsonl" % game_id(appid),
            "snapshots": "${DECKY_DATA}/snapshots/${TXN_ID}",
        },
        "import_roots": [{
            "label": "downloads",
            "path": "${XDG_DOWNLOAD}",
            "note": "Where the Game Mode browser saves files. READ ONLY.",
        }],
        "mod_package": {
            "archive_format": "zip",
            "magic": "504b0304",
            "parser": "path_map",
            # Round 77: user games receive ordinary "MyMod/..." zips, so the
            # shared top folder is the mod's own name and must be kept under the
            # target (BepInEx/plugins/MyMod/MyMod.dll), not flattened.
            "strip_single_root": True,
        },
        "conflict_policy": {"duplicate": "reject_with_replace_option",
                            "file_collision": "backup_then_replace",
                            "case_handling": "case_insensitive_listdir",
                            "symlink_policy": "reject"},
        "capabilities": {
            "local_import": True,
            "detection_only": False,
            "enable_disable": False,
            "uninstall_quarantine": True,
            "rollback": True,
            "atomic_state_write": False,
            "gamepad_only": True,
            "history_refresh": True,
            "loader_install": False,
            "launch_option_edit": False,
            "dll_override": False,
            "proton_prefix_write": False,
            "exe_installer": False,
            "network_download": True,
            "workshop": False,
            "load_order_solver": False,
            "dependency_solver": False,
            "requires_root": False,
            "requires_readonly_toggle": False,
            "universal_one_click": False,
        },
        "download_sources": {},
        "safety": {"never_write_outside": "write_roots",
                   "overwrite_requires_backup": True},
        "known_limitations": [
            "This plugin does not install the mod loader (BepInEx/MelonLoader/"
            "UE4SS). Without one, files in the folder may not be loaded by the game.",
            "No load order and no conflict resolution: two mods shipping the same "
            "path keep whichever was installed last.",
        ],
        "known_limitation_keys": ["USER_LIMIT_LOADER", "USER_LIMIT_ORDER"],
    }
