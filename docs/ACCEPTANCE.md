# ACCEPTANCE.md — Definition of Done (DoD) for the MVP

> **PIVOT — selection B (2026-11-14, m03746「全部批准」).** 本文档现含**两个**验收对象：
> **PART I**（新建、当前活动）= 星露谷 / SMAPI detect-only；**PART II**（历史、逐字保留）
> = 原 RimWorld MVP（selection A）。原 G3（RimWorld 294100）**仍 `OPEN`、未被替换、
> 未写 `CLOSED`、仍 NOT SHIPPABLE**；PART I 是另建的独立验收对象，**不构成对原 G3 的签核**。
> 依据 [VERIFICATION.md](VERIFICATION.md) §A–§H（原样保留）与新 §I。
>
> **状态纪律**：本轮未翻转任何 `V#`/`F#` 状态字、未写任何 `CLOSED`、未回填历史快照表；
> `V1` 仍是唯一 `CLOSED`，`V2`–`V20` / `F1`–`F3` 全 `OPEN`，G3 整体仍 `OPEN`。
> 新 §I 与 PART I 内所有条目一律 `DEVICE` / `OPEN` / 待执行。
>
> **诚实边界**：PART I 的 11 项手柄操作、真实 SMAPI 载入、`.mm_deployed` 共存只读、
> 真实 `manifest.json` 写回**仍无真机真值**；本机 46/46 用例（33 RimWorld 回归 +
> 13 Stardew 合成树）只是后端逻辑回归，不是 device-side DoD 签核。前端 F 组
> （Deck 上 `tsc --noEmit` + `rollup -c` → 新 `dist/index.js` → 重打 ZIP → 真机加载）**待执行**。

---

## PART I — 星露谷 / SMAPI detect-only MVP 验收对象（selection B，当前活动）

> 来源：m03703「B」+ m03746「全部批准」（19 项 #1–#19 按 A→E 执行）。
> 对象：Stardew Valley **AppID 413150**，SMAPI 作为**用户已装**的 external launcher，
> 插件**只检测不安装**；`state_mutator.strategy = file_drop`（无 state file / 无
> `ModsConfig.xml` / 无 `<activeMods>` / 无 Core）；`install ≡ enable`（目录在 `Mods/`
> 下且含 `manifest.json`）；`enable_disable = false`。
> **第一版不做什么**：不装 SMAPI、不改 Steam 启动选项、不写 Proton pfx / 不做 DLL
> override、不联网 / 不接 Workshop / 不跑 `.exe` 安装器、不做依赖/排序求解、不自动改
> 第三方 mod manager 的部署、不提供独立可逆 enable/disable 开关、不宣称全游戏通用一键装。

### §B.1 — 11 operations that must work with D-pad + A/B only

Forbidden everywhere (unchanged from selection A): hover, drag-drop, long-press,
right-click, scroll wheel, touch, trackpad, gyro, Steam/X/Menu keys. Only the
optional OSK path box may use the on-screen keyboard.

**Important deviation (must be reviewed):** selection A 的 op #5「Enable/disable 单行
可逆切换」在 file_drop 下**不存在**（`enable_disable=false`；UI 隐藏 Toggle 按钮，
`ModRow` 显示 `Installed` 而非 `Enabled/Disabled`）。其效果由 op #6 卸载（移入隔离区
= 禁用）/ op #7 回滚或重新导入（= 重新启用）达成。第一版**不提供**独立可逆开关。

| # | Operation (selection B) | Gamepad requirement | Where implemented | Status |
| --- | --- | --- | --- | --- |
| 1 | Open QAM → plugin tab; first focusable element auto-focused | `…` → D-pad → A | `src/index.tsx` (`<Focusable autoFocus>`) | **DEVICE** |
| 2 | Browse Inbox (list local ZIPs) | Up/Down; A preview; B back | `openInbox()` + `Modal.showListModal` | **DEVICE** |
| 3 | Import + confirm = **install ≡ enable**; shows W2 absolute path + SMAPI detection line; **no W1** | A "Import" → ConfirmModal → A confirm / B cancel | `inspectAndImport()` → `runTwoPhase()` → `showConfirm` | **DEVICE** (confirm payload LOCAL-OK) |
| 4 | View installed SMAPI mods list (status `Installed`, Toggle hidden) | Up/Down; A details; B back | `ModRow` (`canToggle=false`) + `showModDetail()` | **DEVICE** |
| 5 | View mod details (UniqueID / Name / Version / Minimum SMAPI API / Author; file_drop note) | A details; B back | `showModDetail()` (fd branch) | **DEVICE** |
| 6 | Uninstall + confirm (= disable; moves dir to quarantine, does not delete) | A → ConfirmModal (exact UniqueID) → A / B | `doUninstall()` → two-phase | **DEVICE** (backend LOCAL-OK) |
| 7 | Rollback + confirm (= re-enable; `os.replace` dir back from quarantine) | D-pad to History → A pick txn → ConfirmModal → A / B | `openHistory()` → `confirmRollback()` | **DEVICE** (backend LOCAL-OK) |
| 8 | Read / dismiss error | D-pad scroll long text; A or B closes; code + short hint + log path; **no traceback** | `ErrorView` / `showErrorModal` | **DEVICE** |
| 9 | Refresh | focusable "Refresh" → A; busy state; auto-rescan on tab focus (re-detect loader / launch options / external manager) | `doRefresh()` → `StardewEngine.status()` | **DEVICE** |
| 10 | (optional) OSK path input | A focus → Steam OSK → B/Enter submit; fully skippable | `ImportBox` (`TextField`) | **DEVICE** (⚠️ V3 props) |
| 11 | **State survives leaving + reopening the QAM tab** | proven via journal + `Mods/` dir on disk, NOT React state | `journal.py` + `StardewEngine.status()` reload | **LOCAL-OK** (synthetic tree rereads; device re-open **DEVICE**) |

