# VERIFICATION.md — §7 "verify on device / locked versions" checklist (gate G3)

This is the **G3 non-functional gate** from the approved R1 plan (§5.3 / §7 / DoD).
It is the list of things that must be checked **on a real Steam Deck, against a locked
`decky-plugin-template` commit and a locked Decky Loader version**, before this plugin
can be called shippable.

> ## ⚠️ GATE STATUS: **OPEN / NOT SATISFIED ON THIS MACHINE**
>
> This repository was implemented and self-tested on a **Windows dev box** with:
> - no SteamOS / Decky Loader runtime,
> - no network / npm registry (so no `pnpm install`, no `pnpm-lock.yaml`, no
>   `tsc --noEmit`, no `rollup` build),
> - V1 (version locking) is now **CLOSED** from user-supplied C1/C2/C3 evidence
>   (2026-11-12). **【历史快照】** 撰写时 `package.json` exact-version write-in 与
>   `pnpm-lock.yaml` generation (RUNBOOK §4/§5) 尚未做；这两项已于 2026-11-13 完成
>   （精确版本写入本仓库 `package.json`；lockfile 在联网 Deck 生成后回传本工作区，
>   见 §H.2/H.5）——但**这仅是构建证据，不等于 G3 已满足**。
>
> Strictly, G3 says these items should have had conclusions **before the first line of
> file-writing code** was produced. That could not be honoured here — this is recorded
> as a **known, explicit deviation**, not hidden. The backend has been exercised against
> a synthetic Steam tree only. **V1 is `CLOSED`; every other item (`V2`–`V20`, `F1`–`F3`)
> remains `status: OPEN`**, so gate G3 as a whole is still OPEN. Closing the rest requires
> an on-device / networked run; see [ACCEPTANCE.md](ACCEPTANCE.md).
>
> **状态更正（2026-11-13 证据回写补记，非状态变更）**：上面「no `pnpm install` /
> no `pnpm-lock.yaml` / no `tsc --noEmit` / no `rollup` build」是**实现那一轮的历史
> 快照**。2026-11-13 已在一台联网 Steam Deck（SteamOS 3.9.5 / Decky Loader v3.3.1）上
> 实跑 `pnpm install` + `tsc --noEmit` + `rollup -c`，`pnpm-lock.yaml` 与
> `dist/index.js` 已回传本工作区；详见 §H。**但本轮授权是「只回写证据、状态一律
> 不动」，故 `V2`–`V20` / `F1`–`F3` 仍全部 `OPEN`，未写任何 `CLOSED`；G3 整体仍
> `OPEN`。** status 翻转留给完整 DoD + 人工判定，不由证据回写代替。
>
> **状态更正（2026-11-13 晚补记，非状态变更）**：同日晚用户经 Decky UI 手柄从首版
> ZIP 安装了插件，首启因冻结解释器 PYZ 缺 `xml.etree` 失败；按用户批准加了
> `deckymod/__init__.py` 的 XML 兼容 shim，就地补丁 + WS 重载后**插件在真机冻结解释器
> 里真实加载成功**（子进程存活、`deckymod.log` 有 loaded 行、4 个只读 RPC 全链路返回
> JSON-safe 信封），并重建带 shim 的 ZIP 回传。详见 §H.7。**这使「插件能否在真机加载」
> 有了肯定答案，但 RimWorld 294100 仍未安装、手柄 DoD 11 项与真实游戏写回仍无真值，
> 故 `V2`–`V20` / `F1`–`F3` 一律仍 `OPEN`、未写任何 `CLOSED`、G3 整体仍 `OPEN`。**
>
> **状态更正（2026-11-14 证据回写补记，非状态变更）**：连日「不可达」的真因是**端口写错**——
> 真机 deck-helper 终端 API 实际监听 `http://{{DECK_IP}}:{{HELPER_PORT}}`（不是 `{{OLD_DECK_IP}}:{{OLD_HELPER_PORT}}`；Deck 侧 `ss`
> 显示 {{OLD_HELPER_PORT}} 无监听、{{HELPER_PORT}} `LISTEN`，`plugin_loader.service` active）。改用正确端点后，本轮一次性
> 取得三项逐字证据：①V8 的 `pwd` / `ls -l node_modules/.bin/tsc` / `pnpm exec tsc --noEmit;
> echo EXIT=$?`（cwd = 项目根、`tsc` 存在、`EXIT=0`，并补 `--frozen-lockfile` / `typecheck` /
> `build` 全链绿、`dist/index.js` 与交付 ZIP 内文件 hash 一致）；②**真机冻结解释器**里
> `ET.fromstring("<a><b/></a>")` + `.find("b")` 功能等价通过（`CEXT_LOADED=False`，纯 Python
> 路径可用，临时探针已完整还原并干净重载）；③Deck 侧 `ss` / `systemctl status plugin_loader`
> 逐字 stdout。全部收录于 §H.8。**三项均为证据回写，状态字一律未动**：`V8` 仍 `OPEN`，
> `V2`–`V20` / `F1`–`F3` 仍全 `OPEN`，未写任何 `CLOSED`，G3 整体仍 `OPEN`。
>
> **状态更正（2026-11-14 B 方案证据回写补记，非状态变更）**：同日按用户「B方案」授权，给
> 真机已装插件注入**临时、可逆**的 env shim + 2 个 public 测试 hook、经 WS 重载，在**真·冻结
> 子进程**里用**合成假 RimWorld 树**跑通全链路 RPC（status / list_inbox / inspect / install 两阶段
> / set_enabled / disable / uninstall 两阶段 / rollback / history / recovery / refresh）与 7 类故障
> 注入（E_GAME_RUNNING / E_PATH_ESCAPE / E_BAD_ARCHIVE / E_DUPLICATE / E_FILE_COLLISION /
> E_ID_INVALID / E_STATE_EXTERNAL），`PASS_COUNT 41` / `FAIL_COUNT 0` / `ALL_GREEN`；测完
> `main.py` 逐字节还原为交付 hash、hook 消失、合成树删除、插件干净重载。逐字证据见 §H.9。
> **本节同为证据回写，状态字一律未动**：`V2`–`V20` / `F1`–`F3` 仍全 `OPEN`、未写任何 `CLOSED`、
> G3 整体仍 `OPEN`；RimWorld 294100 仍未安装，手柄 DoD 11 项与真实游戏写回仍无真值，
> B 层只证明「后端逻辑在真冻结解释器 + 真 Decky env 下完整可跑且错误码正确」，不替代真游戏签核。

Legend: `V#` = verification item id (used as `⚠️ V#` markers in code comments).
`code` = the exact file/line whose behaviour depends on the item.
`status` is `OPEN` for all items except V1 (now `CLOSED`) until someone runs the check
on a locked device.

---

## A. Lock the toolchain first (prerequisite to everything else)

### V1 — Pin `decky-plugin-template` commit + Decky Loader version
- **What**: choose ONE template commit/tag and ONE Decky Loader release; record exact
  commit SHA / version strings in this repo (e.g. in `package.json` and a
  `VERSIONS.md`); "不追新 / do not chase latest" was explicitly accepted (review #2).
- **Why**: every V2–V8 answer is version-specific; open-ended ranges (`^1.0.0`) are
  not a pin.
- **code**: `package.json`, `plugin.json`, `rollup.config.js` (comment "G3 / V2").
- **status**: **CLOSED** (2026-11-12) — all four locked values below come from the
  user-supplied C1/C2/C3 evidence. This is exactly the "后续轮次在拿到 C1–C3 全部真实
  证据后人工判定" step that [RUNBOOK.md](RUNBOOK.md) §2 rule 4 reserves for a later
  round. **V2–V20 / F1–F3 remain `OPEN`**, so gate G3 as a whole is still OPEN.

> **Honesty boundary**: this session did **not** re-run any `git` / `curl` / `npm`
> command (git / web / npm are unavailable on this Windows dev box — DNS resolves to
> the `198.18.0.0/15` sinkhole and TLS fails with `SEC_E_NO_CREDENTIALS`). Evidence is
> the user's pasted stdout / values from their networked machine. Command exit codes,
> machine OS, C2's `name` field, `npm config get registry`, and `dist-tags --json`
> outputs were **not** supplied and are marked `未提供` — never fabricated.

#### V1 · locked values (user write-back block, 2026-11-12)

| 组件 | 锁定值 | 获取方式 | 判定依据 |
| --- | --- | --- | --- |
| Decky Loader | `v3.3.1` (`published_at` = `2026-10-27T04:26:19Z`) | GitHub API `/repos/SteamDeckHomebrew/decky-loader/releases/latest`, `http_code=200` | `releases/latest` 返回的最新稳定版 |
| `decky-plugin-template` | `90d0780e882a17f5714fc6de044c645f22608290` | `git ls-remote … HEAD`；`git ls-remote --tags … \| wc -l` → `0` | 该模板仓库确证无 tag，锁定默认分支 HEAD |
| `@decky/api` | `1.1.3` | `npm view @decky/api version` | 与 `@decky/ui` 分两条命令执行、按执行顺序对应；两包独立发布、版本线不同步 |
| `@decky/ui` | `4.16.5` | `npm view @decky/ui version` | 同上；**该包未返回 404**，RUNBOOK C3 的 404 分支不触发 |

- **C1 逐字 stdout（保留自上一轮存档）**:
  ```
  90d0780e882a17f5714fc6de044c645f22608290        HEAD
  ```
  第二条 `git ls-remote --tags …` 输出 `无`；`wc -l` = `0`（用户补充证据）。
- **C1 裁定（保留）**: 40 位小写十六进制 + 单行 `\tHEAD`，符合 §2「预期输出形态」；
  `第二条：无` 不触发「输出为空」判据（tag 列表本就是可选锁定锚点），也不适用「只有
  tag 名/拿不到 peeled commit」（未选 tag）→ **没有 tag ≠ 没锁定**，评审 #2 的「锁一个
  commit 或 tag」落定为锁 HEAD 的 commit。
- **模板锚点**: 锁定值是不可变 40 位 SHA；`ref = HEAD`（默认/main 分支被取到那一刻的
  HEAD），**不是**「跟随分支最新」。基准 commit =
  `90d0780e882a17f5714fc6de044c645f22608290`。
- **未提供字段（不编造）**: C1/C2/C3 各命令退出码、机器 OS、C2 的 `name`、
  `npm config get registry` 值、两条 `dist-tags --json` 输出、C1 精确执行时间。
- **仍待落地（不影响 C1–C3 证据，但 V8 之前必须完成）**: [RUNBOOK.md](RUNBOOK.md)
  §4「附：版本锁定写入」尚未执行 —— `package.json` 的 `devDependencies` 目前仍是
  `"@decky/api": "^1.0.0"` / `"@decky/ui": "^0.0.0"` 范围串（后者还是占位值）。下一轮
  须写成精确 `1.1.3` / `4.16.5` 并生成 `pnpm-lock.yaml`，否则 C4 的
  `pnpm install --frozen-lockfile` 会报 lockfile 与 `package.json` 不一致。本轮离线
  准备**不执行该写入、不执行构建、不改 V4–V8 状态、不放宽类型**。

### V2 — `decky` Python module attribute names
- **What**: confirm the attributes exposed by the injected `decky` module:
  `DECKY_USER`, `DECKY_USER_HOME`, `DECKY_PLUGIN_RUNTIME_DIR`,
  `DECKY_PLUGIN_LOG_DIR`, `DECKY_PLUGIN_SETTINGS_DIR`, `DECKY_HOME`, etc.
- **code**: `main.py:68` — `_bridge_env()` copies these into `os.environ` (idempotent,
  never overrides an existing value). If a name differs, env resolution silently
  falls back and game-path resolution breaks.
- **status**: **OPEN**.

### V3 — `@decky/api` / `@decky/ui` API shapes (frontend, biggest gap)
- **What**: against the locked versions confirm —
  - `definePlugin` import source (`@decky/api` vs `@decky/ui`), factory signature,
    return field `name: string` vs legacy `title: ReactNode`, whether a plugin-level
    `onDismount` field exists (we deliberately rely only on React `useEffect`
    cleanup in `src/index.tsx`);
  - `call<T>(method, ...args)` and `callable<Args,Ret>(name)` generic parameter
    order, and that dispatch uses positional args (never kwargs / object);
  - `decky.emit(event, payload)` — sync fire-and-forget vs `await`;
  - `addEventListener` / `removeEventListener` exact signatures and callback arg
    shape (payload as one arg? event object?); subscription needs the **same stable
    function reference**;
  - `@decky/ui` component props: `PanelSection`, `PanelSectionRow`, `ButtonItem`,
    `Focusable` (`autoFocus`, `onCancel`, `onCancelActionDescription`,
    `onActivateActionDescription`), `DialogButton`, `showModal` (return handle with
    `Close()`), `TextField` OSK-trigger props;
  - `toaster` call shape.
- **code**: `src/index.tsx`, `src/api.ts`, `src/components/*.tsx`,
  `src/components/ConfirmModal.tsx`, `src/components/Modal.tsx`,
  `src/components/ImportBox.tsx`, `deckymod/json_safe.py:1` (§1 JSON-safe contract),
  `main.py:68`.
- **status**: **OPEN** — frontend is **uncompiled / un-type-checked** on this box.

### V4 — Template root file layout / `main.py` location
- **What**: confirm `main.py` belongs at plugin root, `plugin.json` root, the
  `defaults/` / `py_modules` / `dist/index.js` conventions of the locked template.
- **code**: `main.py`, `plugin.json`, `rollup.config.js` (output `dist/index.js`).
- **status**: **OPEN**.

### V5 — `plugin.json` exact fields
- **What**: `name`, `api_version`, `flags`, root/privilege flag spelling,
  `publish` / updater keys, `author`, `tags`.
- **code**: `plugin.json`.
- **status**: **OPEN**.

### V6 — rollup output format + externals
- **What**: `cjs` vs `iife` output, `external` list (`react`, `react-dom`,
  `@decky/api`, `@decky/ui`), whether the loader injects React globals.
- **code**: `rollup.config.js`.
- **status**: **OPEN**.

### V7 — TypeScript config compatibility
- **What**: `tsconfig.json` (ES2022 / Bundler / `react-jsx` / `strict`) matches the
  locked template's React version and typings.
- **code**: `tsconfig.json`, `package.json` devDeps.
- **status**: **OPEN**.

### V8 — Frontend build actually succeeds
- **What**: with a committed `pnpm-lock.yaml`, run `pnpm install --frozen-lockfile`,
  `pnpm run typecheck`, `pnpm run build`; produce `dist/index.js`.
- **code**: `.github/workflows/build.yml` (frontend job), `package.json`.
- **status**: **OPEN** — 【历史快照】撰写时「no lockfile, no registry, not run here」。
  2026-11-14 已在联网 Deck 上取得逐字证据全套：`pwd` = `/home/deck/deckymod-build`、
  `node_modules/.bin/tsc` 存在、`pnpm exec tsc --noEmit` → `EXIT=0`；`pnpm install
  --frozen-lockfile` / `pnpm run typecheck` / `pnpm run build` 全 `EXIT=0`；`dist/index.js`
  40295 字节，与交付 ZIP 内文件 SHA256 同为 `878eb3ce…`（byte-exact）。逐字 stdout 见
  §H.8。**状态仍保持 `OPEN`**：本轮仅证据回写，未收到用户显式 `CLOSED` 指令，status
  翻转留给完整 DoD + 人工判定（同 V1 当初由用户回写块显式置 `CLOSED` 的先例）。

---

## A.1 离线准备：V4–V7 逐项比对清单（待联网核对，本轮只列清单、不判定）

> 本轮为「V1 关闭后的离线准备」。**只列清单，不判定，不改 V4–V7 状态**（四者仍
> `OPEN`），不编造比对结论。基准 = V1 锁定的模板 commit
> `90d0780e882a17f5714fc6de044c645f22608290` 与 Decky Loader `v3.3.1`。
>
> **诚实边界**：本机无网络、无法读取该 commit 的仓库树，因此**下表「模板侧」一律写
> 「待核对」，不臆造模板根目录下有哪些配置文件**。模板侧真实文件清单须在联网机器上
> 取得，例如（**本轮不执行**，仅记录获取方式）：
> `curl -sS -fL "https://api.github.com/repos/SteamDeckHomebrew/decky-plugin-template/git/trees/90d0780e882a17f5714fc6de044c645f22608290?recursive=1"`
> 或 `git clone` 后 `git checkout 90d0780…` 再 `git ls-tree -r --name-only HEAD`。
> 「本仓库侧」只列本机 `glob` 实际存在的文件，**不声称与模板一致或不一致**。

| # | 比对项 | 本仓库侧文件（已存在；内容待核对） | 模板侧（commit `90d0780`） | 关联 | 判定 |
| --- | --- | --- | --- | --- | --- |
| 1 | 插件入口 `main.py` 是否应置于插件根目录 | `main.py` | 待核对 | V4 | 待核对 |
| 2 | `plugin.json` 是否应置于根目录 | `plugin.json` | 待核对 | V4 / V5 | 待核对 |
| 3 | 模板的 `defaults/` 目录约定 | 本仓库**无** `defaults/`（仅事实陈述） | 待核对 | V4 | 待核对 |
| 4 | 模板的 `py_modules/` （或等价 Python 依赖投放）约定 | 本仓库为 `deckymod/` 包 + `registry/` 数据目录 | 待核对 | V4 | 待核对 |
| 5 | 前端产物路径与格式（`dist/index.js`，`cjs` vs `iife`） | `rollup.config.js` 声明 `dist/index.js` / `cjs`；`dist/` 当前不存在 | 待核对 | V4 / V6 | 待核对 |
| 6 | `plugin.json` 精确字段：`name` / `api_version` / `flags` / root 或 privilege 标志拼写 / `publish` 与 updater 键 / `author` / `tags` | `plugin.json`（13 行） | 待核对 | V5 | 待核对 |
| 7 | rollup `external` 清单（`react` / `react-dom` / `@decky/api` / `@decky/ui`）及 loader 是否注入 React 全局 | `rollup.config.js` | 待核对 | V6 | 待核对 |
| 8 | `tsconfig.json` 与锁定模板的 React 版本 / typings 兼容（`ES2022` / `Bundler` / `react-jsx` / `strict`） | `tsconfig.json` | 待核对 | V7 | 待核对 |
| 9 | `package.json` 的 `scripts` / devDeps 与模板脚手架是否对齐 | `package.json`（31 行）；`@decky/*` 仍为范围串，见 V1「仍待落地」 | 待核对 | V7 / V1 | 待核对 |
| 10 | CI 工作流与模板 / `--frozen-lockfile` 约定 | `.github/workflows/build.yml`（36 行） | 待核对 | V8 | 待核对 |
| 11 | 其余根级文件清单差异（逐字文件名比对） | `.gitignore`、`README.md`、`docs/`、`tests/`、`src/`、`registry/` | 待核对 | V4 | 待核对 |

> 上表第 3、4、5 行的「本仓库无 / 当前不存在」是**本机可观察的事实陈述**，不是
> 「与模板不一致」的判定；是否为差异须联网取到模板树后人工比对，本轮不下结论。

---

## A.2 V8 阻塞说明（本轮不执行构建、不改 V8 状态）

- **V8 仍为 `OPEN`**，且本轮**不**改它（也不改 V3/V4–V7）。
- **依赖 1 — `pnpm-lock.yaml`**：不存在（本机 `glob` 未见）。它必须由
  [RUNBOOK.md](RUNBOOK.md) §5 的 `pnpm install` 在**可联网、有真实 npm registry**的
  机器上生成；本仓库 `package.json` 的 `@decky/api` / `@decky/ui` 目前仍是 `^1.0.0` /
  `^0.0.0` 范围串（后者为占位值），须先按 §4 写成精确 `1.1.3` / `4.16.5`，否则
  `--frozen-lockfile` 会报 lockfile 与 `package.json` 不一致。
- **依赖 2 — 可联网环境**：本机 DNS 落到 `198.18.0.0/15` 拦截网段、TLS 报
  `SEC_E_NO_CREDENTIALS`，`node_modules/`、`pnpm-lock.yaml`、bundled `typescript`
  均不存在，`pnpm install` / `tsc --noEmit` / `rollup -c` 无法执行。
- 因此 `dist/index.js` 仍不存在、前端 8 个文件仍**未编译、未类型检查**；V3 亦保持
  `OPEN`。本机无法闭环 V8，须交给联网机器（含 CI runner）完成。
- **本轮未执行**任何 `pnpm` / `tsc` / `rollup` 命令，未放宽类型（未关 `strict`、未加
  `@ts-ignore` / `as any`、未删 `typecheck`、未降伪版本）。

---

## B. Decky ↔ Python runtime contract

### V11 — Python `Plugin` class shape
- **What**: confirm no base class required, which methods must be `async def`,
  reserved lifecycle hooks (`_main`, `_unload`, `_uninstall`, `_migration`), and that
  public methods are dispatched by `getattr` with positional args.
- **code**: `main.py` (`class Plugin`).
- **status**: **OPEN**.

### V12 — `_unload` / `_uninstall` / `_migration` semantics (G1)
- **What**: confirm Decky calls `_unload` on disable/reload and `_uninstall` on
  removal; our `_unload` clears memory only (never mutates game state) and leaves
  `PREPARED`/`APPLYING` txns for next-open `E_RECOVERY_PENDING`; `_uninstall` deletes
  no game data / quarantine / journal.
- **code**: `main.py` (`_unload`, `_uninstall`, `_migration`).
- **status**: **OPEN**.

### V13 — `call` result / exception propagation
- **What**: confirm a raised Python exception or a non-serializable return reaches
  the frontend as a rejected promise (our `invoke()` guard normalises it into
  `E_BACKEND_UNREACHABLE`); confirm `decky.emit` isn't awaited.
- **code**: `src/api.ts` (`invoke`), `main.py` (`_guard`), `main.py` (`_emit`).
- **status**: **OPEN**.

---

## C. Steam library / install-dir resolution

### V9 — `appmanifest_294100.acf` `installdir` verbatim casing
- **What**: on the device, open `steamapps/appmanifest_294100.acf` and record the
  **exact** `installdir` value (case-sensitive, ≠ store title). Our parser preserves
  it verbatim and resolves `GAME_ROOT` with a case-insensitive `os.listdir()`
  fallback.
- **code**: `deckymod/paths.py:206` (`_resolve_install_dir`),
  `deckymod/paths.py:211` (case fallback), `registry/games/rimworld.json:11`.
- **status**: **OPEN**.

### V10 — `libraryfolders.vdf` location + schema
- **What**: confirm on the locked Steam client whether the file is under
  `steamapps/` or `config/`, the key casing (`LibraryFolders` vs `libraryfolders`),
  and the entry schema (`path` + `apps`, indexed `0`/`1`/…). Our finder scans three
  candidate locations and recursively collects any `"path"` key; the VDF parser is
  dependency-free.
- **code**: `deckymod/paths.py:89` (native Steam roots),
  `deckymod/paths.py:102` (`_find_libraryfolders_vdf` three candidates),
  `deckymod/vdf.py:12` (`parse_vdf` / `find_library_paths`).
- **status**: **OPEN**.

### V17 — VDF / ACF parse against the locked client version
- **What**: run `parse_vdf` / `find_library_paths` / `get_installdir` against the
  device's real `libraryfolders.vdf` and `appmanifest_294100.acf` (comments,
  `//` / `/* */`, escaped quotes, nested braces).
