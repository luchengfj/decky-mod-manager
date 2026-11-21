/**
 * Self-contained dependency flow (fix for "dependencies cannot be one-click installed").
 *
 * WHY THIS EXISTS
 * ---------------
 * Two separate problems produced the same symptom:
 *
 * 1. `fetch_dependencies` resolves each missing dependency through the SMAPI
 *    index. That index also carries the mod's display name and its Nexus id,
 *    but the plugin only kept the GitHub repo. A dependency published on Nexus
 *    (no GitHub release asset) therefore resolved to nothing, and the panel
 *    could only say "0 of 2 can be downloaded" — with no address to send the
 *    user to, the feature was a dead end.
 *
 * 2. The confirm dialog ran through the panel's `runTwoPhase`, which is bound
 *    to `mounted.current` / `generation`. Any panel remount (which Steam's CEF
 *    performs on modal close) swallowed the callback and the second phase never
 *    fired. Same root cause as the uninstall and rollback bugs.
 *
 * So this module owns the whole flow: plan, present, open, install. It keeps
 * zero React state and uses the global modal, so a remount cannot drop it.
 */
import { fetchDependencies, openModPage, openSearchPage } from "./api";
import { showInfo, showListModal } from "./components/Modal";
import type { ListRow } from "./components/Modal";
import { t } from "./i18n";
import type { OpEnvelope } from "./types";

interface DepPlanRow {
  uniqueId?: string;
  name?: string | null;
  nexusID?: number | null;
  repo?: string | null;
  resolvable?: boolean;
  reason?: string;
  installed?: boolean;
  detail?: string;
  asset?: string;
}

interface DepPlanData {
  phase?: string;
  deps?: DepPlanRow[];
  fetchable?: number;
  total?: number;
  list?: DepPlanRow[];
  still_missing?: string[];
  note?: string;
}

/** Turn one plan row into a readable title + subtitle. */
function describe(row: DepPlanRow): { label: string; sub: string } {
  const uid = String(row.uniqueId || "?");
  const name = row.name ? String(row.name) : "";
  const label = name ? `${name}  (${uid})` : uid;
  const nexus = typeof row.nexusID === "number" ? row.nexusID : null;
  // A Nexus page wins over "we might fetch it": the site is the authoritative
  // download, and a monorepo asset that names a different mod is refused after
  // the download anyway (verified on device for selph.ExtraMachineConfig).
  if (nexus) {
    return {
      label,
      sub: t("DEP_WEB_SUB", "Nexus #{id}  ·  A = open download page", { id: String(nexus) }),
    };
  }
  if (row.resolvable) {
    return {
      label,
      sub: t("DEP_AUTO_SUB", "Can be installed here  ·  A = install", {}),
    };
  }
  return { label, sub: t("DEP_SEARCH_SUB", "Not in the mod index  ·  A = search on Nexus") };
}

/** Open the download page for one dependency. Never throws. */
async function openFor(row: DepPlanRow): Promise<void> {
  const nexus = typeof row.nexusID === "number" ? row.nexusID : null;
  if (nexus) {
    const r = await openModPage(nexus);
    if (!r.ok) {
      const url = (r.data as { url?: string } | null)?.url || "";
      showInfo(
        t("DEPS_TITLE", "Missing dependencies ({n})", { n: "1" }),
        [t("DEP_OPEN_FAIL", "Could not open the page: {why}", { why: String(r.detail || r.code || "—") }),
         ...(url ? ["", url] : [])],
        [],
      );
    }
    return;
  }
  // No index entry: the site's own search is the only honest destination.
  const q = String(row.uniqueId || "").replace(/[._]/g, " ").trim();
  await openSearchPage(q);
}

/** Translate a wire-level reason into a sentence the user can act on. */
function reasonText(reason: string | undefined): string {
  switch (reason) {
    case "no_repo_in_index": return t("DEPS_R_NO_REPO");
    case "no_zip_asset": return t("DEPS_R_NO_ZIP");
    case "candidate_failed":
    case "no_candidate_matched": return t("DEPS_R_NO_MATCH");
    case "install_refused": return t("DEPS_R_REFUSED");
    case "install_raised": return t("DEPS_R_RAISED");
    case "": return t("DEPS_R_OK");
    default: return t("DEPS_R_UNRESOLVABLE");
  }
}

function resultLines(d: DepPlanData): string[] {
  const list = d.list || d.deps || [];
  const out: string[] = [];
  for (const row of list) {
    const uid = String(row.uniqueId || "?");
    const name = row.name ? String(row.name) : "";
    const who = name ? `${name} (${uid})` : uid;
    if (row.installed) out.push(t("DEP_DONE_ROW", "Installed: {id}", { id: who }));
    else out.push(t("DEP_FAIL_ROW", "Not installed: {id} — {why}", {
      id: who,
      why: reasonText(String(row.reason ?? "")) || String(row.detail || "—"),
    }));
  }
  const still = d.still_missing || [];
  if (still.length) out.push(t("DEPS_STILL", "Still missing: {ids}", { ids: still.join(", ") }));
  if (!out.length) out.push(t("DEP_NO_ROWS", "Nothing was installed."));
  return out;
}