**Read-only posture gate (applies to ops #3/#6/#7):** 当检测到
`Mods/.mm_deployed` 或 `GAME_ROOT/Mods_Core`（Amethyst VFS/符号链接部署）时
`status().state.read_only = true`，UI 显 **READ-ONLY** 横幅；上述三个写操作一律返回
`E_EXTERNAL_MANAGER`（零写入、零破坏、可逆）。缺失 SMAPI → `E_LOADER_MISSING`；启动
选项未指向 SMAPI → `E_LAUNCH_OPTIONS_MISSING`（`unknown` 非致命）。**这些失败步骤的
错误提示必须可在手柄下读到**（见 §B.2）。

Focus / dialog requirements: 与 selection A 相同（deterministic focus order、A 激活、
B 总能返回/关闭、破坏性确认默认聚焦 Cancel、无焦点陷阱、长文 D-pad 滚动、可见焦点环、
操作后回到已知锚点并保留可读的 "Last result"）。→ `Modal.tsx` / `ConfirmModal.tsx`
（`targets` 中 null 的 W1 行被过滤）/ `ModRow.tsx` / `src/index.tsx`。**Status: DEVICE**。

### §B.2 — Error-prompt coverage (50 codes, from `deckymod/errors.py`)

Unified envelope `{ok, code, message, detail, data, rollback_available, log_path, ts}`
(unchanged). 当前 `ERRORS` = **50 码**：原 46 码 + 4 个星露谷新增码。5 个原码文案
已中性化（`E_GAME_NOT_FOUND` / `E_GAME_AMBIGUOUS` / `E_CAPABILITY_DISABLED` /
`E_GAME_RUNNING` / `E_FLATPAK_PERMISSION` 去掉硬编码 "RimWorld / AppID 294100 /
RimWorld MVP only"）。**4 个 `rollback=True` 默认码不变**：
`E_VERIFY_FAILED` / `E_OP_FAILED` / `E_RECOVERY_PENDING` / `E_ROLLBACK_FAILED`。
`error_codes()` RPC 返回 `count == len(ERRORS) == 50`（本机 46 用例已断言）。

**4 个新增码（selection B）**

| Code | Message (short) | Cat | RB | St |
| --- | --- | --- | --- | --- |
| `E_LOADER_MISSING` | SMAPI was not detected. This plugin does NOT install SMAPI; install it yourself or fix the launch options. | environment | – | LOCAL-OK (synthetic) / DEVICE |
| `E_LAUNCH_OPTIONS_MISSING` | The Steam launch options do not point at SMAPI. This plugin does NOT edit launch options. | environment | – | LOCAL-OK (synthetic) / DEVICE |
| `E_EXTERNAL_MANAGER` | Another mod manager owns this Mods folder (symlink deployment detected). Read-only mode: install/enable/uninstall/rollback are refused to avoid damaging it. | safety | – | LOCAL-OK (synthetic) / DEVICE |
| `E_MANIFEST_UNSAFE` | The SMAPI manifest.json is missing required fields or has an invalid UniqueID. | import | – | LOCAL-OK (synthetic) / DEVICE |

**失败步骤 → 必须覆盖的错误提示**（每条都须：显示 code + 短消息 + log path、
A/B 可关闭、无 traceback、constraint 类消息不含 `steamos-readonly disable` / `sudo` /
`flatpak override`）：

| 失败步骤 | 必须出现的码 | 备注 |
| --- | --- | --- |
| 后端 / 桥不可达 | `E_BACKEND_UNREACHABLE`, `E_BRIDGE`, `E_UNKNOWN` | 同 selection A |
| 游戏 / 库定位 | `E_GAME_NOT_FOUND`, `E_GAME_AMBIGUOUS`, `E_FLATPAK_PERMISSION` | 文案已中性化 |
| **detect-only 前置（新增）** | `E_EXTERNAL_MANAGER`, `E_LOADER_MISSING`, `E_LAUNCH_OPTIONS_MISSING` | 只读零破坏 / 不装 loader / 不改启动选项 |
| 游戏运行中 | `E_GAME_RUNNING` | 真机 V20/S12 待验 |
| 本地导入 / 包校验 | `E_INBOX_MISSING`, `E_INBOX_EMPTY`, `E_INBOX_UNREADABLE`, `E_PATH_INVALID`, `E_PATH_ESCAPE`, `E_NOT_ALLOWED_ROOT`, `E_BAD_ARCHIVE`, `E_ZIP_SLIP`, `E_ZIP_BOMB`, `E_DUPLICATE_ENTRY`, `E_UNSAFE_ENTRY`, `E_MANIFEST_MISSING`, `E_MANIFEST_INVALID`, `E_MANIFEST_UNSAFE`, `E_ID_INVALID`, `E_FIELD_MISSING` | `.dll/.so/.dylib` **放行**；8 类 `.exe/.msi/.bat/.cmd/.ps1/.scr/.com/.jar` + 全部结构防护**保留** |
| 冲突 | `E_DUPLICATE`, `E_FILE_COLLISION` | UniqueID / 目录名 |
| 文件系统 / 权限 | `E_ACCESS`, `E_READONLY_FS`, `E_NO_SPACE`, `E_CROSS_DEVICE`, `E_FS_NO_POSIX`, `E_ROOT_OWNED`, `E_STAGING_IN_MODS`, `E_INODE_MISMATCH` | 真 errno 待 DEVICE |
| 事务 / 恢复 | `E_VERIFY_FAILED`, `E_OP_FAILED`, `E_RECOVERY_PENDING`, `E_ROLLBACK_FAILED`, `E_QUARANTINE_FULL` | 4 个 RB=True |

**不适用范围（诚实声明）**：state-file 类码 `E_CORE_MISSING` / `E_STATE_CORRUPT` /
`E_STATE_EXTERNAL` / `E_STATE_MISSING` / `E_STATE_OWNED` / `E_STATE_SYMLINK` 是
**RimWorld 专属**（无 state file），在本验收对象里**不可达**；它们仍留在 50 码表中供
PART II 原对象与 33 个历史回归用例使用。

### §B.3 — detect-only hard constraints (self-certified, LOCAL-OK code + data)

| Constraint | Evidence | Status |
| --- | --- | --- |
| 不默认关闭 SteamOS 只读 | `requires_readonly_toggle:false`；`EROFS`→`E_READONLY_FS`「no files were changed」；无 `sudo` | **LOCAL-OK** |
| 不假设 root | `resolve_user()` 回退到 `geteuid()`；`chown` 仅当 `euid==0`；`requires_root:false` | **LOCAL-OK** |
| 不宣称全游戏通用一键装 | `active_game:"stardew"`；`max_enabled_games_in_mvp:1`；rimworld/factorio/valheim = `planned` + capability gate | **LOCAL-OK** |
| **不装 SMAPI / 不改启动选项 / 不写 Proton pfx** | `registry/loaders/smapi.json` `status:"detect_only"` + `install_policy:"NEVER_INSTALL"` + `launch_options_policy:"MUST_ALREADY_BE_SET_BY_USER"`；`proton_prefix=None`；无 DLL override | **LOCAL-OK** |
| **第三方 manager 共存零破坏** | `.mm_deployed` / `Mods_Core` → `E_EXTERNAL_MANAGER` 只读；不搬移符号链接、不改其部署 | **LOCAL-OK** |
| 仅本地导入 | 无网络 / Workshop / `.exe` 安装器；staging/quarantine 为 `Mods/` 兄弟目录 | **LOCAL-OK** |

### §B.4 — Sign-off checklist (real device; all OPEN)

> **rev 口径**：本节及下方 additive 段中的 `goal-221c8ac6` 指 **rev3**（用户追加
> 「团队分工合作」后的当前权威修订）；实施期曾为 rev2。`factorio.json` 内
> `note` 字符串里的 `rev2` 是**当时写入的描述符字面值**，因该文件被打进最终 ZIP、
> 为保持交付物 byte-exact 未回改；两处 docs 已统一为 rev3，不构成状态字变更。

- [ ] **F 组**：Deck 上 `pnpm install --frozen-lockfile` + `tsc --noEmit`（strict 零错误）+ `rollup -c`（官方 `@decky/rollup`）→ 新 `dist/index.js` — **待执行**
- [ ] 重打 ZIP + 真机加载：`main.py::_make_engine()` 分派到 `StardewEngine`，`status()` 返回 `game.appid=413150`、`paths.w1_state_file=null`、`state.strategy="file_drop"` — **待执行**
- [ ] §B.1 全部 11 项手柄操作逐项验收（QAM、焦点、B 可关闭、busy 态）
- [ ] 真机检测行准确（SMAPI 在位 / 启动选项已设 / external-manager 标记）
- [ ] 只读模式实测：置 `.mm_deployed` / `Mods_Core` 后 op #3/#6/#7 全返 `E_EXTERNAL_MANAGER`、无文件改动
- [ ] 真实 SMAPI 模组 ZIP（单根 `strip_single_root` + `manifest.json` UniqueID + `.dll`）导入后游戏内确实载入
- [ ] §B.2 错误提示抽检：`E_EXTERNAL_MANAGER` / `E_LOADER_MISSING` / `E_LAUNCH_OPTIONS_MISSING` / `E_UNSAFE_ENTRY` / `E_ZIP_SLIP` / `E_DUPLICATE` / `E_FILE_COLLISION` / `E_GAME_RUNNING` / `E_READONLY_FS` / `E_ROLLBACK_FAILED`
- [ ] 原 G3（RimWorld 294100）**仍 `OPEN`**，未被本对象签核/闭合

Until every box is ticked, the build is **"implemented + backend self-tested (46/46
synthetic-tree tests); device acceptance OPEN; original G3 OPEN"**.

