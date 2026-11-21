"""Enumerate the Steam libraries and the games installed in them (goal item 2).

Why this module exists: everything else in the plugin resolves ONE appid from a
descriptor. The goal requires listing games across every Steam library — the
internal drive *and* the SD card — with AppID, install path and compatdata
prefix, and doing it read-only.

Design notes, all of them driven by what the device actually contains:

* Library roots come from ``libraryfolders.vdf`` (parsed by :mod:`deckymod.vdf`,
  which is schema-independent) *plus* a fixed set of well-known roots. The real
  Deck only listed ``/home/deck/.local/share/Steam`` in its vdf while the SD
  card was simply not mounted, so a root that does not exist is skipped quietly
  rather than reported as an error.
* An ``appmanifest_<appid>.acf`` is the only authority for "installed": a folder
  under ``steamapps/common`` with no manifest is not a Steam install.
* ``StateFlags`` 4 means fully installed. Other values are surfaced as
  ``state`` so the UI can be honest instead of pretending a partial download is
  playable. An unreadable manifest still yields an entry with ``state="unknown"``.
* ``compatdata/<appid>`` only exists when Proton ran, so its absence is normal
  for native Linux titles and is reported as ``compatdata: None``.
* Everything here is read-only. It never writes, never creates directories, and
  never touches the game folders — so it is safe to call from ``status``.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from . import paths as paths_mod
from . import templates as templates_mod
from . import vdf as vdf_mod
from .fsops import resolve_user

# Additional roots worth probing even when libraryfolders.vdf does not list them.
# The SD card path on SteamOS is /run/media/<user>/<label> but the label varies,
# so the parent directory is globbed by the caller instead of hard-coded.
_EXTRA_LIBRARY_PARENTS = ("/run/media",)

_STATE_INSTALLED = 4

# Steam installs its own compatibility runtimes as ordinary appmanifests under
# steamapps/, so a naive "every appmanifest is a game" scan lists Proton and the
# Steam Linux Runtime alongside the games the user actually plays. These are
# infrastructure, never moddable, and were 8 of the 29 entries on the device
# (measured 2026-11-20). Filter them out at the SOURCE so every consumer
# (list_games UI counts, catalog, summarise) sees only real games.
#
# Two layers, both read-only and both from data Steam itself writes:
#   1. exact AppIDs Steam uses for its runtimes (stable, authoritative);
#   2. name / installdir prefixes, as a forward-compat net for new versions
#      (e.g. "Proton 12.0") whose AppID is not in the set yet. Prefixes are
#      deliberately specific so an ordinary game whose name merely contains
#      "Proton" is not dropped.
_RUNTIME_APPIDS = frozenset({
    228980,    # Steamworks Common Redistributables
    1070560,   # Steam Linux Runtime 1.0 (scout)
    1391110,   # Steam Linux Runtime 2.0 (soldier)
    1628350,   # Steam Linux Runtime 3.0 (sniper)
    4183110,   # Steam Linux Runtime 4.0
    1493710,   # Proton Experimental
    3658110,   # Proton 10.0
    4628710,   # Proton 11.0
})

# Prefix net is applied ONLY to installdir, never to the display name: a real
# game can be *named* "Proton Glow Racing" and must not be dropped. The Proton
# runtime's installdir is "Proton <number>" / "Proton - Experimental", so the
# regex requires that shape; the runtime dirs are exact known prefixes.
import re as _re

_RUNTIME_DIR_PATTERNS = (
    _re.compile(r"^proton\s+\d"),            # Proton 10.0, Proton 99, ...
    _re.compile(r"^proton\s+-\s+experimental$"),
    _re.compile(r"^steamlinuxruntime"),       # scout/soldier/sniper/4/...
    _re.compile(r"^steamworks shared$"),
)


def _is_runtime_component(appid: int, name: str, installdir: str) -> bool:
    """True when this manifest is a Steam runtime/tool, not a playable game.

    ``name`` is intentionally unused for prefix matching (only the AppID set
    and the installdir shape decide): display names are free-form and matching
    them would drop legitimate games that merely mention "Proton".
    """
    if appid in _RUNTIME_APPIDS:
        return True
    d = (installdir or "").strip().lower()
    for pattern in _RUNTIME_DIR_PATTERNS:
        if pattern.match(d):
            return True
    return False


def _default_home() -> str:
    """The invoking user's home, from the same resolver the path layer uses.

    ``resolve_user()`` returns ``(uid, gid, user_home, username)`` and honours
    DECKY_USER_HOME / HOME, so tests can point it at a synthetic tree.
    """
    try:
        return resolve_user()[2] or ""
    except Exception:  # noqa: BLE001 - listing games must never blow up status()
        return os.path.expanduser("~")


def _library_roots_from_vdf(vdf_path: str) -> List[str]:
    try:
        with open(vdf_path, "r", encoding="utf-8", errors="replace") as f:
            parsed = vdf_mod.parse_vdf(f.read())
    except Exception:  # noqa: BLE001 - a broken vdf must not hide the other roots
        return []
    return vdf_mod.find_library_paths(parsed)


def _sd_card_libraries(parents=None) -> List[str]:
    """Steam libraries on removable media, discovered without assuming a label.

    Both layouts SteamOS actually produces are accepted:

        /run/media/mmcblk0p1           (mounted at the parent, no user dir)
        /run/media/deck/mmcblk0p1      (mounted under the user dir)

    ``parents`` exists so a test can point the scan at a synthetic tree; the
    default is the real ``/run/media``. Nothing is hard-coded to a label or a
    device name, because both vary between cards and SteamOS versions.
    """
    found: List[str] = []
    for parent in (parents if parents is not None else _EXTRA_LIBRARY_PARENTS):
        if not os.path.isdir(parent):
            continue
        try:
            entries = sorted(os.listdir(parent))
        except OSError:
            continue
        for entry in entries:
            candidate = os.path.join(parent, entry)
            if os.path.isdir(os.path.join(candidate, "steamapps")):
                found.append(candidate)
            else:
                # /run/media/<user>/<label> is one level deeper
                inner = os.path.join(candidate)
                try:
                    for sub in sorted(os.listdir(inner)):
                        deep = os.path.join(inner, sub)
                        if os.path.isdir(os.path.join(deep, "steamapps")):
                            found.append(deep)
                except OSError:
                    continue
    return found


def library_roots(user_home: str, sd_parents=None) -> List[Dict[str, object]]:
    """All usable Steam library roots, de-duplicated, with a 'source' tag.

    Order is deterministic (vdf order first, then discovered ones) so the UI does
    not reshuffle between refreshes.
    """
    steam_roots = [p for p, _is_flatpak in paths_mod._steam_roots(user_home)]

    ordered: List[Dict[str, object]] = []
    seen = set()

    def add(path: str, source: str) -> None:
        if not path:
            return
        real = os.path.realpath(path)
        if real in seen:
            return
        if not os.path.isdir(os.path.join(real, "steamapps")):
            return
        seen.add(real)
        # Removable == outside the owning user's home. Deriving it from the path
        # (instead of matching /run/media) keeps this honest on any layout: an SD
        # card under a mountpoint is outside $HOME, the internal library is not.
        home_real = os.path.realpath(user_home) if user_home else ""
        removable = bool(home_real) and not (real == home_real or real.startswith(home_real + os.sep))
        ordered.append({
            "path": real,
            "source": source,
            "removable": removable,
        })

    for root in steam_roots:
        vdf_path = paths_mod._find_libraryfolders_vdf(root)
        if vdf_path:
            for lib in _library_roots_from_vdf(vdf_path):
                add(lib, "libraryfolders.vdf")
        add(root, "steam_root")
    for lib in _sd_card_libraries(sd_parents):
        add(lib, "removable-scan")
    return ordered


def _manifest_files(steamapps: str) -> List[str]:
    try:
        names = os.listdir(steamapps)
    except OSError:
        return []
    return [os.path.join(steamapps, n) for n in sorted(names)
            if n.lower().startswith("appmanifest_") and n.lower().endswith(".acf")]


def _read_manifest(acf_path: str) -> Dict[str, str]:
    """Flatten an appmanifest into lowercased top-level scalar keys."""
    try:
        with open(acf_path, "r", encoding="utf-8", errors="replace") as f:
            parsed = vdf_mod.parse_vdf(f.read())
    except Exception:  # noqa: BLE001
        return {}

    flat: Dict[str, str] = {}

    def walk(node, depth=0):
        if isinstance(node, dict) and depth < 4:
            for k, v in node.items():
                if isinstance(v, str):
                    flat.setdefault(k.lower(), v)
                elif isinstance(v, dict):
                    walk(v, depth + 1)

    walk(parsed)
    return flat


def _appid_from_filename(acf_path: str) -> Optional[int]:
    base = os.path.basename(acf_path)
    digits = base[len("appmanifest_"):-len(".acf")]
    if not digits.isdigit():
        return None
    return int(digits)


def scan_games(user_home: Optional[str] = None,
               sd_parents=None) -> List[Dict[str, object]]:
    """Every installed Steam game across all libraries. Read-only, never raises.

    Each entry: appid, name, installdir, library, install_path, compatdata,
    state, state_flags, size_on_disk, manifest.

    ``sd_parents`` is a test seam only: it lets a caller point the removable
    scan at a synthetic mount tree so the *whole* path (library discovery →
    manifest parse → compatdata prefix) can be exercised without a card in the
    slot. Production passes nothing and scans the real ``/run/media``.
    """
    home = user_home or _default_home()
    if not home:
        home = os.path.expanduser("~")

    games: List[Dict[str, object]] = []
    seen_appids = set()

    for lib in library_roots(home, sd_parents):
        lib_path = str(lib["path"])
        steamapps = os.path.join(lib_path, "steamapps")
        compatdata_root = os.path.join(steamapps, "compatdata")
        for acf in _manifest_files(steamapps):
            appid = _appid_from_filename(acf)
            if appid is None or appid in seen_appids:
                continue
            seen_appids.add(appid)
            info = _read_manifest(acf)
            installdir = info.get("installdir") or ""
            name = info.get("name") or installdir or str(appid)
            # Steam ships Proton / the Linux Runtime as ordinary appmanifests.
            # They are infrastructure, not games: never list them, and never
            # let them inflate game_count. Read-only, based on Steam's own data.
            if _is_runtime_component(appid, name, installdir):
                continue
            flags_raw = info.get("stateflags") or ""
            state_flags = int(flags_raw) if flags_raw.isdigit() else None
            if state_flags is None:
                state = "unknown"
            elif state_flags == _STATE_INSTALLED:
                state = "installed"
            else:
                state = "incomplete"
            prefix = os.path.join(compatdata_root, str(appid))
            install_path = os.path.join(steamapps, "common", installdir) if installdir else ""
            games.append({
                "appid": appid,
                "name": name,
                "installdir": installdir,
                "library": lib_path,
                "install_path": install_path,
                "compatdata": prefix if os.path.isdir(prefix) else None,
                "state": state,
                "state_flags": state_flags,
                "size_on_disk": int(info["sizeondisk"]) if (info.get("sizeondisk") or "").isdigit() else None,
                "manifest": acf,
                "removable": bool(lib.get("removable")),
                # Standard 4: read-only Mod-directory identification. Games with
                # no template are explicitly marked not-adapted; nothing here
                # writes or guesses a path for them.
                "template": templates_mod.identify(appid, install_path),
            })

    games.sort(key=lambda g: (str(g["name"]).lower(), int(g["appid"])))
    return games


def summarize(user_home: Optional[str] = None) -> Dict[str, object]:
    """Games + library roots + honest counts, ready to put in a JSON envelope."""
    libs = library_roots(user_home or _default_home())
    games = scan_games(user_home)
    return {
        "libraries": libs,
        "games": games,
        "library_count": len(libs),
        "game_count": len(games),
        "removable_count": len([g for g in games if g.get("removable")]),
        "with_prefix_count": len([g for g in games if g.get("compatdata")]),
    }
