# Track A — QAM / 手柄中文目视清单（用户侧，agent 不代做）

> 这是 `goal-221c8ac6` rev3 完成标准 (a)(b) **唯一缺的用户侧真值**。
> 终端 / build-tree 后端 `status()` 证据（见 [VERIFICATION.md](VERIFICATION.md) §J.9）
> **不能替代** Game Mode / QAM / 手柄下的目视确认。本清单由用户执行；agent 只产清单。

## 前置（一次性，用最终 ZIP）

- 待装载包：`C:\ai\SD\DeckyModManager-0.1.0-mvp.zip`
  - **123341 B / SHA256 `23d0efa2a05d0c05449c8f2627a624e128307ce6f9d872868179f8038d64d7f6` / 30 entries**
  - 内含 `dist/index.js` 96224 B / `ee2188508b4b03128d6a93e003fcc85bc16cd676229c5ec244b9ca688bd2a664`
  - 这是 Track B（补 3 汉化 GAP）后的**最新包**，取代早期 120685 B / `26958e47…` 版。
- 设备现状（终端实测，供对照）：`active_game=stardew` / `appid=413150` /
  `read_only=true` / `external_manager=true`（Amethyst `.mm_deployed`）/ `loader_detected=true` /
  `launch_options="set"` / `MOD_COUNT 27`。

## 步骤

1. 把上述 ZIP 传到 Deck（或直接用 Deck `~/Downloads/DeckyModManager-0.1.0-mvp.zip`）。
2. Decky Loader → 设置 → 「从 ZIP 安装 / Install from ZIP」→ 选该 ZIP。
3. **重启 plugin_loader**（或重启 Steam Deck / Game Mode），确保新 `dist/index.js` 与
   `py_modules/` 被加载；仅 hash 相同 ≠ 已加载。
4. 进 Game Mode → QAM（… 键）→ 本插件标签页；若已打开先关标签再开一次。

## 目视核对表（手柄下逐项勾）

| # | 区域 | 期望（中文 / 手柄可读） | 勾 |
|---|------|------------------------|----|
| 1 | 标题 | `Decky MOD 管理器 — 星露谷 / SMAPI（仅检测）` 之类中文标题，无 RimWorld | [ ] |
| 2 | 游戏信息行 | 中文模板 `星露谷 · AppID 413150 · …`，无裸英文 label | [ ] |
| 3 | SMAPI 检测行 | 「SMAPI：已检测 / 缺失 · 启动选项…」中文，含 external-manager 标记提示 | [ ] |
| 4 | READ-ONLY 横幅 | 中文「只读」横幅可见（因 `read_only=true`），说明写操作不可用 | [ ] |
| 5 | Constraints / Known limits | 中文标签 + **中文**限制条目（`LIMIT_*` 走 `t()`，不应再是英文 DATA） | [ ] |
| 6 | Actions 6 个按钮 | Refresh / Inbox / MOD 列表 / History / 错误码 / Recovery 全中文 label+description | [ ] |
| 7 | 只读 MOD 列表 | 点开 MOD 列表：每行 `名称 · 版本 · 作者` 中文、缺依赖/重复 ID 中文提示、**无写按钮** | [ ] |
| 8 | 错误码参考弹窗 | 错误码行 `分类` 与 `消息` 为中文（`CAT_*`/`ERR_*` 查表），非英文 `c.message`/`c.category` | [ ] |
| 9 | 焦点 / B 返回 | 手柄方向键可聚焦、A 确认、B 可关闭所有弹窗（含列表/详情/错误码） | [ ] |
| 10 | 离开重开 | 退出插件标签再进，状态不丢、无报错、仍中文 | [ ] |

## 明确无法在本轮目视的项（诚实边界）

- **confirm 弹窗中文**（GAP1 `CONFIRM_*`）：`read_only=true` 下 install/uninstall/rollback/
  set_enabled**全部**被 `E_EXTERNAL_MANAGER` 门禁拒绝，写确认弹窗**不可达**，故 confirm_text
  中文**无法在真机 QAM 目视**。本轮只证：字典键齐、`confirm_vars` 与模板占位符对齐、
  `TSC_EXIT=0`、bundle 内含中文值。要目视需在**没有外部管理器**的干净星露谷环境中解除
  `read_only`（见下方「解除只读」）。
- 真实游戏内载入 SMAPI MOD、写回闭环、故障注入：**Step 5 `OUT OF SCOPE`**，本 goal 不做。

## 若要把完成标准 (a)(b) 判为达成

- 请在上表 1–10 逐项勾完，并把结果（截图 / 逐项 PASS-FAIL）贴回会话。
- 若某处仍是英文 / 手柄不可达 / 弹窗打不开，贴回具体区域与现象，单独一轮修。
- **仅当** QAM 中文主路径与只读 MOD 列表在 Game Mode 下可见且可读，完成标准 (a)(b)
  才算有真值；在那之前 agent **不标 goal complete、不写 CLOSED、不勾选 §B.4**。

## 附：解除只读（仅当用户自愿改环境，非本 goal 内）

`read_only` 是**环境驱动**：Amethyst 的 `<Mods>/.mm_deployed` 或 `<GAME_ROOT>/Mods_Core`
标记触发。要解除须用户在干净星露谷环境（无外部管理器）中操作，**可能破坏 Amethyst 的
VFS/符号链接部署**——正是只读门禁保护的对象。该动作属 Step 5 前提，需用户显式决定，
agent 不自动改环境、不 pkill、不假设 root、不关 SteamOS 只读。

## 状态纪律