**Additive device evidence (2026-11-14; 不勾选上方任何 checkbox、状态字不动)
— 历史快照（selection B 首版 / §I.7，已被下方 Steps 1–4 段的更新交付物取代）.**
> 说明：本段记录的 `dist/index.js` 44934 B / `80cde69d…` 与 ZIP 96874 B /
> `a22abe3e…` / 29 entries 是**当时的历史快照**，保留不改；当前权威交付物见下方
> 「Additive evidence — Steps 1–4」段与 [VERIFICATION.md](VERIFICATION.md) §J.6。
以下均为 Deck（SteamOS 3.9.5 holo，deck-helper 终端 API `http://{{DECK_IP}}:{{HELPER_PORT}}`）
上**终端/后端层**真值：直接 `python3` 调用 `StardewEngine`，**无 Decky runtime、无 QAM、
无手柄、无真实 SMAPI 游戏内载入、无已部署插件加载**。详见
[VERIFICATION.md](VERIFICATION.md) §I.7。**不构成 §B.1 手柄 DoD 签核**；
`V1` 仍唯一 `CLOSED`，G3 仍 `OPEN`，所有 checklist 仍 `OPEN`。

- **F 组 Deck 严格构建已完成**：`tsc --noEmit`（strict 零错误）`TSC_EXIT=0`、
  `rollup -c` `ROLLUP_EXIT=0` → 新 `dist/index.js` **44934 B / `80cde69d…`**（旧
  RimWorld `878eb3ce…`）；`pnpm install --frozen-lockfile` `FROZEN_EXIT=0`（lockfile
  sha 未变）；重打 **ZIP 96874 B / `a22abe3e…` / 29 entries**。已下载回本机
  `C:\ai\SD\dist\index.js` 与 `C:\ai\SD\DeckyModManager-0.1.0-mvp.zip` byte-exact。
  **部署目录 root:root 755 未动**（不假设 root / 不热替换），新 ZIP 在 Deck
  `Downloads/` 供用户经 Decky UI 装载。
- **Deck 真 Linux Python 3.14.6 后端**：`Ran 46 tests OK`、`compileall RC=0`、
  `len(ERRORS)=50`、`active=stardew` / `enabled=['stardew']` / `appid=413150`。
- **真机只读 `status()`**：`game.appid=413150`、`w1_state_file:null`、
  `strategy:"file_drop"`、25 个真实 SMAPI mod 目录、`loader_detected:true`、
  `launch_options:"set"`、**`external_manager:true → read_only:true`**（Amethyst
  `.mm_deployed` 正确触发零破坏门禁）。
- **真机零破坏门禁证明**：`install` / `uninstall` / `rollback` 三个写 RPC 全返
  `code:"E_EXTERNAL_MANAGER"`；`Mods/` 树签名前后一致（`cb495ff9…`）、staging/
  quarantine 未创建、`ZERO_DAMAGE True`（`h_637e6c30_result.txt`）。

仍未覆盖（仍 `OPEN / DEVICE`）：11 项手柄/QAM/焦点、真实 SMAPI ZIP 导入后游戏内
载入、已部署插件经 Decky Loader 加载、真实 errno 故障注入、手柄可读错误抽检 ——
由用户与真机 UI 完成，本轮不勾选、不代替。

**Additive evidence — Steps 1–4 (`goal-221c8ac6` **rev3**（实施期 rev2、当前权威 rev3，
用户追加「团队分工合作」）；2026-11-14；
不勾选上方任何 checkbox、状态字不动、不新增 `CLOSED`).**
详见 [VERIFICATION.md](VERIFICATION.md) §J。范围 = 汉化 / 只读 mod 列表 /
`ManifestParser` 抽象 / 第二游戏可插拔；**Step 5 写回闭环明确 `OUT OF SCOPE`**。
证据均为 `LOCAL`/`SYNTH`/`BUILD`/`DEVICE`（终端/后端层），**无 QAM / 无手柄 /
无已部署插件加载**，不构成 §B.1 手柄 DoD 签核。`V1` 仍唯一 `CLOSED`，G3 仍
`OPEN / NOT SHIPPABLE`。

- **Step 1 汉化**：`src/i18n/{en,zh-CN}.json` 各 208 键（初版 206 → 团队复核补 2 键；
  含 50 `ERR_E_<CODE>` 错误码键 + `ERR_TITLE`/`ERR_BACKEND_UNREACHABLE` 两展示键，
  共 52 个 `ERR_` 前缀键）+ `i18n.ts`
  的 `t()`；前端 8 文件 + `api.ts` 全量接 `t()` 零硬编码 UI 文案；`@rollup/plugin-json`
  已是传递依赖 → 分支 A，不改 `package.json`/`rollup.config.js`/`pnpm-lock.yaml`。
  `BUILD`：strict `TSC_EXIT=0` / `ROLLUP_EXIT=0`；bundle 抽查含「仅本地导入」/「星露谷」/
  `MODLIST`/`ERR_` 文案。**QAM 中文目视 + 手柄可读性仍 `OPEN / DEVICE`**（需用户经
  Decky UI 装载新 ZIP 后确认）。
- **Step 2 只读 mod 列表**：`status().state.mods` 加性扩展为逐目录解析的
  Name/Version/Author/依赖/缺依赖/重复 UniqueID/parse_error；`openModList()` 只读视图
  无写按钮；单目录坏 manifest 隔离不 abort、零写入、零破坏。**`DEVICE` 真机**：27 目录中
  25 解析成功、`read_only:true` / `external_manager:true` / `launch_options:"set"`、
  `ZERO_DAMAGE True`（`MODS_SIG` 前后一致）、`DUPLICATE_IDS []`。真实社区 manifest 的
  JSONC 方言（`/* */` 注释 / 尾随逗号 / `UniqueId` 大小写）经通用 `json_dialect`+
  `field_aliases`（零字段名硬编码）修复后 `PARSE_ERROR_COUNT 10 → 2`（剩 2 个是真正无
  manifest 的安装脚本目录），GMCM 误报依赖消除；**剩余 16 项 `MISSING_DEPENDENCIES`
  是真实缺失/内容包宿主引用，只提示不求解不安装**。
