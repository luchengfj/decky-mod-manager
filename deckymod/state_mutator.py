"""ModsConfig.xml surgical-line-edit mutator (§3.3 / R1 review #3).

KEY DECISION (approved): we do NOT re-serialize with ElementTree. Re-serializing
would drop comments, indentation, the <version> element, and possibly change
encoding. Instead:

  * ElementTree parses the file READ-ONLY to validate structure + extract the
    ordered list of <activeMods>/<li> packageIds (and the Core invariant).
  * The WRITE inserts or deletes EXACTLY ONE line "<li>packageId</li>" inside
    the <activeMods> ... </activeMods> block, leaving every other byte of the
    file unchanged.
  * Core invariant: ludeon.rimworld must be present AND be the first <li>.
    Missing / out of position -> E_CORE_MISSING, operation refused.
  * preserve_unknown_entries: DLC (ludeon.rimworld.*), Workshop <li> entries,
    and any <li> we did not create are left byte-for-byte untouched. We only
    add/remove the single <li> for the managed packageId.

RimWorld may rewrite ModsConfig.xml on quit -> the engine does verify_on_open
with a stored fingerprint and raises E_STATE_EXTERNAL on drift (§3.3 / §5.2).
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import List
from xml.etree import ElementTree as ET

from .errors import ModError

CORE_ID = "ludeon.rimworld"


def fingerprint(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def parse_state(data: bytes) -> dict:
    """Read-only validation + extraction. Returns JSON-safe dict."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise ModError("E_STATE_CORRUPT", detail=f"XML parse: {e}")
    active = root.find("activeMods")
    if active is None:
        raise ModError("E_STATE_CORRUPT", detail="no <activeMods> element")
    ids = []
    for li in active.findall("li"):
        ids.append((li.text or "").strip())
    # Core invariant
    if not ids or ids[0] != CORE_ID:
        raise ModError("E_CORE_MISSING", detail=f"first activeMod is {ids[0] if ids else '<empty>'!r}, expected {CORE_ID!r}")
    return {
        "activeMods": ids,
        "core_present": ids[0] == CORE_ID,
        "fp": fingerprint(data),
        "encoding": "utf-8",
        "size": len(data),
    }


def _find_active_block(text: str):
    """Locate the <activeMods>...</activeMods> byte span (string indices).

    Returns (open_tag_end, close_tag_start, inner_text). Tolerates attributes
    on the open tag. Does not use regex across newlines greedily.
    """
    m_open = re.search(r"<activeMods(?:\s[^>]*)?>", text)
    if not m_open:
        raise ModError("E_STATE_CORRUPT", detail="<activeMods> open tag not found")
    m_close = re.search(r"</activeMods\s*>", text[m_open.end():])
    if not m_close:
        raise ModError("E_STATE_CORRUPT", detail="</activeMods> close tag not found")
    open_end = m_open.end()
    close_start = m_open.end() + m_close.start()
    return open_end, close_start, text[open_end:close_start]


def _detect_indent(inner: str) -> str:
    """Match the indentation/line style of existing <li> lines."""
    m = re.search(r"(\r?\n)([ \t]*)<li>", inner)
    if m:
        return m.group(1) + m.group(2)
    return "\n"  # fallback


def _detect_eol(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def add_entry(data: bytes, package_id: str) -> bytes:
    """Insert <li>packageId</li> at the END of <activeMods>, preserving all
    other bytes. Idempotent: if already present, return data unchanged.
    """
    state = parse_state(data)  # validates + Core invariant
    if package_id in state["activeMods"]:
        return data  # already enabled; no-op
    text = data.decode("utf-8")
    open_end, close_start, inner = _find_active_block(text)
    eol_indent = _detect_indent(inner) or _detect_eol(text)
    # Insert right before the closing tag, after the last existing <li> line.
    # We append a single new line, matching the file's EOL + indentation.
    insertion = f"{eol_indent}<li>{_xml_escape(package_id)}</li>"
    # place before the trailing whitespace that precedes </activeMods>
    trailing = re.search(r"(\s*)$", inner)
    trail = trailing.group(1) if trailing else ""
    inner_wo_trail = inner[: len(inner) - len(trail)] if trail else inner
    new_inner = inner_wo_trail + insertion + trail
    new_text = text[:open_end] + new_inner + text[close_start:]
    return new_text.encode("utf-8")


def remove_entry(data: bytes, package_id: str) -> bytes:
    """Remove EXACTLY the one <li>packageId</li> line we manage, preserving
    all other bytes (including unknown <li> entries and Core).
    """
    state = parse_state(data)  # validates + Core invariant
    if package_id not in state["activeMods"]:
        return data  # already disabled; no-op
    if package_id == CORE_ID:
        raise ModError("E_CORE_MISSING", detail="refusing to remove the locked Core entry")
    text = data.decode("utf-8")
    open_end, close_start, inner = _find_active_block(text)
    # match a whole line containing exactly this <li>...</li>
    esc = re.escape(_xml_escape(package_id))
    line_re = re.compile(r"(?:^|\r?\n)[ \t]*<li>\s*" + esc + r"\s*</li>[ \t]*(?=\r?\n|$)")
    m = line_re.search(inner)
    if not m:
        raise ModError("E_STATE_CORRUPT", detail=f"could not locate a removable <li> line for {package_id}")
    new_inner = inner[: m.start()] + inner[m.end():]
    new_text = text[:open_end] + new_inner + text[close_start:]
    # verify the result still parses and Core is intact
    parse_state(new_text.encode("utf-8"))
    return new_text.encode("utf-8")


def _xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;").replace("'", "&apos;"))


def read_state_file(path: str) -> tuple:
    """Return (data_bytes, parsed_state_dict, os.stat_result) for state file."""
    if not os.path.isfile(path):
        raise ModError("E_STATE_MISSING", detail=path)
    if os.path.islink(path):
        raise ModError("E_STATE_SYMLINK", detail=path)
    try:
        with open(path, "rb") as f:
            data = f.read()
        st = os.stat(path)
    except OSError as e:
        from .fsops import map_oserror
        raise map_oserror(e)
    return data, parse_state(data), st
