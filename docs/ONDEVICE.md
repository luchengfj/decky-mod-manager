# ONDEVICE.md — Steam Deck 真机调试清单（实现方式 + 实现步骤 + 详细操作）

> ## 状态：**全清单「待执行 / 待复核」，无一项「已通过」**
>
> - 本文件在**无 SteamOS 设备、无网络**的本机以纯文档方式离线编写；文中所有命令均为
>   **换机 / 真机上待执行**的操作，不是已运行结果。**本会话未执行其中任何一条命令**。
> - **未修改任何 `V#` / `F#` 状态**：[VERIFICATION.md](VERIFICATION.md) 的 V1–V20 + F1–F3
>   全部仍为 `OPEN`；本文件**不产生任何 `CLOSED` 状态**（文中出现 `CLOSED` 字样仅用于
>   「不得擅自改为 CLOSED」这类否定式说明）。
> - **不编造实测输出**：文中所有 `<...>`、`形如 ...`、命令清单都是**形态占位符 / 操作模板**，
>   不是真机 stdout、不是 commit hash、不是版本号、不是 errno 实测值。
> - **不放宽类型、不改后端语义、不新增功能**：调试中发现的问题只**记录**，不通过关 `strict`、
>   加 `@ts-ignore` / `as any`、跳过 `tsc --noEmit`、mock、伪版本来「让它变绿」。
> - 本轮**只写这一份文档**；不改 `src/`、`deckymod/`、`main.py`、任何配置或任何 `V#` 状态。
>
> **状态更正（2026-11-12 后续轮次补记，非本文的状态变更）**：本文 §0 与 §9 的
> 「V1 / V3 / V8 全 `OPEN`」「需 C1–C4 真实输出」是**本文撰写那一轮的历史快照**，不是
> 实时状态。C1–C3 证据已由用户在联网侧补齐，**V1 现已 `CLOSED`**（权威记录见
> [VERIFICATION.md](VERIFICATION.md) §A）；V3 / V8 仍 `OPEN`，`dist/index.js` 仍不存在，
> 「现在直接上真机只会得到加载不起来的插件」这一**产物缺口结论仍成立**。§9 表格保留原样
> （当时真实记录）。本补记未执行任何命令、未改本文任何 V#/F# 状态、未放宽类型。
>
> **状态更正（2026-11-13 证据回写补记，非本文的状态变更）**：上面「`dist/index.js`
> 仍不存在 / 前端 8 个文件未编译未类型检查 / V8 仍 `OPEN`」是**本文撰写那一轮的历史
> 快照**。2026-11-13 已在一台**联网 Steam Deck（即本文 §0.1 的第 ② 档就在这台闭环）**
> 实跑 `pnpm install` + `tsc --noEmit`(strict 零错误，修复 8 个真实 TS 错误) +
> `rollup -c`（官方 `@decky/rollup` 产出可加载 ESM），`pnpm-lock.yaml` 与 `dist/index.js`
> 已生成并回传本工作区；本文 §0.4「当前卡点在 ② 不是 ③」的**产物缺口已消除**。
> 逐字 stdout 见 [VERIFICATION.md](VERIFICATION.md) §H。**但**这仅是构建/类型核对证据：
> 按本轮授权「只回写证据、状态一律不动」，**V2–V20 / F1–F3 仍全部 `OPEN`、未写任何
> `CLOSED`**、G3 整体仍 `OPEN`。§2 步骤 4–9（部署、QAM/手柄 DoD 11 项、V15/V16/V19/V20、
> F1/F2/F3、真实 errno 故障注入）**仍待执行**；RimWorld 294100 在该 Deck 未安装，
> 真实游戏写回仍无真值。§0 / §9 的表格与「待执行」状态字保留原样（历史记录不回填）。
>
> **状态更正（2026-11-13 晚补记，非本文的状态变更）**：同日晚用户经 Decky UI 手柄
> 「从 ZIP 安装」**已把插件装上真机**；首启因冻结解释器 PYZ 缺 `xml.etree` 失败，按用户
> 批准加了 `deckymod/__init__.py` 的 XML 兼容 shim，就地补丁 + WS 重载后**插件在真机
> 冻结解释器里真实加载成功**（子进程存活、`deckymod.log` 有 loaded 行、4 个只读 RPC
> 全链路通过），并重建带 shim 的 ZIP 回传。逐字证据见 [VERIFICATION.md](VERIFICATION.md)
> §H.7。**因此本文表格中「`dist/index.js`（非空、cjs）/ rollup 输出的 cjs / 是否 cjs」是
> 撰写时的历史快照**：实际产物已改用官方 `@decky/rollup` 产出 **ESM**（`SP_REACT/SP_JSX/DFL`
> globals，见 §H.2/V6），「产物缺口 / 未安装」结论已被取代；这些表格列按「历史记录不回填」
> 保留原样，请以 §H 为准。**但**按授权 V2–V20 / F1–F3 仍全部 `OPEN`、未写任何 `CLOSED`、
> G3 整体仍 `OPEN`；RimWorld 294100 仍未安装、手柄 DoD 11 项与真实游戏写回仍无真值，
> §2 步骤 4–9 仍待执行。
>
> **状态更正（2026-11-14 B 方案补记，非本文的状态变更）**：同日按用户「B方案」授权，
> 已用临时、可逆的 env shim + WS 重载，在真机**冻结解释器**里以合成假 RimWorld 树跑通
> 11 个 RPC 全链路 + 7 类故障注入（41 项全绿），测完 `main.py` 逐字节还原、hook 消失、
> 合成树删除、插件干净重载。逐字证据见 [VERIFICATION.md](VERIFICATION.md) §H.9。
> **这不改变本文的操作清单**：它是后端逻辑回归，不是真游戏 DoD 签核；RimWorld 294100
> 仍未安装、手柄 DoD 11 项与真实游戏写回仍无真值、§2 步骤 4–9 仍待执行、V2–V20 / F1–F3
> 仍全 `OPEN`、未写 `CLOSED`、G3 仍 `OPEN`。§0 / §9 历史表格继续按「不回填」保留。

---

## 0. 文档定位、阅读顺序与阶段地图

| 文档 | 回答的问题 | 在哪台机器 |
| --- | --- | --- |
| [README.md](README.md) | 这个项目是什么、怎么组织、W1/W2/W3、通信契约、诚实限制 | 任意 |
| [RUNBOOK.md](RUNBOOK.md) | **怎样产出可部署产物**：C1–C4 锁版本 + `tsc` + `rollup` | **联网机器** |
| [VERIFICATION.md](VERIFICATION.md) | G3 门：V1–V20 + F1–F3 待核实项与回写规则 | 证据汇总处 |
| [ACCEPTANCE.md](ACCEPTANCE.md) | DoD：11 项手柄操作 + G1/G2/G3 + 46 码错误表 | 真机签核 |
| **本文 ONDEVICE.md** | **真机上具体怎么调**：实现方式、实现步骤、观测面、故障注入、闭环顺序 | **Steam Deck 真机** |

**严格顺序**：先 `RUNBOOK.md` C1→C4 在联网机器上产出 `pnpm-lock.yaml` + `dist/index.js`
（并核对 V3 形状），**再**把产物带到 Deck 按本文 §2 调试。**【历史快照】** 撰写时
`dist/index.js` 不存在、前端 8 个文件未编译未类型检查、V3/V8 仍 `OPEN`（V1 已于
2026-11-12 置 `CLOSED`，见 [VERIFICATION.md](VERIFICATION.md) §A）——当时直接上真机
只会得到加载不起来的插件。**2026-11-13 更新**：② 档已在联网 Deck 闭环，可加载 ESM
`dist/index.js` 已生成并回传（见文首「状态更正」与 §H）；产物缺口已消除，但 V2–V20 /
F1–F3 仍 `OPEN`、RimWorld 294100 未安装，故 §2 步骤 4–9 仍待执行。

### 阶段地图

| 阶段 | 目标 | 对应本文 | 主要闭环对象 |
| --- | --- | --- | --- |
| **−1** | 联网机器产出可部署产物 | §2 步骤 1 → [RUNBOOK.md](RUNBOOK.md) | V1、V8（及 V3 证据） |
| **0** | 本机离线准备、前置门槛确认 | §2 步骤 0 | 无（只判定能否开始） |
| **A** | 部署整棵目录到 Deck | §2 步骤 2–3 | V4、V5 |
| **B** | 启动 + 接通 4 个观测面 | §2 步骤 4 | V2、V11、V12、V13 |
| **C** | `status()` 首检 + 后端零风险干跑 | §2 步骤 5–6 | V9、V10、V14、V17、V18 |
| **D** | 前端加载 + 快速迭代循环 | §2 步骤 7 | V3、V6、V7 |
| **E** | 按 V#/F# 分组逐项闭环 | §2 步骤 8 | V15、V16、V19、V20、F1–F3 |
| **F** | 手柄 DoD 11 项 + 故障注入 | §2 步骤 9 | G1/G2/G3 + 46 码 |
| **G** | 证据回写 | §2 步骤 10 / §7 | 全部 |

