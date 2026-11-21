/**
 * index.tsx — Decky Loader plugin entry (frontend / QAM panel).
 *
 * This is the integration glue that wires the 11 gamepad operations of §5.1
 * to the Python backend through api.ts, and implements the §5.3 onDismount
 * cleanup. All version-specific @decky/* surface is flagged ⚠️ V3 and must
 * be confirmed against the LOCKED template / Decky Loader version before a
 * real build (see docs/VERIFICATION.md, gate G3).
 *
 * Design decisions that matter for review:
 *  - Two-phase ops (install / uninstall) call phase 1 (NO writes), show a
 *    confirm modal with the W1/W2 absolute paths, then call phase 2.
 *  - Enable/disable is REVERSIBLE, so we deliberately SKIP phase 1 and call
 *    afterConfirm=true directly: a single A-press, no second dialog (§5.1 #5).
 *  - Rollback has no backend two-phase; the confirm is built in the UI after
 *    picking a txn from History (§5.1 #7).
 *  - Every mutating result is reloaded from the BACKEND (getStatus reads the
 *    journal), never from React state, so state survives a QAM re-open (#11).
 *  - onDismount discards stale in-flight RPC results via a generation counter;
 *    it NEVER aborts a backend write transaction (those are atomic in Python).
 */
import {
  definePlugin,
  toaster,
  addEventListener,
  removeEventListener,
} from "@decky/api";
import {
  PanelSection,
  PanelSectionRow,
  ButtonItem,
  DialogButton,
  Focusable,
  TextField,
} from "@decky/ui";
import { useEffect, useRef, useState } from "react";

import {
  PROGRESS_EVENT,
  bridgeError,
  envelopeError,
  getStatus,
  listInbox,
  inspectZip,
  getHistory,
  refreshStatus,
  getRecovery,
  getErrorCodes,
  listGames,
  switchGame,
  gameSetup,
  configureGame,
  forgetGame,
  openLoaderPage,
  installLoader,
  deleteZipSource,
  installMod,
  setModEnabled,
  uninstallMod,
  rollbackTxn,
  fetchDependencies,
  openModPage,
  openSearchPage,
  openBrowsePage,
  handoverMods,
  reclaimQuarantine,
} from "./api";
import type {
  Envelope,
  StatusData,
  InboxData,
  ManagedMod,
  ConfirmData,
  OpResultData,
  OpEnvelope,
  HistoryItem,
  ProgressPayload,
  CatalogEntry,
  SteamGame,
  GameSetupData,
} from "./types";
import { isConfirmData } from "./types";
import { t, errorText, categoryText } from "./i18n";
import type { ModListEntry } from "./types";
import { showConfirm } from "./components/ConfirmModal";
import { runUninstallFlow } from "./uninstallFlow";
import { autoImportNew, autoImportSilent } from "./autoImport";
import { runRollbackFlow } from "./rollbackFlow";
import { runDepsFlow } from "./depsFlow";
import { showInfo, showListModal, showErrorModal, showFomodModal } from "./components/Modal";
import type { ListRow, ModalAction } from "./components/Modal";
import { ModRow } from "./components/ModRow";
import { ImportBox } from "./components/ImportBox";

/* ------------------------------------------------------------------ small utils */

/** Toast never throws: a broken toaster must never break an operation. */
function toast(title: string, body: string): void {
  try {
    toaster.toast({ title, body, duration: 4000 });
  } catch (_) {
    /* ⚠️ V3: toaster.toast shape confirmed against locked @decky/api */
  }
}

/** Human-readable one-liner for the persisted "last result" (journal-backed). */
function summarize(item: HistoryItem): string {
  const ev = item.event || t("EVENT");
  const pid = item.packageId ? ` · ${item.packageId}` : "";
  const txn = item.txn ? ` · ${item.txn}` : "";
  return t("LAST_ENTRY", "Last journal entry: {ev}{pid}{txn}", { ev, pid, txn });
}

/** Human-readable one-liner for a history transaction.
 *  Picks the meaningful action event out of a txn's journal rows (a txn has
 *  PREPARED / APPLYING / MOD_* / COMMITTED) so the row says "Uninstalled
 *  Automate" instead of a raw txn id + event code. */
function describeTxn(items: HistoryItem[]): { label: string; mod: string } {
  // Priority: the action event that names the mod.
  const actionOrder = ["MOD_UNINSTALLED", "MOD_INSTALLED", "MOD_ENABLED", "MOD_DISABLED"];
  let hit: HistoryItem | undefined;
  for (const ev of actionOrder) {
    hit = items.find((i) => i.event === ev);
    if (hit) break;
  }
  const verbKey: Record<string, [string, string]> = {
    MOD_UNINSTALLED: ["HIST_UNINSTALLED", "Uninstalled {mod}"],
    MOD_INSTALLED: ["HIST_INSTALLED", "Installed {mod}"],
    MOD_ENABLED: ["HIST_ENABLED", "Enabled {mod}"],
    MOD_DISABLED: ["HIST_DISABLED", "Disabled {mod}"],
  };
  // packageId from the action event, or from PREPARED.plan, or COMMITTED.detail.
  let mod = hit?.packageId || "";
  if (!mod) {
    const prep = items.find((i) => i.event === "PREPARED");
    mod = (prep?.plan?.packageId as string) || "";
  }
  if (!mod) {
    const com = items.find((i) => i.event === "COMMITTED");
    mod = (com?.detail?.packageId as string) || "";
  }
  const evName = hit?.event || "PREPARED";
  const [key, fallback] = verbKey[evName] || ["HIST_CHANGED", "Changed {mod}"];
  const label = t(key, fallback, { mod: mod || t("Q_MARK") });
  return { label, mod };
}

/** Turn a journal txn id like "20261120T131035-eaa92e1b" into a local time string. */
function txnTime(txn: string): string {
  const m = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})/.exec(txn || "");
  if (!m) return txn;
  const d = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]);
  return Number.isNaN(d.getTime()) ? txn : d.toLocaleString();
}

/**
 * selection B (Stardew / SMAPI): `file_drop` has NO ModsConfig.xml state file and
 * NO separate enable step (install == enable). Both engines share the 11 RPCs
 * and the same envelope; we branch UI copy/behavior on the strategy flag that
 * the backend returns in `status().state.strategy`. This keeps the RimWorld
 * 41-green path byte-identical while making the panel correct for Stardew.
 */
function isFileDrop(s: StatusData | null): boolean {
  return !!s && s.state?.strategy === "file_drop";
}

/* ------------------------------------------------------------------ panel */

