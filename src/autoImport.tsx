/**
 * One-tap "import my newly downloaded mods" flow.
 *
 * WHY
 * ---
 * Game Mode has no file manager and a free Nexus account cannot be downloaded
 * through the API, so the only reliable path is: open the mod page in the
 * browser -> download the ZIP (lands in ~/Downloads) -> come back and import.
 * That last step used to be 3 taps (Inbox -> preview -> confirm) per file, and
 * the Downloads ZIP was buried among the plugin's own inbox files.
 *
 * This module does it in one tap: scan the DECLARED import roots (inbox +
 * Downloads, read-only, from the backend), and for each ZIP that is NOT already
 * installed, run the two-phase install automatically.
 *
 * SAFETY GUARDS (so "auto" never means "installs garbage"):
 *   1. Only real .zip files from declared roots. Steam's half-downloaded files
 *      use .crdownload and are never listed by list_inbox().
 *   2. inspect() must succeed and yield a real mod identity — a non-mod ZIP or
 *      a corrupt archive is skipped.
 *   3. Skip if uniqueId is already on disk (conflict.duplicate or
 *      same_unique_id_dirs) — never create a second copy.
 *   4. Skip usable FOMOD archives — those need the user's choices, so they go
 *      through the normal manual preview instead of being auto-extracted.
 *   5. Two-phase install: phase-1 dry-run, then phase-2 only if phase-1 is a
 *      proper confirm payload. No blind writes.
 *
 * Module-level state + a global modal: survives the Steam-CEF panel remount.
 */
import { showModal, Focusable, DialogButton } from "@decky/ui";
import { MODAL_BODY_STYLE } from "./components/Modal";
import { listInbox, inspectZip, installMod } from "./api";
import { t } from "./i18n";
import type { InboxData, InboxItem, InspectData, ConfirmData, OpEnvelope } from "./types";
import { FONT, SPACE } from "./theme";

type Handle = { Close?: () => void } | null;

export interface AutoImportOutcome {
  ok: boolean;
  installed: string[];
  skipped: Array<{ name: string; why: string }>;
}

function isConfirmData(d: unknown): d is ConfirmData {
  return !!d && typeof d === "object" && (d as ConfirmData).phase === "confirm";
}

/** Paths already handled this plugin session, so a panel remount never
 *  re-installs or re-reports the same ZIP. Module-level = survives remount. */
const seen = new Set<string>();

/** Core scan+install. `onlyNew` skips paths in `seen`. Adds handled paths to
 *  `seen` on success / already-installed / install-options (NOT on transient
 *  unreadable, so a half-downloaded file can be retried next time). */
async function scanAndInstall(onlyNew: boolean): Promise<AutoImportOutcome> {
  const installed: string[] = [];
  const skipped: Array<{ name: string; why: string }> = [];
  const lr = await listInbox();
  if (!lr.ok || !lr.data) return { ok: false, installed, skipped };
  const data = lr.data as InboxData;
  const inboxPath = (data.inbox || "").replace(/\\/g, "/").toLowerCase();
  const candidates: InboxItem[] = (data.items || []).filter((it) => {
    const p = (it.path || "").replace(/\\/g, "/").toLowerCase();
    if (p.startsWith(inboxPath)) return false;         // inbox = plugin's own
    if (onlyNew && seen.has(it.path || "")) return false;
    return true;
  });

  for (const it of candidates) {
    const name = it.name || it.path?.split("/").pop() || "?";
    let ins: OpEnvelope;
    try {
      ins = await inspectZip(it.path);
    } catch {
      // Transient: leave out of `seen` so a later pass retries.
      skipped.push({ name, why: t("AI_SKIP_UNREADABLE", "unreadable archive") });
      continue;
    }
    if (!ins.ok || !ins.data) {
      skipped.push({ name, why: t("AI_SKIP_NOTMOD", "not a valid mod ZIP") });
      continue;
    }
    const d = ins.data as InspectData;
    const same = d.conflict?.same_unique_id_dirs || [];
    if (d.conflict?.duplicate || same.length) {
      skipped.push({ name, why: t("AI_SKIP_INSTALLED", "already installed") });
      seen.add(it.path || "");
      continue;
    }
    if (d.fomod?.present && d.fomod.usable && (d.fomod.steps || []).length) {
      skipped.push({ name, why: t("AI_SKIP_FOMOD", "has install options — import manually") });
      seen.add(it.path || "");   // don't nag on every mount; manual button still works
      continue;
    }
    try {
      const first = await installMod(it.path, false, null);
      if (!first.ok || !isConfirmData(first.data)) {
        skipped.push({ name, why: t("AI_SKIP_REFUSED", "install refused") });
        continue;
      }
      const second = await installMod(it.path, true, null);
      if (second.ok) {
        installed.push(d.mod?.name || name);
        seen.add(it.path || "");
      } else {
        skipped.push({ name, why: t("AI_SKIP_FAILED", "install failed") });
      }
    } catch {
      skipped.push({ name, why: t("AI_SKIP_FAILED", "install failed") });
    }
  }
  return { ok: true, installed, skipped };
}

/** Manual one-tap flow: scan ALL new-download candidates (ignores `seen`, so
 *  the user can retry) and show a summary modal. Never throws. */
export function autoImportNew(onDone?: (r: AutoImportOutcome) => void): void {
  scanAndInstall(false)
    .then((r) => { showSummary(r); if (onDone) onDone(r); })
    .catch(() => { const r = { ok: false, installed: [], skipped: [] }; showSummary(r); if (onDone) onDone(r); });
}

/** Silent background pass for panel mount: auto-installs brand-new downloads
 *  only (respects `seen`), no modal. Caller decides how to notify the user. */
export function autoImportSilent(): Promise<AutoImportOutcome> {
  return scanAndInstall(true).catch(() => ({ ok: false, installed: [], skipped: [] }));
}

function showSummary(r: AutoImportOutcome): void {
  let handle: Handle = null;
  const close = () => handle?.Close?.();
  const lines: string[] = [];
  if (r.installed.length) {
    lines.push(t("AI_DONE", "Installed {n} mod(s):", { n: String(r.installed.length) }));
    r.installed.forEach((m) => lines.push("  ✓ " + m));
  }
  if (r.skipped.length) {
    if (lines.length) lines.push("");
    lines.push(t("AI_SKIPPED", "Skipped {n}:", { n: String(r.skipped.length) }));
    r.skipped.forEach((s) => lines.push("  · " + s.name + " — " + s.why));
  }
  if (!lines.length) {
    lines.push(r.ok
      ? t("AI_NONE", "No new downloads found. Nothing to import.")
      : t("AI_ERROR", "Could not read the download folders."));
  }
  const body = (
    <Focusable
      onCancel={close}
      onCancelActionDescription={t("BTN_BACK")}
      onOKActionDescription={t("BTN_OK")}
      style={MODAL_BODY_STYLE}
    >
      <div style={{ fontWeight: 700, fontSize: FONT.title }}>{t("AI_TITLE", "Import new downloads")}</div>
      <div style={{ fontSize: FONT.bodyLg, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
        {lines.join("\n")}
      </div>
      <Focusable style={{ marginTop: SPACE.sm }}>
        <DialogButton onClick={close}>{t("BTN_OK", "OK")}</DialogButton>
      </Focusable>
    </Focusable>
  );
  handle = showModal(body) as Handle;
}
