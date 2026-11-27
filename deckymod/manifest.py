"""Descriptor-driven manifest parsing (Steps 2-4 of the selection-B goal).

Design rule: game-specific field names (UniqueID, Name, Version, ...) NEVER
appear in this module nor in the engine layer. They come exclusively from the
descriptor's ``mod_package`` block (``field_map``, ``required_manifest_fields``,
``id_regex``, ``id_normalize``, ``dependency_id_keys``, ``manifest_globs``,
``install_relpath_prefix``). Adding a new game = one descriptor JSON; a new
manifest *format* (not just field names) additionally requires one parser class
registered in ``PARSERS``.

This module is stdlib-only. It reuses ``archive.locate_manifest`` (a purely
structural helper) and ``archive.parse_about_xml`` (the existing RimWorld XML
parser). It does NOT modify either, so the 33 historical RimWorld tests and the
41-green frozen-interpreter path stay byte-identical.

Round 62 note: ``locate_manifest`` replaced ``archive._strip_single_root`` here
because glob matching used ``fnmatch``, whose ``*`` also matches ``/``. That let
a ``*/manifest.json`` glob find a manifest *two* levels below the directory that
had been stripped, and the mod was then installed one folder too deep to load.
``locate_manifest`` derives the root and the member mapping from the same
member, so they cannot disagree; more than one mod in one archive is refused
with ``E_MULTI_MOD_ARCHIVE`` instead of silently picking one.
"""
from __future__ import annotations

import io
import json
import os
import re
import zipfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol

from . import archive, updatekeys
from .errors import ModError

_MAX_MANIFEST_BYTES = 1_000_000


@dataclass
class ParsedManifest:
    """Normalized, game-agnostic identity read from one manifest file."""
    uid: str
    dir_name: str
    name: str
    version: str
    author: object = None
    minimum_api_version: object = None
    entry_dll: object = None
    dependencies: List[str] = field(default_factory=list)
    badges: Dict[str, object] = field(default_factory=dict)
    # Round 49: the places this mod says it publishes itself, parsed from
    # whatever field the descriptor names. Empty for manifests that declare
    # none, which is a fact about the mod, not an error.
    update_keys: List[Dict[str, str]] = field(default_factory=list)
    # Round 67: {dependency id (lowercased): declared minimum version}. A mod
    # may be INSTALLED and still too old for the mod that needs it; SMAPI skips
    # the dependent one and the panel used to say nothing was wrong. Kept apart
    # from ``dependencies`` so no existing caller changes shape.
    dependency_minimums: Dict[str, str] = field(default_factory=dict)


@dataclass
class ManifestHit:
    """Where the manifest member lives inside an archive."""
    orig_name: str
    root: Optional[str]
    mapping: Dict[str, str]  # {stripped: original}, relative to `root`


class ManifestParser(Protocol):
    def find_member(self, entries: List[str],
                    only_root: Optional[str] = None) -> Optional[ManifestHit]: ...

    def parse(self, raw: bytes, member: str) -> ParsedManifest: ...


def _subtree(entries: List[str], root: str) -> List[str]:
    """The entries under ``root``, with ``root + "/"`` cut off.

    Matching is case-insensitive because archive member names and a root the
    caller picked earlier (e.g. from ``list_mod_roots``) may differ in case.
    ``root == ""`` means the archive root, i.e. the entries as they are.
    """
    prefix = root.strip("/")
    if not prefix:
        return list(entries)
    low = prefix.lower() + "/"
    cut = len(prefix) + 1
    return [e[cut:] for e in entries if e.lower().startswith(low)]


