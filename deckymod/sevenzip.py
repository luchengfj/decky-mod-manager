"""7-Zip support (goal item 3 asks for .zip **and** .7z import).

Why this is a separate module and not a branch inside ``archive.py``:

* The stdlib cannot read 7z. There is no ``py7zr`` on the Deck and we must not
  add a dependency, so the only honest options are (a) shell out to the ``7z``
  binary that SteamOS already ships, or (b) refuse .7z entirely. The goal asks
  for .7z, so we shell out — but in the narrowest possible way.
* ``7z`` is an external process, so the security analysis is different from
  ``zipfile``: we must NOT let it write before we have validated the entry list.
  Therefore: list first (``7z l -slt``), validate every name with the same rules
  the ZIP path uses, and only then extract.
* The runner is **injectable**. On a machine with no 7z (the Windows dev box)
  the unit tests pass a fake runner, so the validation logic is still covered
  offline. ``default_runner`` is the only thing that touches subprocess.

Threat model kept from the ZIP path: absolute paths, ``..`` traversal, backslash
separators, symlinks/hardlinks, devices, entries that resolve outside the target,
forbidden extensions, entry-count and size caps. 7z reports the unix mode in the
``Attributes`` field (``l`` prefix = link), which is what we check for links.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Callable, Dict, List, Optional

from .errors import ModError

# 7z exit codes are 0 ok, 1 warning, 2 fatal. 1 means "some files could not be
# read but the operation completed", which for a listing is still usable; we only
# treat 2 and above as failure.
_OK_CODES = (0, 1)

_SEVEN_ZIP_CANDIDATES = ("7z", "7za", "7zr", "7zz")

# Test-only injection point. Production leaves this None and every call uses
# ``default_runner``. The test suite sets it to a fake so the whole
# inspect -> extract path can be exercised on a machine with no 7z binary
# (the Windows dev box), which is otherwise the one part of .7z support that
# could only be verified on the Deck.
_test_runner: Optional[Callable[..., Dict[str, object]]] = None
_test_tool: Optional[str] = None


def set_runner(fn: Optional[Callable[..., Dict[str, object]]],
               tool: Optional[str] = None) -> None:
    """Install (or clear, with None) a runner override. Tests only.

    Pinning ``tool`` as well lets the full inspect -> install path run on a
    machine with no 7z binary: every call site reaches ``find_tool()``, so
    overriding it here keeps production code free of test branches.
    """
    global _test_runner, _test_tool
    _test_runner = fn
    _test_tool = tool if fn else None


def _runner_or_default(runner):
    return runner or _test_runner or default_runner


def tool_available(tool: Optional[str] = None) -> bool:
    """True when a real 7z can be executed (or the caller pinned one)."""
    return bool(_resolve_tool(tool))


def _resolve_tool(tool: Optional[str] = None) -> Optional[str]:
    """Explicit tool, else a pinned test tool, else whatever is on PATH."""
    return tool or _test_tool or find_tool()


def find_tool() -> Optional[str]:
    """Absolute path of a usable 7z binary, or None.

    Checked with shutil.which so the caller can produce a readable error rather
    than an OSError deep inside a subprocess call.
    """
    for name in _SEVEN_ZIP_CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    return None


def default_runner(argv: List[str], cwd: Optional[str] = None) -> Dict[str, object]:
    """Run 7z and return {code, stdout, stderr}. Never raises for a non-zero exit."""
    try:
        proc = subprocess.run(
            argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=300, check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise ModError("E_BAD_ARCHIVE", detail=f"cannot run 7z: {type(e).__name__}: {e}")
    return {
        "code": proc.returncode,
        "stdout": proc.stdout.decode("utf-8", "replace"),
        "stderr": proc.stderr.decode("utf-8", "replace"),
    }


def _parse_slt(out: str) -> List[Dict[str, str]]:
    """Parse `7z l -slt -ba` output into one dict per entry.

    With ``-ba`` 7z prints only the entry blocks: repeating ``key = value``
    groups separated by a blank line, no archive header, no footer. We still
    tolerate a leading ``----------`` separator (that is what the verbose
    ``-slt`` form emits before the entries) by discarding everything before it,
    so a future flag change cannot turn the archive stanza into a phantom entry.
    Blocks without a ``Path`` key are dropped for the same reason; a block whose
    ``Path`` is present but empty is kept so the validator can reject it loudly
    instead of it disappearing into "no entries".
    """
    blocks: List[Dict[str, str]] = []
    current: Dict[str, str] = {}
    for raw in out.splitlines():
        line = raw.rstrip("\r")
        if line.startswith("----------"):
            current = {}
            blocks = []
            continue
        if not line:
            if current:
                blocks.append(current)
            current = {}
            continue
        if " = " in line:
            key, value = line.split(" = ", 1)
            current[key.strip()] = value
    if current:
        blocks.append(current)
    return [b for b in blocks if "Path" in b]


def _attrs(entry: Dict[str, str]) -> str:
    """Lower-cased Attributes field.

    7z prints unix modes ("drwxr-xr-x", "lrwxrwxrwx") for archives made on
    Linux and Windows attribute strings ("D....", "....A") for archives made on
    Windows. Lower-casing lets one prefix test cover both, which matters because
    a Windows-made .7z can contain directories too.
    """
    return (entry.get("Attributes") or "").strip().lower()


def _check_entry(entry: Dict[str, str], forbidden_ext, max_depth: int,
                 limits: Dict[str, int]) -> str:
    """Validate one 7z entry name; return the normalized name.

    Mirrors ``archive._validate_member_name`` deliberately rather than calling it,
    because 7z reports names with the archive's own separator and we want the
    failure detail to say "7z" so the log makes the source obvious.
    """
    name = entry.get("Path") or ""
    if not name:
        raise ModError("E_UNSAFE_ENTRY", detail="7z entry with an empty path")
    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        raise ModError("E_UNSAFE_ENTRY", detail=f"absolute path in 7z: {name}")
    if "\\" in name:
        raise ModError("E_UNSAFE_ENTRY", detail=f"backslash path in 7z: {name}")
    parts = name.split("/")
    if any(p == ".." for p in parts):
        raise ModError("E_PATH_ESCAPE", detail=f"parent traversal in 7z: {name}")
    if any(p == "." for p in parts):
        raise ModError("E_UNSAFE_ENTRY", detail=f"dot segment in 7z: {name}")
    if len([p for p in parts if p]) > max_depth:
        raise ModError("E_UNSAFE_ENTRY", detail=f"too deep in 7z: {name}")

    attrs = _attrs(entry)
    # 7z prints unix modes as e.g. "lrwxrwxrwx" for a symlink and "drwxr-xr-x"
    # for a directory; Windows-made archives show "D...." for a directory and
    # "l" is never a Windows attribute, so the lower-cased prefix test is safe
    # for both flavours.
    if attrs.startswith("l"):
        raise ModError("E_UNSAFE_ENTRY", detail=f"symlink in 7z: {name}")
    if attrs.startswith("c") or attrs.startswith("b"):
        raise ModError("E_UNSAFE_ENTRY", detail=f"device entry in 7z: {name}")

    if forbidden_ext:
        ext = os.path.splitext(name.rstrip("/"))[1].lower()
        if ext in forbidden_ext:
            raise ModError("E_UNSAFE_ENTRY", detail=f"forbidden extension in 7z: {name} ({ext})")

    try:
        size = int(entry.get("Size") or 0)
    except ValueError:
        size = 0
    if size > limits["max_uncompressed_bytes"]:
        raise ModError("E_ZIP_BOMB", detail=f"7z entry too large: {name}")
    return name


def inspect_7z(path: str, limits: Dict[str, int], forbidden_ext=None,
               runner: Optional[Callable[..., Dict[str, object]]] = None,
               tool: Optional[str] = None) -> Dict[str, object]:
    """List + validate a .7z without writing anything.

    Returns {"entries": [{name, size, is_dir}], "total_uncompressed": int,
             "tool": str}. Raises ModError with a stable code on any violation.
    """
    size = os.path.getsize(path)
    if size > limits["max_compressed_bytes"]:
        raise ModError("E_ZIP_BOMB", detail=f"7z compressed {size} > {limits['max_compressed_bytes']}")

    run = _runner_or_default(runner)
    exe = _resolve_tool(tool)
    if not exe:
        raise ModError(
            "E_BAD_ARCHIVE",
            detail="no 7z binary found (looked for 7z/7za/7zr/7zz); .7z import needs 7-Zip",
        )

    res = run([exe, "l", "-slt", "-ba", path])
    code = int(res.get("code", 99))
    if code not in _OK_CODES:
        raise ModError(
            "E_BAD_ARCHIVE",
            detail="7z could not list the archive (exit %d): %s"
                   % (code, str(res.get("stderr") or "").strip()[:200]),
        )

    blocks = _parse_slt(str(res.get("stdout") or ""))
    if not blocks:
        raise ModError("E_BAD_ARCHIVE", detail="7z listed no entries")
    if len(blocks) > limits["max_entries"]:
        raise ModError("E_ZIP_BOMB", detail=f"{len(blocks)} entries > {limits['max_entries']}")

    entries: List[Dict[str, object]] = []
    total = 0
    seen = set()
    for entry in blocks:
        name = _check_entry(entry, forbidden_ext, limits["max_path_depth"], limits)
        if name in seen:
            raise ModError("E_DUPLICATE_ENTRY", detail=name)
        seen.add(name)
        try:
            entry_size = int(entry.get("Size") or 0)
        except ValueError:
            entry_size = 0
        total += entry_size
        if total > limits["max_uncompressed_bytes"]:
            raise ModError("E_ZIP_BOMB", detail="total uncompressed exceeds limit")
        entries.append({"name": name, "size": entry_size,
                        "is_dir": _attrs(entry).startswith("d")})

    return {"entries": entries, "total_uncompressed": total, "tool": exe}


def extract_7z(path: str, dest_dir: str,
               runner: Optional[Callable[..., Dict[str, object]]] = None,
               tool: Optional[str] = None) -> None:
    """Extract a .7z that has ALREADY passed ``inspect_7z``.

    ``-y`` accepts overwrite prompts, ``-bd`` disables progress output. We must
    never call this before inspect_7z: extraction is the step that writes.
    """
    run = _runner_or_default(runner)
    exe = _resolve_tool(tool)
    if not exe:
        raise ModError("E_BAD_ARCHIVE", detail="no 7z binary found for extraction")
    res = run([exe, "x", "-y", "-bd", "-o" + dest_dir, path])
    code = int(res.get("code", 99))
    if code not in _OK_CODES:
        raise ModError(
            "E_OP_FAILED",
            detail="7z extraction failed (exit %d): %s"
                   % (code, str(res.get("stderr") or "").strip()[:200]),
        )


def is_7z(path: str) -> bool:
    """Extension check plus the 37 7A BC AF 27 1C magic, so a renamed file fails."""
    if not path.lower().endswith(".7z"):
        return False
    try:
        with open(path, "rb") as f:
            return f.read(6) == b"7z\xbc\xaf'\x1c"
    except OSError:
        return False