### 0.1 三档机器分工（回答「是不是全部要在 Steam Deck 上跑」）

**不是。** 只有一部分必须在 Deck；甚至「联网机器」那一档连 SteamOS / Decky Loader /
RimWorld 都不用装。三档分工如下（本小节是**机器归属说明**，不是状态变更；所有
V# / F# 仍 `OPEN`，不产生任何 `CLOSED` 状态）：

| 档 | 在哪做 | 对应内容 | 需要什么 | 不需要什么 |
| --- | --- | --- | --- | --- |
| **① 本机**（当前 Windows 无网机） | 这台开发机 | 写/读文档、离线复核 O1–O12、实现阶段已跑过的后端测试 + compileall + 12 JSON 校验（见 [ACCEPTANCE.md](ACCEPTANCE.md)）、步骤 10 证据回写 | Python + 文件 | Decky、网络 |
| **② 任意能联网的机器**（**不必是 Deck**） | 任何有公网 + Node/pnpm 的机器，**或 GitHub Actions runner** | [RUNBOOK.md](RUNBOOK.md) C1–C4：`git ls-remote` / curl releases / `npm view` / `pnpm install`+`tsc --noEmit`+`rollup -c`+`--frozen-lockfile` | npm registry + 工具链 | SteamOS、Decky Loader、RimWorld |
| **③ Steam Deck 真机** | Deck | 部署、QAM 加载、`status()` 真路径、游戏写回语义、microSD/Flatpak、手柄 DoD 11 项、故障注入 | Decky Loader + Game Mode + SteamOS + 已装的 RimWorld（AppID 294100） | — |

**一句话工作流**：本机写文档 / 跑后端测试 → ② 编译出 `pnpm-lock.yaml` + `dist/index.js`
→ 拷到 Deck → 只在 Deck 上做「加载 + QAM + 真路径 + 游戏行为 + 手柄」那部分。

### 0.2 每个步骤在哪台机器（清单自带标注）

| 步骤 | 机器 | 说明 |
| --- | --- | --- |
| 步骤 0 前置门槛 | ① / ② | 判定 ② 是否已完成；本机只看文档与留档 |
| 步骤 1 产出产物 | **②** | RUNBOOK C1–C4；不装 Decky |
| 步骤 2 Deck 侧准备 | **③** | Developer mode、插件目录、SSH |
| 步骤 3 部署整棵目录 | ② → ③ | 从 ② 的产物 rsync 到 Deck |
| 步骤 4 启动 + 接通 S1–S4 | **③** | 需要 Decky 运行时 |
| 步骤 5 `status()` 首检 | **③** | 必须解析**真**路径，不注入 §1.5 env |
| 步骤 6(a) 合成树 unittest | ① 已跑 / 任意 Linux 可复跑 | 只是额外确认 Linux 语义，**不是必须、更不是只能 Deck** |
| 步骤 6(b) 交互式干跑 | ① / 任意 Linux | `main.py:30-33` 的 shim 让普通 Python 即可 import，不用 Decky 运行时 |
| 步骤 7 快速迭代循环 | ②（重建）+ ③（生效） | 前端产物在 ② 出、在 ③ 重载 |
| 步骤 8 V#/F# 闭环 | **③**（A/B 组部分可在 ②） | 见 §0.3「只有这些必须是 Deck」 |
| 步骤 9 手柄 DoD + 故障注入 | **③** | Game Mode 手柄操作 |
| 步骤 10 证据回写 | ① | 把真机留档写进 [VERIFICATION.md](VERIFICATION.md) |

### 0.3 只有这些**必须**是 Deck

- QAM / Game Mode / 手柄 11 项操作（G1 的 unmount 清理也在这里观察）
- V15 / V16 —— 启动 RimWorld 再退出，看它是否重写 `ModsConfig.xml`、是否把点号兄弟目录当成 MOD
- V19 —— 真实社区 ZIP 的 `strip_single_root`
- V20 —— RimWorld **正在运行**时拒绝写（真进程检测，不能用 `DECKYMOD_GAME_RUNNING=1` 冒充）
- F1 microSD/exFAT、F2 跨设备 `EXDEV`、F3 Flatpak Steam
- 故障注入里的 `E_READONLY_FS` / `E_NO_SPACE` / `E_CROSS_DEVICE` 真实 errno

### 0.4 这些**不必**在 Deck

- **② 可用 CI 代劳**：[.github/workflows/build.yml](../.github/workflows/build.yml) 的 frontend job
  就是 `node20 + pnpm@9 + --frozen-lockfile + build`；提交 lockfile 后 push 触发即可，
  连「另找一台联网电脑」都省了。
- 步骤 6(a) 的 `unittest` 在实现阶段已于本机跑过（结论见 [ACCEPTANCE.md](ACCEPTANCE.md)，
  属实现阶段历史记录，不是本文任何真机步骤的实测输出）；Deck 上再跑只是额外确认 Linux
  语义（`fchmod` / `fchown` / `statvfs` / `geteuid`），任何 Linux 机都行。
- 步骤 6(b) 交互式干跑不用 Decky（`main.py:30-33` shim），普通 Python 即可，env 指向
  合成目录树，不碰真实游戏文件。
- 「读真实 `appmanifest_294100.acf` / `libraryfolders.vdf` / `ModsConfig.xml` 精确路径」
  这类，任何装了 Steam + RimWorld 的 Linux 环境都能做；因目标平台是 Deck，顺手在 Deck 做掉。

> **【历史快照，2026-11-13 已解】当前卡点在 ②，不是 ③**：本机无网、无 npm registry、
> 前端 8 个文件未编译、`dist/index.js` 不存在。真机部分当时还开始不了 —— 先按
> [RUNBOOK.md](RUNBOOK.md) 在任意联网环境（含 CI）产出产物，③ 才有意义。
> **2026-11-13 更新（见文首「状态更正」与 [VERIFICATION.md](VERIFICATION.md) §H）**：② 档
> 已在一台联网 Steam Deck 上闭环，`pnpm-lock.yaml` 与可加载 ESM `dist/index.js` 已生成
> 并回传；产物缺口已消除，卡点现转为 ③（部署 + QAM/手柄 + 真实游戏），而 RimWorld
> 294100 在该 Deck 未安装。本段为纯说明，**不改任何 V# / F# 状态**。

---

# 1. 实现方式 —— 调试所依赖的机制（为什么能这样调）

这一节解释「这套调试流程靠什么成立」。**先理解机制，再照 §2 执行**，否则容易把
开发期的临时手段误当成插件运行时行为。

## 1.1 可调试性设计（六个支点）

| # | 机制 | 代码位置 | 调试价值 |
| --- | --- | --- | --- |
| D1 | **后端 stdlib-only、零第三方依赖** | `deckymod/*.py`（12 模块） | 不需在 Deck 上 pip 装任何东西，SSH shell 里直接 `import` 即可跑 |
| D2 | **`import decky` 带 shim** | `main.py:30-33`（`try: import decky / except ImportError: decky = None`） | 脱离 Decky 运行时也能编译与 import，是 §2 步骤 6「零风险干跑」的前提 |
| D3 | **一切运行时信息从 env 解析** | `main.py:63-87` `_bridge_env()`、`deckymod/paths.py`、`deckymod/engine.py` | 用 env 把路径指向**合成目录树**，即可不碰真实 `Mods/` 与 `ModsConfig.xml`（见 §1.5） |
| D4 | **两阶段写操作 `after_confirm`** | `engine.install / set_enabled / uninstall`；`main.py:220/232/240` | `after_confirm=False` 只返回 `{phase:"confirm", plan, confirm_text, targets, log_path}`，**零写入**；`True` 才提交。真机上可先核对确认框里的 W1/W2 绝对路径 |
| D5 | **统一 envelope + `error_codes` RPC** | `deckymod/envelope.py`、`main.py:207-217` | 每个回复形状固定 `{ok, code, message, detail, data, rollback_available, log_path, ts}`；`error_codes()` 一次吐出全部 46 码，便于核对 UI 与后端一致 |
| D6 | **事务可逆** | `deckymod/journal.py`、`deckymod/fsops.py` | JSONL 日志 + 快照 + 隔离区（永不删除）+ 回滚，调试失败可退回，不怕把真机玩坏 |