function Content() {
  const [status, setStatus] = useState<StatusData | null>(null);
  // Installed Steam games, loaded once at mount and shown directly in the
  // Games tab so picking a game is a single tap, not a buried modal.
  const [gameList, setGameList] = useState<SteamGame[]>([]);
  const [inbox, setInbox] = useState<InboxData | null>(null);
  const [busy, setBusy] = useState(false);
  const [lastResult, setLastResult] = useState(t("RESOLVING"));
  const [progress, setProgress] = useState<ProgressPayload | null>(null);
  const [error, setError] = useState<Envelope<unknown> | null>(null);

  const [nexusModId, setNexusModId] = useState("");
  // The game whose Nexus site the ID lookup targets. Set when the user picks a
  // game in the library; drives the visible prefix and the open-page URL. The
  // backend still derives the actual domain from the active descriptor, so this
  // is a display/selection aid, not a way to point the plugin at arbitrary hosts.
  const [nexusDomain, setNexusDomain] = useState<string | null>(null);
  // Round 43: the keyword is ordinary text, not a secret, so it may be
  // rendered back. It is handed to open_search_page, which refuses control
  // characters and anything over 64 characters, then opens the site's own
  // search page.
  const [searchText, setSearchText] = useState("");

  // Round 37: "my mods, grouped by game". The plugin's journal only knows what
  // IT installed, so a game the user modded by hand looked empty. The scan is
  // read-only and fetched on demand by openModsByGame() -- there is no cached
  // copy here on purpose, because a stale render-time list is exactly how the
  // grouping would show yesterday's folders.

  // Round 30: one section visible at a time. Before this the panel
  // stacked five PanelSections (~40 focusables) at once, so nothing
  // read as the primary action. "" = every section collapsed.
  const [openSection, setOpenSection] = useState<string>("games");

  // The visible Nexus prefix for the selected game. Falls back to the active
  // game's domain so the panel is useful even before a game is picked.
  const activeNexusDomain = nexusDomain
    || (status?.catalog || []).find((c) => c.active)?.nexus_domain
    || (status?.catalog || []).find((c) => c.operable)?.nexus_domain
    || null;
  const nexusPrefix = activeNexusDomain
    ? `https://www.nexusmods.com/${activeNexusDomain}/mods`
    : null;

  // §5.3 lifecycle refs -----------------------------------------------------
  const generation = useRef(0);        // bumped on unmount -> stale RPCs dropped
  const mounted = useRef(false);
  const busyRef = useRef(false);
  const timers = useRef<Set<ReturnType<typeof setTimeout>>>(new Set());

  const setBusySafe = (v: boolean) => {
    busyRef.current = v;
    if (mounted.current) setBusy(v);
  };

  /** Tracked timer: cleared on unmount (§5.3 "no watcher/timer left"). */
  const later = (fn: () => void, ms: number) => {
    const t = setTimeout(() => {
      timers.current.delete(t);
      if (mounted.current) fn();
    }, ms);
    timers.current.add(t);
  };

  /** Discard a failed envelope into the uniform error modal (§5.2 / op #8). */
  const applyResult = (r: Envelope<unknown>, successMsg: string): boolean => {
    if (!mounted.current) return false;
    if (!r.ok) {
      setError(r);
      setLastResult(t("STATUS_FAILED", "Failed: {msg}", { msg: envelopeError(r) }));
      return false;
    }
    if (successMsg) setLastResult(successMsg);
    return true;
  };

  /** Re-read EVERYTHING from the backend (journal), never from React state. */
  // Round 37: fetch the per-game Mod-directory scans. Read-only, and a failure
  // here must never break the panel — the mod list simply stays ungrouped.
  const loadGameGroups = async (): Promise<SteamGame[]> => {
    const g = generation.current;
    try {
      const r = await listGames();
      if (!mounted.current || generation.current !== g) return [];
      if (r.ok && r.data) {
        return r.data.games || [];
      }
    } catch (_) {
      /* grouping is a convenience; never surface its failure as a panel error */
    }
    return [];
  };

  // Round 76: exactly one game is active at a time. Switching rewrites
  // active_game, the backend drops its cached engine, and the next RPC rebuilds
  // against the new descriptor — so the refresh below is all that is needed.
  const doSwitchGame = (gameId: string, label: string) => {
    setBusySafe(true);
    const g = generation.current;
    (async () => {
      const r = await switchGame(gameId);
      if (!mounted.current || generation.current !== g) { setBusySafe(false); return; }
      if (!r.ok) { setBusySafe(false); setError(r); setLastResult(envelopeError(r)); return; }
      await reload();
      if (!mounted.current || generation.current !== g) { setBusySafe(false); return; }
      setBusySafe(false);
      toast(t("GAME_SWITCHED_TITLE"), t("GAME_SWITCHED", "Now managing: {name}", { name: label }));
      setLastResult(t("GAME_SWITCHED", "Now managing: {name}", { name: label }));
    })().catch((e) => {
      if (!mounted.current) return;
      setBusySafe(false);
      setError(bridgeError(String(e)));
    });
  };

  // Round 77: a game with no built-in descriptor can still be managed — the
  // user points the plugin at the folder that game's loader reads. Nothing is
  // written until an install runs, and then only inside that folder.
  const saveGameConfig = (appid: number, name: string, folder: string) => {
    setBusySafe(true);
    const g = generation.current;
    (async () => {
      const r = await configureGame(appid, name, [folder]);
      if (!mounted.current || generation.current !== g) { setBusySafe(false); return; }
      setBusySafe(false);
      if (!r.ok) { setError(r); setLastResult(envelopeError(r)); return; }
      await reload();
      toast(t("GS_SAVED_TITLE"), t("GS_SAVED", "{name} → {folder}", { name, folder }));
      setLastResult(t("GS_SAVED", "{name} → {folder}", { name, folder }));
    })().catch((e) => {
      if (!mounted.current) return;
      setBusySafe(false);
      setError(bridgeError(String(e)));
    });
  };

  // Round 78: a configuration can be wrong — the folder the user picked may
  // not be where the game's loader reads. Removing it stops the plugin from
  // writing there at all (the backend also falls back to a built-in game when
  // the removed one was active). It never touches the game's files.
  const doForgetGame = (appid: number, name: string) => {
    setBusySafe(true);
    const g = generation.current;
    (async () => {
      const r = await forgetGame(appid);
      if (!mounted.current || generation.current !== g) { setBusySafe(false); return; }
      setBusySafe(false);
      if (!r.ok) { setError(r); setLastResult(envelopeError(r)); return; }
      await reload();
      void loadGameGroups().then((gl) => {
        if (mounted.current && generation.current === g) setGameList(gl);
      });
      toast(t("GS_REMOVED_TITLE"), t("GS_REMOVED", "{name} is no longer configured", { name }));
      setLastResult(t("GS_REMOVED", "{name} is no longer configured", { name }));
    })().catch((e) => {
      if (!mounted.current) return;
      setBusySafe(false);
      setError(bridgeError(String(e)));
    });
  };

  // Round 79: open a loader's official download page (browser hand-off, no
  // download by the plugin). The URL is built in the backend from the loader
  // catalog — the caller passes the catalog id only.
  const doOpenLoaderPage = (loaderId: string, name: string) => {
    setBusySafe(true);
    const g = generation.current;
    (async () => {
      const r = await openLoaderPage(loaderId);
      if (!mounted.current || generation.current !== g) { setBusySafe(false); return; }
      setBusySafe(false);
      if (!r.ok) { setError(r); setLastResult(envelopeError(r)); return; }
      toast(t("GS_LOADER_OPENED_TITLE"), t("GS_LOADER_OPENED", "{name} download page opened — grab the ZIP, then come back.", { name }));
    })().catch((e) => {
      if (!mounted.current) return;
      setBusySafe(false);
      setError(bridgeError(String(e)));
    });
  };

  // Round 79: pick the downloaded loader ZIP and extract it in two phases.
  // The list comes from the same read-only scan the import list uses
  // (inbox + the browser's download folder). The backend refuses anything
  // outside the declared roots and journals every file it places.
  const openLoaderZipPicker = (d: GameSetupData) => {
    setBusySafe(true);
    const g = generation.current;
    (async () => {
      const fresh = await listInbox();
      if (!mounted.current || generation.current !== g) { setBusySafe(false); return; }
      setBusySafe(false);
      if (!fresh.ok || !fresh.data) {
        showInfo(t("GS_LOADER_INSTALL"), [envelopeError(fresh)], []);
        return;
      }
      const zips = (fresh.data.items || []).filter((it) => /\.zip$/i.test(it.name));
      const rows: ListRow[] = zips.map((it) => ({
        label: it.name,
        sub: `${it.path}${it.size != null ? t("INBOX_BYTES", "  ·  {n} bytes", { n: it.size }) : ""}`,
        onActivate: (close) => { close(); void confirmLoaderInstall(d, it.path, it.name); },
      }));
      showListModal(
        t("GS_LOADER_PICK", "Loader ZIPs ({n})", { n: zips.length }),
        rows,
        t("GS_LOADER_PICK_SUB", "These are the ZIPs in your download folders. A = extract into the game folder."),
      );
    })().catch((e) => {
      if (!mounted.current) return;
      setBusySafe(false);
      setError(bridgeError(String(e)));
    });
  };

  const confirmLoaderInstall = async (d: GameSetupData, path: string, name: string): Promise<void> => {
    setBusySafe(true);
    const g = generation.current;
    const plan = await installLoader(path, false);
    if (!mounted.current || generation.current !== g) { setBusySafe(false); return; }
    setBusySafe(false);
    if (!plan.ok) { setError(plan); setLastResult(envelopeError(plan)); return; }
    showInfo(
      t("GS_LOADER_CONFIRM", "Install loader?"),
      [
        (plan.data && (plan.data as { confirm_text?: string }).confirm_text) || name,
        "",
        t("GS_LOADER_REMOVABLE", "Removable afterwards: uninstall it from the mods list like any mod."),
      ],
      [
        {
          label: t("GS_LOADER_DO", "Install (A)"),
          onClick: (close) => {
            close();
            void runLoaderInstall(path, false);
          },
        },
        {
          label: t("GS_LOADER_DO_DELETE"),
          onClick: (close) => {
            close();
            void runLoaderInstall(path, true);
          },
        },
      ],
    );
  };

  const runLoaderInstall = async (path: string, deleteAfter: boolean): Promise<void> => {
    setBusySafe(true);
    const g = generation.current;
    const done = await installLoader(path, true);
    if (!mounted.current || generation.current !== g) { setBusySafe(false); return; }
    if (!done.ok) { setBusySafe(false); setError(done); setLastResult(envelopeError(done)); return; }
    const dd = (done.data || {}) as { files?: number; packageId?: string };
    let note = t("GS_LOADER_DONE", "{n} files installed as {pid}. Remove it from the mods list any time.",
      { n: String(dd.files ?? 0), pid: dd.packageId ?? "" });
    if (deleteAfter) {
      const dr = await deleteZipSource(path);
      if (dr.ok) {
        note += " · " + t("ZIP_REMOVED", "{name} deleted.", { name: path.split("/").pop() || path });
      } else {
        setError(dr);
      }
    }
    await reload();
    setBusySafe(false);
    toast(t("GS_LOADER_DONE_TITLE"), note);
    setLastResult(note);
  };

  const openGameSetup = (game: SteamGame) => {
    setBusySafe(true);
    const g = generation.current;
    (async () => {
      const r = await gameSetup(game.appid);
      if (!mounted.current || generation.current !== g) { setBusySafe(false); return; }
      setBusySafe(false);
      if (!r.ok || !r.data) {
        showInfo(t("GS_TITLE", "Mod folder for {name}", { name: game.name }),
          [r.ok ? t("GS_FAIL") : envelopeError(r)], []);
        return;
      }
      const d = r.data;
      if (d.refused) {
        showInfo(t("GS_REFUSED_TITLE", "Not supported"), [
          t("GS_REFUSED_BODY", "{name} is an online game with anti-cheat. Modding it risks a ban, so this plugin will not touch it.", { name: d.name }),
        ], []);
        return;
      }
      const rows: ListRow[] = [];
      if (d.configured) {
        // Round 78: reconfiguring is possible by tapping another folder, but
        // UN-configuring had no surface at all — the only fix for a wrong
        // folder was deleting a JSON file in Desktop Mode.
        rows.push({
          label: t("GS_REMOVE", "Remove this configuration"),
          sub: t("GS_REMOVE_SUB",
            "The plugin stops managing {name}. Nothing in the game folder is deleted.",
            { name: d.name }),
          onActivate: (close) => { close(); doForgetGame(d.appid, d.name); },
        });
      }
      rows.push(...d.candidates.map((c): ListRow => ({
        label: c.path,
        sub: c.exists
          ? (d.configured && d.write_roots.indexOf(c.path) >= 0
              ? t("GS_CURRENT", "already configured")
              : t("GS_EXISTS", "folder exists — A = use it"))
          : t("GS_WILL_CREATE", "will be created — only if you already installed the loader"),
        onActivate: (close) => { close(); saveGameConfig(d.appid, d.name, c.path); },
      })));
      // Round 79: loader hand-off — jump to the official page, then extract
      // the ZIP the user downloaded. Built-in games get no loader rows here
      // (their descriptors keep loader_install=false and the backend refuses).
      const loaders = d.loaders || [];
      if (loaders.length) {
        rows.push({
          label: t("GS_LOADER_HEAD", "Mod loaders"),
          sub: t("GS_LOADER_HEAD_SUB",
            "Open the official page, download the ZIP, then install it — journaled and removable like any mod. Steam launch options are never edited."),
          onActivate: () => { /* header row: no action */ },
          disabled: true,
        });
        for (const ld of loaders) {
          rows.push({
            label: t("GS_LOADER_ROW", "{name} · open download page",
              { name: ld.version ? `${ld.name} ${ld.version}` : ld.name }),
            sub: (ld.installed ? t("GS_LOADER_INSTALLED", "already installed  ·  ") : "")
              + (ld.hint_fits ? (ld.hint_note || "") : t("GS_LOADER_UNFIT", "may not fit this game") + "  ·  " + ld.hint_note),
            onActivate: (close) => { close(); doOpenLoaderPage(ld.id, ld.name); },
          });
        }
        rows.push({
          label: t("GS_LOADER_INSTALL", "Install loader ZIP from Downloads"),
          sub: t("GS_LOADER_INSTALL_SUB",
            "Pick the ZIP you just downloaded; the plugin extracts it into the game folder."),
          onActivate: (close) => { close(); void openLoaderZipPicker(d); },
        });
      }
      showListModal(
        t("GS_TITLE", "Mod folder for {name}", { name: d.name }),
        rows,
        t("GS_SUB", "Where does this game load mods from? The plugin only writes inside the folder you pick, and this does not install any loader."),
      );
    })().catch((e) => {
      if (!mounted.current) return;
      setBusySafe(false);
      setError(bridgeError(String(e)));
    });
  };

  const reload = async (): Promise<void> => {
    const g = generation.current;
    const [s, i] = await Promise.all([getStatus(), listInbox()]);
    // §5.3: drop the result if the panel was unmounted while the RPC was in flight
    if (!mounted.current || generation.current !== g) return;
    if (s.ok) setStatus(s.data);
    else setError(s);
    if (i.ok) setInbox(i.data);
  };

  // Round 37: "my mods grouped by game". Every game with a template is listed
  // with the folders actually present on disk; games without one say "not
  // adapted" instead of being given a guessed path.
  const openModsByGame = async () => {
    // Read the fresh list every time: there is no cached copy, so the grouping
    // always reflects the disk as it is right now.
    const games = await loadGameGroups();
    if (!games.length) {
      showInfo(t("MODS_BY_GAME"), [t("MODS_BY_GAME_EMPTY")], []);
      return;
    }
    const scanned = games.filter(
      (g) => g.template && g.template.adapted && (g.template.total_mods ?? 0) > 0,
    );
    const rows: ListRow[] = [];
    for (const g of games) {
      const tpl = g.template;
      if (!tpl || !tpl.adapted) {
        rows.push({
          label: t("MODS_BY_GAME_ROW", "{name} · {n}", { name: g.name, n: "—" }),
          sub: t("LIB_UNSUPPORTED_NOTE"),
          onActivate: () => {
            showInfo(g.name, [t("LIB_UNSUPPORTED_NOTE")], []);
          },
        });
        continue;
      }
      const total = tpl.total_mods ?? 0;
      rows.push({
        label: t("MODS_BY_GAME_ROW", "{name} · {n}", { name: g.name, n: total }),
        sub: tpl.writable
          ? t("MODS_BY_GAME_WRITABLE")
          : t("LIB_IDENTIFY_ONLY"),
        onActivate: () => {
          const lines: string[] = [];
          for (const d of tpl.mod_dirs || []) {
            lines.push(t("LIB_MODDIR_ROW", "{p} ({state})", {
              p: d.path || "—",
              state: d.exists ? t("LIB_MODDIR_YES") : t("LIB_MODDIR_NO"),
            }));
            const names = d.mods || [];
            if (!d.exists) continue;
            if (!names.length) {
              lines.push(t("MODS_BY_GAME_NONE"));
              continue;
            }
            for (const n of names) lines.push("  " + n);
            if (d.truncated) lines.push(t("MODS_BY_GAME_TRUNCATED"));
          }
          if (!lines.length) lines.push(t("MODS_BY_GAME_NONE"));
          showInfo(g.name, lines, [], t("MODS_BY_GAME_SUB", "Read-only folder listing"));
        },
      });
    }
    const subtitle = scanned.length
      ? t("MODS_BY_GAME_SUB2", "{n} games with mod folders", { n: scanned.length })
      : t("MODS_BY_GAME_SUB_EMPTY2");
    showListModal(t("MODS_BY_GAME"), rows, subtitle);
  };

  // ---------------------------------------------------------------- mount / unmount
  useEffect(() => {
    mounted.current = true;
    const g = ++generation.current;

    // emit subscription: STABLE listener reference for add/remove (§1)
    const listener = (payload: unknown) => {
      if (!mounted.current) return;
      setProgress((payload || {}) as ProgressPayload);
    };
    try {
      addEventListener(PROGRESS_EVENT, listener);
    } catch (_) {
      /* ⚠️ V3: confirm addEventListener exists in locked @decky/api */
    }

    // Bootstrap == §5.1 op #9 "auto rescan when the tab gains focus": every
    // QAM re-open re-mounts this panel and re-runs status (which performs the
    // verify_on_open drift check) + inbox scan. #11's persistence proof:
    // installed/enable state comes from the on-disk journal, not React state.
    (async () => {
      const [s, i, h] = await Promise.all([getStatus(), listInbox(), getHistory(1)]);
      if (!mounted.current || generation.current !== g) return;
      if (s.ok) setStatus(s.data);
      else setError(s);
      if (i.ok) setInbox(i.data);
      if (h.ok && h.data && h.data.items.length) setLastResult(summarize(h.data.items[0]));
      else setLastResult(t("STATUS_READY"));

      // Round 70: auto-install newly downloaded mods on panel mount. The common
      // flow is "download in Game Mode browser -> come back to QAM"; this pass
      // installs any brand-new valid mod ZIP from Downloads with no taps. Guards
      // in autoImport.tsx skip non-mods / already-installed / FOMOD, and a module
      // `seen` set prevents re-installing across remounts. Silent + toast only.
      const auto = await autoImportSilent();
      if (!mounted.current || generation.current !== g) return;
      if (auto.installed.length) {
        const msg = t("AI_AUTO_DONE", "Auto-installed {n} new mod(s): {names}", {
          n: String(auto.installed.length), names: auto.installed.join(", "),
        });
        setLastResult(msg);
        toast(t("TOAST_DONE"), msg);
        // Re-read status so the freshly installed mods appear immediately.
        const s2 = await getStatus();
        if (mounted.current && generation.current === g && s2.ok) setStatus(s2.data);
        const i2 = await listInbox();
        if (mounted.current && generation.current === g && i2.ok) setInbox(i2.data);
      }
    })();
    // Load the installed-game list once and keep it for the Games tab, so the
    // user can pick a game directly instead of digging through a modal.
    loadGameGroups().then((gl) => {
      if (mounted.current && generation.current === g) setGameList(gl);
    });

    return () => {
      // §5.3 onDismount cleanup ---------------------------------------------
      mounted.current = false;
      generation.current++;            // invalidate ALL in-flight RPC results
      // NOTE: we do NOT abort backend write transactions; they are atomic in
      // Python and their outcome is read back from the journal on next open.
      try {
        removeEventListener(PROGRESS_EVENT, listener);
      } catch (_) {
        /* ⚠️ V3 */
      }
      timers.current.forEach(clearTimeout);
      timers.current.clear();
      // No setState here: React unmount already discards the tree.
    };
  }, []);

  // §5.1 op #8 / §5.2: uniform error popup (A/B closable, no traceback).
  useEffect(() => {
    if (!error) return;
    showErrorModal(error, {
      onDismiss: () => setError(null),
      // Our reduced envelope has rollback_available but no txn_id, so the
      // Rollback action opens History where the user picks the exact txn.
      onRollback: error.rollback_available
        ? () => {
            setError(null);
            void openHistory();
          }
        : undefined,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [error]);

  /* -------------------------------------------------------------- op helpers */

  /**
   * Generic two-phase runner. `phase(false)` is a NO-WRITE dry-run; its
   * ConfirmData is shown to the user; only `phase(true)` commits.
   */
  const runTwoPhase = (
    phase: (afterConfirm: boolean) => Promise<OpEnvelope>,
    successMsg: (d: OpResultData) => string,
    /* Round 55: a refusal that carries its own reason (handover's blocking
     * obstacles) gets to speak for itself instead of the generic error text.
     * Returns true when handled, so the caller's message is not overwritten. */
    onRefuse?: (r: OpEnvelope) => boolean,
    /* Round 80: an optional follow-up that runs once AFTER a committed op —
     * e.g. deleting the source ZIP behind "install and delete". Its message,
     * when it returns one, is appended to the result line. */
    afterSuccess?: () => Promise<string | null>,
  ) => {
    setBusySafe(true);
    const g = generation.current;
    (async () => {
      const first = await phase(false);
      if (!mounted.current || generation.current !== g) {
        setBusySafe(false);
        return;
      }
      if (!first.ok) {
        if (onRefuse && onRefuse(first)) {
          setBusySafe(false);
          return;
        }
        applyResult(first as Envelope<unknown>, "");
        setBusySafe(false);
        return;
      }
      const d = first.data;
      if (!isConfirmData(d)) {
        // Defensive: backend executed without a confirm payload.
        const msg = successMsg((d || {}) as OpResultData);
        applyResult(first as Envelope<unknown>, msg);
        await reload();
        setBusySafe(false);
        return;
      }
      showConfirm(d as ConfirmData, async (confirmed) => {
        if (!mounted.current) return;
        if (!confirmed) {
          setLastResult(t("STATUS_CANCELLED"));
          setBusySafe(false);
          return;
        }
        const second = await phase(true);
        if (!mounted.current || generation.current !== g) {
          setBusySafe(false);
          return;
        }
        const msg = successMsg((second.data || {}) as OpResultData);
        const okDone = applyResult(second as Envelope<unknown>, msg);
        if (okDone) {
          toast(t("TOAST_DONE"), msg);
          later(() => setProgress(null), 1500);
          if (afterSuccess) {
            const extra = await afterSuccess();
            if (extra) setLastResult(`${msg} · ${extra}`);
          }
        }
        await reload();
        setBusySafe(false);
      });
      // busy stays true while the modal is open; the callback clears it.
    })().catch((e) => {
      if (!mounted.current) return;
      setBusySafe(false);
      setError(bridgeError(String(e)));
    });
  };

  /* -------------------------------------------------------------- §5.1 #2/#3 inbox */
  const openInbox = async () => {
    // Round 68: always re-scan when the user opens the inbox. The most common
    // flow is "download in the Game Mode browser, come back to import" — that
    // file lands in Downloads AFTER the panel mounted, so the cached `inbox`
    // state is stale. A fresh listInbox() here is what makes the downloaded ZIP
    // actually appear (inbox + declared import roots). Read-only.
    setBusySafe(true);
    const g = generation.current;
    const fresh = await listInbox();
    if (!mounted.current || generation.current !== g) {
      setBusySafe(false);
      return;
    }
    setBusySafe(false);
    const data = fresh.ok ? (fresh.data as InboxData) : inbox;
    if (fresh.ok && data) setInbox(data);
    const items = data?.items || [];
    // Round 42: a file the plugin downloaded and a file the user fetched in the
    // Game Mode browser can share a name. Showing the root is the only way the
    // user can tell which one they are about to install.
    const rows: ListRow[] = items.map((it) => ({
      label: it.name,
      sub: `${it.root ? t("INBOX_ROOT", "from {root}", { root: it.root }) + "  ·  " : ""}${it.path}${it.size != null ? t("INBOX_BYTES", "  ·  {n} bytes", { n: it.size }) : ""}`,
      onActivate: (close) => {
        close();
        void inspectAndImport(it.path);
      },
    }));
    showListModal(
      t("INBOX_TITLE", "Local archives ({n})", { n: items.length }),
      rows,
      t("INBOX_SUB",
        "Looking in:\n{roots}\nA = preview / import · B = back. No network, no Workshop.",
        { roots: (data?.roots || []).map((r) => `${r.label}: ${r.path}${r.exists ? "" : " (absent)"}`).join("\n")
          || (data?.inbox || t("NOT_SET")) }),
    );
  };

  const inspectAndImport = async (path: string) => {
    setBusySafe(true);
    const g = generation.current;
    const r = await inspectZip(path);
    if (!mounted.current || generation.current !== g) {
      setBusySafe(false);
      return;
    }
    setBusySafe(false);
    if (!r.ok) {
      setError(r);
      return;
    }
    const d = r.data!;
    const fd = isFileDrop(status);
    const lines = [
      t("DETAIL_NAME", "Name:          {v}", { v: d.mod.name }),
      fd
        ? t("DETAIL_UID", "UniqueID:     {v}", { v: d.mod.packageId })
        : t("DETAIL_PID", "packageId:     {v}", { v: d.mod.packageId }),
      t("DETAIL_VERSION", "Version:       {v}{fb}", {
        v: d.mod.version,
        fb: d.mod.version_is_fallback ? t("DETAIL_VERSION_FB") : "",
      }),
      t("DETAIL_SUPPORTED", "Supported:     {v}", {
        v: d.mod.supportedVersions.join(", ") || t("UNSPECIFIED"),
      }),
      t("DETAIL_ENTRIES", "Entries / size:{n} / {b} bytes", {
        n: d.mod.entry_count, b: d.mod.uncompressed_size,
      }),
      t("DETAIL_DUP", "Duplicate:     {v}", {
        v: d.conflict.duplicate ? t("DETAIL_DUP_YES") : t("DETAIL_DUP_NO"),
      }),
      t("DETAIL_COLL", "File collision:{v}", {
        v: d.conflict.file_collision ? t("DETAIL_COLL_YES") : t("DETAIL_COLL_NO"),
      }),
      t("EMPTY_LINE"),
      // selection B: W1 is null for file_drop (no ModsConfig.xml).
      ...(fd ? [] : [t("DETAIL_W1", "W1 (state):  {v}", { v: d.targets.w1_state_file ?? t("EMPTY_W1") })]),
      t("DETAIL_W2", "W2 (target): {v}", { v: d.targets.w2_install_dir }),
    ];
    const badges = d.mod.badges || {};
    const loadAfter = badges.loadAfter || [];
    const dependencies = badges.dependencies || [];
    if (loadAfter.length || dependencies.length) {
      lines.push(
        t("EMPTY_LINE"),
        t("BADGES_TITLE"),
        t("BADGES_LOADAFTER", "  loadAfter={v}", { v: loadAfter.join(", ") || t("DASH") }),
        t("BADGES_DEPS", "  dependencies={v}", { v: dependencies.join(", ") || t("DASH") }),
      );
    }
    if (fd && badges.minimumApiVersion) {
      lines.push(t("EMPTY_LINE"), t("MIN_API", "Minimum SMAPI API: {v}", { v: badges.minimumApiVersion }));
    }
    // Round 27: a mod with this UniqueID may already be on disk under a folder
    // name the user chose. Installing would create a second copy that SMAPI
    // loads alongside the first, so say it here — before the import button.
    const sameUid = (d.conflict && (d.conflict as { same_unique_id_dirs?: string[] })
      .same_unique_id_dirs) || [];
    if (fd && sameUid.length) {
      lines.push(
        t("EMPTY_LINE"),
        t("DETAIL_SAME_UID_WARN",
          "Already on disk as {dirs}: installing would create a second copy with the same UniqueID. Disable or uninstall that one first.",
          { dirs: sameUid.join(", ") }),
      );
    }
    // Round 28 (criterion 3): if the archive carries a FOMOD config, say so.
    // A usable descriptor gets its own chooser button (single/multi); a broken
    // one is reported with a readable reason and the plain-import button remains
    // available (backend falls back to a full extract — never silent).
    const fomodDesc = d.fomod;
    const importSuccess = (res: OpResultData) =>
      fd
        ? t("IMPORT_OK_FD", "Installed & enabled {id} → {dir}. (file_drop: install == enable)",
            { id: res.packageId || d.mod.packageId, dir: res.dir || d.targets.w2_install_dir })
        : t("IMPORT_OK_XML", "Installed {id} → {dir}. NOT enabled yet (use Enable (A)).",
            { id: res.packageId || d.mod.packageId, dir: res.dir || d.targets.w2_install_dir });
    const actions: { label: string; onClick: (close: () => void) => void }[] = [];
    if (fomodDesc && fomodDesc.present && fomodDesc.usable && (fomodDesc.steps || []).length) {
      lines.push(t("EMPTY_LINE"), t("FOMOD_DETECTED"));
      actions.push({
        label: t("FOMOD_CHOOSE"),
        onClick: (close) => {
          close();
          showFomodModal(fomodDesc!, (choices) => {
            runTwoPhase(
              (ac) => installMod(path, ac, choices),
              importSuccess,
            );
          });
        },
      });
    } else if (fomodDesc && fomodDesc.present) {
      lines.push(
        t("EMPTY_LINE"),
        t("FOMOD_UNUSABLE", "FOMOD config could not be read ({reason}); will do a plain extract instead.",
          { reason: fomodDesc.reason || t("UNSPECIFIED") }),
      );
    }
    actions.push({
      label: t("BTN_IMPORT"),
      onClick: (close) => {
        close();
        runTwoPhase(
          (ac) => installMod(path, ac),
          importSuccess,
        );
      },
    });
    // Round 80: opt-in source cleanup. A separate action, never automatic —
    // a deleted ZIP cannot come back from the journal.
    actions.push({
      label: t("BTN_IMPORT_DELETE"),
      onClick: (close) => {
        close();
        runTwoPhase(
          (ac) => installMod(path, ac),
          importSuccess,
          undefined,
          async () => {
            const dr = await deleteZipSource(path);
            if (!dr.ok) { setError(dr); return null; }
            const name = path.split("/").pop() || path;
            const note = t("ZIP_REMOVED", "{name} deleted.", { name });
            toast(t("ZIP_REMOVED_TITLE"), note);
            return note;
          },
        );
      },
    });
    showInfo(t("DETAIL_MOD"), lines, actions, fd ? t("SUBTITLE_FD") : t("SUBTITLE_XML"));
  };

  /* -------------------------------------------------------------- §5.1 #4 details */
  const showModDetail = (mod: ManagedMod) => {
    const fd = isFileDrop(status);
    const q = t("Q_MARK");
    showInfo(
      mod.name || mod.packageId,
      [
        fd
          ? t("MODDETAIL_UID", "UniqueID:  {v}", { v: mod.packageId })
          : t("MODDETAIL_PID", "packageId:  {v}", { v: mod.packageId }),
        t("MODDETAIL_VERSION", "Version:    {v}", { v: mod.version || q }),
        // selection B: file_drop uses directory presence; no separate enable flag.
        ...(fd ? [] : [t("MODDETAIL_ENABLED", "Enabled:    {v}", {
          v: mod.enabled ? t("YES") : t("NO"),
        })]),
        t("MODDETAIL_DIR", "Directory:  {v}", { v: mod.dir || q }),
        t("MODDETAIL_TXN", "Txn:        {v}", { v: mod.txn || q }),
        t("EMPTY_LINE"),
        ...(fd ? [] : [t("MODDETAIL_W1", "W1 (state):    {v}", { v: status?.paths.w1_state_file || q })]),
        t("MODDETAIL_W2", "W2 (mod root): {v}", { v: status?.paths.w2_mod_root || q }),
        t("MODDETAIL_QUAR", "Quarantine:    {v}", { v: status?.paths.quarantine_root || q }),
        t("EMPTY_LINE"),
        fd ? t("MODDETAIL_FD_NOTE") : t("MODDETAIL_XML_NOTE"),
        fd ? t("MODDETAIL_FD_NOTE2") : t("MODDETAIL_XML_NOTE2"),
      ],
      [],
      t("MODDETAIL_FOOTER"),
    );
  };

  /* -------------------------------------------------------------- §5.1 #5 toggle
   * Round 25: file_drop games DO have a real enable/disable step now — the
   * backend moves the mod directory between Mods/ and its sibling
   * .decky-disabled/ (nothing deleted, ownership kept). The two-phase confirm is
   * reused so the UI never moves a directory without the user seeing it first. */
  const toggle = (mod: ManagedMod) => {
    const fd = isFileDrop(status);
    const next = !mod.enabled;
    setBusySafe(true);
    const g = generation.current;
    (async () => {
      let r: Envelope<unknown>;
      if (fd) {
        // file_drop: ask for the confirm plan first, then let ConfirmModal run
        // the same call with after_confirm=true. Nothing is written until then.
        const plan = await setModEnabled(mod.packageId, next, false);
        if (!mounted.current || generation.current !== g) {
          setBusySafe(false);
          return;
        }
        if (!plan.ok) {
          applyResult(plan as Envelope<unknown>, "");
          setBusySafe(false);
          return;
        }
        const pd = plan.data as ConfirmData;
        // The backend already returns a complete ConfirmData (phase/plan/…),
        // so hand it to the modal unchanged instead of rebuilding a subset.
        showConfirm(pd, async (okToProceed) => {
          if (!okToProceed) {
            setBusySafe(false);
            return;
          }
          const r2 = await setModEnabled(mod.packageId, next, true);
          if (!mounted.current || generation.current !== g) {
            setBusySafe(false);
            return;
          }
          finishToggle(r2, mod, next);
        });
        return;
      }
      // Reversible op: SKIP the dry-run confirm entirely (§5.1 #5).
      r = await setModEnabled(mod.packageId, next, true);
      finishToggle(r, mod, next);
    })();

    function finishToggle(r: Envelope<unknown>, mod0: ManagedMod, next0: boolean) {
      if (!mounted.current || generation.current !== g) {
        setBusySafe(false);
        return;
      }
      if (!r.ok) {
        applyResult(r as Envelope<unknown>, "");
        setBusySafe(false);
        return;
      }
      const d = (r.data || {}) as OpResultData;
      const stateWord = next0 ? t("MOD_ENABLED") : t("MOD_DISABLED");
      const msg = d.noop
        ? t("TOGGLE_NOOP", "{id} was already {state}.", { id: mod0.packageId, state: stateWord })
        : t("TOGGLE_OK", "{id} {state}. Reversible — History → Rollback.", { id: mod0.packageId, state: stateWord });
      setLastResult(msg);
      toast(
        next0 ? t("TOAST_MOD_ENABLED") : t("TOAST_MOD_DISABLED"),
        t("TOGGLE_TOAST_BODY", "{id} · reversible via History → Rollback", { id: mod0.packageId }),
      );
      later(() => setProgress(null), 1500);
      setBusySafe(false);
      void reload();
    }
  };

  /* -------------------------------------------------------------- §5.1 #6 uninstall */
  const doUninstall = (mod: ManagedMod) => {
    runTwoPhase(
      (ac) => uninstallMod(mod.packageId, ac),
      (res) =>
        t("UNINSTALL_OK", "Uninstalled {id}. Folder moved to quarantine (NOT deleted): {q}. Use History → Rollback to restore.",
          { id: res.packageId || mod.packageId, q: res.quarantine || t("Q_MARK") }),
    );
  };

  /* Round 20: uninstall a mod DIRECTORY that this plugin did not install.
   * The backend only accepts a single directory name, re-checks that it lives
   * directly under Mods/ and is not a symlink, still moves it to quarantine
   * (never deletes), and still runs the whole write gate. */
  const doUninstallDir = (dirName: string) => {
    // Round 56: use the self-contained flow (src/uninstallFlow.ts). It owns the
    // confirm modal at module scope so a Steam-CEF panel remount (triggered by
    // closing the previous modal) cannot swallow the phase-1 result — the bug
    // that made "Uninstall" look dead even though the backend answered.
    setBusySafe(true);
    runUninstallFlow(dirName, (res) => {
      setBusySafe(false);
      if (res.done && res.ok) {
        toast(
          t("TOAST_DONE"),
          t("UNINSTALL_OK", "Uninstalled {id}. Folder moved to quarantine (NOT deleted): {q}. Use History → Rollback to restore.",
            { id: dirName, q: t("Q_MARK") }),
        );
        // Refresh from the on-disk journal. If the panel remounted, this instance
        // is stale and guarded by reload() itself; the fresh panel bootstraps too.
        void reload();
      } else if (!res.ok) {
        setError({
          ok: false,
          code: res.code ?? null,
          message: res.code || t("STATUS_FAILED", "Failed"),
          detail: res.detail ?? "",
        } as Envelope<unknown>);
      }
      // Cancelled: no-op (the global modal already closed itself).
    });
  };

  /* -------------------------------------------------------------- §5.1 #7 history/rollback */
  const openHistory = async () => {
    setBusySafe(true);
    const g = generation.current;
    const r = await getHistory(50);
    if (!mounted.current || generation.current !== g) {
      setBusySafe(false);
      return;
    }
    setBusySafe(false);
    if (!r.ok) {
      setError(r);
      return;
    }
    const items = r.data?.items || [];
    const txns: string[] = [];
    for (const it of items) {
      if (it.txn && !txns.includes(it.txn)) txns.push(it.txn);
    }
    const rows: ListRow[] = txns.map((txn) => {
      const group = items.filter((i) => i.txn === txn);
      const desc = describeTxn(group);
      const when = txnTime(txn);
      const q = group.find((i) => i.event === "MOD_UNINSTALLED")?.quarantine
        || (group.find((i) => i.event === "COMMITTED")?.detail?.quarantine as string)
        || status?.paths.quarantine_root || "";
      return {
        // Say what happened in plain language; the raw txn id moves to sub.
        label: desc.label,
        sub: `${when}  ·  ${txn}  ·  ${t("HIST_RESTORE_HINT", "A = restore")}`,
        onActivate: (_close: () => void) => {
          // Do NOT _close(): closing a Decky modal remounts the panel and the
          // global confirm from runRollbackFlow replaces this modal cleanly.
          confirmRollback(txn, desc.mod || txn, q);
        },
      };
    });
    showListModal(
      t("HISTORY_TITLE", "History — roll back a transaction ({n})", { n: txns.length }),
      rows,
      t("HISTORY_SUB2", "Pick an action to restore its mod folder from quarantine. Nothing is deleted."),
    );
  };

  const confirmRollback = (txn: string, modLabel?: string, quarantinePath?: string) => {
    // Round 69: self-contained rollback flow. The old version used showConfirm
    // + panel mounted/generation guards; closing the History modal remounted the
    // panel and swallowed the confirm → the rollback RPC never fired. The flow
    // now lives at module scope (src/rollbackFlow.tsx) with a global modal.
    const quarantine = quarantinePath || status?.paths.quarantine_root || t("ROLLBACK_SEE_STATUS");
    runRollbackFlow(txn, modLabel || txn, quarantine, (res) => {
      if (!res.ok) {
        setLastResult(t("STATUS_FAILED", "Failed: {msg}", { msg: res.detail || res.code || "?" }));
        return;
      }
      if (res.restored) {
        const msg = t("ROLLBACK_DONE", "Rolled back {txn}: restored {d}.", { txn, d: res.restored });
        setLastResult(msg);
        toast(t("TOAST_ROLLBACK"), msg);
      }
      void reload();
    });
  };

  /* -------------------------------------------------------------- §5.1 #9 refresh */
  const doRefresh = () => {
    setBusySafe(true);
    const g = generation.current;
    (async () => {
      const r = await refreshStatus();     // re-resolve + verify_on_open drift check
      if (!mounted.current || generation.current !== g) {
        setBusySafe(false);
        return;
      }
      if (!r.ok) {
        applyResult(r, "");
        setBusySafe(false);
        return;
      }
      setStatus(r.data);
      const i = await listInbox();
      if (!mounted.current || generation.current !== g) {
        setBusySafe(false);
        return;
      }
      if (i.ok) setInbox(i.data);
      setLastResult(t("TOAST_REFRESHED_BODY"));
      toast(t("TOAST_REFRESHED"), t("TOAST_REFRESHED_BODY"));
      setBusySafe(false);
    })().catch((e) => {
      if (!mounted.current) return;
      setBusySafe(false);
      setError(bridgeError(String(e)));
    });
  };

  /* -------------------------------------------------------------- E_RECOVERY_PENDING */
  const openRecovery = async () => {
    const r = await getRecovery();
    if (!mounted.current) return;
    if (!r.ok) {
      setError(r);
      return;
    }
    const pending = r.data?.pending || [];
    const stuck = r.data?.stuck || [];
    // Round 72: a transaction whose rollback failed does not block writes, so
    // it never appeared under "pending" -- but it is exactly the one whose
    // folder holds the only copy of the old version. Same modal, same action,
    // different description.
    const rows: ListRow[] = [
      ...pending.map((tx) => ({
        label: tx,
        sub: t("RECOVERY_SUB"),
        onActivate: (_close: () => void) => {
          confirmRollback(tx);
        },
      })),
      ...stuck.map((tx) => ({
        label: tx,
        sub: t("RECOVERY_STUCK_SUB"),
        onActivate: (_close: () => void) => {
          confirmRollback(tx);
        },
      })),
    ];
    showListModal(
      t("RECOVERY_TITLE"),
      rows,
      t("RECOVERY_SUBTITLE"),
    );
  };

  /* -------------------------------------------------------------- §5.2 error reference */
  const openErrorCodes = async () => {
    const r = await getErrorCodes();
    if (!mounted.current) return;
    if (!r.ok) {
      setError(r);
      return;
    }
    const rows: ListRow[] = (r.data?.codes || []).map((c) => ({
      label: t("ERRCODE_ROW", "{code} · {cat}", { code: c.code, cat: categoryText(c.category) }),
      sub: t("ERRCODE_SUB", "{msg}{rb}", {
        msg: errorText(c.code, c.message),
        rb: c.rollback_available ? t("ERRCODE_RB") : "",
      }),
      onActivate: () => showInfo(c.code, [errorText(c.code, c.message)], [], categoryText(c.category)),
    }));
    showListModal(
      t("ERRCODE_TITLE", "Error codes ({n})", { n: r.data?.count ?? rows.length }),
      rows,
      t("ERRCODE_SUBTITLE"),
    );
  };

  /* -------------------------------------------------------------- §Goal item 2 game library
   * Read-only. `list_games` only stats appmanifests, so opening this list can
   * never change anything. Games with no descriptor are shown with an explicit
   * "not adapted yet" note instead of being hidden — the goal forbids silent
   * failure, and a missing adapter must be visible rather than guessed at.
   */
  const openGameLibrary = async () => {
    setBusySafe(true);
    try {
      const r = await listGames();
      if (!mounted.current) return;
      if (!r.ok) {
        setError(r);
        return;
      }
      const data = r.data;
      const games = data?.games || [];
      if (!games.length) {
        showInfo(t("LIB_SECTION"), [t("LIB_NO_GAMES")], [], t("LIB_SECTION_DESC"));
        return;
      }
      // Which AppIDs actually have an adapter. Sourced from the backend catalog
      // (descriptor-driven), never from a literal list here — otherwise the UI
      // would drift from the backends the moment a descriptor changes.
      const adaptedIds = (status?.catalog || [])
        .filter((c) => c.operable && c.appid !== null)
        .map((c) => c.appid as number);
      const stateWord = (s: SteamGame["state"]): string =>
        s === "installed" ? t("LIB_STATE_INSTALLED")
          : s === "incomplete" ? t("LIB_STATE_INCOMPLETE")
            : t("LIB_STATE_UNKNOWN");
      const rows: ListRow[] = games.map((g) => ({
        label: t("LIB_GAME_ROW", "{name} · {appid}", { name: g.name, appid: g.appid }),
        sub: t("LIB_GAME_DESC", "AppID {appid} · {state}", {
          appid: g.appid, state: stateWord(g.state),
        }),
        onActivate: () => {
          // Annotated explicitly: without it TS widens this to string[] and the
          // `+` below becomes an array-concat error rather than a spread.
          const lines: string[] = [
            t("LIB_PATH_ROW", "Library: {p}", { p: g.library }),
            t("LIB_INSTALL_ROW", "Install path: {p}", { p: g.install_path || "—" }),
            g.compatdata
              ? t("LIB_PREFIX_ROW", "Proton prefix: {p}", { p: g.compatdata })
              : t("LIB_PREFIX_NONE_ROW", "No compatdata prefix (native Linux title)"),
          ];
          // Standard 4: show the identified Mod directory when a template
          // exists; otherwise say "not adapted" explicitly and guess nothing.
          // A writable=false template is identification-only — never imply the
          // game is operable just because we recognise where its mods live.
          const tpl = g.template;
          if (tpl && tpl.adapted) {
            const dirs = (tpl.mod_dirs || []).map((d) =>
              t("LIB_MODDIR_ROW", "{p} ({state})", {
                p: d.path || "—",
                state: d.exists ? t("LIB_MODDIR_YES") : t("LIB_MODDIR_NO"),
              }));
            lines.push(t("LIB_MODDIR_TITLE", "Mod directory template:"));
            for (const d of dirs) lines.push(d);
            if (tpl.loader) lines.push(t("LIB_LOADER_ROW", "Expected loader: {l}", { l: tpl.loader }));
            if (!tpl.writable) lines.push(t("LIB_IDENTIFY_ONLY"));
          } else if (!adaptedIds.includes(g.appid)) {
            lines.push(t("LIB_UNSUPPORTED_NOTE"));
          }
          // The game's Nexus domain comes from the descriptor-driven catalog,
          // matched by AppID. No hard-coded name -> domain table in the UI.
          const gDomain = (status?.catalog || []).find(
            (c) => c.appid === g.appid)?.nexus_domain || null;
          const activeAppid = (status?.catalog || []).find((c) => c.active)?.appid;
          const isActive = activeAppid !== null && activeAppid !== undefined
            && g.appid === activeAppid;
          const actions: ModalAction[] = [];
          // Primary path: this game's MOD list with per-mod actions (manage).
          actions.push({
            label: t("GAME_MANAGE_MODS", "Manage mods for {game}", { game: g.name }),
            onClick: (close) => {
              close();
              later(() => openGameMods(g), 250);
            },
          });
          if (gDomain) {
            // Secondary path: look up a mod by its Nexus ID, prefix pre-filled.
            actions.push({
              label: t("LIB_NEXUS_BY_ID", "Find a Nexus mod by ID for {game}", { game: g.name }),
              onClick: (close) => {
                close();
                setNexusDomain(gDomain);
                setNexusModId("");
                setOpenSection("import");
                setLastResult(t("NEXUS_PREFIX_READY", undefined, {
                  domain: gDomain, prefix: `https://www.nexusmods.com/${gDomain}/mods`,
                }));
              },
            });
          }
          showInfo(
            g.name,
            [...lines, isActive ? t("GAME_ACTIVE_HINT") : ""].filter((x) => x !== ""),
            actions,
            t("LIB_GAME_DESC", "AppID {appid} · {state}", {
              appid: g.appid, state: stateWord(g.state),
            }),
          );
        },
      }));
      showListModal(
        t("LIB_COUNT", "{libs} libraries · {games} games installed · {removable} on removable media", {
          libs: data?.library_count ?? 0,
          games: data?.game_count ?? rows.length,
          removable: data?.removable_count ?? 0,
        }),
        rows,
        t("LIB_SECTION_DESC"),
      );
    } catch (e) {
      if (!mounted.current) return;
      setError(bridgeError(String(e)));
    } finally {
      setBusySafe(false);
    }
  };

  /* -------------------------------------------------------------- Round 40 loader log */
  // The log tells us what the SMAPI loader actually did last launch. A missing
  // entry means "installed but the game never reported it" -- which is NOT the
  // same as working, so the label says so and never claims success.
  const loadStatusLabel = (s0?: ModListEntry["load_status"]): string => {
    if (s0 === "loaded") return t("LOAD_STATUS_LOADED");
    if (s0 === "content_pack") return t("LOAD_STATUS_PACK");
    if (s0 === "skipped") return t("LOAD_STATUS_SKIPPED");
    if (s0 === "patched") return t("LOAD_STATUS_PATCHED");
    if (s0 === "unknown") return t("LOAD_STATUS_UNKNOWN");
    return "";
  };
  const loadStatusNote = (m: ModListEntry): string =>
    t("LOAD_DETAIL_STATUS", "Last launch: {status}", { status: loadStatusLabel(m.load_status) });

  /* -------------------------------------------------------------- §Step 2 read-only mod list */
  const openModList = () => {
    // Round 25: enabled mods live in Mods/, disabled ones are parked in the
    // sibling .decky-disabled/. Both are shown, otherwise disabling a mod would
    // make it disappear from the UI with no way to bring it back.
    const disabled: ModListEntry[] = st?.disabled_mods || [];
    const mods: ModListEntry[] = [...(st?.mods || []), ...disabled];
    const dupMap = new Map<string, string[]>();
    (st?.duplicate_ids || []).forEach(([uid, dirs]) => {
      dirs.forEach((d) => dupMap.set(d, (dupMap.get(d) || []).concat(
        dirs.filter((x) => x !== d),
      )));
    });
    // Round 20: file_drop can now uninstall a pre-existing directory too, so the
    // detected list is no longer purely read-only. The engine still gates every
    // write (read_only => E_EXTERNAL_MANAGER), so the button is only offered
    // when writes are actually allowed.
    const canRemove = fd && !readOnly;
    // Round 25: a parked mod can be ENABLED again (moved back into Mods/).
    const canToggleDisabled = fd && !readOnly && canToggle;
    const disabledDirs = new Set(disabled.map((d) => d.dir));
    const rows: ListRow[] = mods.map((m) => {
      const isParked = disabledDirs.has(m.dir);
      // Round 49: the mod's own UpdateKeys are the only trustworthy source for
      // "which Nexus page is this?". Guessing from the name would open someone
      // else's mod, so an absent key yields no button at all.
      const keys = m.update_keys || [];
      const nx = keys.filter((k) => (k.site || "").toLowerCase() === "nexus" && k.id)[0];
      const nxId = nx ? Number(nx.id) : NaN;
      const onActivate = () =>
        showInfo(
          m.name || m.dir,
          [
            t("MODLIST_ROW", "{name} · v{version} · {author}", {
              name: m.name || m.dir,
              version: m.version || t("Q_MARK"),
              author: m.author || t("UNSPECIFIED"),
            }),
            isParked ? t("MODDETAIL_DISABLED", "State: disabled (parked in .decky-disabled/, not loaded by the game)") : "",
            m.uniqueId ? t("MODDETAIL_UID", "UniqueID:  {v}", { v: m.uniqueId }) : "",
            t("MODDETAIL_DIR", "Directory:  {v}", { v: m.dir }),
            ...(!isParked && m.load_status ? [loadStatusNote(m)] : []),
            ...(!isParked && m.load_version
              ? [t("LOAD_DETAIL_VERSION", "Log version: {v}", { v: m.load_version })] : []),
            ...(!isParked && m.load_missing_ids && m.load_missing_ids.length
              ? [t("LOAD_DETAIL_MISSING", "It needs: {v}", { v: m.load_missing_ids.join(", ") })] : []),
            ...(!isParked && m.load_reason
              ? [t("LOAD_DETAIL_REASON", "Why it was skipped: {v}", { v: m.load_reason })] : []),
            ...(m.dependencies && m.dependencies.length
              ? [t("MODLIST_DEPS", "Dependencies: {v}", { v: m.dependencies.join(", ") })] : []),
            ...(m.missing_dependencies && m.missing_dependencies.length
              ? [t("MODLIST_MISSING_DEPS", "Missing dependencies: {v}", { v: m.missing_dependencies.join(", ") })] : []),
            ...(m.parked_dependencies && m.parked_dependencies.length
              ? [t("MODLIST_PARKED_DEPS", "Dependencies installed but disabled: {v} (enable them)", { v: m.parked_dependencies.join(", ") })] : []),
            ...(m.parse_error
              ? [t("MODLIST_PARSE_ERR", "Manifest error: {v}", { v: m.parse_error })] : []),
            ...(keys.length
              ? [t("MODDETAIL_KEYS", "Declared update keys: {v}", {
                  v: keys.map((k) => `${k.site}:${k.id}${k.channel ? "@" + k.channel : ""}`).join(", "),
                })] : []),
          ].filter((x) => x !== ""),
          [
            ...(isParked && canToggleDisabled
              ? [{
                  label: t("BTN_ENABLE"),
                  onClick: (close: () => void) => {
                    close();
                    // Let this detail modal finish closing before the two-phase
                    // runner opens its confirm modal — Decky's showModal allows
                    // only one overlay, and a close→open in the same tick drops
                    // the second modal (the button looked dead).
                    later(() => toggle({ packageId: m.dir, name: m.name, enabled: false } as ManagedMod), 250);
                  },
                }]
              : []),
            ...(!isParked && canToggleDisabled
              ? [{
                  label: t("BTN_DISABLE"),
                  onClick: (close: () => void) => {
                    close();
                    later(() => toggle({ packageId: m.dir, name: m.name, enabled: true } as ManagedMod), 250);
                  },
                }]
              : []),
            ...(canRemove && !isParked
              ? [{
                  label: t("BTN_UNINSTALL"),
                  onClick: (_close: () => void) => {
                    // Round 56: the confirm must survive the Steam-CEF panel
                    // remount that closing a Decky modal triggers. The flow is
                    // now self-contained (src/uninstallFlow.ts) and uses only
                    // module state + a global modal — no component generation
                    // guard. We intentionally do NOT close() the detail modal:
                    // the global confirm overlay replaces it, and closing it
                    // first was what caused the remount that swallowed the
                    // old runTwoPhase result.
                    doUninstallDir(m.dir);
                  },
                }]
              : []),
            ...(Number.isInteger(nxId) && nxId > 0
              ? [{
                  label: t("OPEN_PAGE_BTN", "Open mod page"),
                  onClick: (close: () => void) => {
                    close();
                    doOpenPage(nxId);
                  },
                }]
              : []),
          ],
          t("MODDETAIL_FOOTER"),
        );
      if (m.parse_error || !m.name) {
        return {
          label: t("MODLIST_ROW_UNKNOWN", "{dir} · (manifest unreadable)", { dir: m.dir }),
          sub: m.parse_error ? t("MODLIST_PARSE_ERR", "Manifest error: {v}", { v: m.parse_error }) : "",
          onActivate,
        };
      }
      const notes: string[] = [];
      if (isParked) notes.push(t("MODLIST_BADGE_DISABLED"));
      // Round 40: parked mods are deliberately absent from the log, so only an
      // ACTIVE mod gets a load badge (a parked one would read as "not loaded"
      // when that is exactly what the user asked for).
      if (!isParked && m.load_status) notes.push(loadStatusLabel(m.load_status));
      if (m.missing_dependencies && m.missing_dependencies.length) {
        notes.push(t("MODLIST_MISSING_DEPS", "Missing dependencies: {v}", {
          v: m.missing_dependencies.join(", "),
        }));
      }
      // Round 66: a disabled dependency is the user's own switch, so it is
      // reported with the action that fixes it instead of as a gap.
      if (m.parked_dependencies && m.parked_dependencies.length) {
        notes.push(t("MODLIST_PARKED_DEPS",
          "Dependencies installed but disabled: {v} (enable them)", {
            v: m.parked_dependencies.join(", "),
          }));
      }
      // Round 67: installed but older than this mod asks for. SMAPI skips
      // the whole mod in that state, so it is stated with the version it
      // needs. Round 40: the old wording promised an in-plugin upgrade this
      // plugin does not have -- fetch_dependencies reads only missing_dependencies, never
      // outdated ones. Point at the path that DOES exist: fetch a newer copy
      // and import it here, which upgrades through the normal verified flow.
      if (m.outdated_dependencies && m.outdated_dependencies.length) {
        notes.push(t("MODLIST_OUTDATED_DEPS",
          "Dependencies below required version: {v} (download a newer copy, then import it here)", {
            v: m.outdated_dependencies
              .map((d) => `${d.id} ${d.installed} < ${d.required}`)
              .join(", "),
          }));
      }
      const others = dupMap.get(m.dir) || [];
      if (others.length) {
        notes.push(t("MODLIST_DUP_ID", "Duplicate UniqueID also in: {v}", { v: others.join(", ") }));
      }
      // Round 71: the reverse direction, on the row of the mod being depended
      // on. This is the one place that answers "may I remove this?" before the
      // user asks, and it costs nothing -- the scan already had every row.
      if (m.dependents && m.dependents.length) {
        notes.push(t("MODLIST_DEPENDENTS", "Other mods need this one: {v}", {
          v: m.dependents.map((d) => d.name || d.id).join(", "),
        }));
      }
      return {
        label: t("MODLIST_ROW", "{name} · v{version} · {author}", {
          name: m.name, version: m.version || t("Q_MARK"), author: m.author || t("UNSPECIFIED"),
        }),
        sub: notes.join(" · "),
        onActivate,
      };
    });
    const summary: string[] = [];
    if (st?.missing_dependencies && st.missing_dependencies.length) {
      summary.push(t("MODLIST_SUMMARY_DEPS", "Missing dependencies: {v}", {
        v: st.missing_dependencies.join(", "),
      }));
    }
    if (st?.parked_dependencies && st.parked_dependencies.length) {
      summary.push(t("MODLIST_SUMMARY_PARKED_DEPS",
        "Dependencies installed but disabled: {v}", {
          v: st.parked_dependencies.join(", "),
        }));
    }
    if (st?.outdated_dependencies && st.outdated_dependencies.length) {
      summary.push(t("MODLIST_SUMMARY_OUTDATED_DEPS",
        "Dependencies too old: {v}", {
          v: st.outdated_dependencies
            .map((d) => `${d.id} ${d.installed} < ${d.required}`)
            .join(", "),
        }));
    }
    if (st?.duplicate_ids && st.duplicate_ids.length) {
      summary.push(t("MODLIST_SUMMARY_DUP", "Duplicate IDs: {v}", {
        v: st.duplicate_ids.map(([uid]) => uid).join(", "),
      }));
    }
    showListModal(
      t("MODLIST_TITLE", "Detected mods ({n})", { n: mods.length }),
      rows,
      [t("MODLIST_SUB"), ...summary].join("\n"),
    );
  };

  /* ---------------------------------------------------------- game-centric mods */
  /* Enter a game's mod list. The single active game has FULL metadata in
     status.state (name/version/deps/nexus keys) and every write RPC works, so
     its mods reuse openModList() with all actions. Any other installed game is
     identified read-only from its template (folder names only) -- the plugin
     never implies it can manage a game it has no descriptor for. */
  const openGameMods = (game: SteamGame) => {
    const activeAppid = (status?.catalog || []).find((c) => c.active)?.appid;
    if (activeAppid !== null && activeAppid !== undefined && game.appid === activeAppid) {
      openModList();
      return;
    }
    // Round 78: an operable but non-active game used to fall into the
    // read-only display below — labelled "not managed by this plugin" even
    // though one tap in the Games section would manage it. Offer the actions
    // where the user is looking instead of making them hunt for the switch.
    const cat = (status?.catalog || []).find((c) => c.appid === game.appid);
    if (cat && cat.operable) {
      // Round 79 (device finding): "Change mod folders" must only be offered
      // for USER-configured games — offering it for a built-in descriptor let
      // Stardew Valley be re-configured as a root_merge game, which shadowed
      // its SMAPI management.
      const isUserConfigured = cat.id.startsWith("user_");
      showListModal(
        game.name,
        [
          {
            label: t("GAME_MGMT_SWITCH", "Make this the managed game"),
            sub: t("GAME_SWITCH_DESC",
              "Make this the managed game. Nothing is deleted — the other game's mods stay untouched."),
            onActivate: (close) => { close(); doSwitchGame(cat.id, cat.name || cat.id); },
          },
          {
            label: t("GAME_MGMT_SETUP", "Change mod folders…"),
            sub: t("GAME_MGMT_SETUP_SUB",
              "Re-pick where this game's loader reads mods from, or remove the configuration."),
            onActivate: (close) => { close(); openGameSetup(game); },
            disabled: !isUserConfigured,
          },
        ],
        isUserConfigured
          ? t("GAME_MGMT_SUB", "This game can be managed by the plugin.")
          : t("GAME_MGMT_BUILTIN_SUB",
              "Built-in adaptation: the mod folders are fixed by the descriptor — no manual setup needed."),
      );
      return;
    }
    const tpl = game.template;
    const lines: string[] = [];
    if (tpl && tpl.adapted) {
      for (const d of tpl.mod_dirs || []) {
        lines.push(t("LIB_MODDIR_ROW", "{p} ({state})", {
          p: d.path || "—",
          state: d.exists ? t("LIB_MODDIR_YES") : t("LIB_MODDIR_NO"),
        }));
        for (const n of d.mods || []) lines.push("  " + n);
        if (d.truncated) lines.push(t("MODS_BY_GAME_TRUNCATED"));
      }
    } else {
      lines.push(t("LIB_UNSUPPORTED_NOTE"));
    }
    showInfo(
      game.name,
      [...lines, "", t("GAME_MODS_READONLY")],
      [],
      t("GAME_MODS_SUBTITLE", "Identified read-only — not managed by this plugin"),
    );
  };

  /* -------------------------------------------------------------- P0 (round 2) read-only game catalog */
  /* Display-only "Plane 1": shows every descriptor as browsable metadata.
     It NEVER calls an install/enable RPC and never lifts the single-active-game
     write gate. Planned / unsupported games are marked "catalog-only, not
     installable". A opens a read-only detail dialog; B goes back. */
  const openGameCatalog = () => {
    const games: CatalogEntry[] = status?.catalog || [];
    // Typed to accept `undefined` too so older backends that omit appid stay
    // safe without provoking TS2367 (number|null vs undefined) under strict.
    const appidText = (a: number | null | undefined): string =>
      a === null || a === undefined ? t("CATALOG_NA") : String(a);
    const rows: ListRow[] = games.map((g) => ({
      label: t("CATALOG_ROW", "{name} · AppID {appid} · {platform}", {
        name: g.name,
        appid: appidText(g.appid),
        platform: g.platform,
      }),
      sub: g.operable ? t("CATALOG_OPERABLE") : t("CATALOG_ONLY"),
      onActivate: () =>
        showInfo(
          g.name,
          [
            t("CATALOG_DETAIL_APPID", "AppID: {v}", { v: appidText(g.appid) }),
            t("CATALOG_DETAIL_PLATFORM", "Platform: {v}", { v: g.platform }),
            t("CATALOG_DETAIL_STATUS", "Status: {v}", { v: g.status }),
            t("CATALOG_DETAIL_ENGINE", "Engine: {v}", { v: g.engine }),
            t("CATALOG_DETAIL_LOADERS", "Loaders: {v}", {
              v: g.loaders.length ? g.loaders.join(", ") : t("CATALOG_LOADERS_NONE"),
            }),
            g.operable ? t("CATALOG_OPERABLE") : t("CATALOG_ONLY"),
          ],
          [],
          t("CATALOG_DETAIL_FOOTER"),
        ),
    }));
    showListModal(
      t("CATALOG_TITLE", "Game catalog (read-only, {n})", { n: games.length }),
      rows,
      t("CATALOG_SUB"),
    );
  };

  /* -------------------------------------------------------------- round 19: download sources
   * ALL network I/O lives in the PYTHON BACKEND (deckymod/github_source.py +
   * download.py). This panel only drives 4 positional RPCs; Steam CEF never opens
   * a socket and never sees a credential, because the legacy credential surface
   * was retired entirely.
   *
   * Both download paths are three-phase and strictly ordered, so a UI mistake
   * cannot cause a write:
   *   phase 1 (false, false) -> download + inspect, nothing written
   *   phase 2 (true,  false) -> plan shown, nothing written
   *   phase 3 (true,  true ) -> engine.install(), ENGINE-GATED
   * Phase 3 returns whatever the engine says. On a Mods folder owned by another
   * manager that is E_EXTERNAL_MANAGER, and it is surfaced through the uniform
   * error modal — never hidden, never bypassed, never retried.
   */




  /* ----------------------------------------------------- §5.3b dependencies */
  // Round 74: one entry point. The old pair of buttons split "look at the
  // plan" from "install", and neither could do anything when the SMAPI index
  // named no GitHub repo — the panel just said 0 of N. runDepsFlow() now owns
  // planning, installing what it can, and opening the Nexus page for the rest.
  const doDepsInstall = () => runDepsFlow();

  /** Browse one of the three feeds. There is no search because there is no endpoint. */
  const doNexusRecent = (kind: string) => {
    // Round 73: no API key needed. The Nexus API's recent() requires a personal
    // key a free account may not have; the WEBSITE shows the same sorts to a
    // signed-in browser. Open that page instead of failing with E_CAPABILITY_*.
    setBusySafe(true);
    const g = generation.current;
    (async () => {
      const r = await openBrowsePage(kind);
      if (!mounted.current || generation.current !== g) { setBusySafe(false); return; }
      setBusySafe(false);
      if (!r.ok) {
        const url = (r.data && r.data.url) || "";
        setLastResult(t("OPEN_PAGE_FAIL", undefined, { reason: r.detail || r.code || "—" }));
        showInfo(
          t("NEXUS_RECENT_TITLE"),
          [
            t("OPEN_PAGE_FAIL", undefined, { reason: r.detail || r.code || "—" }),
            "",
            t("OPEN_PAGE_WHY"),
            url ? t("NEXUS_BROWSER_URL", undefined, { url }) : "",
          ],
          [],
          t("NEXUS_SECTION"),
        );
        return;
      }
      setLastResult(t("NEXUS_BROWSE_OPENED", undefined, {
        url: (r.data && r.data.url) || "",
      }));
    })().catch((e) => {
      if (!mounted.current) return;
      setBusySafe(false);
      setError(bridgeError(String(e)));
    });
  };

  /** Metadata + file list for one mod. Downloads nothing. */
  const doNexusMod = () => {
    const raw = nexusModId.trim();
    if (!/^\d+$/.test(raw)) {
      showInfo(t("NEXUS_MOD_TITLE"), [t("NEXUS_BAD_ID")], []);
      return;
    }
    // Round 73: open the mod's page directly — no API key needed. The old path
    // called nexusMod(), which needs a personal key and failed with
    // E_CAPABILITY_DISABLED for accounts that never configured one. The browser
    // is already signed in, so it shows the real page + download button.
    doOpenPage(Number(raw));
  };

  /**
   * Show a mod's page in the Game Mode browser.
   *
   * Round 41 measured three ways to do this on the device and only one works:
   * `xdg-open` exits 0 while opening nothing (no DISPLAY in the plugin process),
   * and forcing DISPLAY=:0 makes it choke on the .desktop Exec line, while
   * `steam steam://openurl/<url>` really lands a tab in the Steam client. So the
   * failure branch says the page did not appear instead of pretending it did --
   * a silent success here sends the user hunting for an invisible window.
   */
  const doOpenPage = (modId: number) => {
    setBusySafe(true);
    const g = generation.current;
    (async () => {
      const r = await openModPage(modId);
      if (!mounted.current || generation.current !== g) { setBusySafe(false); return; }
      setBusySafe(false);
      if (!r.ok) {
        const url = (r.data && r.data.url) || "";
        const why = r.detail || r.code || "—";
        setLastResult(t("OPEN_PAGE_FAIL", undefined, { reason: why }));
        showInfo(
          t("NEXUS_SECTION"),
          [
            t("OPEN_PAGE_FAIL", undefined, { reason: why }),
            "",
            t("OPEN_PAGE_WHY"),
            "",
            url ? t("NEXUS_BROWSER_URL", undefined, { url }) : "",
          ],
          [],
          t("NEXUS_SECTION"),
        );
        return;
      }
      setLastResult(t("OPEN_PAGE_OK", undefined, { url: (r.data && r.data.url) || "" }));
    })().catch((e) => {
      if (!mounted.current) return;
      setBusySafe(false);
      setError(bridgeError(String(e)));
    });
  };

  /**
   * Round 43: run a keyword search where search actually exists.
   *
   * The API has no search endpoint, so this opens the website's search page
   * with the keyword applied. Two outcomes must stay distinguishable: the
   * client accepted the address (success), or it did not (failure with the
   * address printed). Anything else would repeat the xdg-open mistake, where
   * an exit code of 0 accompanied nothing appearing on screen.
   */
  const doSearch = () => {
    const q = searchText.trim();
    if (!q) {
      setLastResult(t("SEARCH_EMPTY"));
      return;
    }
    setBusySafe(true);
    const g = generation.current;
    (async () => {
      const r = await openSearchPage(q);
      if (!mounted.current || generation.current !== g) { setBusySafe(false); return; }
      setBusySafe(false);
      if (!r.ok) {
        const url = (r.data && r.data.url) || "";
        const why = r.detail || r.code || "—";
        setLastResult(t("SEARCH_FAIL"));
        showInfo(
          t("SEARCH_SECTION"),
          [
            t("SEARCH_FAIL"),
            t("SEARCH_WHY"),
            "",
            url ? t("NEXUS_BROWSER_URL", undefined, { url }) : why,
          ],
          [],
          t("SEARCH_SECTION"),
        );
        return;
      }
      setLastResult(t("SEARCH_OK"));
    })().catch((e) => {
      if (!mounted.current) return;
      setBusySafe(false);
      setError(bridgeError(String(e)));
    });
  };

  /* -------------------------------------------------------------- render */
  const installed = status?.installed || [];
  const paths = status?.paths;
  // GAP2: prefer stable i18n keys from the descriptor; fall back to the
  // original English DATA lines for older backends.
  const limitationKeys = status?.known_limitation_keys || [];
  const limitations = limitationKeys.length
    ? limitationKeys.map((k) => t(k))
    : (status?.known_limitations || []);
  const fd = isFileDrop(status);
  const caps = status?.capabilities || {};
  const canToggle = fd ? !!caps.enable_disable : true;
  // Round 44: "read-only" alone tells the user nothing actionable. The backend
  // now returns a structural survey of the mod folder (symlinked folder, symlinked
  // entries, another filesystem), so the banner can name the actual cause.
  const foreignWhy = (): string => {
    const lay = status?.state?.layout;
    if (!lay || !lay.reasons || !lay.reasons.length) return "";
    const bits: string[] = [];
    for (const r of lay.reasons) {
      if (r === "mods_dir_missing") continue;
      if (r === "mods_dir_is_symlink") bits.push(t("LAYOUT_WHY_SYMLINK"));
      else if (r === "symlinked_entry") {
        const names = (lay.symlinked || []).join(", ");
        const total = lay.symlinked_count || (lay.symlinked || []).length;
        const more = total > (lay.symlinked || []).length ? ` (+${total - (lay.symlinked || []).length})` : "";
        bits.push(t("LAYOUT_WHY_ENTRIES", undefined, { names: names + more }));
      } else if (r === "mods_on_other_device") bits.push(t("LAYOUT_WHY_DEVICE"));
      else bits.push(r);
    }
    return bits.join(" ");
  };
  const readOnly = fd ? !!status?.state?.read_only : false;
  const st = status?.state;
  // Round 40: absent on older backends, so every use is optional.
  const ll = status?.loader_log;
  /**
   * Round 47: one line summarising shared paths, or "" when there is nothing
   * to say. Deliberately a summary and not a wall: a user with a big mod pack
   * can easily have dozens, and a panel is not a diff view.
   */
  /**
   * Round 48: quarantine folders whose uninstall record is gone. Those hold
   * data no code path can restore, while the user reasonably believes they are
   * recoverable. Shown only when the folder actually contains something --
   * an empty orphan is clutter, not a warning.
   */
  // Round 50. The gate refuses writes while the game runs, so the panel
  // must be able to say so -- a bare E_GAME_RUNNING reads as a bug.
  const runningLine = (): string => {
    const rr = status?.state?.running;
    if (!rr || !rr.state || rr.state === "stopped") return "";
    if (rr.state === "running") {
      return t("RUNNING_LINE", "The game is running -- close it before changing mods.");
    }
    return t("RUNNING_UNKNOWN", "Whether the game is running could not be checked.");
  };
  const quarantineLine = (): string => {
    const q = status?.state?.quarantine;
    if (!q || !q.checked) return "";
    if (q.journal === "unreadable") return t("QUAR_UNKNOWN");
    const held = (q.entries || []).filter(
      (e) => e.state === "orphan" && (e.bytes || 0) > 0);
    if (!held.length) return "";
    const shown = held.slice(0, 2).map((e) =>
      t("QUAR_ROW", "{txn} ({bytes} B)", {
        txn: e.txn, bytes: String(e.bytes || 0),
      }));
    let text = t("QUAR_ORPHANS",
      "{n} quarantine folder(s) can no longer be restored: {list}",
      { n: String(held.length), list: shown.join("; ") });
    if (held.length > shown.length) {
      text += " " + t("CONFLICT_MORE", "(+{n} more)",
        { n: String(held.length - shown.length) });
    }
    return text;
  };

  /**
   * Round 54: delete the quarantine folders nothing can restore any more.
   *
   * The list comes from the status the panel is already showing, and only
   * entries the backend called "orphan" with bytes in them: a restorable folder
   * still holds a mod the user can bring back, and an "unknown" one means the
   * journal could not be read. Sending those would be spending "I cannot tell"
   * as "nobody owns it", which is the exact mistake the audit exists to avoid.
   */
  // Only offered where the panel already says somebody else owns the folder.
  // A handover that is not needed would just move files around for no reason.
  const doHandover = () => {
    runTwoPhase(
      (afterConfirm) => handoverMods(afterConfirm),
      (d) => t("HANDOVER_DONE", "Moved {n} entr(y/ies) into the quarantine.", {
        n: String((d.moved || []).length),
      }),
      (r) => {
        const d = (r.data || {}) as OpResultData;
        const why = d.explain || (d.blocking || []).join(", ");
        if (why) {
          // "nothing to hand over" is not an obstacle the user can clear; it
          // means there was never anything here to take over.
          const key = /nothing to hand over/i.test(r.detail || "")
            ? "HANDOVER_NONE"
            : "HANDOVER_BLOCKED";
          setError(r);
          setLastResult(key === "HANDOVER_NONE"
            ? t("HANDOVER_NONE")
            : t("HANDOVER_BLOCKED", "This cannot be undone in one step, so "
                + "nothing was moved: {why}", { why }));
          return true;
        }
        return false;
      },
    );
  };

  const doReclaim = () => {
    const q = status?.state?.quarantine;
    const txns = ((q && q.entries) || [])
      .filter((e) => e.state === "orphan" && (e.bytes || 0) > 0)
      .map((e) => e.txn);
    if (!txns.length) {
      setLastResult(t("QUAR_RECLAIM_NONE"));
      return;
    }
    runTwoPhase(
      (afterConfirm) => reclaimQuarantine(txns, afterConfirm),
      (d) => t("QUAR_RECLAIM_DONE", "Deleted {n} folder(s), freed {kb} KB.", {
        n: String((d.removed || []).length),
        kb: String(Math.round((d.bytes || 0) / 1024)),
      }),
    );
  };

  const conflictLine = (): string => {
    const c = status?.state?.conflicts;
    if (!c || !c.checked || !c.total) return "";
    const shown = (c.conflicts || []).slice(0, 2).map((x) => {
      const mods = (x.mods || []).join(" + ");
      return x.path + " (" + mods + ")";
    });
    let text = t("CONFLICT_LINE", "{n} shared path(s): {list}",
      { n: String(c.total), list: shown.join("; ") });
    if (c.total > shown.length) {
      text += " " + t("CONFLICT_MORE", "(+{n} more)", { n: String(c.total - shown.length) });
    }
    if (c.truncated) {
      text += " " + t("CONFLICT_TRUNCATED");
    }
    return text;
  };
  // Round 19: localized progress line (the key-status line is gone with the
  // retired credential surface).
  const progressLine = progress
    ? t("PROGRESS_LINE", "Progress: {stage}{pct}", {
        stage: progress.stage || "",
        pct: progress.pct ? ` (${progress.pct}%)` : "",
      })
    : "";

  return (
    // ⚠️ V3: `autoFocus` on Focusable is the Decky-standard way to give the
    // first focusable element focus when the QAM tab opens (§5.1 #1).
    <Focusable autoFocus style={{ display: "flex", flexDirection: "column" }}>
      {/* ── 1. 状态摘要（永远可见，但只占一块） ───────────────────────── */}
      <PanelSection title={fd ? t("TITLE_FILEDROP") : t("TITLE_XML")}>
        <PanelSectionRow>
          <div style={{ fontSize: "13px", lineHeight: 1.35 }}>
            <div style={{ fontWeight: 700 }}>
              {status ? t("GAME_INFO", "{name} \u00b7 AppID {appid} \u00b7 {platform} \u00b7 {state}", {
                name: status.game.name, appid: status.game.appid,
                platform: status.game.platform, state: status.game.status,
              }) : t("RESOLVING")}
            </div>
            <div style={{ opacity: 0.75, fontSize: "11px", wordBreak: "break-word" }}>
              {!fd ? (
                t("DETAIL_W1", "W1 (state):  {v}", { v: paths?.w1_state_file || "\u2026" })
              ) : (
                <>
                  {t("SMAPI_LINE", "SMAPI: {loader} \u00b7 launcher option: {lo}", {
                    loader: st?.loader_detected ? t("DETECTED") : t("MISSING"),
                    lo: st?.launch_options || t("LAUNCH_UNKNOWN"),
                  })}
                  {st?.external_manager ? t("EXTERNAL_MANAGER_FLAG") : ""}
                </>
              )}
            </div>
            <div style={{ opacity: 0.6, fontSize: "11px", wordBreak: "break-word" }}>
              {t("W2_LINE", "W2 (mods): {v}", { v: paths?.w2_mod_root || "\u2026" })}
            </div>
            {ll && ll.available ? (
              <div style={{ opacity: 0.75, fontSize: "11px", wordBreak: "break-word" }}>
                {t("LOADER_LOG_LINE", "Last launch: {loaded} mods, {packs} content packs, {skipped} skipped", {
                  loaded: ll.loaded ?? 0, packs: ll.content_packs ?? 0, skipped: ll.skipped ?? 0,
                })}
                {ll.truncated ? " " + t("LOADER_LOG_TRUNCATED") : ""}
              </div>
            ) : ll ? (
              <div style={{ opacity: 0.55, fontSize: "11px", wordBreak: "break-word" }}>
                {ll.reason === "log_missing"
                  ? t("LOADER_LOG_NONE")
                  : t("LOADER_LOG_BAD", "Loader log not usable: {reason}", {
                      reason: ll.reason || "\u2014",
                    })}
              </div>
            ) : null}
          </div>
        </PanelSectionRow>
        {fd && readOnly ? (
          <PanelSectionRow>
            <div style={{ fontSize: "12px", opacity: 0.95, wordBreak: "break-word", fontWeight: 600 }}>
              {t("READ_ONLY_BANNER")}
            </div>
          </PanelSectionRow>
        ) : null}
        {fd && readOnly ? (
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              label={t("HANDOVER_BTN")}
              description={t("HANDOVER_DESC")}
              disabled={busy}
              onClick={() => doHandover()}
            />
          </PanelSectionRow>
        ) : null}
        {fd && readOnly && foreignWhy() ? (
          <PanelSectionRow>
            <div style={{ fontSize: 11, opacity: 0.7, lineHeight: 1.35, wordBreak: "break-word" }}>
              {t("LAYOUT_WHY_TITLE")} {foreignWhy()}
            </div>
          </PanelSectionRow>
        ) : null}
        {conflictLine() ? (
          <PanelSectionRow>
            <div style={{ fontSize: 11, opacity: 0.7, lineHeight: 1.35, wordBreak: "break-word" }}>
              {conflictLine()}
            </div>
          </PanelSectionRow>
        ) : null}
        {quarantineLine() ? (
          <PanelSectionRow>
            <div style={{ fontSize: 11, opacity: 0.7, lineHeight: 1.35, wordBreak: "break-word" }}>
              {quarantineLine()}
            </div>
          </PanelSectionRow>
        ) : null}
        {!readOnly && quarantineLine() ? (
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              label={t("QUAR_RECLAIM_BTN")}
              description={t("QUAR_RECLAIM_DESC")}
              disabled={busy}
              onClick={() => doReclaim()}
            />
          </PanelSectionRow>
        ) : null}
        {runningLine() ? (
          <PanelSectionRow>
            <div style={{ fontSize: 11, opacity: 0.7, lineHeight: 1.35, wordBreak: "break-word" }}>
              {runningLine()}
            </div>
          </PanelSectionRow>
        ) : null}
        <PanelSectionRow>
          <div style={{ fontSize: "11px", opacity: 0.85, wordBreak: "break-word" }}>
            {busy ? t("STATUS_WORKING", "Working\u2026 {stage}{pct}", {
              stage: progress?.stage || "",
              pct: progress?.pct ? ` (${progress.pct}%)` : "",
            }) : <><b>{t("LAST_RESULT")}:</b> {lastResult}</>}
          </div>
        </PanelSectionRow>
      </PanelSection>

      {/* ── 2. 分区切换器：同时只展开一个区 ──────────────────────────── */}
      <PanelSection>
        <PanelSectionRow>
          <Focusable style={{ display: "flex", gap: "4px", width: "100%" }}>
            {([
              ["games", t("NAV_GAMES"), String((status?.catalog || []).filter((c) => c.operable).length)],
              ["import", t("NAV_IMPORT"), String(inbox?.items.length ?? "")],
              ["more", t("NAV_MORE"), ""],
            ] as [string, string, string][]).map(([key, label, badge]) => {
              const active = openSection === key;
              return (
                <DialogButton
                  key={key}
                  disabled={busy && !active}
                  onClick={() => setOpenSection(key)}
                  style={{
                    flex: 1,
                    minWidth: 0,
                    height: "auto",
                    padding: "5px 2px",
                    fontSize: "12px",
                    lineHeight: 1.15,
                    textAlign: "center",
                    opacity: active ? 1 : 0.5,
                    borderBottom: active ? "2px solid #1a9fff" : "2px solid transparent",
                  }}
                >
                  <div style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {label}
                  </div>
                  {badge ? (
                    <div style={{ fontSize: "10px", opacity: 0.8 }}>{badge}</div>
                  ) : null}
                </DialogButton>
              );
            })}
          </Focusable>
        </PanelSectionRow>
      </PanelSection>

      {/* ── 3a. 游戏（主入口）：已安装游戏直接列出，点一个进它的 MOD 列表 ── */}
      {openSection === "games" ? (
        <PanelSection>
          <PanelSectionRow>
            <div style={{ fontSize: "11px", opacity: 0.7, wordBreak: "break-word" }}>
              {t("GAMES_HINT")}
            </div>
          </PanelSectionRow>
          {/* Round 76: only these descriptors are installable, and exactly one
              is active at a time. Switching rewrites active_game and the engine
              is rebuilt on the next RPC, so nothing else has to change. */}
          <PanelSectionRow>
            <div style={{ fontSize: "11px", opacity: 0.65, fontWeight: 700, marginTop: "8px" }}>
              {t("GAMES_SUPPORTED", "Installable games")}
            </div>
          </PanelSectionRow>
          {(status?.catalog || []).filter((c) => c.enabled).map((c) => (
            <ButtonItem
              key={c.id}
              label={(c.active ? "▶ " : "") + (c.name || c.id)}
              description={c.active
                ? t("GAME_CURRENT_DESC", "The panel manages this game right now.")
                : t("GAME_SWITCH_DESC", "Make this the managed game. Nothing is deleted — the other game's mods stay untouched.")}
              disabled={busy || c.active}
              onClick={() => doSwitchGame(String(c.id), c.name || String(c.id))}
            >
              {c.active ? t("GAME_CURRENT", "Current") : t("GAME_SWITCH", "Switch")}
            </ButtonItem>
          ))}
          <PanelSectionRow>
            <div style={{ fontSize: "11px", opacity: 0.65, fontWeight: 700, marginTop: "8px" }}>
              {t("GAMES_ALL", "All installed games (read-only)")}
            </div>
          </PanelSectionRow>
          {gameList.length ? (
            <Focusable style={{ display: "flex", flexDirection: "column", gap: "6px", width: "100%" }}>
              {/* Playable games first (active / with mods), so the game the user
                  actually manages is the first stop instead of buried at #20. */}
              {[...gameList]
                .sort((a, b) => {
                  const score = (g: SteamGame) => {
                    const cat = (status?.catalog || []).find((c) => c.appid === g.appid);
                    const mods = (g.template?.total_mods ?? 0);
                    return (cat?.active ? 2 : 0) + (mods > 0 ? 1 : 0);
                  };
                  return score(b) - score(a);
                })
                .map((g) => {
                  const cat = (status?.catalog || []).find((c) => c.appid === g.appid);
                  const isActive = cat && cat.active;
                  const modCount = (g.template?.total_mods ?? 0);
                  return (
                    <DialogButton
                      key={g.appid}
                      disabled={busy}
                      onClick={() => (cat ? openGameMods(g) : openGameSetup(g))}
                      style={{ width: "100%", textAlign: "left", padding: "8px 10px" }}
                    >
                      <div style={{ fontSize: "13px", fontWeight: 500 }}>
                        {isActive ? "▶ " : ""}{g.name}
                      </div>
                      <div style={{ fontSize: "11px", opacity: 0.7 }}>
                        {t("GAME_ROW_SUB", "AppID {appid} · {n} mods{active}", {
                          appid: String(g.appid),
                          n: String(modCount),
                          active: isActive ? " · " + t("GAME_ACTIVE_BADGE") : "",
                        })}
                        {cat ? "" : "  ·  " + t("GAME_SETUP_HINT", "tap to set mod folder")}
                      </div>
                    </DialogButton>
                  );
                })}
            </Focusable>
          ) : (
            <PanelSectionRow>
              <div style={{ fontSize: "12px", opacity: 0.75 }}>{t("LIB_NO_GAMES")}</div>
            </PanelSectionRow>
          )}
          <ButtonItem
            label={t("LIB_REFRESH")}
            description={t("LIB_REFRESH_DESC")}
            disabled={busy}
            onClick={() => void loadGameGroups().then((gl) => setGameList(gl))}
          >
            {t("LIB_SECTION")}
          </ButtonItem>
        </PanelSection>
      ) : null}

      {/* ── 3b. 下载：Nexus 按 ID / 本地 ZIP / 关键词搜索 ──────────────── */}
      {openSection === "import" ? (
        <PanelSection>
          <PanelSectionRow>
            <div style={{ fontSize: "11px", opacity: 0.85, wordBreak: "break-word", fontWeight: 700 }}>
              {t("DOWNLOAD_TITLE")}
            </div>
          </PanelSectionRow>
          <PanelSectionRow>
            <div style={{ fontSize: "11px", opacity: 0.65, wordBreak: "break-word" }}>
              {t("DOWNLOAD_HINT")}
            </div>
          </PanelSectionRow>
          <ButtonItem
            label={t("AI_BTN", "Import new downloads (auto)")}
            description={t("AI_BTN_DESC", "Scan Downloads + inbox, auto-install every new mod ZIP already downloaded in the browser. Skips installed mods and install-options archives.")}
            disabled={busy}
            onClick={() => autoImportNew()}
          >
            {t("AI_BTN_SUB", "One tap → install all")}
          </ButtonItem>
          <ButtonItem
            label={t("INBOX_LABEL", "Inbox — local ZIPs ({n}) (A)", { n: inbox?.items.length ?? 0 })}
            description={t("INBOX_DESC")}
            disabled={busy}
            onClick={openInbox}
          >
            {t("INBOX_FIXED")}
          </ButtonItem>
          <PanelSectionRow>
            <div style={{ fontSize: "11px", opacity: 0.65 }}>{t("IMPORT_OSK")}</div>
          </PanelSectionRow>
          <ImportBox busy={busy} onSubmit={(p) => void inspectAndImport(p)} />


          {/* Round 74: one button. Splitting "check" from "install" left the
              user with a plan and no way to act on it when no GitHub asset
              existed; the merged flow installs what it can and opens the
              Nexus page for the rest. */}
          <ButtonItem
            label={t("DEPS_BTN")}
            description={t("DEPS_BTN_DESC")}
            disabled={busy}
            onClick={doDepsInstall}
          >
            {t("DEPS_BTN_SUB")}
          </ButtonItem>
          {progressLine ? (
            <PanelSectionRow>
              <div style={{ fontSize: "12px", opacity: 0.8, wordBreak: "break-word" }}>{progressLine}</div>
            </PanelSectionRow>
          ) : null}

          {/* ── Nexus: browse & open in browser (no API key) ─────────────── */}
          <PanelSectionRow>
            <div style={{ fontSize: "11px", opacity: 0.65, wordBreak: "break-word", marginTop: "10px", fontWeight: 700 }}>
              {t("NEXUS_SECTION")}
            </div>
          </PanelSectionRow>
          <PanelSectionRow>
            <div style={{ fontSize: "11px", opacity: 0.6, wordBreak: "break-word" }}>
              {t("NEXUS_SECTION_DESC")}
            </div>
          </PanelSectionRow>
          <PanelSectionRow>
            <div style={{ fontSize: "11px", opacity: 0.85, wordBreak: "break-all", fontWeight: 700 }}>
              {nexusPrefix
                ? t("NEXUS_CURRENT_PREFIX", undefined, { prefix: nexusPrefix })
                : t("NEXUS_NO_PREFIX")}
            </div>
          </PanelSectionRow>

          <PanelSectionRow>
            <div style={{ fontSize: "11px", opacity: 0.65, wordBreak: "break-word", marginTop: "6px" }}>
              {t("NEXUS_RECENT_DESC")}
            </div>
          </PanelSectionRow>
          <PanelSectionRow>
            <Focusable style={{ display: "flex", flexDirection: "row", gap: "4px", width: "100%" }}>
              <DialogButton
                style={{ flex: 1, minWidth: 0, height: "auto", padding: "5px 2px", fontSize: "12px" }}
                disabled={busy || !activeNexusDomain}
                onClick={() => doNexusRecent("latest_added")}
              >
                {t("NEXUS_RECENT_ADDED")}
              </DialogButton>
              <DialogButton
                style={{ flex: 1, minWidth: 0, height: "auto", padding: "5px 2px", fontSize: "12px" }}
                disabled={busy || !activeNexusDomain}
                onClick={() => doNexusRecent("latest_updated")}
              >
                {t("NEXUS_RECENT_UPDATED")}
              </DialogButton>
              <DialogButton
                style={{ flex: 1, minWidth: 0, height: "auto", padding: "5px 2px", fontSize: "12px" }}
                disabled={busy || !activeNexusDomain}
                onClick={() => doNexusRecent("trending")}
              >
                {t("NEXUS_RECENT_TRENDING")}
              </DialogButton>
            </Focusable>
          </PanelSectionRow>

          <PanelSectionRow>
            <Focusable style={{ display: "flex", flexDirection: "column", gap: "8px", width: "100%" }}>
              <TextField
                label={t("NEXUS_MOD_ID")}
                value={nexusModId}
                disabled={busy}
                onChange={(e) => setNexusModId(e?.target?.value ?? "")}
              />
            </Focusable>
          </PanelSectionRow>
          {nexusPrefix && /^\d+$/.test(nexusModId.trim()) ? (
            <PanelSectionRow>
              <div style={{ fontSize: "11px", opacity: 0.7, wordBreak: "break-all" }}>
                {t("NEXUS_FULL_URL", undefined, { url: `${nexusPrefix}/${nexusModId.trim()}` })}
              </div>
            </PanelSectionRow>
          ) : null}
          <ButtonItem
            label={t("NEXUS_MOD_FETCH")}
            description={t("NEXUS_MOD_FETCH_DESC")}
            disabled={busy || !activeNexusDomain || !nexusModId.trim()}
            onClick={doNexusMod}
          >
            {t("NEXUS_MOD_FETCH")}
          </ButtonItem>

          <PanelSectionRow>
            <div style={{ fontSize: "11px", opacity: 0.65, wordBreak: "break-word", marginTop: "10px", fontWeight: 700 }}>
              {t("SEARCH_SECTION")}
            </div>
          </PanelSectionRow>
          <PanelSectionRow>
            <div style={{ fontSize: "11px", opacity: 0.6, wordBreak: "break-word" }}>
              {t("SEARCH_SECTION_DESC")}
            </div>
          </PanelSectionRow>
          <PanelSectionRow>
            <Focusable style={{ display: "flex", flexDirection: "column", gap: "8px", width: "100%" }}>
              <TextField
                label={t("SEARCH_INPUT")}
                value={searchText}
                disabled={busy}
                onChange={(e) => setSearchText(e?.target?.value ?? "")}
              />
            </Focusable>
          </PanelSectionRow>
          <ButtonItem
            label={t("SEARCH_BTN")}
            description={t("SEARCH_BTN_DESC")}
            disabled={busy || !activeNexusDomain || !searchText.trim()}
            onClick={doSearch}
          >
            {t("SEARCH_SECTION")}
          </ButtonItem>

          {readOnly ? (
            <PanelSectionRow>
              <div style={{ fontSize: "11px", opacity: 0.65, wordBreak: "break-word" }}>
                {t("WRITE_GATE_NOTE", "Writes are disabled for this game (read-only mode).")}
              </div>
            </PanelSectionRow>
          ) : null}
        </PanelSection>
      ) : null}

      {/* ── 3c. 更多：历史 / 刷新 / 错误码 / 恢复 / 约束 ───────────────── */}
      {openSection === "more" ? (
        <PanelSection>
          <ButtonItem
            label={t("REFRESH_LABEL")}
            description={t("REFRESH_DESC")}
            disabled={busy}
            onClick={doRefresh}
          >
            {t("REFRESH_BODY")}
          </ButtonItem>
          <ButtonItem label={t("HISTORY_LABEL")} description={t("HISTORY_DESC")} disabled={busy} onClick={() => void openHistory()}>
            {t("HISTORY_BODY")}
          </ButtonItem>
          <ButtonItem label={t("ERRORCODES_LABEL")} description={t("ERRORCODES_DESC")} disabled={busy} onClick={() => void openErrorCodes()}>
            {t("ERRORCODES_BODY")}
          </ButtonItem>
          {status?.recovery_needed ? (
            <ButtonItem label={t("RECOVERY_LABEL")} description={t("RECOVERY_DESC")} disabled={busy} onClick={() => void openRecovery()}>
              {status.pending_recovery.join(", ")}
            </ButtonItem>
          ) : null}
          <PanelSectionRow>
            <div style={{ fontSize: "11px", opacity: 0.65, wordBreak: "break-word" }}>
              {t("QUAR_LINE", "Quarantine: {v}", { v: paths?.quarantine_root || "…" })}
            </div>
          </PanelSectionRow>
          <PanelSectionRow>
            <div style={{ fontSize: "11px", opacity: 0.65 }}>
              {t("CONSTRAINTS")}: {t("CONSTRAINTS_BODY")}
            </div>
          </PanelSectionRow>
          {limitations.length ? (
            <PanelSectionRow>
              <div style={{ fontSize: "11px", opacity: 0.7, wordBreak: "break-word" }}>
                <b>{t("KNOWN_LIMITS")}:</b> {limitations.join(" ")}
              </div>
            </PanelSectionRow>
          ) : null}
        </PanelSection>
      ) : null}
    </Focusable>
  );
}

/* ------------------------------------------------------------------ plugin export */

export default definePlugin(() => {
  // §5.3: all real cleanup (generation counter, event unsubscription, timers)
  // lives in <Content>'s useEffect cleanup — the React-standard unmount hook.
  // ⚠️ V3: confirm whether the locked template also exposes a plugin-level
  // `onDismount` field on the definePlugin return object; if so, it can be
  // added here as an explicit teardown point. We intentionally do NOT rely on
  // an unverified field, so the panel is self-cleaning on unmount.
  return {
    name: "Decky MOD Manager",
    // ⚠️ V3: replace with a proper react-icons glyph once the template version
    // is locked. A plain ReactNode keeps this buildable with zero icon deps.
    icon: <span aria-label="Decky MOD Manager">📦</span>,
    content: <Content />,
  };
});