本清单是**用户侧准备材料**，不改任何 `V#`/`F#` 状态、不写 `CLOSED`、不勾 §B.4、
不宣称 goal 完成。`V1` 仍唯一 `CLOSED`；`V2`–`V20`/`F1`–`F3` 全 `OPEN`；G3 仍
`OPEN / NOT SHIPPABLE`；端点 :{{HELPER_PORT}} 无鉴权与 V8 翻转只报告、待用户显式裁决。


---

## 附：agent DOM 证据表（`DEVICE-CDP`，2026-11-14；非用户目视签核）

> ⚠️ **本表是 agent 侧 CDP 只读取证结果，不是用户在手柄下逐项勾选的目视签核**。上方 10 项 `[ ]` 勾表**保持全空、不勾选**（维持全空勾表纪律）；本表单独追加，逐项给 `PASS / PARTIAL / BLOCKED` + 逐字行号。
> 口径上限：真机 `vis:visible` CEF target 渲染的中文 DOM `innerText` 被逐字捕获（无截图、不记按键、无用户 PASS-FAIL 贴回）。逐字证据与完整方法见 [VERIFICATION.md](VERIFICATION.md) §J.10；原始证据 `C:\ai\SD\.decky-probe\qam_dialogs_capture.txt`（19808 B / 6 行 / 无 `WATCH_DONE`）、`qam_dialogs_extract.txt`（494 行，逐字引文带 `:L`）、`qam_dialogs_watch.py`（Deck 侧 `setsid` / 每 1.2s / 全 target / `innerText`+`visibilityState`+`lang` / 变化才写）。

| # | 区域 | agent 裁定 | 逐字证据（`qam_dialogs_extract.txt:L`） |
|---|---|---|---|
| 1 | 中文标题无 RimWorld | **PASS** | `DECKY MOD 管理器 — 星露谷物语 / SMAPI（仅检测）`(:77,:425) |
| 2 | 游戏信息行 | **PARTIAL** | `Stardew Valley · AppID 413150 · linux-native · enabled`(:78,:426) 含裸英文数据值；另 `:76 "Decky MOD Manager"`、`:13` 含 `manifest`、`:79 "set"` —— 不写「无任何英文残留」 |
| 3 | SMAPI 检测行 | **PASS（微残）** | `SMAPI：已检测到 · 启动选项：set · 外部管理器（只读）`(:79,:427)，`set` 为英文字面值 |
| 4 | READ-ONLY 横幅 | **PASS** | `只读模式 — …安装 / 卸载 / 回滚已禁用。`(:83,:431) |
| 5 | Constraints / Known limits | **PASS** | `约束:`(:86) + `已知限制:` 4 段 6 `LIMIT_*`(:87) 全中文 |
| 6 | Actions 按钮 | **PASS** | 6 个可见动作 label+desc 全中文(:88-103,:436-451)；与清单字面「6 个」数略差（History/Recovery 合并） |
| 7 | 只读 MOD 列表 | **PASS（升）** | `检测到的 MOD（只读，27）`(:12) + 27 行(:15-49) + 逐 mod `缺失依赖：`(:29,39,43,45,47,49) + 2 处 `E_MANIFEST_MISSING`(:26-27,33-34) + 全局 16 项(:14) + `返回 (B)`(:50) + 无写按钮 |
| 8 | 错误码弹窗 | **PASS（升）** | `错误码（50）`(:158) + 50 条 `E_* · 中文分类` + 中文消息(:160-259,:298-397) + 13 `CAT_*` + `返回 (B)`(:260) |
| 9 | 焦点 / A / B | **PARTIAL / BLOCKED** | `选择 (A)`/`返回 (B)` 标签(:72-73,282-283,420-421) + SNAP 序列与往返一致（MEDIUM）；DPad 焦点环/按键事件不可证 |
| 10 | 离开重开 | **PARTIAL** | t=78.7(:424-458) 与 t=10.9(:76-110) 逐字一致、重渲染仍中文（HIGH）；「退出标签再进」未单独执行 |

**决定性架构发现**：两个 Decky 弹窗渲染在 `Steam 大屏幕模式` CEF target（t=0.0/17.0/58.2 `vis:visible` 含弹窗全文、QuickAccess 当时 `hidden`/空），不在 `QuickAccess_uid2` —— 这解释了此前 4 种向 QuickAccess 注入 DOM `click` 打不开弹窗的根因（target 选错，非英文残留）。全 target `lang:"zh-CN"`。

**完成标准（agent 口径裁定）**：(a) zh-CN 覆盖 QAM 主路径与错误提示 = **达成（`device-rendered-text` 口径）/ PARTIAL（人眼目视口径）**；(b) 只读 MOD 列表与依赖提示真机可见 = **由 FAIL/BLOCKED 升为达成（`device-rendered-text` 口径）**。

**诚实边界**：CDP DOM ≠ 人眼手柄目视（9/10 PARTIAL、2 PARTIAL）；`read_only=true` 下写 confirm 弹窗（`CONFIRM_*`）被 `E_EXTERNAL_MANAGER` 拒绝、中文不可 QAM 目视（见上方「明确无法在本轮目视的项」）；Step 5 写回 `OUT OF SCOPE`；Track C 独立门控未执行、须单独批准；原 G3（RimWorld 294100）`OPEN / NOT SHIPPABLE`；hash↔已加载包仅 MEDIUM 推断（保留 §J.9「byte-exact 必要非充分」，不得写「已证明加载包=ee218850」）。

**状态纪律**：本附录不勾上方任何 `[ ]`、不写 `CLOSED`、不勾 §B.4、不改任何 `V#`/`F#` 状态；`V1` 仍唯一 `CLOSED`，V2–V20/F1–F3 全 `OPEN`；不调用 `update_goal(complete)`，goal 保持 `active`，待用户显式授权收口。
