"""Filesystem primitives: ownership, mountinfo, atomic replace, errno mapping.

Design rules (§3.2 / §3.6 / §3.7 / §6):
  * We neither assume root nor assume non-root. Resolve the real deck user via
    pwd.getpwnam(DECKY_USER); chown ONLY when os.geteuid()==0.
  * Non-POSIX mounts (microSD/exFAT) have no owners/symlinks: SKIP ownership
    checks (do not try to fix permissions) and tolerate EOPNOTSUPP from
    fchmod/fchown. Signal E_FS_NO_POSIX as information.
  * Atomic replace: mkstemp(dir=SAME_PARENT), write, fsync, (optional chown),
    os.replace(tmp, final), fsync parent dir. Temp file MUST be on the same
    filesystem and in the same directory as the target (EXDEV avoidance).
  * Every OSError is mapped to a stable E_* code, never leaked as a traceback.
"""

from __future__ import annotations

import errno
import os
import stat
import tempfile
from typing import Callable

from .errors import ModError

# Filesystems that do NOT provide POSIX ownership / symlink semantics.
# On these we skip owner checks and tolerate EOPNOTSUPP from chmod/chown.
NON_POSIX_FS = {
    "vfat", "exfat", "fat", "fat32", "msdos", "ntfs", "ntfs3", "fuseblk",
    "sdcardfs", "fuse.sdcardfs", "9p", "cifs", "smb3",
}

# Errno -> our code
ERRNO_MAP = {
    errno.EACCES: "E_ACCESS",
    errno.EPERM: "E_ACCESS",
    errno.EROFS: "E_READONLY_FS",
    errno.ENOSPC: "E_NO_SPACE",
    errno.EDQUOT: "E_NO_SPACE",
    errno.EXDEV: "E_CROSS_DEVICE",
    errno.ELOOP: "E_STATE_SYMLINK",
    errno.ENOTDIR: "E_PATH_INVALID",
    errno.EEXIST: "E_FILE_COLLISION",
    errno.EMLINK: "E_OP_FAILED",
    errno.EOPNOTSUPP: "E_FS_NO_POSIX",
    errno.ENOTSUP: "E_FS_NO_POSIX",
    errno.EINVAL: "E_FS_NO_POSIX",
}


def map_oserror(exc: OSError) -> ModError:
    code = ERRNO_MAP.get(exc.errno, "E_OP_FAILED")
    return ModError(code, detail=f"errno={exc.errno}: {exc.strerror}", context={"errno": exc.errno})