补充：`tests/test_mvp.py` 的 `build_tree()` 自建合成 Steam 库 + `appmanifest_294100.acf`
+ `ModsConfig.xml` + Inbox ZIP，写操作全落在 `.decky-test-tmp/` 内。**这套用例本身就是
「实现方式」的一部分**——它在实现阶段已把 §1.2 的整条数据流在没有真机的情况下跑通
（结论见 [ACCEPTANCE.md](ACCEPTANCE.md)，属历史记录，不是本文真机步骤的输出）。

## 1.2 运行时架构与数据流

```
[Game Mode / QAM]
   └─ src/index.tsx  (definePlugin → <Content/>, state, useEffect 清理)
        └─ src/api.ts  invoke<T>(method, ...args)  ← 唯一守卫路径
             └─ @decky/api  call<Envelope<T>>("method", ...args)   [位置参数]
                  └─ Decky Loader（按锁定版本）
                       └─ getattr(Plugin, "method")(*args)          [V11/V13]
                            └─ main.py  _guard()  → 全捕获转 E_UNKNOWN
                                 └─ Engine.status/list_inbox/inspect/
                                      install/set_enabled/uninstall/
                                      rollback/history/refresh/recovery
                                      └─ deckymod/*（vdf / paths / archive /
                                         state_mutator / fsops / journal / registry）
                                           └─ 磁盘：W1 / W2 / W3（见 §1.4）
反向：decky.emit("deckymod:progress", payload)  → addEventListener(PROGRESS_EVENT, listener)
      （fire-and-forget；订阅/退订必须用同一稳定函数引用 —— V3 / G1）
```

**JSON-safe 契约**（`deckymod/json_safe.py` + `envelope.py`）：所有回复经
`to_json_safe()` 再 `json.dumps(allow_nan=False)`。`pathlib.Path`→`str`、
`bytes`→base64 标签 dict、`set`→有序 list、`datetime`→isoformat、`Decimal`→`str`、
非有限 float→`None`、`int > 2^53-1`（SteamID64）→字符串、非字符串 dict 键→`str`；
**禁用 `default=str`**。真机上若前端看到 `E_BACKEND_UNREACHABLE`，优先查是不是某个
返回值破坏了这条契约（V13）。

## 1.3 通信契约与 RPC 全清单（逐字，来自 `main.py`）

所有 RPC 均为 `async def`、**位置参数**（绝不传对象 / kwargs）；前导下划线名是保留
生命周期钩子，**不可**被当作 RPC 调用。

| 类型 | 方法签名 | 作用 | 写盘 |
| --- | --- | --- | --- |
| 读 | `status()` | 启动自检：游戏信息、W1/W2 已解析路径、启用列表、已装 MOD、待恢复事务、能力位、已知限制、日志路径 | 否 |
| 读 | `list_inbox()` | 列固定收件箱内 `*.zip`（无网络 / 无 Workshop） | 否 |
| 读 | `inspect(zip_path: str)` | 单 ZIP 干跑校验：归档 / 清单 / 冲突 / W1+W2 目标路径 | 否 |
| 读 | `history(limit: int = 50)` | 事务历史 | 否 |
| 读 | `refresh()` | 重解析路径 + `verify_on_open` 漂移检查 | 否 |
| 读 | `recovery()` | 列出未完结事务（PREPARED / APPLYING） | 否 |
| 读 | `error_codes()` | 返回 `{"codes":[{"code","category","message","rollback_available"}], "count":46}` | 否 |
| 写 | `install(zip_path: str, after_confirm: bool = False)` | 导入 → 安装（解压目录进 `Mods/<packageId>/`）；**装 ≠ 启用** | 是（两段） |
| 写 | `set_enabled(package_id: str, enabled: bool, after_confirm: bool = False)` | 在 `ModsConfig.xml` 插/删一行 `<li>` | 是（两段） |
| 写 | `uninstall(package_id: str, after_confirm: bool = False)` | 先停用，再把目录**同 FS 移入隔离区**（永不删除） | 是（两段） |
| 写 | `rollback(txn: str)` | 从隔离区 + `ModsConfig.xml.before` 快照恢复 | 是 |
| 生命周期 | `_main()` / `_unload()` / `_uninstall()` / `_migration()` | 加载 / 卸载 / 移除 / 迁移 | 见 §1.7 |

`main.py:39` `PROGRESS_EVENT = "deckymod:progress"`；`_progress()`（`:99`）发
`{stage, op, packageId, pct}`，各写 RPC 包了 `*:start` / `*:done`。前端 `index.tsx`
用它显示 busy / progress。

## 1.4 路径解析与三个写入根

`deckymod/paths.py` 的 `resolve(appid=294100, *, preflight=False) -> ResolvedPaths`
**每次动作重解析、不缓存**，12 步（调试时 `status()` 会把结果直接摆出来）：

1. `resolve_user()` — `DECKY_USER` / `DECKY_USER_HOME` / `pwd.getpwnam`，回退 `geteuid`
2. `_steam_roots()` — Flatpak `~/.var/app/com.valvesoftware.Steam` 优先 + native 候选
   （`.local/share/Steam`、`.steam/steam`、`.steam/root`、`.local/share/steam`）；
   **env `DECKYMOD_STEAM_ROOT` 插到最前**
3. `_find_libraryfolders_vdf()` — 三候选：`steamapps/`、`config/`、库根
4. `find_library_paths()` — 递归收集任意 `"path"` 键（兼容 schema 变体）
5. `_resolve_install_dir()` — 大小写不敏感扫 `appmanifest_<appid>.acf` 取 `installdir`
6. 去重；不唯一 → `E_GAME_NOT_FOUND` / `E_GAME_AMBIGUOUS`
7. Flatpak 命中 → **直接 `E_FLATPAK_PERMISSION` 拒绝**（绝不执行 `flatpak override`）
8. `game_root = realpath(LIB/steamapps/common/INSTALLDIR)`，带大小写回退
9. `mod_root = game_root/Mods`；`staging = game_root/.decky-staging`、
   `quarantine_root = game_root/.decky-quarantine`（**兄弟目录**，由 `E_STAGING_IN_MODS` 守卫）
10. `state_file = ${XDG_CONFIG_HOME|~/.config}/unity3d/Ludeon Studios/RimWorld by Ludeon Studios/Config/ModsConfig.xml`（**含空格、逐字大小写**）；`state_staging = Config/.decky-staging`
11. `proton_prefix = None`（本样板游戏是 Linux 原生，MVP 不写 Proton 前缀）
12. `is_posix_fs()` 读 `/proc/self/mountinfo` → `preflight_root` + `same_filesystem`
    跨设备守卫 → `_containment_check` 用 `realpath` 做包含性断言

### W1 / W2 / W3（来自 [README.md](README.md) §「三个写入根」）

| 根 | 路径 | 文件系统 | 写什么 |
| --- | --- | --- | --- |
| **W1** 状态 | `${XDG_CONFIG}/unity3d/Ludeon Studios/RimWorld by Ludeon Studios/Config/ModsConfig.xml` | 内部 SSD / POSIX | 启用列表 |
| **W2** 载荷 | `${STEAM_LIBRARY}/steamapps/common/${APP_INSTALL_DIR}/Mods/<packageId>/` | 游戏安装处，**可能是 microSD / exFAT** | MOD 目录 |
| **W3** 元数据 | `${DECKY_DATA}/journal`、`${DECKY_DATA}/snapshots`、`${DECKY_PLUGIN_LOG_DIR}` | Decky 托管 / 内部 SSD / POSIX | 日志、快照 |

- 每个写入根各有**同级暂存**；原子写模板：`mkstemp(同父目录) → 写 → fsync →
  fchmod(guarded) → chown(仅 euid==0) → os.replace → fsync(父目录)`。
- **`EXDEV(18)` 跨设备 `os.replace` → `E_CROSS_DEVICE`**，绝不跨 FS 重命名。
- **#4 唯一例外**：隔离区必须在 **W2 同一 FS**（`${GAME_ROOT}/.decky-quarantine/${TXN_ID}/`），
  否则 microSD↔SSD 移整个目录会失败；journal 仍记原路径 / 隔离路径 / txn id。
- 暂存 / 隔离**绝不建在 `Mods/` 内**（RimWorld 会扫含 `About/About.xml` 的子目录）——V16 待真机确认点号目录是否被忽略。

