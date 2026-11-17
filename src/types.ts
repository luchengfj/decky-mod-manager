/**
 * Shared wire types. These MUST mirror deckymod/envelope.py exactly.
 *
 * JSON-safe contract (§1): the Python backend never returns Path / bytes / set /
 * datetime / NaN. Every value here is a primitive, a plain object, or an array.
 * The frontend must never receive a Python object. `envelope()` is the single
 * gateway that normalizes + serializes with allow_nan=False.
 *
 * selection B (Stardew / SMAPI): the SAME 11 RPCs and the SAME envelope are
 * shared with the RimWorld engine. `packageId` is the shared wire identity key
 * (RimWorld: About.xml packageId; SMAPI: manifest.json UniqueID). Stardew is
 * `file_drop` — there is NO state file, so `w1_state_file` is null, `state`
 * carries SMAPI detection fields, and `enable_disable` is gated off.
 */

/** The single response envelope returned by EVERY backend callable. */
export interface Envelope<T = unknown> {
  ok: boolean;
  code: string | null;
  message: string;
  detail: string;
  data: T | null;
  rollback_available: boolean;
  log_path: string;
  ts: string;
}

export interface GameInfo {
  appid: number;
  name: string;
  platform: string;
  status: string;
}

export interface StatusPaths {
  /** null for SMAPI file_drop (no ModsConfig.xml / W1 state file). */
  w1_state_file: string | null;
  w2_mod_root: string;
  quarantine_root: string;
  staging: string;
  /** Round 25: sibling of Mods/ where DISABLED mods are parked. */
  disabled_root?: string;
  flatpak: boolean;
  fs_posix: boolean;
}

/** A single READ-ONLY detected mod dir (Step 2: parsed from its manifest). */
export interface ModListEntry {
  dir: string;
  uniqueId?: string;
  name?: string;
  version?: string;
  author?: string | null;
  dependencies?: string[];
  missing_dependencies?: string[];
  parse_error?: string;
}

export interface StateInfo {
  // RimWorld (xml_list)
  activeMods?: string[];
  fp?: string;
  error?: string;
  detail?: string;
  // file_drop (Stardew / SMAPI and any descriptor-driven game)
  strategy?: string;
  /** Legacy (pre-Step2) entries were [{dir}]; now richer ModListEntry. */
  mods?: ModListEntry[];
  /**
   * Round 25: mods parked in the sibling .decky-disabled/ directory. They are
   * NOT loaded by the game but the plugin still owns them, so the UI must list
   * them with an Enable action instead of letting them vanish.
   */
  disabled_mods?: ModListEntry[];
  external_manager?: boolean;
  loader_detected?: boolean;
  launch_options?: string;
  read_only?: boolean;
  /** Step 2: [uid, [dirs]] pairs for duplicate UniqueIDs. */
  duplicate_ids?: [string, string[]][];
  /** Step 2: dependency ids referenced but not present in the mod set. */
  missing_dependencies?: string[];
}

export interface ManagedMod {
  packageId: string;
  name: string;
  version: string;
  enabled: boolean;
  dir: string;
  txn: string;
  installed_at?: number;
}

/**
 * P0 (round 2): read-only browse-by-category game catalog entry.
 * Display-only descriptor metadata. `enabled` marks the single active game;
 * planned / unsupported rows are grey "catalog-only, not installable".
 * Showing more games here never lifts the single-active-game write gate.
 */
export interface CatalogEntry {
  id: string;
  name: string;
  appid: number | null;
  platform: string;
  status: string;
  enabled: boolean;
  active: boolean;
  operable: boolean;
  engine: string;
  display_label: string;
  loaders: string[];
  capabilities: Record<string, boolean>;
}

