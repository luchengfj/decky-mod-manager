/**
 * Self-contained rollback flow (root-fix for the "restore did nothing" bug).
 *
 * WHY
 * ---
 * The old confirmRollback lived inside the panel and used showConfirm + the
 * panel's mounted.current / generation guards. Selecting a History row closes
 * that modal, and Steam's CEF re-mounts the host panel on modal close — which
 * bumps generation and flips mounted, so the confirm dialog and its callback
 * were silently dropped. The RPC never fired (verified: no rollback call in
 * webhelper_js.txt after the user tapped restore).
 *
 * Like uninstallFlow, this module keeps ZERO React state. The global modal and
 * the RPC are independent of any panel instance, so a remount cannot swallow it.
 */
import { showModal, Focusable, DialogButton } from "@decky/ui";
import { MODAL_BODY_STYLE } from "./components/Modal";
import { rollbackTxn } from "./api";
import { t } from "./i18n";
import type { OpEnvelope, OpResultData } from "./types";
import { FONT, SPACE } from "./theme";

type Handle = { Close?: () => void } | null;

export interface RollbackOutcome {
  ok: boolean;
  restored?: string;
  code?: string | null;
  detail?: string;
}

/**
 * Ask for confirmation (global modal), then roll back txn. Never throws.
 *
 * `setBusy` is optional so the module keeps working for callers that have no
 * panel state (and for tests). When supplied it is raised only after the user
 * confirms — cancelling never touches it — and cleared on BOTH the then and
 * catch paths BEFORE `onDone`, because `onDone` opens a fresh modal and a
 * still-busy panel would leave that modal's buttons disabled.
 */
export function runRollbackFlow(
  txn: string,
  modLabel: string,
  quarantinePath: string,
  onDone: (r: RollbackOutcome) => void,
  setBusy?: (v: boolean) => void,
): void {
  let handle: Handle = null;
  let settled = false;
  const close = () => { if (!settled) { settled = true; handle?.Close?.(); } };

  const body = (
    <Focusable
      onCancelActionDescription={t("BTN_CANCEL")}
      onCancel={() => { close(); onDone({ ok: true }); }}
      onOKActionDescription={t("BTN_CONFIRM")}
      style={MODAL_BODY_STYLE}
    >
      <div style={{ fontWeight: 700, fontSize: FONT.heading }}>{t("RB_TITLE", "Restore mod")}</div>
      <div style={{ fontSize: FONT.lead, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
        {t("RB_CONFIRM", "Restore {mod} back into the game's Mods folder?\nNothing is deleted — this undoes the uninstall.", { mod: modLabel })}
      </div>
      <div style={{ fontSize: FONT.body, opacity: 0.75, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
        {t("RB_FROM", "From: {q}", { q: quarantinePath })}
      </div>
      <Focusable style={{ display: "flex", gap: SPACE.lg, marginTop: SPACE.md }}>
        <DialogButton
          onClick={() => {
            close();
            // Busy only once the user has actually confirmed: the cancel
            // button and the B-button both leave it alone.
            setBusy?.(true);
            rollbackTxn(txn)
              .then((r: OpEnvelope): RollbackOutcome => {
                if (!r.ok) return { ok: false, code: r.code, detail: r.detail };
                const d = (r.data || {}) as OpResultData;
                return { ok: true, restored: d.restored || modLabel };
              })
              .catch((e): RollbackOutcome => ({ ok: false, detail: String(e) }))
              // Clear before onDone: onDone opens a new modal, and a panel
              // still marked busy would render that modal's buttons disabled.
              .finally(() => { setBusy?.(false); })
              .then((outcome) => onDone(outcome));
          }}
        >
          {t("BTN_CONFIRM")}
        </DialogButton>
        <DialogButton onClick={() => { close(); onDone({ ok: true }); }}>
          {t("BTN_CANCEL")}
        </DialogButton>
      </Focusable>
    </Focusable>
  );
  handle = showModal(body) as Handle;
}
