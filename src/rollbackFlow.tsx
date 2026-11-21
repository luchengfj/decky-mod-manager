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
import { rollbackTxn } from "./api";
import { t } from "./i18n";
import type { OpEnvelope, OpResultData } from "./types";

type Handle = { Close?: () => void } | null;

export interface RollbackOutcome {
  ok: boolean;
  restored?: string;
  code?: string | null;
  detail?: string;
}

/** Ask for confirmation (global modal), then roll back txn. Never throws. */
export function runRollbackFlow(
  txn: string,
  modLabel: string,
  quarantinePath: string,
  onDone: (r: RollbackOutcome) => void,
): void {
  let handle: Handle = null;
  let settled = false;
  const close = () => { if (!settled) { settled = true; handle?.Close?.(); } };

  const body = (
    <Focusable
      onCancelActionDescription={t("BTN_CANCEL")}
      onCancel={() => { close(); onDone({ ok: true }); }}
      onOKActionDescription={t("BTN_CONFIRM")}
      style={{ display: "flex", flexDirection: "column", gap: "12px", padding: "16px" }}
    >
      <div style={{ fontWeight: 700, fontSize: "18px" }}>{t("RB_TITLE", "Restore mod")}</div>
      <div style={{ fontSize: "14px", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
        {t("RB_CONFIRM", "Restore {mod} back into the game's Mods folder?\nNothing is deleted — this undoes the uninstall.", { mod: modLabel })}
      </div>
      <div style={{ fontSize: "12px", opacity: 0.75, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
        {t("RB_FROM", "From: {q}", { q: quarantinePath })}
      </div>
      <Focusable style={{ display: "flex", gap: "10px", marginTop: "8px" }}>
        <DialogButton
          onClick={() => {
            close();
            rollbackTxn(txn)
              .then((r: OpEnvelope) => {
                if (!r.ok) {
                  onDone({ ok: false, code: r.code, detail: r.detail });
                  return;
                }
                const d = (r.data || {}) as OpResultData;
                onDone({ ok: true, restored: d.restored || modLabel });
              })
              .catch((e) => onDone({ ok: false, detail: String(e) }));
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
