/**
 * Uniform error presentation (§5.2).
 *
 * Rules encoded here:
 *   - one code = one friendly message; the raw `code` is shown in small text
 *   - a log path is always offered (when the backend provided one)
 *   - rollback_available surfaces a "Rollback" action button
 *   - NO traceback, NO 'steamos-readonly disable', 'sudo', 'flatpak override'
 *     wording is ever rendered (the backend guarantees this; we just display)
 *   - A-button dismissable, gamepad reachable (Focusable)
 *
 * Step 1: the friendly message is localized via errorText(code, message), the
 * raw code and log path stay verbatim (they are identifiers/paths, not prose).
 */
import { Focusable, DialogButton } from "@decky/ui";
import { t, errorText } from "../i18n";
import type { Envelope } from "../types";
import { FONT, SPACE, BOX_SIZING } from "../theme";

interface Props {
  env: Envelope<unknown>;
  onDismiss: () => void;
  onRollback?: (txn: string) => void;
  txn?: string;
}

export function ErrorView({ env, onDismiss, onRollback, txn }: Props) {
  const message = errorText(env.code, env.message) || t("ERR_TITLE");
  return (
    <Focusable style={{ display: "flex", flexDirection: "column", gap: SPACE.md, width: "100%", boxSizing: BOX_SIZING }}>
      <div style={{ fontWeight: 600, fontSize: FONT.strong, wordBreak: "break-word" }}>{message}</div>
      {env.detail ? (
        <div style={{ opacity: 0.8, fontSize: FONT.body, wordBreak: "break-word" }}>{env.detail}</div>
      ) : null}
      <div style={{ opacity: 0.55, fontSize: FONT.caption }}>
        {t("CODE_LABEL", "Code: {code}", { code: env.code || "E_UNKNOWN" })}
        {env.log_path ? t("LOG_LABEL", " · Log: {path}", { path: env.log_path }) : ""}
      </div>
      {/* Round 81: this error view is shown inside a modal, so the button row
          is a plain block -- PanelSectionRow brings the QAM panel's width and
          padding with it and pushed the buttons off the modal's edge. */}
      <Focusable style={{ display: "flex", gap: SPACE.md, width: "100%", boxSizing: BOX_SIZING }}>
        <DialogButton onClick={onDismiss}>{t("BTN_OK")}</DialogButton>
        {env.rollback_available && onRollback ? (
          <DialogButton onClick={() => onRollback(txn || "")}>{t("BTN_ROLLBACK")}</DialogButton>
        ) : null}
      </Focusable>
    </Focusable>
  );
}
