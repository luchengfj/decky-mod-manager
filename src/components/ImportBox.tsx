/**
 * OPTIONAL OSK path box (§5.1 op #10, review #3: "inbox first + optional OSK
 * path box").
 *
 * The primary flow is the fixed inbox (listInbox). This box is entirely
 * skippable: it only exists so a user who already knows an absolute path can
 * type it with the Steam on-screen keyboard instead of copying a ZIP into the
 * inbox. It NEVER does network / Workshop / file-dialog import. The backend
 * still enforces E_PATH_ESCAPE / E_NOT_ALLOWED_ROOT containment, so a typed
 * path cannot broaden the allowed write roots.
 *
 * ⚠️ V3: `TextField`'s OSK trigger and exact props (`bShowOSK` / focus
 * behavior / `onChange` signature) must be confirmed against the LOCKED
 * @decky/ui version. We use the most conservative surface (value + onChange).
 * Step 1: all labels go through t().
 */
import { Focusable, TextField, DialogButton, PanelSectionRow } from "@decky/ui";
import { useState } from "react";
import { t } from "../i18n";

interface Props {
  busy: boolean;
  onSubmit: (path: string) => void;
}

export function ImportBox({ busy, onSubmit }: Props) {
  const [path, setPath] = useState("");

  return (
    <PanelSectionRow>
      <Focusable style={{ display: "flex", flexDirection: "column", gap: "8px", width: "100%" }}>
        <div style={{ fontSize: "12px", opacity: 0.7 }}>
          {t("OSK_HINT")}
        </div>
        <TextField
          label={t("OSK_LABEL")}
          value={path}
          disabled={busy}
          onChange={(e) => setPath(e?.target?.value ?? "")}
        />
        <Focusable style={{ display: "flex", gap: "8px" }}>
          <DialogButton
            disabled={busy || !path.trim()}
            onClick={() => {
              const p = path.trim();
              if (p) onSubmit(p);
            }}
          >
            {t("BTN_INSPECT")}
          </DialogButton>
          <DialogButton disabled={busy} onClick={() => setPath("")}>
            {t("BTN_CLEAR")}
          </DialogButton>
        </Focusable>
      </Focusable>
    </PanelSectionRow>
  );
}
