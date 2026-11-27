"""Descriptor-driven file_drop backend (Steps 2-4, goal-221c8ac6 rev2).

Approved plan 2026-11-14 (m04651). This engine is game-AGNOSTIC: it contains
no game id, AppID, game name, or manifest field-name literals at runtime.
Game identity is ``self.game_id`` (from the active descriptor) and manifest
field names all live in the descriptor's ``mod_package`` consumed by
``deckymod/manifest.py``. ``main.Plugin`` selects this class via the
descriptor's ``engine: "file_drop"`` key — there is no ``if game == ...``.

It stays a SEPARATE engine from the RimWorld ``Engine`` so the 41-green
real-machine RimWorld path remains byte-identical.

Posture (hard constraints preserved):
  * An external user-installed launcher (e.g. SMAPI) is DETECTED, never installed.
  * Steam launch options must ALREADY be set: never edited.
  * No Proton pfx, no DLL override, no loader install, no root, no read-only
    toggle, no universal one-click install, no network.
  * If a third-party mod manager owns Mods/ (Amethyst VFS markers), EVERY
    write RPC returns E_EXTERNAL_MANAGER -> read-only, zero damage.
  * file_drop games have NO state file. A mod is enabled iff its DIRECTORY is
    present under Mods/. install == enable; no ModsConfig.xml/<activeMods>/Core.

Both engines expose the SAME 11 positional RPC methods, so Plugin/frontend
never need to know which one is active. Returns JSON-safe envelopes (ok/err).
"""

from __future__ import annotations

import os
import shutil
import time

from . import (
    archive,
    conflicts,
    file_drop,
    fomod,
    handover,
    import_root,
    loaderlog,
    manifest,
    modwatch,
    paths,
    procs,
    quarantine,
    upgrade,
)
from .envelope import err, ok
from .errors import ModError
from .fsops import ensure_dir, map_oserror, preflight_root, same_filesystem
from .journal import Journal, new_txn_id
from .registry import Registry


def _log_path(jrn: Journal) -> str:
    return jrn.log_path


def _slug(path: str) -> str:
    """A filesystem-safe folder name for one handed-over mod root.

    Round 81: an engine can now hand over more than one folder, so each needs
    its own quarantine subfolder. Derived from the absolute path so two roots
    with the same basename cannot collide, and stripped to ``[A-Za-z0-9._-]`` so
    it is safe on every filesystem this plugin meets.
    """
    raw = str(path or "").replace("\\", "/").strip("/")
    safe = "".join(c if (c.isalnum() or c in "._-") else "_" for c in raw)
    return safe[-120:] or "root"