def _match_member(entries: List[str], globs: List[str],
                  only_root: Optional[str] = None) -> Optional[ManifestHit]:
    """Locate the manifest, and derive the mod root FROM that member.

    Round 62: this used to strip one wrapper directory off the archive and then
    match descriptor globs against the stripped names with ``fnmatch``, where
    ``*`` matches ``/`` too. ``*/manifest.json`` therefore matched
    ``Pack/ModA/manifest.json`` -- a member two levels below the stripped root
    -- and the extraction mapping (which only knew about ``Pack``) wrote the mod
    to ``Mods/<id>/ModA/``. SMAPI only reads a manifest at a mod directory's
    top level, so a "successful" install produced a folder that never loads and
    that the plugin itself could not uninstall.

    Now the two facts come from one member: the manifest's own path tells us
    both where the mod starts and which files belong to it, so they cannot
    disagree. An archive holding more than one mod is refused instead of
    silently installing whichever manifest sorts first and dropping the rest.
    """
    if only_root is not None:
        # Round 84: the caller named ONE root (from list_mod_roots), so the
        # search happens inside that subtree only and "several mods in one
        # archive" is no longer an error -- the user picked which one to
        # install. The mapping is re-anchored at the requested root (not at
        # whatever root the manifest happens to sit in), because the caller
        # will extract exactly those keys under one directory.
        root = only_root.strip("/")
        sub = _subtree(entries, root)
        loc = archive.locate_manifest(sub, archive._relpaths(globs))
        if not loc:
            return None
        prefix = root + "/" if root else ""
        wanted = prefix + loc.orig_name
        orig_name = next((e for e in entries if e.lower() == wanted.lower()), wanted)
        mapping: Dict[str, str] = {}
        for e in entries:
            if not e or e.endswith("/"):
                continue
            if prefix:
                if not e.lower().startswith(prefix.lower()):
                    continue
                stripped = e[len(prefix):]
            else:
                stripped = e
            if stripped:
                mapping[stripped] = e
        return ManifestHit(orig_name=orig_name, root=root or None, mapping=mapping)
    loc = archive.locate_manifest(entries, archive._relpaths(globs))
    if not loc:
        return None
    if loc.others:
        raise ModError(
            "E_MULTI_MOD_ARCHIVE",
            detail="this archive holds %d mods (%s); import them one at a time"
                   % (len(loc.others) + 1, ", ".join([loc.base or "(root)"] + loc.others)))
    return ManifestHit(orig_name=loc.orig_name, root=loc.base or None,
                       mapping=loc.mapping)


def _coerce_dep_specs(value, id_keys: List[str], optional_key: str = "",
                      minimum_key: str = ""):
    """Extract (dependency id, declared minimum version) pairs.

    Round 67: the minimum version is part of the same declaration as the id, so
    it is read here rather than by re-walking the field somewhere else. A
    missing ``minimum_key`` (descriptor did not declare one) yields an empty
    string, which the scanner reads as "no minimum stated" -- never as "no
    minimum required", because only the mod author knows that.
    """
    out = []
    if value is None:
        return out
    items = value if isinstance(value, list) else [value]
    for it in items:
        if isinstance(it, str):
            out.append((it, ""))
            continue
        if not isinstance(it, dict):
            continue
        if optional_key and it.get(optional_key) is False:
            continue
        picked = None
        for k in id_keys:
            v = it.get(k)
            if isinstance(v, str):
                picked = v
                break
        if picked is None:
            for k, v in it.items():
                if isinstance(v, str):
                    picked = v
                    break
        if picked is None:
            continue
        minimum = ""
        if minimum_key:
            raw_min = it.get(minimum_key)
            if raw_min not in (None, ""):
                minimum = str(raw_min).strip()
        out.append((picked, minimum))
    return out


