/**
 * Typed bridge to the Python backend (§1: call / callable / emit).
 *
 * All backend methods are exposed on `main.py::Plugin` as public async methods.
 * The Decky loader dispatches `call(method, ...args)` to them via getattr, so
 * ARGUMENTS ARE POSITIONAL — never pass an object as a single arg.
 *
 * Modern `@decky/api` (V2/V3 confirmed on device 2026-11-12 against the
 * LOCKED @decky/api 1.1.3 / @decky/ui 4.16.5):
 *   call<Args, Return>(method, ...args)      request/response (Args = arg tuple)
 *   callable<Args, Ret>(name)                typed handle (see callableHandles)
 *   addEventListener/removeEventListener     server->client events (emit)
 *   toaster / definePlugin / routerHook      used in index.tsx
 *
 * JSON-safe: `call` resolves to the envelope object (plain JSON). We NEVER
 * construct Path/bytes/set here. If the bridge itself throws (backend not
 * loaded / plugin reloading), we synthesize an E_BACKEND_UNREACHABLE envelope
 * instead of letting a raw exception reach the UI.
 */

import { call, callable } from "@decky/api";
import { errorText, reasonText } from "./i18n";
import type {
  Envelope,
  StatusData,
  InboxData,
  InspectData,
  ArchiveModsData,
  HistoryData,
  RecoveryData,
  ErrorCodesData,
  OpEnvelope,
  ConfirmData,
  OpResultData,
  GhSearchData,
  GhReleasesData,
  SteamLibData,
  SwitchGameData,
  GameSetupData,
  OpenModPageData,
  SearchPageData,
  BrowsePageData,
  HandoverData,
  ReclaimData,
} from "./types";

export const PROGRESS_EVENT = "deckymod:progress";

/** Synthesized error envelopes for bridge-level failures (never a traceback). */
export function bridgeError(detail: string): Envelope<never> {
  return {
    ok: false,
    code: "E_BACKEND_UNREACHABLE",
    message: errorText("E_BACKEND_UNREACHABLE",
      "Backend is not reachable. Reopen the plugin or restart the Steam Deck."),
    detail,
    data: null,
    rollback_available: false,
    log_path: "",
    ts: new Date().toISOString(),
  };
}

/** One guarded call. Any thrown bridge error becomes a stable envelope. */
async function invoke<T>(method: string, ...args: unknown[]): Promise<Envelope<T>> {
  try {
    // @decky/api 1.1.3: call<Args extends any[], Return>(route, ...args).
    // The FIRST generic is the argument tuple, the SECOND is the return type.
    const r = await call<unknown[], Envelope<T>>(method, ...args);
    // Defensive: if the backend somehow returned a non-envelope, normalize it.
    if (r && typeof r === "object" && typeof (r as Envelope<T>).ok === "boolean") {
      return r as Envelope<T>;
    }
    return bridgeError(`malformed response from ${method}`);
  } catch (e) {
    return bridgeError(`${method} failed: ${e instanceof Error ? e.message : String(e)}`);
  }
}

/* ------------------------------------------------------------------ read RPCs */
export const getStatus = () => invoke<StatusData>("status");
/**
 * Goal item 2: every Steam library (internal + SD card) and the games in it.
 * Read-only on the backend — it only stats manifests, never writes.
 */
export const listGames = () => invoke<SteamLibData>("list_games");

/** Round 76: point the panel at another supported game (one active at a time). */
export const switchGame = (gameId: string) =>
  invoke<SwitchGameData>("switch_game", gameId);

/** Round 77: candidate mod folders for a game with no built-in descriptor. */
export const gameSetup = (appid: number) => invoke<GameSetupData>("game_setup", appid);
export const configureGame = (appid: number, name: string, writeRoots: string[]) =>
  invoke<{ appid: number; write_roots: string[] }>("configure_game", appid, name, writeRoots);
export const forgetGame = (appid: number) =>
  invoke<{ appid: number; deleted: boolean }>("forget_game", appid);

