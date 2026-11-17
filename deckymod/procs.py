"""Is the game running right now? A read-only answer from /proc.

Why this module exists
----------------------
``safety.refuse_if_game_running`` has been ``true`` in the Stardew descriptor
since Round 39, but the implementation only ever read the ``DECKYMOD_GAME_RUNNING``
environment variable, and nothing in production sets it. So the flag was a
promise the code did not keep: the plugin would uninstall a mod while the game
had its ``.dll`` files open. That is the one failure this plugin can cause that
no rollback repairs, because the game may write a corrupt save before it dies.

Measured on this Deck before writing a line of it:

* ``/proc`` is mounted plainly (``proc /proc proc rw,nosuid,nodev,noexec``) and
  320 of 322 processes expose a readable ``cmdline`` to uid 1000.
* The plugin process itself cannot read its own ``/proc/self/environ`` (the
  setuid drop clears ``dumpable``) -- a different file, and irrelevant here.
* The game runs as the SAME user as the plugin. That matters: ``hidepid=2``
  hides *other* users' processes, never your own, so a same-uid game stays
  visible even on a hardened mount. This check therefore does not depend on the
  permissive /proc that happens to exist on this device.

Why argv[0] rather than a name search anywhere in the command line
------------------------------------------------------------------
A terminal sitting in the Mods folder would otherwise look like a running game.
``argv[0]`` is the executable (or, under ``exec -a``, what it claims to be), and
on this device the launch option points straight at
``<GAME_ROOT>/StardewModdingAPI``, so the first argument is exactly the thing we
want to recognise. Two rules, both narrow:

* ``argv[0]``'s basename is one of the descriptor's markers, or
* ``argv[0]`` lives inside ``GAME_ROOT``.

Never a substring of a later argument, never a partial name, never a count.

Honesty about not knowing
-------------------------
If ``/proc`` cannot be listed at all (a non-Linux host, a container without it),
the answer is ``unknown`` -- not ``False``. ``is_running()`` returns a dict so
the caller can tell "checked, not running" from "could not check", and the
panel can say so rather than implying a safety it does not have.
"""

from __future__ import annotations

import os

MAX_PIDS = 4096
MAX_CMDLINE = 8192

STATE_RUNNING = "running"
STATE_STOPPED = "stopped"
STATE_UNKNOWN = "unknown"


def _lister() -> list:
    """Return /proc entries. Injectable so tests need no real processes."""
    try:
        return os.listdir("/proc")
    except OSError:
        return []


def _reader(pid: str) -> bytes:
    """Return one process's cmdline, or b"" when it is gone or unreadable."""
    try:
        with open("/proc/%s/cmdline" % pid, "rb") as f:
            return f.read(MAX_CMDLINE)
    except OSError:
        return b""


def _argv0(pid: str) -> str:
    raw = _reader(pid)
    if not raw:
        return ""
    first = raw.split(b"\0", 1)[0]
    try:
        return first.decode("utf-8", "replace")
    except Exception:
        return ""


def _basename(path: str) -> str:
    return path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def _norm(path: str) -> str:
    """Collapse a POSIX path without os.path.

    /proc always reports POSIX paths, but this module is also exercised on a
    Windows dev box, and ``os.path.normpath`` there would rewrite
    ``/a/b`` into ``\\a\\b`` and make every containment test wrong. Using plain
    string operations keeps the reasoning identical on both hosts.
    """
    parts = []
    for seg in path.replace("\\", "/").split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    return "/" + "/".join(parts)


def _inside(path: str, root: str) -> bool:
    if not path or not root:
        return False
    norm = _norm(path)
    rootn = _norm(root).rstrip("/") + "/"
    return norm.startswith(rootn)


def is_running(game_root: str = "", markers=None) -> dict:
    """Decide whether the game is running.

    Returns ``{"state": "running"|"stopped"|"unknown", "pid": str, "match":
    str, "scanned": int, "detail": str}``. Never raises: a status call must
    survive whatever /proc looks like.
    """
    want = set()
    for m in (markers or []):
        if isinstance(m, str) and m.strip():
            want.add(m.strip().lower())
    root = game_root or ""
    try:
        entries = _lister()
    except Exception as exc:                       # noqa: BLE001 - never raise
        return {"state": STATE_UNKNOWN, "pid": "", "match": "",
                "scanned": 0, "detail": "%s: %s" % (type(exc).__name__, exc)}
    pids = [e for e in entries if e.isdigit()][:MAX_PIDS]
    if not pids:
        return {"state": STATE_UNKNOWN, "pid": "", "match": "", "scanned": 0,
                "detail": "/proc lists no processes; cannot tell"}
    scanned = 0
    for pid in pids:
        if pid == str(os.getpid()):
            continue          # our own argv can name the game folder
        head = _argv0(pid)
        scanned += 1
        if not head:
            continue
        base = _basename(head).lower()
        if base and base in want:
            return {"state": STATE_RUNNING, "pid": pid, "match": head,
                    "scanned": scanned, "detail": ""}
        if root and _inside(head, root):
            return {"state": STATE_RUNNING, "pid": pid, "match": head,
                    "scanned": scanned, "detail": ""}
    return {"state": STATE_STOPPED, "pid": "", "match": "", "scanned": scanned,
            "detail": ""}


def describe(state: dict) -> str:
    """One line for the panel, naming the evidence rather than asserting calm."""
    st = (state or {}).get("state") or STATE_UNKNOWN
    if st == STATE_RUNNING:
        return "the game is running (pid %s: %s)" % (
            state.get("pid") or "?", state.get("match") or "?")
    if st == STATE_STOPPED:
        return ""
    return "could not check whether the game is running: %s" % (
        (state or {}).get("detail") or "unknown reason")