> ⚠️ `registry/registry.json` 里 `allowed_write_roots` 为 5 项；`deckymod/registry.py`
> 的 `DEFAULT_REGISTRY_PATH` 是**相对插件根目录**定位 `registry/registry.json` 的。
> **部署时整棵 `registry/` 必须一起带**，否则启动直接失败（见 §2 步骤 3）。

## 1.5 env 注入点完整表（真机干跑的核心开关）

`main.py:63-87` 的 `_bridge_env()` 把 Decky 模块属性拷进 `os.environ`（**幂等、不覆盖
已有值**）：`DECKY_HOME`、`DECKY_USER`、`DECKY_USER_HOME`、
`DECKY_PLUGIN_SETTINGS_DIR`、`DECKY_PLUGIN_RUNTIME_DIR`、`DECKY_PLUGIN_LOG_DIR`、
`DECKY_PLUGIN_DIR`。⚠️ **V2**：属性名必须按锁定 Loader 版本核对；名字错了会**静默**
回退，`user_home` 解析错，后面全歪。

调试用注入点（把前几个指向一棵**合成目录树**即可零风险验证）：

| env | 来源 | 用途 | 风险 / 备注 |
| --- | --- | --- | --- |
| `DECKYMOD_STEAM_ROOT` | `paths.py` | 覆盖 Steam 根候选，插到最前 | 干跑主开关 |
| `XDG_CONFIG_HOME` | `paths.py` | 覆盖 W1 `ModsConfig.xml` 所在配置根 | 干跑主开关 |
| `DECKYMOD_INBOX` | `engine.py` | 固定收件箱 | 仍走 `E_PATH_ESCAPE` 包含性检查 |
| `DECKYMOD_EXTRA_IMPORT_ROOT` | `engine.py` | 可选 OSK 路径白名单 | 同上，不能越界 |
| `DECKYMOD_DATA` | `engine.py` | journal / snapshots / 日志落点 | 干跑时指向合成树 |
| `DECKYMOD_GAME_RUNNING` | `engine.py:79` `_check_not_running()` | `1/true/yes` → 强制 `E_GAME_RUNNING` | ⚠️ **V20**：这只是保守 dev 检查，**不是真进程检测**，真机必须替换并验证 |
| `DECKY_USER` / `DECKY_USER_HOME` | `fsops.resolve_user()` | 属主解析 | ⚠️ V2 |
| `DECKY_PLUGIN_RUNTIME_DIR` / `DECKY_PLUGIN_LOG_DIR` | `main.py` / `journal.py` | 日志落点 | ⚠️ V2 |

> **纪律**：这些注入是**开发 / 干跑手段**，不是插件运行时假设。正式验收 DoD 时**不要**
> 注入，让 `status()` 解析**真实**的 Steam 库与配置路径，否则验的是假路径。

## 1.6 四个观测面

| 面 | 位置 / 手段（待执行） | 看什么 |
| --- | --- | --- |
| **S1 插件自身日志** | `${DECKY_PLUGIN_LOG_DIR}/deckymod.log`（`journal.py:44` `log_path = log_dir/deckymod.log`；`main.py:52-58` 的 `_log()` 也会镜像写入） | `_main` 启动、每个 RPC、`E_*`、事务状态机、`_guard` 捕获的异常与 traceback（**只进日志，不进前端**） |
| **S2 事务日志** | `${DECKY_DATA}/journal/rimworld.jsonl` + `${DECKY_DATA}/snapshots/${TXN_ID}/` | `PREPARED→APPLYING→COMMITTED / ROLLED_BACK / ROLLBACK_FAILED`；`installed()` 靠它重建 |
| **S3 框架日志** | `journalctl -u plugin_loader -f` ⚠️ 服务名按锁定版本核实（V1/V4） | 插件加载 / import 失败、`getattr` 派发、生命周期钩子（V11/V12/V13） |
| **S4 前端** | Decky Developer 的 CEF remote debugging → `http://<deck-ip>:<port>` ⚠️ 端口 / 入口按锁定版本核实（V1/V3） | React 渲染、焦点顺序、`call()` 返回值、toast、弹窗、console |

另外两个「不用翻日志就能看」的观测点：

- **`status()`**：把 W1 / W2 / quarantine / staging / flatpak / fs_posix / uid-gid-home
  直接摆出来。**上机第一件事就是它**——路径解析错了，后面全是白测。
- **`error_codes()`**：一次拿全 46 码，核对 UI 显示与后端一致。

> 所有日志命令均为**待执行**；真实输出、退出码、errno 一律留空，由真机实跑填写。

## 1.7 事务、可逆性与回滚（为什么调试失败也不怕）

- 状态机（`journal.py`）：`PREPARED → APPLYING → COMMITTED | ROLLED_BACK | ROLLBACK_FAILED`；
  `pending()` 返回 PREPARED / APPLYING。
- 卸载 = **同 FS `os.replace(src, qdir)` 移入隔离区，永不删除**；事件 `MOD_UNINSTALLED`
  记 `{from_path, quarantine, txn_quarantine}`。
- 回滚 = 从隔离区恢复目录 + 从 `ModsConfig.xml.before` 快照恢复状态字节。
- 安装替换已存在目录时，先把旧目录 `os.replace` 到
  `quarantine_root/txn/<pid>.replaced` 并记 `replaced_old`，**绝不静默删除**。
- `_unload()`（G1）：只清内存 + 刷日志，**不改游戏状态**；未完结事务留到下次打开报
  `E_RECOVERY_PENDING`。`_uninstall()` 不删用户游戏数据 / 隔离区 / journal。
- ⇒ **调试纪律**：不要手动清 `.decky-quarantine/`，否则回滚链断裂。

## 1.8 错误体系与故障注入

统一 envelope（§1.2）：`{ok, code, message, detail, data, rollback_available, log_path, ts}`。
[ACCEPTANCE.md](ACCEPTANCE.md) §5.2 的 **46 码**按 13 类分组（bridge 2、internal 1、
discovery 2、capability 1、safety 7、environment 1、planned 2、import 12、conflict 2、
fs 6、info 1、state 4、txn 5）；**恰好 4 码默认 `rollback=True`**：
`E_VERIFY_FAILED`、`E_OP_FAILED`、`E_RECOVERY_PENDING`、`E_ROLLBACK_FAILED`。

约束执行型消息（`E_READONLY_FS` / `E_ROOT_OWNED` / `E_ACCESS` / `E_LOADER_REQUIRED` /
`E_PROTON_PREFIX_MISSING` / `E_FLATPAK_PERMISSION`）**不得**出现
`steamos-readonly disable` / `sudo` / `flatpak override` /「会替你装加载器或前缀」措辞。
每条错误：显示 code 小字 + 短提示 + 日志路径、A/B 可关、**不吐 traceback**。
故障注入矩阵见 §5。

## 1.9 三条硬约束在调试中的体现（不得在真机上破例）

| 约束 | 实现 | 调试时怎么自查 |
| --- | --- | --- |
| **不默认关闭 SteamOS 只读** | `requires_readonly_toggle:false`；5 个 `allowed_write_roots` 全在 `$HOME`/用户库/microSD/Decky 托管目录；`EROFS`→`E_READONLY_FS` 明确拒绝 | 全程不执行 `steamos-readonly disable`；注入只读挂载看是否拒绝且「no files were changed」 |
| **不假设 root** | 也不假设非 root：`pwd.getpwnam(DECKY_USER)`，仅 `geteuid()==0` 时对自己产物 `chown`；属主不符 → `E_ROOT_OWNED` / `E_STATE_OWNED` 拒绝而非修权限；非 POSIX 挂载跳过属主校验 | 开发期开 SSH / 重启 loader 是**一次性准备**，绝不写进插件运行时假设 |
| **不宣称全游戏通用一键装** | `universal_one_click:false`、`max_enabled_games_in_mvp:1`、仅 `rimworld` 为 `enabled`；`factorio` / `valheim` 为 `planned` | 别在真机上顺手「启用」别的描述符；Harmony / 顺序限制如实确认，别优化掉 |

---

# 2. 实现步骤 —— 详细、逐步、可照做

> 以下步骤**全部待执行**。Shell 块默认在 SteamOS 的 bash 环境执行；
> 若在开发机侧执行，注意 [RUNBOOK.md](RUNBOOK.md) §0 的「bash 兼容 shell」口径
> （Windows PowerShell 的 `curl` 是 `Invoke-WebRequest` 别名，不认 `-w/-o/-H`）。

## 步骤 0 — 前置门槛（任一不满足即停，保留全部 `OPEN`）

