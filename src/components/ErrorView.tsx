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
import { Focusable, DialogButton, PanelSectionRow } from "@decky/ui";
import { t, errorText } from "../i18n";
import type { Envelope } from "../types";

interface Props {
  env: Envelope<unknown>;
  onDismiss: () => void;
  onRollback?: (txn: string) => void;
  txn?: string;
}

export function ErrorView({ env, onDismiss, onRollback, txn }: Props) {
  const message = errorText(env.code, env.message) || t("ERR_TITLE");
  return (
    <Focusable style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
      <div style={{ fontWeight: 600, fontSize: "15px" }}>{message}</div>
      {env.detail ? (
        <div style={{ opacity: 0.8, fontSize: "12px", wordBreak: "break-word" }}>{env.detail}</div>
      ) : null}
      <div style={{ opacity: 0.55, fontSize: "11px" }}>
        {t("CODE_LABEL", "Code: {code}", { code: env.code || "E_UNKNOWN" })}
        {env.log_path ? t("LOG_LABEL", " · Log: {path}", { path: env.log_path }) : ""}
      </div>
      <PanelSectionRow>
        <Focusable style={{ display: "flex", gap: "8px", width: "100%" }}>
          <DialogButton onClick={onDismiss}>{t("BTN_OK")}</DialogButton>
          {env.rollback_available && onRollback ? (
            <DialogButton onClick={() => onRollback(txn || "")}>{t("BTN_ROLLBACK")}</DialogButton>
          ) : null}
        </Focusable>
      </PanelSectionRow>
    </Focusable>
  );
}