def _coerce_dep_ids(value, id_keys: List[str],
                    optional_key: str = "") -> List[str]:
    """Extract REQUIRED dependency ids from a manifest field of unknown shape.

    Handles: a plain string, a list of strings, a list of objects (each holding
    an id under ``id_keys``), or a single object. No field name is
    hard-coded here — ``id_keys`` comes from the descriptor.

    Round 27: an optional dependency declared with ``IsRequired: false`` is not
    missing when absent — reporting it as missing turned a shipped content pack
    into a fake warning. ``optional_key`` comes from the descriptor
    (``field_map.dependency_optional_key``) so the parser still knows no game
    field names; when unset, every dependency counts as required (old
    behaviour, unchanged for descriptors that do not declare the key).
    """
    return [pid for pid, _minimum in
            _coerce_dep_specs(value, id_keys, optional_key)]


def _strip_jsonc_text(text: str) -> str:
    """Remove ``/* */`` / ``//`` comments and trailing commas, string-aware.

    Generic JSON-with-comments tolerance, used only when a descriptor opts in
    via ``json_dialect: "jsonc"``. No game field name appears here. The scanner
    respects string literals so URLs like ``https://smapi.io/...`` keep their
    ``//``, escaped quotes stay intact, and newlines inside block comments are
    preserved (line numbers in JSON errors stay meaningful).
    """
    out: List[str] = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            i += 2
            while i < n and text[i] not in "\r\n":
                i += 1
            continue  # keep the newline itself
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                if text[i] in "\r\n":
                    out.append(text[i])
                i += 1
            i = min(i + 2, n)
            continue
        out.append(c)
        i += 1
    cleaned = "".join(out)

    # Second string-aware pass: drop a comma whose next significant char is } or ].
    res: List[str] = []
    j, m = 0, len(cleaned)
    in_str = False
    while j < m:
        c = cleaned[j]
        if in_str:
            res.append(c)
            if c == "\\" and j + 1 < m:
                res.append(cleaned[j + 1])
                j += 2
                continue
            if c == '"':
                in_str = False
            j += 1
            continue
        if c == '"':
            in_str = True
            res.append(c)
            j += 1
            continue
        if c == ",":
            k = j + 1
            while k < m and cleaned[k] in " \t\r\n":
                k += 1
            if k < m and cleaned[k] in "}]":
                j += 1  # drop the trailing comma
                continue
        res.append(c)
        j += 1
    return "".join(res)


def check_entry_dll(entry_dll, members) -> None:
    """Refuse a manifest whose declared EntryDll is not shipped in the archive.

    ``members`` is the extraction map: ``{relative_path: {...}}`` as returned by
    ``file_drop.inspect_mod`` -- exactly the paths that will land in the mod
    folder, so this compares against what the user will actually get, not
    against the raw archive listing (which includes files the mapping drops).

    ``entry_dll`` empty/None means the package declares none (a content pack),
    which is not an error: only a DECLARED but absent file is.
    """
    if entry_dll is None:
        return
    rel = str(entry_dll).strip().replace("\\", "/")
    if not rel:
        return
    if rel.startswith("/") or (len(rel) > 1 and rel[1] == ":") or ".." in rel.split("/"):
        raise ModError(
            "E_MANIFEST_UNSAFE",
            detail="EntryDll %r points outside the mod folder" % entry_dll)
    want = rel.lower()
    have = {str(k).replace("\\", "/").lower() for k in (members or {})}
    if want in have:
        return
    # A leading "./" (or repeated separators) is noise, not a different file.
    squashed = "/".join(p for p in want.split("/") if p not in ("", "."))
    if squashed and squashed in have:
        return
    raise ModError(
        "E_MANIFEST_INVALID",
        detail=("EntryDll %r is not in this archive; the mod would be installed "
                "but fail to load" % entry_dll))


def _apply_aliases(obj: dict, aliases: dict) -> None:
    """Copy alias keys onto their canonical key (descriptor-driven, in place).

    Handles real-world casing variants (e.g. ``UniqueId`` alongside
    ``UniqueID``) without any field name being hard-coded in this module.
    """
    for canonical, alts in (aliases or {}).items():
        if canonical in obj:
            continue
        for alt in (alts if isinstance(alts, list) else [alts]):
            if alt in obj:
                obj[canonical] = obj[alt]
                break


