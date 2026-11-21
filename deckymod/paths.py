"""Path resolution — the 12-step algorithm from §3.7 (R1 / selection A).

RESOLVE ON EVERY ACTION, NEVER CACHE. Steam library layout, microSD mount
state, and the Proton prefix can all change between two button presses.

Steps:
  1  resolve deck user (uid/gid/home)             (fsops.resolve_user)
  2  STEAM_ROOT + Flatpak detection
  3  parse libraryfolders.vdf -> library roots
  4  scan appmanifest_*.acf -> locate AppID 294100, read installdir
  5  GAME_DIR = realpath(LIB/steamapps/common/INSTALLDIR)
  6  MOD_ROOT / STAGING / QUARANTINE (siblings, NOT inside Mods/)
  7  STATE_FILE (XDG_CONFIG, path with literal spaces)
  8  PFX = N/A for this native-Linux sample game
  9  read /proc/self/mountinfo -> FS type / POSIX?
 10  preflight (statvfs, writable, non-symlink, realpath containment)
 11  per-root atomic write helpers (fsops)
 12  UI must show W1/W2 absolute paths for confirmation; re-resolve each action

Flatpak Steam (§3.5): we DETECT it, but in MVP we refuse with
E_FLATPAK_PERMISSION (planned). We NEVER run 'flatpak override' ourselves.
"""

from __future__ import annotations

import os
from typing import Dict, Optional

from .errors import ModError
from .fsops import is_posix_fs, preflight_root, resolve_user, same_filesystem
from .vdf import VDFError, find_library_paths, get_installdir, parse_vdf

FLATPAK_STEAM_ID = "com.valvesoftware.Steam"


class ResolvedPaths:
    """JSON-safe value object. All paths are absolute strings (never Path)."""

    def __init__(self):
        self.uid = None
        self.gid = None
        self.user_home = ""
        self.username = ""
        self.steam_root = ""
        self.library_root = ""
        self.appid = 294100
        self.install_dir = ""
        self.game_root = ""
        self.mod_root = ""
        self.state_file = ""
        self.state_staging = ""
        self.staging = ""
        self.quarantine_root = ""
        # Round 25: file_drop parks a DISABLED mod here (a sibling of Mods/, so
        # os.replace stays on one filesystem). Distinct from quarantine_root:
        # quarantine means "uninstalled, restorable", this means "still owned,
        # temporarily not loaded by the game".
        self.disabled_root = ""
        self.proton_prefix = None  # N/A for native Linux
        self.xdg_config = ""
        self.flatpak = False
        self.fs_posix = True
        self.mountinfo = {}

    def to_json_safe(self) -> dict:
        from .json_safe import to_json_safe
        return to_json_safe(vars(self))

    def w1(self) -> str:
        return self.state_file

    def w2(self) -> str:
        return self.mod_root


def _xdg_config(user_home: str) -> str:
    return os.environ.get("XDG_CONFIG_HOME") or os.path.join(user_home, ".config")


def _flatpak_steam_root(user_home: str) -> Optional[str]:
    """Return the Flatpak Steam data root if it exists (§3.5)."""
    cand = os.path.join(user_home, ".var", "app", FLATPAK_STEAM_ID)
    if os.path.isdir(cand):
        return cand
    return None


def _steam_roots(user_home: str) -> list:
    """Candidate Steam config roots, in priority order. (§3.7 step 2/3)"""
    roots = []
    flatpak = _flatpak_steam_root(user_home)
    if flatpak:
        roots.append((flatpak, True))
    # native Steam (path varies by distro; ⚠️ V10 verify)
    for rel in (".local/share/Steam", ".steam/steam", ".steam/root", ".local/share/steam"):
        p = os.path.join(user_home, rel)
        if os.path.isdir(p):
            roots.append((p, False))
    # env override (e.g. explicit test tree / custom layout)
    env = os.environ.get("DECKYMOD_STEAM_ROOT")
    if env:
        roots.insert(0, (env, os.path.basename(env.rstrip("/\\")) == FLATPAK_STEAM_ID))
    return roots