| # | 检查 | 期望 | 不满足时 |
| --- | --- | --- | --- |
| 0.1 | [RUNBOOK.md](RUNBOOK.md) C1–C4 已在联网机器实跑完毕 | 有逐字留档、`pnpm-lock.yaml`、`dist/index.js`（非空、cjs） | **停止**，回 RUNBOOK；不得用未编译产物上机 |
| 0.2 | `pnpm run typecheck`（`tsc --noEmit`）零 `error TS...` 行 | 退出码 0 | 报错是 V3 证据，逐字记录、保留 `OPEN`，**不放宽类型** |
| 0.3 | V3 的 API 形状按锁定版本核对过 | `definePlugin` / `call` / `addEventListener` / `showModal` / `Focusable` / `TextField` OSK 形状有结论 | 保留 `OPEN`，上机时重点观测 S4 |
| 0.4 | 一台 Steam Deck（SteamOS）、已装 Decky Loader、RimWorld（AppID 294100，Linux 原生） | 游戏能正常启动并生成过 `ModsConfig.xml` | 无 Core 文件会导致 `E_STATE_MISSING` / `E_CORE_MISSING` |
| 0.5 | Debug 通道可用（SSH 或 Deck 本地终端） | 能读 `${DECKY_PLUGIN_LOG_DIR}` 与 `${DECKY_DATA}` | 无法观测 ⇒ 无法闭环，停止 |
| 0.6 | 明确「开发准备 ≠ 运行时假设」 | 记录在案 | 见 §1.9 |

> 如果 0.1–0.3 尚未完成（**当前正是这个状态**），正确做法是**先做 RUNBOOK**，
> 而不是带着未编译的 `src/` 上真机。

## 步骤 1 — 产出可部署产物（在联网机器，指向 RUNBOOK）

按 [RUNBOOK.md](RUNBOOK.md) §2–§5 顺序实跑并**逐字留档**：

| RUNBOOK 命令 | 产出 | 回写目标 |
| --- | --- | --- |
| C1 `git ls-remote ... HEAD` / `--tags` | 模板 commit（40 位 SHA） | V1 |
| C2 `curl ... /releases/latest` + `node -e` | Decky Loader `tag_name` / `published_at` | V1 |
| C3 `npm view @decky/api version` / `@decky/ui version` | 精确版本号（无 `^`/`~`） | V1（并影响 V3） |
| C4 `pnpm install` → `tsc --noEmit` → `rollup -c` → `--frozen-lockfile` | `pnpm-lock.yaml` + `dist/index.js` | V8 |

**验收形态**（占位符，不是实测值）：`created dist/index.js in <Xs>`、`dist/index.js`
存在且非空、`lockfileVersion: <N>`、退出码 0。⚠️ 若 `@decky/ui` 为 `404`，按
RUNBOOK C3 处置：**跳过写入、留 404 证据、V1/V3 保留 `OPEN`**，不臆造版本。

## 步骤 2 — Deck 侧一次性准备（开发动作，不是插件行为）

1. Decky Loader 设置里打开 **Developer mode**。⚠️ 入口 / 名称按 V1 锁定的 Loader 版本核实。
2. 确认插件目录 `~/homebrew/plugins/<插件名>/`（`$HOME` 可写，**不需要**动只读根文件系统）。
   ⚠️ **V4**：具体路径、`main.py` 是否根级、`plugin.json` 是否根级，按锁定模板 commit 核实。
3. 打通 SSH 或本地终端用于读日志（`scp`/`rsync` 后续迭代用）。
   > 这是**开发期一次性准备**，绝不写进插件运行时假设（§1.9）。

## 步骤 3 — 部署整棵目录（文件清单）

从仓库副本拷贝（`rsync -av ... deck@<deck-ip>:~/homebrew/plugins/<插件名>/`，待执行）。
**必须一起带 `registry/`**——`deckymod/registry.py` 的 `DEFAULT_REGISTRY_PATH`
是相对插件根目录定位的，漏拷直接启动失败。

| 必带 | 文件 |
| --- | --- |
| 清单 | `plugin.json`（`name "Decky MOD Manager"` / `api_version 1` / `flags []`，⚠️ V5 核实精确字段） |
| 入口 | `main.py` |
| 后端 | `deckymod/` 全 12 个 `.py`（`errors / envelope / json_safe / fsops / vdf / paths / archive / state_mutator / registry / journal / engine / __init__`） |
| 数据 | `registry/registry.json`、`registry/games/*.json`、`registry/loaders/*.json` |
| 前端产物 | **`dist/index.js`**（rollup 输出的 cjs，⚠️ V6 核实 format/externals） |
| 构建元数据 | `package.json`（便于在机上复现 / 核对版本） |

可不带：`src/`、`tests/`、`docs/`、`.github/`、`tsconfig.json`、`rollup.config.js`
（但若要机上重建，则一并带上并核对 ⚠️ V7）。

## 步骤 4 — 启动 + 接通 4 个观测面（命令待执行）

```bash
# S1 插件自身日志（⚠️ 实际 DECKY_PLUGIN_LOG_DIR 以 status() / V2 核实为准）
tail -f "$DECKY_PLUGIN_LOG_DIR/deckymod.log"

# S2 事务日志
tail -f "$DECKY_DATA/journal/rimworld.jsonl"
ls -la "$DECKY_DATA/snapshots/"

# S3 框架日志（⚠️ 服务名按锁定版本核实）
journalctl -u plugin_loader -f

# S4 前端（Developer mode 的 CEF remote debugging，⚠️ 端口/入口按锁定版本核实）
# 浏览器打开 http://<deck-ip>:<port>
```

然后 QAM → 插件标签页触发加载，确认：
- S1 出现 `Decky MOD Manager loaded (RimWorld MVP, selection A)` 与 `plugin loaded`；
- S3 无 import 报错 / `getattr` 派发异常；
- 标签页能渲染（不是空白 / 报错弹窗）。

> 三条对应 **V11 / V12 / V13**：Plugin 类形状、生命周期钩子、`call` 结果传播。
> ⚠️ 若插件根本没出现，先查 S3 的 import 失败，别急着重装 Decky。

## 步骤 5 — `status()` 首检（路径解析核对，最重要的一步）

在 QAM 里打开插件（或 S4 console 里直接调用 `status` RPC），拿到 envelope 后逐项核对：

| 期望字段（以实跑为准） | 应指向 | 不对时的处理 |
| --- | --- | --- |
| `paths.w1_state_file` | 真实 `${XDG_CONFIG_HOME}/unity3d/Ludeon Studios/RimWorld by Ludeon Studios/Config/ModsConfig.xml`（**含空格、逐字大小写**） | `E_STATE_MISSING` → V14 |
| `paths.w2_mod_root` | 真实 `.../steamapps/common/<installdir逐字>/Mods/` | `E_GAME_NOT_FOUND` / `E_GAME_AMBIGUOUS` → V9/V10 |
| `paths.quarantine_root` | `${GAME_ROOT}/.decky-quarantine`（**W2 同 FS、Mods 的兄弟**） | 跨 FS → F2 / `E_CROSS_DEVICE` |
| `paths.staging` | `${GAME_ROOT}/.decky-staging`（兄弟，不在 `Mods/` 内） | `E_STAGING_IN_MODS` |
| `flatpak` | 应为 false；若为 true 会直接 `E_FLATPAK_PERMISSION`（设计行为） | F3 |
| `fs_posix` | 内部 SSD 应 true；microSD/exFAT 应 false 并触发信息级 `E_FS_NO_POSIX` | F1 |
| `uid / gid / user_home` | 真实游戏用户（**不是 root**） | 静默错 → **V2**（`_bridge_env` 属性名） |
| `state.activeMods` | 至少含 `ludeon.rimworld` 且**第一** | `E_CORE_MISSING` / `E_STATE_CORRUPT` |
| `state.fp` | 当前 `ModsConfig.xml` 指纹 | 后续 `verify_on_open` 靠它比对 |
| `pending_recovery` / `recovery_needed` | 应为无 | 有 → `E_RECOVERY_PENDING`，先 Recover / Rollback |

> **纪律**：这一步**不要**注入 §1.5 的任何 env，让它解析真路径。
> 同时调一次 `error_codes()` 核对 46 码与 UI 一致。

## 步骤 6 — 后端零风险干跑（不碰真实 `Mods/` / `ModsConfig.xml`）

利用 D1/D2/D3：后端 stdlib-only + `import decky` shim，可**脱离 Decky 运行时直接
import**，因此本步骤不必在 Deck、更不必有 Decky（见 §0.2 / §0.4）。

