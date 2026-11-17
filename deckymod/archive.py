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
from typing import Dict, List, Tuple
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


def _strip_single_root(entries: List[str]) -> Tuple[str | None, Dict[str, str]]:
    """If all entries share one leading directory component, strip it.

    Returns (root_or_none, mapping from stripped_name -> original_name).
    """
    top = set()
    for e in entries:
        parts = e.split("/")
        if parts and parts[0]:
            top.add(parts[0])
        else:
            return None, {}
    if len(top) != 1:
        return None, {}
    root = next(iter(top))
    # only strip when it is a real wrapper dir (at least one nested path)
    if not any("/" in e.rstrip("/") for e in entries):
        return None, {}
    mapping = {}
    for e in entries:
        stripped = e[len(root) + 1:] if e.startswith(root + "/") else e
        if stripped:
            mapping[stripped] = e
    return root, mapping


def _find_manifest(entries: List[str]) -> str | None:
    """Locate About/About.xml after strip_single_root (or as-is)."""
    root, mapping = _strip_single_root(entries)
    names = list(mapping.keys()) if mapping else entries
    candidates = [n for n in names if n.lower().endswith("about/about.xml")]
    if not candidates:
        # also accept a root-level About.xml (some mods)
        candidates = [n for n in names if n.lower() == "about.xml" or n.lower().endswith("/about.xml")]
    if not candidates:
        return None
    # prefer shortest / most canonical
    candidates.sort(key=lambda n: (n.lower().count("/"), len(n)))
    stripped = candidates[0]
    return mapping.get(stripped, stripped) if mapping else stripped


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
        manifest = _find_manifest([i.filename for i in infos])
        if not manifest:
            raise ModError("E_MANIFEST_MISSING", detail="no About/About.xml found")
        meta = parse_about_xml(zf, manifest)
        # Build the extraction mapping. _strip_single_root() returns
        # {stripped_name: original_name}; INVERT it so a ZIP that wraps all
        # files in one top folder still extracts About/About.xml at the TOP
        # level of Mods/<packageId>/ (not nested under the wrapper directory).
        # The `orig` value keeps the real archive member name for zf.open().
        root, mapping = _strip_single_root([i.filename for i in infos])
        orig_to_stripped = {v: k for k, v in mapping.items()} if mapping else {}
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