def _find_libraryfolders_vdf(steam_root: str) -> Optional[str]:
    """libraryfolders.vdf location has varied across Steam versions (§7 V10)."""
    candidates = [
        os.path.join(steam_root, "steamapps", "libraryfolders.vdf"),
        os.path.join(steam_root, "config", "libraryfolders.vdf"),
        os.path.join(steam_root, "libraryfolders.vdf"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _resolve_install_dir(library_root: str, appid: int) -> Optional[str]:
    """Locate appmanifest_<appid>.acf in the SAME library (§3.7 step 4)."""
    sa = os.path.join(library_root, "steamapps")
    if not os.path.isdir(sa):
        return None
    wanted = f"appmanifest_{appid}.acf"
    # case-insensitive match (Steam has used both cases)
    match = None
    try:
        for name in os.listdir(sa):
            if name.lower() == wanted.lower():
                match = os.path.join(sa, name)
                break
    except OSError:
        return None
    if not match:
        return None
    try:
        with open(match, "r", encoding="utf-8", errors="replace") as f:
            parsed = parse_vdf(f.read())
        return get_installdir(parsed)
    except (VDFError, OSError):
        return None


#: Round 43: folder names used when a descriptor declares no ``paths`` block.
#: These are the historical literals and MUST stay exactly as they were, so
#: every pre-Round-43 descriptor resolves byte-for-byte identically.
_LAYOUT_DEFAULTS = {
    "mod_root": "Mods",
    "staging": ".decky-staging",
    "quarantine": ".decky-quarantine",
    "disabled": ".decky-disabled",
}

_LAYOUT_PLACEHOLDERS = ("GAME_ROOT", "HOME", "XDG_CONFIG")


def _expand_layout(value: str, game_root: str, user_home: str, xdg_config: str) -> str:
    """Expand a descriptor ``paths`` template into an absolute path.

    Unknown ``${...}`` placeholders are an error, not an empty string: a typo in
    a descriptor must not silently resolve to a path under ``/``. Relative
    results are anchored at ``game_root`` (the historical behaviour), so a
    descriptor that says ``"Mods"`` and one that says ``"${GAME_ROOT}/Mods"``
    mean the same thing.
    """
    out = str(value)
    subs = {"GAME_ROOT": game_root, "HOME": user_home, "XDG_CONFIG": xdg_config}
    for name, replacement in subs.items():
        out = out.replace("${%s}" % name, replacement)
    if "${" in out:
        raise ModError("E_PATH_INVALID", detail=f"unknown placeholder in descriptor path: {value!r}")
    if not os.path.isabs(out):
        out = os.path.join(game_root, out)
    # Normalise separators: a descriptor writes ``${GAME_ROOT}/Mods`` with a
    # forward slash, while ``os.path.join`` produces a native separator. Without
    # this, the same folder would have two spellings depending on whether it
    # came from the descriptor or the fallback, and every ``endswith``/
    # string comparison in the plugin and its tests would have to tolerate both.
    return os.path.normpath(out)


def _layout_value(layout: dict | None, key: str, game_root: str,
                  user_home: str, xdg_config: str) -> str:
    """One folder from the descriptor's ``paths`` block, or the historical name.

    Round 43 / P1#5: before this, ``paths.resolve()`` hard-coded ``Mods``,
    ``.decky-staging``, ``.decky-quarantine`` and ``.decky-disabled`` and never
    read the descriptor's ``paths`` block at all -- the block was documentation
    that happened to agree with the code. Any second game whose mod folder was
    not literally ``Mods/`` could not be added by descriptor alone.
    """
    value = None
    if isinstance(layout, dict):
        value = layout.get(key)
    if value is None or value == "":
        value = _LAYOUT_DEFAULTS[key]
    value = str(value)
    # The descriptor spells ``quarantine`` as the per-TRANSACTION directory
    # (``"${GAME_ROOT}/.decky-quarantine/${TXN_ID}"``) because that is what a
    # human reading the file needs to know. ``ResolvedPaths`` stores the ROOT,
    # and every caller appends ``os.path.join(root, txn)`` itself, so the
    # variable must be dropped here -- not passed through (an unexpanded
    # placeholder is an error, and a literal ``${TXN_ID}`` folder name would
    # silently create a directory nobody ever looks in).
    if value.endswith("/${TXN_ID}"):
        value = value[: -len("/${TXN_ID}")]
    elif "${TXN_ID}" in value:
        raise ModError("E_PATH_INVALID", detail=f"misplaced ${{TXN_ID}} in descriptor path: {value!r}")
    return _expand_layout(value, game_root, user_home, xdg_config)


def _containment_check(base: str, candidate: str):
    """realpath containment: candidate must be inside base (anti-escape)."""
    b = os.path.realpath(base)
    c = os.path.realpath(candidate)
    if c != b and not c.startswith(b.rstrip(os.sep) + os.sep):
        raise ModError("E_PATH_ESCAPE", detail=f"{candidate} not inside {base}")


def resolve(appid: int = 294100, *, preflight: bool = False,
            no_state_file: bool = False,
            descriptor_paths: dict | None = None) -> ResolvedPaths:
    """Resolve all paths for a game. Does NOT create or write anything.

    ``no_state_file=True`` (selection B / SMAPI file_drop): the game has NO
    ModsConfig.xml-style W1 state file. We leave ``state_file``/``state_staging``
    empty and skip all state-file preflight. The RimWorld default (False) is
    byte-for-byte unchanged — 33 synthetic-tree tests + the 41-green real-machine
    path depend on that.

    ``descriptor_paths`` (Round 43 / P1#5) is the game descriptor's own
    ``paths`` block. When given, ``mod_root``/``staging``/``quarantine``/
    ``disabled`` come from it (with ``${GAME_ROOT}``/``${HOME}``/``${XDG_CONFIG}``
    expanded); when omitted, the historical literals under ``game_root`` are
    used, which is what every caller did before this parameter existed.
    """
    r = ResolvedPaths()
    r.appid = appid

    # step 1: user
    r.uid, r.gid, r.user_home, r.username = resolve_user()
    if not r.user_home:
        raise ModError("E_PATH_INVALID", detail="could not resolve user home (DECKY_USER_HOME/HOME)")

    # step 2/3: Steam root + library roots
    roots = _steam_roots(r.user_home)
    if not roots:
        raise ModError("E_GAME_NOT_FOUND", detail="no Steam config root found")

    libraries = []
    for steam_root, is_flatpak in roots:
        vdf = _find_libraryfolders_vdf(steam_root)
        if vdf:
            try:
                with open(vdf, "r", encoding="utf-8", errors="replace") as f:
                    libraries += [(p, steam_root, is_flatpak) for p in find_library_paths(parse_vdf(f.read()))]
            except (VDFError, OSError):
                pass
        # the Steam root itself is also a library in many installs
        if os.path.isdir(os.path.join(steam_root, "steamapps")):
            libraries.append((steam_root, steam_root, is_flatpak))

    # dedupe library paths
    seen, libs = set(), []
    for lib, sr, fp in libraries:
        n = os.path.realpath(lib)
        if n not in seen:
            seen.add(n)
            libs.append((lib, sr, fp))

    # step 4: find the game
    hits = []
    for lib, sr, fp in libs:
        installdir = _resolve_install_dir(lib, appid)
        if installdir:
            hits.append((lib, sr, fp, installdir))
    if not hits:
        raise ModError("E_GAME_NOT_FOUND", detail=f"AppID {appid} not found in {len(libs)} libraries")
    if len(hits) > 1:
        raise ModError("E_GAME_AMBIGUOUS", detail=f"AppID {appid} found in {len(hits)} libraries: {[h[0] for h in hits]}")

    lib, steam_root, is_flatpak, installdir = hits[0]
    r.flatpak = is_flatpak
    r.steam_root = os.path.realpath(steam_root)
    r.library_root = os.path.realpath(lib)

    # step 5 (Flatpak): refuse with a clean message; never run flatpak override
    if is_flatpak:
        raise ModError(
            "E_FLATPAK_PERMISSION",
            detail=f"Flatpak Steam detected at {steam_root}; library-path mapping is out of MVP scope",
        )

    r.install_dir = installdir  # verbatim, case-sensitive (⚠️ V9)
    # step 6: game root
    common = os.path.join(r.library_root, "steamapps", "common")
    game_dir = os.path.realpath(os.path.join(common, installdir))
    if not os.path.isdir(game_dir):
        # case-insensitive fallback to the real directory casing (⚠️ V9 / V18)
        try:
            for name in os.listdir(common):
                if name.lower() == installdir.lower():
                    game_dir = os.path.realpath(os.path.join(common, name))
                    r.install_dir = name  # use the REAL casing
                    break
        except OSError:
            pass
    r.game_root = game_dir

    # step 7: W2 mod root + siblings (NOT inside Mods/)
    # Round 43: these four names now come from the descriptor's ``paths`` block
    # when it declares them, and fall back to the historical literals when it
    # does not. Both the RimWorld descriptor and Stardew's declare the same
    # names as the old constants, so their resolution is unchanged.
    layout = descriptor_paths if isinstance(descriptor_paths, dict) else None
    xdg = _xdg_config(r.user_home)
    r.mod_root = _layout_value(layout, "mod_root", r.game_root, r.user_home, xdg)
    r.staging = _layout_value(layout, "staging", r.game_root, r.user_home, xdg)
    r.quarantine_root = _layout_value(layout, "quarantine", r.game_root, r.user_home, xdg)
    # Round 25: file_drop disables a mod by moving its directory out of Mods/,
    # because presence in Mods/ IS the enabled state for SMAPI. The parking area
    # must be a SIBLING of Mods/ (same filesystem) so os.replace works; a path
    # under the user's home or on a microSD would fail with EXDEV(18).
    r.disabled_root = _layout_value(layout, "disabled", r.game_root, r.user_home, xdg)
    if os.path.commonpath([os.path.realpath(r.staging), os.path.realpath(r.mod_root)]) == os.path.realpath(r.mod_root):
        raise ModError("E_STAGING_IN_MODS", detail="staging resolved inside Mods/")

    # step 8: W1 state file (path with literal spaces, single string)
    r.xdg_config = _xdg_config(r.user_home)
    if no_state_file:
        # selection B / SMAPI file_drop: no ModsConfig.xml-style state file.
        r.state_file = ""
        r.state_staging = ""
    else:
        cfg_dir = os.path.join(r.xdg_config, "unity3d", "Ludeon Studios", "RimWorld by Ludeon Studios", "Config")
        r.state_file = os.path.join(cfg_dir, "ModsConfig.xml")
        r.state_staging = os.path.join(cfg_dir, ".decky-staging")

    # step 9: PFX N/A (native Linux); recorded as None for honesty
    r.proton_prefix = None

    # step 10: FS type + preflight
    r.fs_posix = is_posix_fs(r.game_root)
    r.mountinfo = {
        "game_root_posix": r.fs_posix,
        "state_file_posix": is_posix_fs(r.state_file) if r.state_file else None,
    }
    if preflight:
        for p in ((r.mod_root,) if no_state_file else (r.mod_root, r.state_file)):
            parent = os.path.dirname(p)
            if os.path.isdir(parent):
                r.mountinfo[f"preflight:{p}"] = preflight_root(parent, need_writable=True)
        # cross-device guard: mod_root and its staging must be on one FS
        if os.path.isdir(r.mod_root) and not same_filesystem(r.mod_root, r.game_root):
            raise ModError("E_CROSS_DEVICE", detail="Mods/ is on a different filesystem than GAME_ROOT")

    # containment
    _containment_check(r.library_root, r.game_root)
    return r
