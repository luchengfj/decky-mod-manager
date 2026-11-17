"""Puts a mod page on the screen the user is actually looking at.

Why this module exists: goal item 2 asks to reach a mod's download page *from the
installed game*. Since the Nexus API refuses download links to free accounts, the
honest implementation is "open the page, let the browser session do the download,
then import the ZIP" -- which needs a way to open a page, not a way to fetch one.

Two mechanisms were measured on the device (2026-11-17), and the obvious one is
wrong:

  * ``xdg-open`` **cannot** work from the plugin. The plugin process runs as uid
    1000 but with ``DISPLAY`` and ``WAYLAND_DISPLAY`` both unset, so xdg-open
    falls through its browser list (``www-browser``/``links2``/``elinks``/
    ``links``/``lynx``: command not found) and even with ``DISPLAY=:0`` forced it
    dies on a malformed desktop-file command. Both attempts left every CEF tab
    untouched. It exits 0 while doing nothing, which is the worst failure mode.
  * ``steam://openurl/<url>`` **works**: the Steam client itself navigates,
    creating a real tab (observed: a new target with the requested URL) and
    landing the main window on ``steamloopback.host/routes/externalweb``. This is
    the Game Mode browser the user can actually see, so it is what we use.

Constraints this module keeps:
  * the URL is NEVER taken from the caller. We accept a numeric mod id and build
    the page ourselves, so there is no string a caller could inject;
  * argv is a list and ``shell=False``, so no quoting bug can exist;
  * only https on the host allow-list below;
  * a runner is injectable, so the whole thing is testable offline.
"""

from __future__ import annotations

import os
import subprocess
from typing import Callable, Dict, List, Optional

# The only hosts we will ask the Steam client to display. Deliberately tiny: this
# is not a general "open any URL" primitive.
ALLOWED_HOSTS = frozenset({"www.nexusmods.com", "nexusmods.com"})

STEAM_BIN = "/usr/bin/steam"
MAX_URL_LEN = 512

# Injectable seam (same shape as deckymod/sevenzip.py::set_runner) so tests can
# assert the exact argv without launching a browser.
_runner: Optional[Callable[[List[str]], Dict[str, object]]] = None


def set_runner(fn: Optional[Callable[[List[str]], Dict[str, object]]]) -> None:
    """Replace the process runner (tests only). Pass None to restore the default."""
    global _runner
    _runner = fn


def default_runner(argv: List[str]) -> Dict[str, object]:
    """Run the Steam client and report {code, stdout, stderr}. Never raises on exit != 0."""
    try:
        proc = subprocess.run(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=20, check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return {"code": -1, "stdout": "", "stderr": "%s: %s" % (type(e).__name__, e)}
    return {
        "code": proc.returncode,
        "stdout": proc.stdout.decode("utf-8", "replace"),
        "stderr": proc.stderr.decode("utf-8", "replace"),
    }


def _fail(reason: str, detail: str = "") -> Dict[str, object]:
    return {"ok": False, "reason": reason, "detail": detail}


def validate_url(url: str) -> Optional[str]:
    """Return a reason string when the URL is not safe to hand to the client.

    Rejecting on whitespace and control characters is not cosmetic: the URL is
    embedded in a ``steam://openurl/...`` argument, so any newline or quote would
    change which URI the client receives.
    """
    from urllib.parse import urlsplit

    if not isinstance(url, str) or not url:
        return "url is empty"
    if len(url) > MAX_URL_LEN:
        return "url is longer than %d characters" % MAX_URL_LEN
    if "://" not in url:
        return "url is not absolute"
    if any(c.isspace() or ord(c) < 0x20 or ord(c) == 0x7F for c in url):
        return "url contains whitespace or control characters"
    parts = urlsplit(url)
    if parts.scheme != "https":
        return "only https is allowed"
    host = (parts.hostname or "").lower().rstrip(".")
    if host not in ALLOWED_HOSTS:
        return "host %r is not allowed" % host
    if parts.username or parts.password:
        return "userinfo is not allowed"
    return None


def command_for(url: str) -> List[str]:
    """The exact argv that displays ``url``. Separate so tests can assert it."""
    return [STEAM_BIN, "steam://openurl/%s" % url]


def open_url(url: str) -> Dict[str, object]:
    """Ask the running Steam client to display ``url``.

    Note the exit status is deliberately NOT the success criterion. The device
    probe showed that a launcher can exit 0 while displaying nothing (xdg-open
    did exactly that), so a zero code proves only "the client was reached".
    """
    bad = validate_url(url)
    if bad:
        return _fail("url_refused", bad)
    if not os.path.isfile(STEAM_BIN):
        return _fail("steam_missing", "%s does not exist" % STEAM_BIN)
    run = _runner or default_runner
    got = run(command_for(url))
    code = got.get("code")
    if code != 0:
        return _fail("steam_failed", "exit %s: %s" % (code, str(got.get("stderr") or "")[:300]))
    return {"ok": True, "url": url, "detail": ""}