class JsonMapParser:
    """Parse a flat JSON object using a descriptor-driven ``field_map``.

    No JSON field name is hard-coded in this class: every key comes from
    ``config['field_map']`` / ``config['required_manifest_fields']``.
    """
    def __init__(self, config: dict):
        self.config = config
        self.field_map: dict = dict(config.get("field_map") or {})
        self.globs: List[str] = list(config.get("manifest_globs") or [])
        self.required: List[str] = list(config.get("required_manifest_fields") or [])
        pat = config.get("id_regex")
        self.id_regex = re.compile(pat) if pat else None
        self.id_normalize = config.get("id_normalize") or "none"
        self.json_dialect: str = str(config.get("json_dialect") or "strict")
        self.field_aliases: dict = dict(config.get("field_aliases") or {})
        self.dependency_id_keys: List[str] = list(
            self.field_map.get("dependency_id_keys") or []
        )
        # Round 27: descriptor-declared key marking a dependency as optional,
        # so an absent optional dep stops being reported as missing.
        self.dependency_optional_key: str = str(
            self.field_map.get("dependency_optional_key") or ""
        )
        # Round 67: descriptor-declared key carrying the minimum version the
        # dependent mod needs. A dependency that is present but older than this
        # makes SMAPI skip the dependent mod entirely, so the absence of the id
        # was never the whole question.
        self.dependency_minimum_key: str = str(
            self.field_map.get("dependency_minimum_key") or ""
        )

    def find_member(self, entries: List[str],
                    only_root: Optional[str] = None) -> Optional[ManifestHit]:
        return _match_member(entries, self.globs, only_root=only_root)

    def _get(self, obj: dict, role: str):
        key = self.field_map.get(role)
        return obj.get(key) if key else None

    def _decode(self, text: str) -> dict:
        if self.json_dialect == "jsonc":
            try:
                return json.loads(_strip_jsonc_text(text))
            except (ValueError, UnicodeDecodeError):
                pass  # fall through to strict for a clearer error message
        return json.loads(text)

    def parse(self, raw: bytes, member: str) -> ParsedManifest:
        if len(raw) > _MAX_MANIFEST_BYTES:
            raise ModError("E_MANIFEST_INVALID", detail="manifest too large")
        try:
            obj = self._decode(raw.decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError) as e:
            raise ModError("E_MANIFEST_INVALID", detail=f"JSON parse: {e}")
        if not isinstance(obj, dict):
            raise ModError("E_MANIFEST_UNSAFE", detail="manifest is not an object")
        _apply_aliases(obj, self.field_aliases)
        for key in self.required:
            if not obj.get(key):
                raise ModError("E_MANIFEST_UNSAFE", detail=f"missing/empty field {key}")
        uid = self._get(obj, "id")
        if uid is None:
            raise ModError("E_MANIFEST_UNSAFE", detail="id field missing")
        uid = str(uid)
        if self.id_regex and not self.id_regex.match(uid):
            raise ModError("E_MANIFEST_UNSAFE", detail=f"id={uid!r} fails validation")
        dir_name = uid.lower() if self.id_normalize == "lowercase_for_directory" else uid
        deps: List[str] = []
        dep_minimums: Dict[str, str] = {}
        dep_roles = self.field_map.get("dependencies") or []
        if isinstance(dep_roles, str):
            dep_roles = [dep_roles]
        for role in dep_roles:
            for pid, minimum in _coerce_dep_specs(
                    obj.get(role), self.dependency_id_keys,
                    self.dependency_optional_key, self.dependency_minimum_key):
                deps.append(pid)
                if not minimum:
                    continue
                # A mod can be named twice (Dependencies + ContentPackFor); keep
                # the strictest minimum rather than whichever came last.
                key = pid.strip().lower()
                prev = dep_minimums.get(key)
                if prev is None or _version_tuple(minimum) > _version_tuple(prev):
                    dep_minimums[key] = minimum
        author = self._get(obj, "author")
        min_api = self._get(obj, "minimum_api_version")
        entry_dll = self._get(obj, "entry_dll")
        self_declared = self._get(obj, "update_keys")
        return ParsedManifest(
            uid=uid,
            dir_name=dir_name,
            name=str(self._get(obj, "name") or uid),
            version=str(self._get(obj, "version") or ""),
            author=author,
            minimum_api_version=min_api,
            entry_dll=entry_dll,
            dependencies=deps,
            badges={
                "author": author,
                "minimumApiVersion": min_api,
                "entryDll": entry_dll,
            },
            update_keys=updatekeys.parse(self_declared),
            dependency_minimums=dep_minimums,
        )


