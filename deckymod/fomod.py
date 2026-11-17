"""Minimal, safe FOMOD ``moduleconfig.xml`` support (criterion 3).

Scope (deliberately first-version):
  * Detect ``fomod/moduleconfig.xml`` inside a validated ZIP/.7z archive.
  * Parse install steps, groups and plugins into a JSON-safe descriptor that the
    UI can render as single-select (radio) and multi-select (checkbox) controls.
  * Given the user's choices, compute the ``source -> destination`` file map so
    only the selected plugin files are written.
  * On ANY unparseable / unsafe config, raise :class:`FomodError` with a readable
    message. The caller must then fall back to a plain extract — never silently
    install a subset, and never fail the whole install.

Safety rules (non-negotiable):
  * No DTD, no ``<!ENTITY>``: rejected before any XML parser sees the bytes.
  * No external file/network access: ElementTree is used with a plain parser and
    the config is read from bytes already inside the validated archive.
  * Field/count caps keep a hostile config from expanding into huge UI payloads.
  * Nothing here guesses a game path; ``destination`` values are relative to the
    mod root and are re-checked for containment by the extractor.
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

MAX_CONFIG_BYTES = 2_000_000
MAX_STEPS = 20
MAX_GROUPS_PER_STEP = 20
MAX_OPTIONS_PER_GROUP = 40
MAX_FILES_PER_OPTION = 400

_SINGLE = frozenset({"selectone", "selectexactlyone", "selectatmostone"})
_MULTI = frozenset({"selectany", "selectall"})
# A plugin type name that is not usable / not selected by default.
_SKIP_TYPES = frozenset({"notusable"})
_DEFAULT_ON = frozenset({"required", "recommended"})


class FomodError(ValueError):
    """A readable, user-facing FOMOD problem; ``code`` is a stable label."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _tag(el) -> str:
    """Local name of an ElementTree element, lower-cased (namespace tolerant)."""
    tag = getattr(el, "tag", "")
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].lower()


def find_moduleconfig(names: List[str]) -> Optional[str]:
    """Return the archive member that is a FOMOD config, or ``None``.

    Accepts a leading single-root wrapper (e.g. ``MyMod/fomod/moduleconfig.xml``)
    and is case-insensitive, matching how SMAPI mods actually ship.
    """
    for n in names:
        parts = [p for p in str(n).replace("\\", "/").split("/") if p]
        if len(parts) >= 2 and parts[-2].lower() == "fomod" and parts[-1].lower() == "moduleconfig.xml":
            return n
    return None


def _clean(raw: bytes) -> str:
    if len(raw) > MAX_CONFIG_BYTES:
        raise FomodError("FOMOD_TOO_LARGE", "FOMOD config is larger than %d bytes" % MAX_CONFIG_BYTES)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise FomodError("FOMOD_BAD_XML", "FOMOD config is not UTF-8: %s" % e)
    upper = text.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        raise FomodError("FOMOD_UNSAFE_XML",
                         "FOMOD config declares a DTD/ENTITY; refusing to parse it, using plain extract")
    return text


def _files_of(plugin) -> List[dict]:
    out: List[dict] = []
    for files in list(plugin):
        if _tag(files) != "files":
            continue
        for f in list(files):
            kind = _tag(f)
            source = (f.get("source") or "").strip().replace("\\", "/")
            if not source:
                continue
            destination = (f.get("destination") or "").strip().replace("\\", "/")
            if kind == "file":
                out.append({"source": source, "destination": destination or source, "kind": "file"})
            elif kind == "folder":
                out.append({"source": source.rstrip("/"),
                            "destination": (destination or source).rstrip("/"), "kind": "folder"})
    return out[:MAX_FILES_PER_OPTION]


def _default_selected(plugin) -> bool:
    for td in list(plugin):
        if _tag(td) != "typedescriptor":
            continue
        for t in list(td):
            if _tag(t) != "type":
                continue
            name = (t.get("name") or "").strip().lower()
            if name in _SKIP_TYPES:
                return False
            return name in _DEFAULT_ON
    return False