- **code**: `deckymod/vdf.py:12`.
- **status**: **OPEN**.

### V18 — Case-insensitive path resolution fallback
- **What**: confirm the `os.listdir()` case-insensitive hit works on ext4 and on
  case-insensitive microSD/exFAT, and that `realpath` containment holds.
- **code**: `deckymod/paths.py:211`.
- **status**: **OPEN**.

---

## D. Game state file (`ModsConfig.xml`)

### V14 — Exact `ModsConfig.xml` path
- **What**: confirm `$XDG_CONFIG_HOME` (vs `$HOME/.config`), the literal path
  `unity3d/Ludeon Studios/RimWorld by Ludeon Studios/Config/ModsConfig.xml`
  (spaces, casing), and any differences across RimWorld 1.4 / 1.5 / 1.6.
- **code**: `deckymod/paths.py` (`state_file`), `registry/games/rimworld.json:17`.
- **status**: **OPEN**.

### V15 — `surgical_line_edit` write-back acceptance
- **What**: confirm RimWorld accepts a `ModsConfig.xml` where we inserted/deleted one
  `<li>…</li>` line inside `<activeMods>` while preserving all other bytes
  (comments, `<version>`, `<knownExpansions>`, encoding, indentation). Confirm when
  the game rewrites the file (on quit?).
- **code**: `deckymod/state_mutator.py` (`add_entry` / `remove_entry`),
  `registry/games/rimworld.json:87` (`write_impl`), `deckymod/engine.py`
  (`_read_state` / `verify_on_open`).
- **status**: **OPEN** — highest-risk item.

### V16 — Does RimWorld ignore dot-directories under `Mods/`?
- **What**: decide whether staging/quarantine could be inside `Mods/`. We currently
  place them as **siblings** of `Mods/` (`${GAME_ROOT}/.decky-staging`,
  `${GAME_ROOT}/.decky-quarantine`) precisely to avoid the game scanning them for
  `About/About.xml`. `E_STAGING_IN_MODS` guards the invariant.
- **code**: `deckymod/paths.py` (staging/quarantine), `deckymod/errors.py`
  (`E_STAGING_IN_MODS`), `registry/games/rimworld.json:26`.
- **status**: **OPEN**.

---

## E. Archives and packages

### V19 — `strip_single_root` common archive shapes
- **What**: test real community ZIPs (top-level `About/`, single wrapper dir, nested
  wrapper) against `manifest_globs` + `strip_single_root:true`; confirm the mapping
  that unpacks `About/About.xml` to `Mods/<packageId>/About/About.xml` (top level).
  A real bug here (reversed members mapping) was found and fixed during local
  self-test — re-verify on device with real archives.
- **code**: `deckymod/archive.py:1` (`inspect_zip` / `_strip_single_root` /
  `inspect_mod` / `extract_to`), `registry/games/rimworld.json:40`.
- **status**: **OPEN**.

### V20 — "Is RimWorld running?" detection
- **What**: replace the conservative dev-box check (env `DECKYMOD_GAME_RUNNING`) with
  a real on-device mechanism; confirm what Decky/Steam exposes. Must not rely on
  `sudo`/root.
- **code**: `deckymod/engine.py:79` (`_check_not_running`).
- **status**: **OPEN**.

---

## F. Cross-cutting environment probes (R1 §7 additions)

### F1 — microSD / exFAT mount facts
- **What**: on a Deck with a microSD card: record mount point, FS type, mount options
  (`noexec`?), whether `/proc/self/mountinfo` reports it as non-POSIX, and the exact
  `errno` from `fchmod` / `fchown`. Confirm `E_FS_NO_POSIX` tolerance and that
  `os.replace` of a whole mod dir within the same mount works.
- **code**: `deckymod/fsops.py` (`is_posix_fs`, `_maybe_fchmod`, `preflight_root`,
  `atomic_write_bytes`, `same_filesystem`).
- **status**: **OPEN**.

### F2 — Is `${DECKY_DATA}` ever cross-device with W2?
- **What**: confirm the internal-SSD Decky data dir and a microSD game install are (or
  are not) different filesystems; this justifies the quarantine-on-W2 exception.
  Record `EXDEV(18)` behaviour if a cross-device rename is attempted.
- **code**: `registry/registry.json:24` (`allowed_write_roots_note`),
  `registry/games/rimworld.json:27`, `deckymod/fsops.py` (`same_filesystem`).
- **status**: **OPEN**.

### F3 — Flatpak Steam mapping
- **What**: if Steam itself is a Flatpak (`com.valvesoftware.Steam`), confirm library
  path mapping under `~/.var/app/com.valvesoftware.Steam/…`. MVP **detects and
  refuses** with `E_FLATPAK_PERMISSION`; it never runs `flatpak --user override` and
  never grants `home`/`host`. A future milestone would need an explicit, user-run,
  one-time permission change.
- **code**: `deckymod/paths.py` (`_flatpak_steam_root`, `E_FLATPAK_PERMISSION`),
  `deckymod/errors.py:24`.
- **status**: **OPEN**.

---

## G. `⚠️ V#` markers currently in the code

Located by `grep '⚠️|V\d+|核实'` across `*.py` (9 markers):

| File:line | Marker |
| --- | --- |
| `main.py:68` | ⚠️ V2/V3 — `decky` attribute names |
| `deckymod/engine.py:79` | ⚠️ V20 — on-device running-process detection |
| `deckymod/archive.py:1` | §7 V19 — `strip_single_root` shapes |
| `deckymod/json_safe.py:1` | §1/§7 V3 — JSON-safe contract |
| `deckymod/paths.py:89` | ⚠️ V10 — native Steam roots |
| `deckymod/paths.py:102` | §7 V10 — `libraryfolders.vdf` location |
| `deckymod/paths.py:206` | ⚠️ V9 — `installdir` verbatim casing |
| `deckymod/paths.py:211` | ⚠️ V9/V18 — case-insensitive fallback |
| `deckymod/vdf.py:12` | ⚠️ V10/V17 — VDF parse vs locked client |

Frontend `⚠️ V3` markers live in `src/index.tsx`, `src/api.ts`,
`src/components/ConfirmModal.tsx`, `src/components/Modal.tsx`,
`src/components/ImportBox.tsx`.

---

## H. 真机 / 联网环境证据回写（2026-11-13，非状态变更）

> **本节的授权边界**：用户 2026-11-13 批准 (a) 干跑 → (b) 构建 → (d) 只回写证据 →
> (c) 部署。本节是 **(d)**：把真机 stdout 逐字/摘要记录进本文件，**`V2`–`V20` /
> `F1`–`F3` 状态一律不动、全部保持 `OPEN`，未写任何 `CLOSED`，G3 整体仍 `OPEN`**。
> status 翻转留给完整 DoD + 人工判定，不由证据回写代替。
>
> **证据来源与诚实边界**：这些输出**不是**本 Windows 开发箱（`C:\ai\SD`，无网、
> DNS 落 `198.18.0.0/15`）跑出来的，而是**一台真实联网 Steam Deck** 上跑出来的。
> 命令经该机局域网 deck-helper 终端 API（**【历史端口】** `http://{{OLD_DECK_IP}}:{{OLD_HELPER_PORT}}`；
> 2026-11-14 起真机实际监听 `http://{{DECK_IP}}:{{HELPER_PORT}}`，见 §H.8，Python aiohttp、
> **无鉴权**、`Access-Control-Allow-Origin: *`）代理执行，`/bin/bash -lc` + `whoami=deck`；
> 结果逐字回传存于 `C:\ai\SD\.decky-probe\h_*_result.txt`。**本会话未用 SSH、未假设
> root、未关闭 SteamOS 只读、未冒用手柄实测**。端点无鉴权，用毕应关闭该终端服务。

### H.0 设备与版本（只读实测）

| 项 | 实测值 |
| --- | --- |
| 主机名 / 系统 | `{{DECK_HOSTNAME}}` / `SteamOS 3.9.5 holo`，`VARIANT_ID=steamdeck`，`BUILD_ID=20261023.100`，`ID_LIKE=arch` |
| 内核 | `Linux {{DECK_HOSTNAME}} 7.2.7-valve2-2-neptune-72-g31504582a073 #1 SMP PREEMPT_DYNAMIC … x86_64` |
| Decky Loader | `v3.3.1`（`~/homebrew/services/.loader.version`；`systemctl status plugin_loader` active，进程名 `Decky Loader v3.3.1`）；`~/decky-loader-release.json` = `tag_name v3.3.1` / `name Release v3.3.1` / `published_at 2026-10-27T04:26:19Z`（补齐 V1 曾标「未提供」的 `name`） |
| Python | `3.14.6` |
| 根文件系统 | `/` = btrfs **`rw`**（非 ro，用 82%、剩 837M）；`/home` = ext4 剩 542G；W1/W2/W3 全落 `/home`，不碰根 |
| 权限 | `~/homebrew/plugins` = `root:root 755`（deck 不可写）；`sudo -n true` **DENIED**；`systemctl show plugin_loader` → `User=root` / `MainPID=14804`。→ 不能自己写 plugins 目录，须走 Decky UI「从 ZIP 安装」（服务以 root 代劳），**不假设 root** |
| 网络 | `curl registry.npmjs.org` = 200、`api.github.com` = 200（**这台 Deck 能联网**）；`~/.npmrc` = `registry=https://registry.npmmirror.com` |
| 工具链 | `git 2.55.0` / `curl` / `python3` / `flatpak` / `jq` 在；Node via `~/.nvm/versions/node/v22.23.2`（`npm 10.9.8`）；`npm i -g pnpm@9` → **`pnpm 9.15.9`**（对齐 CI）；`node ~/nodejs/lib/node_modules/pnpm/bin/pnpm.mjs` = 12.5.1（`pnpm` 不在 PATH） |

### H.1 (a) 零风险干跑（真 SteamOS，不碰真实游戏文件）

- 38 个源码文件逐个 `POST /upload` 到 Deck `~/deckymod-build/` 相对路径逐字保留：`TOTAL=38 OK=38 FAIL=0`。
- `python3 -m compileall -q deckymod main.py` → `COMPILEALL_OK`。
- `python3 -m unittest discover -s tests -v` → **`Ran 33 tests in 0.184s OK`**，exit 0（真 SteamOS / Python 3.14.6）。
- env 注入 `status()` 干跑（合成树 `/home/deck/deckymod-drytree`，`DECKY_USER_HOME` / `XDG_CONFIG_HOME` / `DECKYMOD_INBOX` / `DECKYMOD_DATA` / `DECKYMOD_STEAM_ROOT` 全指向合成树，无 Decky 运行时）：返回 `{"ok":true,"game":{"appid":294100,"name":"RimWorld","platform":"linux-native","status":"enabled"},"w1":"…/unity3d/Ludeon Studios/RimWorld by Ludeon Studios/Config/ModsConfig.xml","flatpak":false}`。
- `fsops.atomic_write_bytes` 真 Linux：`POSIX_FCHMOD True WROTE b'abc' MODE 0o644`。

### H.2 (b) 精确版本写入 + 构建全绿（V8 相关证据，状态不动）

- **版本锁定写入**（RUNBOOK §4 推迟项，`V1 CLOSED` 授权）：`package.json` 把 `"@decky/api": "^1.0.0"`→`"1.1.3"`、`"@decky/ui": "^0.0.0"`→`"4.16.5"`；联网 `npm view "@decky/api@1.1.3" version`→`1.1.3`、`npm view "@decky/ui@4.16.5" version`→`4.16.5`（精确版本真实存在，无 404）。**这是精确版本写入，不是放宽类型、不是状态变更。**
- `pnpm@9.15.9 install` RC=0：首次 `Packages: +45`（`@decky/api 1.1.3` / `@decky/ui 4.16.5` / `rollup 4.68.2` / `typescript 5.9.3` / `@types/react 18.3.31` / 各 `@rollup/plugin-*` …）；生成 `pnpm-lock.yaml` + `node_modules/.bin/{rollup,tsc,tsserver}`。
- **首次 `pnpm run typecheck` strict → RC=2，8 个真实 TS 错误**（`h_24718bfe_result.txt`）：`src/api.ts:53` `TS2344: Type 'Envelope<T>' does not satisfy the constraint 'any[]'.`、`src/api.ts:55` ×3 `TS1345: An expression of type 'void' cannot be tested for truthiness.`、`ConfirmModal.tsx:40` 与 `Modal.tsx:65/104/162` `TS2322: Property 'onActivateActionDescription' does not exist … Did you mean 'onCancelActionDescription'?`。首次 `pnpm run build` RC=0 但 `dist/index.js` 是 **CJS**（36913 字节）+ 警告 `Unresolved dependencies: react/jsx-runtime`。
- **根因（对照已装 `.d.ts`，V2/V3 证据）**：`@decky/api/dist/index.d.ts:12-13` `call: <Args extends any[] = [], Return = void>(route, ...args) => Promise<Return>` / `callable: <Args extends any[] = [], Return = void>(route) => (...args) => Promise<Return>` → **第一泛型是参数元组、第二是返回类型**，`api.ts` 原 `call<Envelope<T>>` 用反了。`@decky/ui/.../FooterLegend.d.ts:74-75` 有 `onOKActionDescription` / `onCancelActionDescription`，**无 `onActivateActionDescription`**；`FocusableProps extends … FooterLegendProps`。`Modal.d.ts:17-22` `showModal(...) => ShowModalResult { Close(); ClosedPromise; Update() }`。
- **修复 3 文件（纯 API 对齐，未放宽 `strict`、未加 `@ts-ignore` / `as any`）**：`src/api.ts:53` `call<unknown[], Envelope<T>>(method, ...args)`；`src/components/Modal.tsx` 3 处、`src/components/ConfirmModal.tsx` 1 处 `onActivateActionDescription`→`onOKActionDescription`。修复后 `TYPECHECK_RC=0`。
- **V6 可加载性发现**：5/5 已装插件 `~/homebrew/plugins/{Mako,Nexus Mods,protondb-decky,Decky LSFG-VK,DeckyClash}/dist/index.js` 全为 **ESM**（`export default`、0 个 `require(`、数百 `SP_REACT/SP_JSX/DFL` 全局引用）。手写 `rollup.config.js`（`format:'cjs'`、external 含 `@decky/api`）与锁定模板 commit `90d0780e…` 不一致；CJS 包部署会 `require is not defined`。→ 用户 2026-11-13 选「改用官方 `@decky/rollup`」。
- **改用官方构建**：`rollup.config.js` → `import deckyPlugin from '@decky/rollup'; export default deckyPlugin({});`，`package.json` 加 `"@decky/rollup": "1.0.2"`（精确）。`@decky/rollup 1.0.2` 配置：`externalGlobals({react:'SP_REACT','react/jsx-runtime':'SP_JSX','react-dom':'SP_REACTDOM','@decky/ui':'DFL','@decky/manifest':…})`、`external:['react','react-dom','@decky/ui']`（`@decky/api` **内联**）、`output:{dir:'dist',format:'esm',sourcemap:true,exports:'default'}`、`context:'window'`。重装 `Packages: +79`。
- **最终构建 RC=0**：`pnpm run typecheck` `TYPECHECK_RC=0`（strict 零错误）；`pnpm run build` `BUILD_RC=0`，`dist/index.js` **40295 字节** + `dist/index.js.map` 76738 字节。产物形态：开头 `const manifest = {"name":"Decky MOD Manager"};` / `const API_VERSION = 2;` / `const internalAPIConnection = window.__DECKY_SECRET_INTERNALS…_deckyLoaderAPIInit;`（`@decky/api` 内联），结尾 `export { index as default };`；计数 `require( = 0`、`SP_JSX 84`、`SP_REACT 13`、`DFL 51`。与 5/5 已装插件同构。
- `API_VERSION = 2` 疑虑排除：5 个已装插件 `plugin.json` 均 `api_version: 1` 但产物同样 `API_VERSION = 2`（`@decky/api` 的 loader 连接协议版本，含 `connect(1,…)` 回退）→ **不改 `plugin.json`**。

### H.3 路径 / 游戏 / 沙盒（V9/V10/V14/V17/V18/F1–F3 证据，含「无真值」）

- native `~/.local/share/Steam` 存在；`libraryfolders.vdf` 两份（`steamapps/` 与 `config/`），标准 schema（`"libraryfolders"→"0"→path/label/contentid/totalsize/apps`）。
- **无 Flatpak Steam**（`flatpak list` 只有 Chrome/Edge/Moonlight/Amethyst/Ryujinx/Fcitx/Firefox）→ **F3 无对象**，但 native 路径分支已在 H.1 干跑确证。
- `appmanifest_*.acf` 一堆其它游戏但**无 `appmanifest_294100.acf`**；`steamapps/common/` 44 目录**无 RimWorld**；**无 `ModsConfig.xml`**；`~/.config/unity3d/` 只有 noio / Team Cherry / unknown；无 RimWorld 进程。→ **V9（`installdir` 大小写）/ V14（ModsConfig.xml 路径）/ V15（写回）/ V16（点号目录）/ V19（真实 ZIP 形状）/ V20（运行中检测）与手柄 DoD 11 项「暂无真值」，保持 `OPEN`。**
- 无 `/dev/mmcblk*`、`/run/media` 空 → **F1（microSD/exFAT）、F2（跨设备 EXDEV）测不了，保持 `OPEN`**。
- `decky.pyi`（模板，逐字常量清单）与 `main.py:73-87 _bridge_env()` 名单吻合：`HOME/USER/DECKY_VERSION/DECKY_USER/DECKY_USER_HOME/DECKY_HOME/DECKY_PLUGIN_SETTINGS_DIR/DECKY_PLUGIN_RUNTIME_DIR/DECKY_PLUGIN_LOG_DIR/DECKY_PLUGIN_DIR/DECKY_PLUGIN_NAME/DECKY_PLUGIN_VERSION/DECKY_PLUGIN_AUTHOR/DECKY_PLUGIN_LOG`；`async def emit(event: str, *args: Any) -> None`。但 `/proc/<pid>/environ` 全 `Permission denied` → **V2 仍需插件进程内确认，保持 `OPEN`**。

### H.4 部署约定（Decky Loader v3.3.1 权威源码，Deck 联网 `git clone --branch v3.3.1`）