export interface StatusData {
  game: GameInfo;
  paths: StatusPaths;
  state: StateInfo;
  installed: ManagedMod[];
  pending_recovery: string[];
  recovery_needed: boolean;
  capabilities: Record<string, boolean>;
  known_limitations: string[];
  /** Stable i18n keys (LIMIT_*) for the localized known-limitations lines. */
  known_limitation_keys?: string[];
  log_path: string;
  /** Optional: older backends omit it; UI degrades gracefully (no catalog button). */
  catalog?: CatalogEntry[];
}

export interface InboxItem {
  name: string;
  path: string;
  size: number | null;
}

export interface InboxData {
  inbox: string;
  items: InboxItem[];
  log_path: string;
}

export interface ModMeta {
  packageId: string;            // shared wire key (also SMAPI UniqueID)
  name: string;
  version: string;
  version_is_fallback: boolean;
  supportedVersions: string[];
  badges: {
    // RimWorld About.xml
    loadAfter?: string[];
    dependencies?: string[];
    // SMAPI manifest.json
    author?: string | null;
    minimumApiVersion?: string | null;
    entryDll?: string | null;
  };
  install_relpath: string;
  strip_single_root: string | null;
  compressed_size: number;
  uncompressed_size: number;
  entry_count: number;
  // SMAPI-only extras (JSON-safe)
  uniqueId?: string;
  dir_name?: string;
  members?: Record<string, { orig: string; size: number }>;
}

/** Round 28 (criterion 3): parsed FOMOD moduleconfig.xml descriptor. */
export interface FomodFile {
  source: string;
  destination: string;
  kind?: string;
}
export interface FomodOption {
  name: string;
  description: string;
  selected: boolean;
  files: FomodFile[];
}
export interface FomodGroup {
  name: string;
  mode: "single" | "multi";
  options: FomodOption[];
}
export interface FomodStep {
  name: string;
  groups: FomodGroup[];
}
export interface FomodDescriptor {
  present: boolean;
  usable?: boolean;
  reason?: string;
  steps?: FomodStep[];
  warnings?: string[];
}

export interface InspectData {
  mod: ModMeta;
  conflict: {
    duplicate: boolean;
    file_collision: boolean;
    managed: ManagedMod | null;
    same_unique_id_dirs?: string[];
  };
  targets: { w1_state_file: string | null; w2_install_dir: string };
  confirm_text: string;
  log_path: string;
  /** Present when the archive carries fomod/moduleconfig.xml. */
  fomod?: FomodDescriptor;
}

export interface ConfirmPlan {
  op: string;
  packageId?: string;
  name?: string;
  version?: string;
  from?: string;
  to?: string;
  w1?: string;
  w2?: string;
  quarantine?: string;
  was_enabled?: boolean;
  free_w1?: number | null;
  free_w2?: number | null;
  fs_posix?: boolean;
  core_first?: string;
}

/** Phase-1 (dry-run) payload for any two-phase operation. */
export interface ConfirmData {
  phase: "confirm";
  plan: ConfirmPlan;
  confirm_text: string;
  /** Stable i18n key (CONFIRM_*); when present the modal localizes via t(). */
  confirm_key?: string;
  /** JSON-safe placeholder values for confirm_key's {vars}. */
  confirm_vars?: Record<string, string>;
  /** Absolute W1/W2 (or quarantine) paths. Values may be null (file_drop W1). */
  targets: Record<string, string | null>;
  log_path: string;
}

export interface OpResultData {
  packageId?: string;
  dir?: string;
  enabled?: boolean;
  noop?: boolean;
  txn?: string;
  quarantine?: string;
  restored?: string;
  recovered?: boolean;
  rollback_hint?: string;
  log_path?: string;
}

export interface HistoryItem {
  event: string;
  txn: string;
  op?: string;
  packageId?: string;
  quarantine?: string;
  from_path?: string;
  enabled?: boolean;
  detail?: Record<string, unknown>;
  plan?: ConfirmPlan;
}

export interface HistoryData {
  items: HistoryItem[];
  log_path: string;
}

export interface RecoveryData {
  pending: string[];
  log_path: string;
}