def is_posix_fs(path: str) -> bool:
    """Best-effort: read /proc/self/mountinfo and find the mount covering path.

    Returns True when we cannot determine (Windows dev box, no /proc) so the
    self-tests and the locked Linux runtime both behave sensibly. Callers use
    the result only to decide whether to SKIP ownership checks.
    """
    try:
        with open("/proc/self/mountinfo", "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return True  # unknown -> assume POSIX (we will simply try and tolerate failure)

    target = os.path.realpath(path)
    best, best_len = None, -1
    for line in lines:
        parts = line.split(" - ", 1)
        if len(parts) != 2:
            continue
        left, right = parts
        fields = left.split()
        if len(fields) < 5:
            continue
        mount_point = fields[4]
        fstype = right.split()[0] if right.split() else ""
        try:
            # mountinfo escapes spaces as \040
            mp = mount_point.replace("\\040", " ")
            if target == mp or target.startswith(mp.rstrip("/") + "/"):
                if len(mp) > best_len:
                    best, best_len = fstype, len(mp)
        except Exception:
            continue
    if best is None:
        return True
    return best.lower() not in NON_POSIX_FS


def resolve_user():
    """Return (uid, gid, home, username) for the REAL deck user.

    Prefers Decky's DECKY_USER / DECKY_USER_HOME env vars. Falls back to the
    current euid on a non-root box. Never assumes root.
    """
    username = os.environ.get("DECKY_USER") or ""
    home = os.environ.get("DECKY_USER_HOME") or os.environ.get("HOME") or ""
    uid = gid = None
    if username:
        try:
            import pwd
            pw = pwd.getpwnam(username)
            uid, gid = pw.pw_uid, pw.pw_gid
            home = home or pw.pw_dir
        except (KeyError, ImportError):
            uid = gid = None
    if uid is None and hasattr(os, "geteuid"):
        try:
            uid = os.geteuid()
            gid = os.getegid()
        except OSError:
            pass
    return uid, gid, home, username


def _maybe_chown(fd: int, path: str):
    """chown ONLY when running as root, and never on non-POSIX mounts.

    On Windows dev boxes (no chown/geteuid) this is a no-op.
    """
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        return  # not root -> do NOT attempt ownership changes
    uid, gid, _, _ = resolve_user()
    if uid is None:
        return
    if not is_posix_fs(path):
        return  # exFAT etc: no ownership; skip, do not try to fix permissions
    try:
        os.fchown(fd, uid, gid)
    except OSError as e:
        if e.errno not in (errno.EOPNOTSUPP, errno.ENOTSUP, errno.EINVAL, errno.EPERM):
            raise map_oserror(e)


def _maybe_fchmod(fd: int, path: str, mode: int = 0o644):
    fchmod = getattr(os, "fchmod", None)
    if fchmod is None:
        return  # Windows dev box: no POSIX perms; skip (§3.2 non-POSIX tolerance)
    try:
        fchmod(fd, mode)
    except OSError as e:
        if e.errno in (errno.EOPNOTSUPP, errno.ENOTSUP, errno.EINVAL, errno.EPERM):
            return  # non-POSIX mount: tolerate (§3.2)
        raise map_oserror(e)


def check_not_symlink(path: str):
    """Refuse symlinks in the state-file path (anti-escape)."""
    if os.path.islink(path):
        raise ModError("E_STATE_SYMLINK", detail=path)


def check_owner(path: str):
    """Verify the file is owned by the deck user on POSIX mounts.

    Non-POSIX mounts: skip entirely (E_FS_NO_POSIX is informational). If owned
    by someone else on a POSIX fs, refuse (E_ROOT_OWNED / E_STATE_OWNED) rather
    than repairing permissions.
    """
    if not os.path.exists(path):
        return
    if not is_posix_fs(path):
        return
    uid, _, _, _ = resolve_user()
    if uid is None:
        return
    try:
        st = os.stat(path)
    except OSError as e:
        raise map_oserror(e)
    if st.st_uid != uid and hasattr(os, "geteuid") and os.geteuid() == 0:
        # root sees a root-owned leftover: refuse, do not chmod/chown others' files
        raise ModError("E_ROOT_OWNED", detail=f"{path} uid={st.st_uid} expected={uid}")
    elif st.st_uid != uid:
        raise ModError("E_STATE_OWNED", detail=f"{path} uid={st.st_uid} expected={uid}")


def fsync_dir(path: str):
    """fsync a directory so the rename is durable (best-effort on Windows)."""
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def atomic_write_bytes(final_path: str, data: bytes, *, mode: int = 0o644) -> None:
    """Write bytes to final_path atomically via a same-directory temp file."""
    parent = os.path.dirname(final_path) or "."
    if not os.path.isdir(parent):
        raise ModError("E_PATH_INVALID", detail=f"parent missing: {parent}")
    if os.path.islink(final_path):
        raise ModError("E_STATE_SYMLINK", detail=final_path)
    try:
        fd, tmp = tempfile.mkstemp(prefix=".decky-tmp-", dir=parent)
    except OSError as e:
        raise map_oserror(e)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
            # Apply perms/ownership on the SAME open write fd: no TOCTOU
            # window and no leaked os.open() descriptors. Linux-equivalent.
            _maybe_fchmod(f.fileno(), tmp, mode)
            _maybe_chown(f.fileno(), tmp)
        os.replace(tmp, final_path)  # same dir, same fs -> never EXDEV
        tmp = None
        fsync_dir(parent)
    except ModError:
        raise
    except OSError as e:
        raise map_oserror(e)
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def atomic_write_text(final_path: str, text: str, *, encoding: str = "utf-8", mode: int = 0o644) -> None:
    atomic_write_bytes(final_path, text.encode(encoding), mode=mode)


def atomic_replace_with_check(final_path: str, new_data: bytes, expected_stat=None, *, mode=0o644) -> None:
    """Recheck-before-commit: verify the inode/stat of final_path is unchanged
    from the earlier dry-run read, then atomically replace. (safety.recheck_before_commit)
    """
    if expected_stat is not None and os.path.exists(final_path):
        try:
            cur = os.stat(final_path)
        except OSError as e:
            raise map_oserror(e)
        if (cur.st_ino, cur.st_dev, cur.st_size, cur.st_mtime_ns) != (
            expected_stat.st_ino, expected_stat.st_dev, expected_stat.st_size, expected_stat.st_mtime_ns
        ):
            raise ModError("E_INODE_MISMATCH", detail=final_path)
    atomic_write_bytes(final_path, new_data, mode=mode)


def stat_v(path: str):
    try:
        return os.stat(path)
    except OSError:
        return None


def ensure_dir(path: str) -> None:
    """Create a directory (and parents) under an allowed root; map errors."""
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as e:
        raise map_oserror(e)


def preflight_root(path: str, *, need_writable=True) -> dict:
    """Preflight one write root: writable, free space, FS type, symlink safety.

    Returns a JSON-safe dict describing the root (used by dry-run / UI).
    """
    info = {"path": path, "exists": os.path.isdir(path), "posix": is_posix_fs(path)}
    if os.path.islink(path):
        raise ModError("E_STATE_SYMLINK", detail=path)
    if need_writable and os.path.isdir(path):
        if not os.access(path, os.W_OK):
            raise ModError("E_ACCESS", detail=path)
        try:
            stv = os.statvfs(path)
            info["free_bytes"] = stv.f_bavail * stv.f_frsize
            info["total_bytes"] = stv.f_blocks * stv.f_frsize
        except (OSError, AttributeError):
            info["free_bytes"] = None
    if info["exists"]:
        check_owner(path)
    return info


def same_filesystem(a: str, b: str) -> bool:
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return True  # unknown: let os.replace produce the real EXDEV if any