class XmlAboutParser:
    """Thin adapter over the existing ``archive.parse_about_xml``.

    Registered for manifests whose format is XML (e.g. RimWorld About.xml).
    It does NOT migrate the RimWorld Engine — it only demonstrates that a second
    manifest *format* plugs into the same registry. The live RimWorld path keeps
    using ``archive.inspect_mod`` unchanged.
    """
    def __init__(self, config: dict):
        self.config = config
        self.globs: List[str] = list(
            config.get("manifest_globs")
            or ["About/About.xml", "*/About/About.xml", "about.xml"]
        )

    def find_member(self, entries: List[str],
                    only_root: Optional[str] = None) -> Optional[ManifestHit]:
        return _match_member(entries, self.globs, only_root=only_root)

    def parse(self, raw: bytes, member: str) -> ParsedManifest:
        if len(raw) > _MAX_MANIFEST_BYTES:
            raise ModError("E_MANIFEST_INVALID", detail="manifest too large")
        # Reuse the existing XML parser through a one-entry in-memory ZIP so we
        # do not duplicate ElementTree logic or touch archive.py.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(member, raw)
        with zipfile.ZipFile(buf, "r") as z:
            d = archive.parse_about_xml(z, member)
        uid = str(d.get("packageId") or "")
        return ParsedManifest(
            uid=uid,
            dir_name=uid,
            name=str(d.get("name") or uid),
            version=str(d.get("modVersion") or ""),
            dependencies=list(d.get("dependencies") or []),
            badges={
                "loadAfter": d.get("loadAfter"),
                "dependencies": d.get("dependencies"),
                "supportedVersions": d.get("supportedVersions"),
            },
        )


PARSERS = {
    "json_map": JsonMapParser,
    "xml_about": XmlAboutParser,
}


def parser_for(mod_package: dict) -> ManifestParser:
    name = (mod_package or {}).get("parser") or "json_map"
    cls = PARSERS.get(name)
    if cls is None:
        raise ModError("E_MANIFEST_UNSAFE", detail=f"no manifest parser named {name!r}")
    return cls(mod_package or {})


def _version_tuple(value) -> Tuple[int, ...]:
    """Numeric components of a version string, for comparison only.

    "1.2" and "1.2.0" compare equal (padded), which is what a mod author means.
    A string with no digits at all yields an empty tuple, and callers must treat
    that as "cannot tell" rather than "older" -- the same rule the tree scanner
    uses for an unreadable /proc (round 50) and the quarantine audit used for an
    unreadable journal (round 48).
    """
    parts = re.findall(r"\d+", str(value or ""))
    if not parts:
        return ()
    nums = [int(p) for p in parts[:4]]
    while len(nums) < 4:
        nums.append(0)
    return tuple(nums)


def _find_manifest_in_dir(dir_path: str, globs: List[str]) -> Optional[str]:
    try:
        files = os.listdir(dir_path)
    except OSError:
        return None
    for g in globs:
        base = g.rsplit("/", 1)[-1].lower()
        for f in files:
            if f.lower() == base:
                return os.path.join(dir_path, f)
    return None


