"""Transaction engine — orchestrates import/install/enable/disable/uninstall/rollback.

Every mutating operation follows the same shape (§3.6 / §4 / §5.2):
  dry-run preflight (no writes) -> confirm (UI) -> PREPARED -> snapshot ->
  APPLYING -> staged writes -> recheck-before-commit -> atomic commit ->
  post-commit verify -> COMMITTED
  on any failure -> best-effort rollback -> ROLLED_BACK / ROLLBACK_FAILED

Hard rules:
  * refuse if game running (safety.refuse_if_game_running)
  * resolve paths on EVERY action, never cache (paths.resolve)
  * verify_on_open: compare stored state fingerprint to current -> E_STATE_EXTERNAL
  * staging/quarantine are SIBLINGS of Mods/, on the SAME filesystem (EXDEV)
  * capability gate checked on every op (registry.require)
  * no root / no read-only toggle / no network / no .exe execution
  * every failure is a stable E_* code via envelope, never a traceback
"""

from __future__ import annotations

import os
import shutil
import time
from typing import Optional

from . import archive, paths, state_mutator
from .envelope import envelope, err, ok
from .errors import ModError
from .fsops import (
    atomic_replace_with_check,
    atomic_write_bytes,
    ensure_dir,
    map_oserror,
    preflight_root,
    same_filesystem,
    stat_v,
)
from .journal import Journal, new_txn_id
from .registry import Registry

GAME_ID = "rimworld"


def _log_path(jrn: Journal) -> str:
    return jrn.log_path


