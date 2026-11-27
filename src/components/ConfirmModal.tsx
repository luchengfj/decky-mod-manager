/**
 * Two-phase confirm dialog (§4 dry-run, §5.1 ops #3/#6/#9).
 *
 * The backend's phase-1 response is a NO-WRITE payload. This modal shows:
 *   - the human confirm_text
 *   - the W1 (state file) and W2 (mod dir / quarantine) ABSOLUTE paths
 *   - A = confirm (calls the same RPC with afterConfirm=true)
 *   - B = cancel (close)
 *
 * We build the body from the most stable @decky/ui primitives (Focusable +
 * DialogButton) so it depends on as few version-specific props as possible.
 * V3 confirmed on device 2026-11-12 against the LOCKED @decky/ui 4.16.5:
 * `showModal` returns `ShowModalResult` with `Close()`, and `Focusable` uses
 * `onOKActionDescription` (not `onActivateActionDescription`). A/B layout is
 * gamepad-first.
 *
 * Callback-based (not Promise-based) so a dismissed modal can never leave a
 * pending operation hung.
 * Step 1: labels go through t(); a backend phase-1 payload may carry a stable
 * confirm_key + confirm_vars, which we localize via t(). The original English
 * confirm_text is kept verbatim as the fallback for UI-built confirms.
 */
import { Focusable, DialogButton, showModal } from "@decky/ui";
import { MODAL_BODY_STYLE } from "./Modal";
import { t } from "../i18n";
import type { ConfirmData } from "../types";
import { FONT, SPACE } from "../theme";

type Decision = (confirmed: boolean) => void;

export function showConfirm(data: ConfirmData, decide: Decision): void {
  let settled = false;
  const finish = (v: boolean) => {
    if (settled) return;
    settled = true;
    decide(v);
    handle?.Close?.();
  };

  // selection B: file_drop targets may include a null W1 (no state file).
  // Skip null/empty so the modal never renders "w1_state_file: null".
  const pathLines = Object.entries(data.targets || {})
    .filter(([, v]) => v != null && v !== "")
    .map(([k, v]) => `${k}: ${v}`);

  // GAP1: prefer the backend's stable confirm_key + JSON-safe confirm_vars;
  // fall back to the original English confirm_text for UI-built confirms.
  const text = data.confirm_key
    ? t(data.confirm_key, data.confirm_text, data.confirm_vars)
    : data.confirm_text;

  const body = (
    <Focusable
      onCancelActionDescription={t("BTN_CANCEL")}
      onCancel={() => finish(false)}
      onOKActionDescription={t("BTN_CONFIRM")}
      style={MODAL_BODY_STYLE}
    >
      <div style={{ fontWeight: 700, fontSize: FONT.heading }}>{t("CONFIRM_TITLE")}</div>
      <div style={{ fontSize: FONT.lead, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
        {text}
      </div>
      {pathLines.length ? (
        <div style={{ fontSize: FONT.body, opacity: 0.75, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
          {pathLines.join("\n")}
        </div>
      ) : null}
      <Focusable style={{ display: "flex", gap: SPACE.lg, marginTop: SPACE.md }}>
        <DialogButton onClick={() => finish(true)}>{t("BTN_CONFIRM")}</DialogButton>
        <DialogButton onClick={() => finish(false)}>{t("BTN_CANCEL")}</DialogButton>
      </Focusable>
    </Focusable>
  );

  // showModal returns a handle exposing Close() in the template's @decky/ui.
  const handle = showModal(body);
}