export interface ErrorCodeRow {
  code: string;
  category: string;
  message: string;
  rollback_available: boolean;
}

export interface ErrorCodesData {
  codes: ErrorCodeRow[];
  count: number;
}

/**
 * Round 19: download sources. The legacy credential surface was retired, so the
 * Key* payloads are gone; these describe the GitHub search / release views and
 * the shared tri-state download payload instead.
 *
 * Every field here mirrors exactly what deckymod/github_source.py returns —
 * nothing is invented, and nothing optional is assumed present.
 */

/** One `gh_search` result row (description already truncated server-side). */
export interface GhSearchItem {
  owner: string;
  repo: string;
  full_name: string;
  stars: number;
  description: string | null;
  updated_at: string | null;
  archived: boolean;
}

export interface GhSearchData {
  total_count: number;
  page: number;
  items: GhSearchItem[];
}

/**
 * One release asset. `usable` is decided by the BACKEND (`.zip` name plus one
 * of the accepted binary content types) — the UI must not re-derive it, only
 * present it: tapping an unusable asset is disabled, not hidden.
 */
export interface GhAsset {
  id: number;
  name: string;
  size: number;
  content_type: string | null;
  download_count: number;
  usable: boolean;
}

export interface GhRelease {
  id: number;
  tag_name: string;
  name: string | null;
  prerelease: boolean;
  draft: boolean;
  published_at: string | null;
  assets: GhAsset[];
}

export interface GhReleasesData {
  owner: string;
  repo: string;
  releases: GhRelease[];
}

/** What actually landed in the inbox after a download. */
export interface GhDownloaded {
  name: string;
  size: number;
  sha256: string;
  /**
   * Which integrity checks actually RAN ("size" and/or "sha256"). Empty means
   * the source declared nothing to compare against — the UI must not call that
   * "verified", because measuring a file is not the same as checking it.
   */
  verified?: string[];
}

/**
 * Goal item 2: one Steam library root. `removable` is derived from whether the
 * path lives outside the user's home, so it is accurate for an SD card without
 * hard-coding /run/media.
 */
export interface SteamLibrary {
  path: string;
  source: string;
  removable: boolean;
}

/**
 * One installed Steam game. An `appmanifest_<appid>.acf` is the only proof of
 * installation, so a folder under steamapps/common with no manifest is absent.
 * `state` is "installed" (StateFlags 4), "incomplete", or "unknown" when the
 * manifest could not be parsed — the UI must not pretend the latter two are
 * playable. `compatdata` is null for native Linux titles, which is normal.
 */
/** Read-only identification of a game's Mod directory (standard 4).
 *  `adapted=false` means no template: the UI must say "not adapted" and must
 *  NOT guess a path. `writable=false` (identification-only templates) must
 *  never be shown as an operable/modifiable game.
 */
export interface GameTemplateDir {
  path: string;
  exists: boolean;
  /** Round 37: folder names already inside this directory (read-only scan). */
  mods?: string[];
  /** How many folders were found in this directory. */
  count?: number;
  /** True when the scan hit its cap and stopped early -- the UI must say so
   *  rather than present a partial list as complete. */
  truncated?: boolean;
}
export interface GameTemplate {
  adapted: boolean;
  appid: number | null;
  name?: string;
  mod_dirs: GameTemplateDir[];
  loader: string | null;
  writable: boolean;
  note: string;
  /** Round 36: phrase that finds this game's mods in the GitHub search box.
   *  `null` for a game with no template -- the UI must not invent one. */
  search_hint?: string | null;
  /** Round 37: total folders found across all of this game's mod dirs. */
  total_mods?: number;
}

export interface SteamGame {
  appid: number;
  name: string;
  installdir: string;
  library: string;
  install_path: string;
  compatdata: string | null;
  state: "installed" | "incomplete" | "unknown";
  state_flags: number | null;
  size_on_disk: number | null;
  manifest: string;
  removable: boolean;
  template?: GameTemplate;
}