class Engine:
    def __init__(self, registry: Registry | None = None, journal: Journal | None = None, decky=None):
        self.registry = registry or Registry()
        self.decky = decky
        self.journal = journal or self._default_journal()
        self._last_state_fp: dict = {}  # verify_on_open cache (per session)

    def _default_journal(self) -> Journal:
        # Decky-managed dirs (review #4). Env vars are provided by the loader.
        data = os.environ.get("DECKYMOD_DATA") or os.environ.get("DECKY_PLUGIN_RUNTIME_DIR") or ""
        if data and not data.rstrip("/\\").endswith("data"):
            data = os.path.join(data, "data")
        log = os.environ.get("DECKY_PLUGIN_LOG_DIR") or (os.path.join(data, "logs") if data else "")
        if not data:
            # dev / self-test fallback: a writable local dir
            data = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".decky-data")
            log = os.path.join(data, "logs")
        return Journal(data, log, GAME_ID)

    # ------------------------------------------------------------------ helpers
    def _gate(self, capability: str):
        self.registry.assert_enabled_count()
        return self.registry.require(GAME_ID, capability)

    def _resolve(self) -> paths.ResolvedPaths:
        # ALWAYS re-resolve; preflight=True does statvfs/writable/symlink checks.
        return paths.resolve(294100, preflight=True)

    def _check_not_running(self):
        """Best-effort: if a marker for a running RimWorld exists, refuse.

        ⚠️ V20: the real process-detection mechanism (e.g. checking the Steam
        app state / a PID file) must be confirmed on device. Here we use a
        conservative env/marker check and default to 'not running' so the
        self-tests work; the real implementation goes here.
        """
        marker = os.environ.get("DECKYMOD_GAME_RUNNING")
        if marker and marker.lower() in ("1", "true", "yes"):
            raise ModError("E_GAME_RUNNING", detail="DECKYMOD_GAME_RUNNING is set")

    def _check_no_pending(self):
        """Refuse a NEW transaction while an unfinished one is on the books.

        Round 51, same hole as the file_drop engine: ``journal.pending()`` was
        read by ``status()`` and ``recovery()`` but no write path acted on it, so
        a half-applied transaction (power loss, crash, or an exception between
        PREPARED and COMMITTED) could be walked over by the next install.

        ``E_RECOVERY_PENDING`` already existed with rollback=True and
        ``journal.py``'s docstring already promised it; nothing raised it. Using
        the existing code keeps ``error_codes()`` at 50.

        Deliberately NOT called from ``rollback()`` -- rollback IS the recovery.
        """
        try:
            pending = self.journal.pending()
        except Exception as exc:                     # noqa: BLE001 - never fail closed on a read
            self.journal.log("pending check could not read the journal: %s" % exc)
            return
        if not pending:
            return
        shown = ", ".join(pending[:3])
        if len(pending) > 3:
            shown += " (+%d more)" % (len(pending) - 3)
        raise ModError(
            "E_RECOVERY_PENDING",
            detail="%d unfinished transaction(s): %s -- use Recover / Rollback "
                   "before starting a new one" % (len(pending), shown))

    def _read_state(self, r: paths.ResolvedPaths):
        """Read + validate the state file; enforce verify_on_open drift check."""
        data, parsed, st = state_mutator.read_state_file(r.state_file)
        prev = self._last_state_fp.get(r.state_file)
        if prev and prev != parsed["fp"]:
            raise ModError("E_STATE_EXTERNAL", detail=f"state fp changed {prev} -> {parsed['fp']}")
        return data, parsed, st

    def _update_fp(self, r: paths.ResolvedPaths, data: bytes):
        self._last_state_fp[r.state_file] = state_mutator.fingerprint(data)

    def _existing_managed(self, package_id: str) -> Optional[dict]:
        return self.journal.installed().get(package_id)

    # ------------------------------------------------------------------ read ops
    def status(self) -> dict:
        """Non-mutating bootstrap: game resolution, enabled mods, pending recovery."""
        try:
            d = self._gate("local_import")
        except ModError as e:
            return err(e.code, detail=e.detail)
        try:
            r = self._resolve()
        except ModError as e:
            return err(e.code, detail=e.detail, data={"appid": 294100})
        state_info = {}
        if os.path.isfile(r.state_file):
            try:
                data, parsed, st = state_mutator.read_state_file(r.state_file)
                state_info = {"activeMods": parsed["activeMods"], "fp": parsed["fp"]}
                self._update_fp(r, data)
            except ModError as e:
                state_info = {"error": e.code, "detail": e.detail}
        else:
            # Surface a missing state file instead of an empty state object:
            # the UI must be able to show E_STATE_MISSING on bootstrap.
            state_info = {"error": "E_STATE_MISSING", "detail": r.state_file}
        pending = self.journal.pending()
        data = {
            "game": {"appid": 294100, "name": "RimWorld", "platform": "linux-native", "status": "enabled"},
            "paths": {
                "w1_state_file": r.state_file, "w2_mod_root": r.mod_root,
                "quarantine_root": r.quarantine_root, "staging": r.staging,
                "flatpak": r.flatpak, "fs_posix": r.fs_posix,
            },
            "state": state_info,
            "installed": list(self.journal.installed().values()),
            "pending_recovery": pending,
            "recovery_needed": bool(pending),
            "capabilities": d.get("capabilities", {}),
            "known_limitations": d.get("known_limitations", []),
            "known_limitation_keys": d.get("known_limitation_keys", []),
            "log_path": _log_path(self.journal),
        }
        return ok(data)

    def list_inbox(self) -> dict:
        """List local ZIPs in the fixed inbox (review #3: OSK path is optional UI)."""
        try:
            self._gate("local_import")
        except ModError as e:
            return err(e.code, detail=e.detail)
        inbox = os.environ.get("DECKYMOD_INBOX") or os.path.join(self.journal.decky_data, "inbox")
        if not os.path.isdir(inbox):
            return err("E_INBOX_MISSING", detail=inbox)
        try:
            names = sorted(n for n in os.listdir(inbox) if n.lower().endswith(".zip"))
        except OSError:
            return err("E_INBOX_UNREADABLE", detail=inbox)
        items = []
        for n in names:
            p = os.path.join(inbox, n)
            try:
                items.append({"name": n, "path": p, "size": os.path.getsize(p)})
            except OSError:
                items.append({"name": n, "path": p, "size": None})
        return ok({"inbox": inbox, "items": items, "log_path": _log_path(self.journal)})

    def inspect(self, zip_path: str) -> dict:
        """Dry-run inspection of ONE local ZIP (no writes)."""
        try:
            self._gate("local_import")
        except ModError as e:
            return err(e.code, detail=e.detail)
        # path safety: must be a local absolute path under the inbox or an
        # explicitly allowed OSK path (E_PATH_ESCAPE / E_PATH_INVALID)
        try:
            self._validate_import_path(zip_path)
        except ModError as e:
            return err(e.code, detail=e.detail)
        try:
            info = archive.inspect_mod(zip_path, self._limits())
        except ModError as e:
            return err(e.code, detail=e.detail)
        except OSError as e:
            return err(map_oserror(e).code, detail=e.strerror)
        # conflict preflight (no writes)
        r = self._resolve()
        dup = self._existing_managed(info["packageId"])
        collision = os.path.exists(os.path.join(r.mod_root, info["packageId"]))
        info.pop("members", None)  # do not bloat the wire
        return ok({
            "mod": info,
            "conflict": {
                "duplicate": bool(dup), "file_collision": collision and not dup,
                "managed": dup,
            },
            "targets": {"w1_state_file": r.state_file, "w2_install_dir": os.path.join(r.mod_root, info["packageId"])},
            "confirm_text": f"Install to {os.path.join(r.mod_root, info['packageId'])}",
            "log_path": _log_path(self.journal),
        })

    def _limits(self) -> dict:
        d = self.registry.get_game(GAME_ID)
        return d.get("mod_package", {}).get("limits", {})

    def _validate_import_path(self, p: str):
        if not isinstance(p, str) or not p:
            raise ModError("E_PATH_INVALID", detail="empty path")
        ap = os.path.abspath(p)
        inbox = os.path.abspath(os.environ.get("DECKYMOD_INBOX") or os.path.join(self.journal.decky_data, "inbox"))
        allowed = [inbox]
        extra = os.environ.get("DECKYMOD_EXTRA_IMPORT_ROOT")
        if extra:
            allowed.append(os.path.abspath(extra))
        # containment: p must be inside an allowed root
        if not any(ap == root or ap.startswith(root.rstrip(os.sep) + os.sep) for root in allowed):
            raise ModError("E_PATH_ESCAPE", detail=f"{ap} not inside {allowed}")
        if os.path.islink(ap):
            raise ModError("E_PATH_INVALID", detail="path is a symlink")
        if not os.path.isfile(ap):
            raise ModError("E_INBOX_UNREADABLE", detail=ap)

    # ------------------------------------------------------------------ install
    def install(self, zip_path: str, *, after_confirm: bool = False) -> dict:
        """Install a mod DIRECTORY into Mods/<packageId>/ (does NOT enable).

        Phase 1 (after_confirm=False) = dry-run + confirm payload (no writes).
        Phase 2 (after_confirm=True)  = execute the transaction.
        """
        try:
            return self._install_inner(zip_path, after_confirm)
        except ModError as e:
            return err(e.code, detail=e.detail, rollback_available=e.rollback_available)
        except OSError as e:
            return err(map_oserror(e).code, detail=e.strerror, rollback_available=True)
        except Exception as e:  # never leak a traceback
            self.journal.log(f"install unexpected: {type(e).__name__}: {e}")
            return err("E_UNKNOWN", detail=f"{type(e).__name__}: {e}")

    def _install_inner(self, zip_path: str, after_confirm: bool) -> dict:
        d = self._gate("local_import")
        self._check_not_running()
        self._check_no_pending()
        self._validate_import_path(zip_path)
        info = archive.inspect_mod(zip_path, self._limits())
        pid = info["packageId"]
        r = self._resolve()

        # conflict policy
        managed = self._existing_managed(pid)
        target = os.path.join(r.mod_root, pid)
        if managed and not after_confirm:
            raise ModError("E_DUPLICATE", detail=f"{pid} already managed", context={"packageId": pid})
        if os.path.exists(target) and not managed:
            raise ModError("E_FILE_COLLISION", detail=f"{target} exists and is not managed")

        # preflight BOTH write roots (§3.7 step 10)
        w1 = preflight_root(os.path.dirname(r.state_file), need_writable=True)
        w2 = preflight_root(r.game_root, need_writable=True)
        # cross-device guard: staging/quarantine must be on W2's FS
        if os.path.isdir(r.mod_root) and not same_filesystem(r.mod_root, r.staging):
            raise ModError("E_CROSS_DEVICE", detail="Mods/ and .decky-staging are on different filesystems")
        # Core invariant preflight (state file must exist & be valid)
        if os.path.isfile(r.state_file):
            data, parsed, st = state_mutator.read_state_file(r.state_file)
        else:
            raise ModError("E_STATE_MISSING", detail=r.state_file)

        plan = {
            "op": "install", "packageId": pid, "name": info["name"],
            "version": info["version"], "from": zip_path, "to": target,
            "w1": r.state_file, "free_w1": w1.get("free_bytes"), "free_w2": w2.get("free_bytes"),
            "fs_posix": r.fs_posix,
        }
        if not after_confirm:
            return ok({"phase": "confirm", "plan": plan,
                       "confirm_text": f"Install {info['name']} ({pid}) to {target}?\nState file: {r.state_file}",
                       "confirm_key": "CONFIRM_INSTALL_XML",
                       "confirm_vars": {"name": info["name"], "pid": pid,
                                        "target": target, "state": r.state_file},
                       "targets": {"w1_state_file": r.state_file, "w2_install_dir": target},
                       "log_path": _log_path(self.journal)})

        # ---- execute ----
        txn = new_txn_id()
        self.journal.begin(txn, "install", plan)
        self.journal.applying(txn)
        staged = os.path.join(r.staging, txn)
        try:
            # 1) stage directory on the SAME fs as W2, then rename into place
            ensure_dir(r.staging)
            stage_dest = os.path.join(staged, pid)
            archive.extract_to(info, zip_path, stage_dest)
            # 2) snapshot state file (for rollback bookkeeping)
            data, parsed, st = state_mutator.read_state_file(r.state_file)
            self.journal.write_snapshot(txn, "ModsConfig.xml.before", data)
            # 3) commit dir: same-fs rename. If a managed dir already exists
            # (replace path), move the OLD dir into quarantine first so the
            # operation stays reversible; never silently delete it.
            replaced_qdir = None
            if os.path.isdir(target):
                replaced_qdir = os.path.join(r.quarantine_root, txn, pid + ".replaced")
                ensure_dir(os.path.dirname(replaced_qdir))
                os.replace(target, replaced_qdir)
            os.replace(stage_dest, target)  # same filesystem -> no EXDEV
            # 4) record (no state-file change: install != enable)
            self.journal.record("MOD_INSTALLED", txn, packageId=pid, name=info["name"],
                                version=info["version"], dir=target, replaced_old=replaced_qdir, ts=time.time())
            # 5) post-commit verify
            if not os.path.isdir(target) or not os.path.isfile(os.path.join(target, "About", "About.xml")):
                raise ModError("E_VERIFY_FAILED", detail="installed dir missing About/About.xml")
            self.journal.committed(txn, {"packageId": pid, "dir": target})
            return ok({"packageId": pid, "dir": target, "enabled": False, "txn": txn,
                       "log_path": _log_path(self.journal)})
        except Exception as e:
            # best-effort rollback
            try:
                if os.path.isdir(target) and not managed:
                    shutil.rmtree(target, ignore_errors=True)
                self.journal.rolled_back(txn, {"reason": str(e)})
                return err(e.code if isinstance(e, ModError) else map_oserror(e).code if isinstance(e, OSError) else "E_OP_FAILED",
                           detail=str(e), rollback_available=False)
            except Exception as rb:
                self.journal.rollback_failed(txn, {"reason": str(rb)})
                return err("E_ROLLBACK_FAILED", detail=str(rb))
        finally:
            shutil.rmtree(staged, ignore_errors=True)

    # ------------------------------------------------------------------ enable/disable
    def set_enabled(self, package_id: str, enabled: bool, *, after_confirm: bool = False) -> dict:
        try:
            return self._set_enabled_inner(package_id, enabled, after_confirm)
        except ModError as e:
            return err(e.code, detail=e.detail, rollback_available=e.rollback_available)
        except OSError as e:
            return err(map_oserror(e).code, detail=e.strerror)
        except Exception as e:
            self.journal.log(f"set_enabled unexpected: {type(e).__name__}: {e}")
            return err("E_UNKNOWN", detail=f"{type(e).__name__}: {e}")

    def _set_enabled_inner(self, package_id: str, enabled: bool, after_confirm: bool) -> dict:
        self._gate("enable_disable")
        self._check_not_running()
        self._check_no_pending()
        if not package_id or package_id == state_mutator.CORE_ID:
            raise ModError("E_ID_INVALID", detail="cannot toggle the Core entry")
        managed = self._existing_managed(package_id)
        if not managed:
            raise ModError("E_DUPLICATE", detail=f"{package_id} is not installed/managed")
        r = self._resolve()
        data, parsed, st = self._read_state(r)  # verify_on_open drift check
        currently = package_id in parsed["activeMods"]
        if currently == enabled:
            return ok({"packageId": package_id, "enabled": enabled, "noop": True,
                       "log_path": _log_path(self.journal)})

        plan = {"op": "enable" if enabled else "disable", "packageId": package_id,
                "w1": r.state_file, "core_first": parsed["activeMods"][0]}
        if not after_confirm:
            return ok({"phase": "confirm", "plan": plan,
                       "confirm_text": f"{'Enable' if enabled else 'Disable'} {package_id} in ModsConfig.xml?",
                       "confirm_key": "CONFIRM_ENABLE" if enabled else "CONFIRM_DISABLE",
                       "confirm_vars": {"pid": package_id},
                       "targets": {"w1_state_file": r.state_file},
                       "log_path": _log_path(self.journal)})

        txn = new_txn_id()
        self.journal.begin(txn, plan["op"], plan)
        self.journal.applying(txn)
        try:
            # snapshot the WHOLE original file (rollback restores bytes verbatim)
            self.journal.write_snapshot(txn, "ModsConfig.xml.before", data)
            new_data = state_mutator.add_entry(data, package_id) if enabled else state_mutator.remove_entry(data, package_id)
            # recheck-before-commit: inode/mtime unchanged since dry-run read
            atomic_replace_with_check(r.state_file, new_data, expected_stat=st)
            # post-commit verify: re-read + confirm the intended membership
            verify_data, verify_parsed, _ = state_mutator.read_state_file(r.state_file)
            if (package_id in verify_parsed["activeMods"]) != enabled:
                raise ModError("E_VERIFY_FAILED", detail="post-commit state mismatch")
            self._update_fp(r, verify_data)
            self.journal.record("MOD_ENABLED" if enabled else "MOD_DISABLED", txn, packageId=package_id)
            self.journal.committed(txn, {"packageId": package_id, "enabled": enabled})
            return ok({"packageId": package_id, "enabled": enabled, "txn": txn,
                       "log_path": _log_path(self.journal)})
        except Exception as e:
            # restore from snapshot
            try:
                snap = self.journal.read_snapshot(txn, "ModsConfig.xml.before")
                atomic_write_bytes(r.state_file, snap)
                self._update_fp(r, snap)
                self.journal.rolled_back(txn, {"reason": str(e)})
                code = e.code if isinstance(e, ModError) else (map_oserror(e).code if isinstance(e, OSError) else "E_OP_FAILED")
                return err(code, detail=str(e))
            except Exception as rb:
                self.journal.rollback_failed(txn, {"reason": str(rb)})
                return err("E_ROLLBACK_FAILED", detail=str(rb))

    # ------------------------------------------------------------------ uninstall
    def uninstall(self, package_id: str, *, after_confirm: bool = False) -> dict:
        try:
            return self._uninstall_inner(package_id, after_confirm)
        except ModError as e:
            return err(e.code, detail=e.detail)
        except OSError as e:
            return err(map_oserror(e).code, detail=e.strerror)
        except Exception as e:
            self.journal.log(f"uninstall unexpected: {type(e).__name__}: {e}")
            return err("E_UNKNOWN", detail=f"{type(e).__name__}: {e}")

    def _uninstall_inner(self, package_id: str, after_confirm: bool) -> dict:
        self._gate("uninstall_quarantine")
        self._check_not_running()
        self._check_no_pending()
        managed = self._existing_managed(package_id)
        if not managed:
            raise ModError("E_DUPLICATE", detail=f"{package_id} is not installed/managed")
        r = self._resolve()
        # if enabled, disable first (part of this transaction)
        data, parsed, st = self._read_state(r)
        was_enabled = package_id in parsed["activeMods"]
        src = managed.get("dir") or os.path.join(r.mod_root, package_id)
        txn = new_txn_id()
        qdir = os.path.join(r.quarantine_root, txn, package_id)
        plan = {"op": "uninstall", "packageId": package_id, "from": src, "quarantine": qdir,
                "was_enabled": was_enabled, "w1": r.state_file}
        if not after_confirm:
            # quarantine space preflight (same fs as W2 required)
            if os.path.isdir(src) and not same_filesystem(src, r.quarantine_root):
                raise ModError("E_CROSS_DEVICE", detail="mod dir and quarantine are on different filesystems")
            return ok({"phase": "confirm", "plan": plan,
                       "confirm_text": f"Uninstall {package_id}? The folder is moved to quarantine (not deleted).",
                       "confirm_key": "CONFIRM_UNINSTALL",
                       "confirm_vars": {"pid": package_id},
                       "targets": {"w1_state_file": r.state_file, "w2_quarantine": qdir},
                       "log_path": _log_path(self.journal)})

        self.journal.begin(txn, "uninstall", plan)
        self.journal.applying(txn)
        try:
            try:
                sz = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(src) for f in fs)
                stv = os.statvfs(r.quarantine_root)
                if sz > stv.f_bavail * stv.f_frsize:
                    raise ModError("E_QUARANTINE_FULL", detail=f"need {sz} bytes")
            except (OSError, AttributeError):
                pass
            self.journal.write_snapshot(txn, "ModsConfig.xml.before", data)
            # 1) disable in state file if needed (atomic, with recheck)
            if was_enabled:
                new_data = state_mutator.remove_entry(data, package_id)
                atomic_replace_with_check(r.state_file, new_data, expected_stat=st)
                data = new_data
            # 2) move dir into quarantine (SAME fs) — never delete
            ensure_dir(os.path.dirname(qdir))
            if os.path.isdir(src):
                os.replace(src, qdir)
            # 3) record
            self.journal.record("MOD_UNINSTALLED", txn, packageId=package_id, from_path=src,
                                quarantine=qdir, txn_quarantine=txn, enabled=False)
            self.journal.committed(txn, {"packageId": package_id, "quarantine": qdir})
            self._update_fp(r, state_mutator.read_state_file(r.state_file)[0])
            return ok({"packageId": package_id, "quarantine": qdir, "txn": txn,
                       "rollback_hint": "Use rollback to restore this mod",
                       "log_path": _log_path(self.journal)})
        except Exception as e:
            try:
                # restore dir + state
                if os.path.isdir(qdir) and not os.path.isdir(src):
                    os.replace(qdir, src)
                snap = self.journal.read_snapshot(txn, "ModsConfig.xml.before")
                atomic_write_bytes(r.state_file, snap)
                self._update_fp(r, snap)
                self.journal.rolled_back(txn, {"reason": str(e)})
                code = e.code if isinstance(e, ModError) else (map_oserror(e).code if isinstance(e, OSError) else "E_OP_FAILED")
                return err(code, detail=str(e))
            except Exception as rb:
                self.journal.rollback_failed(txn, {"reason": str(rb)})
                return err("E_ROLLBACK_FAILED", detail=str(rb))

    # ------------------------------------------------------------------ rollback
    def rollback(self, txn: str) -> dict:
        """Restore the LAST committed op for txn (mainly uninstall) or recover
        a PREPARED/APPLYING txn. Mirrors uninstall/enable in reverse.
        """
        try:
            return self._rollback_inner(txn)
        except ModError as e:
            return err(e.code, detail=e.detail)
        except OSError as e:
            return err(map_oserror(e).code, detail=e.strerror)
        except Exception as e:
            self.journal.log(f"rollback unexpected: {type(e).__name__}: {e}")
            return err("E_UNKNOWN", detail=f"{type(e).__name__}: {e}")

    def _rollback_inner(self, txn: str) -> dict:
        self._gate("rollback")
        self._check_not_running()
        events = self.journal.events(txn)
        if not events:
            raise ModError("E_UNKNOWN", detail=f"unknown txn {txn}")
        state = self.journal.state(txn)
        r = self._resolve()

        # find the uninstall event (the one with a quarantine path)
        uninst = next((e for e in events if e.get("event") == "MOD_UNINSTALLED"), None)
        if uninst and state in ("COMMITTED", "APPLYING", "PREPARED"):
            pid = uninst["packageId"]
            qdir = uninst["quarantine"]
            src = uninst["from_path"]
            # restore state file from the snapshot taken before uninstall
            try:
                snap = self.journal.read_snapshot(txn, "ModsConfig.xml.before")
            except ModError:
                snap = None
            if os.path.isdir(qdir) and not os.path.isdir(src):
                os.replace(qdir, src)  # same fs
            if snap is not None:
                atomic_write_bytes(r.state_file, snap)
                self._update_fp(r, snap)
            self.journal.record("MOD_ROLLBACK_RESTORED", txn, packageId=pid,
                                mod={"name": pid, "dir": src}, enabled=False)
            self.journal.committed(txn, {"rollback_of": "uninstall", "packageId": pid})
            return ok({"restored": pid, "dir": src, "txn": txn,
                       "log_path": _log_path(self.journal)})

        # generic: restore the pre-op state snapshot for enable/disable
        st = self.journal.state(txn)
        if st in ("PREPARED", "APPLYING"):
            try:
                snap = self.journal.read_snapshot(txn, "ModsConfig.xml.before")
                atomic_write_bytes(r.state_file, snap)
                self._update_fp(r, snap)
                self.journal.rolled_back(txn, {"recovered": True})
                return ok({"recovered": True, "txn": txn, "log_path": _log_path(self.journal)})
            except Exception as rb:
                self.journal.rollback_failed(txn, {"reason": str(rb)})
                return err("E_ROLLBACK_FAILED", detail=str(rb))
        raise ModError("E_UNKNOWN", detail=f"nothing to roll back for txn {txn} (state={state})")

    # ------------------------------------------------------------------ history / refresh
    def history(self, limit: int = 50) -> dict:
        try:
            return ok({"items": self.journal.history(limit), "log_path": _log_path(self.journal)})
        except Exception as e:
            return err("E_UNKNOWN", detail=str(e))

    def refresh(self) -> dict:
        """Re-resolve + verify_on_open drift check; clear fp cache."""
        self._last_state_fp.clear()
        return self.status()

    def recovery(self) -> dict:
        try:
            return ok({"pending": self.journal.pending(), "log_path": _log_path(self.journal)})
        except Exception as e:
            return err("E_UNKNOWN", detail=str(e))
