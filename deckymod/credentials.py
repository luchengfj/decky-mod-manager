"""Local secret store for a single user-supplied API key.

Threat model — what this module defends against, and what it does not.

It defends against the *plugin* leaking the secret: into a log line, into a UI
response, into an error message, into a crash report. Every function here
returns only metadata, never the key itself, and ``read_key`` is the single
place the raw value exists — its result must not be put in a dict that is
returned to the frontend.

It does NOT defend against another process running as the same user reading the
file. There is no keyring on this device (``gnome-keyring-daemon`` is absent
while ``secret-tool`` is present, which fails at random), so the realistic
choice is a 0600 file owned by the plugin's own user. That is the same posture
as the device's own mod managers.

On-disk protocol (each step is load-bearing):

  1. ``O_CREAT|O_EXCL|O_WRONLY`` with mode 0o600 — the file is born private, so
     there is no window where it exists world-readable.
  2. an explicit ``os.chmod`` — ``umask`` (0022 on SteamOS) would otherwise
     strip bits from the mode passed to ``open``.
  3. an update writes a sibling ``.tmp`` then ``os.replace`` — a reader never
     sees a half-written secret, and the rename is atomic on the same FS.
  4. delete is ``os.unlink`` on a path that was re-validated as a regular file.
"""

from __future__ import annotations

import os
import re

FILENAME = "nexus_api_key"
REQUESTED_MODE = 0o600

#: Nexus keys are base64-ish: this was measured, not assumed. A real 96-char key
#: contained "-", "+" and "=", so an alphanumeric-only check wrongly rejected a
#: valid key (that bug shipped once and broke a real user's credential).
_KEY_RE = re.compile(r"\A[A-Za-z0-9+/=_-]{16,128}\Z")


def data_dir() -> str:
    """Resolve the plugin's private data directory, matching the journal's rule.

    The rule is deliberately the SAME as ``engine._default_journal``: an explicit
    ``DECKYMOD_DATA`` wins, otherwise the loader's runtime dir with ``data``
    appended. Getting this wrong once put the key one level above the journal
    (``${RUNTIME}/nexus_api_key`` instead of ``${RUNTIME}/data/journal/...``'s
    sibling), which is a confusing place to look for it. The final fallback is
    a local dir for tests only -- and because it lives INSIDE the plugin tree,
    a deployment must never contain it, which is why the sync/deploy scripts
    exclude ``.decky-data``.
    """
    d = (os.environ.get("DECKYMOD_DATA")
         or os.environ.get("DECKY_PLUGIN_RUNTIME_DIR")
         or "")
    if d and not d.rstrip("/\\").endswith("data"):
        d = os.path.join(d, "data")
    if not d:
        d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         ".decky-data")
    return os.path.abspath(d)


def key_path() -> str:
    return os.path.join(data_dir(), FILENAME)


def _guarded_path() -> str:
    """Refuse to touch a symlink or an unexpected directory.

    The path is built here, so a caller cannot point it somewhere else — but the
    directory itself lives on a user-writable tree, so a local attacker could
    replace the file with a symlink and make an update write through it.
    """
    d = data_dir()
    p = os.path.join(d, FILENAME)
    real_d = os.path.realpath(d)
    if os.path.islink(p):
        raise PermissionError("refusing to use a symlinked credential path")
    parent = os.path.realpath(os.path.dirname(p))
    if os.path.commonpath([real_d, parent]) != real_d:
        raise PermissionError("credential path escapes the plugin data directory")
    return p


def validate_key_format(api_key: str) -> str | None:
    """Return an error string, or None when the key looks structurally valid.

    Deliberately strict about *shape* and silent about *truth*: only the server
    can say whether a well-formed key actually works.
    """
    if not isinstance(api_key, str):
        return "api key must be a string"
    k = api_key.strip()
    if not k:
        return "api key is empty"
    if not _KEY_RE.match(k):
        return ("api key must be 16-128 characters of A-Z a-z 0-9 + / = _ - "
                "(no spaces, no quotes)")
    return None


def save_key(api_key: str) -> dict:
    """Persist the key at mode 0o600. Returns metadata only."""
    err = validate_key_format(api_key)
    if err:
        raise ValueError(err)
    key = api_key.strip()
    d = data_dir()
    os.makedirs(d, exist_ok=True)
    p = _guarded_path()

    if os.path.exists(p):
        # Update path: write a sibling temp file, then rename over the target.
        tmp = p + ".tmp"
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, REQUESTED_MODE)
        try:
            os.write(fd, key.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        os.chmod(tmp, REQUESTED_MODE)
        os.replace(tmp, p)
    else:
        fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, REQUESTED_MODE)
        try:
            os.write(fd, key.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        os.chmod(p, REQUESTED_MODE)

    st = os.stat(p)
    return {"stored": True, "path": p,
            "mode_requested": oct(REQUESTED_MODE),
            "mode_actual": oct(st.st_mode & 0o777)}


def read_key() -> str:
    """Return the raw key. The ONLY function that does.

    Fails closed: a missing, unreadable or malformed file raises rather than
    returning an empty string, because an empty string would silently turn every
    authenticated call into an anonymous one and produce a confusing 401.
    """
    p = _guarded_path()
    with open(p, "r", encoding="utf-8") as f:
        raw = f.read()
    key = raw.strip()
    err = validate_key_format(key)
    if err:
        raise ValueError("stored key is malformed: " + err)
    return key


def delete_key() -> dict:
    """Remove the stored key. Honest about whether there was anything to delete."""
    p = _guarded_path()
    try:
        os.unlink(p)
        return {"deleted": True, "path": p}
    except FileNotFoundError:
        return {"deleted": False, "path": p, "reason": "no key was stored"}
    except OSError as e:
        return {"deleted": False, "path": p,
                "reason": "%s: %s" % (type(e).__name__, e.strerror or e)}


def key_status() -> dict:
    """Report the credential's state WITHOUT reading its value.

    ``stat`` only — the file is never opened. That is what makes this safe to
    call on every panel render and safe to paste into a bug report.
    """
    p = key_path()
    out = {
        "configured": False,
        "path": p,
        "state": "missing",
        "mode_requested": oct(REQUESTED_MODE),
        "mode_actual": None,
        "mode_ok": None,
        "posix": os.name == "posix",
    }
    try:
        st = os.stat(p)
    except FileNotFoundError:
        return out
    except OSError as e:
        out["state"] = "unreadable"
        out["detail"] = "%s: %s" % (type(e).__name__, e.strerror or e)
        return out

    out["configured"] = True
    out["size"] = st.st_size
    if os.name == "posix":
        actual = st.st_mode & 0o777
        out["mode_actual"] = oct(actual)
        out["mode_ok"] = (actual & 0o077) == 0
        if not out["mode_ok"]:
            out["state"] = "unreadable"
            out["detail"] = ("file mode %s is group/world accessible; expected %s"
                             % (oct(actual), oct(REQUESTED_MODE)))
            return out

    # The file exists and is private; whether it *works* needs the network, so
    # state stays "present" until a validation call says otherwise.
    out["state"] = "present"
    return out