- **Step 3 `ManifestParser` 协议**：新建 `deckymod/manifest.py`；`StardewEngine`→
  `FileDropEngine`（保留别名）；`main.py` 按描述符 `engine` 键工厂分派；引擎/解析层
  运行时硬编码游戏字段名 `0` 命中。11 位置参数 RPC / 50 错误码 / 4 rollback=True /
  RimWorld 33 用例行为不变。
- **Step 4 第二游戏可插拔**：`factorio.json`（`info.json` 字段名与 SMAPI 全不同）用同一
  `JsonMapParser`，`force_read_only:true`；`tests/test_parser_pluggability.py` 8 例
  合成树证明「加游戏只改描述符 JSON、引擎无 `if game==` 分支、4 写 RPC 全
  `E_CAPABILITY_DISABLED` 且零破坏」，**不是真游戏写回签核、不闭 G3**。
- **`BUILD` 实施轮交付物（历史快照，已被下方 Track B 段取代）**：`dist/index.js`
  **90110 B / `14e5064d…`**；Deck 全套 `Ran 59 tests OK`；重打
  **ZIP 120685 B / `26958e47…` / 30 entries**
  （实施轮版 = 团队复核发现 i18n 漏译后修复重构建；版本链 119412 `20e57d2e…` → 120630
  `721cf6d2…` → 120624 `c0bd5091…` → 120685 `26958e47…`，详见
  [VERIFICATION.md](VERIFICATION.md) §J.6），下载回本机 byte-exact，含
  `manifest.py`/`stardew.json(jsonc)`/`factorio.json`。部署目录 root:root 755
  **未动**，新 ZIP 在 Deck `Downloads/` 供用户经 Decky UI 装载。
- **Step 5 `OUT OF SCOPE`**：install/uninstall/rollback 写回、真实 errno 故障注入、
  真实 SMAPI ZIP 游戏内载入、4 项写手柄 DoD —— 当前真机 `read_only:true`（Amethyst
  外部管理器门禁正确生效），本 goal 不执行、不勾选、不写 `CLOSED`。
- **Track B 补 3 汉化 GAP（2026-11-14 Round 2；纯证据回写，不勾选任何 checkbox、
  状态字不动、不新增 `CLOSED`）**：`confirm_text`（后端 5 站点加 `confirm_key`+
  `confirm_vars`，`confirm_text` 英文原样保留，前端 `ConfirmModal` 走 `t()`）、
  `known_limitations`（描述符新增 `known_limitation_keys`，两引擎 `status()` 加性透传）、
  错误码弹窗 DATA（`categoryText()`/`errorText()` + 13 个 `CAT_*` 键）；两字典 208→230 键、
  删 2 死键。逐字证据见 [VERIFICATION.md](VERIFICATION.md) §J.9：
  `TSC_EXIT=0`/`ROLLUP_EXIT=0`、`Ran 59 tests OK`、真机只读 `read_only true`/
  `MOD_COUNT 27`/`ZERO_DAMAGE True`/`MODS_SIG 3c073807…` 前后一致；新 `dist/index.js`
  **96224 B / `ee218850…`**、新 **ZIP 123341 B / `23d0efa2…` / 30 entries** byte-exact。
  **诚实边界**：`read_only:true` 下写弹窗被 `E_EXTERNAL_MANAGER` 拒绝 → confirm_text 中文
  无法 QAM 目视，本节只证字典/类型/bundle；QAM 中文与手柄目视（完成标准 (a)(b)）
  仍 `OPEN / DEVICE`，需用户经 Decky UI 装载**本节新 ZIP** 后目视；Track C（path resolver
  重构）独立门控**未执行**；Step 5 写回 `OUT OF SCOPE`；原 G3 仍 `OPEN / NOT SHIPPABLE`；
  `V1` 唯一 `CLOSED`。**不勾选 §B.4 任何 checkbox、不调用 `update_goal(complete)`、
  不宣称 goal 完成**（完成标准 (a)(b) 的 QAM 中文 / 手柄目视仍 `OPEN / DEVICE`）。



> **加性注记 — Track A agent 侧 CDP 取证（2026-11-14；不改上方 Track B 历史快照、状态字一律不动）**：
> 上方 Track B 段末「QAM 中文 / 手柄目视仍 `OPEN / DEVICE`、不宣称 goal 完成」是 **Track B 轮快照**。
> 之后用户 m06789 选「1」→ 真实 Steam Deck / Game Mode / Steam CEF（全 target `lang:"zh-CN"`）下
> 由 agent 用只读 CDP 抓到插件 React 树挂载后的 DOM `innerText`：主内容页全中文（标题 /
> SMAPI 检测行 / READ-ONLY 横幅 / 约束 / 已知限制 6 `LIMIT_*` / 6 个操作按钮 / 已安装的星露谷 MOD（0）），
> 两个弹窗（渲染在 `Steam 大屏幕模式` CEF target，非 `QuickAccess_uid2`）逐字中文全文 =
> `检测到的 MOD（只读，27）` + 27 行 `名称 · 版本 · 作者` + 逐 mod `缺失依赖：` + 2 处
> `E_MANIFEST_MISSING` + 全局 16 项缺依赖 + 无写按钮，以及 `错误码（50）` + 50 条
> `E_* · 中文分类` + 中文消息 + 13 `CAT_*`。逐字证据与方法见
> [VERIFICATION.md](VERIFICATION.md) §J.10 与本目录 `QAM_VISUAL_CHECK.md` 末尾「agent DOM 证据表」附录。
> **(a)(b) 裁定**：达成（`device-rendered-text` 口径）/ PARTIAL（人眼目视口径）；10 项中 1/3/4/5/6/7/8
> PASS、2 PARTIAL（`:78` 含裸英文值）、9 PARTIAL/BLOCKED（焦点/按键不可证）、10 PARTIAL（重渲染仍中文
> 但「退出标签再进」未单独执行）。**口径上限 = 真机 `vis:visible` CEF target 渲染的中文 DOM 文本被逐字捕获**，
> 非人眼手柄目视（无截图 / 不记按键 / 无用户逐项 PASS-FAIL 贴回）。
> 决定性阻塞已解除、goal 客观范围实质达成；**但用户选的是选项「1」非「2」、未显式授权
> `update_goal(complete)`**，故本注记**不勾 §B.4 任何 checkbox、不写 `CLOSED`、不调
> `update_goal(complete)`、不宣称 goal 完成**，goal 保持 `active`，待用户一句显式授权后收口。
> 常驻边界：CDP DOM ≠ 人眼目视；`read_only=true` 下写 confirm 弹窗（`CONFIRM_*`）被
> `E_EXTERNAL_MANAGER` 拒绝、中文不可 QAM 目视；Step 5 写回 `OUT OF SCOPE`；Track C 独立门控未执行、
> 须单独批准；原 G3（RimWorld 294100）`OPEN / NOT SHIPPABLE`；hash↔已加载包仅 MEDIUM 推断
> （保留「byte-exact 必要非充分」，不写「已证明加载包=ee218850」）；`V1` 唯一 `CLOSED`、
> V2–V20/F1–F3 全 `OPEN`；端点 `:{{HELPER_PORT}}`(S9)/V8(S10) 只报告、待用户显式裁决。
---