- `browser.py:58-64` `_unzip_to_plugin_dir` → `ZipFile(zip).extractall(self.plugin_path)`（展开到 `~/homebrew/plugins/`）；`:151-177` `plugin_json_list = [f for f in namelist() if f.endswith("/plugin.json") and f.count("/")==1]`，0→`fatal("No plugin.json found in plugin ZIP")`、>1→`fatal("Multiple …")`、恰 1 个取顶层目录名再被 `plugin.json` 的 `name` 覆盖。→ **(c) ZIP 必须有且仅有一个顶层目录、`<顶层>/plugin.json` 位于第一层**。
- `browser.py:120-135 set_plugin_dir_permissions`：`"root" in flags` 才 chown 为 root；我们 `flags: []` → 非 root（符合硬约束）。`:196-198` 本地 ZIP `artifact` 需 `file://` 前缀（7 字符）。
- `plugin/sandboxed_plugin.py:91` `sys.path.append(path.join(environ["DECKY_PLUGIN_DIR"], "py_modules"))`（**唯一显式加的路径**）；`:112-119` `spec_from_file_location("_", self.file)` + `module_from_spec` + `exec_module` + `if api_version > 0: self.Plugin = module.Plugin()`；`helpers.py:94-108 get_system_pythonpaths()` 过滤掉 `sys.path[0]==''`（`python3 -c` 的 cwd）→ **插件根不在 import 路径**。`plugin/plugin.py:34-45` 读 `package.json` `type: module` → `ESMODULE_V1`，读 `plugin.json` `flags/api_version`。
- **三布局实测（loader 同款 exec_module）**：A) `deckymod/`+`registry/` 放插件根、只 append `py_modules` → `FAIL ModuleNotFoundError: No module named 'deckymod'`；B) 放进 `py_modules/` → `OK Plugin=Plugin` / `enabled_games=['rimworld']`；C) 根布局 + `main.py` 顶部 `sys.path.insert(0,HERE)` → 亦 OK。**决策：ZIP 用 B（`py_modules/deckymod/` + `py_modules/registry/`），不改源码**（唯一无条件保证机制；`deckymod/registry.py:19,24-25` 用 `os.path.dirname(os.path.dirname(__file__))` 找 `registry/`，移到 `py_modules/` 后祖父目录正是 `py_modules/`，故须同放）。ZIP 是构建产物、与源码仓布局不同，此变换记录在此。
- `utilities.py:55-66` WS 路由 install/confirm/uninstall；`browser.py:309-326` `request_plugin_install` 的 `request_id = str(time())` 只 `emit("loader/add_plugin_install_prompt",…)` **不返回 id**，`confirm_plugin_install(request_id)` 才 `_install`；`wsrouter.py:82` 需 `auth == csrf_token`，`GET /auth/token` 返回纯文本（`AUTH_HTTP=200`）。→ **无法无头安装，最终确认必须走 Decky UI 手柄「从 ZIP 安装」**（配合 plugins 目录 root:root 755 / 无 sudo）。

### H.5 (c) ZIP 已组装 + loader 同款验证 + 产物回传（未安装）