export interface SteamLibData {
  libraries: SteamLibrary[];
  games: SteamGame[];
  library_count: number;
  game_count: number;
  removable_count: number;
  with_prefix_count: number;
}

/**
 * Non-committing payload shared by gh_download / download_url phases 1 and 2.
 * `phase` tells the UI which step it is looking at; `install_allowed` is the
 * backend's answer, not a UI opinion.
 */
export interface GhFetchData {
  phase: "inspect" | "confirm";
  install_allowed: boolean;
  source: "github" | "url";
  downloaded: GhDownloaded;
  mod: ModMeta;
  confirm_text?: string;
  plan?: ConfirmPlan;
}

export interface ProgressPayload {
  stage: string;
  op: string;
  packageId: string;
  pct: number;
}

/* --------------------------------------------------- round 39: Nexus credential surface
 * These types describe a file on disk, not a secret. Every field here is safe
 * to render: `path` is a location, `mode_actual` is a permission bitmask, and
 * `state` is one of three words. None of them is, or can be derived into, the
 * key itself -- the backend never returns the key and there is no type for it.
 */
export interface KeyStatusData {
  configured: boolean;
  path: string;
  /** `missing` = no file; `unreadable` = present but not private/readable;
   *  `present` = a key is stored and readable. */
  state: "missing" | "unreadable" | "present";
  mode_requested: string;
  /** Already formatted by the backend, e.g. "0o600". Not a number: a device
   *  probe showed `oct()` output crossing the bridge as a string, so the UI must
   *  render it verbatim instead of re-formatting (prepending "0" produced the
   *  nonsense "00o600" in the first draft). `null` = the file could not be stat'ed. */
  mode_actual: string | null;
  mode_ok: boolean | null;
  /** False on a filesystem with no POSIX mode bits (e.g. exFAT), where the
   *  0600 promise cannot be enforced -- the UI must say so rather than imply it. */
  posix: boolean;
  size?: number;
  detail?: string;
}

export interface KeySetData {
  stored: boolean;
  path: string;
  mode_requested: string;
  mode_actual: string | null;
}

export interface KeyDeleteData {
  deleted: boolean;
  path?: string;
  reason?: string;
}

export interface NexusValidateData {
  status: number;
  name?: string;
  is_premium?: boolean;
  is_supporter?: boolean;
  email_verified?: boolean;
  profile_url?: string;
}

export interface NexusRecentRow {
  mod_id: number;
  name: string;
  version?: string;
  author?: string;
  summary?: string;
  endorsement_count?: number;
  mod_page_url: string;
}

export interface NexusRecentData {
  kind: string;
  mods: NexusRecentRow[];
}

/** The 8 fields the backend keeps out of a 383 KB files.json response. */
export interface NexusFile {
  file_id: number;
  name: string;
  version?: string;
  category_name?: string;
  file_name?: string;
  size_kb?: number;
  uploaded_timestamp?: number;
  mod_version?: string;
}

export interface NexusModData {
  mod_id: number;
  browser_url: string;
  info: {
    mod_id?: number;
    name?: string;
    version?: string;
    author?: string;
    summary?: string;
    endorsement_count?: number;
    mod_page_url?: string;
  };
  files: NexusFile[];
  /** Present when the file list itself failed (e.g. `Mod not available`) while
   *  the mod metadata loaded -- a partial answer the UI must show as partial. */
  files_error?: string;
}

export interface NexusDownloadLinkData {
  /** True for every free account: the API issues download links to premium only. */
  premium_required: boolean;
  browser_url: string;
  server_message?: string;
}

/** Union for a two-phase op result: either the confirm payload or the commit. */
export type OpEnvelope = Envelope<ConfirmData | OpResultData>;

export function isConfirmData(d: ConfirmData | OpResultData | null): d is ConfirmData {
  return !!d && (d as ConfirmData).phase === "confirm";
}
