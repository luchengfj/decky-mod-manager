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
from deckymod.envelope import err, ok
from deckymod.errors import ERRORS
from deckymod.registry import Registry
# Downloads come from GitHub Releases (the one source that works on this device)
# plus a plain https URL fallback. deckymod.download is the shared low-level
# https/JSON/download layer. No credential is stored or read by the plugin.
from deckymod import auto_import
from deckymod import credentials
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
    """
    try:
        result = fn(*args, **kwargs)
        return result
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
                          % (type(e).__name__, e))
    caps = desc.get("capabilities", {}) if isinstance(desc, dict) else {}
    if not caps.get("network_download", False):
        return err("E_CAPABILITY_DISABLED",
                   detail="[network_download] capability=false for %s" % gid)
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

    async def inspect(self, zip_path: str):
        """Dry-run inspection of ONE local ZIP. No writes."""
        return _guard(lambda: self._engine().inspect(zip_path))

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
    async def install(self, zip_path: str, after_confirm: bool = False, fomod_choices=None):
        """Two-phase: after_confirm=False -> dry-run/confirm payload (no writes);
        after_confirm=True -> execute. Positional args match call()/callable().

        Round 28 (criterion 3): ``fomod_choices`` is an optional JSON-safe dict
        mapping ``"<step>.<group>"`` to selected option name(s). Omitting it keeps
        the old call signature working and simply means "no FOMOD override".
        """
        def _run():
            _progress("install:start", op="install", package_id="")
            engine = self._engine()
            # Only the file_drop engine understands FOMOD; keep the RimWorld
            # Engine call byte-identical when no choices are supplied.
            if isinstance(fomod_choices, dict) and fomod_choices and hasattr(engine, "_set_enabled_inner"):
                r = engine.install(zip_path, after_confirm=bool(after_confirm),
                                   fomod_choices=fomod_choices)
            else:
                r = engine.install(zip_path, after_confirm=bool(after_confirm))
            _progress("install:done", op="install", package_id=(r.get("data") or {}).get("packageId", "")
                      if isinstance(r.get("data"), dict) else "", pct=100 if r.get("ok") else 0)
            return r
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
                return err("E_CAPABILITY_DISABLED", detail="[gh_search] github source disabled")
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
                return err("E_CAPABILITY_DISABLED", detail="[gh_releases] github source disabled")
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
                return err("E_CAPABILITY_DISABLED", detail="[gh_download] github source disabled")
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
                return err("E_CAPABILITY_DISABLED", detail="[download_url] direct source disabled")
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

    # ---------------------------------------------------------- Nexus credentials
    #
    # Design notes that are load-bearing:
    #
    # * ``nexus_validate`` takes NO argument. It reads the key from disk itself,
    #   so after ``set_api_key`` the secret never crosses the bridge again. A
    #   validate(key) signature would force the frontend to hold the plaintext
    #   for the lifetime of the panel.
    # * No RPC returns the key. Not masked, not truncated, not its length alone
    #   in combination with anything else — ``key_status`` is stat-only.
    # * These are NOT gated by ``_network_download_gate``: storing a credential
    #   is local, and gating it would make the key impossible to enter before a
    #   descriptor opts into downloads. The network calls themselves ARE gated.

    async def api_key_status(self):
        """Report whether a key is stored and whether its file mode is private."""
        def _run():
            try:
                return ok(credentials.key_status())
            except Exception as e:  # noqa: BLE001 - a stat failure must not raise
                return err("E_ACCESS", detail="[api_key_status] %s: %s"
                           % (type(e).__name__, e))
        return _guard(_run)

    async def set_api_key(self, api_key: str):
        """Store the key at mode 0600. Returns metadata, never the value."""
        def _run():
            try:
                info = credentials.save_key(str(api_key or ""))
            except ValueError as e:
                return err("E_CAPABILITY_DISABLED", detail="[set_api_key] %s" % e)
            except PermissionError as e:
                return err("E_ACCESS", detail="[set_api_key] %s" % e)
            except OSError as e:
                return err("E_ACCESS", detail="[set_api_key] %s: %s"
                           % (type(e).__name__, e.strerror or e))
            _progress("api_key:set")
            return ok(info)
        return _guard(_run)

    async def delete_api_key(self):
        """Remove the stored key. Honest when there was nothing to remove."""
        def _run():
            try:
                info = credentials.delete_key()
            except PermissionError as e:
                return err("E_ACCESS", detail="[delete_api_key] %s" % e)
            except OSError as e:
                return err("E_ACCESS", detail="[delete_api_key] %s: %s"
                           % (type(e).__name__, e.strerror or e))
            _progress("api_key:delete")
            return ok(info)
        return _guard(_run)

    async def nexus_validate(self):
        """Check the stored key against api.nexusmods.com.

        Three outcomes the UI must keep distinct, because they have different
        fixes: no key stored, key stored but rejected, key works (free or
        premium). ``is_premium`` matters: it is the difference between "this
        feature exists" and "this feature will always answer 403".
        """
        def _run():
            gated = _network_download_gate()
            if gated is not None:
                return gated
            try:
                api_key = credentials.read_key()
            except (OSError, ValueError) as e:
                return err("E_CAPABILITY_DISABLED",
                           detail="[nexus_validate] no usable stored key: %s" % e,
                           data={"configured": False,
                                 "hint": "enter your Nexus API key in this panel first"})
            res = nexus.validate(download.default_opener, api_key)
            if not res.get("ok"):
                problem = nexus.key_problem(res)
                return err("E_CAPABILITY_DISABLED",
                           detail="[nexus_validate] %s" % problem,
                           data={"configured": True, "problem": problem,
                                 "status": res.get("status"),
                                 "server_message": res.get("detail")})
            _progress("nexus_validate:done")
            return ok(res)
        return _guard(_run)

    # ------------------------------------------------------------ Nexus metadata

    def _nexus_domain(self):
        """The game's Nexus domain, from the descriptor — never hard-coded here."""
        cfg = _source_cfg("nexus_metadata")
        if not cfg.get("enabled", False):
            return None
        domain = str(cfg.get("game_domain") or "").strip()
        return domain or None

    def _nexus_key(self):
        try:
            return credentials.read_key(), None
        except (OSError, ValueError) as e:
            return None, err("E_CAPABILITY_DISABLED",
                             detail="[nexus] no usable stored key: %s" % e,
                             data={"configured": False,
                                   "hint": "enter your Nexus API key in this panel first"})

    async def nexus_recent(self, kind: str):
        """Browse a game's latest/trending mods — the only listing the API has.

        There is deliberately no ``nexus_search``: the endpoint does not exist.
        Offering a search box would be promising something the API cannot do.
        """
        def _run():
            gated = _network_download_gate()
            if gated is not None:
                return gated
            domain = self._nexus_domain()
            if domain is None:
                return err("E_CAPABILITY_DISABLED",
                           detail="[nexus_recent] nexus_metadata source disabled")
            api_key, bad = self._nexus_key()
            if bad is not None:
                return bad
            res = nexus.recent(download.default_opener, domain, str(kind), api_key)
            return _core_to_envelope(res, auto_import.DL_TO_E, "nexus_recent")
        return _guard(_run)

    async def nexus_mod(self, mod_id: int):
        """One mod's details plus its file list, and the page URL to download from."""
        def _run():
            gated = _network_download_gate()
            if gated is not None:
                return gated
            domain = self._nexus_domain()
            if domain is None:
                return err("E_CAPABILITY_DISABLED",
                           detail="[nexus_mod] nexus_metadata source disabled")
            api_key, bad = self._nexus_key()
            if bad is not None:
                return bad
            try:
                mid = int(mod_id)
            except (TypeError, ValueError):
                return err("E_PATH_INVALID", detail="[nexus_mod] mod_id must be a number")
            info = nexus.mod_info(download.default_opener, domain, mid, api_key)
            if not info.get("ok"):
                return _core_to_envelope(info, auto_import.DL_TO_E, "nexus_mod")
            files = nexus.mod_files(download.default_opener, domain, mid, api_key)
            payload = {
                "mod_id": mid,
                "browser_url": nexus.mod_page_url(domain, mid),
                "info": info.get("data"),
                "files": (files.get("files") if files.get("ok") else []),
                "files_error": None if files.get("ok") else files.get("code"),
            }
            return ok(payload)
        return _guard(_run)

    async def nexus_download_link(self, mod_id: int, file_id: int):
        """Ask for a download link — and report honestly when the tier forbids it.

        Kept as an RPC rather than folded into ``nexus_mod`` because the answer
        for a free account is a refusal, and a refusal deserves its own code
        path (and its own browser_url) instead of looking like a broken mod.
        """
        def _run():
            gated = _network_download_gate()
            if gated is not None:
                return gated
            domain = self._nexus_domain()
            if domain is None:
                return err("E_CAPABILITY_DISABLED",
                           detail="[nexus_download_link] nexus_metadata source disabled")
            api_key, bad = self._nexus_key()
            if bad is not None:
                return bad
            try:
                mid, fid = int(mod_id), int(file_id)
            except (TypeError, ValueError):
                return err("E_PATH_INVALID",
                           detail="[nexus_download_link] mod_id and file_id must be numbers")
            res = nexus.download_link(download.default_opener, domain, mid, fid, api_key)
            return _core_to_envelope(res, auto_import.DL_TO_E, "nexus_download_link")
        return _guard(_run)

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
        """
        def _run():
            domain = self._nexus_domain()
            if domain is None:
                return err("E_CAPABILITY_DISABLED",
                           detail="[open_mod_page] nexus_metadata source disabled")
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
                           data={"url": url, "reason": got.get("reason")})
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
        """
        def _run():
            domain = self._nexus_domain()
            if domain is None:
                return err("E_CAPABILITY_DISABLED",
                           detail="[open_search_page] nexus_metadata source disabled")
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
                                 "reason": got.get("reason")})
            _progress("open_search_page:done")
            return ok({"url": url, "query": text, "opened": True})
        return _guard(_run)
