/**
 * Self-contained two-phase uninstall flow.
 *
 * WHY THIS EXISTS
 * ---------------
 * The original uninstall ran through the panel's `runTwoPhase`, which guards
 * every RPC result with `mounted.current` and `generation.current`. On Steam
 * Deck, closing a Decky modal makes the Steam CEF re-mount the host panel.
 * That bumps `generation` and flips `mounted`, so the in-flight phase-1 result
 * was silently discarded (`generation.current !== g` -> return) and the
 * confirmation dialog never appeared — even though the backend had already
 * answered with a perfectly good confirm payload (verified in webhelper_js.txt:
 * every `uninstall,<id>,false` call returned `Resolved PY call ...`).
 *
 * A `setTimeout` wrapper did not help: its `mounted.current` check belongs to
 * the OLD component instance, which is gone after the remount.
 *
 * This module deliberately keeps ZERO React state. It owns the whole flow:
 *   phase-1 (no write) -> confirmation modal -> phase-2 (write) -> toast.
 * Because `showModal` is a global Steam overlay (not part of the panel tree),
 * it survives the panel remount and the confirmation always shows.
 */
import { showModal, Focusable, DialogButton } from "@decky/ui";
import { uninstallMod } from "./api";
import { t } from "./i18n";
import type { ConfirmData, OpEnvelope } from "./types";

type Handle = { Close?: () => void } | null;

function isConfirmData(d: unknown): d is ConfirmData {
  return !!d && typeof d === "object" && (d as ConfirmData).phase === "confirm";
}

/** Result shown to the user after the flow settles (handed back to the caller
 *  so the panel can refresh its own status/inbox from the on-disk journal). */
export interface UninstallFlowResult {
  ok: boolean;
  code?: string | null;
  detail?: string;
  done: boolean;
}

/**
 * Run the whole uninstall. Never throws; reports outcome via `onDone`.
 * `onDone` is called once the flow settles (success, cancel, or error).
 */
export function runUninstallFlow(dirName: string, onDone: (r: UninstallFlowResult) => void): void {
  // Phase 1 — ask the backend what it would do. No write.
  uninstallMod(dirName, false)
    .then((first: OpEnvelope) => {
      if (!first.ok) {
        onDone({ ok: false, code: first.code, detail: first.detail, done: false });
        return;
      }
      if (!isConfirmData(first.data)) {
        // Backend executed without a confirm payload — treat as unexpected.
        onDone({
          ok: false,
          code: first.code || "E_NO_CONFIRM",
          detail: first.detail,
          done: false,
        });
        return;
      }

      const data = first.data as ConfirmData;
      let handle: Handle = null;
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        handle?.Close?.();
      };

      const pathLines = Object.entries(data.targets || {})
        .filter(([, v]) => v != null && v !== "")
        .map(([k, v]) => `${k}: ${v}`);
      const text = data.confirm_key
        ? t(data.confirm_key, data.confirm_text, data.confirm_vars)
        : data.confirm_text;

      const body = (
        <Focusable
          onCancelActionDescription={t("BTN_CANCEL")}
          onCancel={() => {
            finish();
            onDone({ ok: true, done: false }); // cancelled
          }}
          onOKActionDescription={t("BTN_CONFIRM")}
          style={{ display: "flex", flexDirection: "column", gap: "12px", padding: "16px" }}
        >
          <div style={{ fontWeight: 700, fontSize: "18px" }}>{t("CONFIRM_TITLE")}</div>
          <div style={{ fontSize: "14px", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
            {text}
          </div>
          {pathLines.length ? (
            <div style={{ fontSize: "12px", opacity: 0.75, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {pathLines.join("\n")}
            </div>
          ) : null}
          <Focusable style={{ display: "flex", gap: "10px", marginTop: "8px" }}>
            <DialogButton
              onClick={() => {
                finish();
                // Phase 2 — actually write. Independent of any panel instance.
                uninstallMod(dirName, true)
                  .then((second: OpEnvelope) => {
                    onDone({
                      ok: second.ok,
                      code: second.code,
                      detail: second.detail,
                      done: !!second.ok,
                    });
                  })
                  .catch((e) => onDone({ ok: false, detail: String(e), done: false }));
              }}
            >
              {t("BTN_CONFIRM")}
            </DialogButton>
            <DialogButton
              onClick={() => {
                finish();
                onDone({ ok: true, done: false }); // cancelled
              }}
            >
              {t("BTN_CANCEL")}
            </DialogButton>
          </Focusable>
        </Focusable>
      );

      handle = showModal(body) as Handle;
    })
    .catch((e) => onDone({ ok: false, detail: String(e), done: false }));
}
