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
import { errorText } from "./i18n";
import type {
  Envelope,
  StatusData,
  InboxData,
  InspectData,
  HistoryData,
  RecoveryData,
  ErrorCodesData,
  OpEnvelope,
  ConfirmData,
  OpResultData,
  GhSearchData,
  GhReleasesData,
  SteamLibData,
  KeyStatusData,
  KeySetData,
  KeyDeleteData,
  NexusValidateData,
  NexusRecentData,
  NexusModData,
  NexusDownloadLinkData,
  OpenModPageData,
  SearchPageData,
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
export const listInbox = () => invoke<InboxData>("list_inbox");
export const inspectZip = (zipPath: string) => invoke<InspectData>("inspect", zipPath);
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
 */
export const installMod = (
  zipPath: string,
  afterConfirm: boolean,
  fomodChoices?: Record<string, string[]> | null,
) =>
  invoke<ConfirmData | OpResultData>("install", zipPath, afterConfirm, fomodChoices ?? null) as Promise<OpEnvelope>;

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

/* ------------------------------------------------------- round 39: Nexus metadata
 * FOUR credential RPCs + THREE metadata RPCs. The credential half is where a
 * mistake costs the user their key, so the shape is deliberately narrow:
 *
 *   - `set_api_key` is the ONLY function that accepts a key. It is called once,
 *     with whatever the user typed, and the backend stores it at mode 0600 and
 *     replies with a description of the file (never the contents).
 *   - `nexus_validate` takes NO arguments. Validation re-reads the stored key
 *     inside the backend, so the plaintext never crosses the bridge twice.
 *   - `api_key_status` is stat-only: it reports whether a file exists and what
 *     its mode bits are, and it does not open the file.
 *
 * Nothing here returns key material, and no wrapper below should ever be given
 * one to hold. There is no `nexusSearch`: the API has no keyword-search endpoint
 * (mods/search.json parses "search" as a mod id and answers 422), so browsing is
 * limited to the three feeds the API actually serves.
 */
export const apiKeyStatus = () => invoke<KeyStatusData>("api_key_status");

export const setApiKey = (apiKey: string) => invoke<KeySetData>("set_api_key", apiKey);

export const deleteApiKey = () => invoke<KeyDeleteData>("delete_api_key");

/** No arguments ON PURPOSE: the backend reads the stored key itself. */
export const nexusValidate = () => invoke<NexusValidateData>("nexus_validate");

/** kind ∈ latest_added | latest_updated | trending -- anything else is refused. */
export const nexusRecent = (kind: string) => invoke<NexusRecentData>("nexus_recent", kind);

export const nexusMod = (modId: number) => invoke<NexusModData>("nexus_mod", modId);

/**
 * Honest by construction: for a free account this RPC answers DL_FORBIDDEN with
 * `premium_required: true` and a `browser_url`. The UI must show that refusal
 * and point at the browser, not pretend a download happened.
 */
export const nexusDownloadLink = (modId: number, fileId: number) =>
  invoke<NexusDownloadLinkData>("nexus_download_link", modId, fileId);

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
 * Round 54: delete quarantine folders the journal can no longer restore.
 *
 * Takes an explicit list of transaction ids, never "everything": the backend
 * refuses an empty list rather than sweeping, because a folder it cannot prove
 * is orphaned may hold the only copy of a mod the user still wants.
 *
 * Two-phase like installMod: confirm returns the confirm payload (phase
 * "confirm" + confirm_key CONFIRM_RECLAIM), commit returns the removal report.
 */
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
  inspect: callable<[string], Envelope<InspectData>>("inspect"),
  history: callable<[number], Envelope<HistoryData>>("history"),
  refresh: callable<[], Envelope<StatusData>>("refresh"),
  recovery: callable<[], Envelope<RecoveryData>>("recovery"),
  install: callable<[string, boolean, (Record<string, string[]> | null)], OpEnvelope>("install"),
  set_enabled: callable<[string, boolean, boolean], OpEnvelope>("set_enabled"),
  uninstall: callable<[string, boolean], OpEnvelope>("uninstall"),
  rollback: callable<[string], Envelope<OpResultData>>("rollback"),
  gh_search: callable<[string, number], Envelope<GhSearchData>>("gh_search"),
  gh_releases: callable<[string, string], Envelope<GhReleasesData>>("gh_releases"),
  gh_download: callable<[string, string, number, string, boolean, boolean], OpEnvelope>("gh_download"),
  download_url: callable<[string, string, boolean, boolean], OpEnvelope>("download_url"),
  fetch_dependencies: callable<[boolean, boolean], OpEnvelope>("fetch_dependencies"),
  // Round 39. `nexus_validate` has an EMPTY tuple on purpose: the backend reads
  // the stored key, so validation takes no arguments.
  api_key_status: callable<[], Envelope<KeyStatusData>>("api_key_status"),
  set_api_key: callable<[string], Envelope<KeySetData>>("set_api_key"),
  delete_api_key: callable<[], Envelope<KeyDeleteData>>("delete_api_key"),
  nexus_validate: callable<[], Envelope<NexusValidateData>>("nexus_validate"),
  nexus_recent: callable<[string], Envelope<NexusRecentData>>("nexus_recent"),
  nexus_mod: callable<[number], Envelope<NexusModData>>("nexus_mod"),
  nexus_download_link: callable<[number, number], Envelope<NexusDownloadLinkData>>("nexus_download_link"),
  open_mod_page: callable<[number], Envelope<OpenModPageData>>("open_mod_page"),
  open_search_page: callable<[string], Envelope<SearchPageData>>("open_search_page"),
  reclaim_quarantine: callable<[string[], boolean], Envelope<ReclaimData>>("reclaim_quarantine"),
};

/** Convenience: extract a localized, friendly error string for toasts. */
export function envelopeError(e: Envelope<unknown>): string {
  const msg = errorText(e.code, e.message);
  return `${msg}${e.code ? ` (${e.code})` : ""}`;
}