**(a) 合成树用例：本机已跑，Linux 复跑可选**（待执行）：

```bash
cd <插件目录>
python3 -m unittest discover -s tests -v
python3 tests/_verify.py          # compileall + registry/**/*.json 校验
```

期望形态（占位符，不是实测值）：`Ran 33 tests ... OK`、`compileall: OK`、
`json files: 12 bad: 0`。实现阶段已在本机跑过（历史记录见 [ACCEPTANCE.md](ACCEPTANCE.md)，
不是本文真机步骤的输出）；如需额外确认 Linux 语义（`fchmod` / `fchown` / `statvfs` /
`geteuid` 全部存在的路径），按 §0.4 在**任意 Linux 机**复跑即可，**不要求也不必是 Deck**。
写操作全落在 `.decky-test-tmp/` 内，对真实游戏零影响。

**(b) 交互式干跑**（把 §1.5 的 env 指向一棵**合成目录树**后；命令待执行）：

```python
# 先在 shell 里 export：DECKYMOD_STEAM_ROOT / XDG_CONFIG_HOME /
# DECKYMOD_INBOX / DECKYMOD_DATA / DECKYMOD_EXTRA_IMPORT_ROOT 指向合成树
from deckymod import paths
r = paths.resolve(294100, preflight=False)   # 仅解析，不写
print(r.to_json_safe())                       # 核对 W1/W2/staging/quarantine

from deckymod.engine import Engine
e = Engine()
print(e.inspect("<abs>/inbox/test.zip"))     # dry-run，零写入
print(e.install("<abs>/inbox/test.zip"))     # after_confirm=False → 仅 confirm 载荷
```

**关键**：`after_confirm=False` 返回 `{phase:"confirm", plan, confirm_text, targets,
log_path}`，`targets` 里是 W1/W2 两个**绝对路径**——真机上先核对这两个路径再决定是否
提交 `after_confirm=True`。任何写操作都不要在没有确认框核对前直接提交。

## 步骤 7 — 前端加载与快速迭代循环

| 改动 | 重建 / 部署（待执行） | 生效方式 | 观测点 |
| --- | --- | --- | --- |
| `src/*.tsx` / `src/*.ts` | 联网机器 `pnpm run build` → `rsync dist/index.js` | QAM **关掉 / 重开标签页**（React unmount/remount；`index.tsx` 的 `useEffect` cleanup 会清订阅 / timer / generation counter） | S4、QAM 焦点 |
| `deckymod/*.py` 或 `main.py` | `rsync` → **重启 plugin_loader** | Python 进程**不随** QAM 重开重载 | S1 `_main` 行、S3 |
| `registry/**` 或 `plugin.json` | `rsync` → 重启 loader | 同上 | S1、S3 |

重启 loader 的优先顺序（⚠️ 具体命令 / 是否需要提权按 V1/V4 核实的锁定版本为准）：
1. Decky 设置里**禁用 → 启用**插件（优先，无需提权）；
2. 否则重启 plugin_loader 服务（⚠️ 服务名 / 提权方式待核实）；
3. 再不行重启 Deck。

> 这是**开发期一次性动作**，不构成插件运行时 root 假设（§1.9）。
> 每次重启后**先看 S1 的 `_main` 行，再调一次 `status()`**。

## 步骤 8 — V# / F# 逐项闭环（按风险分组）

每一项都按「**观测方法 → 期望 → 需记录的值 → 失败判据 → 对应 V#**」执行。
所有记录值**留空待填**，不得用本机 Windows 的结果冒充真机值。

### A 组：能不能加载起来（V1、V2、V4–V8、V11–V13）

| V# | 观测方法 | 需记录的真机值 |
| --- | --- | --- |
| V1 | 核对 `package.json` 精确版本串、Loader 设置里的版本 | 模板 commit SHA、Loader `tag_name`、`@decky/api`/`@decky/ui` 精确版本 |
| V2 | `status()` 的 `uid/gid/user_home` + `_bridge_env()` 的 7 个属性名 | 实际属性名清单、是否与环境已导出值一致 |
| V4 / V5 | 目录清单、`plugin.json` 字段 | `main.py` 层级、`api_version`/`flags`/根标志拼写 |
| V6 / V7 | `dist/index.js` 是否 cjs、`external` 是否对、`tsconfig` 与 React 版本是否匹配 | 产物格式、externals、TS 版本 |
| V8 | C4 留档 | `pnpm-lock.yaml` 的 `lockfileVersion`、`dist/index.js` 字节数 |
| V11 | S3 import / getattr | Plugin 类是否需基类、哪些方法必须 `async def` |
| V12（G1） | 关标签页 → 重开；禁用 / 卸载插件 | 无残留 watcher/timer；PREPARED/APPLYING 是否报 `E_RECOVERY_PENDING` |
| V13 | 故意让后端抛异常 / 返回非序列化值 | 前端是否收到 `E_BACKEND_UNREACHABLE` envelope；`decky.emit` 是否被 await |

### B 组：路径解析对不对（V9、V10、V14、V17、V18、F1、F2、F3）

| V# | 观测方法 | 需记录的真机值 |
| --- | --- | --- |
| V9 | 打开 `steamapps/appmanifest_294100.acf` | `installdir` **逐字大小写**（≠ 商店标题） |
| V10 / V17 | 找到 `libraryfolders.vdf`，用 `parse_vdf` / `find_library_paths` / `get_installdir` 跑真实文件 | 文件在 `steamapps/` 还是 `config/`、键大小写、条目 schema、有无注释 / 转义引号 |
| V18 | 大小写回退在 ext4 与 microSD/exFAT 上各试一次 | `os.listdir()` 命中真实大小写、`realpath` 包含性成立 |
| V14 | `status().paths.w1_state_file` | `$XDG_CONFIG_HOME` 实际值、含空格路径逐字、RimWorld 1.4/1.5/1.6 差异 |
| F1 | **把游戏装到 microSD**，读 `/proc/self/mountinfo` | 挂载点、FS 类型、`noexec` 与否、`fchmod`/`fchown` 的实际 errno |
| F2 | 对比 `${DECKY_DATA}`（内部 SSD）与 W2（microSD） | 是否跨设备；尝试跨 FS rename 时的 `EXDEV(18)` 行为 |
| F3 | 若 Steam 为 Flatpak（`com.valvesoftware.Steam`） | 应 **直接 `E_FLATPAK_PERMISSION` 拒绝**；确认从未执行 `flatpak override`、从未授 `home`/`host` |

> F1/F2 正是 **#4「隔离区必须同 W2 FS」例外**的验证点：跨设备时若隔离区放在
> `${DECKY_DATA}`，`os.replace` 整个 MOD 目录会失败。

### C 组：写语义是否被游戏接受（V15、V16、V19、V20）—— **真机才能验，风险最高**

| V# | 观测方法 | 需记录的真机值 | 失败判据 |
| --- | --- | --- | --- |
| **V15** | 装 → 启用（`<li>` 追加到 `</activeMods>` 前）→ **退出 RimWorld 再进游戏** → Refresh | 游戏是否重写 `ModsConfig.xml`；注释 / `<version>` / `knownExpansions` / 缩进 / 编码是否保留；`verify_on_open` 是否报 `E_STATE_EXTERNAL`；重写发生在何时 | 游戏不认该文件、重序列化痕迹、或 Core 位置被改 → 记录并保留 `OPEN` |
| **V16** | 确认 `${GAME_ROOT}/.decky-staging/`、`.decky-quarantine/` 存在后启动游戏 | RimWorld 是否把点号兄弟目录当成 MOD 扫入（查 `About/About.xml`） | 被扫入 → 记录并保留 `OPEN`（当前以 `E_STAGING_IN_MODS` 守卫置于 `Mods/` 外） |
| **V19** | 用几种**真实社区 ZIP**（顶层 `About/`、单包裹目录、多文件）走 `inspect` + `install` | `strip_single_root` 后 `About/About.xml` 是否落到 `Mods/<packageId>/About/About.xml` 顶层 | 落到 `<wrapper>/About/...` 或触发 `E_VERIFY_FAILED` → 记录（本地已修过一次 members 映射反转 bug，真机必须复验） |
| **V20** | **让 RimWorld 正在运行**时尝试写操作 | 真机必须实现并验证「运行中拒绝写」；确认 Decky/Steam 暴露了什么可用机制 | 仅用 `DECKYMOD_GAME_RUNNING=1` 冒充通过 → **不算闭环**，保留 `OPEN` |

