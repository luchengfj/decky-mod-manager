"""Decky Loader plugin entry point (Python / backend side).

Decky loads this file, instantiates ``Plugin``, and dispatches frontend
``call("method", ...args)`` to the matching public ``async def`` on this class
via ``getattr``. Leading-underscore names are RESERVED lifecycle hooks
(``_main`` / ``_unload`` / ``_uninstall`` / ``_migration``) and are never
reachable as RPC methods.

Communication contract (§1):
  * call / callable  -> public async methods below, positional args only
                        (``call("install", zipPath, true)``). The Python side
                        returns plain JSON-safe dicts (envelope.py).
  * emit             -> server->client fire-and-forget progress events via
                        ``decky.emit("deckymod:progress", payload)``; the
                        frontend subscribes with a STABLE function reference
                        (addEventListener/removeEventListener).
  * JSON-safe        -> no Path / bytes / set / datetime / NaN ever leaves
                        this module; envelope() is the single gateway.

This module is stdlib-only. ``import decky`` is provided by the Decky loader
at runtime; the guarded import below lets the file be compiled and imported on
a dev box (where decky is absent) for self-tests.
"""

from __future__ import annotations

import os
import traceback

try:
    import decky  # injected by the Decky plugin loader
except ImportError:  # dev / CI box: provide a harmless shim
    decky = None

from deckymod.engine import Engine
from deckymod.smapi import FileDropEngine
from deckymod.root_merge import RootMergeEngine
from deckymod.envelope import err, ok
from deckymod.errors import ERRORS, ModError
from deckymod.registry import Registry
# Downloads come from GitHub Releases (the one source that works on this device)
# plus a plain https URL fallback. deckymod.download is the shared low-level
# https/JSON/download layer. No credential is stored or read by the plugin.
from deckymod import auto_import
from deckymod import deps
from deckymod import github_source
from deckymod import download
from deckymod import nexus
from deckymod import openurl
from deckymod import steamlib
from deckymod import templates

PROGRESS_EVENT = "deckymod:progress"

# Descriptor-driven engine selection (goal-221c8ac6 rev2, Steps 3-4). Game
# identity NEVER appears as an `if game == "..."` branch: the descriptor's
# "engine" key chooses the class. Adding a game = one descriptor JSON.
# "unsupported" (e.g. valheim) has NO entry, so it can never be dispatched.
ENGINE_FACTORY = {
    "file_drop": FileDropEngine,
    "xml_list": Engine,
    # Round 76: games whose mods are files scattered across several roots
    # (Cyberpunk 2077) install per file, not "one folder into Mods/".
    "root_merge": RootMergeEngine,
}


def _make_engine():
    """Dispatch purely from the active descriptor's ``engine`` key.

    Production: registry.json active_game="stardew" (engine=file_drop) ->
    FileDropEngine (SMAPI detect-only). The 33 historical RimWorld tests pin
    DECKYMOD_GAME_ID=rimworld (engine=xml_list) -> the original Engine,
    byte-for-byte. Both expose the SAME 11 positional RPCs, so the wire is
    unchanged. Construction is deferred to first use.
    """
    _, desc = Registry().active_descriptor()
    engine_key = desc.get("engine", "file_drop")
    cls = ENGINE_FACTORY.get(engine_key)
    if cls is None:
        raise RuntimeError(f"no engine registered for descriptor engine={engine_key!r}")
    return cls(decky=decky)


def _selection_label() -> str:
    """Descriptor-driven QAM/log label (no hard-coded game name)."""
    try:
        _, desc = Registry().active_descriptor()
        return desc.get("display_label") or desc.get("identity", {}).get("name") or "unknown"
    except Exception:
        return "unknown"


def _with_game_mods(summary: dict) -> dict:
    """Round 37: attach a read-only Mod-directory scan to every listed game.

    The user asked to see "my mods" grouped by game. The plugin's own journal
    only knows what IT installed, so a game the user modded by hand looked
    empty. This walks each game's template directory and reports the folder
    names already there — still read-only, still no new RPC, and games without
    a template keep ``note="not_adapted"`` rather than a guessed path.

    Display-only: a failure on one game must never blank the whole list.
    """
    try:
        games = summary.get("games") if isinstance(summary, dict) else None
        if isinstance(games, list):
            for g in games:
                if not isinstance(g, dict):
                    continue
                try:
                    g["template"] = templates.scan_mods(
                        g.get("appid"), str(g.get("install_path") or ""))
                except Exception:
                    # keep whatever identify() already put there
                    pass
    except Exception:
        pass
    return summary


def _with_catalog(env: dict) -> dict:
    """P0 (round 2): additively attach the read-only game catalog to an
    existing ``status()`` envelope. This does NOT add a new RPC — the same 11
    positional RPCs stay on the wire, and only the ``status`` envelope gains a
    new ``data.catalog`` key. The catalog is gate-free read-only descriptor
    metadata (see ``Registry.catalog``). Both engines' ``status()`` are left
    untouched, so the RimWorld regression path stays byte-identical.

    Display-only: any failure is swallowed so it can never break ``status()``.
    """
    try:
        data = env.get("data") if isinstance(env, dict) else None
        if isinstance(data, dict):
            data["catalog"] = Registry().catalog()
    except Exception:
        pass
    return env


# --------------------------------------------------------------------------- helpers
def _log(level: str, msg: str) -> None:
    """Best-effort logging that works with and without the Decky runtime."""
    try:
        if decky is not None and getattr(decky, "logger", None) is not None:
            getattr(decky.logger, level, decky.logger.info)(msg)
    except Exception:
        pass
    # Always mirror into our own managed log so the UI can show a log path.
    try:
        rt = os.environ.get("DECKY_PLUGIN_RUNTIME_DIR") or ""
        log_dir = os.environ.get("DECKY_PLUGIN_LOG_DIR") or (os.path.join(rt, "logs") if rt else "")
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
            import time
            with open(os.path.join(log_dir, "deckymod.log"), "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} [{level}] {msg}\n")
    except OSError:
        pass


