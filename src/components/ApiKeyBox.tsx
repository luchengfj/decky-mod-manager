/**
 * Round 84: the Nexus API key box.
 *
 * Before this the panel had no way to enter a key at all. `src/api.ts` had
 * declared `apiKeyStatus` / `setApiKey` / `deleteApiKey` / `nexusValidate`
 * since Round 39 and nothing called any of them, so `check_mod_updates` could
 * only ever answer `E_CAPABILITY_DISABLED` ("no usable stored key") -- and the
 * generic message for that code reads "This action is not available in this
 * version", which is not what happened. The feature was not missing; the door
 * was.
 *
 * The key never comes back out. `api_key_status` is stat-only, `set_api_key`
 * replies with a description of the file (path + mode), and `nexus_validate`
 * takes no argument because the backend re-reads the stored key itself. So
 * there is no state here that holds key material after the save.
 *
 * Every control is a DialogButton or a TextField, so the D-pad can reach all of
 * them; nothing here needs a mouse.
 */
import { Focusable, TextField, DialogButton, PanelSectionRow } from "@decky/ui";
import { useCallback, useEffect, useState } from "react";
import { t } from "../i18n";
import {
  apiKeyStatus,
  setApiKey,
  deleteApiKey,
  nexusValidate,
  envelopeError,
} from "../api";
import type { KeyStatusData } from "../types";
import { FONT, SPACE, BOX_SIZING } from "../theme";

interface Props {
  /** The panel's own busy flag: a key change must not race an install. */
  busy: boolean;
}

export function ApiKeyBox({ busy }: Props) {
  const [key, setKey] = useState("");
  const [status, setStatus] = useState<KeyStatusData | null>(null);
  const [note, setNote] = useState("");
  const [working, setWorking] = useState(false);

  const load = useCallback(async () => {
    const r = await apiKeyStatus();
    if (r.ok && r.data) setStatus(r.data as KeyStatusData);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /** One wrapper so every button clears the previous note and cannot double-run. */
  const run = async (body: () => Promise<void>) => {
    if (working) return;
    setWorking(true);
    setNote("");
    try {
      await body();
    } catch (e) {
      // A thrown bridge error is still something the user must see; the panel
      // has no toast here because this box is a row, not a dialog.
      setNote(String((e && (e as Error).message) || e));
    } finally {
      setWorking(false);
    }
  };

  const doSave = () =>
    run(async () => {
      const text = key.trim();
      if (!text) return;
      const r = await setApiKey(text);
      if (!r.ok) {
        setNote(envelopeError(r));
        return;
      }
      // Clear the field first: keeping it would leave the secret in the DOM
      // after it is already on disk.
      setKey("");
      setNote(t("KEY_SAVED", "The key is stored."));
      await load();
    });

  const doValidate = () =>
    run(async () => {
      const r = await nexusValidate();
      if (!r.ok) {
        setNote(envelopeError(r));
        await load();
        return;
      }
      const d = (r.data || {}) as { name?: string; is_premium?: boolean };
      setNote(
        d.name
          ? t("KEY_VALID_NAME", "Nexus accepted the key for {name}.", { name: d.name })
          : t("KEY_VALID_OK", "Nexus accepted the key."),
      );
      await load();
    });

  const doDelete = () =>
    run(async () => {
      const r = await deleteApiKey();
      if (!r.ok) {
        setNote(envelopeError(r));
        return;
      }
      setNote(t("KEY_DELETED", "The stored key was deleted."));
      await load();
    });

  const state = status?.state || "missing";
  const stateText =
    state === "present"
      ? t("KEY_ST_PRESENT", "A key is stored.")
      : state === "unreadable"
        ? t("KEY_ST_UNREADABLE", "A key file exists but is not readable or not private.")
        : t("KEY_ST_MISSING", "No key is stored yet.");

  const disabled = busy || working;

  return (
    <PanelSectionRow>
      <Focusable
        style={{
          display: "flex",
          flexDirection: "column",
          gap: SPACE.md,
          width: "100%", boxSizing: BOX_SIZING,
        }}
      >
        <div style={{ fontSize: FONT.body, fontWeight: 700 }}>{t("KEY_TITLE")}</div>
        <div style={{ fontSize: FONT.caption, opacity: 0.7, wordBreak: "break-word" }}>
          {t("KEY_DESC")}
        </div>
        <div style={{ fontSize: FONT.caption, opacity: 0.85, wordBreak: "break-word" }}>
          {stateText}
        </div>
        {/* A filesystem without POSIX bits cannot keep the 0600 promise, so the
            panel says so instead of implying a protection it does not have. */}
        {status && status.posix === false ? (
          <div style={{ fontSize: FONT.caption, opacity: 0.7, wordBreak: "break-word" }}>
            {t("KEY_NO_POSIX", "This filesystem has no POSIX mode bits, so 0600 cannot be enforced.")}
          </div>
        ) : null}
        <TextField
          label={t("KEY_LABEL")}
          value={key}
          disabled={disabled}
          onChange={(e) => setKey(e?.target?.value ?? "")}
        />
        <Focusable style={{ display: "flex", flexWrap: "wrap", gap: SPACE.md }}>
          <DialogButton disabled={disabled || !key.trim()} onClick={() => void doSave()}>
            {t("BTN_KEY_SAVE")}
          </DialogButton>
          <DialogButton disabled={disabled || state !== "present"} onClick={() => void doValidate()}>
            {t("BTN_KEY_VALIDATE")}
          </DialogButton>
          <DialogButton disabled={disabled || state === "missing"} onClick={() => void doDelete()}>
            {t("BTN_KEY_DELETE")}
          </DialogButton>
        </Focusable>
        {note ? (
          <div style={{ fontSize: FONT.caption, opacity: 0.85, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
            {note}
          </div>
        ) : null}
      </Focusable>
    </PanelSectionRow>
  );
}
