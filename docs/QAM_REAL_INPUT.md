# QAM real-input evidence (criterion 2)

This document records how the three QAM `ButtonItem` controls were activated
with **trusted browser input**, not a DOM `el.click()`, and the screenshots
kept as proof. It is additive; it changes no product code and no status boxes.

## Why this needed a new method

Earlier attempts to open Decky dialogs with `element.click()`, synthetic
`MouseEvent`/`PointerEvent`, or React-fiber `onClick` invocation all failed —
Decky's `ButtonItem` is a Steam gamepad component whose modal opens only when
the browser itself delivers a trusted input event. A DOM dispatch has
`isTrusted=false` and is correctly ignored.

The criterion explicitly permits "CEF/CDP 自动化" and rejects only "纯 DOM
派发 click". The method below uses `Input.dispatchMouseEvent`, which the
browser delivers as a genuine `isTrusted=true` event.

## Method (`C:\ai\SD\.decky-probe\qam_click2.ps1`)

1. Scan `http://{{DECK_IP}}:8081/json` for the live CEF targets. The QAM
   panel mounts in one target (`quickaccess_content_999`); Decky dialogs render
   in the *gamepad* target (`index.html?...IN_GAMESCOPE=true`).
2. In the panel target, locate the element whose trimmed `innerText` equals the
   button label, walk up the React fiber to the DOM node that actually owns
   `onMouseDown`/`onClick`, `scrollIntoView`, read its viewport rect.
3. Dispatch a trusted mouse sequence at that rect through CDP:
   `mouseMoved → mouseMoved → mousePressed → mouseReleased` (button=left,
   clickCount=1). A capture listener confirmed `event.isTrusted === true`.
4. Snapshot every CEF target's `body.innerText` before and after; the target
   whose text changed is the one that opened the dialog. Screenshot that target
   with `Page.captureScreenshot`.

## Results — three distinct ButtonItems

| # | Button label | Locator handler | Trusted event | Dialog that opened (verbatim) | Screenshot |
|---|---|---|---|---|---|
| 1 | `导入目录 — 本地 ZIP（11）(A)` | `onMouseDown` | `isTrusted=true`, text `仅固定导入目录…` | `导入目录 — 本地 ZIP（11） / 导入目录：/home/deck/homebrew/data/decky-mod-manager/data/inbox / A = 预览/导入 · B = 返回。不联网，不用创意工坊。 / BetterRanching.2.0.5.zip …` | `qam_import_910892_1.png` (154088 B) |
| 2 | `禁用 (A)` (the enable/disable toggle) | `onClick,onMouseDown,onMouseUp` | `isTrusted=true`, text `禁用 (A)` | `确认更改 / 在 ModsConfig.xml 中禁用 focustense.stardewui？ / w2_disabled: …/Stardew Valley/.decky-disabled / 确认 (A) / 取消 (B)` | `qam_disable_910892_1.png` (94005 B) |
| 3 | `卸载 (A)` | `onClick,onMouseDown,onMouseUp` | `isTrusted=true`, text `卸载 (A)` | `确认更改 / 卸载 focustense.StardewUI？文件夹将移入隔离区（不会删除）。 / w2_quarantine: …/.decky-quarantine/20261116T124930-0923e7cf/focustense.stardewui / 确认 (A) / 取消 (B)` | `qam_uninstall_910892_1.png` (106013 B) |

Notes on coverage:

- **启用** is the *same* `ButtonItem` as 禁用, in its opposite state: the toggle
  flips label once a mod is parked in `.decky-disabled/`. Button #2 exercised
  that exact control; a reversible disable→enable cycle was attempted but the
  QAM panel was dismissed by an intervening Escape before the second phase, so
  the screenshot evidence above is for the disable phase of the toggle only.
- All three confirm dialogs were **cancelled** (Escape / no confirm). Device
  re-check after the clicks: `MOD_DIRS=30`, `focustense.stardewui` present,
  `ivory.sdvhd2d` present, `.decky-disabled` count unchanged ⇒ no destructive
  change to the user's mods.

## "No bare `<button>`" assertion

`C:\ai\SD\.decky-probe\r19_frontend_preflight.py` gained an eighth static group:
after stripping comments it fails if any `src/**/*.tsx` contains a bare
`<button` tag, and prints positive counts of `ButtonItem`/`DialogButton`.
Latest run:

```
BARE_BUTTON_COUNT 0
BUTTONITEM_COUNT 14
DIALOGBUTTON_COUNT 13
FRONTEND_PREFLIGHT_OK
RC=0
```

## Honest boundaries

- CDP trusted input is not a physical controller; it is the permitted
  CEF-automation branch of the criterion, with `isTrusted=true` as the
  distinguishing evidence. No human gamepad session was simulated end-to-end.
- Screenshots were captured by `Page.captureScreenshot` of the gamepad target
  and saved locally; they are the visual record of each modal.
- This document does not claim any mod was actually installed/enabled/uninstalled
  through the panel — the confirms were intentionally cancelled.