## 步骤 9 — 手柄 DoD 验收 + 故障注入

按 [ACCEPTANCE.md](ACCEPTANCE.md)：**DoD = 11 项手柄操作 + G1/G2/G3 + 46 码表**。
在 Game Mode 里**只用十字键 + A/B** 走一遍（禁止悬停 / 拖放 / 长按 / 右键 / 滚轮 /
触摸 / 触控板 / 陀螺仪 / Steam/X/Menu 键；OSK 仅用于可选路径框）。

1. QAM → 标签页首元素自动获焦；
2. 浏览 Inbox（上下 / A 预览 / B 返回）；
3. 导入并确认（确认框显示 W1+W2 **两个绝对路径**）；
4. 查看已装列表；
5. 启用 / 禁用（**单次 A、无二次确认**，toast + History→Rollback）；
6. 卸载并确认（显示精确 mod id，破坏性确认默认焦点在 Cancel）；
7. 回滚并确认（History → 选 txn → 确认）；
8. 阅读 / 关闭错误（code 小字 + 短提示 + 日志路径，**无 traceback**，A/B 可关）；
9. Refresh（busy 可见、标签页获焦自动重扫）；
10. （可选）OSK 路径框，可完全跳过；
11. **状态跨「离开并重新打开 QAM 标签页」存活**（证明靠 journal + 磁盘，非 React state）。

破坏性确认（卸载 / 回滚 / Replace / 清空隔离区 / Recover「Roll back」）默认焦点落在
**Cancel**；单次未确认的 A 绝不触发破坏性动作；禁用项移出焦点序；长文十字键滚动；
操作后焦点回已知锚点并保留「Last result」行。

**G1**：关标签页后 S1/S4 确认无残留 watcher/timer/订阅；generation counter 丢弃在途 RPC
但**后端写事务绝不中止**（原子完成，下次打开从 journal 读）。
**G2**：三条硬约束在真机重证（§1.9）。**G3**：全部 V#/F# 有真机结论后才可能关闭，
当前 `OPEN`。

## 步骤 10 — 证据回写

按 §7 的规则与模板把真机实测值写入 [VERIFICATION.md](VERIFICATION.md)；
**只有拿到真机输出 + 设备/版本/日期、经人工核对后**才允许把某个 `status` 从 `OPEN`
调整（本清单**不执行**任何状态变更）。DoD 签核清单见
[ACCEPTANCE.md](ACCEPTANCE.md) §「Sign-off checklist」。

---

## 3. V# / F# ↔ 调试步骤 对照矩阵（23 项全覆盖，全部 `OPEN`）

| 项 | [VERIFICATION.md](VERIFICATION.md) 行 | 闭环步骤 | 分组 |
| --- | --- | --- | --- |
| V1 | 30 | 步骤 1（RUNBOOK C1–C3）、步骤 8-A | A |
| V2 | 39 | 步骤 5（uid/gid/home）、步骤 8-A | A |
| V3 | 48 | 步骤 0.3、步骤 7（S4）、步骤 8-A | A |
| V4 | 71 | 步骤 2、3、8-A | A |
| V5 | 77 | 步骤 3、8-A | A |
| V6 | 83 | 步骤 3、7、8-A | A |
| V7 | 89 | 步骤 3、7、8-A | A |
| V8 | 95 | 步骤 1（RUNBOOK C4）、8-A | A |
| V11 | 105 | 步骤 4、8-A | A |
| V12 | 112 | 步骤 7、9（G1）、8-A | A |
| V13 | 120 | 步骤 4、8-A | A |
| V9 | 131 | 步骤 5、8-B | B |
| V10 | 140 | 步骤 5、8-B | B |
| V17 | 151 | 步骤 8-B | B |
| V18 | 158 | 步骤 8-B | B |
| V14 | 168 | 步骤 5、8-B | B |
| V15 | 175 | 步骤 8-C（**最高风险**） | C |
| V16 | 185 | 步骤 8-C | C |
| V19 | 198 | 步骤 8-C | C |
| V20 | 208 | 步骤 8-C | C |
| F1 | 219 | 步骤 8-B（microSD 实机） | B |
| F2 | 228 | 步骤 8-B（跨设备） | B |
| F3 | 236 | 步骤 8-B（Flatpak） | B |

---

## 4. 快速迭代循环（改动 → 生效 → 观测）汇总

| 改动类型 | 动作（待执行） | 生效方式 | 先看哪个观测面 |
| --- | --- | --- | --- |
| 前端 `src/` | `pnpm run build` → `rsync dist/index.js` | QAM 标签页关 / 开 | S4 + 焦点 |
| 后端 `deckymod/` / `main.py` | `rsync` → 重启 plugin_loader | 进程重载（不随 QAM 重开） | S1 `_main` → 再 `status()` |
| `registry/**` / `plugin.json` | `rsync` → 重启 loader | 同上 | S1 / S3 |
| 只改文档 | 无需重载 | — | — |

每次循环都重复：`看 S1 的 _main → 调 status() → 才动写操作`。

---

## 5. 故障注入矩阵（主动制造失败，别只读代码）

| 注入方式（待执行） | 期望码 | 观测面 | 关联 V# |
| --- | --- | --- | --- |
| 删 / 改名 `appmanifest_294100.acf`，或造两个库都命中 | `E_GAME_NOT_FOUND` / `E_GAME_AMBIGUOUS` | UI + S1 | V9/V10 |
| 放含 `../` 的 ZIP | `E_ZIP_SLIP` | UI + S1 | — |
| 放含 `.exe` / `.dll` / 符号链接的 ZIP | `E_UNSAFE_ENTRY` | UI | — |
| 放超大 / 超高压缩比 ZIP | `E_ZIP_BOMB` | UI | — |
| 放重复 `packageId` | `E_DUPLICATE` | UI | — |
| 让 `Mods/<id>/` 已存在且未被本插件管理 | `E_FILE_COLLISION` | UI | — |
| 把 `ModsConfig.xml` 里 `ludeon.rimworld` 删掉 / 挪位 | `E_CORE_MISSING` / `E_STATE_CORRUPT` | UI | V15 |
| 游戏运行中改 `ModsConfig.xml` 再 Refresh | `E_STATE_EXTERNAL` | UI + S1 | V15/V20 |
| 把 `ModsConfig.xml` 换成符号链接 / 移走 | `E_STATE_SYMLINK` / `E_STATE_MISSING` | UI | — |
| 塞满磁盘 / 指向只读挂载 | `E_NO_SPACE` / `E_READONLY_FS` | UI + S1 | F1 |
| 在 microSD 与内部 SSD 之间制造跨设备 rename | `E_CROSS_DEVICE` | S1 | F2 |
| 中途杀 plugin_loader 造 PREPARED / APPLYING | `E_RECOVERY_PENDING` → Recover / Rollback | S2 + UI | V12 |
| 破坏隔离区让自动回滚失败 | `E_ROLLBACK_FAILED` | UI + S1 | V12 |
| Flatpak 版 Steam | `E_FLATPAK_PERMISSION` | UI | F3 |

每条错误必须同时满足：**显示 `code` 小字 + 短提示 + 日志路径、A/B 可关、不吐
traceback、约束执行型消息不出现** `steamos-readonly disable` / `sudo` /
`flatpak override` 措辞。

---

## 6. 症状 → 定位速查表（待真机填写实测结论）

| 症状 | 先看 | 可能原因 / V# | 处置 |
| --- | --- | --- | --- |
| QAM 里没有这个插件 | S3（框架日志） | 目录 / `plugin.json` / `dist/index.js` 缺失；V4/V5/V6 | 核对步骤 3 文件清单 |
| 插件面板空白 / 报错 | S4（CEF console） | `definePlugin` / 组件 prop 形状；V3 | 记录 TS/运行时报错，**不放宽类型** |
| `E_BACKEND_UNREACHABLE` | S1 + S3 | Python 异常 / 非序列化返回；V13 | 查 `_guard` 的 traceback（只在日志） |
| `status()` 里 `user_home` 是 root / 空 | S1 | `_bridge_env` 属性名不符；V2 | 核对 7 个属性名 |
| `E_GAME_NOT_FOUND` | `status().paths` | `libraryfolders.vdf` schema / `installdir`；V9/V10/V17 | 记录真实文件内容 |
| `E_STATE_MISSING` | W1 路径 | 路径含空格 / 版本差异；V14 | 核对逐字大小写 |
| 装完进游戏 MOD 没生效 | W1 + S2 | 文件被游戏重写 / 顺序；V15/V19 | 看 `E_STATE_EXTERNAL` 与 `<li>` 位置 |
| 卸载后想恢复却找不到 | S2 + 隔离区 | 手动清过 `.decky-quarantine/` | 不要清隔离区（§1.7） |
| 运行中仍能改 MOD | S1 | V20 仍是保守 env 检查 | 必须实现真检测，不算闭环 |

