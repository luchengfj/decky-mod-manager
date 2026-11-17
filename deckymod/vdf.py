"""Minimal, dependency-free Valve KeyValues (VDF) parser (§3.7).

We need exactly two things from Steam's text files:
  * libraryfolders.vdf  -> the list of library roots ("path")
  * appmanifest_<appid>.acf -> the "installdir" value

We deliberately do NOT hard-code the schema: Steam has shipped several
variants (LibraryFolders vs libraryfolders, entries with "path"/"apps" keys,
numeric 0/1/2 entries, config/ vs steamapps/ location, quoted numbers). This
parser is generic (nested brace blocks, quoted keys/values) and the CALLER
searches recursively for any dict containing a "path" key, so all variants
work without changes. ⚠️ V10/V17: verify against locked Steam client version.
"""

from __future__ import annotations

from typing import Any, Dict, List


class VDFError(Exception):
    pass


def _tokenize(text: str):
    """Yield (kind, value): kind in {str, '{', '}'}."""
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":  # // comment
            j = text.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":  # /* comment */
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if c == "{" or c == "}":
            yield c, c
            i += 1
            continue
        if c == '"':
            i += 1
            buf = []
            while i < n:
                ch = text[i]
                if ch == "\\" and i + 1 < n:
                    nxt = text[i + 1]
                    buf.append({"n": "\n", "t": "\t", "r": "\r"}.get(nxt, nxt))
                    i += 2
                    continue
                if ch == '"':
                    i += 1
                    break
                buf.append(ch)
                i += 1
            yield "str", "".join(buf)
            continue
        # unquoted token
        j = i
        while j < n and text[j] not in " \t\r\n{}\"":
            j += 1
        yield "str", text[i:j]
        i = j


def parse_vdf(text: str) -> Dict[str, Any]:
    tokens = list(_tokenize(text))
    pos = 0

    def parse_block() -> Dict[str, Any]:
        nonlocal pos
        out: Dict[str, Any] = {}
        while pos < len(tokens):
            kind, val = tokens[pos]
            if kind == "}":
                pos += 1
                return out
            if kind != "str":
                raise VDFError(f"unexpected token {kind}")
            key = val
            pos += 1
            if pos >= len(tokens):
                out[key] = ""
                break
            k2, v2 = tokens[pos]
            if k2 == "{":
                pos += 1
                out[key] = parse_block()
            elif k2 == "}":
                # key with no value
                out[key] = ""
            elif k2 == "str":
                # a value; but it might be a key of a nested block opened next
                pos += 1
                if pos < len(tokens) and tokens[pos][0] == "{":
                    pos += 1
                    out[key] = {v2: parse_block()}  # unusual; tolerate
                else:
                    out[key] = v2
            else:
                out[key] = ""
        return out

    # top-level is one or more "root" { ... } blocks
    result: Dict[str, Any] = {}
    while pos < len(tokens):
        kind, val = tokens[pos]
        pos += 1
        if kind == "str":
            if pos < len(tokens) and tokens[pos][0] == "{":
                pos += 1
                result[val] = parse_block()
            elif pos < len(tokens) and tokens[pos][0] == "str":
                result[val] = tokens[pos][1]
                pos += 1
    return result


def find_library_paths(parsed: Dict[str, Any]) -> List[str]:
    """Recursively collect any 'path' string value (schema-independent)."""
    found: List[str] = []
    seen = set()

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k.lower() == "path" and isinstance(v, str) and v:
                    if v not in seen:
                        seen.add(v)
                        found.append(v)
                else:
                    walk(v)
        elif isinstance(node, list):
            for x in node:
                walk(x)

    walk(parsed)
    return found


def get_installdir(parsed: Dict[str, Any]) -> str | None:
    """Find 'installdir' (case-insensitive) anywhere in the appmanifest."""

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k.lower() == "installdir" and isinstance(v, str) and v:
                    return v
                r = walk(v)
                if r:
                    return r
        elif isinstance(node, list):
            for x in node:
                r = walk(x)
                if r:
                    return r
        return None

    return walk(parsed)