/**
 * Round 79: loader hand-off (user-approved red-line change, scoped to
 * user-configured games). `openLoaderPage` hands the catalog's official page
 * to the browser; `installLoader` extracts the ZIP the user downloaded into
 * the game's loader root — two-phase, journaled, backed up, rollback-able.
 * Built-in games answer E_CAPABILITY_DISABLED.
 */
export const openLoaderPage = (loaderId: string) =>
  invoke<{ url: string; loader: string; opened: boolean }>("open_loader_page", loaderId);
export const installLoader = (zipPath: string, afterConfirm: boolean) =>
  invoke<ConfirmData | OpResultData>("install_loader", zipPath, afterConfirm) as Promise<OpEnvelope>;

/**
 * Round 80: delete the source ZIP of an already-committed install. Opt-in —
 * the panel only calls this behind an explicit "install and delete" action,
 * and the backend refuses anything outside a declared import root.
 */
export const deleteZipSource = (zipPath: string) =>
  invoke<{ removed: string }>("delete_zip_source", zipPath);
export const listInbox = () => invoke<InboxData>("list_inbox");
export const inspectZip = (zipPath: string, memberRoot?: string | null) =>
  invoke<InspectData>("inspect", zipPath, typeof memberRoot === "string" ? memberRoot : null);
/**
 * Round 84: list every mod root inside one archive. Read-only.
 *
 * An archive that ships several mods used to be a dead end — install() answered
 * E_MULTI_MOD_ARCHIVE ("import them one at a time") while Game Mode has no file
 * manager. This names each root so the panel can let the user pick one.
 */
export const archiveMods = (zipPath: string) =>
  invoke<ArchiveModsData>("archive_mods", zipPath);
export const getHistory = (limit = 50) => invoke<HistoryData>("history", limit);
export const refreshStatus = () => invoke<StatusData>("refresh");
export const getRecovery = () => invoke<RecoveryData>("recovery");
export const getErrorCodes = () => invoke<ErrorCodesData>("error_codes");

/* ------------------------------------------------------------------ write RPCs
 * Two-phase ops: pass afterConfirm=false for the dry-run/confirm payload,
 * then afterConfirm=true to commit. The backend NEVER writes during phase 1.
 */
/**
 * Round 28: `fomodChoices` is optional. It maps "<step>.<group>" to selected
 * option name(s) for archives carrying fomod/moduleconfig.xml. Omitting it (or
 * passing null) means "no override -> plain extract"; the backend treats an
 * empty/null map as falsy, so all existing 2-arg call sites stay safe.
 *
 * Round 84: `memberRoot` is optional and names ONE mod root inside an archive
 * that holds several (see `archiveMods`). Empty string means "the archive
 * root" and is deliberately distinct from undefined, which means "the archive
 * holds exactly one mod, use it". Passing it implies the user has chosen.
 */
export const installMod = (
  zipPath: string,
  afterConfirm: boolean,
  fomodChoices?: Record<string, string[]> | null,
  memberRoot?: string | null,
) =>
  invoke<ConfirmData | OpResultData>(
    "install", zipPath, afterConfirm, fomodChoices ?? null,
    typeof memberRoot === "string" ? memberRoot : null,
  ) as Promise<OpEnvelope>;

/*
 * selection B (Stardew/SMAPI): `packageId` is the SHARED wire identity key —
 * RimWorld uses About.xml packageId, SMAPI uses manifest.json UniqueID. Both
 * engines expose the SAME 11 positional RPCs, so the call signatures are
 * identical and the backend maps the key internally (deckymod/smapi.py).
 * For file_drop, set_enabled is gated off (install == enable); the UI hides
 * the toggle button rather than calling this with an unsupported capability.
 */
export const setModEnabled = (uniqueId: string, enabled: boolean, afterConfirm: boolean) =>
  invoke<ConfirmData | OpResultData>("set_enabled", uniqueId, enabled, afterConfirm) as Promise<OpEnvelope>;

export const uninstallMod = (uniqueId: string, afterConfirm: boolean) =>
  invoke<ConfirmData | OpResultData>("uninstall", uniqueId, afterConfirm) as Promise<OpEnvelope>;

export const rollbackTxn = (txn: string) =>
  invoke<OpResultData>("rollback", txn);

