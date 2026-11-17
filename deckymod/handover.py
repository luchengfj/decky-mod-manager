"""Hand the ``Mods/`` folder over from another mod manager, reversibly.

Why this exists
---------------
Round 44 taught the engine to refuse writing into a folder that another tool
owns (``modwatch`` sees symlinked entries or a symlinked ``Mods/``; the marker
check sees ``.mm_deployed`` / ``Mods_Core``). Refusing is correct, and Round 53
made the descriptor name its own markers instead of hard-coding Amethyst's.

What was missing is the next sentence. A user who has never heard of Amethyst
installs this plugin, opens the panel, and sees "read-only" everywhere with no
way forward, so the reasonable conclusion is that the plugin is broken. Refusing
without offering the exit is a dead end, and a dead end costs the user the
plugin.

The exit has to be narrow, because the alternative -- a plugin that rearranges
somebody else's deployment on its own -- is far worse than a dead end:

* **The user asks for it.** There is no automatic sweep, no "fix" button that
  runs during ``status()``. It is one explicit call with a two-phase confirm.
* **Nothing is deleted.** Everything moved goes into the quarantine under a
  journal transaction, so ``rollback`` puts it back byte for byte.
* **Only what is provably ours to move.** A symlink inside ``Mods/`` is a
  pointer; moving the pointer does not touch the mod it points at. A marker
  *file* inside ``Mods/`` is bookkeeping; moving it is reversible.
* **Everything else is refused, not attempted.** A symlinked ``Mods/`` itself, a
  ``Mods_Core/`` directory beside the game, or a ``Mods/`` on another
  filesystem are all things this plugin cannot move without breaking the other
  tool's deployment in ways it cannot see. Those stop the whole operation and
  name the one step the user must take outside the plugin.

So the shape is: report exactly what blocks writes, move only the movable part,
and say plainly what is left. Anything else would be this plugin deciding that
it knows better than the user which mod manager should own the folder.
"""

import os

from .errors import ModError

#: A symlink found inside Mods/ -- a pointer, safe to move.
R_SYMLINKED_ENTRY = "symlinked_entry"
#: A marker file inside Mods/ -- bookkeeping, safe to move.
R_MARKER_FILE = "marker_inside_mods"
#: Mods/ itself is a symlink. Moving it would make the folder disappear.
R_MODS_SYMLINK = "mods_dir_is_symlink"
#: A marker directory beside the game (Amethyst's real data lives here).
R_MARKER_DIR = "marker_beside_game"
#: Mods/ is on a different filesystem from the game; a move cannot be atomic.
R_OTHER_DEVICE = "mods_on_other_device"

#: Reasons this module is allowed to act on. Everything else blocks the run.
MOVABLE = (R_SYMLINKED_ENTRY, R_MARKER_FILE)

MAX_ENTRIES = 200
MAX_NAMED = 20


def _fail(code, detail, **extra):
    out = {"ok": False, "code": code, "detail": detail}
    out.update(extra)
    return out


def _ok(**kw):
    out = {"ok": True, "code": None, "detail": ""}
    out.update(kw)
    return out


def _marker_names(markers):
    """The declared marker list, or nothing.

    No historical default here on purpose: this module MOVES things, and a
    default it inherited from another module is not something the user agreed
    to. With no declaration there is nothing to move and the answer is honest.
    """
    return [str(m) for m in (markers or ()) if str(m)]


def survey(game_root, mod_root, markers=None):
    """What is in the way, split into movable and not. Never writes.

    Returns::

        {
          "ok": True,
          "movable": [{kind, name, path}],   # capped at MAX_ENTRIES
          "blocking": [code, ...],          # empty means "we could act"
          "explain": "sentence; sentence",  # "" when nothing blocks
          "entries": int,                   # movable count, uncapped
        }

    A directory that cannot be listed yields zero movable entries and no
    blocking reason: "I could not look" must not become "you must act".
    """
    movable = []
    blocking = []
    notes = []

    names = _marker_names(markers)

    try:
        is_link = os.path.islink(mod_root)
        exists = os.path.exists(mod_root) or is_link
    except OSError:
        is_link = False
        exists = False

    if is_link:
        # Deliberately fatal for this operation: moving the link would leave
        # Mods/ missing while the other tool still believes it is deployed.
        blocking.append(R_MODS_SYMLINK)
        notes.append("Mods/ is a symbolic link, so it belongs to a deployment "
                     "this plugin cannot take apart safely")
        mdir = os.path.dirname(os.path.abspath(mod_root))
        root_dir = mod_root
    else:
        mdir = mod_root
        root_dir = mod_root

    if exists and not is_link:
        try:
            with os.scandir(mod_root) as it:
                for de in it:
                    try:
                        if de.is_symlink():
                            if len(movable) < MAX_ENTRIES:
                                movable.append({"kind": R_SYMLINKED_ENTRY,
                                                "name": de.name,
                                                "path": os.path.join(mod_root, de.name)})
                            continue
                    except OSError:
                        continue
            if names:
                for name in names:
                    p = os.path.join(mod_root, name)
                    try:
                        if os.path.isfile(p):
                            if len(movable) < MAX_ENTRIES:
                                movable.append({"kind": R_MARKER_FILE,
                                                "name": name, "path": p})
                    except OSError:
                        continue
        except OSError:
            pass

    # Markers that live BESIDE the game are the other tool's real data.
    if names:
        for name in names:
            p = os.path.join(game_root, name)
            try:
                if os.path.isdir(p):
                    blocking.append(R_MARKER_DIR)
                    notes.append("%s/ sits beside the game and holds the other "
                                 "manager's deployed files; this plugin will not "
                                 "touch it" % name)
            except OSError:
                continue

    try:
        dev_mods = os.lstat(mod_root).st_dev
        dev_game = os.lstat(game_root).st_dev
        if dev_mods != dev_game:
            blocking.append(R_OTHER_DEVICE)
            notes.append("Mods/ and the game are on different filesystems, so a "
                         "move could not be undone in one step")
    except OSError:
        pass

    # De-duplicate while keeping the order the user will read.
    seen = set()
    uniq = []
    for code in blocking:
        if code not in seen:
            seen.add(code)
            uniq.append(code)

    return _ok(movable=movable, blocking=uniq, explain="; ".join(notes),
               entries=len(movable))