/** Install everything the plugin can fetch on its own. */
async function installFetchable(plan: DepPlanData): Promise<void> {
  const r: OpEnvelope = await fetchDependencies(true, true);
  if (!r.ok) {
    showInfo(
      t("DEP_INSTALL_RESULT", "Dependency result"),
      [t("DEP_INSTALL_FAIL", "Install failed: {why}", { why: String(r.detail || r.code || "—") })],
      [],
    );
    return;
  }
  const d = (r.data || {}) as DepPlanData;
  const list = d.list || d.deps || [];
  const installed = list.filter((x) => x.installed).length;
  // A fetch can fail on content, not on networking: a monorepo publishes many
  // mods and the zip it serves may belong to a different one (verified on
  // device for selph.ExtraMachineConfig, whose asset declares FurnitureMachine).
  // Those rows usually still have a Nexus page, so hand it over rather than
  // leaving the user at a dead end.
  const failed = list.filter((x) => !x.installed && typeof x.nexusID === "number");
  const actions = failed.slice(0, 2).map((row) => ({
    label: t("DEP_OPEN_ONE", "Open {name} page", {
      name: row.name ? String(row.name) : String(row.uniqueId || ""),
    }),
    onClick: (close: () => void) => {
      close();
      void openFor(row);
    },
  }));
  showInfo(
    t("DEP_INSTALL_RESULT", "Dependency result"),
    [t("DEP_INSTALLED_N", "Installed {n} dependencies.", { n: String(installed) }), "", ...resultLines(d)],
    actions,
    t("DEP_AFTER_INSTALL", "New downloads from the browser install automatically when you return."),
  );
  void plan;
}

/**
 * One entry point for both panel buttons:
 *   - everything fetchable  -> confirm-free install (the button already is consent)
 *   - nothing fetchable     -> a list that opens each mod's download page
 *   - mixed                 -> list with an install row on top
 */
export function runDepsFlow(): void {
  (async () => {
    const r = await fetchDependencies(true, false);
    if (!r.ok) {
      showInfo(
        t("DEPS_TITLE", "Missing dependencies ({n})", { n: "0" }),
        [t("DEP_PLAN_FAIL", "Could not read the dependency plan: {why}", {
          why: String(r.detail || r.code || "—"),
        })],
        [],
      );
      return;
    }
    const d = (r.data || {}) as DepPlanData;
    const deps = d.deps || [];
    const total = typeof d.total === "number" ? d.total : deps.length;
    const fetchable = typeof d.fetchable === "number" ? d.fetchable : 0;

    if (!total) {
      showInfo(t("DEPS_TITLE", "Missing dependencies ({n})", { n: "0" }), [t("DEPS_NONE")], []);
      return;
    }

    // Every dependency can be fetched: no list needed, just do it.
    if (fetchable >= total) {
      await installFetchable(d);
      return;
    }

    const rows: ListRow[] = [];

    if (fetchable > 0) {
      rows.push({
        label: t("DEP_INSTALL_ALL", "Install {n} fetchable dependencies", { n: String(fetchable) }),
        sub: t("DEP_INSTALL_ALL_SUB", "Downloads from GitHub and verifies each manifest"),
        onActivate: (close) => {
          close();
          void installFetchable(d);
        },
      });
    }

    const manual = deps.filter((x) => !x.resolvable);
    if (manual.length > 1) {
      rows.push({
        label: t("DEP_OPEN_ALL", "Open all {n} download pages", { n: String(manual.length) }),
        sub: t("DEP_OPEN_ALL_SUB", "One at a time — download each, then come back"),
        onActivate: (close) => {
          close();
          (async () => {
            for (const row of manual) {
              await openFor(row);
            }
          })().catch(() => { /* opening is best-effort; never break the flow */ });
        },
      });
    }

    for (const row of deps) {
      const view = describe(row);
      rows.push({
        label: view.label,
        sub: view.sub,
        onActivate: (close) => {
          close();
          // Order matters and matches describe(): a known Nexus page is the
          // most reliable destination; only an id we cannot place falls back
          // to the plugin's own GitHub fetch (or a site search).
          if (typeof row.nexusID === "number") {
            void openFor(row);
            return;
          }
          if (row.resolvable) {
            void installFetchable(d);
            return;
          }
          void openFor(row);
        },
      });
    }

    showListModal(
      t("DEPS_TITLE", "Missing dependencies ({n})", { n: String(total) }),
      rows,
      t("DEP_LIST_SUB", "{auto} can be installed here · {manual} need the Nexus page",
        { auto: String(fetchable), manual: String(total - fetchable) }),
    );
  })().catch((e) => {
    showInfo(t("DEPS_TITLE", "Missing dependencies ({n})", { n: "0" }), [String(e)], []);
  });
}
