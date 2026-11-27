/**
 * Reusable gamepad-first modal helpers (§5.1 focus rules).
 *
 * Rules encoded here:
 *   - every interactive element is a focusable DialogButton (D-pad reachable)
 *   - A activates, B always closes (Focusable.onCancel)
 *   - buttons are rendered in a DETERMINISTIC order (no focus trap)
 *   - long text is scrollable with the D-pad (whiteSpace: pre-wrap, no hover)
 *   - no raw traceback, no drag/drop, no right-click
 *
 * All version-specific @decky/ui surface is concentrated in this file so the
 * LOCKED-template review (VERIFICATION.md, V3) only has to check one place.
 * V3 confirmed on device 2026-11-12 against the LOCKED @decky/ui 4.16.5:
 *   - `showModal` returns `ShowModalResult` with a required `Close()`.
 *   - `Focusable` accepts `onCancel` / `onCancelActionDescription` /
 *     `onOKActionDescription` (FooterLegendProps); there is NO
 *     `onActivateActionDescription`.
 */
import { Focusable, DialogButton, showModal } from "@decky/ui";
import { useState } from "react";
import { t } from "../i18n";
import type { Envelope, FomodDescriptor } from "../types";
import { ErrorView } from "./ErrorView";
import { FONT, SPACE, BOX_SIZING } from "../theme";

type ModalHandle = { Close?: () => void } | null;

function asHandle(v: unknown): ModalHandle {
  return (v && typeof v === "object" ? v : null) as ModalHandle;
}

export interface ModalAction {
  label: string;
  /** Called with a `close()` so the action can dismiss the modal itself. */
  onClick: (close: () => void) => void;
}

export interface ListRow {
  label: string;
  sub?: string;
  /** A-button activation. */
  onActivate: (close: () => void) => void;
  /** Disabled rows are rendered but moved out of the focus order. */
  disabled?: boolean;
}

const colStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: SPACE.lg,
  padding: SPACE.xl,
  // Round 81: `maxHeight`/`overflowY` were declared only here, so this modal
  // scrolled and the four others (ConfirmModal, rollbackFlow, uninstallFlow,
  // autoImport) grew past the screen. `minHeight: 0` is what actually lets a
  // flex child scroll instead of stretching its parent.
  maxHeight: "70vh",
  overflowY: "auto",
  minHeight: 0,
  // Round 83: this body carries `padding` and is the direct child of the modal
  // frame. The frame gives it a width, so under the default content-box the
  // padding was added on top of that width and the body came out wider than the
  // frame. Nothing scrolls horizontally in a QAM modal, so the overflow simply
  // fell off the right edge.
  boxSizing: BOX_SIZING,
};

/**
 * The one modal body style, exported so every dialog scrolls instead of
 * overflowing. Round 81: four of the five dialogs had a near-copy of this
 * object with `maxHeight`/`overflowY` missing, and a long confirm message
 * pushed its buttons below the screen edge where the D-pad could not reach
 * them.
 */
export const MODAL_BODY_STYLE: React.CSSProperties = colStyle;

