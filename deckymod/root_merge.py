"""Round 76 — root_merge engine (Cyberpunk 2077 and games like it).

WHY THIS ENGINE EXISTS
----------------------
FileDropEngine assumes "one mod == one directory under mod_root", identified by
a manifest. Cyberpunk breaks every part of that assumption:

  * a classic mod is a single ``.archive`` FILE, not a folder;
  * a framework plugin is a tree under ``bin/x64/plugins``;
  * a redscript is a lone ``.reds`` file under ``r6/scripts``;
  * one archive can ship all three at once, and there is no manifest at all.

So this engine installs FILE BY FILE:
  * every member is routed into one of the descriptor's write_roots;
  * a member that routes nowhere is REFUSED (never guessed into place);
  * anything inside the descriptor's protected list is REFUSED;
  * a file that already exists is backed up byte-exact before replacement;
  * every placed file is journaled, which is what makes uninstall and rollback
    exact instead of "delete the folder and hope".

It inherits FileDropEngine for the game-agnostic parts: capability gate,
/proc running check, inbox listing, history, recovery, quarantine survey.
"""
from __future__ import annotations

import os
import shutil
import time
import zipfile

from . import quarantine as quarantine_mod
from .envelope import err, ok
from .errors import ModError
from .fsops import ensure_dir, map_oserror
from .journal import new_txn_id
from .smapi import FileDropEngine

# Members we never install and never complain about: OS/editor droppings.
_JUNK_DIRS = {"__MACOSX", ".git", ".svn"}
_JUNK_FILES = {".ds_store", "thumbs.db", "desktop.ini"}

# Root-level documentation. A mod zip that also carries a readme is normal; it
# must not block the install just because documentation is not routable.
_DOC_SUFFIXES = (".txt", ".md", ".pdf", ".url", ".htm", ".html",
                 ".jpg", ".jpeg", ".png", ".gif", ".webp")

# How many routing failures we name in one error message.
_MAX_REPORTED = 8


def _norm(name: str) -> str:
    """Normalise a zip member name to a relative POSIX path."""
    n = str(name or "").replace("\\", "/")
    while n.startswith("./"):
        n = n[2:]
    return n.lstrip("/")


def _is_unsafe(n: str) -> bool:
    """Reject absolute paths, drive letters, empty segments and '..'."""
    if not n:
        return True
    parts = n.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return True
    return ":" in parts[0] or parts[0].startswith("~")


def _sha256_file(path: str) -> str:
    h = __import__("hashlib").sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 256), b""):
            h.update(block)
    return h.hexdigest()


