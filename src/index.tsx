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
  installMod,
  setModEnabled,
  uninstallMod,
  rollbackTxn,
  ghSearch,
  ghReleases,
  ghDownload,
  downloadUrl,
  fetchDependencies,
  apiKeyStatus,
  setApiKey,
  deleteApiKey,
  nexusValidate,
  nexusRecent,
  nexusMod,
  nexusDownloadLink,
  openModPage,
  openSearchPage,
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
  GhSearchItem,
  GhReleasesData,
  GhRelease,
  GhAsset,
  GhDownloaded,
  SteamGame,
  KeyStatusData,
  NexusModData,
} from "./types";
import { isConfirmData } from "./types";
import { t, errorText, categoryText } from "./i18n";
import type { ModListEntry } from "./types";
import { showConfirm } from "./components/ConfirmModal";
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
  const [inbox, setInbox] = useState<InboxData | null>(null);
  const [busy, setBusy] = useState(false);
  const [lastResult, setLastResult] = useState(t("RESOLVING"));
  const [progress, setProgress] = useState<ProgressPayload | null>(null);
  const [error, setError] = useState<Envelope<unknown> | null>(null);

  // Round 19: download-source panel state. GitHub search -> repo -> release ->
  // asset -> download -> inspect -> confirm, plus a direct-URL fallback. No
  // credential is held anywhere: the backend has none to give out.
  const [ghQuery, setGhQuery] = useState("stardew mod");
  const [ghResults, setGhResults] = useState<GhSearchItem[]>([]);
  const [ghTotal, setGhTotal] = useState(0);
  // Round 35: paging. GitHub caps search at 100 pages x 10 results; the
  // backend clamps anything above that, so the UI only has to stay honest.
  const [ghPage, setGhPage] = useState(1);
  const [ghSelected, setGhSelected] = useState<GhSearchItem | null>(null);
  const [ghRel, setGhRel] = useState<GhReleasesData | null>(null);
  const [directUrlValue, setDirectUrlValue] = useState("");

  // Round 39: Nexus metadata surface. `keyInput` is the ONLY place a key ever
  // lives on this side of the bridge, and it is cleared the moment the backend
  // confirms it wrote the file. It is never rendered back, never logged, never
  // put in a toast, and never passed to anything except setApiKey().
  const [keyStatus, setKeyStatus] = useState<KeyStatusData | null>(null);
  const [keyInput, setKeyInput] = useState("");
  const [nexusVerify, setNexusVerify] = useState("");
  const [nexusModId, setNexusModId] = useState("");
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
  const [openSection, setOpenSection] = useState<string>("mods");

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

  /* ------------------------------------------- round 39: Nexus (metadata only)
   * Everything below is read-only browsing. The one write is storing the key,
   * which is a local file action (no network), so it does not go through the
   * download gate; the metadata calls do, inside the backend.
   */

  /** Re-read the on-disk key state. Stat only — the backend never opens it. */
  const refreshKeyStatus = async (): Promise<void> => {
    const g = generation.current;
    try {
      const r = await apiKeyStatus();
      if (!mounted.current || generation.current !== g) return;
      if (r.ok) setKeyStatus(r.data);
    } catch (_) {
      /* status is informational; a failure must not break the panel */
    }
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
    })();
    void loadGameGroups();
    // Round 39: prime the stored-key state (stat only, no network).
    void refreshKeyStatus();

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
  const openInbox = () => {
    const items = inbox?.items || [];
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
        { roots: (inbox?.roots || []).map((r) => `${r.label}: ${r.path}${r.exists ? "" : " (absent)"}`).join("\n")
          || (inbox?.inbox || t("NOT_SET")) }),
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
    runTwoPhase(
      (ac) => uninstallMod(dirName, ac),
      (res) =>
        t("UNINSTALL_OK", "Uninstalled {id}. Folder moved to quarantine (NOT deleted): {q}. Use History → Rollback to restore.",
          { id: res.packageId || dirName, q: res.quarantine || t("Q_MARK") }),
    );
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
    const rows: ListRow[] = txns.map((t) => {
      const first = items.find((i) => i.txn === t)!;
      return {
        label: t,
        sub: `${first.event || ""}${first.packageId ? ` · ${first.packageId}` : ""}`,
        onActivate: (close) => {
          close();
          confirmRollback(t);
        },
      };
    });
    showListModal(
      t("HISTORY_TITLE", "History — roll back a transaction ({n})", { n: txns.length }),
      rows,
      t("HISTORY_SUB"),
    );
  };

  const confirmRollback = (txn: string) => {
    const fd = isFileDrop(status);
    // Explicit typed object (no conditional spread) so strict tsc cannot
    // produce an optional `string | undefined` vs `Record<string,string|null>`.
    const targets: Record<string, string | null> = {
      w2_quarantine: status?.paths.quarantine_root || t("ROLLBACK_SEE_STATUS"),
    };
    if (!fd) targets.w1_state_file = status?.paths.w1_state_file ?? null;
    const data: ConfirmData = {
      phase: "confirm",
      plan: { op: "rollback" },
      confirm_text: fd
        ? t("ROLLBACK_CONFIRM_FD", "Roll back transaction {txn}?\nThis restores the mod folder from quarantine (file_drop: no ModsConfig.xml snapshot).", { txn })
        : t("ROLLBACK_CONFIRM_XML", "Roll back transaction {txn}?\nThis restores the previous ModsConfig.xml from the journal snapshot (and the mod folder from quarantine).", { txn }),
      targets,
      log_path: status?.log_path || "",
    };
    showConfirm(data, async (confirmed) => {
      if (!confirmed || !mounted.current) return;
      setBusySafe(true);
      const g = generation.current;
      const r = await rollbackTxn(txn);
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
      const msg = d.restored
        ? t("ROLLBACK_DONE", "Rolled back {txn}: restored {d}.", { txn, d: d.restored })
        : d.recovered
          ? t("ROLLBACK_RECOVERED", "Recovered pending transaction {txn} from its snapshot.", { txn })
          : t("ROLLBACK_COMPLETED", "Rollback of {txn} completed.", { txn });
      setLastResult(msg);
      toast(t("TOAST_ROLLBACK"), msg);
      later(() => setProgress(null), 1500);
      await reload();
      setBusySafe(false);
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
    const rows: ListRow[] = pending.map((tx) => ({
      label: tx,
      sub: t("RECOVERY_SUB"),
      onActivate: (close) => {
        close();
        confirmRollback(tx);
      },
    }));
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
          // Round 36: selecting a game leads straight to that game's MOD
          // search. The phrase comes from the descriptor-driven template when
          // there is one; otherwise the game's own name, never a guess at its
          // Mod directory.
          const searchPhrase = (tpl && tpl.adapted && tpl.search_hint) || g.name;
          showInfo(g.name, lines, [
            {
              label: t("LIB_SEARCH_MODS", "Search mods for {game}", { game: g.name }),
              onClick: (close) => {
                close();
                setOpenSection("download");
                setGhQuery(searchPhrase);
                setGhResults([]);
                setGhSelected(null);
                setGhRel(null);
                doGhSearch(1, searchPhrase);
              },
            },
          ], t("LIB_GAME_DESC", "AppID {appid} · {state}", {
            appid: g.appid, state: stateWord(g.state),
          }));
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
            ...(m.parse_error
              ? [t("MODLIST_PARSE_ERR", "Manifest error: {v}", { v: m.parse_error })] : []),
          ].filter((x) => x !== ""),
          [
            ...(isParked && canToggleDisabled
              ? [{
                  label: t("BTN_ENABLE"),
                  onClick: (close: () => void) => {
                    close();
                    toggle({ packageId: m.dir, name: m.name, enabled: false } as ManagedMod);
                  },
                }]
              : []),
            ...(!isParked && canToggleDisabled
              ? [{
                  label: t("BTN_DISABLE"),
                  onClick: (close: () => void) => {
                    close();
                    toggle({ packageId: m.dir, name: m.name, enabled: true } as ManagedMod);
                  },
                }]
              : []),
            ...(canRemove && !isParked
              ? [{
                  label: t("BTN_UNINSTALL"),
                  onClick: (close: () => void) => {
                    close();
                    doUninstallDir(m.dir);
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
      const others = dupMap.get(m.dir) || [];
      if (others.length) {
        notes.push(t("MODLIST_DUP_ID", "Duplicate UniqueID also in: {v}", { v: others.join(", ") }));
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

  /** Human-readable asset size; the raw byte count stays in the label too. */
  const assetSize = (n: number): string => {
    if (!Number.isFinite(n) || n <= 0) return String(n);
    if (n >= 1048576) return `${(n / 1048576).toFixed(1)} MiB`;
    if (n >= 1024) return `${Math.round(n / 1024)} KiB`;
    return `${n} B`;
  };

  /** Step 1: search GitHub. Read-only, 60 req/h unauthenticated. */
  const doGhSearch = (page: number, rawQuery?: string) => {
    // `rawQuery` exists because setState is async: a caller that just called
    // setGhQuery(...) would otherwise search the previous term.
    const q = (rawQuery ?? ghQuery).trim();
    if (!q) return;
    setBusySafe(true);
    const g = generation.current;
    (async () => {
      const r = await ghSearch(q, page);
      if (!mounted.current || generation.current !== g) { setBusySafe(false); return; }
      setBusySafe(false);
      if (!r.ok) { setError(r); setLastResult(envelopeError(r)); return; }
      // Envelope.data is `T | null`; keep the same optional-chain style the
      // rest of this file uses (see the inbox/history handlers).
      const items = r.data?.items || [];
      const total = r.data?.total_count ?? 0;
      setGhResults(items);
      setGhTotal(total);
      setGhPage(page);
      setGhQuery(q);
      setGhRel(null);
      setGhSelected(null);
      const label = t("GH_SEARCH_DONE", "Found {total} (showing {n})", {
        total, n: items.length,
      });
      setLastResult(label);
      if (!items.length) showInfo(t("GH_SEARCH_DONE", "Found {total} (showing {n})", {
        total: 0, n: 0,
      }), [t("GH_NO_RESULTS")], []);
    })().catch((e) => {
      if (!mounted.current) return;
      setBusySafe(false);
      setError(bridgeError(String(e)));
    });
  };

  /** Step 2: pick a repo -> list its releases and assets. */
  const doGhReleases = (item: GhSearchItem) => {
    setGhSelected(item);
    setBusySafe(true);
    const g = generation.current;
    const owner = item.owner;
    const repo = item.repo;
    (async () => {
      const r = await ghReleases(owner, repo);
      if (!mounted.current || generation.current !== g) { setBusySafe(false); return; }
      setBusySafe(false);
      if (!r.ok || !r.data) { setError(r); setLastResult(envelopeError(r)); return; }
      setGhRel(r.data);
      const n = r.data.releases.length;
      setLastResult(t("GH_RELEASES_LOADED", "Releases: {n}", { n }));
      if (!n) {
        showInfo(t("GH_RELEASES_LOADED", "Releases: {n}", { n: 0 }), [t("GH_NO_RELEASES")], []);
      }
    })().catch((e) => {
      if (!mounted.current) return;
      setBusySafe(false);
      setError(bridgeError(String(e)));
    });
  };

  /** Step 3: download an asset into the inbox and inspect it (NO write). */
  const doGhDownload = (asset: GhAsset) => {
    if (!ghSelected || !asset.usable) return;
    // Primitive consts for the async closure (see the round-18 note pattern).
    const owner = ghSelected.owner;
    const repo = ghSelected.repo;
    const assetId = asset.id;
    const filename = asset.name;
    setBusySafe(true);
    const g = generation.current;
    (async () => {
      const r = await ghDownload(owner, repo, assetId, filename, false, false);
      if (!mounted.current || generation.current !== g) { setBusySafe(false); return; }
      setBusySafe(false);
      if (!r.ok) { setError(r); setLastResult(envelopeError(r)); return; }
      setLastResult(describeDownload(filename, r.data));
      toast(t("TOAST_DONE"), t("GH_DOWNLOADED", "Downloaded {name} (inbox only, nothing installed)", {
        name: filename,
      }));
      void reload();
    })().catch((e) => {
      if (!mounted.current) return;
      setBusySafe(false);
      setError(bridgeError(String(e)));
    });
  };

  /** Step 4: import that inbox file through the two-phase confirm. */
  const doGhImport = (asset: GhAsset) => {
    if (!ghSelected || !asset.usable) return;
    const owner = ghSelected.owner;
    const repo = ghSelected.repo;
    const assetId = asset.id;
    const filename = asset.name;
    runTwoPhase(
      (afterConfirm) => ghDownload(owner, repo, assetId, filename, true, afterConfirm),
      (_res) => t("GH_IMPORT_TITLE"),
    );
  };

  /**
   * Say what was actually VERIFIED, not just what was downloaded.
   *
   * The backend reports `verified` as the list of checks that really ran. An
   * empty list means the source declared no size/hash, so we say "no checksum
   * available" instead of implying we checked something. This is the honest
   * half of criterion 4: measuring a file is not verifying it.
   */
  const describeDownload = (name: string, data: unknown): string => {
    const d = (data || {}) as { downloaded?: GhDownloaded } | null;
    const got = d && d.downloaded ? d.downloaded : null;
    if (!got) return t("GH_DOWNLOADED", "Downloaded {name} (inbox only, nothing installed)", { name });
    const verified = got.verified || [];
    const base = t("GH_DOWNLOADED", "Downloaded {name} (inbox only, nothing installed)", { name });
    if (verified.indexOf("sha256") >= 0) {
      return base + " · " + t("GH_VERIFIED_HASH", "size + SHA-256 verified", {});
    }
    if (verified.indexOf("size") >= 0) {
      return base + " · " + t("GH_VERIFIED_SIZE", "size verified ({n} bytes)", { n: String(got.size) });
    }
    return base + " · " + t("GH_NOT_VERIFIED", "no checksum published by the source", {});
  };

  /** Direct-URL fallback — accepts any HTTPS zip the user pastes. Same three phases. */
  const doDirectDownload = () => {
    const raw = directUrlValue.trim();
    if (!raw) return;
    setBusySafe(true);
    const g = generation.current;
    (async () => {
      const name = "direct-download.zip";
      const r = await downloadUrl(raw, name, false, false);
      if (!mounted.current || generation.current !== g) { setBusySafe(false); return; }
      setBusySafe(false);
      if (!r.ok) { setError(r); setLastResult(envelopeError(r)); return; }
      setLastResult(describeDownload(name, r.data));
      toast(t("TOAST_DONE"), t("GH_DIRECT_DONE"));
      void reload();
    })().catch((e) => {
      if (!mounted.current) return;
      setBusySafe(false);
      setError(bridgeError(String(e)));
    });
  };

  const doDirectImport = () => {
    const raw = directUrlValue.trim();
    if (!raw) return;
    const name = "direct-download.zip";
    runTwoPhase(
      (afterConfirm) => downloadUrl(raw, name, true, afterConfirm),
      (_res) => t("GH_IMPORT_TITLE"),
    );
  };


  /* ----------------------------------------------------- §5.3b dependencies */
  // Round 38: a mod whose required dependencies are missing is skipped by
  // SMAPI, so the install looks successful and the game ignores it. These two
  // buttons close that gap; the acceptance rule (manifest UniqueID must match)
  // lives in the backend, not here.
  const depReason = (r: string | undefined): string => {
    switch (r) {
      case "no_repo_in_index": return t("DEPS_R_NO_REPO");
      case "no_zip_asset": return t("DEPS_R_NO_ZIP");
      case "candidate_failed":
      case "no_candidate_matched": return t("DEPS_R_NO_MATCH");
      case "install_refused": return t("DEPS_R_REFUSED");
      case "install_raised": return t("DEPS_R_RAISED");
      case "": return t("DEPS_R_OK");
      default: return t("DEPS_R_UNRESOLVABLE");
    }
  };

  const describeDeps = (d: unknown): string[] => {
    const box = (d || {}) as {
      deps?: Array<Record<string, unknown>>;
      rounds?: number;
      still_missing?: string[];
      note?: string;
    };
    const list = box.deps || [];
    // Round 45: a dependency can pull in another one, so the same question is
    // re-asked after each round. Show the round only when there was more than
    // one -- printing "round 1" on every single-level install would be noise.
    const multi = (box.rounds ?? 0) > 1;
    const out: string[] = [];
    if (!list.length) return [t("DEPS_NONE")];
    for (const row of list) {
      const uid = String(row.uniqueId || "");
      const done = row.installed === true;
      const reason = depReason(String(row.reason ?? ""));
      const asset = row.asset ? String(row.asset) : "";
      const detail = row.detail ? String(row.detail) : "";
      const roundNo = typeof row.round === "number" ? row.round : 0;
      const head = t("DEPS_ROW", "{id} · {state}", {
        id: multi && roundNo > 1 ? t("DEPS_ROW_DEEP", "{id} (depth {n})", { id: uid, n: String(roundNo) }) : uid,
        state: done ? t("DEPS_OK") : reason,
      });
      const tail = done ? asset : detail;
      out.push(tail ? head + "\n  " + tail : head);
    }
    const still = box.still_missing || [];
    if (still.length) out.push(t("DEPS_STILL", "Still missing: {ids}", { ids: still.join(", ") }));
    if (box.note) out.push(String(box.note));
    return out;
  };

  const doDepsPlan = () => {
    setBusySafe(true);
    const g = generation.current;
    (async () => {
      const r = await fetchDependencies(false, false);
      if (!mounted.current || generation.current !== g) { setBusySafe(false); return; }
      setBusySafe(false);
      if (!r.ok) { setError(r); setLastResult(envelopeError(r)); return; }
      const d = (r.data || {}) as { phase?: string; total?: number; fetchable?: number };
      const lines = describeDeps(r.data);
      setLastResult(t("DEPS_PLAN_DONE", "{n} missing", { n: String(d.total ?? 0) }));
      showInfo(
        t("DEPS_TITLE", "Missing dependencies ({n})", { n: String(d.total ?? 0) }),
        lines,
        d.fetchable
          ? [{ label: t("DEPS_INSTALL_BTN"), onClick: (close) => { close(); doDepsInstall(); } }]
          : [],
        t("DEPS_SUB", "{n} can be downloaded from GitHub", { n: String(d.fetchable ?? 0) }),
      );
    })().catch((e) => {
      if (!mounted.current) return;
      setBusySafe(false);
      setError(bridgeError(String(e)));
    });
  };

  const doDepsInstall = () => {
    runTwoPhase(
      (afterConfirm) => fetchDependencies(true, afterConfirm),
      () => t("DEPS_DONE"),
    );
  };

  /* ------------------------------------------- round 39: Nexus (metadata only)
   * Everything below is read-only browsing. The one write is storing the key,
   * which is a local file action (no network), so it does not go through the
   * download gate; the metadata calls do, inside the backend.
   * refreshKeyStatus() lives further up, next to reload(), so the mount effect
   * can prime it.
   */

  /** One-line description of the stored key state, for the panel body. */
  const keyStatusLine = (): string => {
    if (!keyStatus) return "";
    if (!keyStatus.configured || keyStatus.state === "missing") {
      return t("NEXUS_KEY_NONE");
    }
    // The backend formats the mode itself ("0o600"). Render it verbatim: a
    // device probe showed `oct()` crosses the bridge as a string, so treating
    // it as a number produced "00o600".
    const mode = keyStatus.mode_actual === null ? "—" : keyStatus.mode_actual;
    if (keyStatus.state === "unreadable") {
      return t("NEXUS_KEY_STATE_UNREADABLE", undefined, { mode });
    }
    const head = t("NEXUS_KEY_STATE_PRESENT", undefined, { size: String(keyStatus.size ?? 0) });
    const perm = !keyStatus.posix
      ? t("NEXUS_KEY_NO_POSIX")
      : (keyStatus.mode_ok ? t("NEXUS_KEY_MODE_OK", undefined, { mode })
                           : t("NEXUS_KEY_MODE_BAD", undefined, { mode }));
    return head + " · " + perm;
  };

  const doSaveKey = () => {
    const value = keyInput.trim();
    if (!value) return;
    setBusySafe(true);
    const g = generation.current;
    (async () => {
      const r = await setApiKey(value);
      if (!mounted.current || generation.current !== g) { setBusySafe(false); return; }
      // Clear the field on EVERY outcome: on success the backend owns the key,
      // on failure the user must re-paste from the source anyway, and in both
      // cases leaving a secret in component state serves no purpose.
      setKeyInput("");
      setBusySafe(false);
      if (!r.ok) { setError(r); setLastResult(envelopeError(r)); return; }
      // `data` is `T | null` on the envelope (an ok:false reply can carry null),
      // so narrow before reading. A missing payload is not an error worth a
      // modal here — the key WAS stored, we simply have no mode to report.
      const set = r.data;
      const mode = !set || set.mode_actual === null ? "—" : set.mode_actual;
      setLastResult(t("NEXUS_KEY_SAVED", undefined, { mode }));
      toast(t("NEXUS_KEY_TITLE"), t("NEXUS_KEY_SAVED", undefined, { mode }));
      await refreshKeyStatus();
    })().catch((e) => {
      if (!mounted.current) return;
      setKeyInput("");
      setBusySafe(false);
      setError(bridgeError(String(e)));
    });
  };

  const doClearKey = () => {
    setBusySafe(true);
    const g = generation.current;
    (async () => {
      const r = await deleteApiKey();
      if (!mounted.current || generation.current !== g) { setBusySafe(false); return; }
      setBusySafe(false);
      if (!r.ok) { setError(r); setLastResult(envelopeError(r)); return; }
      setNexusVerify("");
      const del = r.data;
      setLastResult(del && del.deleted ? t("NEXUS_KEY_CLEARED") : t("NEXUS_KEY_CLEAR_NONE"));
      await refreshKeyStatus();
    })().catch((e) => {
      if (!mounted.current) return;
      setBusySafe(false);
      setError(bridgeError(String(e)));
    });
  };

  /** Ask Nexus who the stored key belongs to. Takes no arguments on purpose. */
  const doValidateKey = () => {
    setBusySafe(true);
    const g = generation.current;
    (async () => {
      const r = await nexusValidate();
      if (!mounted.current || generation.current !== g) { setBusySafe(false); return; }
      setBusySafe(false);
      if (!r.ok) {
        // A rejected key is an expected outcome, not a crash: show the server's
        // own wording, which the backend already put in `detail`.
        setError(r);
        setLastResult(envelopeError(r));
        setNexusVerify("");
        return;
      }
      const d = r.data;
      if (!d) {
        setNexusVerify("");
        setLastResult(t("NEXUS_KEY_NONE"));
        return;
      }
      const tier = d.is_premium ? t("NEXUS_VALIDATE_PREMIUM") : t("NEXUS_VALIDATE_FREE");
      const supp = d.is_supporter ? " · " + t("NEXUS_VALIDATE_SUPPORTER") : "";
      const line = t("NEXUS_VALIDATE_OK", undefined, { name: d.name || "—" }) + " · " + tier + supp;
      setNexusVerify(line);
      setLastResult(line);
    })().catch((e) => {
      if (!mounted.current) return;
      setBusySafe(false);
      setError(bridgeError(String(e)));
    });
  };

  /** Browse one of the three feeds. There is no search because there is no endpoint. */
  const doNexusRecent = (kind: string) => {
    setBusySafe(true);
    const g = generation.current;
    (async () => {
      const r = await nexusRecent(kind);
      if (!mounted.current || generation.current !== g) { setBusySafe(false); return; }
      setBusySafe(false);
      if (!r.ok) { setError(r); setLastResult(envelopeError(r)); return; }
      const mods = (r.data && r.data.mods) || [];
      setLastResult(t("NEXUS_RECENT_ROWS", undefined, { n: String(mods.length) }));
      if (!mods.length) {
        showInfo(t("NEXUS_RECENT_TITLE"), [t("NEXUS_FILES_EMPTY")], []);
        return;
      }
      const rows: ListRow[] = mods.map((m) => ({
        label: m.name || String(m.mod_id),
        sub: t("NEXUS_ROW_DESC", undefined, {
          version: m.version || "—",
          author: m.author || t("NEXUS_ROW_NO_AUTHOR"),
        }),
        onActivate: () => {
          showInfo(
            m.name || String(m.mod_id),
            [
              m.summary || "",
              t("NEXUS_BROWSER_URL", undefined, { url: m.mod_page_url }),
              "",
              t("NEXUS_OPEN_PAGE"),
            ],
            [
              {
                label: t("OPEN_PAGE_BTN"),
                onClick: (close) => {
                  close();
                  doOpenPage(m.mod_id);
                },
              },
            ],
            t("NEXUS_SECTION"),
          );
        },
      }));
      showListModal(t("NEXUS_RECENT_TITLE"), rows, t("NEXUS_RECENT_DESC"));
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
    setBusySafe(true);
    const g = generation.current;
    (async () => {
      const r = await nexusMod(Number(raw));
      if (!mounted.current || generation.current !== g) { setBusySafe(false); return; }
      setBusySafe(false);
      if (!r.ok) { setError(r); setLastResult(envelopeError(r)); return; }
      if (!r.data) {
        // ok:true with a null payload should not happen, but inventing a mod
        // detail screen from nothing would be worse than saying so.
        showInfo(t("NEXUS_MOD_TITLE"), [t("NEXUS_FILES_ERROR", undefined, { detail: r.code || "—" })], []);
        return;
      }
      openModDetail(r.data);
    })().catch((e) => {
      if (!mounted.current) return;
      setBusySafe(false);
      setError(bridgeError(String(e)));
    });
  };

  /** The mod detail modal: metadata, the page URL, and the file list. */
  const openModDetail = (d: NexusModData) => {
    const files = d.files || [];
    const lines: string[] = [];
    const info = d.info || {};
    if (info.summary) lines.push(info.summary, "");
    lines.push(t("NEXUS_BROWSER_URL", undefined, { url: d.browser_url }));
    lines.push("", t("NEXUS_FILES_TITLE", undefined, { n: String(files.length) }));
    if (d.files_error) {
      lines.push(t("NEXUS_FILES_ERROR", undefined, { detail: d.files_error }));
    } else if (!files.length) {
      lines.push(t("NEXUS_FILES_EMPTY"));
    } else {
      for (const f of files) {
        const kb = f.size_kb === undefined ? "" : " · " + t("NEXUS_FILE_SIZE", undefined, { kb: String(f.size_kb) });
        lines.push(t("NEXUS_FILE_ROW", undefined, { name: f.name || "—", version: f.version || "—" }) + kb);
      }
    }
    lines.push("", t("NEXUS_OPEN_PAGE"));
    // First action: actually put the page on screen. Asking for a file's link is
    // the only honest way to show that a free account is refused -- a disabled
    // button would look like a plugin bug instead of a Nexus rule. Both lists are
    // capped so the focus ring stays walkable.
    const actions: ModalAction[] = [
      {
        label: t("OPEN_PAGE_BTN"),
        onClick: (close) => {
          close();
          doOpenPage(d.mod_id);
        },
      },
    ];
    for (const f of files.slice(0, 5)) {
      actions.push({
        label: t("NEXUS_FILE_LINK_BTN", undefined, { id: String(f.file_id) }),
        onClick: (close) => {
          close();
          doNexusLink(d.mod_id, f.file_id, f.name || "");
        },
      });
    }
    showInfo(String(info.name || t("NEXUS_MOD_TITLE")), lines, actions, t("NEXUS_SECTION"));
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

  /**
   * Ask for one file's download link. For a free account this is REFUSED by
   * Nexus — the point of having the RPC is that the refusal is reported as a
   * refusal (premium gate + browser URL), not dressed up as a broken download.
   */
  const doNexusLink = (modId: number, fileId: number, fileName: string) => {
    setBusySafe(true);
    const g = generation.current;
    (async () => {
      const r = await nexusDownloadLink(modId, fileId);
      if (!mounted.current || generation.current !== g) { setBusySafe(false); return; }
      setBusySafe(false);
      if (!r.ok) {
        // Show the honest explanation rather than the generic error modal: the
        // user cannot fix this by retrying, so it must not read like a bug.
        const data = (r.data || {}) as { premium_required?: boolean; browser_url?: string };
        const lines = [t("NEXUS_PREMIUM_ONLY")];
        if (r.detail) lines.push("", t("NEXUS_PREMIUM_WHY", undefined, { detail: r.detail }));
        if (data.browser_url) lines.push("", t("NEXUS_BROWSER_URL", undefined, { url: data.browser_url }));
        lines.push("", t("NEXUS_OPEN_PAGE"));
        showInfo(fileName || t("NEXUS_FILES_TITLE", undefined, { n: "1" }), lines, [], t("NEXUS_SECTION"));
        setLastResult(t("NEXUS_PREMIUM_ONLY"));
        return;
      }
      setLastResult(t("NEXUS_LOADING"));
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
    ? t("GH_PROGRESS", "Progress: {stage}{pct}", {
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
              ["mods", t("NAV_MODS"), String(st?.mods?.length ?? 0)],
              ["download", t("NAV_DOWNLOAD"), String(inbox?.items.length ?? "")],
              ["games", t("NAV_GAMES"), String(status?.catalog?.length ?? 0)],
              ["system", t("NAV_SYSTEM"), ""],
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

      {/* ── 3a. 我的 MOD：导入 + 已安装 ──────────────────────────────── */}
      {openSection === "mods" ? (
        <PanelSection>
          <ButtonItem
            label={t("INBOX_LABEL", "Inbox — local ZIPs ({n}) (A)", { n: inbox?.items.length ?? 0 })}
            description={t("INBOX_DESC")}
            disabled={busy}
            onClick={openInbox}
          >
            {t("INBOX_FIXED")}
          </ButtonItem>
          <ButtonItem label={t("MODLIST_BTN")} description={t("MODLIST_BTN_DESC")} disabled={busy} onClick={openModList}>
            {t("MODLIST_SUB")}
          </ButtonItem>
          <ButtonItem
            label={t("MODS_BY_GAME")}
            description={t("MODS_BY_GAME_BTN_DESC")}
            disabled={busy}
            onClick={() => void openModsByGame()}
          >
            {t("MODS_BY_GAME_BTN_SUB")}
          </ButtonItem>
          {/* The list below is a different set of mods from "Detected mods" above:
              that one scans disk, this one is what the plugin installed. Without
              this heading the rows appear to belong to the button. */}
          <PanelSectionRow>
            <div style={{ fontSize: "11px", opacity: 0.65, marginTop: "4px" }}>
              {t("INSTALLED_FILEDROP", "Mods installed by this plugin ({n})", { n: installed.length })}
            </div>
          </PanelSectionRow>
          {installed.length === 0 ? (
            <PanelSectionRow>
              <div style={{ fontSize: "12px", opacity: 0.75 }}>
                {t("NO_MANAGED_MODS")}
              </div>
            </PanelSectionRow>
          ) : (
            installed.map((mod) => (
              <ModRow
                key={mod.packageId}
                mod={mod}
                busy={busy}
                canToggle={canToggle}
                onToggle={toggle}
                onUninstall={doUninstall}
                onDetail={showModDetail}
              />
            ))
          )}
          <PanelSectionRow>
            <div style={{ fontSize: "11px", opacity: 0.65 }}>{t("IMPORT_OSK")}</div>
          </PanelSectionRow>
          <ImportBox busy={busy} onSubmit={(p) => void inspectAndImport(p)} />
        </PanelSection>
      ) : null}

      {/* ── 3b. 下载 MOD ─────────────────────────────────────────────── */}
      {openSection === "download" ? (
        <PanelSection>
          <PanelSectionRow>
            <div style={{ fontSize: "11px", opacity: 0.65, wordBreak: "break-word" }}>
              {t("GH_SECTION_DESC")}
              {t("GH_FROM_GAME_HINT")}
            </div>
          </PanelSectionRow>

          <PanelSectionRow>
            <Focusable style={{ display: "flex", flexDirection: "column", gap: "8px", width: "100%" }}>
              <TextField
                label={t("GH_QUERY")}
                value={ghQuery}
                disabled={busy}
                onChange={(e) => setGhQuery(e?.target?.value ?? "")}
              />
            </Focusable>
          </PanelSectionRow>
          <ButtonItem
            label={t("GH_SEARCH")}
            description={t("GH_SEARCH_DESC")}
            disabled={busy || !ghQuery.trim()}
            onClick={() => doGhSearch(1)}
          >
            {t("GH_SEARCH")}
          </ButtonItem>

          {ghResults.length ? (
            <PanelSectionRow>
              <div style={{ fontSize: "11px", opacity: 0.7, wordBreak: "break-word" }}>
                {t("GH_SEARCH_DONE", "Found {total} (showing {n})", {
                  total: ghTotal, n: ghResults.length,
                })}{" · "}{t("GH_PAGE_INFO", "page {p}", { p: ghPage })}
              </div>
            </PanelSectionRow>
          ) : null}
          {ghResults.map((item) => (
            <ButtonItem
              key={item.full_name}
              label={`${item.full_name} · ★${item.stars}`}
              description={item.archived ? t("GH_ARCHIVED") : (item.description || t("GH_NO_DESC"))}
              disabled={busy}
              onClick={() => doGhReleases(item)}
            >
              {item.full_name}
            </ButtonItem>
          ))}

          {ghResults.length ? (
            <PanelSectionRow>
              <Focusable style={{ display: "flex", flexDirection: "row", gap: "4px", width: "100%" }}>
                <DialogButton
                  style={{ flex: 1, minWidth: 0, height: "auto", padding: "5px 2px", fontSize: "12px" }}
                  disabled={busy || ghPage <= 1}
                  onClick={() => doGhSearch(ghPage - 1)}
                >
                  {t("GH_PAGE_PREV", "Prev")}
                </DialogButton>
                <DialogButton
                  style={{ flex: 1, minWidth: 0, height: "auto", padding: "5px 2px", fontSize: "12px" }}
                  disabled={busy || ghResults.length === 0 || ghPage >= 100}
                  onClick={() => doGhSearch(ghPage + 1)}
                >
                  {t("GH_PAGE_NEXT", "Next")}
                </DialogButton>
              </Focusable>
            </PanelSectionRow>
          ) : null}

          {ghSelected ? (
            <PanelSectionRow>
              <div style={{ fontSize: "11px", opacity: 0.7, wordBreak: "break-word" }}>
                {t("GH_SELECTED", "Selected: {name}", { name: ghSelected.full_name })}
              </div>
            </PanelSectionRow>
          ) : null}
          {ghRel && !ghRel.releases.length ? (
            <PanelSectionRow>
              <div style={{ fontSize: "11px", opacity: 0.7, wordBreak: "break-word" }}>
                {t("GH_NO_RELEASES")}
              </div>
            </PanelSectionRow>
          ) : null}
          {ghRel
            ? ghRel.releases.map((rel: GhRelease) =>
                rel.assets.map((asset) => (
                  <ButtonItem
                    key={`${rel.id}-${asset.id}`}
                    label={`${rel.tag_name} · ${assetSize(asset.size)}`}
                    description={`${asset.name} · ${asset.usable ? t("GH_ASSET_USABLE") : t("GH_ASSET_UNUSABLE")}`}
                    disabled={busy || !asset.usable}
                    onClick={() => doGhDownload(asset)}
                  >
                    {asset.name}
                  </ButtonItem>
                )),
              )
            : null}
          {ghRel
            ? ghRel.releases.map((rel: GhRelease) =>
                rel.assets.map((asset) =>
                  asset.usable ? (
                    <ButtonItem
                      key={`imp-${rel.id}-${asset.id}`}
                      label={t("GH_IMPORT_TITLE")}
                      description={`${asset.name} · ${t("GH_IMPORT_DESC")}`}
                      disabled={busy}
                      onClick={() => doGhImport(asset)}
                    >
                      {t("GH_IMPORT_TITLE")}
                    </ButtonItem>
                  ) : null,
                ),
              )
            : null}

          <PanelSectionRow>
            <div style={{ fontSize: "11px", opacity: 0.65, wordBreak: "break-word", marginTop: "6px" }}>
              {t("GH_DIRECT_DESC")}
            </div>
          </PanelSectionRow>
          <PanelSectionRow>
            <Focusable style={{ display: "flex", flexDirection: "column", gap: "8px", width: "100%" }}>
              <TextField
                label={t("GH_DIRECT_URL")}
                value={directUrlValue}
                disabled={busy}
                onChange={(e) => setDirectUrlValue(e?.target?.value ?? "")}
              />
            </Focusable>
          </PanelSectionRow>
          <ButtonItem
            label={t("GH_DIRECT_FETCH")}
            description={t("GH_DIRECT_DESC")}
            disabled={busy || !directUrlValue.trim()}
            onClick={doDirectDownload}
          >
            {t("GH_DIRECT_FETCH")}
          </ButtonItem>
          <ButtonItem
            label={t("GH_DIRECT_IMPORT")}
            description={t("GH_IMPORT_DESC")}
            disabled={busy || !directUrlValue.trim()}
            onClick={doDirectImport}
          >
            {t("GH_DIRECT_IMPORT")}
          </ButtonItem>

          <ButtonItem
            label={t("DEPS_BTN")}
            description={t("DEPS_BTN_DESC")}
            disabled={busy}
            onClick={doDepsPlan}
          >
            {t("DEPS_BTN_SUB")}
          </ButtonItem>
          {readOnly ? null : (
            <ButtonItem
              label={t("DEPS_INSTALL_BTN")}
              description={t("DEPS_INSTALL_DESC")}
              disabled={busy}
              onClick={doDepsInstall}
            >
              {t("DEPS_INSTALL_SUB")}
            </ButtonItem>
          )}
          {progressLine ? (
            <PanelSectionRow>
              <div style={{ fontSize: "12px", opacity: 0.8, wordBreak: "break-word" }}>{progressLine}</div>
            </PanelSectionRow>
          ) : null}

          {/* ── round 39: Nexus, metadata only ───────────────────────────── */}
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
            <div style={{ fontSize: "11px", opacity: 0.7, wordBreak: "break-word" }}>
              {keyStatusLine()}
            </div>
          </PanelSectionRow>
          {keyStatus && keyStatus.configured ? (
            <PanelSectionRow>
              <div style={{ fontSize: "10px", opacity: 0.45, wordBreak: "break-all" }}>
                {t("NEXUS_KEY_PATH", undefined, { path: keyStatus.path })}
              </div>
            </PanelSectionRow>
          ) : null}

          <PanelSectionRow>
            <Focusable style={{ display: "flex", flexDirection: "column", gap: "8px", width: "100%" }}>
              <TextField
                label={t("NEXUS_KEY_INPUT")}
                value={keyInput}
                disabled={busy}
                onChange={(e) => setKeyInput(e?.target?.value ?? "")}
              />
            </Focusable>
          </PanelSectionRow>
          <ButtonItem
            label={t("NEXUS_KEY_SAVE")}
            description={t("NEXUS_KEY_SAVE_DESC")}
            disabled={busy || !keyInput.trim()}
            onClick={doSaveKey}
          >
            {t("NEXUS_KEY_SAVE")}
          </ButtonItem>
          <ButtonItem
            label={t("NEXUS_VALIDATE")}
            description={t("NEXUS_VALIDATE_DESC")}
            disabled={busy || !keyStatus || !keyStatus.configured}
            onClick={doValidateKey}
          >
            {t("NEXUS_VALIDATE")}
          </ButtonItem>
          {nexusVerify ? (
            <PanelSectionRow>
              <div style={{ fontSize: "11px", opacity: 0.8, wordBreak: "break-word" }}>
                {nexusVerify}
              </div>
            </PanelSectionRow>
          ) : null}
          <ButtonItem
            label={t("NEXUS_KEY_CLEAR")}
            description={t("NEXUS_KEY_CLEAR_DESC")}
            disabled={busy || !keyStatus || !keyStatus.configured}
            onClick={doClearKey}
          >
            {t("NEXUS_KEY_CLEAR")}
          </ButtonItem>

          <PanelSectionRow>
            <div style={{ fontSize: "11px", opacity: 0.65, wordBreak: "break-word", marginTop: "6px" }}>
              {t("NEXUS_RECENT_DESC")}
            </div>
          </PanelSectionRow>
          <PanelSectionRow>
            <Focusable style={{ display: "flex", flexDirection: "row", gap: "4px", width: "100%" }}>
              <DialogButton
                style={{ flex: 1, minWidth: 0, height: "auto", padding: "5px 2px", fontSize: "12px" }}
                disabled={busy}
                onClick={() => doNexusRecent("latest_added")}
              >
                {t("NEXUS_RECENT_ADDED")}
              </DialogButton>
              <DialogButton
                style={{ flex: 1, minWidth: 0, height: "auto", padding: "5px 2px", fontSize: "12px" }}
                disabled={busy}
                onClick={() => doNexusRecent("latest_updated")}
              >
                {t("NEXUS_RECENT_UPDATED")}
              </DialogButton>
              <DialogButton
                style={{ flex: 1, minWidth: 0, height: "auto", padding: "5px 2px", fontSize: "12px" }}
                disabled={busy}
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
          <ButtonItem
            label={t("NEXUS_MOD_FETCH")}
            description={t("NEXUS_MOD_FETCH_DESC")}
            disabled={busy || !nexusModId.trim()}
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
            disabled={busy || !searchText.trim()}
            onClick={doSearch}
          >
            {t("SEARCH_SECTION")}
          </ButtonItem>

          {readOnly ? (
            <PanelSectionRow>
              <div style={{ fontSize: "11px", opacity: 0.65, wordBreak: "break-word" }}>
                {t("GH_B_GATE")}
              </div>
            </PanelSectionRow>
          ) : null}
        </PanelSection>
      ) : null}

      {/* ── 3c. 游戏：目录 + 已安装游戏库 ────────────────────────────── */}
      {openSection === "games" ? (
        <PanelSection>
          {status?.catalog && status.catalog.length > 0 ? (
            <ButtonItem label={t("CATALOG_BTN")} description={t("CATALOG_BTN_DESC")} disabled={busy} onClick={openGameCatalog}>
              {t("CATALOG_SUB")}
            </ButtonItem>
          ) : null}
          <ButtonItem
            label={t("LIB_REFRESH")}
            description={t("LIB_REFRESH_DESC")}
            disabled={busy}
            onClick={() => void openGameLibrary()}
          >
            {t("LIB_SECTION")}
          </ButtonItem>
        </PanelSection>
      ) : null}

      {/* ── 3d. 系统：刷新 / 历史 / 错误码 / 恢复 / 约束 ─────────────── */}
      {openSection === "system" ? (
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
