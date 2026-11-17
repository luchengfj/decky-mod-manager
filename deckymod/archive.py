"""ZIP validation + About.xml parsing (§4 dry-run / §3.4 / §7 V19).

Security gates applied BEFORE anything is written to disk:
  * magic bytes 504b0304 (or empty/spanned variants) + zipfile.is_zipfile
  * reject: absolute paths, parent traversal, backslash paths, symlinks,
    hardlinks, devices, duplicate entries, encrypted entries, forbidden
    extensions (.exe/.msi/...), too many entries, path too deep, zip bomb
    (compressed/uncompressed/ratio limits)
  * strip_single_root: many mod ZIPs wrap everything in one top folder
  * manifest must be About/About.xml (or */About/About.xml), parsed with
    ElementTree (stdlib) read-only; packageId extracted + validated

We NEVER execute archive contents. The archive is unpacked, not installed.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from typing import Dict, List, NamedTuple, Tuple
from xml.etree import ElementTree as ET

from .errors import ModError

DEFAULT_LIMITS = {
    "max_compressed_bytes": 268435456,   # 256 MiB
    "max_uncompressed_bytes": 268435456,  # 256 MiB
    "max_entries": 4096,
    "max_compression_ratio": 100,
    # Round 27: a ratio is only evidence of a bomb when the OUTPUT is big.
    # Stardew map files are sparse 158 KB .btr blobs that legitimately hit
    # 390:1; rejecting them refused a real content pack while a 390:1 bomb
    # big enough to matter still trips max_uncompressed_bytes below.
    "ratio_floor_bytes": 1048576,         # 1 MiB
    "max_path_depth": 16,
}

FORBIDDEN_EXT = {".exe", ".msi", ".bat", ".cmd", ".ps1", ".scr", ".com", ".jar", ".dll", ".so", ".dylib"}
ID_REGEX = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


def _is_unsafe_external_attr(info: zipfile.ZipInfo) -> bool:
    """Detect symlinks / devices / other non-regular entries via unix mode."""
    mode = (info.external_attr >> 16) & 0xFFFF
    if not mode:
        return False
    import stat as _s
    if _s.S_ISLNK(mode) or _s.S_ISCHR(mode) or _s.S_ISBLK(mode) or _s.S_ISFIFO(mode) or _s.S_ISSOCK(mode):
        return True
    return False


def _validate_member_name(name: str, max_depth: int,
                          forbidden_ext=None) -> str:
    """Return a normalized posix relative path, or raise E_ZIP_SLIP/UNSAFE_ENTRY.

    ``forbidden_ext`` (selection B): an optional caller-supplied set of blocked
    extensions. Defaults to ``FORBIDDEN_EXT`` so all existing RimWorld behavior
    (and the 33 synthetic-tree tests' E_UNSAFE_ENTRY assertions) is unchanged.
    SMAPI file_drop passes the 8-class reject list, allowing .dll/.so/.dylib.
    """
    if forbidden_ext is None:
        forbidden_ext = FORBIDDEN_EXT
    if not name:
        return name
    # backslash is a Windows separator but on Linux would be a literal char;
    # either way reject to avoid hidden-path tricks (§3.4)
    if "\\" in name:
        raise ModError("E_UNSAFE_ENTRY", detail=f"backslash in path: {name}")
    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        raise ModError("E_ZIP_SLIP", detail=f"absolute path: {name}")
    norm = name.replace("\\", "/")
    parts = [p for p in norm.split("/")]
    if any(p == ".." for p in parts):
        raise ModError("E_ZIP_SLIP", detail=f"parent traversal: {name}")
    if len(parts) > max_depth:
        raise ModError("E_ZIP_BOMB", detail=f"path depth {len(parts)} > {max_depth}: {name}")
    ext = os.path.splitext(parts[-1])[1].lower()
    if ext in forbidden_ext:
        raise ModError("E_UNSAFE_ENTRY", detail=f"forbidden file type: {name}")
    return "/".join(parts)


def inspect_zip(path: str, limits: dict | None = None,
                forbidden_ext=None) -> dict:
    """Validate a local ZIP and return a JSON-safe inspection dict.

    Does not write anything. Checks every entry's metadata and content sizes.
    ``forbidden_ext`` (selection B) is forwarded to ``_validate_member_name``;
    omitting it preserves the original RimWorld default exactly.
    """
    lim = {**DEFAULT_LIMITS, **(limits or {})}
    try:
        size = os.path.getsize(path)
    except OSError as e:
        from .fsops import map_oserror
        raise map_oserror(e)
    if size > lim["max_compressed_bytes"]:
        raise ModError("E_ZIP_BOMB", detail=f"compressed {size} > {lim['max_compressed_bytes']}")
    if size < 4:
        raise ModError("E_BAD_ARCHIVE", detail="file too small for a ZIP")
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
    except OSError as e:
        from .fsops import map_oserror
        raise map_oserror(e)
    if magic[:2] != b"PK":
        raise ModError("E_BAD_ARCHIVE", detail=f"bad magic: {magic.hex()}")
    if not zipfile.is_zipfile(path):
        raise ModError("E_BAD_ARCHIVE", detail="zipfile.is_zipfile() == False")

    try:
        zf = zipfile.ZipFile(path, "r")
    except zipfile.BadZipFile as e:
        raise ModError("E_BAD_ARCHIVE", detail=str(e))

    entries = []
    total_uncompressed = 0
    seen_names = set()
    with zf:
        infos = zf.infolist()
        if len(infos) > lim["max_entries"]:
            raise ModError("E_ZIP_BOMB", detail=f"{len(infos)} entries > {lim['max_entries']}")
        for info in infos:
            name = _validate_member_name(info.filename, lim["max_path_depth"],
                                         forbidden_ext=forbidden_ext)
            if name in seen_names:
                raise ModError("E_DUPLICATE_ENTRY", detail=name)
            seen_names.add(name)
            if _is_unsafe_external_attr(info):
                raise ModError("E_UNSAFE_ENTRY", detail=f"link/device entry: {name}")
            if info.flag_bits & 0x1:  # encrypted
                raise ModError("E_UNSAFE_ENTRY", detail=f"encrypted entry: {name}")
            # Per-entry ratio bomb. Only meaningful above ratio_floor_bytes:
            # below that the absolute size cannot hurt anyone, and sparse game
            # assets legitimately compress hundreds of times.
            floor = lim.get("ratio_floor_bytes", 0)
            if info.compress_size > 0 and info.file_size >= floor:
                ratio = info.file_size / info.compress_size
                if ratio > lim["max_compression_ratio"]:
                    raise ModError("E_ZIP_BOMB", detail=f"ratio {ratio:.0f} on {name}")
            total_uncompressed += info.file_size
            if total_uncompressed > lim["max_uncompressed_bytes"]:
                raise ModError("E_ZIP_BOMB", detail="total uncompressed exceeds limit")
            entries.append({"name": name, "size": info.file_size, "is_dir": name.endswith("/")})

    return {"path": path, "compressed_size": size, "uncompressed_size": total_uncompressed,
            "entry_count": len(entries), "entries": entries, "_zf_entries": infos}


class ManifestLocation(NamedTuple):
    """Where a mod's manifest lives, and what the mod's own root directory is.

    ``base`` is the mod root as a path prefix INSIDE the archive ("" when the
    mod sits at the archive root). ``mapping`` is {stripped: original} for the
    files that belong to THIS mod, where ``stripped`` is relative to ``base``.
    ``others`` lists the mod roots of any other mods found in the same
    archive -- an archive that ships several mods cannot be installed as one.
    """
    base: str
    orig_name: str
    mapping: Dict[str, str]
    others: List[str]


def _relpaths(globs: List[str]) -> List[str]:
    """Turn descriptor globs into manifest paths relative to a mod's root.

    Round 62: the globs were being applied to archive-wide names through
    ``fnmatch``, where ``*`` also matches ``/``. So ``*/manifest.json`` happily
    matched ``Pack/ModA/manifest.json``, but the extraction mapping had only
    stripped ``Pack`` -- the mod was extracted one directory too deep, where
    SMAPI never looks for it. A glob is now read as "this path, relative to the
    mod's own root, at any depth": the leading ``*/`` means "wherever the mod
    root happens to be", not "exactly one component".
    """
    rels = []
    for g in globs:
        r = str(g).strip("/")
        while r.startswith("*/"):
            r = r[2:]
        if r and r not in rels:
            rels.append(r)
    # most specific first, so "About/About.xml" wins over a bare "About.xml"
    rels.sort(key=lambda r: (-r.count("/"), -len(r)))
    return rels


def locate_manifest(entries: List[str], relpaths: List[str]) -> ManifestLocation | None:
    """Find every member that looks like a manifest, and the root it implies.

    The mod root is derived from the member itself (``name`` minus the
    ``relpath`` suffix), never from a guess about how many directories the
    packer wrapped around the files. Returns ``None`` when nothing matches;
    the first entry of ``others`` being non-empty means the archive contains
    more than one mod, which the caller must refuse rather than silently pick.
    """
    files = [e for e in entries if e and not e.endswith("/")]
    found: List[Tuple[str, str]] = []   # (base, orig_name)
    for e in files:
        low = e.lower()
        for rel in relpaths:
            rl = rel.lower()
            if low == rl:
                found.append(("", e))
                break
            if low.endswith("/" + rl):
                found.append((e[: -(len(rel) + 1)], e))
                break
    if not found:
        return None
    # shallowest, then shortest: the most likely "the mod itself"
    found.sort(key=lambda b: (b[0].count("/"), len(b[0]), b[0].lower()))
    bases: List[str] = []
    for base, _ in found:
        if base not in bases:
            bases.append(base)
    base = bases[0]
    orig_name = next(o for b, o in found if b == base)
    prefix = base + "/" if base else ""
    mapping: Dict[str, str] = {}
    for e in files:
        if prefix:
            if not e.startswith(prefix):
                continue
            stripped = e[len(prefix):]
        else:
            stripped = e
        if stripped:
            mapping[stripped] = e
    return ManifestLocation(base=base, orig_name=orig_name,
                            mapping=mapping, others=bases[1:])


def _find_manifest(entries: List[str]) -> str | None:
    """Locate About/About.xml, keeping the historical "no refusal" behaviour.

    Only used by the RimWorld ``xml_list`` engine, which is a planned game and
    not reachable in production; it deliberately keeps picking one manifest
    instead of raising so this dormant path cannot start refusing archives.
    """
    loc = locate_manifest(entries, _relpaths(["About/About.xml", "*/About/About.xml"]))
    return loc.orig_name if loc else None


def parse_about_xml(zf: zipfile.ZipFile, member: str) -> dict:
    """Parse About.xml with ElementTree (stdlib), read-only."""
    try:
        raw = zf.read(member)
    except (KeyError, OSError, RuntimeError) as e:
        raise ModError("E_MANIFEST_INVALID", detail=f"cannot read {member}: {e}")
    # reject huge manifest
    if len(raw) > 1_000_000:
        raise ModError("E_MANIFEST_INVALID", detail="About.xml too large")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise ModError("E_MANIFEST_INVALID", detail=f"XML parse: {e}")

    def child_text(tag):
        el = root.find(tag)
        return (el.text or "").strip() if el is not None and el.text else ""

    package_id = child_text("packageId").lower()
    name = child_text("name")
    supported = [li.text.strip() for li in root.findall("supportedVersions/li") if li.text]
    mod_version = child_text("modVersion")
    target_version = child_text("targetVersion")
    load_after = [li.text.strip() for li in root.findall("loadAfter/li") if li.text]
    deps = [li.text.strip() for li in root.findall("dependencies/li") if li.text]

    for field in ("packageId", "name", "supportedVersions"):
        if field == "supportedVersions":
            if not supported:
                raise ModError("E_FIELD_MISSING", detail="supportedVersions")
        elif field == "name" and not name:
            raise ModError("E_FIELD_MISSING", detail="name")
        elif field == "packageId" and not package_id:
            raise ModError("E_ID_INVALID", detail="packageId missing")

    if not ID_REGEX.match(package_id):
        raise ModError("E_ID_INVALID", detail=f"packageId={package_id!r} fails {ID_REGEX.pattern}")

    return {
        "packageId": package_id,
        "name": name or package_id,
        "supportedVersions": supported,
        "modVersion": mod_version,
        "targetVersion": target_version,
        "loadAfter": load_after,      # info badge only
        "dependencies": deps,        # info badge only
    }


def inspect_mod(path: str, limits: dict | None = None) -> dict:
    """Full inspection: validate ZIP + parse About.xml + compute install id.

    Returns JSON-safe dict with keys: packageId, name, version, badges,
    install_relpath (Mods/<packageId>/), member mapping for extraction.
    """
    info = inspect_zip(path, limits)
    infos = info.pop("_zf_entries")
    with zipfile.ZipFile(path, "r") as zf:
        loc = locate_manifest([i.filename for i in infos],
                              _relpaths(["About/About.xml", "*/About/About.xml"]))
        if not loc:
            raise ModError("E_MANIFEST_MISSING", detail="no About/About.xml found")
        manifest = loc.orig_name
        meta = parse_about_xml(zf, manifest)
        # Build the extraction mapping.  Round 62: the mapping is now anchored
        # at the directory the manifest was FOUND in (loc.base), not at a
        # separate guess about the archive's wrapper.  Derived from one member,
        # the two can no longer disagree about how deep the mod starts.
        root = loc.base or None
        orig_to_stripped = {v: k for k, v in loc.mapping.items()} if loc.mapping else {}
        members = {}
        for zi in infos:
            nm = zi.filename
            if nm.endswith("/"):
                continue
            stripped = orig_to_stripped.get(nm, nm)
            if not stripped:
                continue
            members[stripped] = {"orig": nm, "size": zi.file_size}

    # version fallback: sha256:12 of the file
    version = meta.get("modVersion") or ""
    if not version:
        import hashlib
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        version = "sha256:12:" + h.hexdigest()[:12]

    info.update({
        "packageId": meta["packageId"],
        "name": meta["name"],
        "version": version,
        "version_is_fallback": not bool(meta.get("modVersion")),
        "supportedVersions": meta["supportedVersions"],
        "badges": {"loadAfter": meta["loadAfter"], "dependencies": meta["dependencies"]},
        "install_relpath": f"Mods/{meta['packageId']}",
        "strip_single_root": root,
        "manifest_member": manifest,
        "members": members,
    })
    return info


def extract_to(info: dict, zip_path: str, dest_dir: str, *, member_override: dict | None = None) -> None:
    """Extract a validated archive into dest_dir (caller has already staged dir).

    Dispatches on the format recorded by ``inspect_mod``. The ZIP branch walks
    ``info["members"]`` (stripped -> original) and writes the STRIPPED names, so
    a single-root wrapper disappears. 7z cannot be told to rename while
    extracting, so its branch extracts to scratch and then copies the same
    member map into place — the on-disk layout is therefore identical for both
    formats, which is what the post-commit verify depends on.
    """
    # Round 28 (criterion 3, FOMOD): a caller that processed moduleconfig.xml may
    # pass a reduced/renamed member map. It is still fully containment-checked
    # below; nothing here trusts the override blindly.
    members = member_override if isinstance(member_override, dict) else info["members"]
    if info.get("format") == "7z":
        _extract_7z_normalized(info, zip_path, dest_dir, member_override=members)
        return

    os.makedirs(dest_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        for stripped, meta in members.items():
            # containment guard (defense in depth) — applies to the FOMOD
            # destination too, not just to the archive's own stripped name.
            if stripped.startswith("/") or ".." in stripped.split("/") or "\\" in stripped:
                raise ModError("E_ZIP_SLIP", detail=stripped)
            rel = str(meta.get("destination") or stripped)
            if rel.startswith("/") or ".." in rel.split("/") or "\\" in rel:
                raise ModError("E_ZIP_SLIP", detail=rel)
            out = os.path.join(dest_dir, *rel.split("/"))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with zf.open(meta["orig"]) as src, open(out, "wb") as dst:
                while True:
                    buf = src.read(65536)
                    if not buf:
                        break
                    dst.write(buf)


def _extract_7z_normalized(info: dict, path: str, dest_dir: str, *, member_override: dict | None = None) -> None:
    """Extract a validated .7z and reproduce the ZIP branch's stripped layout.

    7z has no "rename while extracting", so we unpack into a scratch dir and then
    copy exactly the members the inspector approved, keyed by their STRIPPED
    names. Copying (rather than moving the whole tree) is deliberate: it means an
    archive containing files outside ``info["members"]`` — which the validator
    would have rejected anyway — still cannot reach the destination on the way
    through, and the layout matches ZIP byte for byte.
    """
    from . import sevenzip

    scratch = file_drop_scratch()
    try:
        sevenzip.extract_7z(path, scratch)
        os.makedirs(dest_dir, exist_ok=True)
        members = member_override if isinstance(member_override, dict) else info["members"]
        for stripped, meta in members.items():
            if stripped.startswith("/") or ".." in stripped.split("/") or "\\" in stripped:
                raise ModError("E_ZIP_SLIP", detail=stripped)
            src_path = os.path.join(scratch, *str(meta["orig"]).split("/"))
            if not os.path.isfile(src_path):
                raise ModError("E_VERIFY_FAILED",
                               detail="7z did not produce %s" % meta["orig"])
            rel = str(meta.get("destination") or stripped)
            if rel.startswith("/") or ".." in rel.split("/") or "\\" in rel:
                raise ModError("E_ZIP_SLIP", detail=rel)
            out = os.path.join(dest_dir, *rel.split("/"))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            shutil.copyfile(src_path, out)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def file_drop_scratch() -> str:
    """Scratch dir for the 7z extract path (see file_drop._scratch_dir)."""
    base = tempfile.gettempdir()
    for _ in range(8):
        cand = os.path.join(base, "deckymod-7zx-" + uuid.uuid4().hex[:12])
        try:
            os.makedirs(cand)
            return cand
        except FileExistsError:
            continue
    raise ModError("E_ACCESS", detail="could not create a scratch directory for .7z")