### §B.5 — 分辨率目视验收（Round 83 新增；全部 `DEVICE` / `OPEN`）

> **为什么单列一组**：上面 §B.1 的 11 项验的是「手柄能不能操作到」，
> §B.4 验的是「功能对不对」。**没有一项验「在两个目标分辨率下看得对不对」**——
> 这正是用户从 Round 30 起反复报的「分辨率问题 / 贴图位移」，
> 也是本轮 px→rem 重构**不能**自动解决的部分（见
> [PANEL_LAYOUT.md](PANEL_LAYOUT.md) §7）。
>
> **状态纪律**：本节新增项一律 `DEVICE`，不写 `CLOSED`，不勾 `[x]`。

**两个目标分辨率**（Steam Deck 原生 + 外接屏）：

| # | 分辨率 | 怎么到达 | 检查什么 | 状态 |
| --- | --- | --- | --- | --- |
| R1 | **1280×800**（Deck 原生） | Game Mode 默认，不接外屏 | 面板不横向溢出；三个切换标签等高；badge 槽在空/非空时同高；焦点环贴住按钮本体 | **DEVICE** |
| R2 | **1920×1080**（外接 / 桌面模式） | 接 HDMI 屏或桌面模式改分辨率后进 QAM | 同 R1；另外确认文字没有因为根字号变化而错位（这是 rem 改造唯一可能改变行为的地方） | **DEVICE** |
| R3 | 分辨率**热切换** | 在 QAM 打开的状态下改分辨率（或拔插 HDMI） | 重开后布局不残留旧尺寸；不出现「贴图位移」 | **DEVICE** |
| R4 | 长文本不撑宽 | 打开「约束 / 已知限制」段与任一长路径确认框 | 中文长句在行内换行，不把行撑出面板右缘 | **DEVICE** |

**为什么这四项必须由人做**：布局只在真机渲染时存在。本机所有布局结论都来自
CDP 抓的 DOM 文本，`tests/test_panel_layout_rules.py` 与
`tests/test_style_units.py` 钉的是**结构**（覆盖没被写回去、单位没退回 px），
不是**观感**。测试通过 ≠ 有人看过屏幕。

**已排除的可能**（本轮审计结论，不需要真机重复验证）：
- 代码里 **0 张图片、0 处 `position: absolute`** → 不存在「贴图」可位移，用户
  看到的位移是焦点环/底图与按钮盒子脱钩，Round 81 已修根因。
- `src/` 下**已无任何 px 字号/间距**（`tests/test_style_units.py` 逐文件断言），
  所以 R2 若仍有错位，原因不在单位，应往 Steam 自身的 `DialogButton` 几何查。

### §B.6 — Round 84 新增控件的目视验收（全部 `DEVICE` / `OPEN`）

> Round 84 修的是「功能缺口」，但其中四项新增了面板上的东西：API key 输入框、
> 归档选择列表、删除游戏确认框、依赖批量安装确认框。结构有测试，
> 观感没有。状态纪律同上：`DEVICE`，不写 `CLOSED`。

| # | 控件 | 怎么到达 | 检查什么 | 状态 |
| --- | --- | --- | --- | --- |
| K1 | ~~API key 输入框~~ | — | **Round 88 删除了这个控件**（连同整套 key 功能，见 §B.7）。此项作废，不再验收 | **VOID** |
| K2 | 归档选择列表 | 导入一个含两个 mod 的 ZIP | 列表项显示 mod 名而非路径；选中后进入该 mod 的普通预览；**不会回到同一个选择列表**（这是本轮修掉的循环） | **DEVICE** |
| K3 | 删除游戏确认 | Games 区 → 任一行 → 删除 | 弹确认框而不是直接删；确认后结果文案说明现在接管的是哪个游戏 | **DEVICE** |
| K4 | 依赖批量安装确认 | 有可获取依赖时点「安装全部依赖」 | 先弹确认并写明数量；取消后不写盘 | **DEVICE** |
| K5 | ~~更新检查结果行~~ | — | **Round 88 删除了「检查 mod 更新」按钮**。想知道某个 mod 是否最新，打开它的 Nexus 页面看（那本来也是唯一能下载的地方） | **VOID** |

**未覆盖**：`.7z` + 归档选择（本机无 `7z` 二进制，`test_7z_listing_with_the_real_binary`
一直 skip），需要在 Deck 上另做一次，见 `docs/ARCHIVE_LAYOUT.md` §「Not proven」。

---

### §B.7 — Round 88 删除 key 之后的面板验收（全部 `DEVICE` / `OPEN`）

> Round 88 从「下载 MOD」区移除了 API key 输入框和 4 个可聚焦行。上面
> 算过这会让该区从约占 86% 降到约 45%（700px 视口），但**没人看过实际渲染**。
> 结构有测试（bundle 里 `ApiKeyBox` / `UPDATE_CHECK` / `api_key` 均 0 次），观感没有。

| # | 看什么 | 怎么到达 | 检查什么 | 状态 |
| --- | --- | --- | --- | --- |
| X1 | 「下载 MOD」区高度 | QAM → 下载 MOD | 整个区**不需要滚动**就能看完全部按钮；最后一个按钮下方留白不过分（说明确实腾出了空间） | **DEVICE** |
| X2 | 小字可读性 | 同一屏，看区块说明文字 | 11px 的说明文字在 1280×800 上手柄看仍可读；与正文（13px）层级仍分得开 | **DEVICE** |
| X3 | 删掉的两句没造成困惑 | Games 区只读态、导入框 | 「只读」这件事**仍被 `READ_ONLY_BANNER` 说清**（含原因）；绝对路径输入框的 placeholder 仍能让人明白该填什么 | **DEVICE** |
| X4 | 三个 Nexus 打开器 | 有 Nexus 域的游戏 → 任一模的作者页/搜索/列表 | 三处都真的打开浏览器页面；没有「要你填 key」之类的残留文案 | **DEVICE** |
| X5 | 没有孤儿错误句子 | 制造 `E_CAPABILITY_DISABLED`（例如对赛博朋克点归档选择） | 显示的是具体理由句（如「这台引擎会整包安装，因此无法从中挑一个 mod」），**不是**通用句、也不是空白 | **DEVICE** |

---

## PART II — 原 RimWorld MVP 验收对象（selection A，历史逐字保留；G3 仍 `OPEN` / NOT SHIPPABLE）