---

## 7. 证据回写规则与模板

### 规则

1. **逐字**粘贴 stdout / stderr，每条附**退出码、执行日期、机器 OS、SteamOS 版本、
   锁定的模板 commit 与 Decky Loader 版本、`node --version` / `pnpm --version`**。
2. 记录**真机实测值**：路径逐字大小写、FS 类型、`errno`、`installdir`、mountinfo 行、
   `ModsConfig.xml` 前后 diff、`dist/index.js` 字节数、`lockfileVersion`。
3. 只有「真机输出 + 设备/版本齐全 + 人工核对」才允许调整 `status`；
   **本清单不执行任何状态变更**，也不得把某轮失败输出当作 `CLOSED` 依据。
4. 失败 / 报错是**证据**，逐字记录并保留 `OPEN`；严禁 mock、跳过 `tsc`、伪版本、
   放宽类型来「让它变绿」。
5. V3 的 `tsc` 报错另附 V3 并写明「因 API 形状未确认而保留 `OPEN`」。
6. 回写分工沿用 [RUNBOOK.md](RUNBOOK.md) §6：C1–C3 → V1，C4 → V8；本文 §2 步骤 4–9
   的真机观测 → V2、V4–V7、V9–V20、F1–F3 及 DoD。

### 模板（占位符，非实测值）

```
### V<n> — <标题>
- status: OPEN（本 ONDEVICE 清单不改状态；是否调整由后续轮次人工判定）
- 设备: <SteamOS 版本> / <Decky Loader tag_name> / <template commit 40-hex>
- 执行日期: <date>   执行人/机器: <who>
- 观测面: <S1|S2|S3|S4|status()|inspect()>
- 命令 / 操作: <逐字>
- 逐字输出与退出码: <粘贴>
- 记录值: <路径 / FS 类型 / errno / installdir / 字节数 / ...>
- 结论: <待填；未拿到真机值前留空>
```

---

## 8. 离线复核清单（本机可逐项人工核对，全部「待复核」）

| # | 复核项 | 期望 | 状态 |
| --- | --- | --- | --- |
| O1 | Markdown 结构完整（实现方式 §1、实现步骤 §2、矩阵 §3–§6、回写 §7 齐全） | 是 | **待复核** |
| O2 | §1 的每条机制都能对上具体文件 / 行号 | 是 | **待复核** |
| O3 | §2 步骤 0–10 顺序自洽，前置门槛指向 [RUNBOOK.md](RUNBOOK.md) | 是 | **待复核** |
| O4 | §3 覆盖全部 20 个 V# + 3 个 F#，无遗漏 | 是 | **待复核** |
| O5 | 每条命令 / 真机操作都标「待执行」，无一处声称本文清单项「已完成 / 已通过」；若出现「实现阶段已跑过」字样须明确标注为历史记录、且不能指向本文任一真机步骤 | 是 | **待复核** |
| O6 | 全文**不产生任何 `CLOSED` 状态**；未改任何 V#/F# 状态 | 是 | **待复核** |
| O7 | 无编造实测输出；`<...>` / 「形如」均为形态占位符 | 是 | **待复核** |
| O8 | 所有 ⚠️ V# 版本相关项都标注「按锁定版本核实」 | 是 | **待复核** |
| O9 | 三条硬约束在 §1.9 / 步骤 0 / 步骤 9 均有体现，无 `sudo` / 关只读 / 通用一键装的运行时假设 | 是 | **待复核** |
| O10 | 明确禁止放宽类型 / mock / 跳过 `tsc` / 伪版本 | 是 | **待复核** |
| O11 | 与 [RUNBOOK.md](RUNBOOK.md)、[VERIFICATION.md](VERIFICATION.md)、[ACCEPTANCE.md](ACCEPTANCE.md)、[README.md](README.md) 互相链接 | 是 | **待复核** |
| O12 | §0.1–§0.4 三档机器分工齐全：①本机 / ②任意联网机器（含 CI，不必装 Decky）/ ③Deck；逐步标注机器；列「必须 Deck」与「不必 Deck」；明确卡点在 ② | 是 | **待复核** |

> O1–O12 全部为「**待复核**」，不是「已通过」。C1–C4 与全部真机观测一律留到
> 能联网的机器 / Steam Deck 与后续轮次。

---

## 9. 状态声明（本轮前后无变化）

| 项 | 本轮之前 | 本轮之后 | 原因 |
| --- | --- | --- | --- |
| V1 / V8 | `OPEN` | **`OPEN`（未改）** | 需 RUNBOOK C1–C4 真实输出；本轮只产出调试清单 |
| V2 / V3 / V4–V7 / V11–V13 | `OPEN` | `OPEN`（未改） | 需锁定版本 + 真机加载观测 |
| V9 / V10 / V14 / V17 / V18 | `OPEN` | `OPEN`（未改） | 需真机 `status()` 与真实 VDF / ACF |
| V15 / V16 / V19 / V20 | `OPEN` | `OPEN`（未改） | 需真机写语义与游戏回读 |
| F1 / F2 / F3 | `OPEN` | `OPEN`（未改） | 需 microSD / 跨设备 / Flatpak 实机 |
| DoD（11 项 + G1/G2/G3 + 46 码） | 未签核 | 未签核 | 需真机手柄验收 + 故障注入 |

**没有任何 `V#` / `F#` 被改为 `CLOSED`。** 本文不执行任何命令、不写任何代码、
不生成 `pnpm-lock.yaml`、不跑 `tsc` / `rollup`、不修改 [VERIFICATION.md](VERIFICATION.md)。

---

## 10. 真机安全纪律（再列一次，别破例）

- **不关只读**：所有写入只落 `$HOME` / 用户库 / microSD / Decky 托管目录；撞 `EROFS`
  明确 `E_READONLY_FS` 拒绝。开发期 SSH / 重启服务是一次性准备，不是运行时假设。
- **不假设 root / 不假设非 root**：`pwd.getpwnam(DECKY_USER)`，仅 `geteuid()==0` 对
  自己产物 `chown`；属主不符是 `E_ROOT_OWNED` 拒绝而非修权限。
- **不宣称全游戏通用**：`max_enabled_games_in_mvp:1`，仅 `rimworld` 为 `enabled`；
  Harmony 类因 `append_to_end` + 不求解依赖/顺序可能失效，需游戏内手动拖——如实确认。
- **卸载移入隔离区、永不删除**；调试时不要手动清 `.decky-quarantine/`，否则回滚链断。
- **Flatpak Steam 直接拒绝**，绝不执行 `flatpak --user override`、绝不授 `home`/`host`。
- **不执行 `.exe` / `.msi` 安装器**，不写 Proton `pfx` / compatdata 前缀，不改启动项 /
  `WINEDLLOVERRIDES`，不碰 `steamapps/workshop/content/294100/`。

---

## 11. 下一轮建议

1. 先在满足 [RUNBOOK.md](RUNBOOK.md) §0 P1–P5 的联网机器上实跑 C1→C2→C3→C4，
   **逐字留档**并把证据按 §6 模板回写 V1 / V8（状态字仍由后续轮次人工判定）。
2. 带 `dist/index.js` + `pnpm-lock.yaml` 到 Deck，按本文 §2 步骤 2→3→4→5 先让插件
   **加载起来并核对 `status()` 的 W1/W2**，这是所有后续验证的地基。
3. 步骤 6(a) 合成树用例在实现阶段已于本机跑过；如需额外确认 Linux 语义
   （`fchmod` / `fchown` / `statvfs` / `geteuid`），按 §0.4 在任意 Linux 机复跑即可，
   **不要求、也不必是 Deck**。
4. 按 §3 矩阵逐项闭环，优先 **C 组（V15/V16/V19/V20）**——它们只有真机能验、
   风险最高；V20 尤其不能用 `DECKYMOD_GAME_RUNNING=1` 冒充通过。
5. 最后按 [ACCEPTANCE.md](ACCEPTANCE.md) 走 11 项手柄操作 + 故障注入 + G1/G2/G3 签核。
6. 全程保持：不改后端语义、不新增功能、不放宽类型、不 mock、不跳过 `tsc --noEmit`、
   不编造实测输出、不擅自把任何 `OPEN` 改为 `CLOSED`。