def _bridge_env() -> None:
    """Copy Decky module attributes into os.environ (idempotent, never overwrite
    an explicit value). The backend resolves everything from env vars so it can
    be unit-tested against a synthetic tree without the Decky runtime.

    ⚠️ V2/V3: confirm the exact attribute names against the LOCKED Decky
    Loader version; the loader usually ALSO exports these as env vars already.
    """
    if decky is None:
        return
    pairs = {
        "DECKY_HOME": "DECKY_HOME",
        "DECKY_USER": "DECKY_USER",
        "DECKY_USER_HOME": "DECKY_USER_HOME",
        "DECKY_PLUGIN_SETTINGS_DIR": "DECKY_PLUGIN_SETTINGS_DIR",
        "DECKY_PLUGIN_RUNTIME_DIR": "DECKY_PLUGIN_RUNTIME_DIR",
        "DECKY_PLUGIN_LOG_DIR": "DECKY_PLUGIN_LOG_DIR",
        "DECKY_PLUGIN_DIR": "DECKY_PLUGIN_DIR",
    }
    for env_name, attr in pairs.items():
        if os.environ.get(env_name):
            continue
        val = getattr(decky, attr, None)
        if isinstance(val, str) and val:
            os.environ[env_name] = val


def _emit(event: str, payload: dict) -> None:
    """Fire-and-forget server->client event. Never raises, never blocks."""
    try:
        if decky is not None and hasattr(decky, "emit"):
            decky.emit(event, payload)
    except Exception as e:  # emit is optional; a broken bridge must not fail an op
        _log("debug", f"emit skipped: {type(e).__name__}: {e}")


def _progress(stage: str, *, op: str = "", package_id: str = "", pct: int = 0) -> None:
    _emit(PROGRESS_EVENT, {"stage": stage, "op": op, "packageId": package_id, "pct": pct})


def _guard(fn, *args, **kwargs):
    """Last-resort net around every RPC method: convert ANY exception into a
    stable E_* envelope so a traceback never reaches the frontend bridge.

    Round 78: a ``ModError`` is NOT flattened to E_UNKNOWN any more — it
    reaches the panel under its own code (E_CAPABILITY_DISABLED for a refused
    switch, E_NOT_ALLOWED_ROOT for an anti-cheat game, …), with the localized
    message from errors.py and the original detail. Flattening it made every
    refusal look like a plugin bug instead of the answer it was.
    """
    try:
        result = fn(*args, **kwargs)
        return result
    except ModError as e:
        _log("info", f"{getattr(fn, '__name__', 'rpc')} refused: {e.code}: {e.detail}")
        data = dict(e.context) if e.context else None
        return err(e.code, detail=e.detail, rollback_available=e.rollback_available,
                   data=data)
    except Exception as e:  # noqa: BLE001 - deliberate catch-all at the boundary
        _log("error", f"{getattr(fn, '__name__', 'rpc')} unhandled: {type(e).__name__}: {e}")
        _log("debug", traceback.format_exc())
        return err("E_UNKNOWN", detail=f"{type(e).__name__}: {e}")


def _core_to_envelope(res, mapper: dict, stage: str):
    """Adapt a policy-neutral core result (download) into the SHIPPED
    8-key Envelope. Those libraries return their own ``{ok, code, ...}`` dicts
    with module-local ``DL_*`` codes that are NOT in errors.py, so:

      * success -> the whole (already JSON-safe, already key-scrubbed) dict is
        placed in ``data`` via ``ok()``;
      * failure -> the module code is mapped onto an EXISTING ``E_*`` code via
        ``mapper`` (DL_TO_E), keeping ``error_codes()`` at 50 entries
        and the i18n ``ERR_E_*`` / ``CAT_*`` dictionaries untouched.

    The core never echoes the secret; this helper never sees the raw key.
    """
    if not isinstance(res, dict):
        return err("E_UNKNOWN", detail=f"[{stage}] core returned a non-dict result")
    if res.get("ok"):
        return ok(res)
    code = str(res.get("code") or "")
    e_code = mapper.get(code, "E_UNKNOWN")
    detail = "[%s] %s: %s" % (stage, code, res.get("detail") or res.get("message") or "failed")
    return err(e_code, detail=detail, data=res)


def _network_download_gate():
    """Fail-closed policy hook for EVERY network-facing RPC.

    Returns None when the active game's ``network_download`` capability is true;
    otherwise a stable E_CAPABILITY_DISABLED Envelope. Deliberately NON-RAISING:
    a raised ModError would be flattened to E_UNKNOWN by _guard.

    Round 19: unlike round 18 there is no ungated exception. The credential RPCs
    are gone, and all four download RPCs reach the network, so all four gate.
    """
    try:
        gid, desc = Registry().active_descriptor()
    except Exception as e:  # noqa: BLE001 - policy hook must not leak a traceback
        return err("E_CAPABILITY_DISABLED",
                   detail="[network_download] no active game descriptor: %s: %s"
                          % (type(e).__name__, e),
                   data={"reason": "no_active_game"})
    caps = desc.get("capabilities", {}) if isinstance(desc, dict) else {}
    if not caps.get("network_download", False):
        return err("E_CAPABILITY_DISABLED",
                   detail="[network_download] capability=false for %s" % gid,
                   data={"reason": "network_download_off"})
    return None


def _source_cfg(name: str) -> dict:
    """Read the active descriptor's ``download_sources.<name>`` block.

    Game-specific hosts/paths live in the descriptor, not in Python, so a new
    source is a JSON edit. Missing configuration degrades to an empty dict and
    the caller decides what that means (direct-URL stays disabled by default).
    """
    try:
        _, desc = Registry().active_descriptor()
    except Exception:  # noqa: BLE001 - config lookup must never raise into a RPC
        return {}
    src = (desc.get("download_sources") or {}) if isinstance(desc, dict) else {}
    cfg = src.get(name)
    return cfg if isinstance(cfg, dict) else {}


