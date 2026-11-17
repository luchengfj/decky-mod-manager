# QAM Panel Visual Check — Round 25 (enable/disable era)

Additive section. The checklist in the earlier part of this file is untouched:
its `[ ]` boxes stay unticked. This section records what the panel actually
rendered in round 25 and separates "text the DOM reported" from "a human looked
at it", because those are different strengths of evidence.

## Method

Read the mounted panel's `innerText` from the Decky UI over CEF
(`document.getElementById("quickaccess_content_999")`) with the panel genuinely
open by the user (`document.visibilityState === "visible"`). Raw capture saved
at `C:\ai\SD\.decky-probe\qam_r25_text.txt` (1862 characters, 54 non-empty
lines).

This is **device-rendered text**, not a screenshot and not a human's judgement.

## What rendered

| # | item | rendered text | verdict |
|---|---|---|---|
| 1 | Chinese title, no RimWorld leftovers | `DECKY MOD 管理器 — 星露谷物语 / SMAPI（仅检测）` | PASS |
| 2 | game identity line | `Stardew Valley · AppID 413150 · linux-native · enabled` (bare English values) | PARTIAL |
| 3 | SMAPI detection line | `SMAPI：已检测到 · 启动选项：set` — the `外部管理器（只读）` segment is gone after the migration | PASS |
| 4 | paths block | `W2（MOD 目录）…` / `隔离区…` / `文件系统 POSIX：是 · Flatpak Steam：否` | PASS |
| 5 | read-only banner | absent — correct, because the external manager is gone and `read_only` is `false` | PASS |
| 6 | constraints line | `约束: 仅本地 ZIP + 可选 GitHub/HTTPS 下载，只落收件箱 · 不用创意工坊 · 不运行 .exe · 不装加载器 · 不改启动选项或 Proton 前缀 · 不需要 root · 保持只读文件系统开启。` | PASS |
| 7 | known limitations, all six keys in Chinese | `仅检测…` / `共存…` / `file_drop 不做加载顺序…` / `没有全游戏一键安装…` / `GitHub 覆盖面…` / `直连 URL…` — no bare `LIMIT_*` key names | PASS |
| 8 | actions block | `刷新 (A)` / `导入目录 — 本地 ZIP（4）(A)` / `检测到的 MOD (A)` / `游戏目录 (A)` / `重新扫描游戏库 (A)` / `所有游戏库` / `历史记录 → 回滚 (A)` / `错误码 (A)` — each with a Chinese description | PASS |
| 9 | download section | `下载 MOD（GITHUB + 直连 URL）` + `搜索关键词` / `搜索 GitHub (A)` / `直连 HTTPS URL` / `从 URL 下载 (A)` / `导入该 URL (A)` + full Chinese explanation | PASS |
| 10 | installed-by-plugin section | `本插件安装的 MOD（0）` + `本插件还没有安装过 MOD。磁盘上已有的 MOD 请在「检测到的 MOD」里查看。` | PASS |

## What actually caught bugs

Two defects were only findable with the panel rendering:

* Round 19 — `LIMIT_GH_COVERAGE` and `LIMIT_DIRECT_URL` appeared as **bare key
  names** because the validator only scanned literal `t("KEY")` calls in `src/`
  and could never see descriptor-driven keys. Fixed by adding the two strings
  plus a new `DATA_KEYS` sweep that reads `known_limitation_keys` and
  `confirm_keys` out of `registry/games/*.json`.
* Round 20 — `已安装的星露谷 MOD（0）` claimed zero mods while 27 were on disk.
  The number was correct (`journal.installed()` only counts what this plugin
  installed) but the wording was wrong. Renamed to `本插件安装的 MOD（n）` with
  a sentence pointing at "检测到的 MOD".

## Not proven, and why

* **No human looked at this.** The evidence above is text extracted from the
  DOM. Nothing here proves pixel layout, focus rings, or that a person can read
  the panel comfortably on a 1280×800 handheld screen.
* **D-pad focus and A/B behaviour are untested.** The panel's buttons are
  `ButtonItem`s driven by Steam's gamepad input layer. Round 25 retried four
  independent DOM injection strategies (`.click()`, full `PointerEvent` +
  `MouseEvent` sequence, React fiber `onClick` lookup, precise leaf `.click()`)
  against `检测到的 MOD` and none of them opened the dialog — the panel text
  stayed byte-identical at 1862 characters. That is a property of Steam's input
  routing, not evidence that the button is broken.
* **Dialog contents are unverified on device.** The mod list, the mod detail
  dialog with its Enable/Disable/Uninstall actions, the history dialog, the
  error-code dialog and the game-library dialog have never been seen rendered.
  Their code paths are covered by 301 local tests and by RPC probes against the
  running process, but tests are not pixels.

## State of the panel at the time of capture

```
quickaccess_content_999 -> {"vis":"visible", "len":1862}
```

Saved copy: `C:\ai\SD\.decky-probe\qam_r25_text.txt`.

Status discipline: this section adds no CLOSED item, ticks no `[ ]` box in the
original checklist, and flips no V#/F# status.