def describe(survey_result, limit=3):
    """A one-line summary of what would move, for the confirm dialog."""
    movable = survey_result.get("movable") or []
    if not movable:
        return ""
    by_kind = {}
    for row in movable:
        by_kind.setdefault(row["kind"], []).append(row["name"])
    parts = []
    for kind in MOVABLE:
        got = by_kind.get(kind) or []
        if not got:
            continue
        shown = ", ".join(sorted(got)[:limit])
        extra = "" if len(got) <= limit else " (+%d more)" % (len(got) - limit)
        label = ("symbolic link" if kind == R_SYMLINKED_ENTRY else "marker file")
        parts.append("%d %s(s): %s%s" % (len(got), label, shown, extra))
    return "; ".join(parts)


def plan(survey_result, quarantine_dir):
    """Decide whether to act, and what the confirm must say.

    Returns a dict shaped like the other two-phase operations, so the panel can
    reuse the same confirm component instead of growing a second one.
    """
    if not survey_result.get("ok"):
        return _fail(survey_result.get("code") or "E_UNKNOWN",
                     survey_result.get("detail") or "survey failed")

    blocking = survey_result.get("blocking") or []
    if blocking:
        # Refuse the whole operation rather than doing half of it: moving the
        # links out and then still being blocked would leave the user worse off
        # than before, with the other manager's deployment half dismantled.
        return _fail(
            "E_CAPABILITY_DISABLED",
            "this folder cannot be handed over safely: %s. %s"
            % (", ".join(blocking), survey_result.get("explain") or ""),
            blocking=list(blocking), movable=[], explain=survey_result.get("explain") or "",
        )

    movable = survey_result.get("movable") or []
    if not movable:
        return _fail("E_CAPABILITY_DISABLED",
                     "nothing to hand over: no symlinked entries and no marker "
                     "files were found",
                     blocking=[], movable=[], explain="")

    return _ok(movable=movable, blocking=[], quarantine=quarantine_dir,
               explain=survey_result.get("explain") or "")


def execute(planned, *, after_confirm=False, quarantine_root="", txn="", mover=None):
    """Move the planned entries into ``quarantine_root/<txn>/``.

    ``mover`` is injected so the decision logic can be tested without a real
    filesystem, and so Windows (where a symlink needs a privilege the test
    runner does not have) can exercise the same code the Deck runs.
    """
    movable = list(planned.get("movable") or [])
    if not movable:
        return _ok(phase="nothing", moved=[], failed={})

    if not after_confirm:
        return _ok(phase="confirm", moved=[], failed={},
                   count=len(movable), describe=describe({"movable": movable}))

    if not quarantine_root or not txn:
        return _fail("E_PATH_INVALID", "quarantine root and transaction id are required")

    dest_root = os.path.join(quarantine_root, txn)
    moved = []
    failed = {}
    for row in movable:
        src = row.get("path") or ""
        name = row.get("name") or ""
        if not src or not name:
            failed[name or "?"] = "entry has no path"
            continue
        # Re-check immediately before acting: the survey is a snapshot, and a
        # folder can change between the confirm dialog and the confirm.
        try:
            if not os.path.islink(src) and not os.path.isfile(src):
                failed[name] = "already gone"
                continue
        except OSError as exc:
            failed[name] = "unreadable: %s" % exc
            continue
        dest = os.path.join(dest_root, name)
        try:
            if mover is not None:
                mover(src, dest)
            else:
                os.makedirs(dest_root, exist_ok=True)
                os.replace(src, dest)
            moved.append(name)
        except OSError as exc:
            failed[name] = "%s: %s" % (exc.strerror or exc.__class__.__name__, exc)

    return _ok(phase="moved", moved=moved, failed=failed,
               quarantine=dest_root, count=len(movable))


def restore(quarantine_dir, from_path, names, *, mover=None):
    """Put handed-over entries back where they came from.

    This is what makes the promise in the confirm dialog true. Without it the
    dialog would say "Rollback puts them back" while ``_rollback_inner`` knew
    nothing about ``MODS_HANDOVER`` and would answer "nothing to roll back" --
    a claim in the UI that the code does not keep is worse than no claim.

    ``names`` is the list recorded in the journal, so restoring is driven by
    what actually moved, not by re-reading a directory that may have changed.

    A name whose copy is missing is reported, not invented. A name whose
    destination is already occupied is refused rather than overwritten: someone
    put something there in the meantime, and that something is not ours to
    replace.
    """
    moved = []
    failed = {}
    for name in list(names or []):
        name = str(name or "")
        if not name:
            continue
        src = os.path.join(quarantine_dir, name)
        dest = os.path.join(from_path, name)
        try:
            if not os.path.islink(src) and not os.path.exists(src):
                failed[name] = "not in the quarantine any more"
                continue
            if os.path.islink(dest) or os.path.exists(dest):
                failed[name] = "something else is at the destination now"
                continue
            if mover is not None:
                mover(src, dest)
            else:
                os.makedirs(from_path, exist_ok=True)
                os.replace(src, dest)
            moved.append(name)
        except OSError as exc:
            failed[name] = "%s: %s" % (exc.strerror or exc.__class__.__name__, exc)
    return {"ok": True, "moved": moved, "failed": failed}
