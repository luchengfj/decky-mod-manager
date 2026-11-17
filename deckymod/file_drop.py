"""SMAPI / file_drop helpers for the stardew (selection B) backend.

DETECT-ONLY + READ-ONLY posture (approved 2026-11-14):
  * SMAPI is an EXTERNAL user-installed launcher. We DETECT it, never install.
  * The user's Steam launch options must ALREADY point at SMAPI; we never edit.
  * If a third-party mod manager owns Mods/ (Amethyst VFS: Mods/.mm_deployed +
    sibling Mods_Core/), every WRITE is refused with E_EXTERNAL_MANAGER.
  * SMAPI mods are DIRECTORIES containing manifest.json. A mod is enabled iff
    its directory is present under Mods/ (file_drop). There is NO state file.

This module is stdlib-only and does NOT import the frozen-interpreter-missing
xml.etree directly (it reuses archive.py, which is shimmed by deckymod/__init__).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import uuid
import zipfile

from . import archive, fomod, manifest, sevenzip
from .errors import ModError

# Only these three (.NET assemblies) are relaxed. All other forbidden
# extensions + all structural guards remain in force (see descriptor).
SMAPI_ALLOW_RELAXED = {".dll", ".so", ".dylib"}
SMAPI_FORBIDDEN_EXT = archive.FORBIDDEN_EXT - SMAPI_ALLOW_RELAXED


DEFAULT_EXTERNAL_MARKERS = (".mm_deployed", "Mods_Core")
"""Fallback marker names, used only when the descriptor declares none.