/* ------------------------------------------------------------------ round 19: download sources
 * FOUR positional-args RPCs replacing the retired Download surface. All return the
 * standard JSON-safe Envelope. The backend owns ALL HTTPS; the frontend never
 * performs network I/O itself (Steam CEF is not a browser) and never handles a
 * credential — there is none any more.
 *
 * Both download RPCs are three-phase coordinators:
 *   (allowInstall=false, afterConfirm=false) -> download to inbox + inspect, NO write
 *   (allowInstall=true,  afterConfirm=false) -> confirm payload, NO write
 *   (allowInstall=true,  afterConfirm=true)  -> engine.install(), ENGINE-GATED
 * Phase 3 can return E_EXTERNAL_MANAGER; that is the correct verdict, display it.
 */
export const ghSearch = (query: string, page: number) =>
  invoke<GhSearchData>("gh_search", query, page);

export const ghReleases = (owner: string, repo: string) =>
  invoke<GhReleasesData>("gh_releases", owner, repo);

// Typed as OpEnvelope — the SAME proven pattern as installMod — so the existing
// runTwoPhase() helper can drive the confirm->commit flow with no cast.
export const ghDownload = (
  owner: string,
  repo: string,
  assetId: number,
  filename: string,
  allowInstall: boolean,
  afterConfirm: boolean,
) => invoke<ConfirmData | OpResultData>("gh_download", owner, repo, assetId, filename, allowInstall, afterConfirm) as Promise<OpEnvelope>;

export const downloadUrl = (
  url: string,
  filename: string,
  allowInstall: boolean,
  afterConfirm: boolean,
) => invoke<ConfirmData | OpResultData>("download_url", url, filename, allowInstall, afterConfirm) as Promise<OpEnvelope>;

/**
 * Round 38: fetch the required dependencies the installed game is missing.
 * Same TRI-STATE contract as the other downloads — False/False plans, True/False
 * confirms, True/True downloads and installs.
 */
export const fetchDependencies = (
  allowInstall: boolean,
  afterConfirm: boolean,
) => invoke<ConfirmData | OpResultData>("fetch_dependencies", allowInstall, afterConfirm) as Promise<OpEnvelope>;

/**
 * Round 41: show a mod's page in the Game Mode browser.
 *
 * Takes a numeric id, never a URL. The address is built in the backend from the
 * descriptor's game domain, so this call cannot be used to display an arbitrary
 * page. Measured on the device: `steam://openurl/` is the only mechanism that
 * actually puts a page on screen (xdg-open exits 0 and opens nothing here).
 */
export const openModPage = (modId: number) =>
  invoke<OpenModPageData>("open_mod_page", modId);

/**
 * Round 43: keyword search, run where search actually exists.
 *
 * The API has no search endpoint (`mods/search.json` reads "search" as a mod
 * id and answers 422), and every website page is behind a Cloudflare
 * challenge, so scraping is not a fallback. The site's own search page does
 * work, so this opens it with the keyword already applied.
 *
 * Takes the keyword only, never a URL: the address is assembled in the backend
 * from the descriptor's game domain.
 */
export const openSearchPage = (query: string) =>
  invoke<SearchPageData>("open_search_page", query);

/**
 * Round 73: no-key browse page. `sort` is one of trending/latest_added/
 * latest_updated. The backend builds the URL from the game's Nexus domain;
 * no API key and no network call from the plugin — the browser does the work.
 */
export const openBrowsePage = (sort: string) =>
  invoke<BrowsePageData>("open_browse_page", sort);

/**
 * Round 54: delete quarantine folders the journal can no longer restore.
 *
 * Takes an explicit list of transaction ids, never "everything": the backend
 * refuses an empty list rather than sweeping, because a folder it cannot prove
 * is orphaned may hold the only copy of a mod the user still wants.
 *
 * Two-phase like installMod: confirm returns the confirm payload (phase
 * "confirm" + confirm_key CONFIRM_RECLAIM), commit returns the removal report.
 */
