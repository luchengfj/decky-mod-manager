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

from . import archive, conflicts, file_drop, fomod, import_root, loaderlog, manifest, modwatch, paths
from .envelope import err, ok
from .errors import ModError
from .fsops import ensure_dir, map_oserror, preflight_root, same_filesystem
from .journal import Journal, new_txn_id
from .registry import Registry


def _log_path(jrn: Journal) -> str:
    return jrn.log_path


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
        return paths.resolve(appid, preflight=True, no_state_file=True)

    def _check_not_running(self):
        marker = os.environ.get("DECKYMOD_GAME_RUNNING")
        if marker and marker.lower() in ("1", "true", "yes"):
            raise ModError("E_GAME_RUNNING", detail="DECKYMOD_GAME_RUNNING is set")

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
        if file_drop.detect_external_manager(r.game_root, r.mod_root):
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
        external = file_drop.detect_external_manager(r.game_root, r.mod_root)
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
        scanned = manifest.scan_installed_mods(r.mod_root, self._mod_package())
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
        # with no way back.
        disabled_scan = manifest.scan_installed_mods(r.disabled_root, self._mod_package())
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
        ident = d.get("identity", {}) or {}
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
                "external_manager": probe["external_manager"],
                "loader_detected": probe["loader_detected"],
                "launch_options": probe["launch_options"],
                "read_only": probe["read_only"],
                "layout": probe.get("layout") or {},
                # Round 47: paths shipped by more than one mod. Reported, never
                # resolved -- ordering needs per-game knowledge this plugin does
                # not have and should not pretend to have.
                "conflicts": conflict_info,
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
        collision = os.path.exists(os.path.join(r.mod_root, dn))
        # Round 27: a same-UniqueID mod may already sit under a DIFFERENT folder
        # name (that is exactly what a hand-installed mod looks like). Report it
        # so the UI can warn, and refuse it in install unless the caller confirms.
        same_uid_dirs = self._disk_dirs_with_uid(r.mod_root, uid)
        # Keep "members" in the wire dict: the frontend/test surface uses it to
        # show the archive contents. It is JSON-safe (file_drop made it so).
        return ok({
            "mod": info,
            # Round 28 (criterion 3): the parsed FOMOD descriptor rides along so
            # the UI can render single/multi-select steps before the user commits.
            "fomod": info.get("fomod") or {"present": False},
            "conflict": {"duplicate": bool(managed), "file_collision": bool(collision and not managed),
                         "managed": managed,
                         "same_unique_id_dirs": same_uid_dirs},
            "targets": {"w1_state_file": None, "w2_install_dir": os.path.join(r.mod_root, dn)},
            "confirm_text": f"Install {info['name']} to {os.path.join(r.mod_root, dn)} "
                            f"(file_drop: install == enable)",
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
        self._validate_import_path(zip_path)
        info = file_drop.inspect_mod(zip_path, self._limits(),
                                    reject_extensions=self._reject_extensions(),
                                    mod_package=self._mod_package())
        uid, dn = info["uniqueId"], info["dir_name"]
        target = os.path.join(r.mod_root, dn)
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
        managed = self._existing_managed(uid)
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
            if same_uid:
                raise ModError(
                    "E_DUPLICATE",
                    detail=(f"{uid} is already on disk as {', '.join(same_uid)}; "
                            f"disable or uninstall that copy before installing {dn}"),
                    context={"packageId": uid, "existing_dirs": same_uid})
        if os.path.exists(target) and not managed:
            raise ModError("E_FILE_COLLISION", detail=f"{target} exists and is not managed")
        w2 = preflight_root(r.game_root, need_writable=True)
        if os.path.isdir(r.mod_root) and not same_filesystem(r.mod_root, r.staging):
            raise ModError("E_CROSS_DEVICE", detail="Mods/ and .decky-staging are on different filesystems")
        plan = {"op": "install", "packageId": uid, "uniqueId": uid, "name": info["name"],
                "version": info["version"], "from": zip_path, "to": target,
                "w2": r.mod_root, "free_w2": w2.get("free_bytes"), "fs_posix": r.fs_posix,
                "strategy": "file_drop", "note": "install==enable (directory presence)"}
        if fomod_warnings:
            plan["fomod_warnings"] = fomod_warnings
            plan["fomod_selected"] = bool(fomod_override)
        if not after_confirm:
            return ok({"phase": "confirm", "plan": plan,
                       "confirm_text": f"Install {info['name']} ({uid}) to {target}?\n"
                                       f"(file_drop: unpacking the directory IS the enable step)",
                       "confirm_key": "CONFIRM_INSTALL_FD",
                       "confirm_vars": {"name": info["name"], "uid": uid, "target": target},
                       "targets": {"w1_state_file": None, "w2_install_dir": target},
                       "log_path": _log_path(self.journal)})
        txn = new_txn_id()
        self.journal.begin(txn, "install", plan)
        self.journal.applying(txn)
        staged = os.path.join(r.staging, txn)
        try:
            ensure_dir(r.staging)
            stage_dest = os.path.join(staged, dn)
            archive.extract_to(info, zip_path, stage_dest, member_override=fomod_override)
            replaced_qdir = None
            if os.path.isdir(target):
                replaced_qdir = os.path.join(r.quarantine_root, txn, dn + ".replaced")
                ensure_dir(os.path.dirname(replaced_qdir))
                os.replace(target, replaced_qdir)
            os.replace(stage_dest, target)
            self.journal.record("MOD_INSTALLED", txn, packageId=uid, uniqueId=uid,
                                name=info["name"], version=info["version"], dir=target,
                                dir_name=dn, replaced_old=replaced_qdir, ts=time.time())
            self.journal.record("MOD_ENABLED", txn, packageId=uid)  # file_drop: install==enable
            # Verify uses the descriptor parser's manifest path, NOT a hard-coded
            # "manifest.json" (Step 3: game-agnostic engine).
            verify_rel = info.get("manifest_stripped") or self._manifest_basename()
            if not os.path.isdir(target) or not os.path.isfile(os.path.join(target, verify_rel)):
                raise ModError("E_VERIFY_FAILED", detail=f"installed dir missing {verify_rel}")
            self.journal.committed(txn, {"packageId": uid, "dir": target})
            result = {"packageId": uid, "uniqueId": uid, "dir": target, "dir_name": dn,
                      "enabled": True, "txn": txn, "log_path": _log_path(self.journal)}
            if fomod_warnings:
                result["fomod_warnings"] = fomod_warnings
            return ok(result)
        except Exception as e:
            try:
                if os.path.isdir(target) and not managed:
                    shutil.rmtree(target, ignore_errors=True)
                self.journal.rolled_back(txn, {"reason": str(e)})
                code = e.code if isinstance(e, ModError) else (
                    map_oserror(e).code if isinstance(e, OSError) else "E_OP_FAILED")
                return err(code, detail=str(e), rollback_available=False)
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
            if enabled:
                raise ModError("E_DUPLICATE",
                               detail=f"{package_id} is not disabled (nothing parked in {r.disabled_root})")
            raise ModError("E_DUPLICATE", detail=f"{package_id} is not an enabled mod directory")
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
            return ok({"phase": "confirm", "plan": plan,
                       "confirm_text": f"{verb} {name}? The folder is moved to {dst_root} (not deleted).",
                       "confirm_key": "CONFIRM_ENABLE" if enabled else "CONFIRM_DISABLE",
                       "confirm_vars": {"pid": name},
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
                raise ModError("E_DUPLICATE", detail=f"{package_id} is not installed/managed")
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
            return ok({"phase": "confirm", "plan": plan,
                       "confirm_text": f"Uninstall {package_id}? The folder is moved to quarantine (not deleted).",
                       "confirm_key": "CONFIRM_UNINSTALL",
                       "confirm_vars": {"pid": package_id},
                       "targets": {"w1_state_file": None, "w2_quarantine": qdir},
                       "log_path": _log_path(self.journal)})
        self.journal.begin(txn, "uninstall", plan)
        self.journal.applying(txn)
        try:
            ensure_dir(os.path.dirname(qdir))
            if os.path.isdir(src):
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

    def _rollback_inner(self, txn: str) -> dict:
        self._gate("rollback")
        self._check_not_running()
        r = self._resolve()
        self._check_write_allowed(r)
        events = self.journal.events(txn)
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
            if os.path.isdir(qdir) and not os.path.isdir(src):
                os.replace(qdir, src)
            self.journal.record("MOD_ROLLBACK_RESTORED", txn, packageId=pid,
                                mod={"name": pid, "dir": src}, enabled=True,
                                # Round 21: carry ownership with the event. A mod
                                # the plugin never installed must not become
                                # "managed" just because its uninstall was undone.
                                unmanaged=bool(uninst.get("unmanaged")))
            self.journal.committed(txn, {"rollback_of": "uninstall", "packageId": pid})
            return ok({"restored": pid, "dir": src, "txn": txn, "log_path": _log_path(self.journal)})
        if state in ("PREPARED", "APPLYING"):
            try:
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
        return self.status()   # no state-fp cache in file_drop

    def recovery(self) -> dict:
        try:
            return ok({"pending": self.journal.pending(), "log_path": _log_path(self.journal)})
        except Exception as e:
            return err("E_UNKNOWN", detail=str(e))


# Backward-compatible alias: the historical Stardew tests and any external
# caller import ``StardewEngine``. The class is now descriptor-agnostic, but the
# name stays so no consumer breaks (Step 3 keeps the 46-test suite green).
StardewEngine = FileDropEngine