> 以下 §5.1 / §5.2 / 非功能 gate G1–G3 / 全部「状态更正」补记 / 本地证据 / 签核清单
> 均为**原验收对象的历史记录，逐字保留、状态字一律未动**；原 G3（RimWorld 294100）
> 仍 `OPEN`、未被本文件替换、未写 `CLOSED`。PART I 是**新建**的独立验收对象，不构成
> 对原 G3 的签核。§5.2 表头「46 codes」是原对象撰写时的**历史快照**；当前
> `deckymod/errors.py` 为 **50 码**（新增 4 个星露谷码 + 5 个中性化文案），以
> PART I §B.2 为准。

Approved in review #5 (R1 §5): **DoD = 11 gamepad-only operations + 3 non-functional
gates (G1/G2/G3) + the re-coded §5.2 error table (46 codes).**

Every row is marked with where it stands on this Windows dev box:

- **LOCAL-OK** — exercised by the synthetic-tree unittest / directly inspectable in code.
- **DEVICE** — can only be truly confirmed on a Steam Deck (needs Decky + SteamOS).
- **OPEN** — blocked by the G3 gate (see [VERIFICATION.md](VERIFICATION.md)); not
  verified here.

> **Overall: NOT SHIPPABLE YET.** The backend logic passes local tests, but G3
> is still OPEN (V1 version locking was CLOSED 2026-11-12, but V2–V20 / F1–F3
> device & build verification remain OPEN) and the frontend is uncompiled. "All 11 ops
> gamepad-reachable" is a **design + code** claim here, not an on-device acceptance.
>
> **状态更正（2026-11-13 证据回写补记，非状态变更）**：以上「frontend is uncompiled」
> 是**实现轮历史快照**。2026-11-13 已在一台联网 Steam Deck 实跑 `pnpm install` +
> `tsc --noEmit`(strict 零错误，修复 8 个真实 TS 错误) + `rollup -c`（官方
> `@decky/rollup` 产出可加载 ESM），`pnpm-lock.yaml` 与 `dist/` 已回传。但这**只是构建/
> 类型核对证据**：本轮授权「只回写证据、状态一律不动」，故 `V2`–`V20` / `F1`–`F3`
> 仍全部 `OPEN`、未写新的 `CLOSED`、G3 整体仍 `OPEN`。RimWorld 294100 在该 Deck
> 未安装，QAM/手柄 DoD 11 项与真实游戏写回**仍无真值**，仍 NOT SHIPPABLE。逐字
> stdout 与对照见 [VERIFICATION.md](VERIFICATION.md) §H。
>
> **状态更正（2026-11-13 晚补记，非状态变更）**：同日晚用户经 Decky UI 手柄「从 ZIP
> 安装」已把插件装上真机；首启因冻结解释器 PYZ 缺 `xml.etree` 失败，按用户批准加
> `deckymod/__init__.py` 的 XML 兼容 shim 后，**插件在真机冻结解释器里真实加载成功**
> （子进程存活、4 个只读 RPC 全链路返回 JSON-safe 信封），并重建带 shim 的 ZIP 回传。
> 逐字证据见 [VERIFICATION.md](VERIFICATION.md) §H.7。**但**这仍不是 DoD 签核：
> RimWorld 294100 仍未安装、全部 11 项手柄操作（含 Focusable/`showModal` 的 A/B 交互）
> 与真实游戏写回仍**无真值**，故 DoD 行仍按原文 `DEVICE`/`OPEN` 保留、G3 仍 `OPEN`、
> 未写新 `CLOSED`、仍 NOT SHIPPABLE。
>
> **状态更正（2026-11-14 B 方案补记，非状态变更）**：同日按用户「B方案」授权，在真机
> **冻结解释器**里用合成假 RimWorld 树跑通 11 个 RPC 全链路 + 7 类故障注入（41 项全绿），
> 测完逐字节还原；逐字证据见 [VERIFICATION.md](VERIFICATION.md) §H.9。**这仍不是 DoD 签核**：
> 合成树是后端逻辑回归，RimWorld 294100 仍未安装，11 项手柄操作与真实游戏写回仍无真值。
> DoD 行仍 `DEVICE`/`OPEN`、G3 仍 `OPEN`、未写新 `CLOSED`、仍 NOT SHIPPABLE。

---

## §5.1 — 11 operations that must work with D-pad + A/B only

Forbidden everywhere: hover, drag-drop, long-press, right-click, scroll wheel,
touch, trackpad, gyro, Steam/X/Menu keys. Only the optional OSK path box may use the
on-screen keyboard.

| # | Operation | Gamepad requirement | Where implemented | Status |
| --- | --- | --- | --- | --- |
| 1 | Open QAM → plugin tab; first focusable element auto-focused | `…` → D-pad → A | `src/index.tsx` (`<Focusable autoFocus>`) | **DEVICE** (code present, uncompiled) |
| 2 | Browse Inbox | Up/Down; A preview; B back | `openInbox()` + `Modal.showListModal` | **DEVICE** |
| 3 | Import + confirm | A "Import" → ConfirmModal → A confirm / B cancel; shows W1+W2 absolute paths | `inspectAndImport()` → `runTwoPhase()` → `showConfirm` | **DEVICE** (confirm payload LOCAL-OK) |
| 4 | View installed list | Up/Down; A details; B back | `ModRow` list + `showModDetail()` | **DEVICE** |
| 5 | Enable / disable (reversible, **no** 2nd confirm) | single A; toast + "History→Rollback" | `toggle()` → `setModEnabled(pid,next,true)` | **DEVICE** (backend LOCAL-OK) |
| 6 | Uninstall + confirm | A → ConfirmModal (exact mod id) → A / B | `doUninstall()` → two-phase | **DEVICE** (backend LOCAL-OK) |
| 7 | Rollback + confirm | D-pad to History → A pick txn → ConfirmModal → A / B | `openHistory()` → `confirmRollback()` | **DEVICE** (backend LOCAL-OK) |
| 8 | Read / dismiss error | D-pad scroll long text; A or B closes; shows code + short hint + log path; **no traceback** | `ErrorView` / `showErrorModal` | **DEVICE** (message table LOCAL-OK) |
| 9 | Refresh | focusable "Refresh" → A; busy state visible; auto-rescan on tab focus | `doRefresh()` + bootstrap `useEffect` | **DEVICE** |
| 10 | (optional) OSK path input | A focus → Steam OSK → B/Enter submit; fully skippable | `ImportBox` (`TextField`) | **DEVICE** (⚠️ V3 props) |
| 11 | **State survives leaving + reopening the QAM tab** | proven via journal + disk, NOT React state | `journal.py` + `engine.status()` reload | **LOCAL-OK** (synthetic tree rereads state; device re-open DEVICE) |

### Focus / dialog requirements (§5.1, apply to all 11)
Deterministic focus order; every interactive element focusable; A activates, B always
back/close; **destructive confirms (uninstall / rollback / Replace / clear quarantine /
Recover "Roll back") default-focus Cancel** while incremental ops (import) may focus
Confirm but must be B-closable; a single unconfirmed A never triggers a destructive
act; no focus trap; disabled items removed from focus order; lists loop or clamp;
long text scrolls with D-pad; visible focus ring + adequate hit area; after an op focus
returns to a known anchor and a readable "Last result" line remains.
→ Implemented in `src/components/Modal.tsx`, `ConfirmModal.tsx`, `ModRow.tsx`,
`src/index.tsx`. **Status: DEVICE** (shape needs ⚠️ V3 confirmation).