def dependents_of(target_id: str, entries) -> List[dict]:
    """Which of ``entries`` would stop loading if ``target_id`` went away.

    Round 71: ``missing_dependencies`` answers "what does this mod need", which
    is only half the question a removal asks. The other half is "who needs
    this": SMAPI skips a mod whose required dependency is absent, so removing a
    library silently stops its dependents from loading -- the panel said
    nothing until the list was rescanned afterwards.

    Only ids this scan actually found with the right dependency are returned;
    an id that is merely *mentioned* somewhere is not a dependent. Rows carry
    id/name/dir so the caller can name a mod the user recognises.
    """
    key = str(target_id or "").strip().lower()
    out: List[dict] = []
    if not key:
        return out
    for m in entries or []:
        uid = str(m.get("uniqueId") or "").strip()
        if uid.lower() == key:
            continue
        deps = m.get("dependencies") or []
        if not any(str(d).strip().lower() == key for d in deps):
            continue
        out.append({
            "id": uid or str(m.get("dir") or ""),
            "name": str(m.get("name") or ""),
            "dir": str(m.get("dir") or ""),
        })
    out.sort(key=lambda r: (r["id"].lower(), r["dir"].lower()))
    return out


def scan_installed_mods(mod_root: str, mod_package: dict,
                        parked_ids=None) -> dict:
    """Read-only enumeration of installed mod directories (Step 2).

    Returns a JSON-safe dict::

        {"mods": [...], "duplicate_ids": [[uid, [dirs]]...],
         "missing_dependencies": [str...]}

    Each ``mods`` entry carries dir/uniqueId/name/version/author/dependencies/
    badges/missing_dependencies, or a ``parse_error`` code when that one mod is
    unreadable. A single bad manifest NEVER aborts the whole scan. No writes,
    no journal.begin — this is safe under read_only posture.

    Round 66: ``parked_ids`` are the ids the caller knows are DISABLED (they
    live in ``.decky-disabled/``, a sibling of ``Mods/``, so this walk cannot
    see them). A disabled dependency is not absent -- it is present and the
    user turned it off. Keeping the two apart matters because
    ``missing_dependencies`` is what the automatic download fetches, and a
    device run proved the cost of conflating them: fetching a parked
    dependency replaced the copy the user had deliberately disabled, and the
    missing list still did not clear. So parked ids are reported in their own
    list, with the remedy the game actually needs (enable it).
    """
    try:
        parser = parser_for(mod_package)
    except ModError:
        return {"mods": [], "duplicate_ids": [], "missing_dependencies": [],
                "parked_dependencies": [], "outdated_dependencies": []}
    globs = list(mod_package.get("manifest_globs") or [])
    parked = {str(x).strip().lower() for x in (parked_ids or []) if str(x).strip()}
    mods: List[dict] = []
    id_to_dirs: Dict[str, List[str]] = {}
    try:
        names = sorted(os.listdir(mod_root))
    except OSError:
        names = []
    for name in names:
        dir_path = os.path.join(mod_root, name)
        if name.startswith(".") or not os.path.isdir(dir_path):
            continue
        entry: dict = {"dir": name}
        mfile = _find_manifest_in_dir(dir_path, globs)
        if not mfile:
            entry["parse_error"] = "E_MANIFEST_MISSING"
            mods.append(entry)
            continue
        try:
            with open(mfile, "rb") as f:
                raw = f.read()
            pm = parser.parse(raw, mfile)
        except ModError as e:
            entry["parse_error"] = e.code
            mods.append(entry)
            continue
        except (OSError, ValueError):
            entry["parse_error"] = "E_MANIFEST_UNSAFE"
            mods.append(entry)
            continue
        uid = pm.uid
        entry.update({
            "uniqueId": uid,
            "name": pm.name,
            "version": pm.version,
            "author": pm.author,
            "dependencies": pm.dependencies,
            "badges": pm.badges,
            # Round 49: where this mod publishes itself. Absent means the
            # manifest declared nothing -- reported as an empty list, never as
            # a guess, because a wrong id opens someone else's mod page.
            "update_keys": list(pm.update_keys),
            # Round 67: what this mod SAYS it needs, so the comparison below
            # happens against a declaration rather than a guess. Absent for
            # manifests that state no minimum -- that is a fact about the mod.
            "dependency_minimums": dict(pm.dependency_minimums or {}),
        })
        id_to_dirs.setdefault(uid.lower(), []).append(name)
        mods.append(entry)

    present = set(id_to_dirs.keys())
    # Round 67: what version each present id actually has, so "installed" can be
    # followed by "but not new enough". An id with no readable version is left
    # out: unknown must never read as outdated.
    id_version: Dict[str, str] = {}
    for m in mods:
        uid = str(m.get("uniqueId") or "").lower()
        ver = str(m.get("version") or "")
        if uid and ver:
            id_version.setdefault(uid, ver)
    minimums: Dict[str, str] = {}
    for m in mods:
        for dep_id, minimum in (m.get("dependency_minimums") or {}).items():
            minimums.setdefault(dep_id, minimum)
    missing: set = set()
    parked_gaps: set = set()
    outdated: List[dict] = []
    for m in mods:
        deps = m.get("dependencies") or []
        mins = m.get("dependency_minimums") or {}
        absent = [d for d in deps if d.lower() not in present]
        # Round 66: split "absent" into "present but disabled" and "truly not
        # here". Only the second is a download problem.
        parked_here = [d for d in absent if d.lower() in parked]
        missing_here = [d for d in absent if d.lower() not in parked]
        m["missing_dependencies"] = missing_here
        m["parked_dependencies"] = parked_here
        for d in missing_here:
            missing.add(d)
        for d in parked_here:
            parked_gaps.add(d)
        # Round 67: present, not parked, and older than the dependent mod asks
        # for. SMAPI skips the dependent mod in this state, so "nothing is
        # missing" was a half-truth: the remedy is "update it", not "download
        # it", and not "enable it" either. Reported as its own list.
        stale: List[dict] = []
        for d in deps:
            key = d.lower()
            if key in parked or key not in present:
                continue
            need = mins.get(key) or ""
            have = id_version.get(key) or ""
            if not need or not have:
                continue
            want_t, have_t = _version_tuple(need), _version_tuple(have)
            if not want_t or not have_t:
                continue
            if have_t < want_t:
                stale.append({"id": d, "required": need, "installed": have})
        m["outdated_dependencies"] = stale
        # Round 71: the reverse direction, from the pass already in hand.
        # "who needs me" is what a removal has to warn about.
        m["dependents"] = []
        for row in stale:
            outdated.append({
                "from": str(m.get("uniqueId") or m.get("dir") or ""),
                "id": row["id"],
                "required": row["required"],
                "installed": row["installed"],
            })
    # Round 71: fill the reverse map once, from the entries above.
    for m in mods:
        m["dependents"] = dependents_of(m.get("uniqueId") or m.get("dir"), mods)
    duplicate_ids = [
        [uid, dirs] for uid, dirs in sorted(id_to_dirs.items()) if len(dirs) > 1
    ]
    outdated.sort(key=lambda r: (r["id"].lower(), r["from"].lower()))
    return {
        "mods": mods,
        "duplicate_ids": duplicate_ids,
        "missing_dependencies": sorted(missing),
        # Round 67: dependencies that are installed but older than the mod that
        # needs them. Separate from ``missing`` because the remedy differs.
        "outdated_dependencies": outdated,
        # Round 66: dependencies the user owns but has disabled. Kept apart
        # from ``missing_dependencies`` on purpose -- the panel can offer
        # "enable it" and the fetcher must not touch it.
        "parked_dependencies": sorted(parked_gaps),
    }