/**
 * Hand the Mods/ folder over from another mod manager.
 *
 * Only two kinds of thing move: symlinked entries inside Mods/ and marker
 * files the descriptor names. The backend refuses the whole operation when the
 * obstacle cannot be undone in one step (Mods/ itself is a symlink, a marker
 * directory sits beside the game, the folder is on another device), because
 * half a handover leaves the other manager's deployment partly dismantled and
 * the folder still unmanaged. Nothing is ever deleted: the entries move into
 * the quarantine under one transaction and rollback puts them back.
 */
export const handoverMods = (afterConfirm: boolean) =>
  invoke<ConfirmData | OpResultData>(
    "handover_mods", afterConfirm,
  ) as Promise<OpEnvelope>;

export const reclaimQuarantine = (txns: string[], afterConfirm: boolean) =>
  invoke<ConfirmData | OpResultData>(
    "reclaim_quarantine", txns, afterConfirm,
  ) as Promise<OpEnvelope>;

/**
 * `callable` demonstration (§1). These typed handles are equivalent to the
 * wrappers above; they exist to document the callable() shape against the
 * LOCKED template. They are intentionally NOT used by the UI so the code has a
 * single, guarded path (`invoke`). V3 confirmed 2026-11-12: callable<Args, Ret>
 * takes the argument tuple first and the return type second.
 */
export const callableHandles = {
  status: callable<[], Envelope<StatusData>>("status"),
  list_inbox: callable<[], Envelope<InboxData>>("list_inbox"),
  inspect: callable<[string, (string | null)], Envelope<InspectData>>("inspect"),
  archive_mods: callable<[string], Envelope<ArchiveModsData>>("archive_mods"),
  history: callable<[number], Envelope<HistoryData>>("history"),
  refresh: callable<[], Envelope<StatusData>>("refresh"),
  recovery: callable<[], Envelope<RecoveryData>>("recovery"),
  install: callable<[string, boolean, (Record<string, string[]> | null), (string | null)], OpEnvelope>("install"),
  set_enabled: callable<[string, boolean, boolean], OpEnvelope>("set_enabled"),
  uninstall: callable<[string, boolean], OpEnvelope>("uninstall"),
  rollback: callable<[string], Envelope<OpResultData>>("rollback"),
  gh_search: callable<[string, number], Envelope<GhSearchData>>("gh_search"),
  gh_releases: callable<[string, string], Envelope<GhReleasesData>>("gh_releases"),
  gh_download: callable<[string, string, number, string, boolean, boolean], OpEnvelope>("gh_download"),
  download_url: callable<[string, string, boolean, boolean], OpEnvelope>("download_url"),
  fetch_dependencies: callable<[boolean, boolean], OpEnvelope>("fetch_dependencies"),
  open_mod_page: callable<[number], Envelope<OpenModPageData>>("open_mod_page"),
  open_search_page: callable<[string], Envelope<SearchPageData>>("open_search_page"),
  open_browse_page: callable<[string], Envelope<BrowsePageData>>("open_browse_page"),
  handover_mods: callable<[boolean], Envelope<HandoverData>>("handover_mods"),
  reclaim_quarantine: callable<[string[], boolean], Envelope<ReclaimData>>("reclaim_quarantine"),
  open_loader_page: callable<[string], Envelope<{ url: string; loader: string; opened: boolean }>>("open_loader_page"),
  install_loader: callable<[string, boolean], OpEnvelope>("install_loader"),
};

/**
 * Convenience: extract a localized, friendly error string for toasts.
 *
 * Round 84 — two fixes, both about not throwing away what the backend said:
 *
 *  * `data.reason` wins over the code's generic sentence. E_CAPABILITY_DISABLED
 *    covers ten different situations with one sentence, so for most of them
 *    that sentence is false; the reason word names the real one.
 *  * `detail` is appended when present. It was dropped entirely before, and it
 *    is the only part that says WHICH path/loader/source failed.
 */
export function envelopeError(e: Envelope<unknown>): string {
  const data = (e.data ?? null) as { reason?: unknown } | null;
  const specific = reasonText(typeof data?.reason === "string" ? data.reason : "");
  const msg = specific || errorText(e.code, e.message);
  const detail = String(e.detail || "").trim();
  const head = detail ? `${msg} — ${detail}` : msg;
  return `${head}${e.code ? ` (${e.code})` : ""}`;
}