def parse(raw: bytes) -> dict:
    """Parse a FOMOD config into a JSON-safe ``{"steps":[...]}`` descriptor.

    Raises :class:`FomodError` with a readable message when the config is unsafe,
    malformed, or contains nothing selectable — the caller then falls back to a
    plain extract and shows the message to the user.
    """
    text = _clean(raw)
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(text)
    except ImportError:
        raise FomodError("FOMOD_UNAVAILABLE",
                         "XML parser is unavailable in this runtime; using plain extract")
    except Exception as e:
        raise FomodError("FOMOD_BAD_XML", "cannot parse FOMOD config: %s" % e)
    if _tag(root) != "module":
        raise FomodError("FOMOD_UNSUPPORTED", "FOMOD root is not <module>; using plain extract")

    steps: List[dict] = []
    warnings: List[str] = []
    for step in list(root):
        if _tag(step) != "installsteps":
            continue
        for st in list(step):
            if _tag(st) != "installstep" or len(steps) >= MAX_STEPS:
                continue
            groups: List[dict] = []
            for ofg in list(st):
                if _tag(ofg) != "optionalfilegroups":
                    continue
                for g in list(ofg):
                    if _tag(g) != "group" or len(groups) >= MAX_GROUPS_PER_STEP:
                        continue
                    gtype = (g.get("type") or "").strip().lower()
                    if gtype in _SINGLE:
                        mode = "single"
                    elif gtype in _MULTI:
                        mode = "multi"
                    else:
                        warnings.append("group %r has unknown type %r; treated as multi-select"
                                        % (g.get("name"), gtype))
                        mode = "multi"
                    options: List[dict] = []
                    for plugins in list(g):
                        if _tag(plugins) != "plugins":
                            continue
                        for p in list(plugins):
                            if _tag(p) != "plugin" or len(options) >= MAX_OPTIONS_PER_GROUP:
                                continue
                            options.append({
                                "name": (p.get("name") or "").strip(),
                                "description": _description(p),
                                "selected": _default_selected(p),
                                "files": _files_of(p),
                            })
                    groups.append({"name": (g.get("name") or "").strip(),
                                   "mode": mode, "options": options})
            if groups:
                steps.append({"name": (st.get("name") or "").strip(), "groups": groups})
    if not steps or not any(g["options"] for s in steps for g in s["groups"]):
        raise FomodError("FOMOD_NO_OPTIONS",
                         "FOMOD has no selectable install options; using plain extract")
    return {"steps": steps, "warnings": warnings}


def _description(plugin) -> str:
    for child in list(plugin):
        if _tag(child) == "description":
            txt = "".join(child.itertext()).strip()
            return txt[:500]
    return ""


def _safe_relative(path: str) -> bool:
    if not path or path.startswith("/") or "\\" in path:
        return False
    parts = path.split("/")
    return all(p not in ("", ".", "..") for p in parts)


def choose(parsed: dict, choices: dict) -> dict:
    """Resolve user choices into the file map to actually install.

    ``choices`` maps ``"<step>.<group>"`` (0-based string indices, e.g.
    ``"0.0"``) to a list of selected option names. Unmentioned groups keep their
    defaults. Returns ``{"files":[{source,destination,kind}...], "warnings":[...]}``.
    """
    if not isinstance(parsed, dict) or not isinstance(choices, dict):
        raise FomodError("FOMOD_BAD_CHOICE", "invalid FOMOD selection payload")
    files: List[dict] = []
    warnings: List[str] = list(parsed.get("warnings") or [])
    seen_sources: set = set()
    for si, step in enumerate(parsed.get("steps") or []):
        for gi, group in enumerate(step.get("groups") or []):
            key = "%d.%d" % (si, gi)
            opts = group.get("options") or []
            raw = choices.get(key)
            if raw is None:
                selected = [o.get("name") for o in opts if o.get("selected")]
            elif isinstance(raw, list):
                selected = [str(x) for x in raw]
            else:
                selected = [str(raw)]
            if group.get("mode") == "single" and len(selected) > 1:
                warnings.append("group %s is single-select; kept the first choice" % key)
                selected = selected[:1]
            by_name = {o.get("name"): o for o in opts}
            for name in selected:
                opt = by_name.get(name)
                if opt is None:
                    warnings.append("unknown option %r in group %s; ignored" % (name, key))
                    continue
                for f in opt.get("files") or []:
                    src = str(f.get("source") or "")
                    dst = str(f.get("destination") or src)
                    if not _safe_relative(src) or not _safe_relative(dst):
                        warnings.append("unsafe FOMOD path %r -> %r; ignored" % (src, dst))
                        continue
                    if src in seen_sources:
                        continue
                    seen_sources.add(src)
                    files.append({"source": src, "destination": dst,
                                  "kind": f.get("kind") or "file"})
    if not files:
        raise FomodError("FOMOD_EMPTY_SELECTION",
                         "no files matched the FOMOD selection; using plain extract")
    return {"files": files, "warnings": warnings}


def apply_to_members(info: dict, files: List[dict]) -> dict:
    """Map FOMOD ``source`` paths onto the archive's approved member map.

    Returns a NEW member dict ``{stripped: {orig,size,destination}}`` containing
    only selected files. A source that is not in the archive is skipped with a
    warning (never silently dropped without telling the user).
    """
    members = info.get("members") or {}
    # Also allow matching by the original (un-stripped) archive name.
    by_orig = {str(m.get("orig")): k for k, m in members.items()}
    out: dict = {}
    warnings: List[str] = []
    for f in files:
        src = str(f.get("source") or "")
        # ``members`` is {stripped: meta}; the key IS the stripped name.
        key = src if src in members else by_orig.get(src)
        if key is None:
            # folder rules: match every approved member under the source prefix
            prefix = src.rstrip("/") + "/"
            hits = [k for k in members if k.startswith(prefix)]
            if not hits:
                warnings.append("FOMOD source %r is not in the archive; skipped" % src)
                continue
            for k in hits:
                rel = k[len(prefix):]
                dest = str(f.get("destination") or src).rstrip("/") + "/" + rel
                out[k] = {"orig": members[k]["orig"], "size": members[k].get("size", 0),
                          "destination": dest}
            continue
        base_dest = str(f.get("destination") or key)
        out[key] = {"orig": members[key]["orig"], "size": members[key].get("size", 0),
                    "destination": base_dest}
    return {"members": out, "warnings": warnings}