/** A generic information / preview modal. A activates a button, B closes. */
export function showInfo(
  title: string,
  lines: string[],
  actions: ModalAction[],
  subtitle?: string,
): void {
  let handle: ModalHandle = null;
  const close = () => handle?.Close?.();

  const body = (
    <Focusable
      onCancel={close}
      onCancelActionDescription={t("BTN_BACK")}
      onOKActionDescription={t("BTN_SELECT")}
      style={colStyle}
    >
      <div style={{ fontWeight: 700, fontSize: FONT.heading }}>{title}</div>
      {subtitle ? (
        <div style={{ fontSize: FONT.body, opacity: 0.7, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
          {subtitle}
        </div>
      ) : null}
      <div style={{ fontSize: FONT.bodyLg, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
        {lines.join("\n")}
      </div>
      <Focusable style={{ display: "flex", flexWrap: "wrap", gap: SPACE.md, marginTop: SPACE.sm }}>
        {actions.map((a) => (
          <DialogButton key={a.label} onClick={() => a.onClick(close)}>
            {a.label}
          </DialogButton>
        ))}
        <DialogButton onClick={close}>{t("BTN_BACK")}</DialogButton>
      </Focusable>
    </Focusable>
  );

  handle = asHandle(showModal(body));
}

/** A list browser (Inbox / History / error-code reference). A = row, B = back. */
export function showListModal(
  title: string,
  rows: ListRow[],
  subtitle?: string,
): void {
  let handle: ModalHandle = null;
  const close = () => handle?.Close?.();

  const body = (
    <Focusable
      onCancel={close}
      onCancelActionDescription={t("BTN_BACK")}
      onOKActionDescription={t("BTN_SELECT")}
      style={colStyle}
    >
      <div style={{ fontWeight: 700, fontSize: FONT.heading }}>{title}</div>
      {subtitle ? (
        <div style={{ fontSize: FONT.body, opacity: 0.7, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
          {subtitle}
        </div>
      ) : null}
      {rows.length === 0 ? (
        <div style={{ fontSize: FONT.bodyLg, opacity: 0.8 }}>{t("NOTHING_HERE")}</div>
      ) : (
        // Round 81: these rows used to sit in a PanelSectionRow, which is the
        // QAM panel's own row container -- it carries the panel's width and
        // padding assumptions. A modal is narrower, so the same component laid
        // the rows out against the wrong box and they drifted off the modal's
        // left edge. A plain block is what a modal actually needs.
        rows.map((r, i) => (
          <div key={`${r.label}-${i}`}>
            <DialogButton disabled={!!r.disabled} onClick={() => r.onActivate(close)}>
              <div style={{ textAlign: "left", wordBreak: "break-word" }}>
                <div style={{ fontSize: FONT.bodyLg }}>{r.label}</div>
                {r.sub ? (
                  <div style={{ fontSize: FONT.caption, opacity: 0.65, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                    {r.sub}
                  </div>
                ) : null}
              </div>
            </DialogButton>
          </div>
        ))
      )}
      <Focusable style={{ marginTop: SPACE.sm }}>
        <DialogButton onClick={close}>{t("BTN_BACK")}</DialogButton>
      </Focusable>
    </Focusable>
  );

  handle = asHandle(showModal(body));
}

/**
 * Round 28 (criterion 3): FOMOD choice picker. Single-select groups behave like
 * radio buttons (choosing one replaces the previous); multi-select groups toggle
 * members on/off. Every control is a DialogButton so the Steam gamepad can
 * reach it; there are no raw <button> elements. `onConfirm` receives the map
 * {"<step>.<group>": string[]} that installMod forwards to the backend.
 */
export function showFomodModal(
  descriptor: FomodDescriptor,
  onConfirm: (choices: Record<string, string[]>) => void,
  onCancel?: () => void,
): void {
  let handle: ModalHandle = null;
  const close = () => handle?.Close?.();
  const steps = descriptor.steps || [];
  const initial: Record<string, string[]> = {};
  steps.forEach((st, si) => st.groups.forEach((g, gi) => {
    const key = `${si}.${gi}`;
    const defaults = g.options.filter((o) => o.selected).map((o) => o.name);
    initial[key] = g.mode === "single" ? defaults.slice(0, 1) : defaults;
  }));

  // A React child component owns the choice state so toggles re-render in place
  // (no stacked modals). Every interactive control is a DialogButton.
  function FomodBody() {
    const [chosen, setChosen] = useState<Record<string, string[]>>(initial);
    const toggle = (key: string, mode: string, name: string) => {
      setChosen((prev) => {
        const cur = prev[key] || [];
        if (mode === "single") return { ...prev, [key]: [name] };
        return {
          ...prev,
          [key]: cur.indexOf(name) >= 0 ? cur.filter((n) => n !== name) : [...cur, name],
        };
      });
    };
    return (
      <Focusable
        onCancel={() => { close(); if (onCancel) onCancel(); }}
        onCancelActionDescription={t("BTN_BACK")}
        onOKActionDescription={t("BTN_SELECT")}
        style={colStyle}
      >
        <div style={{ fontWeight: 700, fontSize: FONT.heading }}>{t("FOMOD_TITLE")}</div>
        {descriptor.warnings
          ? <div style={{ fontSize: FONT.body, opacity: 0.7, whiteSpace: "pre-wrap" }}>
              {descriptor.warnings.join("\n")}
            </div>
          : null}
        {steps.map((st, si) => (
          <div key={`s-${si}`}>
            {st.groups.map((g, gi) => {
              const key = `${si}.${gi}`;
              return (
                <div key={`g-${key}`}>
                  <div style={{ fontWeight: 700, marginTop: SPACE.md }}>
                    {st.name} / {g.name} · {g.mode === "single" ? t("FOMOD_SINGLE") : t("FOMOD_MULTI")}
                  </div>
                  {g.options.map((o) => {
                    const on = (chosen[key] || []).indexOf(o.name) >= 0;
                    return (
                      <div key={`o-${key}-${o.name}`}>
                        <DialogButton onClick={() => toggle(key, g.mode, o.name)}>
                          {on ? "[A] " : "[ ] "}{o.name}{o.description ? ` — ${o.description}` : ""}
                        </DialogButton>
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        ))}
        <Focusable style={{ display: "flex", gap: SPACE.md, marginTop: SPACE.sm }}>
          <DialogButton onClick={() => { close(); onConfirm(chosen); }}>
            {t("BTN_IMPORT")}
          </DialogButton>
          <DialogButton onClick={() => { close(); if (onCancel) onCancel(); }}>
            {t("BTN_BACK")}
          </DialogButton>
        </Focusable>
      </Focusable>
    );
  }

  handle = asHandle(showModal(<FomodBody />));
}

/**
 * Error popup (§5.2 / §5.1 op #8): readable, A or B closes, code + log path,
 * rollback action only when `rollback_available` is true. Never a traceback.
 */
export function showErrorModal(
  env: Envelope<unknown>,
  opts: {
    onDismiss: () => void;
    onRollback?: (txn: string) => void;
    txn?: string;
  },
): void {
  let handle: ModalHandle = null;
  const close = () => {
    opts.onDismiss();
    handle?.Close?.();
  };

  const body = (
    <Focusable
      onCancel={close}
      onCancelActionDescription={t("BTN_CLOSE")}
      onOKActionDescription={t("BTN_OK")}
      style={colStyle}
    >
      <ErrorView
        env={env}
        onDismiss={close}
        onRollback={opts.onRollback}
        txn={opts.txn}
      />
    </Focusable>
  );

  handle = asHandle(showModal(body));
}