---

## Non-functional gates

### G1 — §5.3 onDismount cleanup  → **LOCAL-OK (code) / DEVICE (runtime)**
`src/index.tsx` `useEffect` cleanup:
- `generation` ref bumped on unmount ⇒ stale in-flight RPC results are discarded
  (backend write txns are **never** aborted — they finish atomically and the next open
  reads the result from the journal);
- `addEventListener(PROGRESS_EVENT, listener)` paired with
  `removeEventListener(PROGRESS_EVENT, listener)` using the **same stable reference**;
- all tracked `setTimeout` timers (toasts, progress) cleared;
- `mounted` flag prevents setState after unmount;
- focus returns to QAM; no watcher/timer/lock survives tab close; re-entry re-runs
  `verify()` (refresh) + inbox rescan.
`main.py` `_unload` clears memory only, never mutates game state, leaves
`PREPARED`/`APPLYING` for next-open `E_RECOVERY_PENDING`. A plugin-level
`onDismount` field (if the locked template has one) is intentionally **not** depended
on — ⚠️ V3.

### G2 — §6 three hard constraints, self-certified → **LOCAL-OK (code + data)**
| Constraint | Evidence | Status |
| --- | --- | --- |
| **Never disable SteamOS read-only** | `requires_readonly_toggle:false`; `allowed_write_roots` = 5 (all `$HOME`/user lib/microSD/Decky-managed); `EROFS`→`E_READONLY_FS` refuses with "no files were changed"; no `sudo` anywhere; §3.8 hard-prohibition #1 | **LOCAL-OK** |
| **No root assumption** | `resolve_user()` uses `DECKY_USER`/`DECKY_USER_HOME`/`pwd.getpwnam`, falls back to `geteuid`; `chown` only when `os.geteuid()==0`; wrong owner → `E_ROOT_OWNED`/`E_STATE_OWNED` refusal (never chmod); non-POSIX mount skips ownership check instead of fixing perms; `requires_root:false` | **LOCAL-OK** (Windows-portability fix applied; see README) |
| **No universal one-click** | `universal_one_click:false`; `max_enabled_games_in_mvp:1`; only `rimworld` `status:enabled`; others `planned` + capability gate refuses (`E_CAPABILITY_DISABLED`); UI shows "ONE game only · no universal one-click"; honest Harmony/order limitation | **LOCAL-OK** (data + code), text **DEVICE** |

### G3 — §7 "verify on device / locked versions" → **OPEN / NOT SATISFIED**
Full checklist in [VERIFICATION.md](VERIFICATION.md): V1–V20 + F1–F3, 9 `⚠️ V#`
markers in `*.py` plus frontend `⚠️ V3` markers. **Deviations to report honestly
(实现轮历史快照；2026-11-13 补记见上方「状态更正」与 VERIFICATION.md §H，状态一律未动):**
- no SteamOS device / Decky runtime ⇒ no on-device run;
- no network / npm registry **on this Windows box** ⇒ `pnpm install`, `pnpm-lock.yaml`,
  `tsc --noEmit`, `rollup` build 跑不了；本机构建前 **frontend 8 files uncompiled /
  un-type-checked**（2026-11-13 已在联网 Deck 上补跑构建，见 §H.2）;
- V1 version locking **CLOSED (2026-11-12)** from user-supplied C1/C2/C3 evidence
  (see [VERIFICATION.md](VERIFICATION.md) §A); `package.json` exact-version write-in and
  `pnpm-lock.yaml` still pending, so V2–V8 / G3 remain OPEN;
- R1 said these should be closed *before the first line of file-writing code* — that
  could not be honoured on this box and is recorded, not hidden.

---

## §5.2 — Re-coded error table (46 codes, from `deckymod/errors.py`)

Unified envelope: `{ok, code, message, detail, data, rollback_available, log_path, ts}`.
One code = one short message; code shown in small text for support; **no raw traceback**
(only in the log); every error closable with A/B; `rollback_available` decides whether
a Rollback / History action is offered. Constraint-type messages contain **no**
`steamos-readonly disable`, `sudo`, or `flatpak override` instructions.

`RB` column = `rollback` offered by default (`True` for the 4 txn/recovery codes).
`St` = local status: **OK** = table entry verified against code; **DEVICE** = the
real failure can only be triggered on device.

### Bridge / backend
| Code | Message (short) | Cat | RB | St |
| --- | --- | --- | --- | --- |
| `E_BACKEND_UNREACHABLE` | Backend is not reachable. Reopen the plugin or restart the Steam Deck. | bridge | – | OK |
| `E_BRIDGE` | Communication with the plugin backend failed. | bridge | – | OK |
| `E_UNKNOWN` | An unexpected error occurred. See the log for details. | internal | – | OK |

### Capability / game selection
| `E_GAME_NOT_FOUND` | RimWorld (AppID 294100) was not found in any Steam library. | discovery | – | OK |
| `E_GAME_AMBIGUOUS` | RimWorld was found in more than one Steam library; cannot choose automatically. | discovery | – | OK |
| `E_CAPABILITY_DISABLED` | This action is not available in this version (RimWorld MVP only). | capability | – | OK |
| `E_GAME_RUNNING` | RimWorld is running. Close the game before changing mods. | safety | – | DEVICE (V20) |
| `E_FLATPAK_PERMISSION` | Flatpak Steam uses an isolated library path. This build does not manage it. | environment | – | DEVICE (F3) |
| `E_LOADER_REQUIRED` | This sample game does not need a loader. (Reserved for planned games.) | planned | – | OK |
| `E_PROTON_PREFIX_MISSING` | This sample game does not need a Proton prefix. (Reserved for planned games.) | planned | – | OK |

### Inbox / import / archive
| `E_INBOX_MISSING` | The import folder does not exist. | import | – | OK |
| `E_INBOX_EMPTY` | No ZIP files found in the import folder. | import | – | OK |
| `E_INBOX_UNREADABLE` | A file in the import folder could not be read. | import | – | OK |
| `E_PATH_INVALID` | The given path is not allowed. | safety | – | OK |
| `E_PATH_ESCAPE` | The path points outside an allowed folder. | safety | – | OK |
| `E_NOT_ALLOWED_ROOT` | The target is outside the allowed write locations. | safety | – | OK |
| `E_BAD_ARCHIVE` | The file is not a valid ZIP archive. | import | – | OK |
| `E_ZIP_BOMB` | The archive is too large or too highly compressed to import safely. | import | – | OK |
| `E_ZIP_SLIP` | The archive contains a path that escapes the mod folder. | import | – | OK |
| `E_UNSAFE_ENTRY` | The archive contains an unsafe entry (link, device, or forbidden file type). | import | – | OK |
| `E_DUPLICATE_ENTRY` | The archive contains duplicate file names. | import | – | OK |
| `E_MANIFEST_MISSING` | About/About.xml was not found in the archive. | import | – | OK |
| `E_MANIFEST_INVALID` | About/About.xml could not be parsed. | import | – | OK |
| `E_ID_INVALID` | The mod's packageId is missing or invalid. | import | – | OK |
| `E_FIELD_MISSING` | A required field is missing from About.xml. | import | – | OK |