- Deck `/home/deck/Downloads/DeckyModManager-0.1.0-mvp.zip` **首版** = 77983 字节，SHA256 `70ad2f10418056aaa5b8c71f00ec222253602e0dab0948d1258d3aca544964ea`；顶层 `decky-mod-manager/`；26 文件 = `plugin.json` / `package.json` / `main.py` / `dist/index.js` / `dist/index.js.map` + `py_modules/deckymod/*.py`(12) + `py_modules/registry/*.json`(**9**：顶层 1 + games 3 + loaders 5；此前记为 12 有误，见 H.7 更正）。
- **【历史快照】** 下条「产物回传」的四项 hash/size 对应此**首版** ZIP；2026-11-13 晚因真机加载暴露 `xml.etree` 缺失（H.7），已用带 shim 的 `deckymod/__init__.py` **重建** ZIP 为 78863 字节 / SHA256 `49cd684b742fa320983284c9f07b74dd66a9f8e7a9687501026d6c115d529337`，并回传覆盖本地 `C:\ai\SD\DeckyModManager-0.1.0-mvp.zip`（byte-exact）。**当前交付物以 H.7 的重建版为准；本节「未安装」结论亦已被 H.7 的用户 UI 安装取代。**
- loader 同款验证全通过：`PLUGIN_JSON_SCAN`=`['decky-mod-manager/plugin.json']` count 1、`LOADER_NAME_OVERRIDE 'Decky MOD Manager'`、`flags [] api_version 1`、`package.json type module version 0.1.0`、ESM `require( 0` / `export default True` / `SP_JSX 84` / `DFL 51`；extractall 到 scratch + append `py_modules` + exec_module → `EXTRACTED_IMPORT_OK Plugin= Plugin | enabled_games ['rimworld']`；`BUILD_SCRIPT_RC=0`。
- **产物回传本机（`GET /api/files/download`，全 HTTP 200，byte-exact）**：`C:\ai\SD\pnpm-lock.yaml` 41231 字节（含 `'@decky/rollup@1.0.2'`）、`C:\ai\SD\dist\index.js` 40295 字节、`C:\ai\SD\dist\index.js.map` 76738 字节、`C:\ai\SD\DeckyModManager-0.1.0-mvp.zip` 77983 字节（SHA256 与 Deck 一致）。
- **(c) 尚未完成安装**：ZIP 已就绪并验证，但**没有**写 `~/homebrew/plugins`（无 root / 须 UI 手柄确认），也**没有** QAM 加载、手柄 DoD 11 项、真实游戏写回等真机行为验证。这些保持 `OPEN`。

### H.6 本节覆盖 / 未覆盖的核对项（状态一律不动）

- **提供了实测证据但保持 `OPEN`**：V2（`decky.pyi` 清单吻合，进程内 environ 仍待确证）、V3（8 错修复 + `.d.ts` 对照）、V4–V7（模板树 / `@decky/rollup` / tsconfig / plugin.json 字段 / rollup external 已取权威源码核对）、V8（install + typecheck + build 全绿、lockfile + dist 已生成并回传）、V10/V17（`libraryfolders.vdf` schema）、V18（native 路径分支干跑）。
- **无真值、保持 `OPEN`**：V9/V14/V15/V16（RimWorld 294100 未安装）、V19/V20（无真实游戏/进程）、F1/F2（无 microSD/跨设备）、F3（无 Flatpak Steam）、V11/V12/V13（插件进程内行为 / 迁移 / emit 需真加载）、手柄 DoD 11 项（须 UI 安装 + 游戏）。
- **未写任何 `CLOSED`**；`V1` 仍是唯一 `CLOSED`（2026-11-12 用户 C1/C2/C3 证据）；G3 整体仍 `OPEN`。
- **本轮未做**：关闭 SteamOS 只读、假设 root、宣称全游戏通用一键装、放宽 `strict`、改任何 V#/F# 状态、产生新的 `CLOSED`、把未装 RimWorld 的项伪装成已验证。

### H.7 真机 UI 安装 → 启动失败 → XML 兼容 shim → 真机加载成功（2026-11-13 晚，非状态变更）

> **授权边界**：用户 2026-11-13 晚回写「已安装」（经 Decky UI 手柄「从 ZIP 安装」首版 ZIP），
> 随后针对加载失败用 `ask_user_question` 明确批准两项：`fix-approach` = **「加 XML 兼容 shim」**、
> `deploy-path` = **「两者都做」**（先就地补丁 + 重载查日志，再更新本机源码 / 重建 ZIP / 回写证据）。
> 本节是这次修复与验证的**证据记录**：`V2`–`V20` / `F1`–`F3` 状态仍一律不动、全部保持 `OPEN`，
> **未写任何 `CLOSED`**，G3 整体仍 `OPEN`。真加载成功不等于 G3 满足：RimWorld 仍没装、
> 手柄 DoD 11 项与真实游戏写回仍「无真值」。

- **UI 安装落地（只读核实）**：`~/homebrew/plugins/decky-mod-manager/` 于 18:50 创建，含 28 文件
  （`dist/index.js` 40295 / `dist/index.js.map` 76738 / `main.py` 10840 / `package.json` 852 /
  `plugin.json` 430 root 所有 + `py_modules/deckymod/*.py`(12) + `py_modules/registry/*.json`(9)）；
  `plugin.json` 的 `name = Decky MOD Manager` 命中 `find_plugin_folder`。ZIP 经 root 服务代劳展开，
  符合「不假设 root」。

- **启动失败（决定性问题，逐字 traceback，`h_43939d86_result.txt`）**：
  `~/homebrew/logs/decky-mod-manager/2026-11-13 18.50.41.log` 与 `journalctl -u plugin_loader` 命中
  `Failed to start Decky MOD Manager (v0.1.0)!` →
  `File "decky_loader/plugin/sandboxed_plugin.py", line 116, in initialize` →
  `File ".../decky-mod-manager/main.py", line 35` `from deckymod.engine import Engine` →
  `py_modules/deckymod/engine.py:26 from . import archive, paths, state_mutator` →
  `py_modules/deckymod/archive.py:23 from xml.etree import ElementTree as ET` →
  **`ModuleNotFoundError: No module named 'xml.etree'`**。6 个其它插件子进程存活，无本插件子进程。
  **教训**：H.4 的 B 布局「OK」用的是**系统 python3** 的 `spec_from_file_location`，只验证了
  import 路径，**没复现冻结沙盒解释器的 stdlib 子集**；真机子进程才暴露。

- **根因（4 组只读证据确证）**：Decky Loader v3.3.1 是 PyInstaller 冻结包，其 PYZ 只打了
  **部分 `xml` 包**（`xml`/`xml.parsers`/`xml.sax` 在，`xml.etree`/`ElementTree`/`ElementPath`
  全缺，PYZ TOC 421 模块数过，`h_647249ba_result.txt`）；冻结包优先于系统 stdlib →
  `import xml` 成功但 `import xml.etree` 失败（故报 `No module named 'xml.etree'` 而非 `xml`）。
  `helpers.py:9-23 get_system_pythonpaths()` 过滤掉 `sys.path[0]==''`，`sandboxed_plugin.py:91`
  只 append `py_modules/` → 系统 `/usr/lib/python3.14/xml/` 虽在磁盘却不在解释器 `sys.path`。
  `pyexpat…so`（纯 Python ElementTree 依赖的 C 扩展）在 bundle；`pyzcheck2.py` 复核
  `re/json/zipfile/hashlib/uuid/…` 全在 PYZ/BASE → **只缺 `xml.etree` 一个纯 Python stdlib 模块**。
  `etfallback.py` 屏蔽 `_elementtree` 模拟：纯 Python `ElementTree` 的 `fromstring`/`find`/
  `findall`/`ParseError`/实体解码全部可用 → shim 是一次性修复。

- **修复（本机唯一源码改动：`deckymod/__init__.py`）**：新增 `_ensure_elementtree()` 并在包级
  末尾调用（先于任何子模块 import）。逻辑：先试 `import xml.etree.ElementTree`，成功则 no-op
  （正常解释器零影响）；失败则 `import xml` 后 `xml.__path__ = list(xml.__path__)`，从
  `sys.path` + `sys.base_prefix`/`sys.prefix`/`/usr/lib`/`/usr/local/lib` 拼
  `python%d.%d/xml`（用 `sys.version_info`，**不硬编码版本号**）候选中找
  `etree/ElementTree.py` 并 append 进 `xml.__path__`；都找不到则原样重抛 ImportError。
  **无第三方依赖、不改业务解析逻辑、不动 Decky bundle、不放宽类型**。文件 68 行，
  SHA256 `5e3a51f7977a09a85af3f3a7c62f66369781433f5a40d7a33b4857edc198fc94`。

- **shim 端到端验证（Deck 系统 python3，模拟 PYZ 冻结部分包，`h_7f18cf15_result.txt` 全绿）**：
  `PRECHECK_BROKEN "No module named 'xml.etree'"` → 导入 deckymod 触发 shim →
  `XML_PATH_AFTER ['…frozen_xml_pkg','/usr/lib/python3.14/xml']` / `ET_FILE …/ElementTree.py` →
  `PARSE_ABOUT_OK author.sample | Sample & Mod | ['1.5','1.6']`（`&amp;` 解码）/ `PARSE_STATE_OK`
  / `ADD_ENTRY_OK True` / `REMOVE_ENTRY_OK True` / `BAD_XML_ERR ModError E_MANIFEST_INVALID` /
  `MAIN_IMPORT_OK True`。

- **补记（2026-11-14）：XML 解析功能等价已验证。** 上条为系统 python3 模拟；同日已在
  **真机冻结解释器**里跑 `ET.fromstring("<a><b/></a>")` + `.find("b")`，逐字
  `ET_FROMSTRING_OK root_tag='a'` / `FIND_B child_tag='b' child_is_None=False` /
  `ET_FILE=/usr/lib/python3.14/xml/etree/ElementTree.py` / `CEXT_LOADED=False`
  （纯 Python 路径可用），临时探针已完整还原并干净重载。逐字 stdout 见 §H.8。这是
  **功能等价验证**，不只是「import 可用」；§H.7 不降级为「import 可用、解析未验证」。

- **就地补丁 + 真机重载（`deploy-path=两者都做` 第一步）**：已装
  `py_modules/deckymod/__init__.py` 对 `deck` 可写 → 上传覆盖（hash 与 build tree 一致，
  `h_1dc50ebb_result.txt` 双 `PATCHED`）。经 v3.3.1 源码确认 `loader/reload_plugin` WS 路由
  （`loader.py:101,235` → `reload_queue` → `import_plugin()` 重读磁盘 `main.py` 起新子进程），
  用系统 `aiohttp` 写 `reload_client.py`（`GET /auth/token` 取 csrf → `ws://127.0.0.1:1337/ws?auth=` →
  `{"type":0,"id":..,"route":..,"args":[..]}`）：`loader/get_plugins` 返回 7 插件含本插件且未
  disabled，`loader/reload_plugin` 回 `RELOAD_TYPE 1`（无 error）。

- **真机加载成功（决定性，`h_d4bae532_result.txt`）**：重载后新增子进程
  `82204 deck Decky MOD Manager (…/main.py)`；`deckymod.log` 逐字
  `no migrations for schema 0.1.0-mvp` / `Decky MOD Manager loaded (RimWorld MVP, selection A)` /
  `plugin loaded`；近 3 分钟 `Failed to start` 计数 = **0**。**插件在冻结解释器里真的加载了。**

- **真机 RPC 全链路（`h_1b98da42_result.txt`，v3.3.1 `loader/call_plugin_method` + getattr 分发）**：
  `error_codes` → 46 码 JSON-safe 信封；`status` → `{"ok":false,"code":"E_GAME_NOT_FOUND",
  "detail":"AppID 294100 not found in 1 libraries"}`（**预期**，RimWorld 没装）；
  `recovery` / `history` → 正常空信封。确认 `getattr` 分发、JSON-safe 信封、Engine 在冻结解释器
  内运行、shim 生效均成立。

- **重建 ZIP（deploy-path 第二步）+ 回传**：`repack.py` 用显式白名单从 build tree 重建
  `/home/deck/Downloads/DeckyModManager-0.1.0-mvp.zip` = **78863 字节**，SHA256
  **`49cd684b742fa320983284c9f07b74dd66a9f8e7a9687501026d6c115d529337`**，26 文件、单顶层
  `decky-mod-manager/`；ZIP 内 `__init__.py` hash `5e3a51f…` 与已装一致、`_ensure_elementtree`
  出现 3 次、`plugin.json` 单层扫描 `SCAN … COUNT 1`、`NAME Decky MOD Manager API 1 FLAGS []`。
  `GET /api/files/download` 回传覆盖 `C:\ai\SD\DeckyModManager-0.1.0-mvp.zip`（byte-exact，
  78863 / `49cd684b…`）。**交付物与真机实装现在一致**。本机 `deckymod/__init__.py` hash 亦为
  `5e3a51f…`；本机 bundled Python `compileall` RC=0、`Ran 33 tests … OK`（shim 在普通解释器
  为 no-op，未破坏任何既有用例）。

- **状态纪律**：本节全程**未改任何 V#/F# 状态、未写 `CLOSED`、未放宽 `strict`、未假设 root、
  未关闭 SteamOS 只读、未宣称全游戏通用**。原地补丁 / 重载 / RPC 均只读或经用户批准的修复；
  重建 ZIP 用回传覆盖本地文件，未触碰游戏文件。首版 ZIP 的 hash/尺寸记录保留在本文件历史中
  不回填（见 H.5 更正条）。`V1` 仍是唯一 `CLOSED`；G3 整体仍 `OPEN`。

### H.8 端口更正 + 三项逐字证据补取（2026-11-14，非状态变更）

- **背景 / 端点更正**：此前多轮「端点不可达」的真因是**端口/IP 写错**。用户 2026-11-14
  给出 `http://{{DECK_IP}}:{{HELPER_PORT}}` 并确认「我已连好」；实测
  `PORT={{HELPER_PORT}} HTTP=200 TIME=0.041375 SIZE=305 CURL_EXIT=0`，响应体逐字
  `{"status": "success", "timestamp": 1794586126, "device": {"online": true, "hostname": "{{DECK_HOSTNAME}}"}, "service": {"running": true, "port": {{HELPER_PORT}}}, "battery": {"available": true, "name": "BAT1", "percent": 66, "status": "Charging", "is_charging": true}, "game": {"running": false, "app_id": null, "name": ""}}`；
  旧 `{{OLD_DECK_IP}}:{{OLD_HELPER_PORT}}` → `HTTP=000 CURL_EXIT=7`。Deck 侧 `ss` 亦证实 {{OLD_HELPER_PORT}} 无监听、{{HELPER_PORT}} `LISTEN`。
  助手 `C:\ai\SD\.decky-probe\deckcmd.ps1` 的 `$base` 已改为 `{{DECK_IP}}:{{HELPER_PORT}}`（终端 API 仍为
  `POST /api/system/terminal/{start,poll,stop}` + `/bin/bash -lc`，whoami=`deck`）。**教训**：
  「DNS 有记录但全端口超时」应先与用户核对端口，不要急于下「设备离线 / L2 不可达」结论。

- **证据 ① — V8 `tsc --noEmit` 逐字 stdout（`h_3cdd2a2a_result.txt`，RC=0）**：
  命令 `export PATH="$HOME/.nvm/versions/node/v22.23.2/bin:$PATH"; cd /home/deck/deckymod-build; pwd; ls -l node_modules/.bin/tsc; pnpm --version; pnpm exec tsc --noEmit; echo EXIT=$?`
  ```
  PWD:
  /home/deck/deckymod-build
  LS:
  -rwxr-xr-x 1 deck deck 1048 Nov 13 08:14 node_modules/.bin/tsc
  PNPM:
  9.15.9
  TSC:
  EXIT=0
  ```
  → cwd 为项目根、`tsc` 存在、`tsc --noEmit` 退出 0。补充全链（`h_9c388428_result.txt`，
  RC=0）：`pnpm install --frozen-lockfile` → `Lockfile is up to date, resolution step is skipped`
  / `Already up to date` / `Done in 881ms using pnpm v9.15.9` / `FROZEN_EXIT=0`；
  `pnpm run typecheck` → `TYPECHECK_EXIT=0`；`pnpm run build` → `created dist in 1.6s` /
  `BUILD_EXIT=0`；`dist/index.js` 40295 字节 SHA256
  `878eb3ce5ecc7865c2c7264ed2037c62cf18bc76253d0c2a59c6e7870f7c724f`，交付 ZIP 内
  `decky-mod-manager/dist/index.js` 经 `unzip -p | sha256sum` 得**同一 hash**（byte-exact）。

- **证据 ② — 真机冻结解释器 XML 解析功能等价（`h_132e3314_result.txt`）**：
  向**已装**插件 `py_modules/deckymod/__init__.py` 临时追加 `_et_probe()`（写
  `/tmp/et_probe_r5.txt`），经 `GET /auth/token` + WS `loader/reload_plugin` 在真机冻结子进程
  里执行，再由系统 python3 读回并 `shutil.copyfile` 原样还原、二次重载。逐字 stdout 关键行：
  ```
  SHIM_SHA=5e3a51f7977a09a85af3f3a7c62f66369781433f5a40d7a33b4857edc198fc94
  INST_SHA_BEFORE=5e3a51f7977a09a85af3f3a7c62f66369781433f5a40d7a33b4857edc198fc94
  SETUP_RC=0 OUT='PROBE_WRITTEN size=3178' ERR=''
  INST_SHA_PROBED=dae2e08847c6bfa427017ff8278b8c8fe7624a443ad7651e80aefb5c7084a44c
  RELOAD_MSG_TYPE=1 RESULT=None ERROR=None
  === FROZEN INTERPRETER ET PROBE OUTPUT (verbatim) ===
  ET_FROMSTRING_OK root_tag='a'
  FIND_B child_tag='b' child_is_None=False
  ET_FILE=/usr/lib/python3.14/xml/etree/ElementTree.py
  CEXT_LOADED=False
  === END ET PROBE OUTPUT ===
  INST_SHA_RESTORED=5e3a51f7977a09a85af3f3a7c62f66369781433f5a40d7a33b4857edc198fc94
  RESTORED_MATCHES_SHIM=True
  PLUGIN_PROCESS_COUNT=1
  PLUGIN_PROC=372519 deck     Decky MOD Manager (/home/deck/homebrew/plugins/decky-mod-manager/main.py)
  ```
  → **shim 在真机冻结解释器里不仅可 import，`fromstring`/`find` 功能等价通过**（`CEXT_LOADED=False`
  证明纯 Python 路径可用）；探针已完整还原、插件干净重载。**已在 §H.7 加「XML 解析功能等价
  已验证」，未降级为「import 可用、解析未验证」。**

- **证据 ③ — Deck 侧服务状态（`h_cfa49b38_result.txt`，RC=0）逐字**：
  ```
  === ss ===
  SS_{{OLD_HELPER_PORT}}_EXIT=1
  LISTEN 0      128          0.0.0.0:{{HELPER_PORT}}      0.0.0.0:*
  SS_{{HELPER_PORT}}_EXIT=0
  === systemctl deck-helper ===
  Unit deck-helper.service could not be found.
  === systemctl plugin_loader ===
  ● plugin_loader.service - SteamDeck Plugin Loader
     Loaded: loaded (/etc/systemd/system/plugin_loader.service; enabled; preset: disabled)
     Active: active (running) since Fri 2026-11-13 18:48:17 CST; 5h 22min ago
   Main PID: 1374 (PluginLoader)
  ```
  → {{OLD_HELPER_PORT}} 无监听、{{HELPER_PORT}} 在听；deck-helper 无独立 systemd unit（是 Decky 插件，非系统服务）；
  `plugin_loader.service` 自 18:48:17 起 active。

- **状态纪律**：本节三项均为**证据补取 / 回写**，`V8` 仍 `OPEN`（§A V8 条已更正过时
  失败原因、附全套证据，但状态字不动），`V2`–`V20` / `F1`–`F3` 仍全 `OPEN`、未写任何
  `CLOSED`，G3 整体仍 `OPEN`。未伪造输出、未把 import 成功当解析成功、未改任何 V#/F# 状态、
  未放宽 `strict`、未假设 root、未关闭 SteamOS 只读。仍无真值：RimWorld 294100 未装 →
  手柄 QAM / DoD 11 项 / 真实 `ModsConfig.xml` 写回 / V9/V14/V15/V16/V19/V20 / F1–F3。

### H.9 B 方案：冻结解释器内 合成树全链路 RPC + 故障注入（2026-11-14，非状态变更）

> **授权边界**：用户 2026-11-14 选定「B方案」——即四层测试法的 B 层：给**真机已装插件**
> 注入**临时、可逆**的测试用 env shim + 2 个 public 测试 hook，经 WS 重载后，在**真·冻结
> 解释器**里用**合成假 RimWorld 安装树**跑全链路 RPC + 故障注入，测完逐字节还原。
> 本节是**证据记录**：`V2`–`V20` / `F1`–`F3` 状态仍一律不动、全部保持 `OPEN`，
> **未写任何 `CLOSED`**，G3 整体仍 `OPEN`。**B 层 ≠ 真游戏**：RimWorld 294100 仍未安装，
> 手柄 QAM / DoD 11 项 / 真实游戏写回 / V9/V14/V15/V16/V19/V20 / F1–F3 仍无真值。

- **为什么做 B 层**：H.4 的「B 布局 OK」与本机 33 例用例都用**系统 python3**，只验证了
  import 路径 / 逻辑，没复现冻结沙盒解释器的 stdlib 子集——`xml.etree` 缺失 bug 正是这样
  漏掉的（H.7）。B 层让**真实后端代码在真实 PyInstaller 冻结子进程**里跑一遍全流程，
  补上这一层缺口。

- **三个可逆 harness（本机 `C:\ai\SD\.decky-probe\`，Deck 侧 `~/deckymod-build/`）**：
  `bt_setup.py`（造合成树 + 注入 shim/hook + 备份 main.py）、`bt_driver.py`（单 aiohttp WS
  进程，按序调 `loader/call_plugin_method`，逐字打印每个信封）、`bt_restore.py`（还原 + 二次
  重载 + hash 校验 + 删树）。三者均 `py_compile` RC=0；上传后 Deck 侧 `sha256sum` 与本机逐字一致。

- **合成树（与 `tests/test_mvp.py:96-172` 同配方）**：`/home/deck/deckymod-btest/` 下
  `Steam/steamapps/{libraryfolders.vdf,appmanifest_294100.acf,common/RimWorld/Mods/}` +
  `xdg/unity3d/Ludeon Studios/RimWorld by Ludeon Studios/Config/ModsConfig.xml`（Core
  `ludeon.rimworld` 第一、含注释与 version）+ `inbox/{testmod.zip,collide.zip,bad.zip}` +
  `outside.zip`。`resolve()` 只认 ACF+installdir 不校验真伪 → 恰好 1 hit，被当成已装
  RimWorld（真 Deck 无 Flatpak Steam、原生库无 294100）。

- **注入点与权限教训（实测）**：env shim 插在 `main.py:28 import traceback` 后、
  `:35 from deckymod.engine import Engine` 前，设 7 个 `DECKYMOD_*` / `XDG_CONFIG_HOME`
  / `DECKY_USER_HOME` / `DECKY_PLUGIN_RUNTIME_DIR` / `DECKY_PLUGIN_LOG_DIR`，全部指向合成树；
  `_bridge_env()`（`main.py:83-84`「never overwrite an explicit value」）保证它们存活。
  `bt_probe` / `bt_env` 两个 **public**（非 `_` 前缀，`loader.py:224` 拦截下划线方法名；
  `sandboxed_plugin.py:205` 用 getattr 分发）hook 插在 `async def status` 前。
  **首跑 SETUP 失败**（`h_e7c4e869_result.txt`）：`PermissionError: [Errno 13] … main.py.bt-backup`
  ——插件根是 `root:root 755`，deck 不能在其中**新建**文件；但 `main.py` 是 `deck:deck 755`
  可**原地改写**。修法：把备份放到 deck 可写的 `/home/deck/deckymod-btest-main.py.bt-backup`
  （不在插件根、也不在会被 setup 清掉的 ROOT 内）。重跑 SETUP 成功：
  `ORIG_SHA e77b3ed3…`（pristine）/ `PATCHED_SHA c48eaa7f…` / `BACKUP_SHA e77b3ed3…` /
  `SHIM_COUNT 2` / `HOOK_COUNT 2` / `SETUP_OK`。

- **bt_probe 决定性证据（`h_0d146a37_result.txt`）**：重载后 RPC 在冻结子进程内返回
  `pid 487678` / `frozen true` / `executable /home/deck/homebrew/services/PluginLoader` /
  `meipass /tmp/_MEI0000055edWaNeJ` / `et_file /usr/lib/python3.14/xml/etree/ElementTree.py`
  / `cwd /home/deck/homebrew/services`，且 `steam_root`、`xdg` 为合成树值 →
  **shim env 在真冻结解释器里生效**，XML 解析由 shim 提供的系统 ElementTree 承担。

- **全链路 + 故障注入逐字结果（`h_0d146a37_result.txt`，`PASS_COUNT 41` / `FAIL_COUNT 0` /
  `FAIL_LABELS []` / `DRIVER_DONE ALL_GREEN` / `DRIVER_EXIT=0`）**：
  - 只读：`status` → 合成 `appid 294100`、`w1_state_file` 指向合成 ModsConfig.xml、
    `activeMods` Core 第一、`recovery_needed false`；`error_codes` → `count 46`；
    `list_inbox` → 3 个 zip；`inspect(testmod.zip)` → `packageId myco.testmod`（dry-run 无写）。
  - 两阶段写：`install(...,False)` → `phase confirm`（**无写**）；`install(...,True)` →
    落 `Mods/myco.testmod/About/About.xml`（`ABOUT_BYTES` 逐字），state 不含 `myco.testmod`、
    注释保留；`set_enabled(pid,True,True)` → 追加 `<li>myco.testmod</li>`、Core 在前、注释与
    `<version>1.4.3704</version>` 均保留（surgical_line_edit 生效）；disable → 删该 `<li>`；
    `uninstall(...,False)` → `phase confirm`；`uninstall(...,True)` →
    `quarantine .decky-quarantine/<txn>/myco.testmod` 保留、Mods 里已无该目录；
    `rollback(utxn)` → `restored myco.testmod`、About 恢复；`history` 含 `MOD_UNINSTALLED`；
    `recovery pending []`；`refresh` 正常。
  - **故障注入（均在冻结解释器内命中预期码且无意外写入）**：
    `E_GAME_RUNNING`（`bt_env` 注入 `DECKYMOD_GAME_RUNNING=1`）、`E_PATH_ESCAPE`
    （`outside.zip` 不在 inbox）、`E_BAD_ARCHIVE`（`bad.zip`「bad magic: 74686973」）、
    `E_DUPLICATE`（重复 install 已管理 pid）、`E_FILE_COLLISION`（未跟踪的 `other.collide`
    目录占位）、`E_ID_INVALID`（禁改 Core）、`E_STATE_EXTERNAL`（`refresh()` 缓存 fp 后
    外部写 drifted，`detail` 逐字 `state fp changed sha256:0edfa014… -> sha256:e0b4df99…`，
    与 `test_mvp.py:560-568` 同机制）。

- **完整还原（决定性，`h_f87a8587_result.txt` + 独立复核 `h_391ec3b3_result.txt`）**：
  `RESTORED_MAIN_SHA e77b3ed3… == EXPECTED_MAIN_SHA` / `RESTORED_MATCHES_DELIVERY True` /
  `INIT_SHA_UNCHANGED True`（shim 版 `5e3a51f…` 未动）/ `BACKUP_REMOVED` /
  `BT_PROBE_AFTER_RESTORE_TYPE -1`（hook 已消失）/ `BT_PROBE_GONE True` /
  `STATUS_AFTER_RESTORE_OK False CODE E_GAME_NOT_FOUND`（**预期**：还原后回到真 env，
  RimWorld 未装）/ `TREE_REMOVED True` / `RESTORE_OK`。独立复核：插件根两文件 hash 与交付一致、
  `TREE_GONE` / `BACKUP_GONE` / `NO_BT_FILE_IN_PLUGIN`、新子进程
  `488241 deck Decky MOD Manager (…/main.py)` 存活、`deckymod.log` 尾部为干净的
  `no migrations … / Decky MOD Manager loaded … / plugin loaded`。

- **状态纪律**：全程**未改任何 V#/F# 状态、未写 `CLOSED`、未放宽 `strict`、未假设 root、
  未关闭 SteamOS 只读、未宣称全游戏通用一键装**；交付 ZIP 与本机源码均未改动（临时补丁只在
  真机已部署副本上、且已逐字节还原）；所有写操作都落在合成树内，未碰真实 Steam 库 / 真实
  `ModsConfig.xml` / 游戏进程。本节只证明**后端逻辑在真冻结解释器 + 真 Decky env 下完整可跑
  且错误码正确**，不替代真游戏的 DoD 签核。`V1` 仍是唯一 `CLOSED`；G3 整体仍 `OPEN`。

### H.10 逐项签核台账 —— 阻塞原因与所需条件（2026-11-14 Goal round 1，非状态变更）

> 本节按 Goal 完成标准「**无法签核项写明阻塞原因与所需条件**」补写，是**纯文档台账**：
> 不改任何 `status` 字、不写 `CLOSED`、不改源码、不跑合成树、不假设 root、不关 SteamOS
> 只读、不伪造真机证据、不把合成树（B 层）结果冒充真实游戏写回。G3 翻转权保留给用户。

- **本轮只读复验（`C:\ai\SD\.decky-probe\h_e846105d_result.txt`，2026-11-14）**：
  Deck `{{DECK_HOSTNAME}}` 在线、`service.port={{HELPER_PORT}}`、`game.running=false`；
  `ss -ltnp` → `LISTEN 0 128 0.0.0.0:{{HELPER_PORT}} 0.0.0.0:*`；`OPTIONS /` →
  `HTTP/1.1 200 OK` + `Access-Control-Allow-Origin: *`；已装 `main.py` /
  `py_modules/deckymod/__init__.py` hash `e77b3ed3…` / `5e3a51f7…` 与交付一致；
  `TREE_GONE` / `BACKUP_GONE` / `NO_BT_RESIDUE`（B 方案残留全清）；子进程
  `488241 deck Decky MOD Manager (…/main.py)` 存活；`NO_ACF` / `NO_GAME_DIR` /
  `NO_STATE` → **RimWorld 294100 仍未安装，A 路径仍无游戏环境**。
- **状态总览**：`V1` 唯一 `CLOSED`；`V2`–`V20` + `F1`–`F3` 共 **22 项 `OPEN`**；
  G3 整体 `OPEN`。本节不翻转任何状态。

- **Round 2 只读诊断补记（2026-11-14，`h_c7e3c83f` / `h_1b76c9b3` / `h_bb6d8151`，非状态变更）**：
  重探结论与 Round 1 一致——RimWorld 294100 仍未装（`ACF_ABSENT` / `COMMON_NO_RIMWORLD` /
  `STATE_ABSENT`）、B 残留全清（`BT_GONE` + 交付 hash `e77b3ed3…`/`5e3a51f7…`）、插件进程
  `488241` 存活、端点仍 `0.0.0.0:{{HELPER_PORT}}` + `Access-Control-Allow-Origin: *`。
  **新增 V2 机制确证**：插件子进程 `Uid: 1000 1000 1000 1000`（与终端 shell 同 uid `deck`），
  但 `/proc/488241/environ` 仍 `Permission denied`；对照 `/proc/self/environ` = `SELF_ENV_READABLE`、
  loader `1374` `Uid: 0` 与 deck-helper `1868` `Uid: 1000` 的 `environ` 同为 `DENIED`，
  `/proc/sys/kernel/yama/ptrace_scope = 1`。机制 = `sandboxed_plugin.py` 由 root `setgid/setuid`
  降权到宿主用户时内核清除 `dumpable`，`/proc/<pid>/environ` 因此对**同 uid 也**永久不可读，
  不是偶发权限问题、重试无意义。→ **表 1 V2 的「所需条件」收紧为**：唯一可行路径是
  **在插件进程内**经 RPC hook 打印 7 个 `DECKY_*` 实值（B 层 `bt_probe` 已证该通道可用），
  而非再尝试 `/proc/environ`；仍须用户显式批准注入 + 用户判定，本轮不执行。

- **Round 3 只读证据补记（2026-11-14，`h_350dc9a3` / `h_7e10b22b` / `h_56829c1d` / `h_470e1357` / `h_445b2c8f`，非状态变更）**：
  复验与 Round 1/2 一致——Deck `{{DECK_HOSTNAME}}` 在线、`service.port={{HELPER_PORT}}`、`game.running=false`；
  全盘 `find`（`$HOME/.local/share/Steam` + `/run/media`）仍 `ACF_ANY` 空 / `RIMWORLD_DIRS` 空 /
  `STATE_ANY` 空、无 RimWorld 进程（`pgrep` 仅命中本探测 shell 自身）→ **A 路径仍无游戏环境**；
  已装 `main.py` / `__init__.py` hash `e77b3ed3…` / `5e3a51f7…` 与交付一致、`BT_GONE`、子进程
  `488241 Decky MOD Manager` 存活；端点仍 `LISTEN 0 128 0.0.0.0:{{HELPER_PORT}}` + `Access-Control-Allow-Origin: *`。
  **本轮新增三类逐字真机证据（均只读、均不判定、均不翻转状态）**：
  1. **锁定模板 `90d0780…` 全量根文件**（GitHub API tree `recursive=1` 共 33 条 + raw 逐字）：
     `rollup.config.js` 全文 = `import deckyPlugin from "@decky/rollup";` +
     `export default deckyPlugin({ ... })`；`tsconfig.json` = `target ES2020` /
     `moduleResolution "node"` / `noUnusedLocals true` / `noUnusedParameters true` /
     `noImplicitReturns true` / `strict true`（无 `moduleResolution "Bundler"`、无 `ES2022`）；
     `plugin.json` = `{"name":"Example Plugin","author":"John Doe","flags":["debug","_root"],"api_version":1,...}`；
     `package.json` = `type module` + `@decky/rollup ^1.0.2` / `@decky/ui ^4.11.0` /
     `@types/react 19.1.1` / `typescript ^5.6.2`，dependencies `@decky/api ^1.1.3` /
     `react-icons ^5.3.0` / `tslib ^2.7.0`；`main.py` = `class Plugin:` 含 `add` /
     `long_running` / `_main` / `_unload` / `_uninstall` / `start_timer` / `_migration`
     （`decky.migrate_logs/migrate_settings/migrate_runtime` 范例）；`decky.pyi` 常量清单 +
     `migrate_any/settings/runtime/logs` + `logger` + `async def emit(event, *args)`；
     `defaults/defaults.txt` = ZIP 根结构 `LICENSE/README/dist/index.js/main.py/package.json/plugin.json`
     + 可选 `themes/`。→ **表 1 V4/V5/V7/V11/V12 的「已有逐字真机证据」栏据此补全模板侧原始值**；
     但 A.1 明令「只列清单不判定」，逐字段差异判定与状态翻转仍属「所需条件」中的**用户判定**，
     本轮不代判。
  2. **端点关闭机制精确化**（deck-helper 插件源码 + 设置，纯只读）：`main.py:47`
     `server_host = config.DEFAULT_SERVER_HOST`；`config.py:68`
     `DEFAULT_SERVER_HOST = "0.0.0.0"`（**硬编码全网卡绑定**）、`:71 DEFAULT_SERVER_PORT = {{OLD_HELPER_PORT}}`；
     `server_manager.py:482` `web.TCPSite(runner, plugin.server_host, plugin.server_port)`；
     `server_manager.py:393` `response.headers['Access-Control-Allow-Origin'] = '*'`（**每个响应硬编码**）；
     应用仅 `web.Application(middlewares=[cors_middleware])` —— 全 py_modules grep 无鉴权中间件
     （无 401/unauthorized/verify_token/api_key/password 守卫），唯一 403 是
     `file_operations.py:841` 某文件操作的 "Access denied"；`settings.json` 键仅
     `running/port/download_dir/auto_copy_text/prompt_upload_path/prevent_sleep_during_transfer/language`，
     `load_settings()` 只覆盖 `SETTING_PORT` 等、**从不读取 host 覆盖键** →
     **没有「改绑 127.0.0.1」的用户设置项**，早前建议中该选项不可行。→ **表 2 端点项
     「所需条件」收紧为唯一干净路径**：由用户在 Decky UI 关闭 deck-helper 服务
     （`settings.json` 的 `"running": false` / 插件 QAM 开关）或停用/卸载该插件；不需 root、
     不需改第三方源码、不需 pkill。agent 按 m03430「报告并建议关闭，不自行 pkill」**仍只报告**，
     且关闭后会失去本会话唯一命令通道，故更须用户裁决。
  3. **端口变更溯源**：`/home/deck/homebrew/settings/deck-helper-plugin/settings.json` mtime
     `Nov 14 00:07` 且 `"port": {{HELPER_PORT}}`（默认 `{{OLD_HELPER_PORT}}` 被覆盖）→ 解释此前多轮 `{{OLD_HELPER_PORT}}` 全超时而
     `{{HELPER_PORT}}` 可用；非设备离线（该结论已作废，见 §H.8）。
  **本轮未做**：不改任何 `status` 字、不写 `CLOSED`、不改源码/已部署插件/交付 ZIP、不跑合成树、
  不重跑 B、不 pkill / 不调 `utilities/disable_plugin`、不假设 root、不关只读、不伪造输出。

- **Round 4 复核补记（2026-11-14，`h_46852f7e`，非状态变更）**：本轮为自动续作轮，重新只读复验
  （不沿用旧结论）：overview `online:true hostname:{{DECK_HOSTNAME}} service.port={{HELPER_PORT}} game.running=false`；
  全盘 `find` 仍 `appmanifest_294100.acf` / `*rimworld*` / `ModsConfig.xml` 全空、无 RimWorld 进程
  → **A 路径仍无游戏环境（连续第 4 轮同一阻塞条件）**；端点仍 `LISTEN 0 128 0.0.0.0:{{HELPER_PORT}}`、
  CORS `*` 未变；已装 `main.py` / `__init__.py` hash `e77b3ed3…` / `5e3a51f7…` 与交付一致、
  `BT_GONE`、子进程 `488241 Decky MOD Manager` 存活 → B 已还原干净。
  **证据完整性复核**：§H.1–§H.10 引用的 18 个 backing stdout 文件全部存在（18/18）；本机
  `Get-FileHash` 三交付物 `DeckyModManager-0.1.0-mvp.zip` `49CD684B742FA320` /
  `main.py` `E77B3ED3F5C47CAC` / `deckymod/__init__.py` `5E3A51F7977A09A8` 均未变；
  23 个 `status` 行 = 恰好 1 个 `CLOSED`（V1）+ 22 个 `OPEN`。
  **表 2 更正**：Round 3 已确证 `config.py:68 DEFAULT_SERVER_HOST = "0.0.0.0"` 硬编码且无 host
  覆盖键 →「改绑 `127.0.0.1`」不可行；本轮把该证伪结论写回上文「端点（无鉴权）」条目
  （纯文档一致性，非状态变更）。
  **Goal 决定**：连续 4 轮同一外部阻塞条件（RimWorld 294100 未装 + 四项用户裁决未给出 +
  无新人工授权）已满足 goal-tool policy 的 `blocked` 门槛；本轮以 `update_goal(blocked)` 上报
  具体阻塞原因后停下，不再逐轮制造同质文档补记。硬约束全守：未改 `status` / 未写 `CLOSED` /
  未改源码 / 未跑合成树 / 未 pkill / 未假设 root / 未关只读 / 未伪造 / 未自行关闭端点。

**表 1 · 逐项「已有证据 / 阻塞原因 / 所需条件」**（`§H.x` 均为逐字真机 stdout 所在小节）

| Item | 已有逐字真机证据 | 阻塞原因（为何还不能签核） | 所需条件（用户 / 设备须提供） |
| --- | --- | --- | --- |
| V2 | §H.0 `decky.pyi` 常量清单与 `main.py:73-87 _bridge_env()` 吻合；homebrew grep 到 `DECKY_*` 名 | `/proc/<pid>/environ` 曾 `Permission denied`；未在插件进程内逐项读出实值 | 插件进程内打印 7 个 `DECKY_*` 实值比对 + 用户判定 |
| V3 | §H.2 锁定 `1.1.3`/`4.16.5` 声明逐字取回 + `tsc --noEmit` 零错误；§H.9 真冻结解释器 11 RPC | 类型/声明对齐 ≠ 手柄下 `showModal`/`Focusable`/OSK 交互逐项目视签核 | 装游戏后手柄会话逐项观察 + 用户判定 |
| V4 | §H.2 模板 `90d0780…` 根文件清单 + A.1 本仓库清单 | A.1 明令「只列清单不判定」，模板侧未逐项比对 | 联网逐行填 A.1 表「模板侧/判定」列 + 用户判定 |
| V5 | §H.2 模板 `plugin.json` 逐字 + 本仓库 `plugin.json`(13 行) | `name`/`flags`/`api_version`/`publish` 差异未逐字段判定 | 联网逐字段比对 + 用户判定 |
| V6 | §H.2/H.7 5/5 已装插件 ESM、改用 `@decky/rollup` 产 `export default` + `SP_*` globals、真机加载成功 | 状态字未翻转；`external` 清单差异未逐项判定 | 用户显式判定；可选与模板 `deckyPlugin({})` 对齐 |
| V7 | §H.2 `tsconfig.json` strict 下 `tsc --noEmit` 零错误 | 模板 `noUnusedLocals`/`moduleResolution node` 等差异未判定 | 联网填 A.1 #8 + 用户判定 |
| V8 | §H.8 `pwd`/`tsc` 存在/`EXIT=0`/全构建链绿/`dist` 40295 `878EB3CE…`/ZIP byte-exact/lockfile 41231 | 硬约束「V8 是否翻转由用户判定」；CI node20 未实跑、lockfile committed 未核验 | **用户显式回写 `CLOSED`**；可选 CI 复验 |
| V9 | §H.3 两份 `libraryfolders.vdf` 标准 schema、**无** `appmanifest_294100.acf` | 游戏未装 → 无真实 `installdir` 大小写真值 | 用户装 RimWorld 294100（native Steam、不开 Proton）并启动一次 |
| V10 | §H.3 两份 VDF 路径 + schema 只读实测 | 仅只读观察，未对真客户端版本逐字段判定 | 装游戏后核对真客户端 + 用户判定 |
| V11 | §H.7/H.9 `getattr` 分发、`spec_from_file_location`、`api_version>0` 实例化、真机加载 | 状态字未翻转，缺用户判定 | 用户显式判定 |
| V12 | §H.7 `no migrations`/`plugin loaded`/`plugin unloaded` 逐字日志；§H.9 还原后干净重载 | `_uninstall` 真机移除路径未跑（未卸载插件） | 用户显式判定；真机卸载观察须另授权 |
| V13 | §H.9 11 RPC `REPLY(type1)`/`ERROR(type-1)` 信封、JSON-safe、`_guard` 归一化 | 前端 `invoke()` 拒绝 promise 的 UI 表现未在手柄下确认 | 手柄会话观察错误提示 + 用户判定 |
| V14 | §H.3 `~/.config/unity3d/` 仅 noio/Team Cherry/unknown、**无** `ModsConfig.xml` | 游戏未装/未启动 → 无真 `state_file` | 装游戏并启动一次进主菜单再退出生成 `ModsConfig.xml` |
| V15 | §H.9 合成树 `surgical_line_edit` 保注释/`<version>`、真冻结解释器写回 | **最高风险**：真游戏是否接受/重写单行编辑未验证；合成树不得冒充 | 装游戏 + 真 `ModsConfig.xml` + 启动→退出→复读逐字对比 |
| V16 | §H.9 staging/quarantine 为 `Mods/` 兄弟目录、`E_STAGING_IN_MODS` 守卫通过 | 真 RimWorld 是否扫描 `Mods/` 下点号目录未验证 | 装游戏后启动观察是否把 `.decky-*` 当 mod |
| V17 | §H.9 合成树 ACF/VDF 被 `parse_vdf`/`get_installdir` 正确解析（B 层逻辑回归） | **合成树不是真客户端文件**，不得冒充真值 | 装游戏后用真 ACF/VDF 跑 `parse_vdf` 逐字输出 |
| V18 | §H.9 合成树 `RimWorld` casing 命中 | 大小写回退在 ext4 / exFAT 真机未测 | 装游戏 + 可选 microSD(F1) + 真 `os.listdir()` 回退实测 |
| V19 | §H.9 单根包裹 ZIP 解到 `Mods/<pid>/About/About.xml`（合成 mod）；本地曾修 reversed mapping bug | 真实社区 ZIP 形状未测 | 装游戏 + 真实社区 mod ZIP 若干形状实测 |
| V20 | §H.9 B 层 `E_GAME_RUNNING` 由 `bt_env` 注入命中 | 真实检测仍是保守 env 检查（代码 ⚠️ V20）；真进程检测未验证 | 用户确认真检测机制（不靠 sudo/root）+ 真运行时拒绝写实测 |
| F1 | §H.3/h_e846105d 无 `/dev/mmcblk*`、`/run/media` 空 | 此 Deck 无 microSD → exFAT/`fchmod`/`E_FS_NO_POSIX` 无真值 | 插入 microSD 后记录 mount/FS/errno |
| F2 | §H.3 `/home` ext4 单 FS；合成树同 FS | 无跨设备场景 → `EXDEV(18)` 无真值 | 游戏装 microSD + Decky data 在内置 SSD 时实测 `os.replace` |
| F3 | §H.3 flatpak list 无 `com.valvesoftware.Steam` | 此 Deck 无 Flatpak Steam → 拒绝分支无对象 | 装 Flatpak Steam 的环境实测 `E_FLATPAK_PERMISSION`（MVP 本就拒绝，非必须） |

**表 2 · 其余签核对象**

- **手柄 DoD 11 项**（[ACCEPTANCE.md](ACCEPTANCE.md) §5.1）：证据 = §H.9 后端 11 RPC 全绿（**后端逻辑层**），
  **不是**手柄交互证据。阻塞 = 无游戏 + 无手柄验收会话 + 前端 `showModal`/`Focusable`/OSK 交互未编译
  验证（虽 `tsc` 零错误 + ESM 真机加载）。所需 = 装 RimWorld + 用户手柄逐项验收会话 + 用户显式判定。
- **B 路径**：已于 m03032「B方案」批准下执行完毕（§H.9 41 绿）并**逐字节完整还原**（hash 一致、无残留、
  hook 消失、干净重载）。Goal 前提「B 待执行」是旧快照。重跑须**逐项批准源码改动**（硬约束），当前无该
  授权 → **本轮不重跑**。
- **端点（无鉴权）**：本轮复验仍 `0.0.0.0:{{HELPER_PORT}}` + CORS `*` + 跨 LAN 无 token `HTTP=200`。**张力**：
  Goal 硬约束「端点若无鉴权应关闭」与 m03430 直接指令「报告并建议关闭，不自行 pkill」冲突；按
  「当前轮显式请求优先 + 不擅自改动用户设备服务」只报告。所需 = 用户裁决授权：**Decky UI 关服务 /
  停用 / 卸载 deck-helper**（Round 3 `h_470e1357` / `h_445b2c8f` 已确证 `config.py:68`
  `DEFAULT_SERVER_HOST = "0.0.0.0"` 硬编码且 `load_settings()` 无 host 覆盖键 →
  **「改绑 `127.0.0.1`」不可行，此处更正为证伪**；不需 root、不改第三方源码）；agent 不 pkill、
  不调 `utilities/disable_plugin`；且关闭后本会话将失去唯一命令通道，更须用户裁决。
- **V2 所需条件补充（Round 2 机制确证）**：`/proc/<pid>/environ` 因降权后 `dumpable` 被清（见上文
  Round 2 只读诊断补记）对同 uid 也不可读，**唯一可行**是在插件进程内经 RPC hook 打印实值；
  重试 `/proc/environ` 无意义。B 层 `bt_probe` 已证该通道可用，但仍须用户显式批准 + 判定。
- **G3 整体**：阻塞 = 证据不齐（A 路径未跑、22 项状态未翻转、V8 待用户判定、端点待裁决）。所需 =
  用户按完成标准「在证据齐全后判定」；**agent 不自行翻转、不写 `CLOSED`**。

**本轮处理**：台账已落地；Goal 保持 `active` 留给下一轮（未 `complete`、未 `blocked` —— round 1 且
已有具体进展）。四项用户裁决（端点关闭授权 / V8 翻转 / B 重跑逐项批准 / 路径 A 游戏环境）仍全部
保留给用户。

---

## How G3 is closed

1. ~~Pin V1 (commit + version) and record them.~~ **DONE (2026-11-12)**: V1 is
   `CLOSED` from user-supplied C1/C2/C3 evidence; see §A above. (The exact-version
   write-in to `package.json` is a RUNBOOK §4/§5 follow-up, not a V1 status change.)
2. Run V2–V8 (toolchain + frontend build) on a machine with registry access; commit
   `pnpm-lock.yaml`; get `tsc --noEmit` + `rollup` green.
3. On a real Steam Deck, work through V9–V20 and F1–F3; record the observed values
   (paths, FS type, errno, `installdir` casing) in this file and flip each `status`
   to `CLOSED` with a date and the device/versions used.
4. Only then re-run [ACCEPTANCE.md](ACCEPTANCE.md) DoD end-to-end on the device.

Until steps 2–4 are done, the correct status of this build is:
**"implemented + backend self-tested on a synthetic tree; V1 version locking CLOSED;
V2–V20 / F1–F3 device & build verification OPEN; frontend unverified."**

> **补记（2026-11-13 晚，非状态变更）**：上面「frontend unverified / device & build
> verification OPEN」是撰写时的历史快照。事实更新：frontend 已在联网 Deck 上
> `tsc --noEmit` 零错误 + `@decky/rollup` 产出 ESM bundle（§H.2），并已在真机冻结
> 解释器里加载成功、4 个只读 RPC 全链路通过（§H.7）。但**状态字仍按授权保持 `OPEN`**，
> 且 frontend 的**手柄 / QAM 行为**、真实游戏写回、DoD 11 项仍无真值。G3 整体仍 `OPEN`。
>
> **补记（2026-11-14，非状态变更）**：§H.8 补取了 V8 逐字 `tsc` 证据、冻结解释器
> `ET.fromstring`/`find` 功能等价证据与 Deck 侧服务状态；§H.9 的 B 方案又进一步在真冻结
> 解释器 + 真 Decky env 下用合成树跑通**全部 11 个 RPC + 7 类故障注入**（41 项全绿），
> 测完逐字节还原。二者都只是**证据 / 逻辑回归**，均非 device-side 真游戏 DoD 签核：
> RimWorld 294100 仍未安装，V9/V14/V15/V16/V19/V20、F1–F3、手柄 QAM 11 项、真实
> `ModsConfig.xml` 写回仍无真值。**状态字一律未动**：`V2`–`V20` / `F1`–`F3` 全 `OPEN`、
> 未写任何 `CLOSED`，G3 整体仍 `OPEN`；`V1` 仍是唯一 `CLOSED`。

---

## §I — 星露谷 / SMAPI detect-only 验收对象（selection B，2026-11-14）

> **本节为新建的独立验收对象**（m03703「B」+ m03746「全部批准」，19 项 #1–#19 按
> A→E 执行）。§A–§H 与 `## How G3 is closed` 全部**原样保留、状态字一律未动**；
> 本文件历史上任何 `V#`/`F#` 状态行、快照表、补记均**不回填**。**原 G3
> （RimWorld 294100）仍 `OPEN`、未写 `CLOSED`、NOT SHIPPABLE**；本节不构成对它的签核。
> 对应 DoD 见 [ACCEPTANCE.md](ACCEPTANCE.md) PART I；PART II 是原对象历史逐字记录。

### §I.1 — 改动清单落地（19 项，按 A→E 分组）

| 组 | 项 | 落地文件 | 状态 |
| --- | --- | --- | --- |
| A | #1–#3 注册表 | `registry/games/stardew.json`（新建：appid 413150 / `manifest.json` / UniqueID / `file_drop` / `state_file:null` / allow `.dll,.so,.dylib` / 8 reject_extensions / detection_only / external-manager markers）；`registry/registry.json`（`version 0.2.0-stardew` + `active_game:stardew` + rimworld→`planned` + `max_enabled_games_in_mvp:1`）；`registry/loaders/smapi.json`（`status:detect_only` / `install_policy:NEVER_INSTALL` / `launch_options_policy:MUST_ALREADY_BE_SET_BY_USER`） | **DONE (LOCAL-OK)** |
| B | #4–#9 后端 | `deckymod/registry.py`（`_pinned_game()` + `active_descriptor()` + `appid_for()`）；`deckymod/paths.py`（`resolve(..., no_state_file=False)`）；`deckymod/errors.py`（4 新码 + 5 中性化）；`deckymod/file_drop.py`（新建）；`deckymod/archive.py`（`forbidden_ext=None` 参数）；`main.py`（`_make_engine()` 分派 + `_selection_label()`）；`tests/test_mvp.py` 顶部 `DECKYMOD_GAME_ID=rimworld` pin；**原 `deckymod/engine.py` 原封不动** | **DONE (LOCAL-OK)** |
| C | #10–#12 安全姿态 | `manifest.json` 解析 + 仅 `.dll/.so/.dylib` 三类放行；`.mm_deployed`/`Mods_Core` → `E_EXTERNAL_MANAGER` 只读零破坏；`E_LOADER_MISSING`/`E_LAUNCH_OPTIONS_MISSING` 前置；不装 loader / 不改启动选项 / 不写 Proton pfx | **DONE (LOCAL-OK)** |
| D | #13–#15 前端 8 文件 | `src/types.ts`（重写：`w1_state_file:string｜null` / `StateInfo.strategy` / `ModMeta.badges` 可选 / `ConfirmData.targets: Record<string,string｜null>`）；`src/api.ts`（形参 `uniqueId`，RPC 字符串与位置参数不变）；`src/components/ConfirmModal.tsx`（过滤 null W1）；`src/components/ModRow.tsx`（`canToggle:boolean` → 显 `Installed`）；`src/index.tsx`（`isFileDrop()` + 标题/检测行/READ-ONLY 横幅/UniqueID/`install≡enable` 文案/toggle 守卫/`confirmRollback` 显式类型对象）；`Modal.tsx`/`ErrorView.tsx`/`ImportBox.tsx` 未改 | **DONE（源码）；DEVICE 构建待 F 组** |
| E | #16–#19 测试/文档/构建 | `tests/test_stardew.py`（13 合成树用例）；`docs/ACCEPTANCE.md` PART I（§B.1 DoD 11 项、§B.2 50 码、§B.3 硬约束、§B.4 签核清单）；`docs/VERIFICATION.md` §I（本节）；Deck 上 `tsc --noEmit` + `rollup -c` → 新 `dist/index.js` → 重打 ZIP → 真机加载 | **部分 DONE；#19 待执行** |

### §I.2 — 架构与 wire 契约

- **分派**：`main.py::_make_engine()` 读 `Registry().active_descriptor()[0]`；`stardew` →
  `StardewEngine`（`deckymod/smapi.py`，`GAME_ID="stardew"`），否则 → 原 `Engine`。
  生产默认 `active_game:"stardew"`；33 个 RimWorld 历史用例靠
  `DECKYMOD_GAME_ID=rimworld` pin 保持不变（**41 绿真机 RimWorld 路径字节级不动**）。
- **两引擎共享**：11 个位置参数 RPC（`status` / `list_inbox` / `inspect` / `history` /
  `refresh` / `recovery` / `error_codes` / `install` / `set_enabled` / `uninstall` /
  `rollback`）、同一 JSON-safe `ok()`/`err()` 信封、`packageId` 作为共享 wire 键
  （SMAPI 侧取 `UniqueID`）。前端按 `status().state.strategy === "file_drop"` 分支，
  **不新增 RPC、不放宽 `strict:true`、不加 `@ts-ignore` / `as any`**。
- **file_drop 语义**：无 W1 state file（`paths.w1_state_file=null`）、无
  `ModsConfig.xml` / `<activeMods>` / Core；`install ≡ enable`（`Mods/<dirName>/manifest.json`
  存在即启用）；`set_enabled` 因 `enable_disable=false` 返回 `E_CAPABILITY_DISABLED`；
  `uninstall` 把目录 `os.replace` 进 `GAME_ROOT/.decky-quarantine/<txn>/`（不删）；
  `rollback` 用 `os.replace` 回 `Mods/`。staging/quarantine 均为 `Mods/` 兄弟目录，
  不在其中（`E_STAGING_IN_MODS`）。
- **错误码**：50 = 原 46 + 4 新码（`E_LOADER_MISSING` / `E_LAUNCH_OPTIONS_MISSING` /
  `E_EXTERNAL_MANAGER` / `E_MANIFEST_UNSAFE`）；4 个 `rollback=True` 不变
  （`E_VERIFY_FAILED` / `E_OP_FAILED` / `E_RECOVERY_PENDING` / `E_ROLLBACK_FAILED`）。
  5 个原码文案中性化（去 "RimWorld / AppID 294100 / RimWorld MVP only"）。
- **不变**：`deckymod/__init__.py` 的 `_ensure_elementtree()` XML shim 保留；
  无新依赖；三条硬约束（不关只读 / 不假设 root / 不宣称全游戏通用一键装）原样保住。

### §I.3 — 本机自测证据（逻辑回归，非 device-side DoD）

| 检查 | 结果 |
| --- | --- |
| `python -m unittest discover -s tests -v` | **Ran 46 tests in 1.030s OK**（33 RimWorld 历史回归 + 13 新 Stardew 合成树） |
| `error_codes().count` | `50`（= `len(ERRORS)`） |
| `compileall -q deckymod main.py` | `RC=0` |
| 4 个 registry JSON（`registry.json` / `games/rimworld.json` / `games/stardew.json` / `loaders/smapi.json`） | `json.load` 全 OK |
| `ACTIVE` / `ENABLED` / `APPID_STARDEW` / `SMAPI_FORBIDDEN` / `ENGINE` | `stardew` / `['stardew']` / `413150` / 8 类 / `StardewEngine` |
| full suite | `exit 0` |

> 上述均为本机合成树**逻辑回归**；不替代真实 SMAPI 载入、真机 11 项手柄、
> `.mm_deployed` 共存、真实 `manifest.json` 写回、真实 errno 故障注入的真值。
> 排错链（记录教训）：`ModuleNotFoundError: deckymod` → 本机须设
> `PYTHONPATH=C:\ai\SD`；`E_CAPABILITY_DISABLED: 2 enabled games > max 1` 根因是
> `enabled_games()` 读描述符文件自身 `status` 而非 registry.json metadata → 把
> `registry/games/rimworld.json` 两处 `"status":"enabled"` 也改为 `"planned"`
> （pin 分支绕过该检查，33 用例不受影响）；`tempfile.mkdtemp` 0o700 DACL → 测试改
> 用 `os.makedirs`；`main.Plugin().error_codes()`/`status()` 是 coroutine → 测试用
> `asyncio.run(...)`；`file_drop.check_launch_options()` 在合成树里返回 `unknown`
> 是设计内非致命值。

### §I.4 — 新验收对象台账（一律 `OPEN` / 待执行）

| 编号 | 检查项 | 状态 |
| --- | --- | --- |
| S1 | F 组 Deck 构建：`pnpm install --frozen-lockfile` + `tsc --noEmit`（strict 零错误）+ `rollup -c`（官方 `@decky/rollup`）→ 新 `dist/index.js` | **OPEN / 待执行** |
| S2 | 重打 ZIP + 真机加载：`status()` 返回 `game.appid=413150` / `paths.w1_state_file=null` / `state.strategy="file_drop"` | **OPEN / 待执行** |
| S3 | §B.1 全部 11 项手柄操作（QAM / 焦点 / B 可关闭 / busy / 离开重开） | **OPEN / DEVICE** |
| S4 | 真机检测行准确（SMAPI 在位 / 启动选项已设 / external-manager 标记 / `unknown` 非致命） | **OPEN / DEVICE** |
| S5 | 只读模式实测：置 `.mm_deployed` 或 `Mods_Core` → `read_only=true` + READ-ONLY 横幅 + op#3/#6/#7 全 `E_EXTERNAL_MANAGER`、零文件改动 | **OPEN / DEVICE** |
| S6 | 真实 SMAPI 模组 ZIP（单根 `strip_single_root` + `manifest.json` UniqueID + `.dll`）导入后游戏内确实载入 | **OPEN / DEVICE** |
| S7 | §B.2 错误提示抽检 10 码（手柄可读、无 traceback、constraint 类不含 `sudo` / `steamos-readonly disable` / `flatpak override`） | **OPEN / DEVICE** |
| S8 | 真实 errno 故障注入：`E_READONLY_FS` / `E_NO_SPACE` / `E_CROSS_DEVICE` / `E_GAME_RUNNING` | **OPEN / DEVICE** |
| S9 | 端点 `http://{{DECK_IP}}:{{HELPER_PORT}}` 无鉴权 + CORS `*` 的关闭授权 | **用户裁决；未 pkill / 未 disable_plugin** |
| S10 | `V8` 状态翻转（证据已齐，是否 `CLOSED` 由用户判定） | **用户裁决；仍 `OPEN`** |

### §I.5 — 状态纪律声明

- 本轮**未翻转任何 `V#`/`F#` 状态字**、**未写任何 `CLOSED`**、**未回填**历史快照表；
- 全局台账仍是 `1 CLOSED + 22 OPEN`（`V1` 唯一 `CLOSED`；`V2`–`V20` / `F1`–`F3` 全 `OPEN`）；
- **G3 整体仍 `OPEN`**（RimWorld 294100 未安装，V9/V14/V15/V16/V19/V20、F1–F3、
  手柄 QAM 11 项、真实 `ModsConfig.xml` 写回仍无真值）；
- PART I / S1–S10 与 §A–§H 之间**无状态传染**：新对象全 `OPEN`，历史对象状态不动。

### §I.6 — 诚实边界 / 未决事项

- 前端 8 文件在本机**未编译、未类型检查**（无 `node_modules` / `typescript`）；F 组
  Deck 构建是唯一可信的 `tsc --noEmit` 证据来源；构建产物 `dist/index.js` 在 S1 完成
  前仍为旧 RimWorld bundle（`40295 B` / `878eb3ce…`），`pnpm-lock.yaml` 亦未因本次
  源码改动重算。
- 三条硬约束原样保住，另加 4 条 detect-only 红线：不装 SMAPI / 不改启动选项 /
  不写 Proton pfx / 不自动改第三方 mod manager 部署。
- 原 G3 的签核仍被 Stardew 转向阻塞；`goal-6e8c3f94` 仍 `blocked` / `disarmed`
  (rev2)；m03746 是新的直接人类工作线，未 rearm 旧 goal。
- 端点关闭（S9）与 `V8` 翻转（S10）保留给用户裁决；本轮只报告、不执行。

### §I.7 — 真机证据回写（additive，2026-11-14；状态字一律不动）

> 本节只是**事实记录**。所有数据来自 Deck（hostname {{DECK_HOSTNAME}}，SteamOS 3.9.5 holo，
> 经 deck-helper 终端 API `http://{{DECK_IP}}:{{HELPER_PORT}}`），是**终端/后端层**真值：
> 直接 `python3` 调用 `StardewEngine`，**无 Decky runtime、无 QAM、无 Game Mode UI、
> 无手柄**。因此它**不构成 §B.1 的 11 项手柄 DoD、不构成真实 SMAPI 游戏内载入、
> 不构成已部署插件的加载**；不勾选 §B.4 任何 checkbox、不翻转 S1–S10 任何状态字、
> 不写任何 `CLOSED`。`V1` 仍是唯一 `CLOSED`，G3 仍 `OPEN`。

**（1）F 组 Deck 严格构建（S1 的事实结果，状态字仍留 `OPEN`）**

| 检查 | 结果（精确值） |
| --- | --- |
| 同步包 | `C:\ai\SD\.decky-probe\sync.tar.gz` 41 文件 / 91465 B → `/home/deck/deckymod-build`（HTTP 200，sha `990cba5f…`）；`tar -xzf` `RC=0` |
| `tsc --noEmit -p tsconfig.json`（Deck，strict:true） | **`TSC_EXIT=0`**（D 组前端 8 文件在 strict 下零类型错误；proof：confirmRollback 显式 `Record<string,string\|null>` 修复有效） |
| `rollup -c`（官方 `@decky/rollup 1.0.2`） | **`ROLLUP_EXIT=0`** `"created dist in 2.3s"` |
| 新 `dist/index.js` | **44934 B / SHA256 `80cde69d9489b6fda1fea2a389b459856eabc9e2d595cf95ce7b58559fca4ffd`**（旧 RimWorld 40295 B / `878eb3ce…`）；`dist/index.js.map` 82327 B；head `const manifest = {"name":"Decky MOD Manager"};` + `const API_VERSION = 2;` |
| 下载回本机 | `C:\ai\SD\dist\index.js` HTTP 200 / 44934 B / `80cde69d…` 与 Deck byte-exact；grep 命中 23 处 Stardew 文案（`file_drop` / `Minimum SMAPI API` / `Installed & enabled ... (file_drop: install == enable)` / READ-ONLY 横幅 / 标题三元 «Stardew Valley / SMAPI (detect-only)»） |
| `pnpm install --frozen-lockfile` | **`FROZEN_EXIT=0`**（plain；pnpm v12.5.1，+124 packages）。`--offline` 曾 `ERR_PNPM_NO_OFFLINE_META`（缺元数据缓存，**非** lockfile 问题，已打印 "Lockfile is up to date"）；`sha256sum pnpm-lock.yaml` = `7bb14e8ac231eac6a4da340b31a5d79aa2d4e5f7868fe3b8ccfe2ab65f12bde6` 未变 |
| `repack.py`（显式白名单 ZIP） | **ZIP 96874 B / SHA256 `a22abe3ed5e71d1dca5bd850d09816b3205bb6ad70e4ce0e3e0e16335148d58c` / 29 entries**（旧 78863 B / `49cd684b…` / 26）；新增 `smapi.py` / `file_drop.py` / `games/stardew.json`。下载回 `C:\ai\SD\DeckyModManager-0.1.0-mvp.zip` byte-exact；本机 zipfile 验证 `dist/index.js`=44934 B/`80cde69d…`、`stardew.json` appid 413150 |
| 已部署插件 | `/home/deck/homebrew/plugins/decky-mod-manager` = root:root 755 / `WRITABLE=no`，其 `dist/index.js` 仍 `878eb3ce…`（旧 RimWorld）→ **不假设 root / 不热替换 / 未动已部署插件**；新 ZIP 在 Deck `Downloads/` 供用户经 Decky UI 装载 |
| Deck 真 Linux Python 后端 | `python3 --version` = **3.14.6**；`PYTHONPATH=/home/deck/deckymod-build python3 -m unittest discover -s tests -v` → **`Ran 46 tests in 0.267s OK`**；`compileall -q deckymod main.py` `RC=0`；`len(ERRORS)`=**50**；`active_descriptor()[0]=stardew` / `enabled_games()=['stardew']` / `appid_for("stardew")=413150` |

**（2）真机只读 `status()` 探针（`C:\ai\SD\.decky-probe\h_c86c39d0_result.txt`）**

- `STATUS_OK True` / `STATUS_ERR None` / `PROBE_EXIT=0`；`DECKYMOD_STEAM_ROOT=/home/deck/.steam/steam` 且清 `DECKYMOD_GAME_ID`。
- `game` = `{"appid":413150,"name":"Stardew Valley","platform":"linux-native","status":"enabled"}`。
- `paths`：`w1_state_file:null`、`w2_mod_root=/home/deck/.local/share/Steam/steamapps/common/Stardew Valley/Mods`、`quarantine_root=.../.decky-quarantine`、`staging=.../.decky-staging`、`flatpak:false`、`fs_posix:true`。
- `state`：`strategy:"file_drop"`，**25 个真实 SMAPI mod 目录**（Automate / ContentPatcher / ChestsAnywhere / GenericModConfigMenu / StardewHack / TractorMod / «[CP] Immersive Spouses» 等），**`external_manager:true` / `loader_detected:true` / `launch_options:"set"` / `read_only:true`** → Amethyst `.mm_deployed` 标记正确触发零破坏只读门禁。
- `capabilities`：local_import / detection_only / uninstall_quarantine / rollback / gamepad_only / history_refresh = true；enable_disable / atomic_state_write = false；loader_install / launch_option_edit / dll_override / proton_prefix_write / exe_installer / network_download / workshop / load_order_solver / dependency_solver / requires_root / requires_readonly_toggle / universal_one_click 全 false。
- 真值结论：AppID 413150 在**真实** Steam library 解析正确、SMAPI 检测正确、启动选项检测为 `"set"`、外部管理器存在时默认姿态正确置为 READ-ONLY。

**（3）真机零破坏门禁证明（`C:\ai\SD\.decky-probe\h_637e6c30_result.txt`，修正后）**

- 快照真实 `Mods/` 树签名 → 调 `install("__nonexistent_probe__.zip")` / `uninstall("probe.nomod")` / `rollback("no-such-txn")` 三个写 RPC → 复算快照。
- `RESULTS`：三者全 `ok:false` / `code:"E_EXTERNAL_MANAGER"` / `message="Another mod manager owns this Mods folder (symlink deployment detected). Read-only mode: ..."` / `detail="external mod manager markers in .../Mods; read-only mode"`。`_check_write_allowed(r)` 在 `smapi.py:232` 先于 `_validate_import_path` / `inspect_mod` / `journal.begin` / 任何 fs 写。
- `BEFORE_MODS_SIG` = `AFTER_MODS_SIG` = `cb495ff9181a28b27f3d3e2719708757233d8586a504ab0362be5778615fecf7`；`MODS_UNCHANGED True` / `STAGING_UNCHANGED True` / `QUARANTINE_UNCHANGED True` / `ALL_EXTERNAL_MANAGER True` / **`ZERO_DAMAGE True`** / `PROBE_EXIT=0`。
- 排错链（探针 artifact，非产品 bug）：首跑 `h_497c42ba_result.txt` 误读信封键 `"error"`（实际是 `"code"`，见 `deckymod/envelope.py:36-44`）→ `ALL_EXTERNAL_MANAGER`/`ZERO_DAMAGE` 假 False；改读 `"code"` 后全 True。零写入证据两次一致。

**（4）仍未覆盖（诚实边界，状态字不动）**：§B.1 11 项手柄/QAM/焦点/B 可关闭、真实 SMAPI ZIP 导入后游戏内载入、已部署插件经 Decky Loader 加载（部署目录未替换）、真实 errno 故障注入（`E_READONLY_FS`/`E_NO_SPACE`/`E_CROSS_DEVICE`/`E_GAME_RUNNING`）、§B.2 手柄可读错误抽检 —— 仍 `OPEN / DEVICE`，由用户与真机 UI 完成；本轮不勾选、不代替。

---

## §J — 星露谷「中文可用 + 只读实用 + 多游戏可扩展」实施证据（selection B Steps 1–4，2026-11-14）

> 本节是 `goal-221c8ac6` (**rev3**, active/armed；rev2 为实施期、rev3 为用户追加
> 「团队分工合作」后的当前权威修订）的事实记录，承 m04575 五步路线 +
> m04651 批准方案。范围 = **Steps 1–4**（汉化 / 只读 mod 列表 / ManifestParser 抽象 /
> 第二游戏可插拔）；**Step 5（写回闭环 + 故障注入）明确 `OUT OF SCOPE`**。
>
> **状态纪律（一律不动）**：未翻转任何 `V#`/`F#`、未写任何 `CLOSED`、未回填历史快照表；
> `V1` 仍是唯一 `CLOSED`；`V2`–`V20`/`F1`–`F3` 全 `OPEN`；**G3 整体仍 `OPEN` /
> `NOT SHIPPABLE`**（RimWorld 294100 未安装）。本节**不新增 CLOSED、不勾选 §B.4 任何
> checkbox、不把只读/合成树结果冒充写回签核**。`goal-6e8c3f94` 仍 `blocked`/`disarmed`
> (rev2)，本节是新的直接人类工作线，未 rearm 旧 goal。
>
> **证据类别标注**：每条证据标明 `DEVICE`（Deck 真机终端/后端层）、`SYNTH`（合成树
> unittest）、`BUILD`（Deck 严格构建）或 `LOCAL`（本机校验）。**`DEVICE` 证据均为
> 终端/后端层**：直接 `python3` 调用 `FileDropEngine.status()`，**无 Decky runtime /
> 无 QAM / 无 Game Mode UI / 无手柄** → 不构成 §B.1 的 11 项手柄 DoD，不构成已部署
> 插件经 Decky Loader 加载，QAM 中文目视与手柄可用性仍 `OPEN / DEVICE`，需用户经
> Decky UI 装载新 ZIP 后目视确认。

### §J.1 — 连通性门禁与端点曾失联（诚实前提，非状态变更）

- 方案 §1 设「{{HELPER_PORT}} 可达」为设备取证前置门槛。本轮开始时
  `http://{{DECK_IP}}:{{HELPER_PORT}}` 一度 `HTTP=000`（curl 28 超时）→ 按门禁**不伪造设备
  证据**，先做全部本地可验证切片（Steps 1–4 后端 + i18n + 前端接线 + Step 4 合成树
  用例 + 本地 unittest/compileall/JSON 对齐）。
- 端点恢复后取证：`curl http://{{DECK_IP}}:{{HELPER_PORT}}/` → **`ROOT_HTTP=200`**（来自当轮
  终端会话的 curl 退出码，非持久化文字产物）；`/api/system/terminal/start` POST
  成功、`whoami=deck`，逐字见 `h_6ec26cf8_result.txt` / `h_759318d8_result.txt` /
  `h_03ddfc5c_result.txt` 等 Deck 终端结果文件（这些文件本身即恢复后会话的逐字输出）。
  此后所有 `DEVICE`/`BUILD` 证据在恢复后的会话取得。**诚实补充**：端点在后续再次失联
  —— `C:\ai\SD\.decky-probe\h_endpoint_final_result.txt` 记录 `ROOT_HTTP=000 LASTEXIT=28`
  （curl 28 超时），故不对「端点当前仍可达」作断言。
- 教训：PowerShell 单引号 `-d '{"command":...}'` 会发坏 JSON（`Expecting property
  name...`）；body 须写入 `C:\ai\SD\.decky-probe\start_body.json` 再 `--data-binary
  @file`。`upload.ps1`/`deckcmd.ps1` 必须经
  `[scriptblock]::Create((Get-Content -Raw ...))` 调用（直接 `&` 触发
  PSSecurityException）。`curl` 下载用完整字面 URL + `-g`（`--globoff`），变量拼接
  `$base?path=...` 会 `curl: (3) URL rejected: Bad hostname`。

### §J.2 — Step 1 汉化（i18n）：`LOCAL` + `BUILD` + `DEVICE`（待 QAM 目视）

- 新建 `src/i18n/en.json` + `src/i18n/zh-CN.json`（初版各 **206 键** → 团队复核补
  2 键后 **208 键**；含 **50 个 `ERR_E_<CODE>` 错误码键全覆盖**（另 `ERR_TITLE` /
  `ERR_BACKEND_UNREACHABLE` 两个展示用键，共 52 个 `ERR_` 前缀键）+ UI 主路径 +
  `MODLIST_*`）+ `src/i18n.ts`
  （`t(key, fallback?, vars?)` 查找链 `zh-CN → en → fallback → key`；`errorText(code,
  englishMessage)`；`isChinese()` 用 `navigator.language`；`format()` 替换占位符）。
  **零硬编码 UI 文案**：`src/index.tsx`（标题/READ-ONLY 横幅/检测行/Constraints/6 个
  ButtonItem/Installed/OSK/toast/confirm/rollback 等）、`src/components/{Modal,
  ConfirmModal,ModRow,ImportBox,ErrorView}.tsx`、`src/api.ts`（`bridgeError`/
  `envelopeError` 走 `errorText`）全量接 `t()`；`definePlugin` 的 name/icon 是插件标识
  非 UI 文案，保留。
- **构建方案（决定性）**：`grep pnpm-lock.yaml` → `@rollup/plugin-json@6.1.0
  (rollup@4.68.2)` 已是 `@decky/rollup 1.0.2` 传递依赖 → 走**分支 A**
  （`import en from "./i18n/en.json"; import zhCN from "./i18n/zh-CN.json";`），
  **不新增依赖、不改 `package.json`/`rollup.config.js`、不重算 `pnpm-lock.yaml`**（批准
  方案的分支 B 未触发）。`tsconfig.json` `strict:true` / `resolveJsonModule:true` 不放宽。
- **校验**：`C:\ai\SD\.decky-probe\validate_i18n.py` → 初版 `EN_KEYS 206 / ZH_KEYS 206`；
  **团队独立复核后补 2 键**（`RECOVERY_SUBTITLE` / `ROLLBACK_SEE_STATUS`）→ 最终
  `EN_KEYS 208 / ZH_KEYS 208` / 双向 diff 空 / `ERROR_CODES 50` / `MISSING_ERR_*` 空 /
  `USED_KEYS 156` / `USED_BUT_MISSING_*` 空 / 仅 `EMPTY_LINE` 为空（故意）。`BUILD`：`tsc --noEmit -p
  tsconfig.json` → **`TSC_EXIT=0`**（strict 零错误，`h_03ddfc5c_result.txt` 逐字）；`rollup -c` →
  **`ROLLUP_EXIT=0`**（`h_03ddfc5c_result.txt` 逐字含 `created dist in 2.2s` 带色行）。Bundle 内容抽查（`h_759318d8_result.txt`）：
  `BUNDLE_ZH_CONSTRAINTS=1`（「仅本地导入」）、`BUNDLE_ZH_TITLE=2`（「星露谷」）、
  `BUNDLE_MODLIST=5`、`BUNDLE_ERR_PREFIX=4`。
- **仍 `OPEN / DEVICE`**：QAM 主路径与错误提示的中文目视、手柄下可读性。需用户经
  Decky UI 装载新 ZIP 后确认；本节不代替。

### §J.3 — Step 2 只读 mod 列表与依赖提示：`LOCAL` + `SYNTH` + `DEVICE`

- 后端 `status().state.mods` 从 `[{dir}]` **加性扩展**为
  `[{dir, uniqueId, name, version, author, dependencies, missing_dependencies,
  parse_error?}]` + `state.duplicate_ids: [[uid,[dirs]]]` +
  `state.missing_dependencies: string[]`，由新 `deckymod/manifest.py` 的
  `scan_installed_mods(mod_root, mod_package)` 只读枚举：跳过点目录/非目录；单目录坏
  manifest 隔离为 `parse_error`（`E_MANIFEST_MISSING`/`E_MANIFEST_UNSAFE`/
  `E_MANIFEST_INVALID`）**绝不让整个 status 失败**；零写入、无 `journal.begin`、
  零破坏（`_tree_sig` 前后一致）。
- 前端 `src/types.ts` 新增 `ModListEntry` / 扩展 `StateInfo`；`src/index.tsx` 新增
  `openModList()`（`showListModal`，每行 `Name · Version · Author`，缺依赖/重复
  UniqueID/parse_error 显提示，只读 `showInfo` 详情，**无写按钮**），Actions 区加第 6 个
  `ButtonItem`（`MODLIST_BTN`），全走 `t()`。
- **`DEVICE` 真机只读 status()（`h_29ec034e_result.txt` 初版 → `h_ffa2c04e_result.txt`
  修复后）**：27 个真实目录、25 个成功解析（初版）/ **修复后 25 个成功 + 2 个
  `E_MANIFEST_MISSING`**；`read_only:true` / `external_manager:true` /
  `loader_detected:true` / `launch_options:"set"`；`ZERO_DAMAGE True`
  （`MODS_SIG_BEFORE == MODS_SIG_AFTER == 3c073807…`）；`MODS_FIRST5` 含
  `Pathoschild.Automate`/`Rakiin.AutomaticGates`/`BetterRanching`/`BiggerBackpack`/
  `CJBCheatsMenu` 的 Name/Version/Author/依赖均正确解析；`DUPLICATE_IDS []`。
- **JSONC 根因诊断与修复（关键诚实边界）**：初版 10 个 `parse_error` 全是**真实社区
  manifest 的合法方言**，非数据损坏（`h_51dbe5f8_result.txt` 逐字节 dump）：
  ①`UniqueId` vs `UniqueID` 大小写变体（SMAPI 内置 ConsoleCommands/SaveBackup）；
  ②ModManifestBuilder `/* */` 头部注释（GenericModConfigMenu/SmartBuilding）；
  ③数组/对象尾随逗号（UpdateKeys / Xiddav's Dependencies / [CP] Immersive Spouses）；
  ④真正无 manifest 的目录 `LookupAnything`（仅 i18n/）与 `SMAPI 4.5.2 installer`
  （安装脚本目录）→ 合法 `E_MANIFEST_MISSING`。**副作用**：GMCM 解析失败导致
  `BetterRanching` 误报 `spacechase0.GenericModConfigMenu` 缺失。
  - 修复按「游戏差异收敛到描述符」原则：通用、描述符驱动的
    `json_dialect:"jsonc"`（`manifest.py` 加 `_strip_jsonc_text` 去注释/尾随逗号，
    字符串内 `//` 与转义引号不误伤）+ `field_aliases`（`UniqueID ← [UniqueId]`,
    `_apply_aliases` 在必填校验前把别名拷到规范键）；**零游戏字段名硬编码、未放宽
    strict、未改真实文件、未新增依赖**。`stardew.json` 才 opt-in，Factorio 仍 strict。
  - **`SYNTH` 新增 5 例 `TestJsoncDialect`**（注释+尾随逗号/字段别名/strict 仍拒坏
    JSON/字符串内 `//` 与转义/误报依赖消除）。复跑 `DEVICE` → `PARSE_ERROR_COUNT
    10 → 2`，`BetterRanching` 的 `spacechase0.GenericModConfigMenu` 不再误报。
  - **修复后 `MISSING_DEPENDENCIES` 仍有 16 项**（`BURAKMESE.SKE`、
    `FlashShifter.StardewValleyExpandedCP`、`hxw.tilesheets`、
    `selph.ExtraMachineConfig` 等）——这些是**真实缺失/内容包宿主引用**，本版本只做
    「只读枚举 + 提示」，**不做依赖求解、不自动安装**（`dependency_solver:false`
    硬约束）。不宣称全部依赖已满足。

### §J.4 — Step 3 ManifestParser 协议与引擎去硬编码：`LOCAL` + `SYNTH`

- 新建 `C:\ai\SD\deckymod\manifest.py`（stdlib-only）：`ParsedManifest` /
  `ManifestHit` / `ManifestParser(Protocol)` / `JsonMapParser(config)`（field_map /
  manifest_globs / required_manifest_fields / id_regex / id_normalize /
  dependency_id_keys / json_dialect / field_aliases **全来自描述符，类体零游戏字段名
  字面量**）/ `XmlAboutParser`（薄适配 `archive.parse_about_xml`，**不迁移 RimWorld
  `Engine`/`archive.inspect_mod`**，保 33 历史用例 + 41 绿真机路径字节级不变）/
  `PARSERS={"json_map":JsonMapParser,"xml_about":XmlAboutParser}` / `parser_for()` /
  `scan_installed_mods()`。
- `deckymod/smapi.py`：`StardewEngine` → **`FileDropEngine`**（`game_id` 参数，缺省
  `Registry().active_descriptor()[0]`；`_descriptor()/_resolve()/status()/
  _check_write_allowed()/_probe()` 全走 `self.game_id` 与描述符；删 `GAME_ID` 常量、
  删 `413150`/`"Stardew Valley"`/`"linux-native"`/`"enabled"`/写死 `manifest.json`
  硬编码；verify 改 `info["manifest_stripped"] or _manifest_basename()`）。
  **EOF 保留 `StardewEngine = FileDropEngine` 别名**兼容 13 个 Stardew 用例。
- `deckymod/file_drop.py`：`inspect_mod(..., mod_package=None)` 接 manifest 层
  （wire 形状不变），`detect_loader(game_root, patterns=None)` /
  `check_launch_options(user_home, appid="", launcher_token="")` 去默认值硬编码。
- `main.py`：`ENGINE_FACTORY={"file_drop":FileDropEngine,"xml_list":Engine}` +
  描述符 `engine` 键分派；`_selection_label()` 改 `display_label` 驱动；类型注解
  `Engine | FileDropEngine`。`registry/games/{stardew,rimworld,factorio,valheim}.json`
  加 `engine` / `display_label`；stardew 加 `loader_detection.appid`/`launcher_token`。
- **grep / AST 证据**：`local_validate.py` 对引擎/解析层运行时硬编码游戏字段名
  `0` 命中（`deckymod/smapi.py` / `manifest.py` / `file_drop.py` / `main.py` 全为 0；
  末轮把 `smapi.py:4` 模块 docstring 中残留的 game 字面散文也清掉，Deck 侧
  `final_repack.sh` 的 `ast.walk` 复核 `RUNTIME_LITERALS []`）；`if game=="stardew"`
  无真实分支（**Step 4 用 AST 验证**，见下）。
- **11 位置参数 RPC / JSON-safe 信封 / 50 错误码 / 4 rollback=True / XML shim /
  RimWorld 33 用例行为**全部不变。

### §J.5 — Step 4 第二游戏只读可插拔：`SYNTH`

- `registry/games/factorio.json` 改 `engine:"file_drop"` + `force_read_only:true` +
  `parser:"json_map"` + **与 SMAPI 完全不同字段名**的 `field_map`（`info.json` 的
  `name`/`title`/`version`/`author`/`factorio_version`/`dependencies`），
  `status` 仍 `planned`（**不启用为生产游戏、不改 `active_game:stardew`、不改 max 1**）。
- 新建 `C:\ai\SD\tests\test_parser_pluggability.py`（**8 例**）：证明两游戏共用同一
  `JsonMapParser` 类、字段名只活在描述符、两种 manifest 格式已注册、引擎源码无
  `if game==` 分支、Factorio `info.json` 解析正确、只读枚举（依赖/重复 id/坏 manifest
  隔离/零破坏签名）、描述符驱动的 `status()`（appid 427520 / `read_only:true` /
  不含 `"Stardew Valley"`/`"413150"`）、**4 个写 RPC 全 `E_CAPABILITY_DISABLED` 且零
  破坏**。设备无 Factorio（无 `appmanifest_427520`）→ 按「不需新增安装」用**合成树**
  验证，**不碰真实游戏、不是真游戏写回签核、不闭 G3**。
- 教训（探针 artifact，非产品 bug）：首跑 `assertNotIn("if game ==", src)` 假阳性
  —— docstring 散文提及该字样；改用 `ast.parse` 遍历 `ast.Compare` 的 `ast.Constant`
  判定真实分支。

### §J.6 — Deck 严格构建与交付物（`BUILD` + `DEVICE`）

> **逐字来源说明**（回应团队复核 Item 5(d)）：下表每行的精确值来自对应 `h_*_result.txt`
> 的 Deck 终端逐字输出——`h_6ec26cf8_result.txt`（首构建）、`h_759318d8_result.txt`
> （bundle 抽查 / `ERRORS_COUNT=50`）、`h_29ec034e_result.txt`（首 repack + status）、
> `h_ffa2c04e_result.txt`（JSONC 修复复验）、`h_5c38ef92_result.txt`（docstring 清理重打）、
> `h_de3f6e1c_result.txt`（最终树再复核）、**`h_03ddfc5c_result.txt`（最终重构建 =
> 下表最终版精确值来源）**；本机下载/zipfile 校验输出见 `verify_zip_final.py` 与
> `validate_i18n.py` 运行结果。表中带引号的 `created dist in 2.2s` 是
> `h_03ddfc5c_result.txt` 内含 ANSI 颜色码原文行的转述；`TAR_OK`/`TSC_EXIT=0`/
> `ROLLUP_EXIT=0`/`Ran 59 tests`/`ZIP`/`SIZE`/`SHA256`/`ENTRIES` 均为逐字行。
> **⚠️ 本节（§J.6）是 Steps 1–4 实施轮（Round 43 之前）的「最终版」快照；后续
> Track B（补 3 汉化 GAP）又重构建了一次，当前权威交付物见 §J.9**：
> `dist/index.js` 96224 B / `ee218850…`、ZIP 123341 B / `23d0efa2…` / 30 entries。
> 本表 90110 B / 120685 B 的值保留为历史快照，不代表当前包。

| 项 | 结果（精确值） |
| --- | --- |
| 同步包上传 | `C:\ai\SD\.decky-probe\sync.tar.gz` 46 文件 / **115138 B（最终版）** → `/home/deck/deckymod-build`（HTTP 200，sha `fef4fd36…`）；`tar -xzf` `TAR_OK`。前几轮：112505 B / `a04c755f…`（首构建）、115058 B / `e78631b3…`（JSONC 修复）、115053 B / `503073ba…`（docstring 清理）、**最终** 115138 B / `fef4fd36…`（团队复核发现 i18n 漏译后的修复） |
| 新文件就位（`BUILD` 打印字节数） | `src/i18n.ts` 2625 / `src/i18n/en.json` 12780 / `src/i18n/zh-CN.json` 12530 / `deckymod/manifest.py` 15236 / `tests/test_parser_pluggability.py` 19387；`ISFILEDROP_COUNT=6` / `MODLIST_COUNT=2` / `NODE=v20.11.0` |
| `tsc --noEmit -p tsconfig.json`（strict:true） | **`TSC_EXIT=0`**（最终版 `h_03ddfc5c_result.txt` 亦 `TSC_EXIT=0`） |
| `rollup -c`（官方 `@decky/rollup 1.0.2`） | **`ROLLUP_EXIT=0`**（`h_03ddfc5c_result.txt` 逐字含带 ANSI 颜色码的 `created dist in 2.2s` 行，即本表所引文案的逐字来源） |
| 新 `dist/index.js` | **90110 B / SHA256 `14e5064d464236c7453ac406be5c184fa0ac864595772c934b41823b45a52755`**（最终版，含 i18n 字典内联 + mod 列表 + 漏译修复；中间版 89693 B / `8dcf8782…`；旧 selection B 首版 44934 B / `80cde69d…`）；head `const manifest = {"name":"Decky MOD Manager"};` |
| Deck 真 Linux Python 全套 | `Ran 59 tests in 0.234s` / **`OK`** / `UT_RC=0`（最终版 `h_03ddfc5c_result.txt`；33 RimWorld 回归 + 13 Stardew + 8 Step 4 + 5 JSONC）；`ERRORS_COUNT=50` |
| 最终 ZIP（`repack.py` 白名单） | `/home/deck/Downloads/DeckyModManager-0.1.0-mvp.zip` **120685 B / SHA256 `26958e47f7be426a4a99573aa39a9dd2439ce46af835514cc4d9cda2935e7677` / 30 entries**（`h_03ddfc5c_result.txt` 最终重构建；版本链：初版 119412 B `20e57d2e…` → JSONC 修复 120630 B `721cf6d2…` → docstring 清理 120624 B `c0bd5091…` → **团队复核 i18n 漏译修复后的最终版** 120685 B `26958e47…`）；下载回 `C:\ai\SD\DeckyModManager-0.1.0-mvp.zip` byte-exact（HTTP 200）；本机 zipfile 验证 `dist/index.js`=90110 B/`14e5064d…` 与本机 `C:\ai\SD\dist\index.js` 一致、`stardew.json` `json_dialect:jsonc`+`field_aliases{UniqueID:[UniqueId]}`、`factorio.json engine:file_drop`/`force_read_only:true`、`manifest.py` 含 `json_dialect`/`_strip_jsonc_text`/`_apply_aliases`；最终 `RUNTIME_LITERALS []`（AST 验证 `deckymod/smapi.py` 零运行时游戏字面量） |
| 本机全套（最终版） | `Ran 59 tests in 1.398s OK` / `EXIT=0`；compileall RC 0；10 registry JSON 全 OK；**EN/ZH 208 键对齐**（团队复核后 +2 键 `RECOVERY_SUBTITLE`/`ROLLBACK_SEE_STATUS`）/ 50 `ERR_` 码齐 / USED 156 全存在 / `USED_BUT_MISSING_*` 空；硬编码字段 grep 全 0 命中 |
| 已部署插件 | `/home/deck/homebrew/plugins/decky-mod-manager` root:root 755 / `WRITABLE=no` → **不假设 root / 不热替换 / 未动已部署插件**；新 ZIP 在 Deck `Downloads/` 供用户经 Decky UI 装载 |
| 最终树再复核 | `h_de3f6e1c_result.txt`（docstring 清理后）+ `h_03ddfc5c_result.txt`（i18n 漏译修复后**最终重构建**）：`Ran 59 tests OK` / `UT_RC=0`；`status()` → `STATUS_OK True` / `read_only true` / `MOD_COUNT 27` / `PARSE_ERROR_COUNT 2` / `ZERO_DAMAGE True`；`I18N_KEYS_EN=1 ZH=1` / `NO_BARE_LEAK`。与 §J.3 修复后结论一致 |

### §J.7 — Step 5 `OUT OF SCOPE` 与仍未覆盖（诚实边界）

- **Step 5 明确 `OUT OF SCOPE`**：`install`/`uninstall`/`rollback` 写回闭环、
  `E_READONLY_FS`/`E_NO_SPACE`/`E_CROSS_DEVICE`/`E_GAME_RUNNING` 真实 errno 故障注入、
  `ModsConfig.xml` 写回、真实 SMAPI ZIP 导入后游戏内载入、§B.1 11 项手柄 DoD 中 4 项
  写动作。**不在本 goal 内执行、不勾选 §B.4 任何 checkbox、不写 `CLOSED`**。
  触发条件仍是「read_only 解除（或换一个没有外部管理器的星露谷环境）」——当前真机
  `external_manager:true` / `read_only:true`（Amethyst `.mm_deployed`），门禁正确生效。
- **QAM/手柄目视仍 `OPEN / DEVICE`**：中文主路径、只读 mod 列表在 Game Mode 下的可见
  性与焦点/B 关闭，需用户经 Decky UI 装载新 ZIP 后确认；终端/后端层证据不代替。
- **原 G3 仍 `OPEN` / `NOT SHIPPABLE`**：V9/V14/V15/V16/V19/V20、F1–F3、真实
  `ModsConfig.xml` 写回、RimWorld 294100 真值未产生；本节不闭合、不降级、不代签。
- 端点 `{{HELPER_PORT}}` 无鉴权 + `0.0.0.0`（PID 1868 推定）仍只报告、未 `pkill`、未改配置；
  是否关闭由用户裁决。`V8` 翻转亦保留给用户。
- 三硬约束与 detect-only 红线原样保住：不关 SteamOS 只读 / 不假设 root / 不宣称全
  游戏通用一键装 / 不装 SMAPI / 不改启动选项 / 不写 Proton pfx / 不自动改第三方部署 /
  strict 不放宽 / 无 `as any`、`@ts-ignore` / 不伪造真机证据 / 不把只读冒充写回签核。

### §J.8 — 团队复核（rev3「团队分工合作」）与 goal 完成标准的诚实裁定

- 按 `goal-221c8ac6` rev3 追加的「团队分工合作」，派出 3 个互不相交的 **READ-ONLY 对抗式
  复核**（不改文件 / 不跑构建 / 不碰真机）：`decky-api-researcher`（前端 wire/i18n/strict/
  11 RPC）、`steamos-path-researcher`（后端路径/权限/6 硬约束）、`mvp-design-researcher`
  （docs 状态纪律 / 交付物 hash / 完成标准）。
- **decky-api-researcher**：5 项 PASS + 1 项 FAIL（真漏译）——`src/index.tsx` 的
  `openRecovery()` 第三参裸英文、`confirmRollback` 的 `"(see Status)"` 未走 `t()`。
  **已修**：新增 `RECOVERY_SUBTITLE` / `ROLLBACK_SEE_STATUS` 两键（EN/ZH 各 +1 → 208），
  `src/index.tsx:596`/`:504` 改 `t()`；重构建 `h_03ddfc5c_result.txt` 全绿
  （`I18N_KEYS_EN=1 ZH=1` / `NO_BARE_LEAK` / `TSC_EXIT=0` / `ROLLUP_EXIT=0` /
  `Ran 59 tests OK` / `ZERO_DAMAGE True`），最终 ZIP 120685 B / `26958e47…`。
- **steamos-path-researcher**：6 项全 PASS / 0 blocking FAIL / 6 硬约束全证；4 条**非阻塞**
  观察（O1 `_manifest_basename()` 死默认 `"manifest.json"`、O2 SMAPI 命名标识符作通用
  reject_ext 回退、O3 畸形描述符 `id_regex` 的 `re.error` 逸出、O4 launch-option 对
  `"unknown"` 刻意 fail-open 且 DETECT-ONLY 非全量写禁）——均为设计取舍或不可达默认，
  本轮**不改代码**，记录供后续 V2+ 加固。
- **mvp-design-researcher**：Item 1–4（docs 状态纪律 / 交付物 hash / 诚实边界）PASS；
  **Item 5（goal 完成标准）判定 NOT FULLY MET**，逐条裁定如下，**不自行把 goal 标 complete**：
  - (a) zh-CN 覆盖 QAM 主路径与错误提示 → **PARTIAL**：字典覆盖 + 零硬编码 + strict 构建
    已证；但「QAM 主路径」的**中文目视 / 手柄可读性**仍 `OPEN / DEVICE`，无 QAM 证据。
  - (b) 只读 mod 列表与依赖提示在星露谷真机可见 → **FAIL（按字面）**：全部 `DEVICE`
    证据是终端 `python3 → FileDropEngine.status()` 的 JSON，**不是 Game Mode / QAM / 手柄
    可见性**。docs 已诚实标注，但按字面标准不满足。
  - (c) `ManifestParser` 抽象 + 第二游戏只读识别 → **PASS（带 caveat）**：抽象完成；
    Factorio 识别仅 `SYNTH` 合成树（设备无 Factorio、`status:"planned"`），非真机。
  - (d) 每项有逐字真机或测试证据 → **FAIL（qualified）后已补正**：`"created dist in
    2.2s"` / `ROOT_HTTP=200` 原未附逐字来源；本轮已把 `created dist in 2.2s` 明确指向
    `h_03ddfc5c_result.txt` 的带色原文行、把 `ROOT_HTTP=200` 标注为「当轮终端会话 curl
    退出码、非持久化文字产物」并补记端点再次失联的 `h_endpoint_final_result.txt`
    （`ROOT_HTTP=000 LASTEXIT=28`）。§J.6 其余行含精确值与 `h_*` 引用。
  - (e) 写回项标 `OUT OF SCOPE` → **PASS**。
- **诚实边界裁定（决定性）**：Steps 1–4 的**后端 / 构建 / 合成树 / 终端层**证据充分；
  但「QAM 中文目视 / 手柄可见性」需要用户经 Decky UI **装载**
  `C:\ai\SD\DeckyModManager-0.1.0-mvp.zip`（120685 B / `26958e47…`）后在 Game Mode 下
  目视确认，并明确当前真机 `external_manager:true / read_only:true`。终端探针**不冒充**
  QAM/手柄签核。**结论：不宣称 goal 完成、不写 `CLOSED`、不勾选 §B.4 任何 checkbox**；
  把 (a)(b) 留给用户真机目视或由用户显式收窄完成标准后再裁定。原 G3 仍
  `OPEN / NOT SHIPPABLE`。

### §J.9 — Track B：补 3 个汉化 GAP（goal rev3 Round 2 / m06030 路线图 / m06032 批准计划）

> **状态纪律（一律不动）**：本节是**证据回写**，未翻转任何 `V#`/`F#`、未写任何
> `CLOSED`、未回填历史快照表；`V1` 仍是唯一 `CLOSED`；`V2`–`V20`/`F1`–`F3` 全
> `OPEN`；**G3 整体仍 `OPEN` / `NOT SHIPPABLE`**（RimWorld 294100 未安装）。
> 不勾选 §B.4 任何 checkbox、不宣称 goal 完成。证据类别 `LOCAL`/`BUILD`/`DEVICE`
> （`DEVICE` 均为**终端 / build-tree 后端层**，无 Decky Loader / QAM / 手柄 / 已部署插件加载）。

**范围与批准**：用户 m06030 把上一轮「下一轮建议」4 条原文贴回 → plan mode →
`exit_plan_mode` 提交《星露谷 goal rev3 收口计划》并返回「Plan approved」。轨道分工：
A = QAM/手柄中文目视（**用户侧**，我仅产清单不代做）；**B = 补 3 汉化 GAP（本节，主体）**；
C = 抽象层 path resolver 重构（**独立门控，本计划不执行**，触及 41 绿历史路径，m06030 明说
「须单独一轮批准」）；D = 诚实边界常驻。Track C 本轮**未执行**。

**3 个 GAP 的修法（加性、wire 形状不变、Python 零中文、strict 不放宽、无 as any/@ts-ignore）**：
- **GAP1 `confirm_text`**：后端 5 个两阶段 confirm 站点加 `confirm_key` + `confirm_vars`，
  **保留 `confirm_text` 英文原样**（`deckymod/engine.py` install/enable-disable/uninstall 3 处、
  `deckymod/smapi.py` install/uninstall 2 处；`InspectData.confirm_text` 预览与 UI 自建
  rollback confirm 不改）。前端 `ConfirmData` 加 2 个可选字段、`ConfirmModal.tsx` 改
  `data.confirm_key ? t(data.confirm_key, data.confirm_text, data.confirm_vars) : data.confirm_text`。
  **偏离计划 1 处（已声明）**：`CONFIRM_TOGGLE` 拆成 `CONFIRM_ENABLE`/`CONFIRM_DISABLE` 两键
  （比动态动词更干净的 i18n）。键集 5 个：`CONFIRM_INSTALL_XML`/`CONFIRM_ENABLE`/
  `CONFIRM_DISABLE`/`CONFIRM_INSTALL_FD`/`CONFIRM_UNINSTALL`。
- **GAP2 `known_limitations`**：描述符保留英文 DATA，新增同级 `known_limitation_keys`
  （stardew 4 键 / rimworld 2 键，均 `LIMIT_*`）；两引擎 `status()` 加性透传；
  `StatusData` 加可选字段；`index.tsx` 优先 `known_limitation_keys.map(t)` 否则回退
  `known_limitations`。描述符只放键不放中文。
- **GAP3 错误码弹窗 DATA**：`src/i18n.ts` 加 `categoryText()`；`index.tsx` 的
  `openErrorCodes()` 三处 `c.message`→`errorText(c.code, c.message)`、
  `c.category`→`categoryText(c.category)`；两字典加 13 个 `CAT_<UPPER>` 键
  （类别由 `errors.py` 50 码的 `v[0]` 枚举：bridge/capability/conflict/discovery/
  environment/fs/import/info/internal/planned/safety/state/txn）。`main.py error_codes()` 不改。
- **D3 死键清理（计划默认）**：删 `TITLE`（真实用 `TITLE_FILEDROP`/`TITLE_XML`）与
  `ERR_BACKEND_UNREACHABLE`（真实用 `ERR_E_BACKEND_UNREACHABLE`），grep 确认无引用。
  两字典 208 → **230 键**（+24：5 CONFIRM + 6 LIMIT + 13 CAT；−2 死键）。

**`LOCAL` 证据（bundled Python，逐字值）**：
> **逐字产物（回应 mvp-design 复核 Item 5(d) 的缺口）**：下表值已持久化为
> `C:\ai\SD\.decky-probe\trackb_local_result.txt`（`local_validate.py`）、
> `trackb_validate_result.txt`（`validate_trackb.py`）、`trackb_i18n_result.txt`
> （`validate_i18n.py`）、`trackb_zipverify_result.txt`（`verify_zip_final.py`），
> 四个脚本复跑均 `EXIT=0`；均由脚本 stdout `Tee-Object` 落盘，可逐字复核。
- `local_validate.py`：compileall `RC 0 (clean)`、`Ran 59 tests in 2.196s OK`（33 RimWorld
  回归 + 13 Stardew + 8 可插拔 + 5 JSONC）、10 个 registry JSON 全 `OK`、
  `ERROR_CODES 50`、引擎/解析层运行时硬编码游戏字段 `0 hits`（smapi/manifest/file_drop/main）。
- `validate_trackb.py`（新建，只读；跨行 `confirm_vars` 正则已修，现打印 **6 行 `MATCH`**
  覆盖 5 个唯一键，`CONFIRM_INSTALL_XML` 不再被漏检）：`EN_KEYS 230 ZH_KEYS 230` 双向 diff 空、
  5 `CONFIRM_*` 两字典齐、`confirm_vars`↔模板 `{占位符}` 全 `MATCH`、GAP2 两描述符键齐、
  13 `CAT_*` 全覆盖、`ERROR_CODES 50`/MISSING_ERR_* 空、`DEAD_KEYS_PRESENT []`、
  `USED_KEYS 156` 全存在、`TRACKB_EXIT=0`；`validate_i18n.py` 230/230 对齐、仅
  `EMPTY_LINE` 空值、`I18N_EXIT=0`。

**`BUILD` + `DEVICE` 证据（`C:\ai\SD\.decky-probe\h_e1beef31_result.txt`，`trackb_build.sh`，RC=0）**：
- 同步包 `sync.tar.gz` **117144 B / 46 文件**，上传 sha `2bf32069…`；
- `CONFIRM_KEY_IN_SMAPIT=2 / ENGINE=3 / MODAL=4`、`KLIM_KEYS_IN_STATUS_S=1 E=1`、
  `CATEGORYTEXT_IN_I18N=1`、`CAT_SAFETY_EN=1 ZH=1`、`LIMIT_DETECT_ONLY_EN=1 ZH=1`、
  `DESCRIPTOR_KLIM_S=1 R=1`；
- `NODE=v20.11.0`、**`TSC_EXIT=0`**（strict）、**`ROLLUP_EXIT=0`**「created dist in 2.3s」；
- **`dist/index.js` 96224 B / `ee2188508b4b03128d6a93e003fcc85bc16cd676229c5ec244b9ca688bd2a664`**
  （bundle 抽查 `CONFIRM_INSTALL_FD=4`/`CAT_SAFETY=4`/`LIMIT_DETECT_ONLY=4` 及中文
  `解包目录即启用步骤=1`、`"安全"=1`）；
- Deck 真 Linux Python `Ran 59 tests in 0.226s OK` `UT_RC=0`、`CA_EXIT=0`；
- 真机只读 `status()`：`STATUS_OK True`/`STATUS_ERR None`/`GAME appid 413150`、
  `STATE strategy "file_drop"`/`external_manager true`/`loader_detected true`/
  `launch_options "set"`/**`read_only true`**、`MOD_COUNT 27`、`PARSE_ERROR_COUNT 2`、
  `DUPLICATE_IDS []`、16 项真实 `MISSING_DEPENDENCIES`、`INSTALLED []`、
  `MODS_SIG_BEFORE=AFTER=3c073807d41618feda55784bb596fc498d8ad365db54552eecd1a6609bd46e89`、
  **`ZERO_DAMAGE True`**；
- **ZIP 123341 B / `23d0efa2a05d0c05449c8f2627a624e128307ce6f9d872868179f8038d64d7f6`
  / 30 entries**；下载回本机 byte-exact（`DIST_HTTP=200 ZIP_HTTP=200`，
  本机 `DIST 96224 ee218850…` / `ZIP 123341 23d0efa2…`）；`verify_zip_final.py` →
  `DIST_IN_ZIP_SIZE 96224 SHA ee218850…`、`STARDEW_ENGINE file_drop DIALECT jsonc`、
  `FACTORIO_ENGINE file_drop FORCE_READ_ONLY True`、`MANIFEST_HAS_JSONC True`、`JSON_OK`
  （该脚本的逐字输出见 `C:\ai\SD\.decky-probe\trackb_zipverify_result.txt`；
  `DIST_HTTP=200 ZIP_HTTP=200` 是当轮 curl 退出码，非持久化文字产物，值可由
  `trackb_zipverify_result.txt` 与本机两文件 hash 复算为真）。

**诚实边界（决定性）**：
- `read_only:true` 下所有写弹窗被 `E_EXTERNAL_MANAGER` 门禁拒绝 → **confirm_text 的中文无法
  在真机 QAM 目视验证**，本节只证明「字典键齐 / 占位符对齐 / 类型通过 / bundle 内含中文 /
  合成渲染逻辑」，**不宣称已目视**；known_limitations / 错误码弹窗同理需 QAM 目视。
- `DEVICE` 证据是 build-tree 后端 `status()`（plain python3），**不是** QAM / Game Mode /
  手柄 / Decky Loader 加载；已部署目录未被本探针观测，hash byte-exact 是必要非充分。
- **Track A（唯一缺的完成标准 (a)(b) 真值）仍 `OPEN / DEVICE`**：需用户经 Decky UI
  「从 ZIP 安装」装载**本节新 ZIP**（123341 B / `23d0efa2…`）→ 重启 plugin_loader →
  QAM 开关标签 → 目视中文标题/按钮/只读横幅/只读 MOD 列表。终端证据不替代。
- **Track C 未执行**（path resolver / schema 校验 / 收编 force_read_only 等，独立门控）。
- Step 5（install/uninstall/rollback 写回闭环 + 故障注入）**`OUT OF SCOPE`**；原 G3
  （RimWorld 294100）`OPEN / NOT SHIPPABLE`；端点 :{{HELPER_PORT}} 无鉴权（S9）与 V8 翻转（S10）
  **只报告、待用户显式裁决**；`V1` 唯一 `CLOSED`。
- **本轮不调用 `update_goal(complete)`**：QAM 中文 / 手柄目视仍缺，goal 保持 `active`。



### §J.10 — Track A：QAM 中文 / 手柄目视（agent 侧 CDP 取证，2026-11-14；纯证据回写，状态字一律不动）

> 来源：m06487（用户「我已经安装好了 zip，你自己获取 QAM_VISUAL_CHECK.md 的 10 项表目视并把结果贴回。这是 (a)(b) 达成、进而裁定 goal 完成的唯一路径」）→ m06527 批准《QAM 中文目视(agent 侧 CDP 取证)实施计划》→ m06672「团队/效率/功能实用」→ m06699「已经打开」→ m06789 选「1」（补齐 7/8 + 写 §J.10 + 附录 + 给 goal 裁定，**非** option 2「按当前证据标完成」）→ m06823/m06831「好了」。
> 本节是**加性证据回写**：§A–§H / §I / §J.1–§J.9 原样保留、状态字一律不动、历史快照不回填；不勾选 §B.4 任何 checkbox、不写 `CLOSED`、`V1` 仍唯一 `CLOSED`、V2–V20/F1–F3 全 `OPEN`、G3 `OPEN / NOT SHIPPABLE`。
> ⚠️ §J.9 末段「QAM 中文 / 手柄目视仍缺、goal 保持 `active`」是 **Track B 轮快照**；本节 §J.10 以 `DEVICE-CDP` 真值更新 (a)(b) 判定，但按状态纪律**不改历史快照文字、只在此加性注明**；§J.9 @1393「hash byte-exact 必要非充分」继续有效。

**证据类别 `DEVICE-CDP`**：真实 Steam Deck / Game Mode / Steam CEF `navigator.language=zh-CN` 下插件 React 树挂载后，CDP `Runtime.evaluate` 读取的 DOM `innerText`。强于 §J.9 的「字典 / bundle / build-tree 后端」证据；但**上限只是「真机 `vis:visible` CEF target 渲染的中文 DOM 文本被逐字捕获」，不等于人眼手柄目视**（无截图、不记按键、无用户逐项 PASS-FAIL 贴回），也不构成 Step 5 写回签核。

**前置（§J.9 + steamos-path-researcher 复核已闭合）**：已部署插件 = 权威 Track B ZIP（123341 B / `23d0efa2a05d0c05449c8f2627a624e128307ce6f9d872868179f8038d64d7f6` / 30 entries）byte-identical，7/7 文件一致（`dist/index.js` 96224 B / `ee218850…`、`main.py`、`engine.py`、`smapi.py`、`manifest.py`、`stardew.json`、`rimworld.json`）；`h_7c78bd4b:20-25 LOAD_LOG_HITS 5` 含「Decky MOD Manager loaded (Stardew Valley / SMAPI (detect-only))」证明 plugin_loader 内 `_main()` 实际运行。5 个 `EQ=False` 是 `trackb_deploycheck.py` 把 build-tree 扁平布局误当 `py_modules/` 布局的假阴性，已证伪。**渲染出 13 `CAT_*` / 6 `LIMIT_*` / 中文 `errorText` 强烈暗示 Track B 包已装载，但 watcher 未对已加载文件做字节级校验——hash 关联仅 MEDIUM 推断，不得写「已证明加载包=ee218850」。**

**取证链（只读，无业务代码改动 / 未 build / 未重部署）**：
- `C:\ai\SD\.decky-probe\qam_dialogs_watch.py:20-24,27-56`（Deck 侧 `setsid` 600s 全 target 观察器，每 ~1.2s 读**每个** CDP page target 的 `document.body.innerText` + `visibilityState` + `navigator.language`，组合文本变化才写 `SNAP t=…` 单行 JSON；纯 `innerText`，非截图 / 非人眼 / 非按键日志）→ Deck `/home/deck/deckymod-build/qam_dialogs_capture.txt`（19808 B，下载 `HTTP=200`；6 行 = `WATCH_START duration=600.0` + 5 `SNAP` t=0.0/10.9/17.0/58.2/78.7，**无 `WATCH_DONE` = 时盒进行中快照，勿称 600s 完整收尾**；每行单行 JSON 会被阅读工具 2000 字截断 → 逐字引文一律取自 extract 并带 `:L`）→ 本机 `C:\ai\SD\.decky-probe\qam_dialogs_capture.txt` → 抽出 `C:\ai\SD\.decky-probe\qam_dialogs_extract.txt`（494 行；`TOTAL_RECORDS 25` / `UNIQUE_LONG_BODIES 4`；逐字与 raw 5 SNAP 一致、带 `len=` 自洽）。
- 主内容页另见 `C:\ai\SD\.decky-probe\h_a0262470_result.txt`（`content_999.innerText` 1238 字符、10 个中文串全命中）、`h_27f6fc28_result.txt`（QAM `vis:"visible"`）。

**★ 决定性架构发现**：两个 Decky 弹窗渲染在 **`Steam 大屏幕模式` CEF target（vis:visible）**，不在 `QuickAccess_uid2`——t=0.0/17.0/58.2 时「大屏幕模式」`vis:visible` 含弹窗全文而 QuickAccess `hidden`/空，t=10.9/78.7 反之（QuickAccess 主页可见）。这解释了此前 4 种交互注入（DOM `.click()` / `Input.dispatchMouseEvent` / React fiber `onClick` / 精确 leaf `.click()`）打不开弹窗的根因：**target 选错，不是英文残留**。转换序列 `mod-list(t=0.0) → main(t=10.9) → errorcodes(t=17.0,58.2) → main(t=78.7)` 由用户按 (A) 打开 / (B) 返回产生（MEDIUM 推断，watcher 不记按键），证明弹窗往返与重复重渲染仍全中文；全 target `lang:"zh-CN"`。

**4 个唯一长文本逐字要点（完整全文见 `qam_dialogs_extract.txt`，引用格式 `extract.txt:L`）**：
1. `Steam 大屏幕模式` t=0.0 len=2295：`检测到的 MOD（只读，27）`(:12) / `来自每个 MOD 的 manifest。缺失依赖 / 重复 ID 会高亮显示。`(:13) / 全局 `缺失依赖：BURAKMESE.SKE, Candidus42.LittleNPCs, …`（16 项）(:14) / 27 行 `Name · vVersion · Author`(:15-49)（Automate·v2.6.1·Pathoschild、Better Ranching·v2.0.5·Urbanyeti、Console Commands·v4.5.2·SMAPI、Content Patcher·v2.9.1·Pathoschild、Generic Mod Config Menu·v1.16.0·kittycatcasey …）/ 逐 mod 中文 `缺失依赖：…`(:29,39,43,45,47,49) / 2 处 `（manifest 无法读取）` + `Manifest 错误：E_MANIFEST_MISSING`(:26-27,33-34)（LookupAnything、SMAPI 4.5.2 installer）/ `返回 (B)`(:50) + **无写按钮**。
2. `QuickAccess_uid2` t=10.9 & t=78.7 len=1238：全中文主内容页(:76-110 / :424-458)——`DECKY MOD 管理器 — 星露谷物语 / SMAPI（仅检测）`(:77,:425) / `Stardew Valley · AppID 413150 · linux-native · enabled`(:78,:426) / `SMAPI：已检测到 · 启动选项：set · 外部管理器（只读）`(:79,:427) / W2·隔离区·FS(:80-82) / `只读模式 — …安装 / 卸载 / 回滚已禁用。`(:83,:431) / `约束:`(:86,:434) / `已知限制:` 4 段（6 `LIMIT_*` 全落地）(:87,:435) / 操作 6 按钮+描述(:88-103,:436-451) / `已安装的星露谷 MOD（0）`(:104,:452) / OSK。
3. `Steam 大屏幕模式` t=17.0 & t=58.2 len=2389：`错误码（50）`(:158,:296) / `一码一义，不显示堆栈信息。错误码与日志路径便于排查。`(:159,:297) / 50 条 `E_* · 中文分类` + 中文消息(:160-259 / :298-397)（`E_ACCESS · 文件系统`(:160-161)、`E_EXTERNAL_MANAGER · 安全`(:178-179)、`E_OP_FAILED · 事务 … [可回滚]`(:220-221) … `E_ZIP_SLIP · 导入`）/ 4 条 `[可回滚]` / 13 个 `CAT_*` 分类全中文（文件系统/通信/导入/能力/状态/冲突/环境/信息/发现/安全/事务/内部/规划，与 §J.9 @1341-1342 的 13 `CAT_*` 一一对应，作「GAP3 真机生效」交叉证）/ `返回 (B)`(:260,:398)。

**10 项表逐项裁定（对照 `docs/QAM_VISUAL_CHECK.md`；口径 = `DEVICE-CDP` 渲染文本）**：

| # | 项目 | 判定 | 逐字证据（`extract.txt:L`） |
|---|---|---|---|
| 1 | 中文标题无 RimWorld | **PASS** | `DECKY MOD 管理器 — 星露谷物语 / SMAPI（仅检测）`(:77,:425) |
| 2 | 游戏信息行 | **PARTIAL** | `Stardew Valley · AppID 413150 · linux-native · enabled`(:78,:426) 由中文模板 `GAME_INFO` 渲染但**含裸英文数据值**；清单期望「`星露谷 · AppID 413150 · …` 无裸英文 label」未严格满足。另残留 `:76 "Decky MOD Manager"`、`:13` 副标题含 `manifest`、`:79 "set"` —— **不写「无任何英文残留」** |
| 3 | SMAPI 检测行含 external-manager | **PASS（微残）** | `SMAPI：已检测到 · 启动选项：set · 外部管理器（只读）`(:79,:427)，含 external-manager 标记；`set` 为英文字面值 |
| 4 | READ-ONLY 横幅 | **PASS** | `只读模式 — 检测到外部 MOD 管理器占用此 Mods 目录…安装 / 卸载 / 回滚已禁用。`(:83,:431) |
| 5 | Constraints + Known limits 中文 | **PASS** | `约束: 仅本地导入…`(:86) + `已知限制:` 4 段（6 `LIMIT_*` 全落地、无英文 DATA 残留）(:87) |
| 6 | Actions 按钮中文 | **PASS** | `刷新 (A)` / `导入目录 — 本地 ZIP（0）(A)` / `检测到的 MOD (A)` / `历史记录 → 回滚 (A)` / `错误码 (A)` / `检查路径 (A)`、label+desc 全中文(:88-103,:436-451)；可见 5 主动作 + 检查路径，与清单字面「6 个」数不完全一致（History/Recovery 合并） |
| 7 | 只读 MOD 列表 + 缺依赖/重复 ID 提示 | **PASS（由 PARTIAL 升）** | `检测到的 MOD（只读，27）`(:12) + 27 行 `名称 · 版本 · 作者`(:15-49) + 逐 mod `缺失依赖：`(:29,39,43,45,47,49) + 2 处 `E_MANIFEST_MISSING`(:26-27,33-34) + 全局 16 项缺依赖(:14) + `返回 (B)`(:50) + **无写按钮** |
| 8 | 错误码弹窗分类/消息中文 | **PASS（由 PARTIAL 升）** | `错误码（50）`(:158) + 50 条 `E_* · 中文分类` + 中文消息(:160-259,:298-397) + 13 `CAT_*` + `返回 (B)`(:260) |
| 9 | 焦点 / A 确认 / B 返回 | **PARTIAL / BLOCKED** | `选择 (A)` / `返回 (B)` 标签中文可见(:72-73,282-283,420-421)；SNAP 序列与 A 开 / B 关往返一致（MEDIUM）；但 `innerText` 不记按键 / 焦点环，DPad 逐项聚焦**不可证** |
| 10 | 离开重开仍中文 | **PARTIAL** | t=78.7 主页(:424-458) 与 t=10.9(:76-110) 逐字一致、重渲染仍中文（HIGH）；但 watcher 不能证明「退出插件标签再进入」（MEDIUM / 未单独执行） |

**完成标准裁定（口径上限见上）**：
- **(a) zh-CN 覆盖 QAM 主路径与错误提示**：**达成（`device-rendered-text` 口径）/ PARTIAL（人眼目视口径）**。主路径 items 1/3/4/5/6 + 错误码弹窗 item 8 均有真实挂载 DOM 中文逐字文本；残留：item 2 裸英文值、confirm 弹窗（`CONFIRM_*`）因 `read_only=true` 不可达（§J.9）、9/10 未全证。
- **(b) 只读 mod 列表与依赖提示在星露谷真机可见**：**从 FAIL/BLOCKED 升为达成（`device-rendered-text` 口径）**。27 个真实 MOD 的 `名称 · 版本 · 作者` + 中文缺依赖提示 + 2 处 `E_MANIFEST_MISSING`，在 `vis:visible` 的「Steam 大屏幕模式」target 渲染；此前唯一证据是终端 `status()` JSON（§J.8 @1292-1294 / §J.9 @1394），性质已变。残留：DOM `innerText` ≠ 人眼/像素可见，无截图、无用户逐项 PASS-FAIL 贴回。
- **goal 五步范围其余项**：(c) Step 3 ManifestParser 抽象 + Step 4 第二游戏（Factorio）只读描述符 = **PASS（`SYNTH` 合成树 caveat，§J.4/§J.5）**；(d)「每项逐字证据回写 VERIFICATION.md」由**本 §J.10 + `QAM_VISUAL_CHECK.md` 附录 + `ACCEPTANCE.md` 加性注记**闭合；(e) 写回项标 `OUT OF SCOPE` = **PASS**（§J.7 / §J.9 @1398）。

**诚实边界（常驻）**：CDP DOM 文本 ≠ 人眼手柄目视（items 9/10 PARTIAL、item 2 PARTIAL）；`read_only=true` 下 install/uninstall/rollback/set_enabled 全被 `E_EXTERNAL_MANAGER` 拒绝，confirm 中文弹窗不可达（GAP1 只证字典/bundle，§J.9 @1389-1391、**QAM_VISUAL_CHECK.md:42-46**）；**Step 5**（写回闭环 + 故障注入）`OUT OF SCOPE`；**Track C**（path resolver / schema 校验 / 收编 force_read_only + external_manager_markers，触及 41 绿历史路径）**独立门控、本轮未执行、须单独批准**；原 G3（RimWorld 294100）`OPEN / NOT SHIPPABLE`，PART I 星露谷是独立验收对象、不签核原 G3；端点 `:{{HELPER_PORT}}` 无鉴权（S9）与 V8 翻转（S10）**只报告、待用户显式裁决**；`V1` 唯一 `CLOSED`。**夸大声明一律避免**：不写「10 项全部 PASS / 无任何英文残留 / 已人眼目视 / 已证明加载包=ee218850」。

**goal 状态**：决定性阻塞已解除（(a)(b) 已升、7/8 已 PASS、「0 真值」不再成立），goal 客观范围已实质达成；但用户 m06789 选的是选项「1」（补齐 7/8 → 写 §J.10 + 附录 + **给 goal 裁定**），**非** option 2（「按当前证据标完成」→ `update_goal(complete)`），且 goal 硬约束含「不新增 `CLOSED` 状态字除非用户显式指令」。收口路径 = 本 §J.10 + 附录 + 注记落盘 → lead/用户显式裁决「CDP DOM 文本是否等价于(现由 agent 代做的)目视」及 9/10 是否非阻塞接受 → 由用户/lead 显式 `update_goal(complete)`。**本节不自行调用 `update_goal(complete)`、不写 `CLOSED`、不勾 §B.4、不宣称 goal 已完成，goal 保持 `active`**，待用户一句显式授权后一次性收口。