def _loader_offers(install_path: str) -> list:
    """Loader catalog entries that can be opened in a browser (round 79).

    Read-only: which loaders APPLY is a hint from stat'ing two well-known
    Unity files (GameAssembly.dll = IL2CPP, Assembly-CSharp.dll = mono), never
    a guess that blocks anything — every loader with a browse_url is listed
    and the user picks. ``installed`` mirrors the catalog's own detect
    patterns so the panel can say "already there".
    """
    try:
        reg = Registry()
    except Exception:  # noqa: BLE001 - display-only helper
        return []
    il2cpp = bool(install_path) and os.path.isfile(
        os.path.join(install_path, "GameAssembly.dll"))
    mono = bool(install_path) and os.path.isfile(
        os.path.join(install_path, "_managed", "Assembly-CSharp.dll"))
    out = []
    for lid, doc in sorted((reg.loaders or {}).items()):
        if not isinstance(doc, dict):
            continue
        url = str(doc.get("browse_url") or "").strip()
        if not url:
            continue  # no official page declared -> nothing to open
        patterns = ((doc.get("detect") or {}).get("patterns")) or []
        installed = False
        if install_path:
            installed = any(os.path.exists(
                os.path.join(install_path, str(p).rstrip("/"))) for p in patterns)
        hint = str(doc.get("hint") or "")
        if hint in ("unity-either", "", "unknown"):
            fits = True       # generic: never hidden, never ranked first
        elif hint == "unity-il2cpp":
            fits = il2cpp
        elif hint == "unity-mono":
            fits = mono
        else:
            fits = True       # unknown hint: show, but it earns no top rank
        out.append({
            "id": str(lid),
            "name": str(doc.get("name") or lid),
            "browse_url": url,
            "version": str(doc.get("version") or ""),
            "hint": hint,
            "hint_note": str(doc.get("hint_note") or ""),
            "hint_fits": bool(fits),
            "installed": installed,
        })
    # Loaders that stat-fit the detected Unity flavour first, then the rest.
    out.sort(key=lambda x: (not x["hint_fits"], x["name"]))
    return out