### Conflict
| `E_DUPLICATE` | This mod (same packageId) is already installed. Use Replace instead. | conflict | – | OK |
| `E_FILE_COLLISION` | A folder with this name already exists and is not managed by this plugin. | conflict | – | OK |

### Filesystem / permissions
| `E_ACCESS` | Permission denied while writing. The location may be read-only. | fs | – | OK |
| `E_READONLY_FS` | The target filesystem is read-only; no files were changed. | fs | – | DEVICE (EROFS) |
| `E_NO_SPACE` | Not enough free space to complete the operation. | fs | – | DEVICE |
| `E_CROSS_DEVICE` | The staging and target are on different filesystems; operation refused. | fs | – | DEVICE (EXDEV) |
| `E_FS_NO_POSIX` | This drive (e.g. microSD/exFAT) has no POSIX permissions; ownership checks were skipped. | info | – | DEVICE (F1) |
| `E_ROOT_OWNED` | A target file is owned by another user; refusing to change its permissions. | fs | – | DEVICE |
| `E_STATE_OWNED` | The game state file is owned by another user; refusing to edit it. | fs | – | DEVICE |
| `E_STATE_SYMLINK` | The game state file is a symbolic link; refusing to edit it. | safety | – | DEVICE |
| `E_STAGING_IN_MODS` | Staging/quarantine must not be placed inside the Mods folder. | safety | – | OK |
| `E_INODE_MISMATCH` | Files changed between the safety check and the write; operation aborted. | safety | – | OK |

### State file
| `E_CORE_MISSING` | Core (ludeon.rimworld) is missing or not first in ModsConfig.xml; refusing to edit. | state | – | OK |
| `E_STATE_CORRUPT` | ModsConfig.xml could not be parsed; refusing to edit it. | state | – | OK |
| `E_STATE_EXTERNAL` | ModsConfig.xml was changed outside this plugin (or by the game on quit). Refresh and retry. | state | – | OK |
| `E_STATE_MISSING` | ModsConfig.xml was not found at the expected location. | state | – | OK |

### Transaction / rollback
| `E_VERIFY_FAILED` | The post-write verification did not match what was planned. | txn | **True** | OK |
| `E_OP_FAILED` | The operation failed and was rolled back where possible. | txn | **True** | OK |
| `E_RECOVERY_PENDING` | A previous operation did not finish. Use Recover / Rollback first. | txn | **True** | OK |
| `E_ROLLBACK_FAILED` | Automatic rollback could not finish. Your data is preserved in the quarantine folder; see the log. | txn | **True** | OK |
| `E_QUARANTINE_FULL` | The quarantine folder is full; uninstall was refused. | txn | – | DEVICE |

**Count: 46 codes** — by `category` (exact, from `ERRORS`): bridge 2, internal 1,
discovery 2, capability 1, safety 7, environment 1, planned 2, import 12,
conflict 2, fs 6, info 1, state 4, txn 5.
**Exactly 4 codes have `rollback=True` by default**: `E_VERIFY_FAILED`,
`E_OP_FAILED`, `E_RECOVERY_PENDING`, `E_ROLLBACK_FAILED`. Any operation may also
set `rollback_available` at its call site; the table above lists the **default**
value from `ERRORS`.

> Note: the `St=OK` rows mean the **code→message mapping and the detection logic**
> are present and unit-tested where a synthetic trigger exists. They do **not** mean
> the real-world failure was reproduced on a Steam Deck. Triggering real `EROFS`,
> `EXDEV`, `ENOSPC`, root-owned files, microSD/exFAT, Flatpak Steam, or a running
> RimWorld process requires the device — those remain **DEVICE / OPEN**.

---

## Local test evidence (this box)

```
python -m unittest discover -s C:\ai\SD\tests -v   -> Ran 33 tests in 0.595s / OK  (LASTEXITCODE=0)
python C:\ai\SD\tests\_verify.py                    -> compileall: OK ; json files: 12 bad: 0
```

Synthetic tree covers: VDF/ACF parse, JSON-safe conversions, `surgical_line_edit`
(Core invariant, byte preservation), ZIP validation (zip-slip / zip-bomb / forbidden
`.exe` / backslash / duplicate entries / manifest errors), capability gate + forbidden
message strings, atomic writes without POSIX-only calls, path resolution (found /
not-found / Flatpak refused), full Engine lifecycle
(install→enable→disable→uninstall→rollback) plus duplicate/collision/path-escape/
game-running/state-drift/state-missing, and `main.Plugin` RPC envelope shape.

During local testing **one real production bug was found and fixed**: `archive.py`
Round 62 note: the mapping-versus-root defect described below was not the last
one in that area. `_strip_single_root()` was also being used to decide *how deep*
a mod starts, while the manifest glob was matched with `fnmatch`, whose `*`
crosses `/`. Those two answers could disagree, and when they did the install
succeeded while writing the mod one directory too deep to ever load. Both facts
now come from the manifest member itself (`archive.locate_manifest`), and an
archive holding more than one mod is refused with `E_MULTI_MOD_ARCHIVE`.
See `docs/ARCHIVE_LAYOUT.md`.

`inspect_mod()` had its `members` mapping reversed (`_strip_single_root()` returns
`{stripped: original}` but the lookup used the original name), so a single-root-wrapped
ZIP unpacked to `Mods/<pid>/<wrapper>/About/About.xml` and post-commit verification
failed with `E_VERIFY_FAILED`. Fixed by inverting the map to `{original: stripped}`.
`engine.status()` was also improved to return `E_STATE_MISSING` instead of an empty
state object when `ModsConfig.xml` is absent.

---

## Sign-off checklist (for a real device)

- [ ] V1 pinned (template commit + Decky Loader version) — [VERIFICATION.md](VERIFICATION.md)
- [ ] V2–V8 closed; `pnpm-lock.yaml` committed; `tsc --noEmit` + `rollup` green
- [ ] V9–V20 + F1–F3 closed with recorded on-device values
- [ ] All 11 §5.1 ops confirmed on a gamepad (focus, B-closable, busy state)
- [ ] G1 onDismount cleanup observed (no stale timers/subscribers)
- [ ] G2 three hard constraints re-checked on device (no readonly toggle, no root, no universal one-click)
- [ ] §5.2 error table spot-checked: at least `E_GAME_NOT_FOUND`, `E_ZIP_SLIP`,
      `E_DUPLICATE`, `E_FILE_COLLISION`, `E_STATE_EXTERNAL`, `E_READONLY_FS` (or
      equivalent), `E_ROLLBACK_FAILED` — each shows code + short message + log path,
      A/B closable, no traceback, no forbidden instructions
- [ ] Honest limitation shown in UI (Harmony / append_to_end / no solver)

Until every box is ticked, the build is **"implemented + backend self-tested; device
acceptance OPEN"**.