Round 53: these two names were hard-coded here, in a module whose whole point
is being game-agnostic, while ``loader_detection.external_manager_markers`` in
the descriptor declared exactly the same two strings -- and nothing read that
key. A second game whose third-party manager leaves a different marker would
have been silently unprotected, and the descriptor would have looked like it
covered the case.
"""


def detect_external_manager(game_root: str, mod_root: str, markers=None) -> bool:
    """True when another mod manager's marker is present.

    The WHERE is part of the evidence, not a detail: a marker is a FILE inside
    ``Mods/`` or a DIRECTORY beside it in the game root. Checking a bare name
    in both places would flag an ordinary mod folder that happens to be called
    ``Mods_Core`` and silently turn the whole plugin read-only.

    ``markers`` comes from ``loader_detection.external_manager_markers``. With
    none declared the historical pair is used, so behaviour is unchanged for
    descriptors that do not declare them.
    """
    names = [str(m) for m in (markers or DEFAULT_EXTERNAL_MARKERS) if str(m)]
    for name in names:
        if os.path.isfile(os.path.join(mod_root, name)):
            return True
        if os.path.isdir(os.path.join(game_root, name)):
            return True
    return False


def detect_loader(game_root: str, patterns=None) -> bool:
    """Launcher presence = any of the descriptor's ``patterns`` under game_root.

    ``patterns`` comes from ``loader_detection.patterns`` in the descriptor.
    No game-specific default lives here: without a descriptor-declared pattern
    there is nothing to detect (callers treat that as "no launcher required").
    """
    for pat in (patterns or ()):
        if os.path.exists(os.path.join(game_root, str(pat).rstrip("/"))):
            return True
    return False


def check_launch_options(user_home: str, appid="", launcher_token="") -> str:
    """Return 'set' | 'missing' | 'unknown'.

    Best-effort scan of Steam userdata localconfig.vdf for ``appid``'s
    LaunchOptions referencing ``launcher_token``. Both come from the
    descriptor (``loader_detection`` / ``identity``), so this helper is
    game-agnostic. With no descriptor tokens supplied, the answer is
    'unknown' (nothing to prove). 'unknown' (no readable file) is deliberately
    non-fatal: absence of the file does not prove the option is unset
    (different Steam layouts / Deck Game Mode). Writes are refused only when
    we can positively see the option is 'missing'.
    """
    if not appid or not launcher_token:
        return "unknown"
    roots = [
        os.path.join(user_home, ".local", "share", "Steam"),
        os.path.join(user_home, ".steam", "steam"),
    ]
    appid_token = '"%s"' % appid
    found_any = False
    for root in roots:
        ud = os.path.join(root, "userdata")
        try:
            uids = os.listdir(ud) if os.path.isdir(ud) else []
        except OSError:
            continue
        for uid in uids:
            lc = os.path.join(ud, uid, "config", "localconfig.vdf")
            if not os.path.isfile(lc):
                continue
            try:
                with open(lc, "r", encoding="utf-8", errors="replace") as f:
                    txt = f.read()
            except OSError:
                continue
            if appid_token not in txt:
                continue
            found_any = True
            if launcher_token and launcher_token in txt:
                return "set"
    return "missing" if found_any else "unknown"


def _active_mod_package() -> dict:
    """Fall back to the active descriptor when a caller passes no mod_package.

    Keeps game-specific field names out of this module entirely: they live in
    the descriptor JSON and are consumed by deckymod/manifest.py.
    """
    try:
        from .registry import Registry
        _, desc = Registry().active_descriptor()
        return desc.get("mod_package", {}) or {}
    except Exception:
        return {}


def find_manifest(entries, mod_package=None):
    """Compat wrapper: locate the manifest member via the descriptor parser.

    Returns (orig_name, root, {stripped: original}) or (None, root, mapping).
    """
    parser = manifest.parser_for(mod_package if mod_package is not None else _active_mod_package())
    hit = parser.find_member(entries)
    if not hit:
        return None, None, {}
    return hit.orig_name, hit.root, hit.mapping


def parse_manifest(zf: zipfile.ZipFile, member: str, mod_package=None) -> dict:
    """Compat wrapper: parse a manifest member via the descriptor parser.

    Returns the legacy normalized dict (uniqueId/dirName/name/version/...).
    """
    parser = manifest.parser_for(mod_package if mod_package is not None else _active_mod_package())
    try:
        raw = zf.read(member)
    except (KeyError, OSError, RuntimeError) as e:
        raise ModError("E_MANIFEST_INVALID", detail=f"cannot read {member}: {e}")
    pm = parser.parse(raw, member)
    return {
        "uniqueId": pm.uid,
        "dirName": pm.dir_name,
        "name": pm.name,
        "version": pm.version,
        "minimumApiVersion": pm.minimum_api_version,
        "author": pm.author,
        "entryDll": pm.entry_dll,
        "dependencies": pm.dependencies,
        "badges": pm.badges,
    }


def inspect_mod(path: str, limits: dict | None = None, reject_extensions=None,
                mod_package=None) -> dict:
    """Validate a ZIP or .7z + parse its manifest + build the members map.

    ALL field names / globs / id rules come from the descriptor's
    ``mod_package`` (via deckymod/manifest.py). Nothing game-specific is
    hard-coded here. The returned wire dict shape is unchanged.

    Round 24: a .7z is routed through ``deckymod/sevenzip.py``, which lists and
    validates the entry table *before* anything is written. The manifest read is
    done by extracting that one member with 7z into a scratch dir, because the
    stdlib cannot open 7z streams. Both paths converge on the same
    ``parser.parse(raw, name)`` call, so a manifest bug cannot differ per format.
    """
    mp = mod_package if mod_package is not None else _active_mod_package()
    forbidden = set(reject_extensions) if reject_extensions is not None else SMAPI_FORBIDDEN_EXT

    if sevenzip.is_7z(path):
        return _inspect_7z(path, mp, forbidden, limits)

    info = archive.inspect_zip(path, limits, forbidden_ext=forbidden)
    infos = info.pop("_zf_entries")
    names = [i.filename for i in infos]
    info["fomod"] = _fomod_from_zip(path, names)
    parser = manifest.parser_for(mp)
    hit = parser.find_member(names)
    if not hit:
        raise ModError("E_MANIFEST_MISSING", detail="no manifest found in archive")
    with zipfile.ZipFile(path, "r") as zf:
        try:
            raw = zf.read(hit.orig_name)
        except (KeyError, OSError, RuntimeError) as e:
            raise ModError("E_MANIFEST_INVALID", detail=f"cannot read {hit.orig_name}: {e}")
    pm = parser.parse(raw, hit.orig_name)
    # Round 62: hit.mapping is now anchored at the directory the manifest was
    # found in, so inverting it puts manifest.json at the TOP of Mods/<dir>/
    # no matter how the packer nested the files.
    orig_to_stripped = {v: k for k, v in hit.mapping.items()} if hit.mapping else {}
    manifest_stripped = orig_to_stripped.get(hit.orig_name, hit.orig_name)
    members = {}
    for zi in infos:
        nm = zi.filename
        if nm.endswith("/"):
            continue
        stripped = orig_to_stripped.get(nm, nm)
        if not stripped:
            continue
        members[stripped] = {"orig": nm, "size": zi.file_size}

    # Round 64: a manifest that declares an EntryDll the archive does not ship
    # installs fine and then never loads. Refuse it while nothing is written.
    manifest.check_entry_dll(pm.entry_dll, members)

    version = pm.version
    version_is_fallback = False
    if not version:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        version = "sha256:12:" + h.hexdigest()[:12]
        version_is_fallback = True

    prefix = mp.get("install_relpath_prefix") or "Mods/"
    info.update({
        "packageId": pm.uid,   # shared wire identity key
        "uniqueId": pm.uid,
        "name": pm.name,
        "version": version,
        "version_is_fallback": version_is_fallback,
        "supportedVersions": ([str(pm.minimum_api_version)] if pm.minimum_api_version else []),
        "badges": pm.badges,
        "dependencies": pm.dependencies,
        "entryDll": pm.entry_dll,
        "install_relpath": prefix + pm.dir_name,
        "dir_name": pm.dir_name,
        "strip_single_root": hit.root,
        "manifest_member": hit.orig_name,
        "manifest_stripped": manifest_stripped,
        "members": members,
    })
    return info


def _fomod_descriptor(parsed: dict) -> dict:
    """Turn a parsed FOMOD descriptor into a compact, JSON-safe wire dict.

    ``present=True, usable=True`` means the UI should render the step/option
    controls. Otherwise ``reason`` is a readable message and the caller must
    fall back to a plain extract (never silently install a subset).
    """
    steps = []
    for st in parsed.get("steps") or []:
        groups = []
        for g in st.get("groups") or []:
            groups.append({
                "name": g.get("name") or "",
                "mode": g.get("mode") or "multi",
                "options": [{"name": o.get("name") or "",
                             "description": o.get("description") or "",
                             "selected": bool(o.get("selected")),
                             "files": [dict(f) for f in (o.get("files") or [])]}
                            for o in (g.get("options") or [])],
            })
        steps.append({"name": st.get("name") or "", "groups": groups})
    return {"present": True, "usable": True, "steps": steps,
            "warnings": list(parsed.get("warnings") or [])}


def _fomod_from_zip(path: str, names: list) -> dict:
    """Best-effort FOMOD detection for a ZIP. Never fails inspect.

    A malformed/unsafe config is reported as ``usable=False`` with a readable
    reason, so the caller falls back to a plain extract and tells the user —
    matching the criterion's "no silent failure" requirement.
    """
    mc = fomod.find_moduleconfig(names)
    if not mc:
        return {"present": False}
    try:
        with zipfile.ZipFile(path, "r") as zf:
            raw = zf.read(mc)
        return _fomod_descriptor(fomod.parse(raw))
    except fomod.FomodError as fe:
        return {"present": True, "usable": False, "reason": fe.detail}
    except Exception as e:
        return {"present": True, "usable": False,
                "reason": "could not read FOMOD config: %s" % e}


def _scratch_dir(prefix: str) -> str:
    """A fresh private scratch directory for the .7z manifest read.

    Deliberately NOT ``tempfile.mkdtemp``: that creates the directory with mode
    0o700, and on Windows the resulting DACL denies writes to the very process
    that owns it (``PermissionError: [Errno 13]``) — the same sandbox behaviour
    the test suite already works around. ``os.makedirs`` gets normal inherited
    permissions, and the caller removes the directory in a ``finally`` anyway, so
    the extra permissive creation does not widen the exposure window.
    """
    base = tempfile.gettempdir()
    for _ in range(8):
        cand = os.path.join(base, prefix + uuid.uuid4().hex[:12])
        try:
            os.makedirs(cand)
            return cand
        except FileExistsError:
            continue
    raise ModError("E_ACCESS", detail="could not create a scratch directory for .7z")


def _inspect_7z(path: str, mp: dict, forbidden, limits) -> dict:
    """The .7z branch of inspect_mod: validate the table, then read one member.

    Extraction happens in a scratch directory that is removed in a ``finally``.
    Nothing is left behind, and a failure to clean up must not change the result
    the user sees — so cleanup swallows its own errors.
    """
    lim = {**archive.DEFAULT_LIMITS, **(limits or {})}
    listed = sevenzip.inspect_7z(path, lim, forbidden_ext=forbidden)
    entries = listed["entries"]
    # Directory entries are reported by 7z via Attributes (see sevenzip._attrs),
    # not by a trailing separator; filtering here keeps the manifest lookup
    # identical to the ZIP path.
    names = [e["name"] for e in entries if not e.get("is_dir")]
    # FOMOD detection for .7z is best-effort: a bad/unparseable config must NOT
    # fail inspect. We record a readable reason and fall back to plain extract.
    fomod_info = {"present": False}
    mc = fomod.find_moduleconfig(names)
    if mc:
        scratch_7 = _scratch_dir("deckymod-7zf-")
        try:
            sevenzip.extract_7z(path, scratch_7, tool=listed["tool"])
            cfg_path = os.path.join(scratch_7, *mc.split("/"))
            with open(cfg_path, "rb") as cf:
                fomod_info = _fomod_descriptor(fomod.parse(cf.read()))
        except fomod.FomodError as fe:
            fomod_info = {"present": True, "usable": False, "reason": fe.detail}
        except Exception as fe:  # extraction/IO trouble is not fatal for inspect
            fomod_info = {"present": True, "usable": False,
                          "reason": "could not read FOMOD config: %s" % fe}
        finally:
            shutil.rmtree(scratch_7, ignore_errors=True)

    parser = manifest.parser_for(mp)
    hit = parser.find_member(names)
    if not hit:
        raise ModError("E_MANIFEST_MISSING", detail="no manifest found in .7z archive")

    scratch = _scratch_dir("deckymod-7z-")
    try:
        sevenzip.extract_7z(path, scratch, tool=listed["tool"])
        manifest_path = os.path.join(scratch, *hit.orig_name.split("/"))
        try:
            with open(manifest_path, "rb") as f:
                raw = f.read()
        except OSError as e:
            raise ModError("E_MANIFEST_INVALID",
                           detail="cannot read %s from .7z: %s" % (hit.orig_name, e))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    pm = parser.parse(raw, hit.orig_name)
    orig_to_stripped = {v: k for k, v in hit.mapping.items()} if hit.mapping else {}
    manifest_stripped = orig_to_stripped.get(hit.orig_name, hit.orig_name)

    members = {}
    for entry in entries:
        nm = entry["name"]
        if entry.get("is_dir"):
            continue
        stripped = orig_to_stripped.get(nm, nm)
        if not stripped:
            continue
        members[stripped] = {"orig": nm, "size": entry.get("size") or 0}

    # Round 64: same check on the .7z path -- it is a parallel implementation, so
    # a ZIP-only fix would leave this format unchecked (see round 63).
    manifest.check_entry_dll(pm.entry_dll, members)

    version = pm.version
    version_is_fallback = False
    if not version:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        version = "sha256:12:" + h.hexdigest()[:12]
        version_is_fallback = True

    prefix = mp.get("install_relpath_prefix") or "Mods/"
    return {
        "format": "7z",
        "entryDll": pm.entry_dll,
        "fomod": fomod_info,
        "total_uncompressed": listed["total_uncompressed"],
        "packageId": pm.uid,
        "uniqueId": pm.uid,
        "name": pm.name,
        "version": version,
        "version_is_fallback": version_is_fallback,
        "supportedVersions": ([str(pm.minimum_api_version)] if pm.minimum_api_version else []),
        "badges": pm.badges,
        "dependencies": pm.dependencies,
        "install_relpath": prefix + pm.dir_name,
        "dir_name": pm.dir_name,
        "strip_single_root": hit.root,
        "manifest_member": hit.orig_name,
        "manifest_stripped": manifest_stripped,
        "members": members,
    }