class RootMergeEngine(FileDropEngine):
    """Per-file install engine driven entirely by the descriptor."""

    # Round 86: this engine installs files, not mod directories, so two of the
    # base engine's optional arguments mean nothing here. Declaring that is what
    # main.py now asks; before, it guessed from hasattr(_set_enabled_inner),
    # which is inherited and therefore always true.
    #
    # SUPPORTS_FOMOD False: a .archive/.reds drop has no FOMOD installer tree.
    # SUPPORTS_MEMBER_ROOT False: there is no "several mods, pick one" case —
    #   a root_merge archive is one package by definition (_plan_archive routes
    #   every member by path, and _package_id names the whole thing).
    # SUPPORTS_ARCHIVE_MODS False: archive_mods exists only to feed the
    #   multi-mod picker, and it needs a manifest parser this descriptor has not
    #   got. Inheriting it silently made the RPC reachable and then failed deep
    #   inside file_drop with "no manifest parser named 'path_map'" — a parser
    #   name the user cannot act on.
    SUPPORTS_FOMOD = False
    SUPPORTS_MEMBER_ROOT = False
    SUPPORTS_ARCHIVE_MODS = False

    # ---------------------------------------------------------------- descriptor
    def _paths_cfg(self) -> dict:
        return (self._descriptor() or {}).get("paths") or {}

    def _write_roots(self) -> list:
        raw = self._paths_cfg().get("write_roots") or []
        return [_norm(str(x)).rstrip("/") for x in raw if str(x).strip()]

    def _protected(self) -> list:
        raw = self._paths_cfg().get("protected") or []
        return [_norm(str(x)).rstrip("/") for x in raw if str(x).strip()]

    def _route(self, name: str):
        """Member path -> install target, or None when it routes nowhere.

        Three accepted shapes: (a) the member already sits under a declared
        write root, (b) a bare .reds when r6/scripts is a declared root,
        (c) any other bare file when the descriptor names a root_file_target
        (a user-defined game has exactly one such folder).
        """
        low = name.lower()
        roots = self._write_roots()
        for root in roots:
            rl = root.lower()
            if low == rl or low.startswith(rl + "/"):
                return name
        if "/" not in name:
            lowers = [r.lower() for r in roots]
            # Cyberpunk's two unambiguous bare-file shapes, kept conditional on
            # the root actually being declared so a user-defined game can never
            # inherit them by accident.
            if low.endswith(".reds") and "r6/scripts" in lowers:
                return "r6/scripts/" + name
            if low.endswith(".archive") and "archive/pc/mod" in lowers:
                return "archive/pc/mod/" + name
            # Documentation at the archive root is skipped by the caller, never
            # installed -- a readme is not a mod file, whoever asked for it.
            if self._is_root_doc(name):
                return None
            fallback = self._paths_cfg().get("root_file_target")
            if isinstance(fallback, str) and fallback.strip():
                return _norm(fallback).rstrip("/") + "/" + name
        return None

    def _in_write_roots(self, target: str) -> bool:
        """Every install target must sit inside a declared root -- no exceptions."""
        low = target.lower()
        for root in self._write_roots():
            rl = root.lower()
            if low == rl or low.startswith(rl + "/"):
                return True
        return False

    def _is_protected(self, target: str) -> bool:
        low = target.lower()
        for p in self._protected():
            pl = p.lower()
            if pl.endswith("*"):
                if low.startswith(pl[:-1]):
                    return True
            elif low == pl or low.startswith(pl + "/"):
                return True
        return False

    def _is_junk(self, name: str) -> bool:
        parts = name.split("/")
        if any(p in _JUNK_DIRS for p in parts):
            return True
        return parts[-1].lower() in _JUNK_FILES

    def _is_root_doc(self, name: str) -> bool:
        return "/" not in name and name.lower().endswith(_DOC_SUFFIXES)

    def _strip_root_enabled(self) -> bool:
        """Only user-defined games enable this: their packages are ordinary
        'one folder + a loader tree' zips, whereas Cyberpunk's are path-mapped."""
        return bool((self._mod_package() or {}).get("strip_single_root"))

    def _single_root(self, names: list):
        """The one top-level folder every member shares, or None.

        A zip whose members are all ``MyMod/...`` carries the mod's own name as
        its first segment. Without this, such a package routes nowhere and the
        user sees "cannot install" for the most common mod format there is.
        Structural top-levels (archive/, mods/, bin/, r6/, BepInEx/) are never
        treated as a mod folder.
        """
        tops = set()
        for n in names:
            if "/" in n:
                tops.add(n.split("/")[0])
            elif self._is_root_doc(n):
                # A readme next to the mod folder is normal (most Nexus uploads
                # have one). It is skipped at install time, so it must not veto
                # the single-root shape.
                continue
            else:
                return None          # a real root-level file: not single-root
        if len(tops) != 1:
            return None
        top = next(iter(tops))
        if top.lower() in {"archive", "mods", "bin", "r6", "red4ext", "bepinex",
                           "plugins", "engine", "content", "mod"}:
            return None
        if self._in_write_roots(top):
            return None
        return top

    def _drop_staging(self, r, txn: str) -> None:
        """Remove this txn's staging dir, then the empty parent shell.

        (Found on device: a finished install left an empty .decky-staging/ in
        the game folder — harmless but confusing, and the user sees a folder
        the panel never explains.)
        """
        parent = os.path.join(r.game_root, ".decky-staging")
        shutil.rmtree(os.path.join(parent, txn), ignore_errors=True)
        try:
            os.rmdir(parent)   # succeeds only when the last txn just finished
        except OSError:
            pass

    # ------------------------------------------------------------------ planning
    def _plan_archive(self, zip_path: str) -> dict:
        """Read the archive and decide, for every member, where it would land.

        Pure: touches no game file. Returns routing results plus the reasons a
        member was refused, so inspect() and install() describe the same plan.
        """
        files = []
        skipped = []
        refused = []
        total = 0
        try:
            with zipfile.ZipFile(zip_path) as zf:
                infos = [i for i in zf.infolist() if not i.is_dir()]
                if len(infos) > 40000:
                    raise ModError("E_BAD_ARCHIVE", detail="archive has too many members")
                # Round 77: a user-added game receives ordinary "one folder"
                # zips (MyMod/MyMod.dll). Decide the shared top folder once,
                # before routing, so every member gets the same treatment.
                strip = None
                strip_base = None
                if self._strip_root_enabled():
                    raws = [_norm(i.filename) for i in infos]
                    raws = [r for r in raws if r and not self._is_junk(r)]
                    strip = self._single_root(raws)
                    if strip:
                        base = (self._paths_cfg().get("root_file_target")
                                or (self._write_roots()[0] if self._write_roots() else ""))
                        strip_base = _norm(str(base)).rstrip("/") if base else ""
                        if not strip_base:
                            strip = None
                for info in infos:
                    raw = _norm(info.filename)
                    if not raw:
                        continue
                    if self._is_junk(raw):
                        continue
                    if _is_unsafe(raw):
                        refused.append((raw, "path_escape"))
                        continue
                    target = self._route(raw)
                    if target is None and strip and raw.startswith(strip + "/"):
                        # Keep the mod folder name: two mods shipping a dll with
                        # the same basename must not overwrite each other.
                        target = strip_base + "/" + raw
                    if target is None:
                        # Name the REAL reason: "protected" (it targets shipped
                        # game payload) is far more useful than "unrouted".
                        if self._is_protected(raw):
                            refused.append((raw, "protected"))
                            continue
                        if self._is_root_doc(raw):
                            skipped.append(raw)
                            continue
                        refused.append((raw, "unrouted"))
                        continue
                    target = _norm(target)
                    if _is_unsafe(target):
                        refused.append((raw, "path_escape"))
                        continue
                    # The final gate: a route that lands outside every declared
                    # root is refused, so a descriptor can never widen itself.
                    if not self._in_write_roots(target):
                        refused.append((raw, "unrouted"))
                        continue
                    if self._is_protected(target):
                        refused.append((raw, "protected"))
                        continue
                    total += info.file_size
                    files.append({"member": raw, "target": target,
                                  "bytes": info.file_size})
        except zipfile.BadZipFile as e:
            raise ModError("E_BAD_ARCHIVE", detail=str(e))
        return {"files": files, "skipped": skipped, "refused": refused,
                "total_bytes": total}

    def _package_id(self, zip_path: str, plan: dict) -> tuple:
        """(packageId, name, version). No manifest exists for most packages.

        REDmod ships mods/<name>/info.json, which names the mod properly; every
        other package is named after the archive and the file set it carries,
        because inventing a UniqueID would be worse than an honest filename.
        """
        name = version = None
        try:
            with zipfile.ZipFile(zip_path) as zf:
                for member in zf.namelist():
                    m = _norm(member)
                    low = m.lower()
                    if not low.endswith("info.json"):
                        continue
                    if not (low.startswith("mods/") or low.count("/") == 1):
                        continue
                    try:
                        import json as _json
                        meta = _json.loads(zf.read(member).decode("utf-8", "replace"))
                    except Exception:
                        continue
                    if isinstance(meta, dict):
                        name = str(meta.get("name") or "").strip() or None
                        version = str(meta.get("version") or "").strip() or None
                        if name:
                            break
        except Exception:
            pass
        stem = os.path.splitext(os.path.basename(str(zip_path)))[0].strip()
        pid = name or stem or "cyberpunk-package"
        # Keep the wire id stable and filesystem-safe.
        pid = "".join(c for c in pid if c not in "\r\n\t").strip()
        return pid, (name or pid), version

    # ------------------------------------------------------------------ inspect
    def archive_mods(self, zip_path: str) -> dict:
        """Round 86: refuse here too, not just at the RPC boundary.

        FileDropEngine.archive_mods is inherited, and it calls
        manifest.parser_for(), so a direct engine call (tests, future code)
        would still surface "no manifest parser named 'path_map'". main.py asks
        SUPPORTS_ARCHIVE_MODS first, so this is the second line of defence --
        and it keeps the ANSWER SHAPE the base engine uses (an envelope, never
        a raised exception), because callers of ``archive_mods`` all treat it as
        envelope-returning.
        """
        return err("E_CAPABILITY_DISABLED",
                   detail="[archive_mods] this engine installs the whole "
                          "archive, so there is no mod root to pick",
                   data={"reason": "no_archive_mods"})

    def inspect(self, zip_path: str) -> dict:
        try:
            self._gate("local_import")
            r = self._resolve()
            self._validate_import_path(zip_path)
            plan = self._plan_archive(zip_path)
            if not plan["files"]:
                raise ModError("E_BAD_ARCHIVE",
                               detail="no installable file: expected .archive/.reds "
                                      "or a path under " + ", ".join(self._write_roots()))
            if plan["refused"]:
                raise ModError("E_NOT_ALLOWED_ROOT", detail=self._refusal_text(plan["refused"]))
            pid, name, version = self._package_id(zip_path, plan)
            collisions = [f for f in plan["files"]
                          if os.path.exists(os.path.join(r.game_root, f["target"]))]
            duplicate = pid in self.journal.installed()
            data = {
                "mod": {
                    "packageId": pid,
                    "name": name,
                    "version": version or "unknown",
                    "version_is_fallback": version is None,
                    "supportedVersions": [],
                    "badges": {},
                    "install_relpath": "",
                    "strip_single_root": None,
                    "entry_count": len(plan["files"]),
                    "uncompressed_size": plan["total_bytes"],
                },
                "conflict": {
                    "duplicate": duplicate,
                    "file_collision": bool(collisions),
                    "managed": None,
                    "same_unique_id_dirs": [],
                },
                "targets": {"w1_state_file": None, "w2_install_dir": r.game_root},
                "confirm_text": self._confirm_text(pid, plan, collisions),
                "log_path": "",
                "files": plan["files"][:200],
                "replaces": [f["target"] for f in collisions][:50],
                "ignored": plan["skipped"][:20],
            }
            return ok(data)
        except ModError as e:
            return err(e.code, detail=e.detail)
        except OSError as e:
            return err(map_oserror(e).code, detail=e.strerror)
        except Exception as e:
            self.journal.log(f"inspect unexpected: {type(e).__name__}: {e}")
            return err("E_UNKNOWN", detail=f"{type(e).__name__}: {e}")

    def _refusal_text(self, refused: list) -> str:
        shown = ["%s (%s)" % (n, why) for n, why in refused[:_MAX_REPORTED]]
        more = len(refused) - len(shown)
        head = "this archive contains files that cannot be installed safely: "
        tail = (" (+%d more)" % more) if more > 0 else ""
        return head + ", ".join(shown) + tail

    def _confirm_text(self, pid: str, plan: dict, collisions: list) -> str:
        lines = ["Install %s?" % pid,
                 "%d file(s), %d bytes" % (len(plan["files"]), plan["total_bytes"])]
        if collisions:
            lines.append("%d existing file(s) will be REPLACED (backed up first)"
                         % len(collisions))
        roots = sorted({f["target"].split("/")[0] for f in plan["files"]})
        lines.append("Writes under: " + ", ".join(roots))
        return "\n".join(lines)

    # ------------------------------------------------------------------ install
    def _install_inner(self, zip_path: str, after_confirm: bool,
                       fomod_choices: dict | None = None,
                       member_root: str | None = None) -> dict:
        # Round 86: the signature above MUST match the base class's, because
        # FileDropEngine.install() passes all four positionally. Before this fix
        # root_merge declared only three, so every install() on every root_merge
        # game -- Cyberpunk and every user-defined game -- raised
        #   TypeError: _install_inner() takes from 3 to 4 positional arguments
        #              but 5 were given
        # which install()'s broad `except Exception` turned into E_UNKNOWN with
        # no traceback to the user. Round 84 introduced it by adding member_root
        # to the wrapper and only one subclass.
        #
        # The two arguments are accepted for signature compatibility and refused
        # out loud. Silently ignoring them would be worse than the TypeError: a
        # caller asking to install ONE mod of a bundle would get the whole
        # bundle, and a caller passing FOMOD choices would get a plain extract
        # with no indication its choices were dropped.
        if fomod_choices:
            raise ModError("E_CAPABILITY_DISABLED",
                           detail="[root_merge] this engine has no FOMOD installer: "
                                  "the package is installed file by file",
                           context={"reason": "no_fomod"})
        if isinstance(member_root, str):
            raise ModError("E_CAPABILITY_DISABLED",
                           detail="[root_merge] this engine installs the whole archive: "
                                  "it has no member-root selection",
                           context={"reason": "no_member_root"})
        self._gate("local_import")
        self._check_not_running()
        r = self._resolve()
        self._check_no_pending()
        self._validate_import_path(zip_path)
        plan = self._plan_archive(zip_path)
        if not plan["files"]:
            raise ModError("E_BAD_ARCHIVE",
                           detail="no installable file in this archive")
        if plan["refused"]:
            raise ModError("E_NOT_ALLOWED_ROOT", detail=self._refusal_text(plan["refused"]))
        pid, name, version = self._package_id(zip_path, plan)
        if pid in self.journal.installed():
            raise ModError("E_DUPLICATE", detail="%s is already installed" % pid,
                           context={"packageId": pid})
        collisions = [f for f in plan["files"]
                      if os.path.exists(os.path.join(r.game_root, f["target"]))]
        if not after_confirm:
            return ok({
                "phase": "confirm",
                "plan": {"op": "install", "packageId": pid, "name": name,
                         "version": version or "unknown"},
                "files": len(plan["files"]),
                "total_bytes": plan["total_bytes"],
                "replaces": [f["target"] for f in collisions],
                "confirm_text": self._confirm_text(pid, plan, collisions),
                "ignored": plan["skipped"][:20],
            })
        txn = new_txn_id()
        self.journal.begin(txn, "root_merge", {"packageId": pid, "files": len(plan["files"])})
        self.journal.applying(txn)
        placed = []
        try:
            staging = os.path.join(r.game_root, ".decky-staging", txn)
            payload = os.path.join(staging, "payload")
            ensure_dir(payload)
            with zipfile.ZipFile(zip_path) as zf:
                for row in plan["files"]:
                    src = os.path.join(payload, row["target"].replace("/", os.sep))
                    ensure_dir(os.path.dirname(src))
                    with zf.open(row["member"]) as rf, open(src, "wb") as wf:
                        shutil.copyfileobj(rf, wf)
                    dest = os.path.join(r.game_root, row["target"].replace("/", os.sep))
                    ensure_dir(os.path.dirname(dest))
                    backup = None
                    if os.path.exists(dest):
                        backup = os.path.join(r.quarantine_root, "backup",
                                              row["target"].replace("/", os.sep))
                        ensure_dir(os.path.dirname(backup))
                        shutil.copy2(dest, backup)
                    os.replace(src, dest)
                    placed.append({"target": row["target"], "backup": backup,
                                   "sha256": _sha256_file(dest), "bytes": row["bytes"]})
                    self.journal.record("FILE_PLACED", txn, packageId=pid,
                                        target=row["target"],
                                        backup=("backup/" + row["target"]) if backup else None,
                                        bytes=row["bytes"])
            self.journal.record("MOD_INSTALLED", txn, packageId=pid, name=name,
                                version=version or "unknown", dir=pid)
            self.journal.record("MOD_ENABLED", txn, packageId=pid)
            self.journal.committed(txn, {"packageId": pid, "files": len(placed)})
            self._drop_staging(r, txn)
        except Exception:
            self.journal.rollback_failed(txn, {"packageId": pid})
            self._drop_staging(r, txn)
            raise
        return ok({
            "installed": pid,
            "packageId": pid,
            "name": name,
            "version": version or "unknown",
            "files": len(placed),
            "replaced": len(collisions),
            "txn": txn,
            "ignored": plan["skipped"][:20],
        })

    # ---------------------------------------------------------------- uninstall
    def _placed_for(self, package_id: str) -> list:
        """Every FILE_PLACED row this package still owns, newest txn first."""
        rows = []
        for rec in self.journal.read_all():
            if rec.get("event") == "FILE_PLACED" and rec.get("packageId") == package_id:
                rows.append(rec)
        return rows

    def _uninstall_inner(self, package_id: str, after_confirm: bool) -> dict:
        self._gate("uninstall_quarantine")
        self._check_not_running()
        r = self._resolve()
        self._check_no_pending()
        managed = self.journal.installed().get(package_id)
        placed = self._placed_for(package_id)
        if not managed and not placed:
            raise ModError("E_MOD_NOT_FOUND", detail="%s is not plugin-managed" % package_id)
        if not after_confirm:
            return ok({
                "phase": "confirm",
                "plan": {"op": "uninstall", "packageId": package_id},
                "files": len(placed),
                "confirm_text": "\n".join([
                    "Remove %s?" % package_id,
                    "%d file(s) will be deleted." % len(placed),
                    "Files this mod replaced are restored from backup.",
                    "Nothing original is touched: writes never leave %s."
                    % ", ".join(self._write_roots()),
                ]),
            })
        txn = new_txn_id()
        self.journal.begin(txn, "root_merge_uninstall", {"packageId": package_id})
        removed = 0
        restored = 0
        for rec in placed:
            target = _norm(rec.get("target") or "")
            if not target or _is_unsafe(target):
                continue
            dest = os.path.join(r.game_root, target.replace("/", os.sep))
            backup_rel = rec.get("backup")
            try:
                if os.path.exists(dest):
                    os.remove(dest)
                    removed += 1
                if backup_rel:
                    backup = os.path.join(r.quarantine_root,
                                          str(backup_rel).replace("/", os.sep))
                    if os.path.exists(backup):
                        ensure_dir(os.path.dirname(dest))
                        shutil.copy2(backup, dest)
                        restored += 1
            except OSError as e:
                self.journal.log("uninstall: %s -> %s" % (target, e))
        self.journal.record("MOD_UNINSTALLED", txn, packageId=package_id,
                            dir=package_id, files=removed, restored=restored)
        self.journal.committed(txn, {"packageId": package_id, "removed": removed})
        return ok({"uninstalled": package_id, "removed": removed,
                   "restored": restored, "txn": txn})

    # ------------------------------------------------------- loader install
    # Round 79 (user-approved red-line change): a loader ZIP (BepInEx …) may be
    # extracted for descriptors whose capabilities.loader_install is TRUE —
    # user-configured games only; every built-in descriptor keeps it false.
    # Guardrails that stay in force:
    #   * two-phase like install: confirm writes nothing;
    #   * the game must not be running; no pending transaction may exist;
    #   * the ZIP must come from a declared import root (Downloads);
    #   * every file is journaled, anything replaced is backed up first, and
    #     uninstall/rollback restore the originals — the loader is as removable
    #     as any mod;
    #   * Steam launch options are NEVER edited (the panel only shows text).

    def _loader_root(self, r) -> tuple:
        """(absolute loader root, path relative to game_root for the journal).

        Descriptor-driven: paths.loader_root is "${GAME_ROOT}" or a relative
        subpath ("${GAME_ROOT}/BepInEx" — even nested under the loader's own
        tree). Relative-to-game_root is what FILE_PLACED rows record, so the
        generic uninstall/rollback machinery works unchanged.
        """
        raw = str((self._paths_cfg() or {}).get("loader_root") or "").strip()
        raw = _norm(raw.replace("\\", "/"))
        if raw.startswith("${GAME_ROOT}"):
            raw = raw[len("${GAME_ROOT}"):].lstrip("/")
        elif raw in ("", ".", "$GAME_ROOT"):
            raw = ""
        loader_root = os.path.join(r.game_root, raw.replace("/", os.sep)) if raw else r.game_root
        return loader_root, raw

    def _plan_loader(self, zip_path: str, r) -> dict:
        files = []
        total = 0
        loader_root, loader_rel = self._loader_root(r)
        try:
            with zipfile.ZipFile(zip_path) as zf:
                infos = [i for i in zf.infolist() if not i.is_dir()]
                if len(infos) > 40000:
                    raise ModError("E_BAD_ARCHIVE", detail="archive has too many members")
                for info in infos:
                    raw = _norm(info.filename)
                    if not raw or self._is_junk(raw):
                        continue
                    if _is_unsafe(raw):
                        raise ModError("E_NOT_ALLOWED_ROOT",
                                       detail="unsafe path in loader zip: %s" % raw)
                    target = (loader_rel + "/" + raw).lstrip("/")
                    if _is_unsafe(target):
                        raise ModError("E_NOT_ALLOWED_ROOT",
                                       detail="unsafe loader target: %s" % target)
                    total += info.file_size
                    files.append({"member": raw, "target": target,
                                  "bytes": info.file_size})
        except zipfile.BadZipFile as e:
            raise ModError("E_BAD_ARCHIVE", detail=str(e))
        return {"files": files, "total_bytes": total, "loader_root": loader_root}

    def _loader_confirm_text(self, pid: str, plan: dict, collisions: list) -> str:
        lines = ["Install loader %s?" % pid.split(":", 1)[-1],
                 "%d file(s), %d bytes" % (len(plan["files"]), plan["total_bytes"])]
        if collisions:
            lines.append("%d existing file(s) will be REPLACED (backed up first)"
                         % len(collisions))
        tops = sorted({f["target"].split("/")[0] for f in plan["files"]})
        lines.append("Extracts to: " + ", ".join(tops[:6]))
        lines.append("Steam launch options are NOT edited. If the loader needs "
                     "WINEDLLOVERRIDES, the panel shows the text to paste yourself.")
        return "\n".join(lines)

    def install_loader(self, zip_path: str, after_confirm: bool = False) -> dict:
        """Extract a loader ZIP (BepInEx …) to the descriptor's loader root."""
        try:
            self._gate("loader_install")
        except ModError as e:
            return err(e.code, detail=e.detail)
        try:
            r = self._resolve()
            self._check_not_running()
            self._check_no_pending()
            self._validate_import_path(zip_path)
            plan = self._plan_loader(zip_path, r)
            if not plan["files"]:
                raise ModError("E_BAD_ARCHIVE",
                               detail="no installable file in this loader archive")
            stem = os.path.splitext(os.path.basename(str(zip_path)))[0].strip()
            pid = "loader:" + "".join(c for c in stem if c not in "\r\n\t")
            collisions = [f for f in plan["files"]
                          if os.path.exists(os.path.join(r.game_root,
                                                         f["target"].replace("/", os.sep)))]
            if not after_confirm:
                return ok({
                    "phase": "confirm",
                    "plan": {"op": "install_loader", "packageId": pid},
                    "files": len(plan["files"]),
                    "total_bytes": plan["total_bytes"],
                    "replaces": [f["target"] for f in collisions][:50],
                    "confirm_text": self._loader_confirm_text(pid, plan, collisions),
                })
            txn = new_txn_id()
            self.journal.begin(txn, "loader_install", {"packageId": pid,
                                                       "files": len(plan["files"])})
            self.journal.applying(txn)
            placed = []
            try:
                staging = os.path.join(r.game_root, ".decky-staging", txn)
                payload = os.path.join(staging, "payload")
                ensure_dir(payload)
                loader_root = plan["loader_root"]
                with zipfile.ZipFile(zip_path) as zf:
                    for row in plan["files"]:
                        src = os.path.join(payload, row["target"].replace("/", os.sep))
                        ensure_dir(os.path.dirname(src))
                        with zf.open(row["member"]) as rf, open(src, "wb") as wf:
                            shutil.copyfileobj(rf, wf)
                        dest = os.path.join(r.game_root, row["target"].replace("/", os.sep))
                        ensure_dir(os.path.dirname(dest))
                        backup = None
                        if os.path.exists(dest):
                            backup = os.path.join(r.quarantine_root, "backup",
                                                  row["target"].replace("/", os.sep))
                            ensure_dir(os.path.dirname(backup))
                            shutil.copy2(dest, backup)
                        os.replace(src, dest)
                        placed.append(row["target"])
                        self.journal.record("FILE_PLACED", txn, packageId=pid,
                                            target=row["target"],
                                            backup=("backup/" + row["target"]) if backup else None,
                                            bytes=row["bytes"])
                self.journal.record("MOD_INSTALLED", txn, packageId=pid, name=pid,
                                    version="loader", dir=pid)
                self.journal.committed(txn, {"packageId": pid, "files": len(placed)})
                self._drop_staging(r, txn)
            except Exception:
                self.journal.rollback_failed(txn, {"packageId": pid})
                self._drop_staging(r, txn)
                raise
            return ok({
                "installed": pid,
                "packageId": pid,
                "files": len(placed),
                "replaced": len(collisions),
                "txn": txn,
            })
        except ModError as e:
            return err(e.code, detail=e.detail)
        except OSError as e:
            return err(map_oserror(e).code, detail=e.strerror)
        except Exception as e:
            self.journal.log("install_loader unexpected: %s: %s"
                             % (type(e).__name__, e))
            return err("E_UNKNOWN", detail=f"{type(e).__name__}: {e}")

    # ------------------------------------------------------------- unsupported
    def _set_enabled_inner(self, package_id: str, enabled: bool, after_confirm: bool) -> dict:
        raise ModError("E_CAPABILITY_DISABLED",
                       detail="this game has no enable/disable: a mod is present "
                              "because its files are present")

    def _handover_roots(self, r) -> list:
        """Round 81: every declared write root is a folder another manager can own.

        This engine has no single ``Mods/``: Cyberpunk receives files into
        ``archive/pc/mod``, ``mods``, ``bin/x64/plugins``, ``r6/scripts`` and
        ``red4ext``, and a user-configured game declares one or more folders of
        its own. Vortex/MO2 deploy into exactly those folders, usually as
        symlinks, so the takeover has to survey all of them -- and refuse as a
        whole if any one of them cannot be moved back in one step.

        Absolute paths, because ``handover.survey()`` compares ``st_dev``
        against ``game_root`` and reads ``os.lstat()`` on each one.
        """
        out = []
        for root in self._write_roots():
            out.append(os.path.join(r.game_root, str(root).replace("/", os.sep)))
        return out

    # ------------------------------------------------------------------- status
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
        inst = self.journal.installed()
        mods = []
        for pid, meta in sorted(inst.items()):
            placed = self._placed_for(pid)
            present = bool(placed) and all(
                os.path.exists(os.path.join(r.game_root, _norm(x.get("target")).replace("/", os.sep)))
                for x in placed)
            mods.append({
                "packageId": pid,
                "name": meta.get("name") or pid,
                "version": meta.get("version") or "unknown",
                "enabled": bool(meta.get("enabled", True)),
                "dir": pid,
                "files": len(placed),
                "present": present,
                "txn": meta.get("txn"),
                "installed_at": meta.get("installed_at"),
            })
        try:
            quar_info = quarantine_mod.survey(r.quarantine_root, self.journal)
        except Exception as exc:  # noqa: BLE001 - status must survive
            quar_info = {"checked": False, "reason": "scan_failed",
                         "detail": "%s: %s" % (exc.__class__.__name__, exc),
                         "entries": [], "dirs": 0, "total_bytes": 0,
                         "restorable": 0, "orphans": 0, "empty": 0}
        ident = d.get("identity", {}) or {}
        pending = self.journal.pending()
        data = {
            "game": {"appid": ident.get("appid"), "name": ident.get("name") or self.game_id,
                     "platform": ident.get("platform") or "",
                     "status": d.get("status") or ""},
            "paths": {
                "w1_state_file": None,
                "w2_mod_root": r.game_root,
                "quarantine_root": r.quarantine_root,
                "staging": r.staging,
                "disabled_root": "",
                "flatpak": r.flatpak,
                "fs_posix": r.fs_posix,
                "write_roots": self._write_roots(),
            },
            "state": {
                "strategy": "root_merge",
                "mods": mods,
                "disabled_mods": [],
                "duplicate_ids": [],
                "missing_dependencies": [],
                "parked_dependencies": [],
                "outdated_dependencies": [],
                "external_manager": {"detected": False, "name": None, "detail": ""},
                "loader_detected": {},
                "launch_options": {"checked": False, "detail": ""},
                "read_only": False,
                "layout": {},
                "conflicts": {"checked": False, "reason": "not_applicable",
                              "conflicts": [], "total": 0},
                "quarantine": quar_info,
                "running": self._running(r),
            },
            "installed": list(inst.values()),
            "pending_recovery": pending,
            "recovery_needed": bool(pending),
            "capabilities": d.get("capabilities", {}),
            "known_limitations": d.get("known_limitations", []),
            "known_limitation_keys": d.get("known_limitation_keys", []),
            "loader_log": {"available": False, "reason": "not_applicable"},
            "log_path": getattr(self.journal, "log_path", ""),
        }
        return ok(data)
