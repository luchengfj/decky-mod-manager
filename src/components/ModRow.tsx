/**
 * One managed-mod row (§5.1 ops #4/#5/#6).
 *
 * Presentational only. Every control is a focusable DialogButton so the whole
 * row is reachable with D-pad + A/B. Enable/disable is a single, reversible
 * A-press with NO second confirmation (per §5.1 op #5); uninstall always goes
 * through a confirm dialog upstream (op #6).
 *
 * Step 1 (selection B): all labels go through t() — no hard-coded UI copy.
 */
import { Focusable, DialogButton, PanelSectionRow } from "@decky/ui";
import { t } from "../i18n";
import type { ManagedMod } from "../types";

interface Props {
  mod: ManagedMod;
  busy: boolean;
  /** selection B: SMAPI file_drop has NO separate enable step (install==enable). */
  canToggle: boolean;
  onToggle: (mod: ManagedMod) => void;
  onUninstall: (mod: ManagedMod) => void;
  onDetail: (mod: ManagedMod) => void;
}

export function ModRow({ mod, busy, canToggle, onToggle, onUninstall, onDetail }: Props) {
  // For file_drop every managed dir IS the enabled state, so "Enabled"/"Disabled"
  // is misleading: show the neutral "Installed" instead.
  const status = canToggle
    ? (mod.enabled ? t("MOD_ENABLED") : t("MOD_DISABLED"))
    : t("MOD_INSTALLED");
  return (
    <PanelSectionRow>
      <Focusable
        style={{ display: "flex", flexDirection: "column", gap: "8px", width: "100%" }}
      >
        <div style={{ fontWeight: 600, fontSize: "14px" }}>
          {mod.name || mod.packageId} <span style={{ opacity: 0.6, fontWeight: 400 }}>· v{mod.version || t("Q_MARK")}</span>
        </div>
        <div style={{ fontSize: "11px", opacity: 0.6, wordBreak: "break-word" }}>
          {mod.packageId} · {status}
        </div>
        <Focusable style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
          {canToggle ? (
            <DialogButton disabled={busy} onClick={() => onToggle(mod)}>
              {mod.enabled ? t("BTN_DISABLE") : t("BTN_ENABLE")}
            </DialogButton>
          ) : null}
          <DialogButton disabled={busy} onClick={() => onDetail(mod)}>
            {t("BTN_DETAILS")}
          </DialogButton>
          <DialogButton disabled={busy} onClick={() => onUninstall(mod)}>
            {t("BTN_UNINSTALL")}
          </DialogButton>
        </Focusable>
      </Focusable>
    </PanelSectionRow>
  );
}
