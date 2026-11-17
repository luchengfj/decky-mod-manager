"""Round 42: the inbox is not the only place a ZIP can land.

WHY THIS EXISTS
---------------
The plugin reads exactly one directory: ``${DECKY_DATA}/inbox``. That is the
right place for anything the plugin downloaded itself. It is the WRONG place for
files the USER downloaded, and on this device that difference is decisive:

  * Round 41 made it possible to show a Nexus mod page in the Game Mode browser.
    A free Nexus account cannot get a download link from the API, so the intended
    flow is: open the page -> download in the browser -> import the ZIP.
  * The Steam browser writes to ``$XDG_DOWNLOAD_DIR`` (measured on the device:
    ``/home/deck/Downloads``, ``deck:deck 775``, already holding files).
  * The plugin's inbox is ``/home/deck/homebrew/data/decky-mod-manager/data/inbox``
    (measured: 12 ZIPs, none of them from the browser).
  * Game Mode has no file manager. The user cannot drag the file from one
    directory to the other, so "download it in the browser, then import" was not
    a usable instruction -- the import list never showed their file.

So the import surface has to be able to READ a small, declared set of extra
directories. Read only: this module never creates, moves, or deletes anything.

DESIGN CONSTRAINTS
------------------
1. **Declared, not discovered.** Roots come from the game descriptor
   (``import_roots``), never from walking the home directory. A plugin that
   recursively scans ``$HOME`` for ZIPs is a privacy problem and a slow one.
2. **Symlinks are refused.** A symlink in Downloads could point anywhere; the
   install path validates separately, but the list must not advertise a target
   the user cannot reason about.
3. **Missing roots are not errors.** ``Downloads`` does not exist on a fresh
   account. A missing directory is reported with ``exists: false`` so the UI can
   say "nothing there yet" instead of failing the whole list.
4. **Bounded.** ``MAX_PER_ROOT`` caps each directory so one pathological folder
   cannot stall the panel.
5. **Read only, always.** No ``os.makedirs`` here even for convenience -- the
   plugin's write surface stays exactly what the user approved.
"""

import os

MAX_PER_ROOT = 200
LOGIN_EXTS = (".zip", ".7z")

_UNKNOWN = "unknown"


def _expand(template, user_home, xdg_download):
    """Expand the two placeholders a descriptor is allowed to use.

    Unknown tokens are left VERBATIM, same rule as ``paths.py``: silently
    dropping part of a path yields a directory that looks configured but never
    matches anything, which is harder to debug than an obvious literal.
    """
    out = str(template or "")
    out = out.replace("${USER_HOME}", user_home or "")
    out = out.replace("${XDG_DOWNLOAD}", xdg_download or "")
    return out


def _xdg_download_dir(user_home):
    """Read XDG_DOWNLOAD_DIR without importing anything or spawning a process.

    Falls back to ``$HOME/Downloads``, which is what xdg-user-dirs writes on this
    device (``XDG_DOWNLOAD_DIR="$HOME/Downloads"``). A parse failure is not worth
    an error: the fallback is the same directory in every normal setup.
    """
    cfg = os.path.join(user_home or "", ".config", "user-dirs.dirs")
    try:
        with open(cfg, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line.startswith("XDG_DOWNLOAD_DIR="):
                    continue
                val = line.split("=", 1)[1].strip().strip('"')
                val = val.replace("$HOME", user_home or "")
                return val or None
    except OSError:
        pass
    return os.path.join(user_home, "Downloads") if user_home else None


def roots_for(inbox, descriptor, user_home):
    """The declared import roots, inbox first.

    Returns a list of ``{label, path, exists}`` dicts. The inbox is always first
    because it is the one the plugin owns; everything else is a read-only
    courtesy for files the user fetched themselves.
    """
    out = [{"label": "inbox", "path": inbox}]
    cfg = descriptor or {}
    mp = cfg.get("mod_package", {}) or {}
    declared = mp.get("import_roots") or cfg.get("import_roots") or []
    xdg_dl = _xdg_download_dir(user_home) if user_home else None
    for item in declared:
        if isinstance(item, str):
            item = {"label": _UNKNOWN, "path": item}
        template = item.get("path") or ""
        path = os.path.abspath(_expand(template, user_home, xdg_dl)) if template else ""
        if not path:
            continue
        label = item.get("label") or _UNKNOWN
        if any(r["path"] == path for r in out):
            continue                      # never list one directory twice
        out.append({"label": label, "path": path})
    for r in out:
        r["exists"] = os.path.isdir(r["path"])
    return out


def list_files(roots, exts=LOGIN_EXTS, limit=MAX_PER_ROOT):
    """List importable files across the declared roots (READ ONLY).

    Each item carries the root it came from, so the UI can tell a file the plugin
    fetched apart from a file the user downloaded -- which matters when the two
    have the same name and the user has to choose.
    """
    norms = tuple(e.lower() for e in exts)
    items = []
    for root in roots or []:
        path = root.get("path") or ""
        if not root.get("exists") or not path:
            continue
        try:
            names = sorted(os.listdir(path))
        except OSError:
            # One unreadable directory must not blank the whole list.
            continue
        count = 0
        for name in names:
            if count >= limit:
                break
            if not name.lower().endswith(norms):
                continue
            full = os.path.join(path, name)
            if os.path.islink(full) or not os.path.isfile(full):
                continue
            try:
                size = os.path.getsize(full)
            except OSError:
                size = None
            items.append({
                "name": name,
                "path": full,
                "size": size,
                "root": root.get("label") or _UNKNOWN,
            })
            count += 1
    return items


def allowed_roots(roots):
    """Absolute paths an import may read from (used by path validation)."""
    out = []
    for root in roots or []:
        path = root.get("path") or ""
        if path:
            out.append(os.path.abspath(path))
    return out