class Plugin:
    """One instance per plugin load. Public async methods == RPC callables.

    Every method returns the SAME JSON-safe envelope shape:
      { ok, code, message, detail, data, rollback_available, log_path, ts }
    """

    def __init__(self):
        self.engine: Engine | FileDropEngine | None = None

    # ------------------------------------------------------------------ lifecycle
    async def _main(self):
        """Lifecycle hook: called once after the plugin is loaded."""
        _bridge_env()
        try:
            self.engine = _make_engine()
            _log("info", f"Decky MOD Manager loaded ({_selection_label()})")
            self.engine.journal.log("plugin loaded")
        except Exception as e:  # keep the plugin alive; status() will report the error
            _log("error", f"engine init failed: {type(e).__name__}: {e}")
            self.engine = None
        _progress("loaded")

    async def _unload(self):
        """Lifecycle hook: Decky is unloading the plugin (G1 / §5.3).

        We do NOT mutate game state here. We only drop in-memory caches and
        flush the log. Any PREPARED/APPLYING transaction stays in the journal
        and is surfaced as E_RECOVERY_PENDING on the next open.
        """
        _log("info", "Decky MOD Manager unloading; no state changes on unload")
        try:
            if self.engine is not None:
                self.engine.journal.log("plugin unloaded")
        except Exception:
            pass
        self.engine = None
        _progress("unloaded")

    async def _uninstall(self):
        """Lifecycle hook: plugin removal. We do NOT delete user game data.
        Uninstalled mods remain in quarantine; the journal remains on disk.
        Only our own transient in-memory state is released.
        """
        _log("info", "plugin _uninstall: game data and journal intentionally preserved")
        self.engine = None

    async def _migration(self):
        """Lifecycle hook: schema migrations, if any, run here. MVP journal is
        append-only JSONL with no schema version to migrate yet.
        """
        _log("info", "no migrations for schema 0.1.0-mvp")
        return None

    # ------------------------------------------------------------------ RPC helpers
    def _engine(self) -> Engine | FileDropEngine:
        if self.engine is None:
            _bridge_env()
            self.engine = _make_engine()
        return self.engine

    # ------------------------------------------------------------------ read RPCs
    async def list_games(self):
        """Enumerate every Steam library and the games installed in them.

        Goal item 2: the UI needs AppID + install path + compatdata prefix for
        all installed games, across the internal drive and the SD card. This is
        read-only — it never creates directories — so it is safe to call from the
        portal before any write capability exists. It deliberately does NOT go
        through an engine: it is a machine-level fact, not a per-game one, and it
        must keep working for games no descriptor covers.
        """
        return _guard(lambda: ok(_with_game_mods(steamlib.summarize())))

    async def switch_game(self, game_id: str):
        """Make another SUPPORTED game the one this panel manages.

        Round 76: exactly one game is active at a time (max_enabled_games_in_mvp
        is 1), so supporting a second game is a switch, not a merge. Only a
        descriptor with status=enabled is selectable; planned/unsupported ones
        keep answering E_CAPABILITY_DISABLED.

        The cached engine is dropped on success, so the next RPC rebuilds
        against the new descriptor -- no plugin reload, no Decky restart.
        """
        def _run():
            res = Registry().switch_active_game(str(game_id or ""))
            self.engine = None
            return ok(res)
        return _guard(_run)

    async def game_setup(self, appid: int):
        """What the panel needs to configure a game the plugin ships no descriptor for.

        Round 77: the honest "every game" story. The plugin can move files for
        any game, but only the user knows where that game's loader reads. This
        returns the usual candidate folders (flagged by whether they already
        exist on disk) plus whether the game is one we refuse outright.
        """
        def _run():
            from deckymod import user_games
            try:
                want = int(appid)
            except (TypeError, ValueError):
                raise ModError("E_PATH_INVALID", detail="appid must be a number")
            name = ""
            install_path = ""
            for g in (steamlib.summarize().get("games") or []):
                try:
                    if int(g.get("appid") or 0) == want:
                        name = str(g.get("name") or "")
                        install_path = str(g.get("install_path") or "")
                        break
                except (TypeError, ValueError):
                    continue
            existing = user_games.load_all().get(want)
            loaders = _loader_offers(install_path)
            return ok({
                "appid": want,
                "name": name or ("App %d" % want),
                "install_path": install_path,
                "candidates": user_games.candidate_roots(install_path),
                "refused": user_games.is_refused_game(name),
                "configured": existing is not None,
                "write_roots": (existing or {}).get("write_roots") or [],
                "loaders": loaders,
            })
        return _guard(_run)

    async def configure_game(self, appid: int, name: str, write_roots: list):
        """Save the mod folders for one game, then rebuild the engine.

        Round 79 (device finding): a user was able to re-configure a game the
        plugin ALREADY ships a descriptor for — Stardew Valley got a second,
        root_merge descriptor that shadowed its SMAPI management. A built-in
        descriptor is an adaptation, not a default: refuse the duplicate.
        """
        def _run():
            from deckymod import user_games
            for gid, d in (Registry().descriptors or {}).items():
                if gid.startswith("user_"):
                    continue
                try:
                    builtin_appid = int((d.get("identity") or {}).get("appid") or 0)
                except (TypeError, ValueError):
                    continue
                if builtin_appid and builtin_appid == int(appid):
                    return err("E_NOT_ALLOWED_ROOT",
                               detail="[configure_game] %r is already managed by the "
                                      "built-in descriptor %r — its mod folders are "
                                      "adapted, not configurable" % (name, gid))
            rec = user_games.save(appid, name, write_roots)
            self.engine = None
            return ok(rec)
        return _guard(_run)

    async def forget_game(self, appid: int):
        """Remove a user-defined configuration (never touches the game files).

        If the removed game was the ACTIVE one, the plugin would be left with
        no enabled descriptor and every later RPC would answer
        E_CAPABILITY_DISABLED. So fall back to a built-in game in that case.
        """
        def _run():
            from deckymod import user_games
            gone = user_games.forget(int(appid))
            gid = user_games.game_id(int(appid))
            switched = None
            reg = Registry()
            if reg.raw.get("active_game") == gid and gid not in reg.descriptors:
                for cand in ("stardew", "cyberpunk"):
                    if cand in reg.descriptors:
                        try:
                            reg.switch_active_game(cand)
                            switched = cand
                        except ModError:
                            continue
                        break
            self.engine = None
            return ok({"appid": int(appid), "deleted": gone, "switched_to": switched})
        return _guard(_run)

    async def install_loader(self, zip_path: str, after_confirm: bool = False):
        """Extract a loader ZIP (BepInEx …) into the game's loader root.

        Round 79 (user-approved red-line change, scoped): ONLY a descriptor
        whose capabilities.loader_install is TRUE may do this — user-configured
        games; every built-in descriptor keeps it false and is refused with
        E_CAPABILITY_DISABLED. The guardrails that stay in force:

        * two-phase: after_confirm=False plans and writes NOTHING;
        * the game must not be running; no unfinished transaction may exist;
        * the ZIP must sit in a declared import root (Downloads);
        * every file is journaled, replaced files are backed up first, and the
        existing uninstall/rollback machinery removes the loader exactly;
        * Steam launch options are NEVER edited — the confirm text says what
        to paste, the user pastes it.
        """
        def _run():
            engine = self._engine()
            if not hasattr(engine, "install_loader"):
                return err("E_CAPABILITY_DISABLED",
                           detail="[install_loader] this engine has no loader "
                                  "install path",
                           data={"reason": "no_loader_install"})
            _progress("loader:start", op="install_loader")
            r = engine.install_loader(str(zip_path or ""),
                                      after_confirm=bool(after_confirm))
            _progress("loader:done", op="install_loader",
                      pct=100 if r.get("ok") else 0)
            return r
        return _guard(_run)

    async def open_loader_page(self, loader_id: str):
        """Open a loader's official download page in the signed-in browser.

        The address is built here from the loader catalog's ``browse_url``
        (registry/loaders/<id>.json) — the caller passes the catalog id, never
        a URL. Nothing is downloaded by the plugin: the browser hand-off is
        the same contract as the Nexus page openers.
        """
        def _run():
            lid = str(loader_id or "").strip()
            try:
                reg = Registry()
            except Exception as e:  # noqa: BLE001 - boundary
                return err("E_UNKNOWN", detail="[open_loader_page] %s: %s"
                           % (type(e).__name__, e))
            doc = (reg.loaders or {}).get(lid)
            if not isinstance(doc, dict):
                return err("E_PATH_INVALID",
                           detail="[open_loader_page] unknown loader id: %s" % lid)
            url = str(doc.get("browse_url") or "").strip()
            if not url:
                return err("E_CAPABILITY_DISABLED",
                           detail="[open_loader_page] loader %s declares no "
                                  "browse_url" % lid,
                           data={"reason": "loader_no_page", "loader": lid})
            # The trust boundary is the loader catalog that ships with the
            # plugin: only the host IT declares may be handed to the browser.
            from urllib.parse import urlsplit
            host = (urlsplit(url).hostname or "").lower().rstrip(".")
            got = openurl.open_url(url, allowed_hosts={host} if host else None)
            if not got.get("ok"):
                return err("E_CAPABILITY_DISABLED",
                           detail="[open_loader_page] %s: %s" % (
                               got.get("reason"), got.get("detail") or ""),
                           data={"url": url, "reason": "open_failed",
                                 "why": got.get("reason")})
            _progress("open_loader_page:done")
            return ok({"url": url, "loader": lid, "opened": True})
        return _guard(_run)

    async def status(self):
        """Bootstrap call: game info, resolved W1/W2 paths, enabled mods,
        managed mods, pending recovery. Non-mutating.
        """
        def _run():
            if self._engine().journal.pending():
                pass  # status() still reports; UI offers Recovery (E_RECOVERY_PENDING)
            return _with_catalog(self._engine().status())
        return _guard(_run)

    async def list_inbox(self):
        """List local ZIPs in the fixed inbox (review #3: no network)."""
        return _guard(lambda: self._engine().list_inbox())

    async def inspect(self, zip_path: str, member_root: str | None = None):
        """Dry-run inspection of ONE local ZIP. No writes.

        Round 84: ``member_root`` previews a single mod of a multi-mod archive.
        Without it the preview of a bundle re-raises E_MULTI_MOD_ARCHIVE, which
        would bounce the user back to the picker they had just used.
        """
        root = member_root if isinstance(member_root, str) else None

        def _run():
            engine = self._engine()
            # Round 86: ask the engine what it supports instead of probing for a
            # method every engine happens to inherit. `hasattr(engine,
            # "_set_enabled_inner")` was true for RootMergeEngine too, so a
            # member_root reached `inspect(zip_path)` as a stray kwarg and the
            # TypeError came back as E_UNKNOWN.
            #
            # Refusing out loud, rather than dropping the argument, because a
            # silently ignored member_root previews the WHOLE archive while the
            # caller believes it is looking at one mod.
            if root is not None:
                if getattr(engine, "SUPPORTS_MEMBER_ROOT", False):
                    return engine.inspect(zip_path, member_root=root)
                return err("E_CAPABILITY_DISABLED",
                           detail="[inspect] this engine installs the whole "
                                  "archive: it has no member-root selection",
                           data={"reason": "no_member_root"})
            return engine.inspect(zip_path)

        return _guard(_run)

    async def archive_mods(self, zip_path: str):
        """Round 84: list every mod root inside one archive. No writes.

        An archive that ships several mods used to be a dead end: install()
        answered E_MULTI_MOD_ARCHIVE ("import them one at a time") while Game
        Mode has no file manager, so the user was asked to do something the
        plugin gave them no way to do. This call makes the archive itself the
        picker: it names each mod root, and install(member_root=...) then
        installs exactly one of them.

        Read-only by construction: it resolves the path, refuses anything
        outside an import root, and never touches the mods folder.
        """
        def _run():
            engine = self._engine()
            if not getattr(engine, "SUPPORTS_ARCHIVE_MODS", False):
                return err("E_CAPABILITY_DISABLED",
                           detail="[archive_mods] this engine installs the whole "
                                  "archive, so there is no mod root to pick",
                           data={"reason": "no_archive_mods"})
            return engine.archive_mods(str(zip_path or ""))
        return _guard(_run)

    async def history(self, limit: int = 50):
        return _guard(lambda: self._engine().history(int(limit)))

    async def refresh(self):
        """Re-resolve paths + verify_on_open drift check (§5.1 op #11)."""
        return _guard(lambda: self._engine().refresh())

    async def recovery(self):
        """List unfinished transactions (PREPARED/APPLYING)."""
        return _guard(lambda: self._engine().recovery())

    async def error_codes(self):
        """Expose the full E_* table to the frontend (one code = one message).
        Useful for i18n and for the acceptance checklist; read-only.
        """
        def _run():
            rows = [
                {"code": c, "category": v[0], "message": v[1], "rollback_available": v[2]}
                for c, v in sorted(ERRORS.items())
            ]
            return ok({"codes": rows, "count": len(rows)})
        return _guard(_run)

    # ------------------------------------------------------------------ write RPCs
    async def install(self, zip_path: str, after_confirm: bool = False, fomod_choices=None,
                      member_root=None):
        """Two-phase: after_confirm=False -> dry-run/confirm payload (no writes);
        after_confirm=True -> execute. Positional args match call()/callable().

        Round 28 (criterion 3): ``fomod_choices`` is an optional JSON-safe dict
        mapping ``"<step>.<group>"`` to selected option name(s). Omitting it keeps
        the old call signature working and simply means "no FOMOD override".

        Round 84: ``member_root`` names ONE mod root inside an archive that holds
        several (see ``archive_mods``). Empty string means "the archive root"
        and is distinct from None, which means "the archive holds exactly one
        mod, use it". Only the file_drop engine can honour it.
        """
        def _run():
            _progress("install:start", op="install", package_id="")
            engine = self._engine()
            want_fomod = isinstance(fomod_choices, dict) and bool(fomod_choices)
            want_root = isinstance(member_root, str)
            # Round 86: ask the engine, do not guess. The old probe
            # (hasattr(engine, "_set_enabled_inner")) is inherited by every
            # engine, so it answered "yes, send the extra kwargs" for root_merge
            # and the mismatch surfaced as E_UNKNOWN instead of an explanation.
            # An engine that cannot honour an argument says so here, before the
            # call, with a reason the UI can translate.
            if want_fomod and not getattr(engine, "SUPPORTS_FOMOD", False):
                return err("E_CAPABILITY_DISABLED",
                           detail="[install] this engine has no FOMOD installer",
                           data={"reason": "no_fomod"})
            if want_root and not getattr(engine, "SUPPORTS_MEMBER_ROOT", False):
                return err("E_CAPABILITY_DISABLED",
                           detail="[install] this engine installs the whole "
                                  "archive: it has no member-root selection",
                           data={"reason": "no_member_root"})
            # Keep the RimWorld Engine call byte-identical when neither applies.
            if want_fomod or want_root:
                extra = {}
                if want_fomod:
                    extra["fomod_choices"] = fomod_choices
                if want_root:
                    extra["member_root"] = member_root
                r = engine.install(zip_path, after_confirm=bool(after_confirm), **extra)
            else:
                r = engine.install(zip_path, after_confirm=bool(after_confirm))
            _progress("install:done", op="install", package_id=(r.get("data") or {}).get("packageId", "")
                      if isinstance(r.get("data"), dict) else "", pct=100 if r.get("ok") else 0)
            return r
        return _guard(_run)

    async def delete_zip_source(self, zip_path: str):
        """Delete the source ZIP of an already-committed install (round 80).

        Opt-in by design: the frontend only calls this after a successful
        install, behind a separate "install and delete the ZIP" action —
        never as an automatic side effect, because a deleted source cannot be
        restored from the journal. The backend still refuses anything outside
        a declared import root, so this can never become a general file
        deleter.
        """
        def _run():
            engine = self._engine()
            if not hasattr(engine, "delete_source_zip"):
                return err("E_CAPABILITY_DISABLED",
                           detail="[delete_zip_source] this engine has no "
                                  "source-ZIP path",
                           data={"reason": "no_source_zip"})
            return engine.delete_source_zip(str(zip_path or ""))
        return _guard(_run)

    async def set_enabled(self, package_id: str, enabled: bool, after_confirm: bool = False):
        def _run():
            _progress("enable:start", op="set_enabled", package_id=package_id)
            r = self._engine().set_enabled(package_id, bool(enabled), after_confirm=bool(after_confirm))
            _progress("enable:done", op="set_enabled", package_id=package_id, pct=100 if r.get("ok") else 0)
            return r
        return _guard(_run)

    async def uninstall(self, package_id: str, after_confirm: bool = False):
        def _run():
            _progress("uninstall:start", op="uninstall", package_id=package_id)
            r = self._engine().uninstall(package_id, after_confirm=bool(after_confirm))
            _progress("uninstall:done", op="uninstall", package_id=package_id, pct=100 if r.get("ok") else 0)
            return r
        return _guard(_run)

    async def rollback(self, txn: str):
        def _run():
            _progress("rollback:start", op="rollback")
            r = self._engine().rollback(txn)
            _progress("rollback:done", op="rollback", pct=100 if r.get("ok") else 0)
            return r
        return _guard(_run)

    async def reclaim_quarantine(self, txns: list, after_confirm: bool):
        """Delete quarantine folders the journal can no longer restore.

        Round 54. ``status().state.quarantine`` has been telling the user that
        N folders are unreachable since Round 48, and there was no way to act on
        it. The ids are positional here for the same reason every other RPC
        uses positional args, and the confirmation is a real second call
        because deleting is not undoable.

        Deliberately an explicit list, never "all of them": the caller must say
        which folders, so a bug in a UI loop cannot empty the quarantine. The
        engine re-checks every id against a fresh survey and refuses
        ``restorable`` and ``unknown`` ones by name.
        """
        def _run():
            _progress("reclaim:start", op="reclaim")
            r = self._engine().reclaim_quarantine(txns, after_confirm=bool(after_confirm))
            _progress("reclaim:done", op="reclaim", pct=100 if r.get("ok") else 0)
            return r
        return _guard(_run)

    async def handover_mods(self, after_confirm: bool):
        """Take ownership of ``Mods/`` away from another mod manager (Round 55).

        ``status().state.read_only`` has been telling the user that somebody
        else owns the folder since Round 44, and the panel offered no way
        forward, so "read-only" read as "broken". This is the exit, and it is
        deliberately the narrowest one available:

        * it moves symlinked entries and marker FILES into the quarantine under
          one journal transaction, so ``rollback`` restores them;
        * it refuses as a whole -- moving nothing -- when the obstacle is a
          symlinked ``Mods/``, a marker directory beside the game, or a folder
          on another filesystem, because those cannot be undone in one step;
        * the confirmation is a real second call, and nothing is ever deleted.

        This is the one write path that does not consult the external-manager
        gate, because that gate is exactly what it exists to clear.
        """
        def _run():
            _progress("handover:start", op="handover")
            r = self._engine().handover_mods(after_confirm=bool(after_confirm))
            _progress("handover:done", op="handover", pct=100 if r.get("ok") else 0)
            return r
        return _guard(_run)

    # ------------------------------------------------------- download RPCs (round 19)
    # Four positional-args async methods, each returning the SAME JSON-safe
    # Envelope via _guard. No credentials exist any more: every request is an
    # anonymous https call to an allow-listed host (api.github.com for search and
    # release metadata; the GitHub asset hosts for the actual bytes). The final
    # write is always the engine's install(), whose E_EXTERNAL_MANAGER verdict is
    # propagated unchanged.
    async def gh_search(self, query: str, page: int):
        """Search GitHub repositories (stars-desc). Read-only, no credentials."""
        def _run():
            gated = _network_download_gate()
            if gated is not None:
                return gated
            cfg = _source_cfg("github")
            if cfg and not cfg.get("enabled", True):
                return err("E_CAPABILITY_DISABLED",
                           detail="[gh_search] github source disabled",
                           data={"reason": "source_disabled",
                                 "source": "github"})
            res = github_source.search_repos(download.default_opener, str(query), int(page))
            return _core_to_envelope(res, auto_import.DL_TO_E, "gh_search")
        return _guard(_run)

    async def gh_releases(self, owner: str, repo: str):
        """List up to 5 releases (with slimmed assets) for one repository."""
        def _run():
            gated = _network_download_gate()
            if gated is not None:
                return gated
            cfg = _source_cfg("github")
            if cfg and not cfg.get("enabled", True):
                return err("E_CAPABILITY_DISABLED",
                           detail="[gh_releases] github source disabled",
                           data={"reason": "source_disabled",
                                 "source": "github"})
            res = github_source.list_releases(download.default_opener, str(owner), str(repo))
            return _core_to_envelope(res, auto_import.DL_TO_E, "gh_releases")
        return _guard(_run)

    async def gh_download(self, owner: str, repo: str, asset_id: int,
                          filename: str, allow_install: bool, after_confirm: bool):
        """Resolve a release asset to its signed URL, download it, TRI-STATE install.

        The asset id is resolved through the API (302 -> allow-listed asset host)
        and the bytes are then fetched with that host pinned, so a redirected
        download can never leave the allow-list. Phases and the install gate are
        identical to every other download path.
        """
        def _run():
            gated = _network_download_gate()
            if gated is not None:
                return gated
            cfg = _source_cfg("github")
            if cfg and not cfg.get("enabled", True):
                return err("E_CAPABILITY_DISABLED",
                           detail="[gh_download] github source disabled",
                           data={"reason": "source_disabled",
                                 "source": "github"})
            _progress("gh_download:start", op="gh_download", package_id=str(filename))
            resolved = github_source.resolve_asset(
                download.default_opener, str(owner), str(repo), int(asset_id))
            if not resolved.get("ok"):
                _progress("gh_download:done", op="gh_download",
                          package_id=str(filename), pct=0)
                return _core_to_envelope(resolved, auto_import.DL_TO_E, "gh_download")
            url = resolved.get("url")
            if not isinstance(url, str) or not url:
                return err("E_INBOX_UNREADABLE", detail="[gh_download] no asset URL resolved")
            # Criterion 4 asks for size/hash verification before install. Ask the
            # API what the asset is SUPPOSED to be, then let the downloader refuse
            # anything that does not match. GitHub reports digest=null for these
            # assets, so a hash can only be checked when the source actually
            # declares one — we never fabricate an "all verified" claim.
            want_size = None
            want_hash = None
            meta = github_source.asset_metadata(
                download.default_opener, str(owner), str(repo), int(asset_id))
            if meta.get("ok"):
                if isinstance(meta.get("size"), int):
                    want_size = int(meta["size"])
                if isinstance(meta.get("sha256"), str):
                    want_hash = str(meta["sha256"])
            r = auto_import.download_and_import(
                download.default_opener, self._engine(),
                url=url, filename=str(filename),
                allow_install=bool(allow_install), after_confirm=bool(after_confirm),
                allowed_hosts=github_source.ASSET_HOSTS,
                expected_size=want_size, expected_sha256=want_hash)
            _progress("gh_download:done", op="gh_download", package_id=str(filename),
                      pct=100 if r.get("ok") else 0)
            return r
        return _guard(_run)

    async def download_url(self, url: str, filename: str,
                           allow_install: bool, after_confirm: bool):
        """Download a user-supplied https URL into the inbox, TRI-STATE gated.

        This is the escape hatch for mods that publish outside GitHub. The URL is
        validated (https, no userinfo, default port, no private literal host) and
        the bytes still land in the inbox only; the game's Mods folder is written
        exclusively by the engine's install().
        """
        def _run():
            gated = _network_download_gate()
            if gated is not None:
                return gated
            cfg = _source_cfg("direct")
            if not cfg.get("enabled", False):
                return err("E_CAPABILITY_DISABLED",
                           detail="[download_url] direct source disabled",
                           data={"reason": "source_disabled",
                                 "source": "direct"})
            # _validate_download_url raises DownloadError; convert it HERE so the
            # specific NX code survives. _guard would flatten it to E_UNKNOWN.
            try:
                github_source._validate_download_url(str(url))
            except download.DownloadError as e:
                return _core_to_envelope(
                    download._fail(e.code, detail=e.detail), auto_import.DL_TO_E, "download_url")
            _progress("download_url:start", op="download_url", package_id=str(filename))
            r = auto_import.download_and_import(
                download.default_opener, self._engine(),
                url=str(url), filename=str(filename),
                allow_install=bool(allow_install), after_confirm=bool(after_confirm))
            _progress("download_url:done", op="download_url", package_id=str(filename),
                      pct=100 if r.get("ok") else 0)
            return r
        return _guard(_run)

    async def fetch_dependencies(self, allow_install: bool, after_confirm: bool):
        """Fetch the required dependencies the installed game is missing.

        Round 38: SMAPI will not load a mod whose required dependencies are
        absent, so a successful-looking install can still be skipped by the
        game. This resolves what is missing, fetches it, and accepts a
        downloaded file ONLY when the manifest inside names the same UniqueID —
        a filename is not evidence (one repo publishes several mods).

        The same TRI-STATE gate as every other download: False/False plans and
        writes nothing; True/False returns the confirmation sentence and still
        writes nothing; True/True downloads and installs, and each dependency
        that cannot be obtained is reported with a reason instead of being
        silently skipped.
        """
        def _run():
            gated = _network_download_gate()
            if gated is not None:
                return gated
            eng = self._engine()
            # Where is "missing" defined? By the engine that owns the game, so a
            # game whose descriptor has no such concept simply reports none.
            try:
                st = eng.status()
                state = (st.get("data") or {}).get("state") or {}
                missing = list(state.get("missing_dependencies") or [])
            except Exception as e:
                return err("E_UNKNOWN", detail="[fetch_dependencies] status failed: %s: %s"
                           % (type(e).__name__, e))
            if not missing:
                return ok({"phase": "none", "deps": [], "fetchable": 0,
                           "total": 0, "installed": 0, "attempted": 0,
                           "install_allowed": bool(allow_install),
                           "note": "no required dependency is missing"})
            _progress("fetch_dependencies:start", op="fetch_dependencies", package_id="")
            res = deps.run(
                download.default_opener, eng, missing_ids=missing,
                allow_install=bool(allow_install),
                after_confirm=bool(after_confirm))
            _progress("fetch_dependencies:done", op="fetch_dependencies", package_id="",
                      pct=100 if res.get("ok") else 0)
            return _core_to_envelope(res, auto_import.DL_TO_E, "fetch_dependencies")
        return _guard(_run)

    # ------------------------------------------------------ Nexus browse links

    def _nexus_browse_domain(self):
        """The Nexus SITE domain for the three website-page openers.

        Round 78 fix: ``open_mod_page`` / ``open_search_page`` /
        ``open_browse_page`` never need an API key — they hand a URL to the
        signed-in browser. Requiring the ``nexus_metadata`` block (the API
        shape) meant a descriptor that declares only the browse-only
        ``nexus_game_domain`` (Cyberpunk 2077) answered E_CAPABILITY_DISABLED
        for pages the browser could perfectly well open. Both shapes are now
        honoured, ``nexus_metadata`` first.

        Round 88: the API RPCs that used to read a domain here
        (nexus_recent / nexus_mod / nexus_download_link / nexus_validate /
        check_mod_updates) are gone along with the key storage. This is now
        the only reader of a Nexus domain, and nothing here needs a key.
        """
        try:
            _, desc = Registry().active_descriptor()
        except Exception:
            return None
        sources = desc.get("download_sources") or {}
        nm = sources.get("nexus_metadata")
        if isinstance(nm, dict) and nm.get("enabled", False):
            domain = str(nm.get("game_domain") or "").strip()
            if domain:
                return domain
        # Browse-only alias: a plain string domain (cyberpunk.json shape).
        domain = sources.get("nexus_game_domain")
        if isinstance(domain, str) and domain.strip():
            return domain.strip()
        return None

    async def open_mod_page(self, mod_id: int):
        """Put a mod's page on the screen the user is looking at.

        Goal item 2 asks to reach a download page from inside the panel. The
        Nexus API will not hand a free account a download link (measured: 403
        "this is for premium users only"), so the only honest route is to open
        the real page and let the signed-in browser session do the download --
        after which the ZIP is imported through the normal inbox path.

        Two deliberate choices:

        * the caller passes an INTEGER, never a URL. The address is built here
          from the descriptor's ``game_domain``, so there is no string a caller
          could use to make the client display an arbitrary page;
        * no ``_network_download_gate()``. Nothing is downloaded and no request
          leaves the device: this hands a URI to a process that is already
          running and already has network access of its own. Gating it would
          mean "viewing a page is a download", which is not true.

        Round 78: reads the browse domain (``_nexus_browse_domain``), so a
        game that declares only ``nexus_game_domain`` still opens its pages.
        """
        def _run():
            domain = self._nexus_browse_domain()
            if domain is None:
                return err("E_CAPABILITY_DISABLED",
                           detail="[open_mod_page] no Nexus domain declared "
                           "for this game (download_sources)",
                           data={"reason": "no_nexus_domain"})
            try:
                mid = int(mod_id)
            except (TypeError, ValueError):
                return err("E_PATH_INVALID",
                           detail="[open_mod_page] mod_id must be a number")
            if mid <= 0:
                return err("E_PATH_INVALID",
                           detail="[open_mod_page] mod_id must be positive")
            url = nexus.mod_page_url(domain, mid)
            got = openurl.open_url(url)
            if not got.get("ok"):
                # Honest failure: the page did NOT appear. Returning ok here
                # would make the user hunt for a window that was never opened.
                return err("E_CAPABILITY_DISABLED",
                           detail="[open_mod_page] %s: %s" % (
                               got.get("reason"), got.get("detail") or ""),
                           data={"url": url, "reason": "open_failed",
                                 "why": got.get("reason")})
            _progress("open_mod_page:done")
            return ok({"url": url, "opened": True})
        return _guard(_run)

    async def open_search_page(self, query: str):
        """Run a keyword search where search actually exists: the website.

        Goal item 2 asks for keyword search. The API cannot do it -- measured:
        ``/games/{d}/mods/search.json?search=SMAPI`` answers 422 because the
        router reads ``search`` as a mod id, and ``q=``, ``game_id=`` and
        ``/v2/search.json`` are all 404. Every website page is behind a
        Cloudflare challenge, so scraping is not a fallback either.

        What IS true: the website has a working search page. Rather than
        pretend to search or return an empty list, this opens that page with
        the keyword already applied. The user sees real results, in the
        browser they are already signed in to.

        Same two properties as ``open_mod_page``: the caller supplies only the
        keyword (the address is built here from ``game_domain``), and no
        ``_network_download_gate()`` applies because nothing is downloaded.

        Round 78: reads the browse domain (``_nexus_browse_domain``).
        """
        def _run():
            domain = self._nexus_browse_domain()
            if domain is None:
                return err("E_CAPABILITY_DISABLED",
                           detail="[open_search_page] no Nexus domain declared "
                           "for this game (download_sources)",
                           data={"reason": "no_nexus_domain"})
            text, problem = nexus.clean_query(query)
            if problem is not None:
                return err("E_PATH_INVALID",
                           detail="[open_search_page] %s" % problem)
            url = nexus.search_page_url(domain, text)
            got = openurl.open_url(url)
            if not got.get("ok"):
                return err("E_CAPABILITY_DISABLED",
                           detail="[open_search_page] %s: %s" % (
                               got.get("reason"), got.get("detail") or ""),
                           data={"url": url, "query": text,
                                 "reason": "open_failed",
                                 "why": got.get("reason")})
            _progress("open_search_page:done")
            return ok({"url": url, "query": text, "opened": True})
        return _guard(_run)

    async def open_browse_page(self, sort: str):
        """Open the website's Trending / Newest / Updated listing — NO API key.

        The API's recent() needs a personal key that a free account may not
        have configured. The website already shows these sorts to a signed-in
        browser, so this is the honest no-key way to deliver "热门/最新/更新". The
        caller passes one of the sort KEYS (trending/latest_added/latest_updated), never
        a URL: the address is built here from the descriptor's game_domain.

        Round 78: reads the browse domain (``_nexus_browse_domain``) — the
        Cyberpunk 2077 descriptor declares ``nexus_game_domain`` (browse only)
        and used to be refused here for no good reason.
        """
        def _run():
            domain = self._nexus_browse_domain()
            if domain is None:
                return err("E_CAPABILITY_DISABLED",
                           detail="[open_browse_page] no Nexus domain declared "
                           "for this game (download_sources)",
                           data={"reason": "no_nexus_domain"})
            url = nexus.browse_page_url(domain, sort)
            if url is None:
                return err("E_PATH_INVALID",
                           detail="[open_browse_page] unknown sort: %r" % sort)
            got = openurl.open_url(url)
            if not got.get("ok"):
                return err("E_CAPABILITY_DISABLED",
                           detail="[open_browse_page] %s: %s" % (
                               got.get("reason"), got.get("detail") or ""),
                           data={"url": url, "reason": "open_failed",
                                 "why": got.get("reason")})
            _progress("open_browse_page:done")
            return ok({"url": url, "sort": sort, "opened": True})
        return _guard(_run)
