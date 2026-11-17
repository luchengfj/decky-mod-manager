"""Undo an upgrade: put the version the install displaced back where it was.

Round 56. ``_install_inner`` has always recorded ``replaced_old`` -- the
quarantine path it moved the previous copy into before unpacking the new one --
and nothing ever read it. Three consequences, all measured on the device:

  1. ``rollback(<upgrade txn>)`` answered
     ``nothing to roll back for txn ... (state=COMMITTED)``;
  2. the version on disk stayed at the new one;
  3. the displaced copy became an ORPHAN in the quarantine, which is exactly
     what round 54's ``reclaim_quarantine`` is allowed to delete.

So two separately-correct features combined into losing the user's old version.
This module is the missing third case, in the same shape as the other two
(``handover.restore`` for a handover, the ``MOD_UNINSTALLED`` branch for an
uninstall): read the record, check the ground, move it back.

It deliberately does NOT delete the new copy if the destination cannot be
freed. A rollback that half-succeeds leaves the user with neither version, and
"nothing happened, here is why" is always recoverable while "half happened" is
not.
"""
from __future__ import annotations

import os
import shutil
from typing import Any, Dict, Optional

from .errors import ModError


def _fail(code: str, detail: str, **extra: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": False, "code": code, "detail": detail}
    out.update(extra)
    return out


def _ok(**kw: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": True}
    out.update(kw)
    return out


def describe(replaced_old: str, target: str) -> str:
    """One line a confirm dialog can show, naming both sides."""
    return "restore %s over %s" % (os.path.basename(replaced_old.rstrip("/\\")),
                                   os.path.basename(target.rstrip("/\\")))


def undo_install(replaced_old: Optional[str], target: Optional[str],
                 *, mover=None) -> Dict[str, Any]:
    """Move ``replaced_old`` back to ``target``, after checking the ground.

    ``replaced_old`` is what the install recorded; ``target`` is where the mod
    lives now. Both must be non-empty, the source must still be a directory, and
    the destination must be replaceable -- if it is missing, that is fine (the
    new copy is simply gone), but if it cannot be removed we refuse rather than
    leave the user with nothing.
    """
    if not replaced_old or not target:
        return _fail("E_UNKNOWN", "this transaction recorded no replaced copy")
    if os.path.islink(replaced_old) or not os.path.isdir(replaced_old):
        return _fail("E_UNKNOWN",
                     "the previous copy is no longer in the quarantine: %s"
                     % replaced_old)
    # Inspect the RAW trailing component. After os.path.normpath("a/b/..") the
    # ".." is gone, so a check on the normalised basename would accept a path
    # that clearly meant "the parent" -- and the first version of this guard
    # did exactly that.
    tail = target.rstrip("/\\").replace("\\", "/").rsplit("/", 1)[-1]
    if tail in ("", ".", ".."):
        return _fail("E_PATH_INVALID", "refusing to restore onto %r" % target)
    if os.path.islink(target):
        # The destination became a link since the install. Whatever it points at
        # is not ours, and os.replace would shadow it rather than remove it.
        return _fail("E_PATH_INVALID",
                     "the destination became a symbolic link; refusing to "
                     "replace it: %s" % target)
    action = mover or shutil.move
    removed_new = False
    try:
        if os.path.isdir(target):
            shutil.rmtree(target)
            removed_new = True
        os.makedirs(os.path.dirname(target), exist_ok=True)
        action(replaced_old, target)
    except OSError as exc:
        return _fail("E_OP_FAILED",
                     "could not restore the previous copy (%s)%s"
                     % (exc, "; the new copy was removed" if removed_new else ""),
                     removed_new=removed_new)
    # The transaction directory we emptied is litter, and round 54 taught us that
    # litter in the quarantine gets counted, shown, and eventually offered for
    # deletion. Remove it only if it is genuinely empty -- os.rmdir refuses
    # otherwise, which is exactly the guard we want.
    try:
        os.rmdir(os.path.dirname(replaced_old))
    except OSError:
        pass
    return _ok(target=target, restored_from=replaced_old, removed_new=removed_new)