class FileDropEngine:
    def __init__(self, registry: Registry | None = None, journal: Journal | None = None,
                 decky=None, game_id: str | None = None):
        self.registry = registry or Registry()
        # game identity comes from the descriptor, NEVER a module constant
        self.game_id = game_id or self.registry.active_descriptor()[0]
        self.decky = decky
        self.journal = journal or self._default_journal()

    def _default_journal(self) -> Journal:
        data = os.environ.get("DECKYMOD_DATA") or os.environ.get("DECKY_PLUGIN_RUNTIME_DIR") or ""
        if data and not data.rstrip("/\\").endswith("data"):
            data = os.path.join(data, "data")
        log = os.environ.get("DECKY_PLUGIN_LOG_DIR") or (os.path.join(data, "logs") if data else "")
        if not data:
            data = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".decky-data")
            log = os.path.join(data, "logs")
        return Journal(data, log, self.game_id)

    # ------------------------------------------------------------------ helpers
    def _descriptor(self) -> dict:
        return self.registry.get_game(self.game_id)

    def _mod_package(self) -> dict:
        return self._descriptor().get("mod_package", {}) or {}

    def _gate(self, capability: str):
        self.registry.assert_enabled_count()
        return self.registry.require(self.game_id, capability)

    def _resolve(self) -> paths.ResolvedPaths:
        appid = self.registry.appid_for(self.game_id)   # from descriptor identity
        # Round 43 / P1#5: pass the descriptor's own ``paths`` block so a second
        # game can name its mod folder instead of being forced onto ``Mods``.
        return paths.resolve(appid, preflight=True, no_state_file=True,
                             descriptor_paths=self._descriptor_paths())

    def _descriptor_paths(self) -> dict:
        p = self._descriptor().get("paths")
        return p if isinstance(p, dict) else {}

    def _running(self, r: paths.ResolvedPaths) -> dict:
        """Round 50: is the game running, decided from /proc argv[0].

        ``safety.refuse_if_game_running`` was true in the descriptor while the
        only implementation read an environment variable nothing sets, so the
        flag was a promise the code did not keep. Markers come from the
        descriptor; the decision comes from deckymod/procs.py.
        """
        det = self._descriptor().get("loader_detection", {}) or {}
        cfg = det.get("running_detection") or {}
        if cfg.get("enabled") is False:
            return {"state": "unknown", "pid": "", "match": "", "scanned": 0,
                    "detail": "running detection is disabled in the descriptor"}
        markers = det.get(cfg.get("markers") or "running_process_markers") or []
        try:
            return procs.is_running(r.game_root, markers)
        except Exception as exc:                     # noqa: BLE001 - never fail
            return {"state": "unknown", "pid": "", "match": "", "scanned": 0,
                    "detail": "%s: %s" % (type(exc).__name__, exc)}

    def _external_markers(self):
        """Marker names for another mod manager, from the descriptor.

        Round 53: ``loader_detection.external_manager_markers`` declared
        ``[".mm_deployed", "Mods_Core"]`` while ``file_drop.py`` hard-coded the
        same two strings, so the key was decoration. Passing it through means a
        descriptor for a different game can name its own marker and actually be
        honoured -- and ``None`` still falls back to the historical pair, so the
        Stardew behaviour is byte-identical.
        """
        det = self._descriptor().get("loader_detection", {}) or {}
        markers = det.get("external_manager_markers")
        if not markers:
            return None
        return [str(m) for m in markers if str(m)]

    def _check_not_running(self):
        """Refuse a write while the game has the mod files open.

        The env-var seam is kept for tests and for an explicit override, but it
        is no longer the only signal -- on this device nothing ever set it, so
        every destructive op ran unchecked. ``unknown`` does NOT refuse: a
        host without /proc would otherwise make the plugin write-nothing, and
        the descriptor's ``post_commit_verify`` plus the journal are what cover
        the rest. Refusing on ``running`` is the case that matters.
        """
        marker = os.environ.get("DECKYMOD_GAME_RUNNING")
        if marker and marker.lower() in ("1", "true", "yes"):
            raise ModError("E_GAME_RUNNING", detail="DECKYMOD_GAME_RUNNING is set")
        cfg = (self._descriptor().get("safety") or {})
        if not cfg.get("refuse_if_game_running", True):
            return
        try:
            r = self._resolve()
        except ModError:
            return          # resolution already failed; its own error is better
        got = self._running(r)
        if got.get("state") == "running":
            raise ModError("E_GAME_RUNNING", detail=procs.describe(got))

    def _check_no_pending(self):
        """Refuse a NEW transaction while an unfinished one is on the books.

        Round 51: ``journal.pending()`` was read by ``status()`` and
        ``recovery()`` -- the panel could say "recovery needed" -- but no write
        path consulted it. A device probe confirmed the consequence: with a
        PREPARED/APPLYING transaction in the journal, ``install()`` happily
        started a second one, so the journal ended up interleaved and a later
        rollback would have undone states in the wrong order.

        ``E_RECOVERY_PENDING`` already existed (``errors.py``, rollback=True) and
        ``journal.py``'s own docstring said an unfinished transaction must
        surface as it -- it was simply never raised. Using it keeps
        ``error_codes()`` at 50.

        NOT called from ``rollback()``: rollback IS the recovery, so gating it
        here would leave a stuck journal unfixable.
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

    def _locate(self, r, dn: str, managed) -> dict:
        """Where a mod directory for ``dn`` lives, and why.

        Round 60. In this engine "disabled" is a LOCATION: a mod with a folder in
        Mods/ is loaded, and disabling it moves the folder to .decky-disabled/.
        Three separate code paths used to compute that answer themselves (rounds
        57-59), and each got it wrong in its own way before being fixed. Keeping
        one expression is not tidiness -- a second copy is a second chance to
        disagree with the first, and the disagreement is user-visible because
        inspect()'s answer becomes the sentence the user agrees to.

        Returns a dict rather than a tuple so call sites read as what they mean:

          install_at  where the bytes live / will live
          parked      True when the journal manages this mod AND a real
                      directory is parked for it -- i.e. the user disabled it
          parked_at   the parked path, whether or not it is the live one
          target      the Mods/ path, always

        ``parked`` deliberately requires ``managed``: a folder that merely shares
        the name is not ours to treat as our own copy, and install/uninstall both
        refuse it separately rather than silently adopting it.
        """
        target = os.path.join(r.mod_root, dn)
        parked_at = os.path.join(r.disabled_root, dn)
        parked = bool(managed) and os.path.isdir(parked_at) and not os.path.islink(parked_at)
        return {
            "target": target,
            "parked_at": parked_at,
            "parked": bool(parked),
            "install_at": parked_at if parked else target,
        }

    def _check_write_allowed(self, r: paths.ResolvedPaths):
        """DETECT-ONLY gate for EVERY mutating op. Order matters: the descriptor
        and external-manager read-only switches are highest priority (zero
        damage). Launcher/launch-option checks come from the descriptor so this
        engine stays game-agnostic — no ``if game == ...`` branch here."""
        d = self._descriptor()
        # A read-only descriptor (Step 4 pluggability proof) refuses ALL writes
        # before any launcher-specific check is reached.
        if d.get("force_read_only"):
            raise ModError("E_CAPABILITY_DISABLED",
                           detail="descriptor is read-only; writes are disabled (detection_only)")
        # Round 53: ``safety.refuse_if_external_manager`` is NOT read here on
        # purpose. The check below runs unconditionally, which is strictly
        # stricter than the descriptor's ``true``; honouring a descriptor that
        # said ``false`` would turn an unconditional refuse into a switch that
        # silently permits writing into another manager's tree. Leaving it
        # unread means the flag can only ever be a no-op, never a size.
        if file_drop.detect_external_manager(r.game_root, r.mod_root,
                                             self._external_markers()):
            raise ModError("E_EXTERNAL_MANAGER",
                           detail=f"external mod manager markers in {r.mod_root}; read-only mode")
        # Round 44: markers only ever recognise the tools somebody thought of.
        # The LAYOUT is the durable signal (symlinked Mods/, symlinked entries,
        # another filesystem), so refuse on that too. Nothing here guesses from
        # names, mtimes or counts -- see deckymod/modwatch.py.
        foreign = modwatch.survey(r.game_root, r.mod_root)
        if modwatch.is_foreign(foreign):
            raise ModError("E_EXTERNAL_MANAGER",
                           detail="%s; read-only mode" % modwatch.describe(foreign))
        det = d.get("loader_detection", {}) or {}
        patterns = det.get("patterns") or []
        if patterns and not file_drop.detect_loader(r.game_root, patterns):
            on_missing = det.get("on_missing_launcher", "E_LOADER_MISSING")
            raise ModError(on_missing, detail=f"required launcher not detected in {r.game_root}")
        if det.get("launch_options_must_already_be_set") and \
                file_drop.check_launch_options(
                    r.user_home,
                    appid=str(d.get("identity", {}).get("appid", "")),
                    launcher_token=det.get("launcher_token") or "") == "missing":
            raise ModError("E_LAUNCH_OPTIONS_MISSING",
                           detail="Steam launch options do not reference the required launcher")

    def _limits(self) -> dict:
        return self._mod_package().get("limits", {})

    def _reject_extensions(self):
        return self._mod_package().get(
            "reject_extensions", list(file_drop.SMAPI_FORBIDDEN_EXT))

    def _manifest_basename(self) -> str:
        """Manifest file name for post-write verify, from descriptor globs."""
        globs = self._mod_package().get("manifest_globs") or []
        return str(globs[0]).rsplit("/", 1)[-1] if globs else "manifest.json"

    def _existing_managed(self, unique_id: str):
        inst = self.journal.installed()
        if unique_id in inst:
            return inst[unique_id]
        low = str(unique_id).lower()
        for k, v in inst.items():
            if str(k).lower() == low:
                return v
        return None

    def _disk_dirs_with_uid(self, mod_root: str, uid: str, *, exclude: str = ""):
        """Directories on disk whose manifest declares ``uid`` (case-insensitive).

        Round 27: install used to compare only DIRECTORY NAMES, so a mod whose
        UniqueID already existed under a different folder name was unpacked a
        second time. Two folders then declared the same UniqueID, SMAPI loads
        both, and the user ends up with two half-configured copies — exactly the
        conflict criterion 3 asks us to detect.

        Read-only; a single unreadable manifest never aborts the scan.
        """
        want = str(uid).strip().lower()
        if not want:
            return []
        try:
            scanned = manifest.scan_installed_mods(mod_root, self._mod_package())
        except Exception:  # a scan failure must not block installing
            return []
        hits = []
        for m in scanned.get("mods") or []:
            d = m.get("dir")
            if not d or d == exclude:
                continue
            if str(m.get("uniqueId") or "").strip().lower() == want:
                hits.append(d)
        return sorted(hits)

    def _resolve_disk_dir(self, name: str, mod_root: str):
        """Resolve a mod DIRECTORY that this plugin does not manage.

        Round 20: the plugin can list every mod on disk (``status.state.mods``)
        but could only uninstall ones it had installed itself, because
        ``uninstall`` consulted the journal alone. Users who arrive with a
        pre-populated ``Mods/`` therefore had no way to manage them.

        Security: the caller supplies a DIRECTORY NAME, never a path. It must be
        a single path component, must not be a symlink, must resolve (via realpath)
        directly inside ``mod_root``, and must actually be a directory. Anything
        else returns None so the caller raises its existing error.
        """
        if not isinstance(name, str) or not name:
            return None
        # single component only: no separators, no traversal, not hidden
        if os.sep in name or (os.altsep and os.altsep in name) or name in (".", ".."):
            return None
        if os.path.basename(name) != name or name.startswith("."):
            return None
        candidate = os.path.join(mod_root, name)
        if os.path.islink(candidate):
            return None
        try:
            real_root = os.path.realpath(mod_root)
            real = os.path.realpath(candidate)
        except OSError:
            return None
        if os.path.dirname(real) != real_root:
            return None
        if not os.path.isdir(real):
            return None
        return real

    def _import_roots(self):
        """The inbox plus every root the descriptor DECLARES (Round 42)."""
        inbox = os.environ.get("DECKYMOD_INBOX") or os.path.join(self.journal.decky_data, "inbox")
        try:
            user_home = self._resolve().user_home
        except Exception:                                   # noqa: BLE001
            # Resolution failure must not take the import list with it: without a
            # home directory we simply have no extra roots to offer.
            user_home = os.path.expanduser("~")
        return import_root.roots_for(inbox, self._descriptor(), user_home)

    def _validate_import_path(self, p: str):
        if not isinstance(p, str) or not p:
            raise ModError("E_PATH_INVALID", detail="empty path")
        ap = os.path.abspath(p)
        allowed = import_root.allowed_roots(self._import_roots())
        extra = os.environ.get("DECKYMOD_EXTRA_IMPORT_ROOT")
        if extra:
            allowed.append(os.path.abspath(extra))
        if not any(ap == root or ap.startswith(root.rstrip(os.sep) + os.sep) for root in allowed):
            raise ModError("E_PATH_ESCAPE", detail=f"{ap} not inside {allowed}")
        if os.path.islink(ap):
            raise ModError("E_PATH_INVALID", detail="path is a symlink")
        if not os.path.isfile(ap):
            raise ModError("E_INBOX_UNREADABLE", detail=ap)

    def delete_source_zip(self, zip_path: str) -> dict:
        """Remove the source ZIP after a successful install (round 80, opt-in).

        The user taps "install and delete the ZIP" in the confirm dialog; this
        is the backend half. Scope guards:
          * the path must sit inside a DECLARED import root (inbox / Downloads)
            — the same containment the import path validates, so no caller can
            turn this into a general file deleter;
          * it must be a regular file (not a symlink, not a directory);
          * the removal is logged to the journal for traceability.
        The ZIP is not user data the journal can restore — it is the SOURCE of
        an install that already committed — so this is honest about being
        irreversible, which is exactly why it is a separate, explicit call
        instead of an automatic side effect.
        """
        try:
            self._gate("local_import")
        except ModError as e:
            return err(e.code, detail=e.detail)
        try:
            self._validate_import_path(zip_path)
            os.remove(zip_path)
            self.journal.log("source zip removed: %s" % zip_path)
            return ok({"removed": str(zip_path)})
        except ModError as e:
            return err(e.code, detail=e.detail)
        except OSError as e:
            return err(map_oserror(e).code, detail=e.strerror)

    # ------------------------------------------------------------------ read ops
    def _probe(self, r: paths.ResolvedPaths) -> dict:
        """Descriptor-driven, READ-ONLY detection shared by status/gate.

        No game id branch: launcher patterns, appid and the launch-option token
        all come from ``loader_detection`` / ``identity`` in the descriptor.
        A descriptor with no declared launcher has nothing to detect (loader is
        treated as satisfied); ``force_read_only`` (Step 4) forces read_only.
        """
        d = self._descriptor()
        det = d.get("loader_detection", {}) or {}
        external = file_drop.detect_external_manager(r.game_root, r.mod_root,
                                                     self._external_markers())
        patterns = det.get("patterns") or []
        loader = file_drop.detect_loader(r.game_root, patterns) if patterns else True
        lo = "n/a"
        if det.get("launch_options_must_already_be_set"):
            lo = file_drop.check_launch_options(
                r.user_home,
                appid=str(d.get("identity", {}).get("appid", "")),
                launcher_token=det.get("launcher_token") or "")
        # Round 44: the marker check above only recognises known tools. The layout
        # survey is what catches "somebody else deployed this folder" in general,
        # and it is also what lets the panel say WHY instead of just "read-only".
        try:
            foreign = modwatch.survey(r.game_root, r.mod_root)
        except Exception:                             # noqa: BLE001 - never fail probe
            foreign = {"checked": False, "reasons": [], "explain": ""}
        read_only = bool(external or not loader or lo == "missing"
                         or d.get("force_read_only") or modwatch.is_foreign(foreign))
        return {"external_manager": bool(external), "loader_detected": bool(loader),
                "launch_options": lo, "read_only": read_only,
                "layout": foreign}

    def status(self) -> dict:
        try:
            d = self._gate("local_import")
        except ModError as e:
            return err(e.code, detail=e.detail)
        try:
            r = self._resolve()
        except ModError as e:
            return err(e.code, detail=e.detail,
                       data={"appid": self.registry.appid_for(self.game_id)})
        probe = self._probe(r)
        # Step 2: read-only enumeration of installed mods. Parses every
        # manifest via the descriptor parser, computes missing deps / duplicate
        # ids. A single bad manifest is isolated to parse_error, never aborts
        # the whole status. NO writes, NO journal.begin -> safe in read_only.
        # Round 66: the parked root is scanned FIRST so the active scan can be
        # told which ids are disabled rather than absent. Both are read-only.
        disabled_scan = manifest.scan_installed_mods(r.disabled_root, self._mod_package())
        parked_ids = [m["uniqueId"] for m in disabled_scan["mods"]
                      if m.get("uniqueId")]
        scanned = manifest.scan_installed_mods(r.mod_root, self._mod_package(),
                                               parked_ids=parked_ids)
        # Round 40: ask the loader's own log what it actually accepted. This is the
        # only place in the plugin that can tell "in Mods/" from "in the game" --
        # the device showed 30 folders against 22 loaded mods and 3 content packs.
        # Read-only, and a missing log is the NORMAL state before the first launch,
        # so any failure here degrades to `available: False` and never fails status.
        try:
            load_cfg = (d.get("loader_detection", {}) or {}).get("loader_log", {}) or {}
            log_info = loaderlog.inspect(r.game_root, r.user_home, r.xdg_config,
                                         load_cfg, scanned["mods"])
        except Exception as exc:                      # noqa: BLE001 - status must survive
            log_info = {"ok": False, "reason": "log_unreadable",
                        "detail": "%s: %s" % (exc.__class__.__name__, exc)}
        # Parked mods are deliberately NOT annotated: a disabled mod is absent from
        # the log by construction, and reporting it as "unknown" would read as a
        # fault when it is the user's own choice.
        active_mods = log_info.get("mods") if log_info.get("ok") else scanned["mods"]
        log_block = (log_info.get("summary") if log_info.get("ok")
                     else {"available": False,
                           "reason": log_info.get("reason") or "unavailable",
                           "detail": log_info.get("detail") or ""})
        # Round 25: mods parked in .decky-disabled/ are still the user's mods and
        # must stay visible, otherwise disabling one makes it vanish from the UI
        # with no way back. (Round 66: this scan now happens above, because the
        # active scan needs its ids to tell "disabled" from "absent".)
        # Round 47: which paths do two mods both ship? A fact about the
        # filesystem, not about the game -- so it needs no per-game knowledge,
        # and it is read-only like everything else in status(). A failure here
        # must not take the whole status down with it.
        try:
            conf_cfg = (self._mod_package() or {}).get("conflicts") or {}
            conflict_info = conflicts.survey(r.mod_root, scanned["mods"], conf_cfg)
        except Exception as exc:  # noqa: BLE001 - status must survive
            conflict_info = {"checked": False, "reason": "scan_failed",
                             "detail": "%s: %s" % (exc.__class__.__name__, exc),
                             "conflicts": [], "total": 0, "truncated": False}
        # Round 48: a quarantine folder is only restorable while the journal
        # still holds the MOD_UNINSTALLED record that names it. Past that it is
        # space the user believes is recoverable and no code path can reach --
        # measured on the device at 29 of 45 folders, one holding a real mod.
        # Reported, never cleaned: deleting folders this plugin did not create
        # is one bug away from deleting a mod the user wanted.
        try:
            quar_info = quarantine.survey(r.quarantine_root, self.journal)
        except Exception as exc:  # noqa: BLE001 - status must survive
            quar_info = {"checked": False, "reason": "scan_failed",
                         "detail": "%s: %s" % (exc.__class__.__name__, exc),
                         "entries": [], "dirs": 0, "total_bytes": 0,
                         "restorable": 0, "orphans": 0, "empty": 0}
        ident = d.get("identity", {}) or {}
        # Round 50: answered from /proc rather than assumed. "unknown" is kept
        # distinct from "stopped" so the panel can say it could not check.
        running_info = self._running(r)
        pending = self.journal.pending()
        data = {
            "game": {"appid": ident.get("appid"), "name": ident.get("name") or self.game_id,
                     "platform": ident.get("platform") or "", "status": d.get("status") or ""},
            "paths": {
                "w1_state_file": None, "w2_mod_root": r.mod_root,
                "quarantine_root": r.quarantine_root, "staging": r.staging,
                "disabled_root": r.disabled_root,
                "flatpak": r.flatpak, "fs_posix": r.fs_posix,
            },
            "state": {
                "strategy": "file_drop",
                "mods": active_mods,
                "disabled_mods": disabled_scan["mods"],
                "duplicate_ids": scanned["duplicate_ids"],
                "missing_dependencies": scanned["missing_dependencies"],
                # Round 66: dependencies the user owns but disabled. Reported
                # apart from missing ones: the remedy is "enable it", and the
                # fetcher reads the missing list only.
                "parked_dependencies": scanned["parked_dependencies"],
                # Round 67: dependencies that are installed but older than the
                # mod needing them. A third list, because the remedy is a third
                # verb: not "download it" (missing) nor "enable it" (parked) but
                # "update it". SMAPI skips the dependent mod in this state, so
                # staying silent meant the panel called a refused mod healthy.
                "outdated_dependencies": scanned["outdated_dependencies"],
                "external_manager": probe["external_manager"],
                "loader_detected": probe["loader_detected"],
                "launch_options": probe["launch_options"],
                "read_only": probe["read_only"],
                "layout": probe.get("layout") or {},
                # Round 47: paths shipped by more than one mod. Reported, never
                # resolved -- ordering needs per-game knowledge this plugin does
                # not have and should not pretend to have.
                "conflicts": conflict_info,
            "quarantine": quar_info,
                # Round 50: whether the game is running RIGHT NOW, so the panel
                # can say why a write was refused instead of showing a bare code.
                "running": running_info,
            },
            "installed": list(self.journal.installed().values()),
            "pending_recovery": pending,
            "recovery_needed": bool(pending),
            "capabilities": d.get("capabilities", {}),
            "known_limitations": d.get("known_limitations", []),
            "known_limitation_keys": d.get("known_limitation_keys", []),
            # Round 40: what the game actually loaded, not just what is on disk.
            "loader_log": log_block,
            "log_path": _log_path(self.journal),
        }
        return ok(data)

    def list_inbox(self) -> dict:
        """Importable archives across the inbox and the declared user roots.

        Round 42: the inbox alone was not enough. A free Nexus account cannot
        download through the API, so the intended flow is "open the page, fetch
        it in the browser, import the ZIP" -- and the browser writes to
        $XDG_DOWNLOAD_DIR, which is not the inbox. Game Mode has no file manager,
        so a list that only showed the inbox showed the user nothing they had
        just downloaded. Each item now carries ``root`` so the two sources stay
        distinguishable.
        """
        try:
            self._gate("local_import")
        except ModError as e:
            return err(e.code, detail=e.detail)
        roots = self._import_roots()
        inbox = roots[0]["path"] if roots else (
            os.environ.get("DECKYMOD_INBOX") or os.path.join(self.journal.decky_data, "inbox"))
        if not os.path.isdir(inbox):
            return err("E_INBOX_MISSING", detail=inbox)
        items = import_root.list_files(roots)
        return ok({
            "inbox": inbox,
            "items": items,
            "roots": [{"label": r["label"], "path": r["path"], "exists": r["exists"]} for r in roots],
            "log_path": _log_path(self.journal),
        })

    def inspect(self, zip_path: str) -> dict:
        """Dry-run inspection (no writes)."""
        try:
            self._gate("local_import")
        except ModError as e:
            return err(e.code, detail=e.detail)
        try:
            self._validate_import_path(zip_path)
        except ModError as e:
            return err(e.code, detail=e.detail)
        try:
            info = file_drop.inspect_mod(zip_path, self._limits(),
                                        reject_extensions=self._reject_extensions(),
                                        mod_package=self._mod_package())
        except ModError as e:
            return err(e.code, detail=e.detail)
        except OSError as e:
            return err(map_oserror(e).code, detail=e.strerror)
        r = self._resolve()
        uid, dn = info["uniqueId"], info["dir_name"]
        managed = self._existing_managed(uid)
        # Round 59, found by auditing every root lookup after rounds 57-58:
        # _install_inner now lands a parked mod's new bytes in .decky-disabled/
        # and counts parked copies in its duplicate check, but this preview did
        # neither. It named `Mods/<dn>` as the destination for a mod the install
        # would place under `.decky-disabled/<dn>`, so the confirm dialog -- the
        # one thing the user actually reads and agrees to -- described a
        # different operation than the one that ran.
        #
        # A preview that disagrees with its execute is worse than no preview: the
        # user's consent was given for the text on screen. Round 60 moved the
        # destination decision into _locate(), so this preview and the install
        # that follows it cannot drift apart again.
        where = self._locate(r, dn, managed)
        parked_managed = where["parked"]
        install_at = where["install_at"]
        collision = os.path.exists(install_at)
        # Round 27: a same-UniqueID mod may already sit under a DIFFERENT folder
        # name (that is exactly what a hand-installed mod looks like). Report it
        # so the UI can warn, and refuse it in install unless the caller confirms.
        # Round 59: the parked root holds copies too, and install refuses them.
        same_uid_dirs = self._disk_dirs_with_uid(r.mod_root, uid)
        same_uid_dirs += ["%s (disabled)" % d
                          for d in self._disk_dirs_with_uid(r.disabled_root, uid, exclude=dn)]
        # Keep "members" in the wire dict: the frontend/test surface uses it to
        # show the archive contents. It is JSON-safe (file_drop made it so).
        return ok({
            "mod": info,
            # Round 28 (criterion 3): the parsed FOMOD descriptor rides along so
            # the UI can render single/multi-select steps before the user commits.
            "fomod": info.get("fomod") or {"present": False},
            "conflict": {"duplicate": bool(managed), "file_collision": bool(collision and not managed),
                         "managed": managed,
                         "same_unique_id_dirs": same_uid_dirs,
                         "parked": bool(parked_managed)},
            "targets": {"w1_state_file": None, "w2_install_dir": install_at},
            "confirm_text": f"Install {info['name']} to {install_at} "
                            f"(file_drop: install == enable"
                            + ("; this mod is disabled, the new version stays disabled)"
                               if parked_managed else ")"),
            "log_path": _log_path(self.journal),
        })

    # ------------------------------------------------------------------ install (== enable)
    def install(self, zip_path: str, *, after_confirm: bool = False,
                fomod_choices: dict | None = None) -> dict:
        try:
            return self._install_inner(zip_path, after_confirm, fomod_choices)
        except ModError as e:
            return err(e.code, detail=e.detail, rollback_available=e.rollback_available)
        except OSError as e:
            return err(map_oserror(e).code, detail=e.strerror, rollback_available=True)
        except Exception as e:
            self.journal.log(f"install unexpected: {type(e).__name__}: {e}")
            return err("E_UNKNOWN", detail=f"{type(e).__name__}: {e}")

    def _install_inner(self, zip_path: str, after_confirm: bool,
                       fomod_choices: dict | None = None) -> dict:
        self._gate("local_import")
        self._check_not_running()
        r = self._resolve()
        self._check_write_allowed(r)
        self._check_no_pending()
        self._validate_import_path(zip_path)
        info = file_drop.inspect_mod(zip_path, self._limits(),
                                    reject_extensions=self._reject_extensions(),
                                    mod_package=self._mod_package())
        uid, dn = info["uniqueId"], info["dir_name"]
        # Round 60: both paths come from _locate(), one expression. `target` is
        # the Mods/ path specifically (the "a non-managed folder already sits
        # there" check below must stay about Mods/); `install_at` is where the
        # bytes actually go.
        managed = self._existing_managed(uid)
        where = self._locate(r, dn, managed)
        target = where["target"]
        # Round 28 (criterion 3): if the archive has a FOMOD descriptor and the
        # user supplied choices, compute the reduced/renamed member map. A bad
        # or empty selection is NOT fatal — we warn and fall back to a plain
        # extract so the mod is never silently half-installed.
        fomod_override = None
        fomod_warnings: list = []
        fomod_desc = info.get("fomod") or {}
        if fomod_desc.get("present") and fomod_desc.get("usable") and isinstance(fomod_choices, dict) and fomod_choices:
            try:
                parsed = {"steps": fomod_desc.get("steps") or [],
                          "warnings": fomod_desc.get("warnings") or []}
                chosen = fomod.choose(parsed, fomod_choices)
                applied = fomod.apply_to_members(info, chosen.get("files") or [])
                manifest_key = info.get("manifest_stripped")
                # The post-commit verify requires the manifest at the top level.
                # If the FOMOD selection dropped it, keep it explicitly.
                if manifest_key and manifest_key not in applied["members"]:
                    applied["members"][manifest_key] = dict(info["members"][manifest_key])
                    applied["warnings"].append("kept manifest so the mod can be verified")
                fomod_override = applied["members"]
                fomod_warnings = list(chosen.get("warnings") or []) + list(applied.get("warnings") or [])
                self.journal.log("fomod: selected %d files" % len(fomod_override))
            except Exception as fe:
                fomod_warnings = ["FOMOD selection could not be applied (%s); "
                                  "fell back to a plain extract" % fe]
                self.journal.log("fomod fallback: %s" % fe)
        # Round 57: a disabled mod lives in .decky-disabled/, not Mods/. Checking
        # only `target` made an upgrade of a parked mod unpack a SECOND copy into
        # Mods/ (which silently re-enables it) while the old one stayed parked.
        # The directory's location IS the state in this engine, so the new bytes
        # must go where the old bytes are.
        # Round 60: `where` was computed above; only the parked view is new here.
        parked_target = where["parked_at"]
        parked_managed = where["parked"]
        install_at = where["install_at"]
        if managed and not after_confirm:
            raise ModError("E_DUPLICATE", detail=f"{uid} already managed", context={"packageId": uid})
        # Round 27: a second copy of a mod that already sits on disk under a
        # DIFFERENT folder name is never correct for SMAPI — it would load both.
        # The old code only compared folder names, so installing a mod the user
        # had hand-installed created the duplicate instead of reporting it.
        # This is a hard refusal (not confirmable): two copies declaring the same
        # UniqueID is a broken install either way.
        if not managed:
            same_uid = self._disk_dirs_with_uid(r.mod_root, uid, exclude=dn)
            if os.path.isdir(r.disabled_root):
                same_uid += ["%s (disabled)" % d for d in
                             self._disk_dirs_with_uid(r.disabled_root, uid, exclude=dn)]
            if same_uid:
                raise ModError(
                    "E_DUPLICATE",
                    detail=(f"{uid} is already on disk as {', '.join(same_uid)}; "
                            f"disable or uninstall that copy before installing {dn}"),
                    context={"packageId": uid, "existing_dirs": same_uid})
        if os.path.exists(target) and not managed:
            raise ModError("E_FILE_COLLISION", detail=f"{target} exists and is not managed")
        if os.path.exists(parked_target) and not parked_managed:
            raise ModError("E_FILE_COLLISION",
                           detail=f"{parked_target} exists and is not managed")
        w2 = preflight_root(r.game_root, need_writable=True)
        if os.path.isdir(r.mod_root) and not same_filesystem(r.mod_root, r.staging):
            raise ModError("E_CROSS_DEVICE", detail="Mods/ and .decky-staging are on different filesystems")
        plan = {"op": "install", "packageId": uid, "uniqueId": uid, "name": info["name"],
                "version": info["version"], "from": zip_path, "to": install_at,
                "w2": r.mod_root, "free_w2": w2.get("free_bytes"), "fs_posix": r.fs_posix,
                "strategy": "file_drop",
                "parked": bool(parked_managed),
                "note": ("install==enable (directory presence)" if not parked_managed
                         else "this mod is disabled; the new version stays disabled")}
        if fomod_warnings:
            plan["fomod_warnings"] = fomod_warnings
            plan["fomod_selected"] = bool(fomod_override)
        if not after_confirm:
            return ok({"phase": "confirm", "plan": plan,
                       "confirm_text": (f"Install {info['name']} ({uid}) to {install_at}?\n"
                                        + ("(this mod is disabled; it stays disabled)"
                                           if parked_managed else
                                           "(file_drop: unpacking the directory IS the enable step)")),
                       "confirm_key": "CONFIRM_INSTALL_FD",
                       "confirm_vars": {"name": info["name"], "uid": uid, "target": install_at},
                       "targets": {"w1_state_file": None, "w2_install_dir": install_at},
                       "log_path": _log_path(self.journal)})
        txn = new_txn_id()
        self.journal.begin(txn, "install", plan)
        self.journal.applying(txn)
        staged = os.path.join(r.staging, txn)
        # Round 69: initialised BEFORE the try. If extract_to() fails, the name
        # would otherwise never be bound, and the handler cannot tell "we moved a
        # previous copy aside and must put it back" from "there was nothing to
        # lose" -- which is the difference between an honest failure and a silent
        # upgrade.
        replaced_qdir = None
        # Round 69b: `placed` records that OUR bytes reached
        # install_at. Cleanup must not ask the journal whether we
        # own the mod -- the journal can name a folder the disk no
        # longer has, and then a first install looks like an
        # upgrade and its failure leaves the half-written folder
        # behind (measured on the device, r69f).
        placed = False
        try:
            ensure_dir(r.staging)
            stage_dest = os.path.join(staged, dn)
            archive.extract_to(info, zip_path, stage_dest, member_override=fomod_override)
            if os.path.isdir(install_at):
                replaced_qdir = os.path.join(r.quarantine_root, txn, dn + ".replaced")
                ensure_dir(os.path.dirname(replaced_qdir))
                os.replace(install_at, replaced_qdir)
            # Round 52: os.replace() into a target whose PARENT does not exist
            # fails with ENOENT, and a game that has never had a mod installed has
            # no Mods/ folder at all. The first install on a fresh game therefore
            # failed with a bare "[Errno 2] No such file or directory" naming the
            # staging path, which reads like a plugin bug rather than "nothing was
            # created yet". Creating the parent here is the same thing the user
            # would do by hand, and it happens after staging succeeded, so a
            # failure above still leaves no half-made folder.
            ensure_dir(os.path.dirname(install_at))
            os.replace(stage_dest, install_at)
            placed = True
            self.journal.record("MOD_INSTALLED", txn, packageId=uid, uniqueId=uid,
                                name=info["name"], version=info["version"], dir=install_at,
                                dir_name=dn, replaced_old=replaced_qdir, ts=time.time(),
                                parked=bool(parked_managed))
            if not parked_managed:
                # file_drop: install==enable -- but only when it actually landed
                # in Mods/. Writing MOD_ENABLED for a parked copy told the rest of
                # the plugin the mod was live when it was not.
                self.journal.record("MOD_ENABLED", txn, packageId=uid)
            # Verify uses the descriptor parser's manifest path, NOT a hard-coded
            # "manifest.json" (Step 3: game-agnostic engine).
            verify_rel = info.get("manifest_stripped") or self._manifest_basename()
            if not os.path.isdir(install_at) or not os.path.isfile(os.path.join(install_at, verify_rel)):
                raise ModError("E_VERIFY_FAILED", detail=f"installed dir missing {verify_rel}")
            self.journal.committed(txn, {"packageId": uid, "dir": install_at})
            result = {"packageId": uid, "uniqueId": uid, "dir": install_at, "dir_name": dn,
                      "enabled": not parked_managed, "parked": bool(parked_managed),
                      "txn": txn, "log_path": _log_path(self.journal)}
            if fomod_warnings:
                result["fomod_warnings"] = fomod_warnings
            return ok(result)
        except Exception as e:
            try:
                # Round 69 (measured on the device): this handler only cleaned up
                # a FIRST install, where the incomplete copy is all there is. For
                # an upgrade it skipped the case that matters.
                # an upgrade it skipped the case that matters -- a previous copy
                # had already been moved into the quarantine and the new one was
                # already in place. The transaction was then recorded as
                # ROLLED_BACK while the disk held the NEW version, status()
                # reported it as installed, and rollback() answered "nothing to
                # roll back": the user was told the upgrade failed and silently
                # got an upgrade. Put the displaced copy back before saying
                # anything, so "failed" means the old version is still there.
                restored = None
                removed_new = False
                if replaced_qdir and os.path.isdir(replaced_qdir):
                    undo = upgrade.undo_install(replaced_qdir, install_at)
                    if not undo.get("ok"):
                        # Restoring is the only honest outcome here. If it cannot
                        # be done, say so and leave both copies where they are --
                        # a half-undone upgrade leaves the user with neither
                        # version (round 56's rule, applied to the failure path).
                        self.journal.rollback_failed(
                            txn, {"reason": str(e),
                                  "restore_error": undo.get("detail") or ""})
                        return err("E_ROLLBACK_FAILED",
                                   detail=("install failed (%s) and the previous copy could "
                                           "not be restored: %s"
                                           % (str(e), undo.get("detail") or "")))
                    restored = replaced_qdir
                    removed_new = bool(undo.get("removed_new"))
                elif placed and os.path.isdir(install_at):
                    # Nothing was displaced, so whatever is here is
                    # the copy this transaction wrote.
                    shutil.rmtree(install_at, ignore_errors=True)
                    removed_new = True
                self.journal.record("MOD_ROLLBACK_RESTORED", txn,
                                    packageId=uid,
                                    # The version now on disk is the one the
                                    # journal held before this install -- the
                                    # entry being displaced. Without it the
                                    # restored row cannot answer "which version
                                    # is installed?", and status() would show a
                                    # managed mod with no version at all.
                                    mod={"name": info["name"], "dir": install_at,
                                         "version": (managed or {}).get("version")},
                                    restored_from=restored, removed_new=removed_new,
                                    enabled=not parked_managed,
                                    reason="install_failed")
                self.journal.rolled_back(txn, {"reason": str(e),
                                               "restored_from": restored})
                code = e.code if isinstance(e, ModError) else (
                    map_oserror(e).code if isinstance(e, OSError) else "E_OP_FAILED")
                return err(code, detail=str(e), rollback_available=False,
                           data={"restored_old": bool(restored),
                                 "removed_new": removed_new})
            except Exception as rb:
                self.journal.rollback_failed(txn, {"reason": str(rb)})
                return err("E_ROLLBACK_FAILED", detail=str(rb))
        finally:
            shutil.rmtree(staged, ignore_errors=True)

    # ------------------------------------------------------------------ enable/disable
    def set_enabled(self, package_id: str, enabled: bool, *, after_confirm: bool = False) -> dict:
        """Round 25: a real enable/disable step for file_drop games.

        For SMAPI the presence of a directory under ``Mods/`` IS the enabled
        state, so disabling means moving the directory OUT of ``Mods/`` and
        enabling means moving it back. The parking area ``.decky-disabled`` is a
        sibling of ``Mods/`` so ``os.replace`` never leaves the filesystem.

        This is deliberately NOT ``uninstall``: uninstall moves the folder to
        quarantine (a restore point that the user thinks of as "removed"), while
        disable keeps the plugin's ownership and is the reversible everyday
        action. Nothing is ever deleted -- the folder only changes parent.
        """
        try:
            return self._set_enabled_inner(package_id, enabled, after_confirm)
        except ModError as e:
            return err(e.code, detail=e.detail)
        except OSError as e:
            return err(map_oserror(e).code, detail=e.strerror)
        except Exception as e:
            self.journal.log(f"set_enabled unexpected: {type(e).__name__}: {e}")
            return err("E_UNKNOWN", detail=f"{type(e).__name__}: {e}")

    def _set_enabled_inner(self, package_id: str, enabled: bool, after_confirm: bool) -> dict:
        self._gate("enable_disable")
        self._check_not_running()
        r = self._resolve()
        self._check_write_allowed(r)
        self._check_no_pending()
        managed = self._existing_managed(package_id)
        # The identifier may be either a journal packageId or the DIRECTORY NAME
        # that status.state.mods shows. Resolve both directions: a mod to disable
        # lives in Mods/, a mod to enable lives in .decky-disabled/.
        if managed:
            journal_id = managed.get("packageId") or package_id
            known_dir = os.path.basename(str(managed.get("dir") or "")) or None
        else:
            journal_id, known_dir = str(package_id), None
        src_root, dst_root = (r.mod_root, r.disabled_root) if not enabled else (r.disabled_root, r.mod_root)
        name = self._pick_dir_name(package_id, known_dir, [src_root])
        if name is None:
            # Round 52: not-found is its own answer. E_DUPLICATE says the mod IS
            # installed, which is the opposite of what happened here.
            if enabled:
                raise ModError("E_MOD_NOT_FOUND",
                               detail=f"{package_id} is not disabled (nothing parked in {r.disabled_root})")
            raise ModError("E_MOD_NOT_FOUND", detail=f"{package_id} is not an enabled mod directory")
        src = os.path.join(src_root, name)
        dst = os.path.join(dst_root, name)
        if not os.path.isdir(src) or os.path.islink(src):
            raise ModError("E_PATH_INVALID", detail=f"{src} is not a real directory")
        if os.path.exists(dst):
            raise ModError("E_FILE_COLLISION", detail=f"{dst} already exists")
        if not same_filesystem(src_root, dst_root):
            raise ModError("E_CROSS_DEVICE", detail="Mods/ and .decky-disabled/ are on different filesystems")
        verb = "Enable" if enabled else "Disable"
        plan = {"op": "enable" if enabled else "disable", "packageId": journal_id, "dir": name,
                "from": src, "to": dst, "strategy": "file_drop_move"}
        if not after_confirm:
            # Round 71: disabling a library has the same consequence as removing
            # it from the game's point of view, so the confirmation says so.
            dependents = self._active_dependents(r, journal_id) if not enabled else []
            who = ", ".join(d.get("name") or d.get("id") or "" for d in dependents)
            key = "CONFIRM_ENABLE"
            if not enabled:
                key = "CONFIRM_DISABLE_WITH_DEPENDENTS" if dependents else "CONFIRM_DISABLE"
            return ok({"phase": "confirm", "plan": plan,
                       "confirm_text": (f"{verb} {name}? The folder is moved to {dst_root} (not deleted)."
                                        + (f" {len(dependents)} installed mod(s) need it and will stop loading: {who}."
                                           if dependents else "")),
                       "confirm_key": key,
                       "confirm_vars": {"pid": name, "n": len(dependents), "who": who},
                       "dependents": dependents,
                       "targets": {"w1_state_file": None, "w2_disabled": dst_root},
                       "log_path": _log_path(self.journal)})
        txn = new_txn_id()
        self.journal.begin(txn, "enable" if enabled else "disable", plan)
        self.journal.applying(txn)
        try:
            ensure_dir(dst_root)
            os.replace(src, dst)
            self.journal.record("MOD_ENABLED" if enabled else "MOD_DISABLED", txn,
                                packageId=journal_id, dir=dst, name=name,
                                from_path=src, to_path=dst)
            self.journal.committed(txn, {"packageId": journal_id, "dir": dst})
            return ok({"packageId": journal_id, "dir": dst, "enabled": bool(enabled), "txn": txn,
                       "rollback_hint": "set_enabled with the opposite flag moves it back",
                       "log_path": _log_path(self.journal)})
        except Exception as e:
            try:
                if os.path.isdir(dst) and not os.path.isdir(src):
                    os.replace(dst, src)
                self.journal.rolled_back(txn, {"reason": str(e)})
                code = e.code if isinstance(e, ModError) else (
                    map_oserror(e).code if isinstance(e, OSError) else "E_OP_FAILED")
                return err(code, detail=str(e))
            except Exception as rb:
                self.journal.rollback_failed(txn, {"reason": str(rb)})
                return err("E_ROLLBACK_FAILED", detail=str(rb))

    def _active_dependents(self, r, target_id: str) -> list:
        """Which ENABLED mods require ``target_id`` (Round 71).

        Read-only, and deliberately limited to ``Mods/``: a parked dependent is
        already not loading, so removing its dependency changes nothing today.
        Reporting it would be noise in a confirmation, and the honest place for
        "this is disabled" is the row itself.
        """
        if not target_id or not os.path.isdir(r.mod_root):
            return []
        try:
            scanned = manifest.scan_installed_mods(r.mod_root, self._mod_package())
        except Exception:                                   # noqa: BLE001 - a warning must not block
            return []
        return manifest.dependents_of(target_id, scanned.get("mods") or [])

    def _pick_dir_name(self, package_id: str, known_dir, roots) -> str | None:
        """Find the on-disk directory for an identifier, case-tolerantly.

        Accepts a literal directory name (what status.state.mods shows) or a
        journal packageId whose recorded ``dir`` basename still exists. Only
        single-component names that resolve directly inside one of ``roots`` are
        returned, so a crafted packageId can never escape the mod tree.
        """
        candidates = []
        if isinstance(package_id, str) and package_id and os.path.basename(package_id) == package_id \
                and not package_id.startswith(".") and package_id not in (".", ".."):
            candidates.append(package_id)
        if known_dir and known_dir not in candidates:
            candidates.append(known_dir)
        low_map = {}
        for root in roots:
            try:
                for entry in os.listdir(root):
                    low_map.setdefault((root, entry.lower()), entry)
            except OSError:
                continue
        for cand in candidates:
            for root in roots:
                real_root = os.path.realpath(root)
                real = os.path.realpath(os.path.join(root, cand))
                if os.path.dirname(real) == real_root and os.path.isdir(real) and not os.path.islink(real):
                    return os.path.basename(real)
                actual = low_map.get((root, cand.lower()))
                if actual:
                    real2 = os.path.realpath(os.path.join(root, actual))
                    if os.path.dirname(real2) == real_root and os.path.isdir(real2) \
                            and not os.path.islink(real2):
                        return actual
        return None

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
        r = self._resolve()
        self._check_write_allowed(r)
        self._check_no_pending()
        managed = self._existing_managed(package_id)
        unmanaged = False
        if not managed:
            # Round 20: allow uninstalling a pre-existing mod directory that this
            # plugin never installed (e.g. a Mods/ folder the user brought with
            # them). The identifier is the directory NAME as listed by
            # status.state.mods. Every safety guard above already ran; the extra
            # _resolve_disk_dir() refuses symlinks and anything outside Mods/.
            disk_dir = self._resolve_disk_dir(str(package_id), r.mod_root)
            if disk_dir is None:
                raise ModError("E_MOD_NOT_FOUND", detail=f"{package_id} is not installed/managed")
            managed = {"packageId": package_id, "dir": disk_dir, "unmanaged": True}
            unmanaged = True
            # Round 20 fix (found on the device): the UI lists DIRECTORY names,
            # while the journal is keyed by UniqueID. If this directory actually
            # belongs to a mod we installed earlier, keep the journal key as the
            # recorded packageId, otherwise MOD_UNINSTALLED would be written under
            # the directory name and installed() would keep a stale record forever.
            real_disk = os.path.realpath(disk_dir)
            for pid, rec in self.journal.installed().items():
                rec_dir = rec.get("dir")
                if rec_dir and os.path.realpath(rec_dir) == real_disk:
                    managed = {**rec, "dir": disk_dir}
                    unmanaged = False
                    break
        src = managed.get("dir") or os.path.join(r.mod_root, str(package_id).lower())
        # Round 58, found on the device: a mod the user DISABLED lives in
        # .decky-disabled/, but every lookup above looked in Mods/ only. The
        # execute branch below guards the move with ``if os.path.isdir(src)``,
        # so a parked folder was neither moved nor reported -- the call returned
        # ok:True, wrote MOD_UNINSTALLED, and the folder stayed exactly where it
        # was. The panel then kept listing it, and journal.installed() forgot it,
        # so the plugin claimed to have removed something it had not touched.
        #
        # Two corrections: resolve the parked path when the recorded dir is not
        # on disk, and refuse rather than report success when neither exists.
        # Round 60: _locate() answers "where does this live", including the case
        # where the recorded dir is stale because the mod was parked after the
        # journal last wrote it.
        _where = self._locate(r, os.path.basename(src), managed)
        parked_src = _where["parked_at"]
        if not os.path.isdir(src) and os.path.isdir(parked_src) and not os.path.islink(parked_src):
            src = parked_src
            if managed.get("dir"):
                managed = {**managed, "dir": parked_src}
        if not os.path.isdir(src):
            raise ModError("E_MOD_NOT_FOUND",
                           detail=f"{package_id} is not on disk ({src} does not exist)")
        # The journal is keyed by UniqueID; the caller may have passed a directory
        # name. Record events under the id the journal actually knows, so
        # installed() stays consistent either way.
        journal_id = managed.get("packageId") or package_id
        txn = new_txn_id()
        qdir = os.path.join(r.quarantine_root, txn, os.path.basename(src))
        plan = {"op": "uninstall", "packageId": journal_id, "from": src,
                "quarantine": qdir, "strategy": "file_drop",
                # Honest: rollback of an unmanaged mod returns the folder, but the
                # journal never owned it, so there is no "re-enable" semantics.
                "previously_managed": not unmanaged}
        if not after_confirm:
            if os.path.isdir(src) and not same_filesystem(src, r.quarantine_root):
                raise ModError("E_CROSS_DEVICE", detail="mod dir and quarantine are on different filesystems")
            # Round 71: SMAPI skips a mod whose required dependency is gone, so
            # removing a library stops its dependents from loading. The old copy
            # said only "the folder is moved to quarantine", which is true and
            # incomplete: the panel went on to list the mods that had stopped.
            dependents = self._active_dependents(r, journal_id)
            who = ", ".join(d.get("name") or d.get("id") or "" for d in dependents)
            return ok({"phase": "confirm", "plan": plan,
                       "confirm_text": (f"Uninstall {package_id}? The folder is moved to quarantine (not deleted)."
                                        + (f" {len(dependents)} installed mod(s) need it and will stop loading: {who}."
                                           if dependents else "")),
                       "confirm_key": ("CONFIRM_UNINSTALL_WITH_DEPENDENTS" if dependents
                                       else "CONFIRM_UNINSTALL"),
                       "confirm_vars": {"pid": package_id, "n": len(dependents), "who": who},
                       "dependents": dependents,
                       "targets": {"w1_state_file": None, "w2_quarantine": qdir},
                       "log_path": _log_path(self.journal)})
        self.journal.begin(txn, "uninstall", plan)
        self.journal.applying(txn)
        try:
            ensure_dir(os.path.dirname(qdir))
            # Round 58: this used to be ``if os.path.isdir(src): os.replace(...)``,
            # which silently skipped the move for a source that was not there and
            # still recorded a successful uninstall. The existence check above
            # makes that unreachable, and this raise keeps it unreachable.
            if not os.path.isdir(src):
                raise ModError("E_OP_FAILED", detail=f"{src} disappeared before it could be moved")
            os.replace(src, qdir)
            self.journal.record("MOD_UNINSTALLED", txn, packageId=journal_id, from_path=src,
                                quarantine=qdir, txn_quarantine=txn, enabled=False,
                                # Round 21: remember whether the plugin ever owned
                                # this mod, so a later rollback can restore the
                                # folder without claiming ownership of it.
                                unmanaged=unmanaged)
            self.journal.committed(txn, {"packageId": journal_id, "quarantine": qdir})
            return ok({"packageId": journal_id, "quarantine": qdir, "txn": txn,
                       "rollback_hint": "Use rollback to restore this mod",
                       "log_path": _log_path(self.journal)})
        except Exception as e:
            try:
                if os.path.isdir(qdir) and not os.path.isdir(src):
                    os.replace(qdir, src)
                self.journal.rolled_back(txn, {"reason": str(e)})
                code = e.code if isinstance(e, ModError) else (
                    map_oserror(e).code if isinstance(e, OSError) else "E_OP_FAILED")
                return err(code, detail=str(e))
            except Exception as rb:
                self.journal.rollback_failed(txn, {"reason": str(rb)})
                return err("E_ROLLBACK_FAILED", detail=str(rb))

    # ------------------------------------------------------------------ rollback
    def rollback(self, txn: str) -> dict:
        try:
            return self._rollback_inner(txn)
        except ModError as e:
            return err(e.code, detail=e.detail)
        except OSError as e:
            return err(map_oserror(e).code, detail=e.strerror)
        except Exception as e:
            self.journal.log(f"rollback unexpected: {type(e).__name__}: {e}")
            return err("E_UNKNOWN", detail=f"{type(e).__name__}: {e}")

    def _read_dir_identity(self, dirpath: str):
        """What is actually in this folder right now (Round 70).

        A restore moves a folder back by PATH. The journal remembers that path
        belonged to some mod, but the bytes underneath may have been replaced by
        hand while the folder was in the quarantine. Recording the remembered
        identity then makes ``status().installed`` describe a mod that is not
        there (measured on the device: the row said ``probe.alpha`` /
        ``version: null`` while the disk held ``probe.beta 9.0.0``), and the
        next install displaces somebody else's folder as "the old copy".

        So every restore asks the restored folder who it is now. Returns None
        when there is no readable manifest -- "cannot tell" is never turned into
        a guess.
        """
        try:
            if not dirpath or not os.path.isdir(dirpath) or os.path.islink(dirpath):
                return None
            parser = manifest.parser_for(self._mod_package())
            globs = list(self._mod_package().get("manifest_globs") or [])
            mfile = manifest._find_manifest_in_dir(dirpath, globs)
            if not mfile:
                return None
            with open(mfile, "rb") as f:
                raw = f.read()
            pm = parser.parse(raw, mfile)
        except Exception:
            return None
        return {"packageId": pm.uid, "name": pm.name, "version": pm.version}

    def _restore_displaced(self, txn: str, saved: str, target: str,
                           pid, name=None, version=None, *,
                           error_detail="could not restore the previous copy"):
        """Put one displaced copy back and record what actually came back.

        Round 72: three rollback branches used to repeat this block. The
        counts that pinned them broke when a third was added -- the real
        problem is that a second copy of the decision is a second chance to
        disagree (round 60). This is the one place that undoes the displacement,
        reads the version from the folder on disk (round 70, a path is not an
        identity), and writes MOD_ROLLBACK_RESTORED.

        Callers decide how to FINISH the transaction -- a committed upgrade,
        a rolled-back interrupted install, a retried stuck rollback -- and what
        to say when there is no copy at all. ``cannot tell`` never becomes a
        guess here.
        """
        got = upgrade.undo_install(saved, target)
        if not got.get("ok"):
            raise ModError(got.get("code") or "E_OP_FAILED",
                           detail=got.get("detail") or error_detail)
        actual = self._read_dir_identity(target)
        self.journal.record(
            "MOD_ROLLBACK_RESTORED", txn,
            packageId=pid,
            mod={"name": (actual or {}).get("name") or name or pid,
                 "dir": target,
                 "version": (actual or {}).get("version") or version},
            restored_from=saved,
            removed_new=bool(got.get("removed_new")))
        return got, actual

    def _replaced_copy_for(self, txn: str):
        """The copy an interrupted install moved aside, if it is still there.

        Returns the absolute path of the single ``<name>.replaced`` entry inside
        this transaction's quarantine folder, or None. Only that exact suffix is
        accepted, and only one: guessing between two candidates would be picking
        which version of the user's mod to put back.
        """
        try:
            root = os.path.join(self._resolve().quarantine_root, txn)
            names = sorted(os.listdir(root))
        except (OSError, ModError):
            return None
        cands = [os.path.join(root, n) for n in names if n.endswith(".replaced")]
        cands = [c for c in cands if os.path.isdir(c) and not os.path.islink(c)]
        return cands[0] if len(cands) == 1 else None

    def _rollback_inner(self, txn: str) -> dict:
        self._gate("rollback")
        self._check_not_running()
        r = self._resolve()
        events = self.journal.events(txn)
        # Round 55: undoing a handover puts the entries BACK into a folder that
        # is somebody else's again, so the external-manager refusal would block
        # the one operation that must always be possible. Swallow exactly that
        # one code, exactly for handover transactions; every other refusal
        # (force_read_only, a missing loader, unset launch options) still fires.
        #
        # The gate runs BEFORE the "unknown txn" error so a foreign tree keeps
        # answering every write with E_EXTERNAL_MANAGER -- the panel explains one
        # reason, not three, and a typo in a transaction id must not look like a
        # different class of problem on one device than another.
        undoing_handover = any(e.get("event") == "MODS_HANDOVER" for e in events)
        try:
            self._check_write_allowed(r)
        except ModError as gate:
            if not (undoing_handover and gate.code == "E_EXTERNAL_MANAGER"):
                raise
        if not events:
            raise ModError("E_UNKNOWN", detail=f"unknown txn {txn}")
        state = self.journal.state(txn)
        # Round 20b (found on the device): a second rollback of the same txn used
        # to return ok again -- the restore step was a no-op because the source
        # directory already existed, but the caller was told the mod had been
        # restored once more. Refuse honestly instead of reporting a fake success.
        if any(e.get("event") == "MOD_ROLLBACK_RESTORED" for e in events):
            raise ModError("E_UNKNOWN", detail=f"txn {txn} was already rolled back")
        uninst = next((e for e in events if e.get("event") == "MOD_UNINSTALLED"), None)
        if uninst and state in ("COMMITTED", "APPLYING", "PREPARED"):
            pid, qdir, src = uninst["packageId"], uninst["quarantine"], uninst["from_path"]
            # Round 65: this used to be `if os.path.isdir(qdir) and not
            # os.path.isdir(src): os.replace(...)` and then record the restore
            # unconditionally. Both halves of that guard could be false for
            # reasons the caller never heard about -- the user reinstalled the
            # mod, or the quarantined copy was cleaned up -- and the answer was
            # still "restored". The journal then believed the mod was back, so
            # the quarantined bytes became an orphan that reclaim_quarantine is
            # allowed to delete (round 54). Refuse instead: an undo that did not
            # undo must not look like one.
            if not os.path.isdir(qdir):
                raise ModError("E_MOD_NOT_FOUND",
                               detail=("the copy of %s saved for this transaction is gone "
                                       "(%s); nothing can be restored" % (pid, qdir)))
            if os.path.islink(src):
                raise ModError("E_PATH_INVALID",
                               detail=("refusing to restore %s over a symbolic link at %s"
                                       % (pid, src)))
            if os.path.exists(src):
                raise ModError("E_FILE_COLLISION",
                               detail=("%s already exists again; move it away before "
                                       "undoing this uninstall" % src))
            os.replace(qdir, src)
            # Round 65: the transaction folder we just emptied is litter, and round
            # 54 taught us that litter in the quarantine gets counted, shown and
            # eventually offered for deletion. `os.rmdir` refuses a non-empty
            # directory, which is exactly the guard we want here.
            try:
                os.rmdir(os.path.dirname(qdir))
            except OSError:
                pass
            # Round 70: ask the folder who it is NOW. Moving a directory back
            # restores a PATH; it does not restore the mod that used to live
            # there. When the contents were swapped by hand, recording `pid`
            # made status().installed claim a mod that is not on disk (and the
            # next install displaced the impostor as "the old copy").
            actual = self._read_dir_identity(src)
            found = str((actual or {}).get("packageId") or "")
            same = bool(found) and found.strip().lower() == str(pid).strip().lower()
            mismatch = bool(found) and not same
            self.journal.record(
                "MOD_ROLLBACK_RESTORED", txn,
                # Under the id the folder really holds, so installed() never
                # names a mod that is not there. A folder that holds somebody
                # else is also not ours to own (round 21's rule).
                packageId=pid if not mismatch else found,
                mod={"name": (actual or {}).get("name") or pid, "dir": src,
                     "version": (actual or {}).get("version"),
                     "expected_package_id": pid if mismatch else None,
                     "found_package_id": found or None},
                enabled=True,
                # Round 21: carry ownership with the event. A mod
                # the plugin never installed must not become
                # "managed" just because its uninstall was undone.
                unmanaged=bool(uninst.get("unmanaged")) or mismatch)
            self.journal.committed(txn, {"rollback_of": "uninstall", "packageId": pid})
            result = {"restored": pid, "dir": src, "txn": txn,
                      "log_path": _log_path(self.journal)}
            if found:
                result["restored_uid"] = found
            if mismatch:
                # The folder came back; the mod did not. Say both.
                result["expected_uid"] = pid
                result["note"] = ("the folder was restored, but it now holds %s, "
                                  "not %s" % (found, pid))
            return ok(result)
        # Round 55: a handover transaction moved entries to the quarantine; the
        # confirm dialog promised Rollback would put them back, so it must.
        # Round 81: root_merge hands over several folders and records one event
        # per folder, so every event is replayed rather than only the first.
        hands = [e for e in events if e.get("event") == "MODS_HANDOVER"]
        if hands and state in ("COMMITTED", "APPLYING", "PREPARED"):
            moved_all = []
            failed_all = {}
            multi = len(hands) > 1
            for hand in hands:
                got = handover.restore(hand.get("quarantine") or "",
                                       hand.get("from_path") or "",
                                       hand.get("moved") or [])
                moved_all.extend(got["moved"])
                for name, why in (got["failed"] or {}).items():
                    # One folder keeps the historical bare name; several folders
                    # need the path, because the same name can fail in two of
                    # them and one answer would hide the other.
                    key = "%s: %s" % (hand.get("from_path") or "", name) if multi else name
                    failed_all[key] = why
            self.journal.record("MOD_ROLLBACK_RESTORED", txn,
                                mod={"name": "handover",
                                     "dir": hands[0].get("from_path")},
                                moved=moved_all, failed=sorted(failed_all))
            self.journal.committed(txn, {"rollback_of": "handover"})
            return ok({"restored": "handover", "moved": moved_all,
                       "failed": failed_all, "txn": txn,
                       "log_path": _log_path(self.journal)})
        # Round 56: an upgrade moved the displaced version into the quarantine and
        # recorded where in `replaced_old`; nothing read it, so rollback answered
        # "nothing to roll back", the new version stayed on disk, and the old one
        # became an orphan that reclaim_quarantine is allowed to delete.
        inst = next((e for e in events
                     if e.get("event") == "MOD_INSTALLED" and e.get("replaced_old")), None)
        # Round 69: ROLLED_BACK belongs here. An upgrade that failed AFTER the two
        # renames had already run recorded MOD_INSTALLED (with replaced_old) and
        # then failed on the commit, so the transaction is ROLLED_BACK while the
        # replacement is still in place. Excluding that state is what made
        # rollback answer "nothing to roll back for txn ... (state=ROLLED_BACK)"
        # for a transaction that had everything needed to undo it.
        # Round 72: ROLLBACK_FAILED belongs here too. A restore that threw is a
        # rollback that did not finish -- the displaced copy is still in the
        # quarantine and the replacement is still on disk. Leaving the state out
        # made rollback() answer "nothing to roll back for txn ... (state=
        # ROLLBACK_FAILED)" to a caller who had just been told the data was
        # preserved and could be recovered.
        if inst and state in ("COMMITTED", "APPLYING", "PREPARED",
                              "ROLLED_BACK", "ROLLBACK_FAILED"):
            got, _actual = self._restore_displaced(
                txn, inst.get("replaced_old"), inst.get("dir"),
                inst.get("packageId"), name=inst.get("packageId"))
            self.journal.committed(txn, {"rollback_of": "upgrade",
                                         "packageId": inst.get("packageId")})
            return ok({"restored": inst.get("packageId"), "dir": inst.get("dir"),
                       "restored_from": inst.get("replaced_old"),
                       "removed_new": bool(got.get("removed_new")), "txn": txn,
                       "log_path": _log_path(self.journal)})
        if state in ("PREPARED", "APPLYING"):
            # Round 68: an install that was interrupted between its two renames
            # (old copy moved aside, new copy not yet in place) leaves the mod
            # ABSENT and its only copy inside the transaction's quarantine
            # folder. This branch used to answer "recovered: True" without
            # looking: the mod stayed missing, the journal said the transaction
            # was undone, and the quarantine copy stopped being referenced by
            # anything -- which is what reclaim_quarantine deletes.
            #
            # So an interrupted install is treated exactly like an interrupted
            # upgrade: find the displaced copy the plan points at, put it back,
            # and refuse honestly if that cannot be done.
            plan = next((e.get("plan") for e in events
                         if e.get("event") == "PREPARED"), None) or {}
            saved = self._replaced_copy_for(txn)
            if saved:
                got, _actual = self._restore_displaced(
                    txn, saved, plan.get("to") or "", plan.get("packageId"),
                    name=plan.get("name"), version=plan.get("version"),
                    error_detail="could not restore the interrupted install")
                self.journal.rolled_back(txn, {"recovered": True,
                                               "restored_from": saved})
                return ok({"recovered": True, "txn": txn,
                           "restored_from": saved,
                           "dir": plan.get("to"),
                           "removed_new": bool(got.get("removed_new")),
                           "log_path": _log_path(self.journal)})
            try:
                self.journal.rolled_back(txn, {"recovered": True})
                return ok({"recovered": True, "txn": txn, "log_path": _log_path(self.journal)})
            except Exception as rb:
                self.journal.rollback_failed(txn, {"reason": str(rb)})
                return err("E_ROLLBACK_FAILED", detail=str(rb))
        if state == "ROLLBACK_FAILED":
            # Round 72: a rollback that already ran and did not finish is not a
            # transaction with nothing to undo -- it is one whose undo failed.
            # This branch exists for the shape where the install died before
            # recording MOD_INSTALLED, so there is no `inst` event above and the
            # only thing naming the old copy is the quarantine folder itself.
            plan = next((e.get("plan") for e in events
                         if e.get("event") == "PREPARED"), None) or {}
            saved = self._replaced_copy_for(txn)
            if saved:
                got, _actual = self._restore_displaced(
                    txn, saved, plan.get("to") or "", plan.get("packageId"),
                    name=plan.get("name"), version=plan.get("version"),
                    error_detail="could not finish the failed rollback")
                self.journal.committed(txn, {"rollback_of": "retry",
                                             "packageId": plan.get("packageId")})
                return ok({"restored": plan.get("packageId"),
                           "dir": plan.get("to"),
                           "restored_from": saved,
                           "removed_new": bool(got.get("removed_new")),
                           "txn": txn, "log_path": _log_path(self.journal)})
            # Nothing to put back. Do NOT answer "recovered": the automatic
            # restore failed once already, and the plugin cannot tell whether a
            # mod is missing because of it. Say what is true.
            raise ModError(
                "E_ROLLBACK_FAILED",
                detail=("the automatic rollback for txn %s did not finish and "
                        "there is no copy left to restore; the quarantine folder "
                        "is at %s"
                        % (txn, os.path.join(r.quarantine_root, txn))))
        raise ModError("E_UNKNOWN", detail=f"nothing to roll back for txn {txn} (state={state})")

    # ------------------------------------------------------------------ reclaim (round 54)
    def reclaim_quarantine(self, txns, *, after_confirm: bool = False) -> dict:
        """Delete quarantine folders the journal can no longer restore.

        Every write gate runs first, in the same order as the other destructive
        ops, because this removes data from disk. Then ``quarantine.reclaim``
        decides: only ``orphan`` entries, only ones named by the caller, and
        only with ``after_confirm``. See that function for the argument.
        """
        try:
            return self._reclaim_inner(txns, after_confirm)
        except ModError as e:
            return err(e.code, detail=e.detail)
        except OSError as e:
            return err(map_oserror(e).code, detail=e.strerror)
        except Exception as e:
            self.journal.log(f"reclaim unexpected: {type(e).__name__}: {e}")
            return err("E_UNKNOWN", detail=f"{type(e).__name__}: {e}")

    def _reclaim_inner(self, txns, after_confirm: bool) -> dict:
        # Deliberately the same three gates as uninstall: this deletes files the
        # user can no longer get back, so it is not "just cleanup".
        self._check_not_running()
        r = self._resolve()
        self._check_write_allowed(r)
        self._check_no_pending()
        cfg = (self._mod_package().get("quarantine") or {})
        if cfg.get("allow_reclaim") is False:
            raise ModError("E_CAPABILITY_DISABLED",
                           detail="reclaim is disabled in the descriptor")
        if isinstance(txns, str):
            txns = [txns]
        wanted = [str(t) for t in (txns or []) if str(t)]
        if not wanted:
            raise ModError("E_PATH_INVALID", detail="no transaction ids were given")
        # Cap: a single call must not be able to empty a large quarantine. The
        # limit is the descriptor's, because how many folders is "a lot" is a
        # property of the game's install, not of this module.
        limit = int(cfg.get("max_reclaim") or quarantine.MAX_DIRS)
        if len(wanted) > limit:
            raise ModError("E_PATH_INVALID",
                           detail=f"at most {limit} folders per call; %d were given"
                                  % len(wanted))

        survey = quarantine.survey(r.quarantine_root, self.journal, cfg)
        out = quarantine.reclaim(r.quarantine_root, wanted, survey,
                                 after_confirm=after_confirm)
        if out.get("phase") == "confirm":
            # The confirm payload is built HERE rather than in quarantine.py:
            # the module knows the filesystem, this method knows the descriptor
            # and the UI contract. Without these four fields runTwoPhase() would
            # see phase=="confirm" and open a modal with nothing in it.
            n = len(out.get("accepted") or [])
            out.update({
                "phase": "confirm",
                "plan": {"op": "reclaim",
                         "txns": list(out.get("accepted") or []),
                         "bytes": out.get("bytes"),
                         "files": out.get("files"),
                         "refused": dict(out.get("refused") or {})},
                "confirm_text": "Delete %d quarantine folder(s) permanently? "
                                "Rollback cannot bring them back." % n,
                "confirm_key": "CONFIRM_RECLAIM",
                "confirm_vars": {"n": str(n),
                                 "kb": str(int((out.get("bytes") or 0) / 1024))},
                "targets": {"w1_state_file": None,
                            "w2_quarantine": r.quarantine_root},
            })
        if out.get("phase") == "removed" and out.get("removed"):
            self.journal.record("QUARANTINE_RECLAIMED",
                                new_txn_id(),
                                removed=out.get("removed"),
                                failed=sorted((out.get("failed") or {}).keys()),
                                bytes=out.get("bytes"))
        out["log_path"] = _log_path(self.journal)
        return ok(out)

    # ------------------------------------------------------------------ handover (round 55)
    def handover_mods(self, *, after_confirm: bool = False) -> dict:
        """Take ownership of ``Mods/`` away from another mod manager.

        This is the only write path that does NOT call ``_check_write_allowed``,
        and that is deliberate: the external-manager refusal is exactly what
        this operation exists to clear, so gating it on that refusal would make
        it unreachable in every situation it is needed. Everything narrower is
        still enforced -- the game must not be running, no transaction may be
        pending, and ``handover.py`` refuses anything it cannot move back.

        Nothing is deleted: entries move into the quarantine under one journal
        transaction, so ``rollback`` restores them byte for byte.
        """
        try:
            return self._handover_inner(after_confirm)
        except ModError as e:
            return err(e.code, detail=e.detail)
        except OSError as e:
            return err(map_oserror(e).code, detail=e.strerror)
        except Exception as e:
            self.journal.log(f"handover unexpected: {type(e).__name__}: {e}")
            return err("E_UNKNOWN", detail=f"{type(e).__name__}: {e}")

    def _handover_roots(self, r) -> list:
        """The folders this engine may take over, absolute.

        Round 81: file_drop owns exactly one folder (``Mods/``). The hook exists
        so an engine whose mods are not "one folder" can name several, without
        duplicating the journal/confirm/rollback machinery around it.
        """
        return [r.mod_root]

    def _handover_inner(self, after_confirm: bool) -> dict:
        self._gate("local_import")
        self._check_not_running()
        self._check_no_pending()
        r = self._resolve()
        d = self._descriptor()
        cfg = (d.get("loader_detection") or {}).get("handover") or {}
        if cfg.get("enabled") is False:
            raise ModError("E_CAPABILITY_DISABLED",
                           detail="handing the mod folder over is disabled in the descriptor")

        roots = [str(p) for p in (self._handover_roots(r) or []) if str(p or "").strip()]
        if not roots:
            raise ModError("E_CAPABILITY_DISABLED",
                           detail="this game declares no mod folder to take over")

        markers = self._external_markers()
        txn = new_txn_id()
        # Survey every root before deciding anything: a refusal must cover the
        # whole operation, never half of it.
        blocking = []
        notes = []
        found = []
        for root in roots:
            survey = handover.survey(r.game_root, root, markers)
            if not survey.get("ok"):
                return err(survey.get("code") or "E_UNKNOWN",
                           detail=survey.get("detail") or "survey failed")
            blocking.extend(survey.get("blocking") or [])
            if survey.get("explain"):
                notes.append(survey["explain"])
            movable = survey.get("movable") or []
            if movable:
                found.append({"root": root, "movable": movable})

        seen = set()
        uniq_blocking = []
        for code in blocking:
            if code not in seen:
                seen.add(code)
                uniq_blocking.append(code)
        explain = "; ".join(dict.fromkeys(notes))

        if uniq_blocking:
            # Refusing as a whole is the point: doing half of it and then
            # stopping would leave the other manager's deployment partly
            # dismantled with nothing gained.
            return err("E_CAPABILITY_DISABLED",
                       detail="this folder cannot be handed over safely: %s. %s"
                              % (", ".join(uniq_blocking), explain),
                       data={"blocking": uniq_blocking, "explain": explain,
                             "movable": []})
        if not found:
            return err("E_CAPABILITY_DISABLED",
                       detail="nothing to hand over: no symlinked entries and no "
                              "marker files were found",
                       data={"blocking": [], "explain": "", "movable": []})

        # One quarantine subfolder per root, but only when there is more than
        # one: a single-root game keeps the historical ``<quarantine>/<txn>``
        # layout byte for byte.
        multi = len(found) > 1
        plans = []
        for row in found:
            qdir = os.path.join(r.quarantine_root, txn)
            if multi:
                qdir = os.path.join(qdir, _slug(row["root"]))
            plans.append({"root": row["root"], "movable": row["movable"],
                          "quarantine": qdir})

        total = sum(len(p["movable"]) for p in plans)
        flat = [m for p in plans for m in p["movable"]]

        if after_confirm:
            # Round 55: without these two events ``journal.state(txn)`` stays
            # None and rollback refuses the transaction as unknown -- the moved
            # entries would sit in the quarantine with no way back.
            self.journal.begin(txn, "handover",
                               {"quarantine": os.path.join(r.quarantine_root, txn),
                                "count": total})
            self.journal.applying(txn)

        if not after_confirm:
            where = "Mods/" if len(roots) == 1 else "the mod folders"
            return ok({
                "phase": "confirm",
                "plan": {"op": "handover", "txn": txn,
                         "moved": [row.get("name") for row in flat],
                         "quarantine": os.path.join(r.quarantine_root, txn)},
                "count": total,
                "confirm_text": "Move %d deployment entr(y/ies) out of %s into "
                                "the quarantine? This plugin will then own the "
                                "folder; Rollback puts them back."
                                % (total, where),
                "confirm_key": "CONFIRM_HANDOVER",
                "confirm_vars": {"n": str(total),
                                 "what": handover.describe({"movable": flat})},
                "targets": {"w1_state_file": None,
                            "w2_quarantine": r.quarantine_root},
                "log_path": _log_path(self.journal),
            })

        moved_all = []
        failed_all = {}
        for plan in plans:
            # handover.execute() builds its destination as quarantine_root/txn,
            # so split our per-root folder back into those two parts. For the
            # single-root case this is exactly the old pair.
            parent, base = os.path.split(plan["quarantine"])
            out = handover.execute(plan, after_confirm=True,
                                   quarantine_root=parent, txn=base)
            got = out.get("moved") or []
            failed_all.update(out.get("failed") or {})
            if got:
                # One event per root: each carries the from_path that its own
                # names must go back to, and rollback replays all of them.
                self.journal.record("MODS_HANDOVER", txn,
                                    moved=got,
                                    failed=sorted((out.get("failed") or {}).keys()),
                                    quarantine=plan["quarantine"],
                                    from_path=plan["root"])
                moved_all.extend(got)

        if moved_all:
            self.journal.committed(txn, {"handover": True, "moved": len(moved_all)})
        else:
            # Nothing moved: close it rather than leaving a pending transaction
            # that would block every later write behind E_RECOVERY_PENDING.
            self.journal.rolled_back(txn, {"handover": True, "moved": 0})
        return ok({"phase": "moved", "moved": moved_all, "failed": failed_all,
                   "quarantine": os.path.join(r.quarantine_root, txn),
                   "count": total, "txn": txn,
                   "log_path": _log_path(self.journal)})

    # ------------------------------------------------------------------ history / refresh
    def history(self, limit: int = 50) -> dict:
        try:
            return ok({"items": self.journal.history(limit), "log_path": _log_path(self.journal)})
        except Exception as e:
            return err("E_UNKNOWN", detail=str(e))

    def refresh(self) -> dict:
        return self.status()   # no state-fp cache in file_drop

    def recovery(self) -> dict:
        """Pending (write-blocking) and stuck (rollback already failed) txns.

        Round 72: these are two different lists on purpose. ``pending`` blocks
        every write until it is recovered; ``stuck`` does not block anything --
        it is work the user still has to look at, and the panel had no way to
        see it before this key existed.
        """
        try:
            return ok({"pending": self.journal.pending(),
                       "stuck": self.journal.stuck(),
                       "log_path": _log_path(self.journal)})
        except Exception as e:
            return err("E_UNKNOWN", detail=str(e))


# Backward-compatible alias: the historical Stardew tests and any external
# caller import ``StardewEngine``. The class is now descriptor-agnostic, but the
# name stays so no consumer breaks (Step 3 keeps the 46-test suite green).
StardewEngine = FileDropEngine
