# Nexus 下载 / 自动导入 / 多游戏分类 — 决策强制路线图（round 1）

> 状态：**OPEN / 决策强制 / 未实现**。本文件是**方案与证据记录**，不是完成声明。
> 目标（m06927 逐字）：「将当前插件，发展成可以到 N 网下载 MOD，自动导入到游戏 MOD 加载文件夹，并且可以管理 MOD，并且可以按照游戏分类查看……通过真机，你可以自行测试功能与获取相关真值。」
> goal：`goal-c9e307e2-507e-4ee0-acc9-bd83438750ae` rev3 / active / round 1 of 256。
> 本轮**保持 goal active**，不调用 `update_goal(complete)`、不写 CLOSED、不勾 §B.4、不翻 V#/F#、不改已部署插件、不放宽 `strict:true`、不新增 `as any`/`@ts-ignore`。

## §0 诚实边界： shipped 现状 vs 新目标

已交付并装机的是 **单游戏 / 本地 ZIP 导入 / DETECT-ONLY / read_only MVP**：
- 唯一启用游戏 stardew（AppID 413150，SMAPI detect-only），其余 3 个 descriptor 全 `planned` 被门禁拒绝（`registry/registry.json:4-5,39,62-82`）。
- 只读：设备实测 `.mm_deployed` + `Mods_Core/` 存在 → Amethyst VFS 符号链接部署 → 所有写操作被 `E_EXTERNAL_MANAGER` 拒（`deckymod/smapi.py:95-97`、`deckymod/file_drop.py:30-34`）。
- 能力全 OFF：`network_download:false` / `workshop:false` / `loader_install:false` / `launch_option_edit:false` / `dll_override:false` / `proton_prefix_write:false` / `exe_installer:false` / `universal_one_click:false` / `enable_disable:false`（`registry/games/stardew.json:142-151` 等）。

新目标 4 个动词中 **3 个撞锁定硬约束，1 个（按游戏分类查看的只读部分）零风险可做**。硬约束（全程不可放松）：不默认关闭 SteamOS 只读 / 不假设 root / 不宣称全游戏通用一键装 / 不写 Proton pfx / 不装 loader / 不改启动选项 / 不执行 .exe / 不破坏第三方 manager / gamepad-only / Step 5 写回 OOS / 原 G3 OPEN。

**本轮结论**：不静默开写联网功能。先记录决定性真机证据（§1）→ 把必须由你拍板的策略变更列清（§4）→ 给出分阶段计划（§5）。理由：G-b「自动导入到 Mods/」在 Amethyst 共存下是**破坏性**动作，G-a 涉及新凭证数据类，G-d 直接矛盾单游戏门禁 —— 三者都只能由用户显式授权，agent 不能代决。

## §1 本轮新增的决定性真机证据（READ-ONLY，经 deck-helper :{{HELPER_PORT}} terminal/start）

三份团队报告都把「冻结 PyInstaller 可能缺 ssl/urllib/CA」列为最大 VERIFY-ON-DEVICE 阻塞。**本轮已用真机证据推翻该假设**：

| 证据文件 | 行 | 事实 |
|---|---|---|
| `.decky-probe/h_26e4d8da_result.txt` | 全文 | DNS(as deck) 解析 Nexus `172.64.145.202`；`https://example.com` → `HTTP=200 t=4.80`；`https://api.nexusmods.com/v1/users/validate.json` → `HTTP=401` body `{"message":"Please provide an authentication method"}`；`NO_PROXY_ENV`；`/usr/bin/python3` 3.14.6 / OpenSSL 3.6.5；插件后端进程 `2104 deck "Decky MOD Manager (.../main.py)"` |
| `.decky-probe/h_3eb24399_result.txt` | 全文 | （**副作用教训**）用 `PluginLoader -B -S -I -c ...` 意外拉起第二个 loader，非纯只读，勿重复；发现 MEI 目录 `/tmp/_MEI0000056870v1Gr` 含 `_ssl...so` + `libssl.so.3` |
| `.decky-probe/h_f43de646_result.txt` | 全文 | MEI 目录含 `aiohttp` / `certifi` / `frozenlist` / `multidict` / `propcache` / `yarl` / `attrs` / `markupsafe` / `libcrypto.so.3` / `base_library.zip` |
| `.decky-probe/h_4b0a9bc9_result.txt` | 4-9 | 临时 loader 已消失，仅基线 1384/1502/1920/1921；插件 2104 仍在 |
| `.decky-probe/h_4b0a9bc9_result.txt` | 13-26 | 把 MEI 加入 `sys.path` 后逐个 `IMPORT_OK ssl / _ssl / urllib.request / http.client / aiohttp 3.13.5 / certifi 2026.06.17 / multidict 6.7.1 / yarl 1.23.0 / frozenlist 1.8.0 / propcache 0.4.1 / attrs 26.1.0` |
| `.decky-probe/h_4b0a9bc9_result.txt` | 27-29 | 用**该 bundle 内** aiohttp GET Nexus validate → `AIOHTTP_STATUS 401 CT application/json; charset=utf-8` / `AIOHTTP_BODY {"message":"Please provide an authentication method"}` |

**结论**：
1. 这台 **Deck 有可用出站 HTTPS**（开发机 `C:\ai\SD` 的「无网 / DNS sinkhole 198.18.0.0/15 / SEC_E_NO_CREDENTIALS」是**另一台机器**，与真机无关，不得混淆）。
2. Nexus API 可达，缺的是 **apikey**（401 而非网络错误）。
3. 冻结 PluginLoader 的 MEI **自带完整 HTTPS 栈**（aiohttp + certifi + ssl/urllib/http.client）→ Python 后端下载器**无需新增 Python 依赖**即可落地。
4. **诚实上限**：这是「系统 python3 + MEI 加入 sys.path」证明的，不是字面在活插件进程 2104 内跑的（`/proc/2104/maps` 无 MEI 命中、`readlink /proc/2104/exe` 为 `EXE_UNREADABLE`）。要在活进程内确认需一个 RPC hook（属实现阶段，未做）。

CEF 远程调试已打开 = 只解锁 §J.10 那种只读 DOM `innerText` 取证（`docs/VERIFICATION.md:1411,1419`），**不等于**授予网络 / 写回 / 鉴权权限。

## §2 三份 READ-ONLY 团队报告（要点，全文见各自消息）

- **decky-api-researcher**（m06996/m07004）：不是纯前端活。前端 JS `fetch()` 直连 Nexus **INFEASIBLE**（CEF CORS/CSP、无 OAuth 回调），必须走 Python 后端；**ZERO 新 npm deps**（复用 `Modal.tsx:95-141 showListModal` / `PanelSection` / `PROGRESS_EVENT` emit / `ImportBox.tsx:35-40` TextField OSK / inline-style 进度条）；`rollup.config.js` LOCKED 勿改；真冲突 = 新增第 12+ 个后端 RPC（`docs/VERIFICATION.md:946-950` 钉「11 位置参数 RPC 不新增、不放宽 strict」）+ Python 网络 stdlib-only + registry DATA 翻转 + i18n 230 键×2 parity（`src/i18n/en.json` / `src/i18n/zh-CN.json` 须同步，否则 `t()` 退化英文）。前端 P0–P4 分相。V3 OPEN 9 项待验。
- **steamos-path-researcher**（m06999/m07005）：Q1 后端 HTTPS in-principle 但 capability 显式 OFF（**其「frozen 缺 ssl」阻塞已被 §1 解决**）；Q2 **无 headless OAuth**，唯一可行 = OSK 粘贴个人 API key，存 `${DECKY_DATA}` 明文（**NEW credential 数据类**，无 keyring）；Q3 安全落盘 = `${DECKY_INBOX}`（`DECKY_PLUGIN_RUNTIME_DIR/inbox`），复用现成 `inspect`/`install` 管线，**ZERO 新写根**，size cap `268435456`(256 MiB)；Q4 `.mm_deployed`/`Mods_Core` 存在时写 `Mods/` 会**破坏 Amethyst VFS 符号链接**（`os.replace` 覆盖/穿透 symlink、`E_FILE_COLLISION`、uninstall 移动 symlink、Flatpak 可见性）→ **USER MUST CHOOSE ONE MANAGER**，无自动共存；Q5 多游戏自动导入会碰 .exe/Proton pfx/loader/launch-option/single-enabled-game。冲突账本 C1–C12。
- **mvp-design-researcher**（m06989/m06995）：按游戏分类可行**且无需碰门禁** = **双正交平面**：Plane1 纯只读 catalog 元数据（只取 descriptors 的 `identity`/`capabilities`，**绝不调用** `get_game`/`require`/`active_descriptor`）+ Plane2 操作面仍唯一 `active_descriptor()`；`max_enabled_games_in_mvp:1` 约束的是「可写/可 dispatch 数」而非「可展示数」；planned/unsupported 一律灰态「仅目录·不可安装」；坑：`paths.*` REFERENCE-ONLY，planned 游戏不得 resolve `mod_root` 伪造 installed 数。5 相 P0–P4 + 冲突账本 C1–C10。新目标应作**独立新 goal/plan**，不得借开工隐式闭合旧 goal。

## §3 冲突账本（4 动词 × 锁定约束，已按 §1 修正）

| 动词 | 冲突约束 | 性质 | 解除路径 |
|---|---|---|---|
| G-a 到 N 网下载 | `network_download:false`（`stardew.json:150`）+ capability_gate（`registry.json:37-43`）+ 新凭证数据类 + CEF CORS | **HARD 策略**（非技术阻塞） | 你授权联网 + 提供 API Key 方案；后端 HTTPS 技术已由 §1 证明可行 |
| G-b 自动导入到 Mods/ | `E_EXTERNAL_MANAGER`（`smapi.py:95-97`）+ Amethyst symlink（`file_drop.py:30-34`）+ read_only:true + Step5 OOS | **HARD + 破坏性** | **你必须二选一**：保留 Amethyst 则下载→inbox 人工交接；或移除 `.mm_deployed`/`Mods_Core`、迁移真实目录后翻转 posture。不可静默启用 |
| G-c 管理 MOD（多游戏） | `max_enabled_games_in_mvp:1`（`registry.json:39`）+ 每游戏需用户自装 loader/`MUST_ALREADY_BE_SET_BY_USER`（`loaders/smapi.json:10,13-15`）+ 拒 .exe/pfx | **HARD 逐游戏** | 每个新游戏单独 descriptor + 你预装 loader + 预设启动选项；gate 逐能力解禁 |
| G-d 按游戏分类查看 | 单游戏门禁（若理解为「多游戏可写」） | **只读部分零风险**；「多游戏可写」矛盾 | 只读 catalog（Plane1）无需动任何门禁；若要「看多写多」须改门禁 + 放弃「no universal one-click」声明 |
| 全部 | 不关只读 / 不假设 root / 安全落盘 | **天然满足，不阻塞** | 下载物只落 `${DECKY_INBOX}` / `${DECKY_DATA}`，零新写根 |

NET：4 个动词里 **3 个需显式 goal 级策略变更 + 真机验证**；只有「只读分类浏览」和「存储/root/只读」天然可做。「CEF 远程调试」只解 DOM 取证，不解网络/写回/鉴权。

## §4 必须你拍板的决策（核心交付物）

按「效率优先」，这些决策决定后续架构，先定后建，避免返工。每项给推荐默认值：

- **D1 — 联网与凭证**：是否授权 G-a？推荐 = 授权，但**只做 OSK 粘贴个人 Nexus API key**（不做 OAuth SSO，无 headless 路径）。Key 存 `${DECKY_DATA}` 明文、`0o600`（**新增 credential 数据类**，需你知情接受「同 uid 进程可读」这一上限）。
- **D2 — 单一管理器（破坏性，最关键）**：G-b 要写 `Mods/`，但设备现由 Amethyst VFS 占用。二选一：
  - **(推荐 A) 不写回**：下载只落 `${DECKY_INBOX}`，复用现有 `list_inbox`/`inspect`/`install` 由你手动 A 确认导入；`read_only` 与 Amethyst 零破坏保持不变。
  - **(B) 接管写入**：你自行移除 `.mm_deployed`/`Mods_Core`、把 `Mods/` 迁成真实目录后，再授权翻转 DETECT-ONLY posture 与新增写回验收（Step 5 移出 OOS）。**此动作会动到你现有的 27 个 MOD 部署，须你明确同意，agent 绝不代做**。
- **D3 — 多游戏范围**：G-d/G-c 是否要把 `max_enabled_games_in_mvp` 从 1 放宽？推荐 **「看多写单」**：catalog 纯只读展示全部 descriptor，但可写/可 dispatch 仍只 1 个 active game（不碰门禁、不宣布全游戏通用）。若你要「看多写多」，须显式放弃「no universal one-click」硬约束并逐游戏补 descriptor + loader + 启动选项。
- **D4 — 每游戏 Nexus 域**：Nexus `game_domain`（如 `stardewvalley`）、允许的 MOD 类型、NSFW/premium/限流策略由你定；`.exe`/FOMOD installers 一律拒绝（`stardew.json:108`）。
- **D5 — 旧 goal 收口**：上一轮 option-1 收口（§J.10/附录/注记已写回）仍 `active`、原 G3(RimWorld 294100) `OPEN/NOT SHIPPABLE`。是否给一句显式授权把它收口？**不得借开工隐式闭合**。
- **D6 — 端点与状态**：deck-helper `:{{HELPER_PORT}}` 无鉴权（S9）、V8 翻转（S10）仍只报告待裁决，本轮不动。

## §5 分阶段计划（每相列「明确不做」）

- **P0 只读分类目录（推荐立即做，零策略变更）**：新增纯只读 catalog，读 descriptors 的 `identity`/`capabilities` 展示 4 游戏（stardew=enabled 可操作，其余灰态「仅目录·不可安装」），**不调** `get_game`/`require`/`active_descriptor`、**不 resolve** planned 游戏的 `mod_root`、**不写**、**不联网**、**不新增 RPC**（把 `catalog` 加性塞进现有 `status()` data，保 11 RPC 契约）、i18n 双字典同步、`strict:true` 保持。明确不做：下载、写回、门禁翻转、redeploy 之外的任何部署变更。
  - **round 2 已实现（backend + frontend 源码，尚未编译 / 尚未重部署，goal 仍 active）**：`deckymod/registry.py::Registry.catalog()` 纯只读、门禁无关（只遍历已加载 descriptors 的 `identity`/`capabilities`/`status`，不调 `get_game`/`require`/`active_descriptor`、不 resolve `mod_root`/`state_file`）；`main.py::_with_catalog()` 把 `catalog` 加性塞进现有 `status()` envelope（**仍 11 个位置参数 RPC，未新增 RPC**）；`src/types.ts` 加 `CatalogEntry` + `StatusData.catalog?`；`src/index.tsx` 加只读 `openGameCatalog()`（复用 `showListModal`/`showInfo`，A 看详情 / B 返回）+ ACTIONS 段一个 `ButtonItem`，planned/unsupported 行标「仅目录·不可安装」，且不 lift 单游戏写门禁；`src/i18n/en.json` + `zh-CN.json` 同步 15 个 `CATALOG_*` 键（parity 245/245）；`tests/test_catalog.py` 9 个用例。本地 bundled-python 验证：`Ran 68 tests OK`（59 历史 + 9 新）、`compileall RC=0`、10 个 registry JSON 全 valid。**诚实边界**：本机无 `node_modules` / 无外网 / 空 pnpm store → **前端未编译、未 type-check、未重打 ZIP、未重部署、未真机 QAM 目视**；`dist/index.js` 仍是旧的 96224 B Track B 产物，本次前端改动尚未进任何交付包。P1–P4 仍全部未做，D1–D6 仍待用户裁决。
- **P1 联网下载到 inbox（需 D1）**：后端 stdlib/MEI aiohttp + OSK API key 管理 + 下载进度（`PROGRESS_EVENT` emit）+ 落 `${DECKY_INBOX}`；新 RPC（**需批准突破 11 RPC**）或复用字段。明确不做：写 `Mods/`、OAuth SSO、自动安装。
- **P2 自动导入（需 D2）**：下载后经手柄 A 确认走现有 `inspect`→`install` 管线；若 D2=A 则停在 inbox 交接，不触碰 `Mods/`。明确不做：绕过 `E_EXTERNAL_MANAGER`、覆盖 symlink。
- **P3 逐游戏启用 / 门禁（需 D3+D4）**：按「看多写单」或放宽 cap；每游戏 descriptor + 用户预装 loader。明确不做：装 loader、改启动选项、写 pfx、执行 .exe。
- **P4 真机验收**：CEF 只读 DOM 取证（§J.10 口径）+ 手柄 A/B 焦点 + 失败步骤错误提示；**CDP innerText ≠ 人眼目视**，须你逐项 PASS/FAIL 贴回。明确不做：自行写 CLOSED、勾 §B.4、翻 V#/F#、标 goal complete。

## §6 下一步（零代码、零 build、零重部署）

round 1 产物仅本文件 + `.decky-probe/` 下 4 个只读探针与结果文件；**未改业务代码、未 build、未重部署、未翻任何状态**。
round 2 追加：P0 只读游戏目录的源码实现（`registry.py` / `main.py` / `types.ts` / `index.tsx` / i18n 双字典 / `tests/test_catalog.py`）+ 本节加性注记；**仍未 build / 未重部署 / 未翻任何状态 / goal 仍 active**（详见 §5 P0 的诚实边界）。
round 3 追加：**策略中立、UNWIRED 的 Nexus 客户端核心** `deckymod/nexus.py`（stdlib-only；`users_validate` / `list_mod_files` / `get_download_link` / `download_to_inbox` / 惰性 `default_opener`；注入式 `opener` 契约；仅 https / apikey 只发 `api.nexusmods.com` 绝不发 CDN / 私有 host 拒绝 / 256 MiB 双上限 / sha256 / 文件名与 inbox 内含性校验 / 经 `fsops.atomic_write_bytes` 只写调用方给的 inbox、绝不写游戏 `Mods/` / 结果全 JSON-safe 且精确 scrub API key）+ `tests/test_nexus.py` 23 个纯离线用例 + `.decky-probe/validate_nexus_unwired.py` 静态守卫。**诚实边界**：本模块**未接任何 RPC、未 import 进 `main.py`、未翻任何 capability 标志、前端零引用、errors.py 仍 50 码、i18n 仍 245/245 键**，即「客户端机制已就绪但整体仍是惰性的、未激活的」；Deck 全端口({{HELPER_PORT}}/8080/8081)本轮 `HTTP=000`，故**仍未 build / 未重部署 / 未真机 QAM 目视 / 未验证真实 Nexus 鉴权与下载**。本地验证：`Ran 91 tests OK`（68 历史 + 23 Nexus）、compileall=0、i18n/p0/unwired 三校验全绿。**激活（接 RPC / 翻 D1 / 选 D2 A/B）仍须你显式裁决**，自动续作不等于批准；goal 保持 active、不标 complete。

round 4 追加（设备真失联下的离线加固，零 build / 零重部署 / 零状态翻转）：① **修 2 个真实集成 bug** —— `tests/test_nexus.py` 两处硬编码 `C:/ai/SD` 开发机路径（会在 Deck build tree 的 `unittest discover` 失败）改为按 `deckymod.nexus.__file__` 推导 + `DECKYMOD_TEST_TMP` 可覆盖；`.decky-probe/sync.tar.gz` 原是 round-1 陈旧快照（46 文件、缺 `deckymod/nexus.py` / `tests/test_catalog.py` / `tests/test_nexus.py`、6 个共有文件字节已变），若直接跑 `rebuild_final.sh` 会编译**旧代码而非 P0** → 用 `make_sync_tar.py` 重建为 49 文件，经 `r4_tar_drift.py` 复验 `TAR_COUNT 49 CUR_COUNT 49 / MISSING 空 / BYTE_CHANGED_COMMON 0`、`tar -tzf` 完整。② 离线 build 尝试 `pnpm install --frozen-lockfile --offline` → `[ERR_SQLITE_ERROR] unable to open database file`，且本机 store 无 `@decky/api|@decky/ui|@decky/rollup` → **本机无法 tsc/rollup**（诚实边界不变）；设备本轮 DNS 解析 `{{DECK_HOSTNAME}}→{{DECK_IP}}` 但 `ping` 100% loss、兄弟 IP 的 {{HELPER_PORT}} 全 000、{{HELPER_PORT}}/8080/8081 全 `HTTP=000` → **设备本轮真失联（非端口错）**，只记「本轮不可达」不下定论。③ 复验全绿：`Ran 91 tests OK` / compileall=0 / i18n 245-245 / p0 / unwired 四校验全绿 / `dist/index.js` 仍 96224 B `ee218850…`（旧 Track B，P0 前端与 nexus.py 仍未进任何交付包）。④ 派 2 份 READ-ONLY 团队审计（前端 P0 严格 tsc 类型审计 / nexus+catalog 安全审计），本轮三次收集窗口到期仍在途，结论留待下一轮折叠。⑤ **提示**：`repack.py:41-43` 白名单 `deckymod/*.py`，故设备恢复后重建的 ZIP 会含**惰性** `py_modules/deckymod/nexus.py`（未接 RPC、不产生网络行为）；若你希望在 D1 授权前把该模块排除在交付包外，请明示，否则按现状随包。⑥ **两个外部门控（自动续作无法替代）**：设备恢复（供 Deck 侧 tsc/rollup + 重打 ZIP + CEF DOM 取证）与 §4 **D1–D6 裁决（尤其 D2 A/B 破坏性二选一）**。goal 保持 active、不标 complete、不写 CLOSED、不勾 §B.4。

round 4b 追加（两份团队 READ-ONLY 审计到达后，按发现闭环修复，仍零 build / 零重部署 / 零状态翻转）：① **前端 P0 严格 `tsc --noEmit` 手工审计（decky-api-researcher）裁定 ZERO 类型错误**（`src/index.tsx:703-738` 的 7 个 `CatalogEntry` 字段全兼容 `src/types.ts:93-106`、`appidText(a: number|null|undefined)` 规避 TS2367、Modal.tsx 的 `ListRow`/`showInfo`/`showListModal` prop 名匹配、无 `as any|@ts-ignore|strict:false`、15 个 `CATALOG_*` 键双字典 245/245）——**须诚实标注为 HIGH 手工分析置信度、非机器验证**（本机无 `node_modules`/tsc）。② **nexus/catalog 安全审计（mvp-design-researcher）**：SCOPE2 四项全 PASS 可放行（catalog 不调 gated 方法、不 resolve planned mod_root、`_with_catalog` 抛错也不破坏 envelope、输出 JSON-safe、仍 11 RPC）；SCOPE1 确认 round-3 两个 bug 已闭合，但发现**同族 4 个残留缺口 F1–F4 + 卫生 F5/F6**，不能判「无进一步 bug」。③ 按 F1–F5 全部落盘修复（`deckymod/nexus.py` 409→488 行）：F1 新增 `_caught()` 外层 `except Exception → _fail("NX_NETWORK")` 边界、`_http_json` 头解析与 read 归一、`download_to_inbox` 全 fs/arg 段包 try，使 `int()/rstrip()/realpath()/TypeError` 永不从 public 函数逃逸；F2 新增 `_json_sanitize()`（非有限 float→None、bytes/对象→None）+ `json.loads(parse_constant=_reject_constant)` 拒 NaN/Infinity + `_scrub_key` 末尾统一 JSON-safe；F3 `default_opener` 用 `build_opener(_NoRedirect)` 不跟随 3xx、`_check_url` 对 `localhost.` 尾点归一化；F4 把 `_download_meta`/非 2xx/read 全路径收进 `try...finally: resp.close()`；F5 `_safe_domain`/文件名改 `fullmatch + \Z` 拒尾随换行。④ 新增 `tests/test_nexus.py::TestAuditRegressionF1toF5` **18 个回归用例**（非 int id / 非 str base / 非 str filename+inbox / 畸形 headers、NaN/Infinity、`_json_sanitize`、fail-context scrub、尾点 host、3xx 不跟随、AST 证 `_NoRedirect`、read/CL/非2xx 的 `closed` 标志、尾随换行 filename/domain）；删 `validate_nexus_unwired.py` 一条硬编码 True 的 no-op check。⑤ **复验全绿**：`Ran 109 tests in 1.089s OK`（91 + 18）、compileall=0、i18n 245/245、p0 `ALL_STATIC_CHECKS True`、unwired `NX_UNWIRED_ALL_OK=True`、sync.tar.gz 重建 132739 B / 49 文件 / 零漂移。**诚实边界**：前端 `tsc` 仍是手工审计（非机器编译）、nexus 仍未接线/未翻 capability/前端零引用/errors.py 仍 50 码、Deck 全端口仍 `HTTP=000` 真失联、仍未 build / 未重打 ZIP / 未重部署 / 未真机 QAM 目视 / 未验证真实 Nexus 鉴权下载，`dist/index.js` 仍 96224 B `ee218850…` 旧 Track B。两个外部门控（设备恢复 + D1–D6 裁决尤其 D2 A/B）不变。goal 保持 active、不标 complete、不写 CLOSED、不勾 §B.4、不翻 V#/F#/§B.4。

round 5 追加（下载→导入半链的**离线机械证明**，仍零 build / 零重部署 / 零状态翻转）：① 目标里「自动导入」(download→import 的连接缝)此前从未被机械验证——round 2–4 分别建了下载核心 `deckymod/nexus.py` 与游戏目录 catalog，但两半从未一起执行。派 `mvp-design-researcher` READ-ONLY 集成契约审计(m07805)：**结论无需任何形状/格式改动**——Q1 `.zip` 扩展名 FINE(`smapi.py:229` 过滤 `.zip`，`nexus.py:58` basename 允许)、Q3 归档形状 FINE(manifest.json + `.dll` + 单根 wrapper 全链路 PK/`is_zipfile`/`_validate_member_name`/JSONC/`id_regex` 通过)、Q4 B 不接受任意绝对路径(`_validate_import_path` 比 `abspath` 内含性)；**唯一 REAL 缺口 Q2 = inbox 解析/创建**——(A) `download_to_inbox` 收调用方 `inbox_dir`、要求 `isdir`、不认环境变量、不创建目录；(B) `list_inbox`/`_validate_import_path` 用 `DECKYMOD_INBOX or <decky_data>/inbox`；交付物中**无任何代码创建该 inbox**。最小 policy-neutral glue = 解析同一 env 绝对路径 + `fsops.ensure_dir` 后传给 `inbox_dir`，再改用 `list_inbox()` 输出（不是 (A) 的 realpath `final`，避开 symlink→`E_PATH_ESCAPE` 的 LOW edge）。最终 `install()` 写 `Mods/` 仍被 `_check_write_allowed` 的 `E_EXTERNAL_MANAGER`/read_only 按设计门控、需 D2。② 新建 `tests/test_integration.py` 6 个纯离线用例（`_ChainOpener` 假开服 download_link.json + 单根 SMAPI ZIP body、`StardewTree` 合成树）：test_1 **决定性半链** `get_download_link→download_to_inbox→list_inbox→inspect` 全接通 + 证 Q2(inbox 删除→`NX_INBOX_MISSING` 干净失败、`fsops.ensure_dir` 修复后成功)+ apikey 只发 API_HOST 不发 CDN + 用 listed path 喂 inspect 得 `uniqueId=TestCo.Automate` + 零 `Mods/` 写；test_2 非 `.zip` 名 list_inbox 不可见；test_3 越界绝对路径→`E_PATH_ESCAPE`；test_4 HTML 200 体→`E_BAD_ARCHIVE` 干净失败；test_5 复制真机 `.mm_deployed` 后 `install(after_confirm=True)`→`E_EXTERNAL_MANAGER` 且零 `Mods/` 写（诚实边界：半链只读可用、最终写按设计被拒）；test_6 AST 证 `main.py` 仍零 nexus import、仍恰 11 RPC（生产仍 UNWIRED）。③ **复验全绿**：`Ran 115 tests in 1.331s OK`（109 + 6）、compileall=0、i18n 245/245、p0 `ALL_STATIC_CHECKS True`、unwired `NX_UNWIRED_ALL_OK=True`、sync.tar.gz 重建 **136785 B / 50 文件** 且 `r4_tar_drift` `BYTE_CHANGED_COMMON 0`。**诚实边界**：只证 READ-ONLY 半链，绝不宣称「自动导入已可用」（`install` 写回需 D2、接线激活需 D1 显式裁决）；前端 `tsc` 仍是手工审计（非机器编译）；Deck 全端口({{HELPER_PORT}}/8080/8081)本轮仍 `HTTP=000` 真失联；仍未 build / 未重打 ZIP / 未重部署 / 未真机 QAM 目视 / 未验证真实 Nexus 鉴权下载，`dist/index.js` 仍 96224 B `ee218850…` 旧 Track B。④ 教训：`-m unittest tests.test_integration` 不加 `tests/` 到 sys.path → `ModuleNotFoundError: test_stardew`（与 test_catalog.py 同用 `from test_stardew import`，只有 `discover -s tests` 才对）；本机 pwsh `2>&1` 重定向到文件须用 `[System.IO.File]::ReadAllText(...,UTF8)` 读，否则 read 工具报 binary file。goal 保持 active、不标 complete。

round 6 追加（把 round-5 已证的下载→导入半链提升为可复用、UNWIRED、policy-neutral 的三态协调器，仍零 build / 零重部署 / 零状态翻转）：① 派 `mvp-design-researcher` READ-ONLY 激活契约审计(m07972)：唯一不破 11-RPC 的接线方式 = 仿 `_with_catalog` 在 `status()` 注入 additive `data.auto_import`；真实下载动作需新增第 12 个位置参数 RPC（`nexus_fetch(game_domain, mod_id, file_id, api_key, after_confirm)`），会破 `validate_nexus_unwired.py:45` / `test_integration.py:275` 的 `==11` 守卫 → 属 D1 策略变更非技术细节；D1 只翻 `stardew.json:150 network_download`、D2=A（推荐）零翻转、永不可翻 root / read-only / universal-one-click / loader-install / launch-option-edit / dll-override / proton-prefix / .exe / workshop / `registry.json:39`；15 个 NX_* 边界映射到已有 E_* 使 errors.py 保持 50 码，仅协调器 UI 键（`CONFIRM_NEXUS_FETCH` / `NEXUS_STAGE_*`）需新增 i18n 双键；审计裁定 `allow_install=False` **不足** → 用三态（默认 False + 强制两段 `after_confirm` + **透传 E_EXTERNAL_MANAGER 为不可绕过最终闸门**）。② 新建 `deckymod/auto_import.py`（UNWIRED：main.py 不 import、前端零引用、无 capability 翻转、11 RPC 不变）：`fetch_and_import(opener, engine, *, game_domain, mod_id, file_id, api_key, filename="mod.zip", allow_install=False, after_confirm=False, ...)` 六阶段 = `get_download_link → _inbox_dir + fsops.ensure_dir → download_to_inbox`（唯一写盘，只写 caller inbox）`→ _listed_path`（用 `list_inbox()` 输出避开 symlink→E_PATH_ESCAPE 的 LOW edge）`→ inspect → TRI-STATE GATE`；`NX_TO_E` 15 映射保 50 码；`_install` 薄封装 `engine.install` **PROPAGATE 不改写**，绝不删/移 `.mm_deployed`、不翻 `force_read_only`/`detection_only`、不吞 `E_EXTERNAL_MANAGER`。③ 新建 `tests/test_auto_import.py` 12 个纯离线用例（默认只读半链 / True 无 after_confirm 返回 confirm 零写 / **决定性：写 `.mm_deployed` 后 True+True→`E_EXTERNAL_MANAGER` 原样透传且零 `Mods/` 写** / 15 个 NX→E 全命中 / NX_TOO_LARGE→E_ZIP_BOMB+verbatim detail / 401→E_CAPABILITY_DISABLED / 无 link / HTML→E_BAD_ARCHIVE / 非 .zip→E_INBOX_EMPTY / 裸异常不逃逸 / AST 证仍 UNWIRED+11 RPC / apikey 只发 API_HOST）。④ 扩展 `.decky-probe/validate_nexus_unwired.py` 第 8 组守卫（协调器存在 / 三态默认 / 透传 / 仍 UNWIRED / errors.py 仍 50 / 顶层 import 白名单）。⑤ **复验全绿**：`Ran 127 tests in 1.438s OK`（115+12）、`COORD_ANY=12` 证 12 用例全执行、compileall=0、i18n 245/245、p0 `ALL_STATIC_CHECKS True`、unwired `NX_UNWIRED_ALL_OK=True`；sync.tar.gz 重建 143566 B / 52 文件 / `r4_tar_drift` 零漂移（含 auto_import）。**诚实边界**：只把「自动导入」做成惰性未接线的协调器，绝不宣称自动导入已可用（接线激活需 D1 第 12 RPC、写回需 D2、最终闸门 `E_EXTERNAL_MANAGER` 按设计不可绕过）；前端 `tsc` 仍手工审计非机器编译；Deck 三端口({{HELPER_PORT}}/8080/8081)本轮仍 `HTTP=000` 真失联；仍未 build / 未重打 ZIP / 未重部署 / 未真机 QAM 目视 / 未验证真实 Nexus 鉴权下载，`dist/index.js` 仍 96224 B `ee218850…` 旧 Track B。两个外部门控（设备恢复 + D1–D6 裁决尤其 D2 A/B）不变；goal 保持 active、不标 complete、不写 CLOSED、不勾 §B.4。

round 7 追加（把「前端能编译」从手工结论升级为**机械证据** + 独立复核 round-6 协调器并闭环 4 个 LOW 加固 nit，仍零 build / 零重部署 / 零状态翻转）：① **设备无关的前端 build preflight**（`.decky-probe/frontend_preflight.mjs`，Node 24 `module.stripTypeScriptTypes`）：本机无 `node_modules`/无网/空 pnpm store（深挖 store 证实无 `typescript/lib/tsc.js`，只有内容寻址二进制），故**诚实标注为 NOT `tsc --noEmit` / NOT 类型检查**；它机械解析 3 个纯 `.ts`（`api.ts`/`i18n.ts`/`types.ts` 全 PASS，真实 TS 语法解析）、对 6 个 `.tsx` 因 JSX stripper 不支持而**只做 import/export 解析 + advisory 括号平衡**（诚实标「NOT syntax-verified」），并校验跨文件符号（**34 imports / 58 named bindings / 10 bare imports 全解析**，相对 import 全命中真实 export、bare import 全在 `@decky/api`/`@decky/ui`/`react` 白名单）、`tsconfig.json` `strict=true` + `jsx=react-jsx` + `resolveJsonModule=true`、零 `as any|@ts-ignore|: any|strict:false`、i18n 双字典 245/245 parity → `PREFLIGHT_ALL_OK=true`。**这把「藏有 compile-breaking import 会在设备恢复那轮暴雷」的风险提前机械排除**，但类型级证据仍是 round-4b 的手工审计，不得写成「tsc 已通过」。② 派 `mvp-design-researcher` READ-ONLY 独立复核 round-6 三态协调器（7 项全 PASS、无阻塞 bug；结论：三态确实 fail-closed、透传 `E_EXTERNAL_MANAGER`、inbox glue 与 `smapi.py:137` 同公式、apikey 无泄漏、15 NX→9 个已存在 E_* 保 50 码、仍 UNWIRED），指出 **4 个 LOW 加固 nit** 并当场闭环：(Q6) `fetch_and_import` public 边界统一 `to_json_safe` 覆盖所有返回路径（含逐字传播的 listing/inspect envelope）；(Q4) 边界 `except Exception` 的 detail 用 `api_key.replace(...,"<redacted>")` scrub，杜绝注入协作者异常回显凭证；(Q7-a) `validate_nexus_unwired.py` 的「透传」守卫改 AST 行为检查（`_install` 无 try/except、除 docstring 外唯一语句是 `return engine.install(...)`），不再被 docstring 子串满足；(Q7-b) 组 8 加「`auto_import.py` 必须存在」守卫，文件缺失时不再静默跳过全部检查。③ 新增 `tests/test_auto_import.py` 2 个回归用例（`_LeakyEnvelopeEngine` 注入 bytes/NaN/Path 到逐字传播的失败 envelope → public 边界仍 JSON-safe；`_KeyLeakEngine` 异常消息含 apikey → `E_UNKNOWN` detail 里变 `<redacted>` 不回显）。④ **复验全绿**：`Ran 129 tests in 1.447s OK`（127 + 2）、compileall=0、i18n 245/245、p0 `ALL_STATIC_CHECKS True`、unwired `NX_UNWIRED_ALL_OK=True`（含新 AST 守卫）、frontend preflight `PREFLIGHT_ALL_OK=true`、sync.tar.gz 重建 **144270 B / 52 文件 / 零漂移**（含 `auto_import.py`/`test_auto_import.py` 硬化版）。**诚实边界**：前端仍是「机械符号+语法预检」非机器类型编译，P0/nexus 前端改动仍**未进 `dist/index.js`**（仍 96224 B `ee218850…` 旧 Track B）；nexus 与 auto_import 仍 UNWIRED、未接 RPC、未翻 capability、errors.py 仍 50 码；Deck 三端口({{HELPER_PORT}}/8080/8081)本轮 `HTTP=000` 且 `ping {{DECK_IP}}` 100% loss / `arp` 无 .191 条目 → 真失联（非错端口）；仍未 build / 未重打 ZIP / 未重部署 / 未真机 QAM 目视 / 未验证真实 Nexus 鉴权下载。两个外部门控（设备恢复 + D1–D6 裁决尤其 D2 A/B）不变；goal 保持 active、不标 complete。

round 8 追加（设备恢复 one-shot 构建路径的**决定性离线证明 + 结构性修复**，仍零 build / 零重部署 / 零状态翻转）：① 权威状态重探：`goal-c9e307e2` rev3 / active / armed / roundsStarted 8 / maxGoalRounds 256；Deck 三端口 {{HELPER_PORT}}/8080/8081 全 `HTTP=000 RC=28`；本机无 `node_modules`、pnpm store v11 深挖 `BLOB_FILE_COUNT=23552 / INDEX_JSON_COUNT=0`、`r8_store_recon.py` 报 `sqlite3.OperationalError: unable to open database file` → **本机真 `tsc`/`rollup` 确认无解**，不再重复；`dist/index.js` 仍 96224 B `ee218850…` 旧 Track B、`ACTIVE=stardew GATE=1` 未翻。② 新建 `.decky-probe/r8_zipload_probe.py` **决定性 ZIP 布局证明**（历轮所有测试都从扁平 checkout 导入 `deckymod`，从未从真实 `py_modules/` 布局导入；曾出「5 个 EQ=False 是 py_modules 前缀假阴性」→ byte-exact necessary-not-sufficient 缺口）：逐字镜像 `repack.py:25-51` 白名单建 ZIP → 解压 → CLEAN sys.path 只留 `<root>/py_modules` + `<root>` → `importlib.import_module("main")` 得 `Plugin()` → PHASE 1 真实 Windows 机 `status()` 得 well-formed `E_PATH_INVALID`（无 Steam 树，期望）+ `HAS_CATALOG True CATALOG_LEN 4` + `ERROR_CODE_COUNT 50`；PHASE 2 造合成 Steam 树（Stardew Valley/Mods + smapi-internal + StardewModdingAPI ELF + libraryfolders.vdf + appmanifest_413150.acf）env 注入后 `PHASE2_STATUS_OK True` + `{"appid":413150,"name":"Stardew Valley",...}` → `VERDICT PASS_ZIP_LAYOUT_LOADS`。初跑 `PermissionError`（tempfile.mkdtemp 0o700 DACL）改工作区锚点 `os.makedirs`；二跑误把 Windows 机 `E_PATH_INVALID` 当 FAIL → 读 `main.py:78-99 _with_catalog` 确认后判定改「well-formed envelope」= `ok` 在 env 且 (ok True 或 code 是已知 E_*)。**离线闭合「加载包字节完全相同 ≠ 能从 ZIP 布局真正加载」缺口**：真实交付布局能加载 Plugin、registry.json 解析到 `py_modules/registry/registry.json`、catalog 注入、50 码、合成树下 status() 全功能；`MISSING_SOURCES [] / WHITELIST_LEAKS [] / ZIP_ENTRIES 32`。③ 派 `mvp-design-researcher` READ-ONLY one-shot 路径审计(m08383) **VERDICT NOT structurally complete**：全新 Deck 只解 `sync.tar.gz` 跑不通 `rebuild_final.sh`——**G1 REAL BLOCKER** tar 只投 src/deckymod/registry/tests + 6 根文件，实测 `COUNT 52 / SCRIPTS_IN_TAR []`，而 `rebuild_final.sh:25/28` 直呼 `status_probe2.py`/`repack.py` 必失败（只对先前轮次已播种的持久构建树成立）；**G2** node_modules/dist 不在 tar 须 Deck 预置（本机离线 pnpm install 曾 ERR_SQLITE_ERROR）；**G3** `repack.py:37` 需 `dist/index.js.map`（@decky/rollup 1.0.2 内部产出，已发布 30-entry ZIP 确有），fine-as-is 非 guaranteed；**G4 LOW-MED** `rebuild_final.sh:2` 仅 `set -u` 无 `set -e`/`$?` 守卫 → tsc/rollup 失败仍拿旧 dist 静默 repack；**G5 LOW** `tar -xzf` 增量 + `repack.py:41-43` re-glob → 已删旧 `.py` 残留进 ZIP；(c) FINE 白名单只收 deckymod/.py + registry/.json、排除 probe/__pycache__/node_modules、未接线 nexus.py/auto_import.py 是有意纳入；(d) FINE `registry.py:19` 在 ZIP 布局解析到 `py_modules/registry/registry.json` ✓；(e) FINE 已加载集合先经 `__init__.py:15-68 _ensure_elementtree()` shim，未来 D1 接线 nexus 须另验 `urllib.parse`/`ipaddress`/`ssl` vs 冻结 PYZ。④ **按 G1/G4/G5 闭合（真缺口、零策略变更）**：`make_sync_tar.py` 增投 `status_probe2.py`+`repack.py` 到 build-tree ROOT（**不投 driver `rebuild_final.sh`**：bash 增量读脚本自覆盖竞争）；`rebuild_final.sh` 把 tsc/rollup 退出码存 `TSC_EXIT`/`ROLLUP_EXIT` 并在 `BUILD_END` 后加「非 0 则 `REBUILD_ABORTED exit 1`、拒绝 repack 旧 dist」(G4) + `tar -xzf` 后用 `comm -13 .synced_py .live_py` 只删盘上有、tar 无的 stale `deckymod/*.py`(G5)；`r4_tar_drift.py` 的 `cur` 集合 + `HELPERS` 路径映射跟踪这两个 helper 的字节漂移。G2/G3 属既有设备前置 / fine-as-is 只记录不擅改。⑤ **复验全绿**：`make_sync_tar.py` 重建 `sync.tar.gz` **146885 B / 54 文件**（`COUNT 54` 含两 helper）、`r4_tar_drift.py` `TAR 54 CUR 54 / MISSING 空 / STALE 空 / BYTE_CHANGED_COMMON 0`；`Ran 129 tests in 1.433s OK`、compileall=0、i18n 245/245、p0 `ALL_STATIC_CHECKS True`、unwired `NX_UNWIRED_ALL_OK=True`、`r8_zipload_probe.py` `PASS_ZIP_LAYOUT_LOADS`、frontend preflight `PREFLIGHT_ALL_OK=true / HARD_FAILS=0` 全 EXIT=0；本机无 bash（`BASH_N=NO_BASH`）故 `rebuild_final.sh` 仅逐字静态核对该脚本 48 行，**未在真机执行**。**诚实边界**：仍 UNWIRED / 未接 RPC / 前端零引用 / errors.py 仍 50 码 / Deck 三端口 000 真失联 / 前端 `tsc` 仍手工非机器 / 仍未 build / 未重打 ZIP / 未重部署 / 未真机 QAM 目视 / 未验证真实 Nexus 鉴权下载、`dist/index.js` 仍 96224 B `ee218850…` 旧 Track B；one-shot 路径现「结构性自洽」但 G2(node_modules/dist 预置) 仍须设备恢复后真机验证；D1–D6 待裁决尤其 D2 A/B；goal 保持 active 不标 complete。两个外部门控（设备恢复 + D1–D6 裁决）不因本轮离线修复而解除。

round 9 追加（团队两次点名 m06999 Q2 / m07972 §2 但从未落地的真实缺口 = **Nexus 个人 API key 凭证存储**；Game Mode 无 headless OAuth，唯一路径是用户经 OSK 粘贴个人 key 存 `${DECKY_DATA}`——这是全新、安全敏感的数据类。本轮把它建成 **UNWIRED、policy-neutral、stdlib-only、可 100% 离线验证**的模块，仍零 build / 零重部署 / 零状态翻转）：① 权威状态重探：`goal-c9e307e2` rev3 / active / armed / roundsStarted 9 / maxGoalRounds 256；Deck 三端口全 `HTTP=000`；本机无 `node_modules` / 无外网；`dist/index.js` 仍 96224 B `ee218850…` 旧 Track B；`ACTIVE=stardew GATE=1` 未翻。② 新建 `deckymod/credentials.py`（stdlib-only）：`FILENAME="nexus_api_key"` 固定常量（caller 不可控路径段）、`REQUESTED_MODE=0o600`（经 `fsops.atomic_write_bytes` 同目录 `os.replace` 防 EXDEV）、`_KEY_RE=^[A-Za-z0-9]{16,128}$`（fullmatch 拒 CRLF/头注入/尾随换行/路径分隔符）、`data_dir()` 逐字镜像 `smapi.py:54-62 _default_journal`（凭证落 journal/inbox 旁，**不新增写根**）、`_guarded_path()` realpath + islink→CR_SYMLINK + commonpath 内含性、`save_key/delete_key/key_status` 全部返回**绝不含 key 的 JSON-safe dict**（`_scrub` 精确键 redact + `_sanitize` 非有限/bytes/对象归一）、`load_key()` 是**唯一**返回裸 str|None 的例外（直送 `nexus.*(api_key=...)`，异常 fail-closed 返 None）、`key_status()` 只读 stat 不读内容且诚实报 `posix`/`mode_actual`（Windows fchmod no-op 不谎称已强制）。`CR_ERRORS` 7 码经 `CR_TO_E` 全映射到**已存在** E_*（CR_BAD_KEY→E_ID_INVALID / CR_BAD_DIR→E_PATH_INVALID / CR_SYMLINK→E_STATE_SYMLINK / STORE|READ|DELETE_FAILED→E_ACCESS / CR_INTERNAL→E_UNKNOWN）→ `errors.py` 保持 **50 码**、零新增 `CAT_*`/`ERR_E_*`。**不 import 进 main.py（仍 11 RPC）、前端零引用、不翻 capability、不写真 Mods/、不碰 Amethyst、不假设 root、不关只读、不宣称通用一键装**；激活（接第 12 RPC / 翻 D1 `network_download`）仍须用户显式裁决。③ 新建 `tests/test_credentials.py` **25 用例**（stdlib-only、无网络/无设备/不写真 Mods）：好 key/坏字符含 CRLF·换行·连字符·短长/尾随 `\n`、save→load→delete 全链、absent noop、overwrite、无 `.decky-tmp-` 残留、5 项 no-secret-leak（含失败 save 不回显坏值）、containment（固定名/对称链拒绝/corrupt 内容 load 返 None/不动其它文件）、CR_TO_E 全在 ERRORS 且 50 码、env 解析（runtime_dir 追加 /data、explicit 不双追加、explicit_dir 覆盖 env）、UNWIRED（main.py/src 零引用、AST public RPC==11）。④ 首轮 `Ran 25 tests FAILED(failures=2,errors=1,skipped=1)` 暴露 3 个真实问题：**(a) API 不一致** `data_dir` 形参写 `explicit` 而其余全用 `explicit_dir`（测试按 `explicit_dir=` 调用 TypeError）→ 修签名+函数体（曾有半改 BROKEN 态，已补 `d=(explicit_dir or ...)`）；**(b) 测试期望 bug** 误把 `credential_path` 父目录与原始目录比较，忽略 `data_dir` 按设计追加 `/data` → 断言改比 `os.path.realpath(cr.data_dir(...))`；**(c) 测试隔离 bug** `TestStoreRoundTrip.setUp` 4 用例共用 `_tmpdir("roundtrip")`，字母序前用例建的文件污染 `test_delete_when_absent_is_noop` → setUp 先删凭证文件。另修 `test_explicit_dir_overrides_env` 同类期望 bug。复跑 `Ran 25 tests OK (skipped=1)`（Windows symlink 预期跳过）。⑤ 扩展 `.decky-probe/validate_nexus_unwired.py` **组 9**（credentials.py 存在、6 个公共函数、`CR_TO_E` 全映射到已有 E_*、`FILENAME` 固定、`0o600`、`load_key` 无 dict 返回、main.py/src 零引用、errors.py 仍 50、仍 11 RPC、顶层 import 白名单加 `stat`）。⑥ **决定性全量复验（全绿）**：`Ran 154 tests in 1.507s OK (skipped=1)`（129 历史 + 25 新）/ UNITTEST_EXIT=0；`compileall`=0；`validate_i18n.py` EXIT=0（EN=ZH=245 / ERROR_CODES 50 / USED_BUT_MISSING_* []）；`validate_p0.py` `PUBLIC_RPC_COUNT 11` / `ALL_STATIC_CHECKS True` / EXIT=0；`validate_nexus_unwired.py` `NX_UNWIRED_ALL_OK=True` / EXIT=0；`frontend_preflight.mjs` `PREFLIGHT_ALL_OK=true / HARD_FAILS=0`（诚实 NOT tsc）；`r8_zipload_probe.py` `ZIP_ENTRIES 33`（含新 credentials.py）/ `ERROR_CODE_COUNT 50` / `PHASE2_STATUS_OK True` / `VERDICT PASS_ZIP_LAYOUT_LOADS` / EXIT=0；`r4_tar_drift.py` 重建前如实报 `MISSING deckymod/credentials.py + tests/test_credentials.py` → `make_sync_tar.py` 重建 **`sync.tar.gz` 153675 B / 56 文件**，复验 `TAR 56 CUR 56 / MISSING 空 / STALE 空 / BYTE_CHANGED_COMMON 0` / DRIFT_EXIT=0。⑦ 派 `steamos-path-researcher` READ-ONLY 独立安全复核（SECRET LEAK / PATH SAFETY / 0o600 诚实性 / KEY VALIDATION / UNWIRED / 真实 bug 裁定）。**诚实边界**：凭证模块仍 **UNWIRED / 未接 RPC / 前端零引用 / errors.py 仍 50 码**；Deck 三端口 000 真失联；前端 `tsc` 仍手工非机器、本机无 bash 脚本未真机执行；仍未 build / 未重打 ZIP / 未重部署 / 未真机 QAM 目视 / 未验证真实 Nexus 鉴权下载；`dist/index.js` 仍 96224 B `ee218850…` 旧 Track B；**明文 0o600 无 keyring 是 D1 已知且须用户知情接受的新 credential 数据类，不是 bug**；D1–D6 待裁决尤其 D2 A/B；goal 保持 active 不标 complete。

round 10 追加（**完整 UNWIRED 栈端到端组合证明** + 收 `steamos-path-researcher` 独立安全复核并闭环 3 个 LOW 加固 nit；仍零 build / 零重部署 / 零状态翻转）：① 权威状态重探：`get_goal` → `goal-c9e307e2` **rev4**（注意：此前记为 rev3）/ phase active / armed / roundsStarted **10** / maxGoalRounds 256；6.5 小时后重探 Deck 三端口 {{HELPER_PORT}}/8080/8081 仍全 `HTTP=000 RC=28`、`ping {{DECK_IP}}` 100% loss → **设备仍真失联**；本机无外网（`web_search`/`web_fetch` 的 provider `ddg`/`fs-quality-fetch` 未注册，本机 `NET=000 RC=35`）；`dist/index.js` 仍 96224 B `ee218850…` 旧 Track B；`ACTIVE=stardew GATE=1` 未翻。② 收 `steamos-path-researcher` READ-ONLY 独立安全复核（m08605）**VERDICT: NO real bug / blocker — fine-as-is**（静态，未改文件/未跑测试/未碰设备）：Q1 凭证泄漏 NO（`save_key` 每个返回都过 `_scrub`；`load_key` 唯一裸 str 例外且 fail-closed；`delete_key`/`key_status` 不读文件内容故无泄漏）；Q2 路径安全（FILENAME 固定 + realpath + islink + commonpath，caveat LOW：data_dir 若被 env/symlink 指进 Mods/ 则凭证同落——与 journal/inbox 共用的既有假设；load/delete/status 有 TOCTOU 竞态）；Q3 0o600 诚实（posix/mode_actual/mode_ok 不谎报，exFAT 下 mode_ok=False 仍诚实）；Q4 校验无绕过（alnum fullmatch 拒 CRLF/冒号/斜杠/尾随换行），**唯一外部未决项**「核实真实 Nexus 个人 key 是否真为纯字母数字」——本会话离线无法验证，诚实记录不臆测；Q5 UNWIRED 确认（main.py/src 零引用、11 RPC、errors.py 50 码、CR_TO_E 5 值全在）。**3 个 LOW 加固当场闭环**：(a) `_KEY_RE` 由 `^…$` 改 `\A…\Z`（显式锚，今日无绕过）；(b) 新增 `_recheck_no_symlink(final)` 在 `load_key`/`delete_key`/`key_status` 的**使用时刻**二次校验（闭合 TOCTOU 竞态，happy path 行为不变）；(c) `delete_key` 的 `_recheck_no_symlink` 使 `not os.path.islink` 分支冗余可删。③ **新建 `tests/test_composition.py`（4 用例）= 最后一个从未被测的组合缝**：历轮各自只证一个 seam（round3 nexus fake opener / round5 半链 / round6 协调器注入 engine / round9 凭证独立），从未证明「**真实落盘的凭证** → `load_key` 裸 str → `auto_import.fetch_and_import` → **真实 `StardewEngine`** 」四块能无缝组合。4 用例全离线：test_1 决定性（`credentials.save_key` 真写盘 → `key_status` 不泄密 → `load_key` 取回 → 把 **loaded 值**（非硬编码常量）喂协调器 → 默认只读半链得 `phase=inspect` + `uniqueId=TestCo.Automate` + **零 Mods 写** + key **只**发 API_HOST、`apikey` 头绝不发 CDN、所有 dict 无 key 回显）；test_2 即使两 flag 全 True 且真实凭证，写 `.mm_deployed` 后仍逐字透传 `E_EXTERNAL_MANAGER` 且零 Mods 写；test_3 凭证字符集与 `nexus._headers` 契约一致（alnum key 可安全入 HTTP 头，CRLF/冒号/斜杠/短 key 全拒）；test_4 AST 证 main.py 零 `credentials|import nexus|auto_import` 引用、恰 11 RPC、ERRORS 50。修 1 个 cosmetic `ResourceWarning`（test_4 `open()` 未关 → `with open`）。④ **决定性全绿复验**：`Ran 158 tests in 1.650s OK (skipped=1)`（154 历史 + 4 新）/ UNITTEST_EXIT=0；compileall=0；validate_i18n / validate_p0 / validate_nexus_unwired（`NX_UNWIRED_ALL_OK=True`）/ frontend_preflight（`PREFLIGHT_ALL_OK=true`，诚实 NOT tsc）/ r8_zipload_probe（`ZIP_ENTRIES 33` / `ERROR_CODE_COUNT 50` / `PHASE2_STATUS_OK True` / `VERDICT PASS_ZIP_LAYOUT_LOADS`）全 EXIT=0；`make_sync_tar.py` 重建 **`sync.tar.gz` 155149 B / 57 文件**，`r4_tar_drift.py` 复验 `TAR 57 CUR 57 / MISSING 空 / STALE 空 / BYTE_CHANGED_COMMON 0`。**离线闭合「四个独立构建的惰性模块可组合」缺口**，把未来 D1 接线的隐格式/路径不匹配风险提前排除。**诚实边界**：组合证明 ≠ 功能已激活；凭证模块/nexus/auto_import **仍 UNWIRED、未接 RPC、前端零引用、errors.py 仍 50 码**；真实 Nexus key 字符集仍待联网核实（D1 前须确认）；Deck 三端口 000 真失联；前端 `tsc` 仍手工非机器、本机无 bash 脚本未真机执行；仍未 build / 未重打 ZIP / 未重部署 / 未真机 QAM 目视 / 未验证真实 Nexus 鉴权下载；`dist/index.js` 仍 96224 B `ee218850…` 旧 Track B；D1–D6 待裁决尤其 D2 A/B；goal 保持 active 不标 complete。

round 11 追加（**设备 10 轮来首次短暂恢复 = 两外部门控之一打开**，但窗口内未完成构建；本轮抓到新的决定性真机事实并交付可复用的一键构建编排器，仍零 build / 零重部署 / 零状态翻转）：① 权威状态重探：`get_goal` → `goal-c9e307e2` **rev4** / phase active / armed / roundsStarted **11** / maxGoalRounds 256。 Round 11 开头（2026-11-15 12:16，Asia/Shanghai）`curl` 实测 **`PORT_{{HELPER_PORT}}=200` / `PORT_8081=200`** —— 这是自 round 3 起设备三端口全 `000` 后**首次真实恢复**（注意 `ping {{DECK_IP}}` 仍 100% loss，但 TCP 服务可达，以 HTTP=200 为准，不是「端口错」那种假离线）；本机 `Ran 158 tests in 1.519s OK` / `DIST=96224` / `TAR=155149`。② **窗口内 READ-ONLY 真机探针（`h_9135892f_result.txt`，RC=0）抓到的决定性新事实**：Deck 构建树 `/home/deck/deckymod-build/` 里 **`TSC_YES` / `ROLLUP_YES`**（`node_modules/.bin/tsc`、`rollup` 都在，G2 已满足）、`dist/index.js=96224`、helper `repack.py`/`status_probe2.py`/`rebuild_final.sh` 都在根目录；**但 `sync.tar.gz` 仍是 `117144 B` 的陈旧快照、`PYNEW` 四项（`nexus.py`/`credentials.py`/`auto_import.py`/`test_composition.py`）全空** → 证明「设备恢复后直接跑 build 会编译旧代码」这个雷真实存在（正是 round-8 审计 G1/G5 警告的场景）。③ 据此新建 2 个零策略变更、离线可验产物：`C:\ai\SD\.decky-probe\r11_predeploy_check.py`（**READ-ONLY 预部署校验**：证明当前 `sync.tar.gz` = **57 成员**且 G1 helper 在 tar / driver 不在 tar / **G5 `tar 内 deckymod/*.py` 集合 == 本地磁盘 18 个 `.py`**（`comm -13` 不会误删合法模块）/ 6 根文件 / src i18n 双字典 / 8 个新后端模块 / 9 个测试文件 / driver 的 G4 守卫+G5 清理+tsc+rollup+repack 全在 / dist 源存在 → `PREDEPLOY_ALL_OK=True` / EXIT=0）；`C:\ai\SD\.decky-probe\r11_deploy_and_build.ps1`（**一键编排器**：单一短探活 → 上传当前零漂移 tar 覆盖陈旧快照 → 单独上传 round-8 加固 driver（按设计不在 tar 内，避免 bash 自覆盖）→ `terminal/start` 跑真机 `bash rebuild_final.sh`（解包 + G5 stale-clean + `tsc --noEmit` + `rollup -c` + unittest + `status_probe2` + `repack.py`）→ 回传新 ZIP 本地字节校验；每步检查 HTTP 码、失败即干净退出、不 spin；全程**纯构建**：不激活 nexus（无 D1）、不写 `Mods/`（无 D2）、不翻 capability、不重部署到 root 目录）。**上传语义**已逐字核对 `html_templates.py:6891-6990 handle_upload`：`dest_path` 是目录（realpath+makedirs 后成 `upload_dir`），`file_path=upload_dir/<filename>` → 传 `/home/deck/deckymod-build/` 即覆盖陈旧 tar。④ **点火结果**：设备窗口在编排器写好前再次失联（3 次探测 `PORT_{{HELPER_PORT}}/8081/8080=000 RC=28`、`terminal/start=000`）；`r11_deploy_and_build.ps1` 干净退出 `STEP0_REACH=000 / DEVICE_UNREACHABLE_NOW / No files changed`（exit 2），**未上传、未编译、未改任何文件**。按效率纪律不反复探、不下「设备永久离线」结论（历史教训：端口/路由间歇可达）。⑤ 收口复验全绿：`r4_tar_drift.py` `TAR 57 CUR 57 / MISSING 空 / STALE 空 / BYTE_CHANGED_COMMON 0` / EXIT=0；`Ran 158 tests OK` / UT_EXIT=0；`validate_i18n`/`validate_p0`/`validate_nexus_unwired` 全 EXIT=0；`r8_zipload_probe.py` `ZIP_ENTRIES 33 / ERROR_CODE_COUNT 50 / VERDICT PASS_ZIP_LAYOUT_LOADS` / EXIT=0；`ROADMAP_LINES` 复核 + `\[[xX]\]` 零勾表。**诚实边界**：本轮**没有**真机 `tsc`/`rollup` 产物、没有新 `dist/index.js`、没有新 ZIP、没有重部署、没有真机 QAM 目视；`dist/index.js` 仍 96224 B `ee218850…` 旧 Track B；组合证明 ≠ 功能已激活；仍 UNWIRED / 未接第 12 RPC / 前端零引用 / errors.py 仍 50 码；真实 Nexus key 字符集待联网核实；Deck 端点 :{{HELPER_PORT}} 无鉴权(S9) / V8 翻转(S10) 只报告待裁决；D1–D6 待用户裁决（**自动续作 ≠ 批准，尤其 D2 破坏性 A/B**）；goal 保持 active，不调 `update_goal(complete)`。**下一步**：用户让端点保持可达后重跑 `r11_deploy_and_build.ps1` 即可一次完成真机编译 + 重打 ZIP（这是设备恢复后被阻塞最久、且完全在授权范围内的真实里程碑）；或先裁决 §4 D1–D6。

round 12 追加（**决定性里程碑：10+ 轮来第一次真机编译成功**、纯构建、仍零重部署）：① 本轮为自动续作（非 D1–D6 裁决）。`get_goal` → `goal-c9e307e2` rev4 / active / armed / roundsStarted **12** / 256。② 先修 round-11 编排器的两个会白白错过设备窗口的真实弱点：`r11_deploy_and_build.ps1` Step0 原只探 `/` 根路径（历史上 `/` 返 000 但 `terminal/start` 仍存活，属假阴性）→ 改为探真正依赖的 `terminal/start` 路由；并把 `$ErrorActionPreference` 从 `Stop` 改 `Continue`、移除全部 `curl -S`（超时 stderr 在 Stop 下会变 `NativeCommandError` 终止脚本）。新建 `C:\ai\SD\.decky-probe\r12_wait_and_fire.ps1`（有界 watcher：6s 轮询、8 次探测，命中 `terminal/start=200` 才点火，否则干净退出零改动）。③ **点火结果（后台 job pwsh-c5aebc14632242d8，exit 0）**：`ATTEMPT_1=200` 设备第一次探活即回来 → 编排器完整跑通：`STEP0_TERMINAL=200 STEP0_ROOT=200` / `STEP1_UPLOAD_TAR=200`（155149 B 零漂移 tar 覆盖陈旧 117144 B）/ `STEP2_UPLOAD_DRIVER=200` / `STEP3_START=200`；`r11_build_result.txt`（39 行 RC=0）逐字要点：**`TSC_EXIT=0` / `ROLLUP_EXIT=0`**（真机 `tsc --noEmit` + `rollup -c` 全过，rollup `created dist in 2.2s`）/`DIST_SIZE=101217` / `DIST_SHA=adc072c11f0b57b45e7fc0216725f73ff0908c1a97db00cd944a0b358bb19471` / `Ran 158 tests OK` `UT_RC=0` / `STATUS_OK True` `MOD_COUNT 27` `ZERO_DAMAGE True` / `REPACK_BEGIN` `SIZE 143395` `SHA256 71abc8baf108d65b517a92d1b8cc14ede387657a244c312a0393d9ee7578acc2` `ENTRIES 33` / `REBUILD_DONE`；`STEP4_DOWNLOAD_ZIP=200` 本地 `LOCAL_ZIP_BYTES=143395` / `LOCAL_ZIP_SHA256=71ABC8BA…`（与设备逐字一致）。④ `C:\ai\SD\.decky-probe\verify_r12_build.py`（READ-ONLY，21 项全 PASS / `R12_ZIP_VERIFY_ALL_OK=True`）：ZIP SHA 与设备一致、33 条目、`dist/index.js` SHA==设备 `adc072c1…` 且**不等于旧 Track B `ee218850…`**、bundle 含 `CATALOG_BTN`+中文「游戏目录/星露谷物语」（证明 **P0 分类目录前端真进了产物**）、`main.py` 零 `import nexus|auto_import|credentials`（**三个新后端模块仍 UNWIRED**）、`py_modules/` 布局 28 文件含 nexus.py/auto_import.py/credentials.py/registry.json。**意义**：round-7 前端「机械预检非 tsc」与 round-1–10「前端从未进 dist」的诚实缺口，本轮由真机 tsc+rollup 决定性闭合；前端类型/编译首次成为机器证据。⑤ 诚实边界（不夸大）：这是**纯构建+字节验证**，不是重部署、不是激活、不是 QAM 目视——已部署插件目录（root:root 755）未动，新 ZIP 未安装，Nexus 下载/自动导入/多游戏写回仍需 D1（第 12 RPC）/D2 破坏性裁决；真机 `status_probe2` 仍 `read_only true`（Amethyst 占用，27 MOD 零破坏）；`dist/index.js` 本地工作副本仍是旧 96224 B（新 101217 B 只在 Deck 构建树与下载 ZIP 内）；端点 :{{HELPER_PORT}} 无鉴权(S9)/V8 翻转(S10) 只报告；V1 唯一 CLOSED、V2–V20/F1–F3 全 OPEN、原 G3(RimWorld 294100) OPEN/NOT SHIPPABLE、Step5 写回 OOS、Track C 独立门控、hash↔loaded bundle 仍 MEDIUM 必要非充分（新 bundle 未在 QAM 目视加载）。⑥ 状态纪律：goal 保持 **active**、不调 `update_goal(complete)`、不写 CLOSED、不勾 §B.4 / `[ ]`、不翻 V#/F#、不放宽 strict、不碰 Amethyst、不假设 root、不关只读、不宣称全游戏通用一键装、未伪造真机证据；本轮只改 `.decky-probe/` 下 2 个脚本 + 新增 verify_r12_build.py + 1 处 docs 加性注记。⑦ 收口后设备仍可达（`DEVICE_REPROBE=200`），补一个 READ-ONLY 真机探针 `h_0d8615a4_result.txt`（RC=0）把「纯构建/零重部署」从声明升级为机器证据：**`DEPLOYED_DIST_SHA=ee2188508b4b0312` / `DEPLOYED_DIST_SIZE=96224`**（已部署插件目录 `root:root 755` 的 `dist/index.js` 仍是旧 Track B，未被覆盖）vs **`BUILDTREE_DIST_SHA=adc072c11f0b57b4` / `BUILDTREE_DIST_SIZE=101217`**（Deck 构建树新产物）vs **`NEW_ZIP_SHA=71abc8baf108d65b` / `NEW_ZIP_SIZE=143395`**（Downloads 里待用户经 Decky UI 安装的新包），`ZERO_REDEPLOY_OK`。即：新前端已真机编译并可交付，但**未安装、未激活、未在 QAM 目视**，重部署仍是用户单独动作。

round 13 追加（**设备真机真值：惰性模块在冻结解释器 + 真实交付布局下加载全通过**，纯 READ-ONLY 探针、零重部署）：① 本轮为自动续作（非 D1–D6 裁决）。`get_goal` → `goal-c9e307e2` rev4 / active / armed / roundsStarted **13** / 256；重探设备仍 `PORT_{{HELPER_PORT}}=200` / `PORT_8081=200` / `terminal/start=200`，本机 `Ran 158 tests OK` / UT_EXIT=0。② **动机**：round-8 审计 (e) 明确点名「未来 D1 接线 nexus 时须另验 `urllib.parse`/`ipaddress`/`ssl` vs 冻结 PYZ」——v3.3.1 的 PyInstaller PYZ 历史上是 partial xml（故有 `deckymod/__init__.py::_ensure_elementtree` shim），而三个惰性模块 `nexus`/`auto_import`/`credentials` 从未在**真机冻结解释器环境 + 真实 ZIP `py_modules/` 布局**下被导入验证过。③ 新建 `C:\ai\SD\.decky-probe\r13_frozen_import_probe.py` + `r13_run.ps1`（READ-ONLY，不碰部署目录/`Mods/`/registry、不启动第二个 loader——round-3 教训）：`/usr/bin/python3` 3.14.6 + 把 LIVE 冻结 bundle 的 MEI 解包目录（`/tmp/_MEI0000056870v1Gr`）加入 `sys.path` 以复用同一套 C 扩展/库；从刚 Deck-build 的 `143395 B` ZIP 解出 `py_modules/` 28 文件到构建树临时目录（**非部署插件目录**）再 import。④ **决定性输出（`r13_probe_result.txt`，`R13_RC=0`）**：`PY_VERSION 3.14.6` / `MEI_DIR /tmp/_MEI0000056870v1Gr MEI_COUNT 1`；**19 个 stdlib 全 `IMPORT_OK`**（`ipaddress`/`urllib.parse`/`urllib.request`/`http.client`/`hashlib`/`math`/`stat`/`json`/`re`/`os`/`ssl`/`_ssl`/`aiohttp`/`certifi`/`multidict`/`yarl`/`frozenlist`/`propcache`/`attrs`）；**5 个模块全 `MODULE_OK`**（`deckymod.nexus`/`deckymod.auto_import`/`deckymod.credentials`/`deckymod.archive`/`deckymod.state_mutator`）、`XML_ETREE_SHIM_OK True`；纯函数实跑 `SAFE_DOMAIN stardewvalley` / `IS_VALID_KEY True` / `NX_TO_E_COUNT 15` / `CHECK_URL_API_OK` / `CHECK_URL_LOCAL_REJECTED NX_LOCAL_HOST`（SSRF 防护正确 raise，首跑误标 FUNC_FAIL 已修为断言 raise）/ `CHECK_URL_CDN_OK`；`NEXUS_TOP_IMPORTS [...]` + **`URLLIB_REQUEST_LAZY True`**（urllib.request 仍惰性，顶层只 `urllib.parse`）；`TMP_CLEANED True`。**意义**：D1 接线时「冻结 PYZ 缺 stdlib」这一曾被列为 VERIFY-ON-DEVICE 的阻塞，本轮由真机决定性排除；三个惰性模块将来可安全 import。诚实上限：这是系统 python3 进程 + 冻结 bundle 库集（b219 方法），**非字面在活插件进程 2104 内**（`/proc/2104/maps`/`environ` 不可读，结构性 V2）；不代表已接线/已激活。⑤ 收尾 `h_063676ff_result.txt`（RC=0）：`DEPLOYED_DIST_SHA=ee2188508b4b0312` / `DEPLOYED_DIST_SIZE=96224`（部署插件仍未动）、`PROBE_FILE_CLEANED=True` / `UNPACK_RESIDUE=NONE`（构建树探针临时文件已清，无残留）、`NEW_ZIP_STILL_THERE=True`（新包仍在 Downloads）。⑥ 状态纪律：goal 保持 **active**、不调 `update_goal(complete)`、不写 CLOSED、不勾 §B.4 / `[ ]`、不翻 V#/F#、不放宽 strict、不碰 Amethyst、不假设 root、不关只读、不宣称全游戏通用一键装、未伪造真机证据；本轮只新增 `.decky-probe/` 下 2 个探针脚本 + 1 处 docs 加性注记，未改任何业务代码/产物/部署。仍 OPEN：D1–D6 裁决（尤其 D2 A/B）、接线成第 12 RPC、重部署 + QAM 目视、真实 Nexus key 字符集待联网核实、端点 :{{HELPER_PORT}} 无鉴权(S9)/V8 翻转(S10) 只报告。

round 14 追加（**设备真机真值 + 独立 NO-GO 裁定：两条旧假设被推翻、但本轮零写操作**，纯 READ-ONLY 探针、零重部署）：① 本轮为自动续作（非 D1–D6 裁决）。`get_goal` → `goal-c9e307e2` rev4 / active / armed / roundsStarted **14** / 256；设备窗口延续 round 12–13：`PORT_{{HELPER_PORT}}=200` / `PORT_8081=200` / `terminal/start=200`（本轮开窗口即用、未反复探），本机 `Ran 158 tests OK` / UT_EXIT=0。② 动机：前 13 轮已把「能离线做的」做满（158 tests / 真机 `tsc --noEmit`+`rollup -c` 产出 143395 B ZIP / 冻结解释器导入验证）；本轮不再堆第 14 个 UNWIRED 测试，改用真机窗口回答「新构建的 P0 分类目录能否由我在真机落地 / 真实 Nexus 与 CEF 现状究竟如何」，对应目标「按游戏分类查看」+ 用户明说「通过真机自行测试功能与获取相关真值」。③ 新建 `C:\ai\SD\.decky-probe\r14_probe.py` + `r14_run.ps1`（沿用 round-13 稳健模板：`Continue` + 无 `-S` + 自查 HTTP 码；READ-ONLY 不碰部署目录/`Mods/`/不启动第二个 loader）。**④ 决定性输出（`r14_probe_result.txt`，RC=0，64 行）**：`UID_EUID 1000/1000`；**推翻历轮假设**——`/home/deck/homebrew/plugins/` 与 `decky-mod-manager/` 目录确为 root:root 0o755 `w=False`，但**目录内所有已存在文件**（`dist/index.js`、`main.py`、15 个 `py_modules/deckymod/*.py`、10 个 `py_modules/registry/*.json`）全是 `uid=1000` `w=True` 可写，**仅 `plugin.json`** 是 root:root `w=False`；`PLUGINS_DIR_WRITABLE False`；`WHICH decky/decky-loader/plugin_loader = None`（无 shell 工具）。`DEPLOYED_DIST 96224 ee218850…`（仍是旧 Track B），`BUILT_ZIP 143395 71abc8ba…`（新构建 ZIP 完好）。CEF 8081/8080 各 5 target（QAM `QuickAccess_uid2` 当前 `about:blank`、插件 tab 未挂载）；Nexus **两个无 apikey 请求都 401**：`/v1/users/validate.json` 与 `/v1/games/stardewvalley.json` → `HTTP=401 {"message":"Please provide an authentication method"}`；真机真实描述符上 `Registry().catalog()` = `CATALOG_COUNT 4`：stardew(413150/enabled/active/operable/file_drop/smapi)、rimworld(294100/planned/xml_list)、factorio(427520/planned/file_drop)、valheim(892970/planned/unsupported/bepinex5)，`CATALOG_OPERABLE_IDS ['stardew']`、`CATALOG_JSONSAFE True`（**P0 分类在真机真实 registry 上输出正确**，但取自 BUILD 树而非已部署进程）。⑤ 派 `steamos-path-researcher` READ-ONLY 裁定（m09038/m09039）：**(1)** POSIX 上 dir `w=False` 只挡目录项增删，覆盖已存在文件字节只需文件自身写位 → `open(f,"wb")` 物理可行；但 `os.replace`/`rename` 需目录写 → `fsops.atomic_write_bytes`（插件唯一安全写入器）失败，只剩非原子截断（对活 loader 有 torn-read 窗口）；新建文件（3 个从未部署的 nexus/auto_import/credentials.py）与 `plugin.json` 均不可达。** (2) 部分可行但无效**：P0 只动 3 个已存在文件（main.py `_with_catalog`、registry.py `catalog()`、dist/index.js），零 root 字节覆盖物理可能，33 条目的完整 ZIP 仍不可；但 plugin_loader 已 `import` 缓存 `sys.modules`、CEF 只在 QAM 打开时加载 dist → 覆盖字节对运行进程**零运行时效果**。** (3) 裁定 NO-GO**：决定性理由=常驻约束「不 pkill / 不热替换已部署插件」+「自动续作 ≠ D1–D6 裁决」；热替换活映射插件得到半旧半新内存态、reload 需 QAM 重开或 loader 重启（= 禁止的 pkill）；byte-exact 必要非充分；**只报告、等用户显式经 Decky UI 装 ZIP**。故本轮**确实零写操作**（未覆盖任何已部署文件、未 build、未重部署、未翻 capability）。**(4) 推翻「public metadata」假设**：Nexus **无匿名层**——连游戏元数据/validate 都必须带个人 apikey，D1 影响=首跑 UI 须先经 OSK 收集 key 才能做任何 Nexus 调用、`users/validate.json` 是天然的 key 校验/连通性探针、`nexus.py` 须把 401（缺/坏 key）与 403/429/5xx 明确区分；诚实上限=探针用 `/usr/bin/python3` uid=1000 普通 urllib，证明的是 Deck 出站的鉴权要求，**不是**冻结 PyInstaller 3.14.6 后端可达性（Q1 仍 OPEN），且 401 文案是「missing auth」非「bad key」，须真实 key 复核。⑥ 本地收口全绿：`Ran 158 tests OK`、compileall=0、validate_i18n/validate_p0/validate_nexus_unwired/r4_tar_drift/r8_zipload_probe/r11_predeploy_check 全 EXIT=0、frontend_preflight EXIT=0；`ROADMAP_LINES=122`（写此前）、`TAR=155149`、`BUILT_ZIP=143395`。⑦ 状态纪律全守：goal 保持 active 不调 `update_goal(complete)`、不写 CLOSED、不勾 `[ ]`/§B.4、不翻 V#/F#、不放宽 strict、不碰 Amethyst、不假设 root、不关只读、不宣称全游戏一键装、未伪造真机证据、未把 BUILD 树 catalog 冒充已部署进程输出；本轮只新增 `.decky-probe/` 下 2 个探针脚本 + 1 处 docs 加性注记，未改任何业务代码/产物/部署。⑧ 诚实边界：新 bundle 仍未安装/未激活/未在 QAM 目视；`dist/index.js` 已部署副本仍 96224 B `ee218850…` 旧 Track B；D1–D6 待裁决（尤其 D2 破坏性 A/B）；真实 Nexus key 字符集与「带真 key 的 200 响应」待联网核实；端点 :{{HELPER_PORT}} 无鉴权(S9)/V8 翻转(S10) 只报告。

round 15 追加（**真机 Q1 收口：生产 nexus.py 在「冻结 bundle 原生 TLS 扩展 + 系统解释器」兼容性代理下可到达 Nexus**，纯 READ-ONLY 探针、零重部署、零写操作）：① 本轮为自动续作（非 D1–D6 裁决）。`get_goal` → `goal-c9e307e2` rev4 / active / armed / roundsStarted **15** / 256；设备窗口延续：`TERMINAL_START=200` / `PORT_{{HELPER_PORT}}=200`；本机 `Ran 158 tests in 1.725s OK (skipped=1)`、compileall/i18n/p0/nexus_unwired/drift 全 EXIT=0。② **动机**：round-14 团队裁定（m09038）明确留 **Q1 OPEN**——「冻结 PyInstaller 3.14.6 后端能否真的到达 Nexus」，因 r14 用系统 python3 + 普通 urllib，只证 Deck 出站鉴权要求，**未证生产 `deckymod/nexus.py` 网络代码在冻结栈上真发请求**；round 13 只证「惰性模块能 import」、round 3 只证「手写 aiohttp GET」、round 14 只证「系统 urllib」。③ 新建 `C:\ai\SD\.decky-probe\r15_frozen_net_probe.py` + `r15_run.ps1` + 设备侧清理（沿用 round-13 稳健模板：`Continue` + 无 `-S` + 自查 HTTP + multipart file 字段最后；不碰部署目录/`Mods/`/registry、不启动第二个 loader——round-3 教训）。方法：`/usr/bin/python3` 3.14.6 + LIVE 冻结 bundle MEI（`/tmp/_MEI0000056870v1Gr`）入 `sys.path`；从新构建 143395 B ZIP 解出 `py_modules/` 28 文件到构建树临时目录（**非部署插件目录**）→ import 生产 `deckymod/nexus.py` → 用生产 `nexus.default_opener` / `users_validate` / `get_download_link` 真发请求到 `api.nexusmods.com`（无 apikey / 假 key）。④ **决定性输出（`r15_probe_result.txt`，`R15_RC=0`）**：`PY_VERSION 3.14.6` / `MEI_DIR /tmp/_MEI0000056870v1Gr MEI_COUNT 1`；`_ssl.so` 来自 MEI、`ssl.py`/`urllib.*`/`certifi` 解析自系统 `/usr/lib/python3.14`（二者 `OpenSSL 3.6.5 29 Sep 2026` 一致，无 ABI 错配）；`EXTRACTED 28 INIT True` / `NEXUS_OK`（生产模块真从交付布局加载）；`RAW_STATUS 401` / `RAW_CT application/json; charset=utf-8` / `RAW_BODY {"message":"Please provide an authentication method"}`（**真 TLS + 真 Nexus 响应**）；`users_validate(无 key)` → `{'ok': False, 'code': 'NX_AUTH_REQUIRED', ..., 'status': 401}` 且 `USERS_VALIDATE_JSONSAFE True`；假 key → 同 `NX_AUTH_REQUIRED`、`FAKEKEY_NOT_ECHOED True`；`get_download_link` → `NX_AUTH_REQUIRED`；`TMP_CLEANED True`。⑤ **团队独立裁定（m09132 / m09137，READ-ONLY）**：**(1) Q1 作为「可操作的 D1 阻塞 / 可行性兼容性」已闭合**——证了「冻结库缺/坏 ssl/urllib」风险不存在、生产 3 条路径全返 JSON-safe `NX_AUTH_REQUIRED`、假 key 不回显；**但非严格「已部署冻结后端已联网」**。（2）**混合栈应表述为兼容性代理**：系统解释器无法导入 PyInstaller PYZ 纯 Python 模块，`sys.path` 只触达 MEI 的**原生扩展** `_ssl.so`，`ssl.py`/`urllib`/`certifi` 来自系统 stdlib/site-packages → 正确措辞「production nexus.py ran under a 3.14.6 system interpreter with the frozen bundle's native TLS extension (`_ssl.so`, OpenSSL 3.6.5) on sys.path; both report the same OpenSSL ⇒ no ABI mismatch」，**绝不可写「ssl/urllib/certifi 全来自 MEI」或「已部署冻结后端到达 Nexus」**。（3）`RAW_CLOSED False` 是**预期非 bug**：`_Response` 构造即 `closed=False`（`nexus.py:219`）、关闭是调用方 `_http_json` 的 finally（`:291-293`，`users_validate` 全路径已走到），且是内存缓冲无 socket 泄漏；探针原注释把 401 分支说成「bounded read + close」不准确（401 走无界 `e.read()` `nexus.py:263`，bounded 是 2xx 分支 `:266`），已就地修正注释，LOW 非阻塞。（4）**仍 OPEN 的 residual**：ⓐ 2xx 路径（无真实个人 key，只证 401）；ⓑ `download_to_inbox`/CDN/`require_api_host=False`/size-cap/`fsops.atomic_write_bytes` 写盘路径未测；ⓒ 字面在活插件进程 2104 内运行（V2 结构性 `/proc` 不可读）；ⓓ 冻结 PYZ 自身纯 Python 栈。⑥ **诚实上限 / 禁写清单**：只证无认证 401 路径（401 文案是「missing auth」非「bad key」，假 key 证的是**脱敏**不是 key 校验/拒绝）；非活体进程、非 2xx/下载/链接解析已证、非 `network_download` 启用 / nexus 已接线 / D1 已批准（`main.py` 仍零 nexus import、11 RPC、`network_download:false`）、非「冻结 CA 库」（certifi 来自系统）；`RC=0`/`TMP_CLEANED True` 仅探针内务。⑦ 设备侧清理（`r15_cleanup_result.txt`）：`PROBE_CLEANED=YES` / `UNPACK_RESIDUE=NONE` / `DEPLOYED_DIST=ee2188508b4b0312 96224`（已部署旧 Track B 仍未动）/ `NEW_ZIP_STILL_THERE=YES`。⑧ 状态纪律全守：本轮只新增 `.decky-probe/` 下 2 探针脚本 + 1 处 docs 加性注记；未改任何业务代码/产物/部署、未 build、未重部署、未翻 V#/F#/§B.4、未写 CLOSED、未勾 `[ ]`、未调 `update_goal(complete)`、不碰 Amethyst、不假设 root、不关只读、不放宽 strict、不宣称全游戏一键装、未伪造真机证据。goal 保持 **active**（两外部门控仍关=D1–D6 裁决尤其 D2 A/B + 接线成第 12 RPC/重部署+QAM 目视；真实 Nexus key 字符集 + 带真 key 的 200 待联网核实；S9/S10 只报告）。

round 16 追加（**两个设备专属缺口闭合：生产 `download_to_inbox` 写盘路径 + 真机 POSIX 凭证 0o600**，纯 READ-ONLY 探针、零重部署、零写操作于已部署插件 / `Mods/` / registry）：① 本轮为自动续作（非 D1–D6 裁决）。`get_goal` → `goal-c9e307e2` rev4 / active / armed / roundsStarted **16** / 256；设备窗口延续：`TERMINAL_START=200` / `PORT_{{HELPER_PORT}}=200`；本机 `TAR=155149 ZIP=143395 DIST=96224`。② **动机**：两个只有设备可达才能取真值、且零策略变更的缺口 = **(A)** round-15 团队裁定（m09132）明确留 residual ⓑ「`download_to_inbox` / CDN / `require_api_host=False` / size-cap / `fsops.atomic_write_bytes` 写盘路径未测」；(B) round 9–10 凭证 `0o600` 安全姿态只在 Windows 沙盒测过（`posix=False`、`mode_actual=None`、symlink 用例 skip），从未在真机 ext4/btrfs 验证。③ 新建 `C:\ai\SD\.decky-probe\r16_device_probe.py` + `r16_run.ps1` + `r16_cleanup.ps1`（沿用 round-13 稳健模板；不碰部署目录 / `Mods/` / registry、不启动第二个 loader——round-3 教训）。方法：`/usr/bin/python3` 3.14.6 + LIVE 冻结 bundle MEI（`/tmp/_MEI0000056870v1Gr`）入 `sys.path`；从新构建 143395 B ZIP 解出 `py_modules/` 28 文件到**构建树临时目录** `.r16_work`（非部署插件目录）→ import 生产 `deckymod/nexus.py` / `credentials.py` / `fsops.py`；用**注入 FakeOpener（无真实网络）** 驱动 `download_to_inbox`，只写构建树临时 inbox（**从不写游戏 `Mods/`**）；凭证 save/load/delete/status 只写构建树临时 creds 目录；全部临时目录末尾删除。④ **决定性输出（`r16_probe_result.txt`，`R16_RC=0`）**：`PY_VERSION 3.14.6` / `MEI_DIR /tmp/_MEI0000056870v1Gr MEI_COUNT 1` / `POSIX_FCHMOD True` / `EXTRACTED 28 INIT True` / `MODULES_OK`（生产模块真从交付布局加载）。**GAP A 闭合**：`D2I_HAPPY OK=True SAFE=True`、落盘 bytes / SHA256 / size 全 match、`D2I_APIKEY_NOT_ON_CDN True`、`D2I_RESULT_HAS_NO_BYTES True`；8 个边界失败码全正确（`NX_BAD_FILENAME`×2 / `NX_LOCAL_HOST` / `NX_INBOX_MISSING` / `NX_TOO_LARGE`×2 / `NX_TRUNCATED` / `NX_HTTP`）、`D2I_NO_STRAY_FILES True`（零残留）。**GAP B 闭合**：`CRED_SAVE OK=True SAFE=True`、`CRED_STATUS present=True posix=True mode_actual=0o600 mode_ok=True`、`CRED_ONDISK_MODE 0o600 IS_0600 True`、`CRED_LOAD_MATCH True IS_BARE_STR True`、`CRED_STATUS_NO_SECRET True`、**`CRED_SYMLINK_DELETE_REFUSED / STATUS_REFUSED / SAVE_REFUSED` 全 True**（Windows 跳过的用例现由真机证明）。`CRED_PATH_UNDER_WORK True`、`DEPLOYED_DIST ee218850… 96224` 未动、`NEW_ZIP_STILL_THERE True`、`WORK_CLEANED True`。⑤ **两处诚实辨析（非 bug）**：`D2I_ONDISK_MODE 0o644` = 下载 ZIP 落 inbox 的默认 mode（凭证才是 0o600，设计如此）；`CRED_DELETE False` = symlink 清理后文件已 absent，预期 noop。⑥ **仍 OPEN / 禁写**：探针是「系统 python3 + 冻结库集」兼容性代理，**非字面在活插件进程 2104 内**（V2 结构性 `/proc` 不可读）；FakeOpener = **非真实 2xx CDN / 非真实网络下载**；无真实 apikey；生产模块仍 **UNWIRED**（`main.py` 零 `import nexus|auto_import|credentials`、仍 11 RPC、`network_download:false`）、**未接线 / 未激活 / 未重部署 / 未真机 QAM 目视 / 未写游戏 `Mods/`**；真实 Nexus key 字符集与「带真 key 的 200」仍待用户提供；`dist/index.js` 已部署副本仍 96224 B `ee218850…` 旧 Track B。⑦ **状态纪律**：goal 保持 `active`、不调 `update_goal(complete)`、不写 CLOSED、不勾 `[ ]` / §B.4、不翻 V#/F#、不放宽 `strict:true`、不碰 Amethyst、不假设 root、不关只读、不宣称全游戏一键装、未伪造真机证据；本轮只新增 `.decky-probe/` 下 3 探针/清理脚本 + 本注记，未改任何业务代码 / 产物 / 部署。⑧ 本地全绿复核：`Ran 158 tests OK`、compileall / validate_i18n / validate_p0 / validate_nexus_unwired / r4_tar_drift / frontend_preflight 全 EXIT=0；设备侧 `PROBE_LEFT=NONE` / `UNPACK_RESIDUE=NONE` / `DEPLOYED_DIST ee218850… 96224` / `NEW_ZIP 71abc8ba… 143395`。

⑨ **团队独立裁定（steamos-path-researcher m09216，READ-ONLY，未改文件/未跑测试/未碰设备）**：两缺口均 **CLOSED，但仅在 FS / containment 层**，network / runtime 全部仍 OPEN。(1) residual ⓑ 于文件系统层闭合（happy path 用生产 `fsops.atomic_write_bytes` 的 mkstemp + `os.replace`、apikey 不落 CDN 头、8 边界码全对零残留）；**仍 OPEN**：真实 2xx/CDN（FakeOpener）、真实 key 的 401/403/429、冻结后端活进程可达（V2）、接线/解锁。(2) `0o644` **设计如此非问题**：`fsops.atomic_write_bytes` 默认 `mode=0o644`（下载 ZIP 非机密、游戏/用户须可读），凭证才显式 `mode=REQUESTED_MODE=0o600`——不同数据类不同 mode，intentional；唯一 LOW note：多用户 Deck 上别的本地用户可读该 archive（非 secret），**只记录不「修」**。(3) `CRED_DELETE False` **预期非 bug**：探针把 cp 换成 symlink→验 delete/status/save 三拒绝→`os.unlink(cp)` 删掉的是 symlink，随后 `delete_key` 见 absent → `_ok(deleted=False, reason="absent")`，正是幂等「已不存在」语义。(4) round 9/10 Windows 缺口 **CLOSED**：`POSIX_FCHMOD True`、`posix=True`/`mode_actual=0o600`/`mode_ok=True`、`_recheck_no_symlink` 在 load/delete/status/save 全生效且真机 symlink-3 拒绝为真（Windows 曾 SKIP）；**仍 OPEN**：活插件进程创建的真实 key 文件（V2）、secret-at-rest vs 同 uid 其它进程、OSK 粘贴路径、无 keyring。(5) **禁写/夸大清单**（与 ⑥ 互为印证）：不可声称字面活插件 PID 2104、真实网络/2xx/CDN、任何真实 apikey、模块已 WIRED（仍 UNWIRED / 11 RPC / `network_download:false`）、任何 `Mods/` 写入、已部署插件已更新（`DEPLOYED_DIST ee218850… 96224` 未变）、写回签核。安全的统一措辞：**「FS/containment + on-disk perms 已在真机冻结库集下验证；network、wiring、QAM、write-back 仍 OPEN/DEVICE」**。本裁定不改变 goal 状态。

请你：
1. 对 §4 的 **D1–D6** 给出裁决（尤其 **D2 的 A/B** 是唯一破坏性决策）；
2. 或直接说「先做 P0 只读分类目录」—— 这相无需任何策略变更，我可在下一轮实现 + 本机 `tsc --noEmit`/`rollup -c` 复验 + 真机 DOM 取证后再交你目视；
3. 若还需要我打开别的设备能力（如允许在活插件进程内跑一次 RPC 网络 hook 以字面证明 §1 第 4 点），请提出，我会列入该轮需求。

round 18 追加（**用户授权接线后，Nexus 只读半链从 UNWIRED 变为 WIRED；本机 173 tests + 真机 tsc/rollup/unittest 全绿；真机端到端取到 200；决定性发现「下载链接接口对免费账号返 403」这一外部会员策略，诚实记录不绕过**。本轮**无重部署、无 `Mods/` 写入、无状态翻转**）：
① 用户裁决（m09261 逐字「1、授权 2、请帮我打开浏览器，我帮你登录 3、我已安装」；m09319 给出真实 96 位 Nexus key 并回「B」）→ D1 接线获显式授权；D2 仍选 B 但**破坏性前提仍未执行**（见 ⑧）。
② **后端接线（我，写域 `main.py` + registry + tests）**：`main.py` 新增 `from deckymod import auto_import / credentials / nexus`；新增 `_core_to_envelope(res, mapper, stage)`（把 CR_*/NX_* 模块内码经 `CR_TO_E`/`NX_TO_E` 映射成已存在的 `E_*`，从而 `ERRORS` 仍恰好 50 码、i18n `ERR_E_*`/`CAT_*` 无需扩张）；新增**非抛出式** `_network_download_gate()`（只用 `err()` 返回而不 raise，因为 `_guard` 会把任何异常压成 `E_UNKNOWN` 并丢掉具体码）；新增 6 个位置参数 RPC `api_key_status` / `set_api_key` / `delete_api_key` / `nexus_validate` / `list_mod_files` / `nexus_fetch`；**public async RPC 计数 11 → 17**。三个**网络** RPC 走门控，三个**key 管理** RPC 刻意不走门控（只碰 0o600 本地凭证、不联网）。key 只由 `credentials.load_key()`（唯一裸 `str` 出口）读出后**直接**交给 nexus/auto_import，从不进 log/envelope/UI。
③ **capability 翻转（最小化）**：`registry/games/stardew.json:150` `network_download: false → true`，并改写 `capabilities_note` 明确「这只解锁下载到 inbox 的只读半链，**不解除写姿态**」。`detection_only:true`、`safety.refuse_if_external_manager:true`、`enable_disable:false` **刻意保持不变**；`workshop` / `loader_install` / `launch_option_edit` / `dll_override` / `proton_prefix_write` / `exe_installer` / `requires_root` / `requires_readonly_toggle` / `universal_one_click` 仍全 `false`。
④ **UNWIRED 守卫整体退役**（这是策略变更，不是测试凑数）：`tests/test_credentials.py::TestUnwired`→`TestWired`、`tests/test_composition.py::test_4`、`tests/test_auto_import.py::test_11`、`tests/test_integration.py::test_6`、`tests/test_catalog.py::test_no_new_rpc` 全部改为「已接线 + 17 RPC + 正向 import 断言」；`.decky-probe/validate_nexus_unwired.py` 语义 INVERT 为 round-18 WIRING 校验器（文件名保留以兼容既有命令），`validate_p0.py` 的 `== 11` 改 `== 17`。**保留**`tests/test_nexus.py` 里「urllib 仍惰性」的内部断言（那证明的是惰性，不是未接线）。
⑤ **新增 `tests/test_wiring.py`（14 用例）= 行为级而非静态断言**：真实 `credentials.save_key/load_key/key_status` 落盘 + mock 网络边界，逐 RPC 断言 8 键 Envelope、`SECRET` 从不出现在任何信封、`set_api_key` 只 log 布尔、`_guard` 把注入 `RuntimeError` 压成 `E_UNKNOWN`、门控在 `load_key` 之前就挡住、失败码 `CR_BAD_KEY`→`E_ID_INVALID`、`NX_AUTH_REQUIRED`→`E_CAPABILITY_DISABLED`、`fetch_and_import` 的 opener/engine 是**位置参数 0/1**（我曾误写成 kwargs，已修）、以及**决定性**一条：全 True 时引擎的 `E_EXTERNAL_MANAGER` **逐字透传不绕过**。
⑥ **本机全绿**：`Ran 173 tests OK (skipped=1)`（159 → +14）、`compileall` RC=0、`validate_i18n`/`validate_p0`/`validate_nexus_unwired`/`r4_tar_drift`/`r8_zipload_probe` 全 EXIT=0。
⑦ **前端（`decky-api-researcher`，写域仅 `src/`，5 文件，纯加性）**：`api.ts` 6 个 typed wrapper + 6 个 `callableHandles`（11 个原 wrapper 字节不变）；`types.ts` 加 `KeyStatusData`/`KeySetData`/`KeyDeleteData`；双 i18n 各 +18 `NEXUS_*`（245 → **263，parity 完全一致、无孤儿键**）；`index.tsx` 在 ACTIONS 与 INSTALLED 之间加**一个** `<PanelSection title={t("NEXUS_SECTION")}>`（OSK key 输入、Set/Clear、Validate、domain/mod_id/file_id、列文件、下载到 inbox（`allow_install=false`）、两段式导入、B 门禁说明），复用既有 `PROGRESS_EVENT`。`FORBIDDEN_MATCHES=0`（无 `as any`/`@ts-ignore`/`: any`），`strict:true` 未放宽，零新 npm 依赖，未改 `rollup.config.js`/`tsconfig.json`/lockfile。
⑧ **真机侧决定性证据（全部经 deck-helper `:{{HELPER_PORT}}` + 冻结/系统解释器，非字面活插件进程）**：
  - **构建**（`r11_deploy_and_build.ps1`，`r11_build_result.txt`）：`TSC_EXIT=0` / `ROLLUP_EXIT=0` / `DIST_SIZE=118664` / `DIST_SHA=7c10bbb8bccb3fca6f523e4abaf458ea0464564dc919fd7778bc41f824373802` / `Ran 173 tests` `UT_RC=0` / `ZIP 154002 B` `SHA256=66e41637416446734f3a5e85abdd64854b208e5569e54a1b89086a8f595ac9c5` / `ENTRIES 33`。**注意**：新 ZIP 落 `~/Downloads`，**已部署插件目录未动**（仍是 round-12 的 `adc072c1…`/101217），所以 QAM 里还看不到 Nexus 区块——需用户经 Decky UI 重装。
  - **修掉一个只有真机才暴露的测试卫生缺陷**：`tests/test_credentials.py::_tmpdir()` 用固定名，`test_symlink_credential_path_refused` 故意种下的 symlink 会**跨轮存活**，导致下一轮的 `test_path_is_under_data_dir_and_fixed_name` 把路径 realpath 到 `cred_outside/stolen.txt` 而失败（真机 `h_6f2fa25…` 定位，非生产代码 bug，属重复运行不幂等）→ 改 `uuid` 唯一后缀，本机连跑两次均 `173 OK`，真机复跑 `UT_RC=0`。
  - **凭证真机落盘**：`/home/deck/homebrew/data/decky-mod-manager/data/nexus_api_key`，`MODE_ACTUAL 0o600`、`MODE_OK True`、`LOAD_ROUNDTRIP True`、`KEY_NOT_IN_ANY_OUTPUT True`（`h_0fc1ef95`）。**踩过的坑**：deck-helper 的终端继承了它自己的 `DECKY_PLUGIN_RUNTIME_DIR`，首次把 key 写进了 `deck-helper-plugin/data/`（`h_ffe8e0ad`）——已删除错位副本并用本插件 `DECKY_*` 重写。
  - **真实网络 200**（`h_f275a6f9`）：`api_key_status` ok（`mode_actual=384` 即 0o600）；`nexus_validate` **HTTP 200**；`list_mod_files("stardewvalley", 2400)` **HTTP 200，343 个文件**；`status` appid `413150` / `read_only True` / `external_manager True` / `launch_options set`；`RPC_COUNT 17`。
  - **三角态 + 引擎门控（决定性，`h_9e2ff8e7`）**：注入 fake opener（生产代码预留的接缝）+ **真实 `FileDropEngine`** 指向 Amethyst 拥有的真 `Mods/` → `P1` `phase=inspect`（零写）、`P2` `phase=confirm`（零写）、`P3` **`E_EXTERNAL_MANAGER`**，detail 逐字 `external mod manager markers in /home/deck/.local/share/Steam/steamapps/common/Stardew Valley/Mods; read-only mode`；`ZERO_DAMAGE True`；同轮证明 `.dll` 放行（`install_relpath Mods/probe.r18gate`）而 `.exe` 仍被 `E_UNSAFE_ENTRY` 拒。
  - **外部会员策略（诚实边界，`h_b0d4e73a`）**：用**真实** key 走**真实**下载链接接口 → `NX_FORBIDDEN: HTTP 403`（Nexus 的 `download_link.json` 对免费账号不放行），被正确映射为 `E_CAPABILITY_DISABLED` 且 detail 保留 `NX_FORBIDDEN`。**未绕过、未伪造**。结论：下载半链「代码完备 + 真机以注入 opener 证明」，**但真实 CDN 取件受账号会员等级限制**；要真正下载需 Premium 或用户手动下载。
⑨ **安全收尾**：本地含明文 key 的两个文件（`.decky-probe/r18_key.txt`、`r18_key_probe.py`）已删除并复查「无文件再含该 key」；设备侧 `r18_key.txt` 由存储脚本自删（`SRC_DELETED True`），构建树仅余不含 key 的 `r18_store_key.py`。全程未回显 key。
⑩ **仍 OPEN / 未做**：已部署插件未更新（QAM 实机目视 Nexus 区块待用户重装）；**B 的破坏性前提未执行**（`.mm_deployed` + `Mods_Core` 仍在、27 个真 MOD 仍是 Amethyst 的符号链接部署），故 `nexus_fetch(..., True, True)` 在真机上**必然**返回 `E_EXTERNAL_MANAGER`；V1 仍唯一 CLOSED、V2–V20/F1–F3 全 OPEN、原 G3 OPEN/NOT SHIPPABLE；Step 5 写回 OOS；Track C 独立门控；后端 3 个模块 docstring 仍写 UNWIRED（历史文案，未回填）。**goal 保持 active，不调用 `update_goal(complete)`。**

## §6.5 Round 19 追加段：Nexus 下载链路 RETIRED，改为 GitHub Releases + 直连 URL

写于 2026-11-15。**只追加，不回填 §0–§6 的历史快照**（那些段落记录的是
round 18 及之前的事实，仍按当时口径成立）。

**触发原因（用户指令 m10068「不走Nexus，走其他地方实现下载MOD」）**：round 18
已接线完成并真机取证，但真实下载链路撞上外部商业策略 —— 用**真实** key 打
`download_link.json` 恒为 **HTTP 403 `NX_FORBIDDEN`**（Nexus 对非 Premium 账号
不放行下载链接端点）。这是外部规则，不是可修的 bug，也不绕过。故整条 Nexus
凭证 + 目录面被移除，而非留一半可用。

**替代来源（真机实测，非假设）**：唯一可端到端取件的是 **GitHub Releases**：
`GET /repos/{o}/{r}/releases/assets/{id}` + `Accept: application/octet-stream`
→ **302** signed `release-assets.githubusercontent.com` → 200 真 ZIP
（`Esca-MMC/DestroyableBushes` 44,252 B / 12 entries；`tiwe0/sdv-hd2d-release`
2,028,243 B）。**`browser_download_url` 在本机恒 502/0 B**（`github.com` 被
hosts 映射到 127.0.0.1 + 本地 TLS 代理），故永不使用该 URL 形态，只走 API
asset 端点两跳。CurseForge 403、ModDrop DNS 失败、Thunderstore 无 stardew 社区、
GitLab/itch/mod.io 不可达、`raw.githubusercontent.com` 不稳定 —— 全部真机复核。

**后端改动（4 个模块 + descriptor）**：
1. `deckymod/nexus.py` 降为**共享低层网络层**：`NX_ERRORS` 加 3 个模块内部码
   （`NX_HOST_NOT_ALLOWED`/`NX_NO_ASSET`/`NX_NOT_FOUND`，**不进 errors.py**）；
   `_check_url` 加 `allowed_hosts` **hostname 精确白名单** + 拒 userinfo +
   拒非 443 端口；新增 `_http_json_generic`（带自定义 header，404 → `NX_NOT_FOUND`）；
   `_fetch_bytes`/`download_to_inbox` 透传 `allowed_hosts`。
2. 新增 `deckymod/github_source.py`：`API_HOST`/`ASSET_HOSTS`/`PER_PAGE_CAP=5`；
   `search_repos` / `list_releases`（剔 `body`，`usable` = `.zip` + 三种二进制
   content-type）/ `resolve_asset`（**不跟随**，302 的 `Location` 必须命中
   `ASSET_HOSTS` 否则 `NX_HOST_NOT_ALLOWED`）；**不发任何凭据**。
3. `deckymod/auto_import.py` 纯加性：`NX_TO_E` 加 3 条映射；新增
   `download_and_import(opener, engine, *, url, filename, allow_install,
   after_confirm, ...)`，复用既有 `_inbox_dir`/`_listed_path`/`_install`/`_fail`。
4. `main.py`：**RPC 17 → 15** —— 删 6 个 Nexus RPC，加 `gh_search`/`gh_releases`/
   `gh_download`/`download_url`；删 `from deckymod import credentials`；新增
   `_source_cfg(name)` 读 descriptor；**4 个下载 RPC 全部走能力门控**（无例外）。
   `download_url` 在 RPC 内把 `NexusError` 转成具体 `E_*`（否则 `_guard` 会压成
   `E_UNKNOWN`）。
5. `registry/games/stardew.json`：新增 `download_sources{github, direct}`；
   `known_limitations` 加 `LIMIT_GH_COVERAGE`/`LIMIT_DIRECT_URL`（键数 4 → 6）；
   `capabilities_note` 改写；`network_download` 保持 true、`detection_only` 与
   `safety.refuse_if_external_manager` **刻意不动**。

**安全姿态（未放宽）**：`errors.py` 仍 **50** 码（NX_* 全部映射到既有 E_*，
双向断言）；不跟随二次跳转；token/apikey 绝不发 CDN；**不加「解析 IP 属私网就拒」**
（本机 hosts 把 github.com 映射 127.0.0.1 但有本地代理，IP 判定会判死可用路径）；
不改 Steam 启动选项、不装 loader、不写 Proton 前缀、不要 root、不关只读、
不宣称全游戏一键装。

**测试**：删 `tests/test_wiring.py`（14 用例全驱动已退役的 Nexus RPC）；
新增 `tests/test_github_source.py`（29）+ `tests/test_download_wiring.py`（19
行为级用例，注入 opener 走 `asyncio.run` 真调 4 个 RPC）；改 6 处旧断言
（17 → 15、`credentials` 反向断言、`NX_TO_E` 15 → 18 且双向完整性）。
本机 **`Ran 207 tests OK (skipped=1)`**、`compileall` RC=0、
`validate_i18n`/`validate_p0`/`validate_nexus_unwired`/`r4_tar_drift`/
`r8_zipload_probe` 全 EXIT=0。

**前端（round 19 收尾时补记）**：`src/` 五个文件已由主控完成替换 ——
`NEXUS_*` 18 键全部删除、新增 25 个 `GH_*` 键，双字典各 270 键 parity 为 0 漂移；
`api.ts` 4 个 wrapper + 4 个 `callableHandles`；`types.ts` 删 3 个 `Key*` 加 7 个
`Gh*`；`index.tsx` 的 `NEXUS_SECTION` 整段换成 `GH_SECTION`（搜索 → repo →
release → asset → 下载 → inspect → 两段确认，外加直连 URL 兜底与 `GH_B_GATE`
诚实说明行）。静态预检 `r19_frontend_preflight.py` 全绿：18+16+3 个 import 名
全部命中真实导出、`callableHandles ⊆ invoke()`、`invoke()` 的 RPC 名后端全有、
196 个 `t()` 字面量与 `ERR_` 码双字典齐全、无 `as any`/`@ts-ignore`/`: any`、
9 个文件括号配平。**但这不是类型检查**：`tsc --noEmit` 从未跑过。

**仍 OPEN / 未做**：QAM 面板**从未渲染、从未加载进 CEF、从未目视** ——
虽然 `tsc --noEmit` 与 `rollup -c` 在 Deck 上都是 `EXIT=0`、bundle 已是
`e4fa4a70…`/120512 B、整包 ZIP 也已产出（163030 B / 34 entries /
`5273ce12a8994021818d55f0d729a0c73004f436034da9841cea8847c95b6603`），但
**已部署插件仍是 round-12 构建**（`7c10bbb8…`/118664 B）——经 Decky UI 重装新
ZIP 是用户动作，在那之前面板里什么都看不到。**B 的破坏性前提未执行**
（`.mm_deployed` + `Mods_Core` 仍在、27 个真 MOD 仍是 Amethyst 符号链接部署），
故 phase 3 在真机上**必然**返回 `E_EXTERNAL_MANAGER`；未见任何真实 mod 成功装入
`Mods/`。V1 仍唯一 CLOSED、V2–V20/F1–F3 全 OPEN、原 G3 OPEN/NOT SHIPPABLE；
Step 5 写回 OOS；Track C 独立门控。**goal 保持 active，不调用
`update_goal(complete)`。**
详见 `docs/DOWNLOAD_SOURCES.md`。

## §6.6 Round 29 附加段：Nexus 表面已彻底清除（记录变更说明）

**变更声明（goal 记录要求）**：下载源由 **Nexus 改为 GitHub Releases + 直连 URL**，依据用户 m10068
指令（「不走Nexus，走其他地方实现下载MOD」）。**Nexus 403 是免费账户的硬限制，不是限流**：
免费账户无直连下载权，必须经网站授权签发 **nxm:// 短时效链接**才能下载，而链接签发需要
浏览器会话。除非换 Premium 账户，否则不可修复——这就是不重新引入 Nexus 下载路线的理由。

本轮（round 29）把 Nexus 的**所有代码面**也清掉了，不只是不调用：

| 项 | 之前 | 现在 |
| --- | --- | --- |
| 共享网络层 | `deckymod/nexus.py`（665 行） | `deckymod/download.py`（无 Nexus 字样） |
| 凭据模块 | `deckymod/credentials.py` | **已删除**（不存储、不读取、不发送任何凭据） |
| 未接线函数 | `users_validate` / `list_mod_files` / `get_download_link` / `_safe_domain` / `_http_json` | **已删除** |
| 错误码前缀 | `NX_*（20 个）` | `DL_*（20 个，一一对应）` |
| 异常类 | `NexusError` | `DownloadError` |
| 语义精简 | `_check_url` 带 `require_api_host`、`_headers(api_key, is_api)` 会发 `apikey` | 两者都去掉，只按 hostname 白名单校验 |
| 设备残留 | `/home/deck/homebrew/data/decky-mod-manager/data/nexus_api_key`（96 B, `-rw-------`） | **已删除**（`DELETE_OK`） |
| 部署树 | `py_modules/deckymod/nexus.py` + `credentials.py` + `__pycache__/nexus*.pyc` | **全部清掉**（`DEPLOY_NEXUS_FILES=0`） |
| 校验器 | `validate_nexus_unwired.py`（旧口径已过时、rc=1） | `validate_download_wiring.py`（**73 项全 PASS**） |

**为何保留 `DL_*` 码而不并入 `errors.py`**：`errors.py` 仍然是 50 个 `E_*` 码（未变），
`auto_import.DL_TO_E` 把 20 个 `DL_*` 双射到已存在的 `E_*`（新校验器用 AST 断言这个双射）。
这样前端 i18n、`error_codes()` 直接展示的码表、以及所有历史文档引用都不变。

**真机证据（round 29，运行中的插件进程，非 SSH 旁路）**：`TSC_EXIT=0` / `ROLLUP_EXIT=0` /
`DIST_SHA=a0fbaa13efa09597d2c865a739ede48f42a807b60c41210076165e219429b2b0` / `Ran 301 tests OK` /
`DEPLOY_NEXUS_FILES=0` / `DATA_KEY_GONE` / `VERIFY_FAIL=0`；重载后运行进程：
`status()` → `ok=True appid=413150 MODS=29 READ_ONLY=False`、`error_codes.count=50`、
`gh_search("stardew mod",1)` → `ok=True TOTAL=2553 N=10`、
`gh_download(…, allow_install=False)` → `phase=inspect size=44252 verified=size`
（即 `DL_SIZE_MISMATCH` 与校验链路在真机生效）、直连护栏
`http://` → `E_PATH_INVALID`、`userinfo` → `E_PATH_INVALID`、`127.0.0.1` → `E_PATH_ESCAPE`。

**仍未证明**：本轮没有重建并重新安装 ZIP 包（只将构建树的文件同步到部署目录并重载）；
QAM 面板本轮未目视（面板当时未打开）。状态纪律不变：V1 唯一 CLOSED、
V2–V20/F1–F3 全 OPEN、原 G3(RimWorld 294100) OPEN / NOT SHIPPABLE，不写 CLOSED、不勾 §B.4。

## §6.7 Round 39 添加段：Nexus 凭据面重建（仅元数据），下载仍不经 Nexus

写于 2026-11-17。**只追加**，不回填 §6.5/§6.6 的历史快照。

**为何在§6.6「彻底清除」之后又加回一个 Nexus 面**：因为本轮目标的第二条要求「通过 Nexus
免费账户下载 MOD，网页或其他下载方式」，而本轮在真机上实测出一个事实：**免费账户
可以读元数据，但永远拿不到下载直链**。于是重建的 Nexus 面严格限定为「**浏览 + 给出模组页面 URL**」，
不声称、也不尝试代下载。下载链路仍然只有 GitHub Releases + 直连 URL（见 §6.5）。

### 真机实测决定事实（逐字，来自只读探针，未修改任何已部署文件）

| 事实 | 证据 |
| --- | --- |
| 带 key 调 `download_link.json` 恒为 **403** | `{"code":403,"message":"You don't have permission to get download links from the API without visting nexusmods.com -\n this is for premium users only."}`（`visting` 是 Nexus 自己的拼写错）。跨 mod 2400/1915、重复两次、加 Referer、换 UA 全 403 → **账号等级闸门**，不是限流 |
| 匿名调任何端点 → **401** | `{"message":"Please provide an authentication method"}` → 「不填 key 也能用」不成立 |
| **关键词搜索端点不存在** | `/v1/games/{d}/mods/search.json?search=SMAPI` → **422** `{"message":"Invalid parameter 'id' value \"search\": Must be a number."}`（路由把 `search` 当 mod_id）；`q=` / `game_id=` / `/v2/search.json` / `categories.json` 全 404 |
| 匿名抓网页不可行 | 模组页/搜索页/首页/文件页全 **403** Cloudflare `Just a moment...`，0 个 mod 名元素（搜索页 3 次 "SMAPI" 全在 CF 挑战脚本回显查询串里）→ **不写 HTML 爬虫** |
| 免费 key 元数据库存充足（均 200） | `latest_added` / `latest_updated` / `trending` / `updated?period=1m` / `md5_search` / `mods/{id}.json` / `mods/{id}/files.json`（343 文件）；限流 `x-rl-daily-limit: 20000`、`hourly-limit: 2000` |
| **`validate.json` 响应体原样回显 key** | 字段 `key`，sha256 前 8 位与提交值一致 → **绝不可透传原 body** |
| 403 不等于「要会员」 | `mods/4729/files.json` 也是 403，但文案是 `{"code":403,"message":"Mod not available: 4729"}`（同 mod 的 `.json` 是 200）→ **必须读 message，且不自动重试 403**（白烧 2000/h） |
| `nxm://` 有 handler 但不依赖 | `xdg-mime query default x-scheme-handler/nxm` → `amethystmodmanager-nxm.desktop` → `flatpak run io.github.Amethyst.ModManager --nxm %u`；用它就是把用户丢进第三方程序，所以不用 |

### 一条比 Nexus 更重要的发现：本机 TLS 通过不能证明来源

Deck 的 `/etc/hosts` 有 **574 条** `127.0.0.1` 覆盖，其中 **43 条是 GitHub 域名**
（`github.com` / `api.github.com` / `objects.githubusercontent.com` 等，注释 `#S302`）。
`getent hosts github.com` → `127.0.0.1`；它返回的证书是
`C=CN, O=Steamcommunity302, OU=XX, CN=steamcommunity.com` 自签，而该 CA **已装进系统信任仓库**
→ `Verify return code: 0 (ok)`。拦截进程：`steamcommunity_302.cli` + `caddy`(root) + Decky Clash。

Nexus **不在**覆盖列表（条目 0），且其链验到真实公开根（ISRG Root X1
指纹 `96:BC:EC:…:DF:08:C6`、X2 `69:72:9B:…:CB:14:70`，有效期 2015-2035 / 2020-2040）——
伪造需 ISRG Root X2 私钥，不可能。**所以把 key 发给 Nexus 是安全的。**

含义：**GitHub 下载的 TLS 校验会通过但证明不了来源**。`deckymod/download.py` 的
`_ssl_context()` 不该改、更不该关；真正的内容完整性防线是 **sha256 校验，不可降级**。
同样地，「解析域名到私网 IP 就拒」不能加——会把唯一可用的本地代理判死。只用 **hostname 白名单**。

### 产品形态（已实现）

- **凭据**：`${DECKY_PLUGIN_RUNTIME_DIR}/data/nexus_api_key`，`0o600`（`O_EXCL|O_CREAT` 出生即私有 → 显式 `chmod`
  抗 umask 0022 → `os.replace` 原子更新 → `unlink` 前复验）。不用 keyring（`gnome-keyring-daemon` 不存在）。
  对象是**服务签发的长期 token**，不是密码库；不存密码、不存会话。
- **零回显**：任何 RPC 不返回 key（连掩码前后 4 位都不行）；`nexus_validate` **不收参数**，
  后端自己重读磁盘 key，明文不过桥两次；`validate` 响应只白名单拷 5 字段。
- **浏览**：`latest_added` / `latest_updated` / `trending` 三个列表 + `mods/{id}` 详情（只保留 8 个
  文件字段，原响应 383 KB）+ **模组页面 URL**。**故意没有 `nexus_search`**，因为端点不存在。
- **下载**：用户点「取下载链接」会得到拒绝，并被翻译成一句诚实的话：
  Nexus 只给高级账户直链，请用浏览器页面下载后回到本页导入 ZIP。**不偷偷绕过、不假装成功**。
- **硬约束未放松**：`errors.py` 仍 **50** 码（Nexus 错误走 `DL_TO_E` 映射）；不开只读、
  不要 root、不改启动选项、不安装 loader、不写 Proton 前缀、不声称全游戏一键装。

### 真机证据（本轮）

- 构建：`TSC_EXIT=0` / `ROLLUP_EXIT=0` / `DIST_SIZE=195114` /
  `DIST_SHA=09fe8794526c03e40f67d42e53b30e28560d8a1e73d86995a6caebc104b5b5ed` /
  `Ran 388 tests OK (skipped=1)` / ZIP 236042 B / 40 entries / `r39_deploy.sh` `CHECKED=32 VERIFY_FAIL=0`。
- 凭据探针（从部署树导入）：`S2_SAVE` → `mode_actual="0o600"` 且 `KEY_IN_RESULT=false`；
  `S4_STATUS_AFTER_SAVE` → `configured=true state=present size=33` 且 `KEY_IN_STATUS=false`；
  `S5` 垃圾 key → `E_CAPABILITY_DISABLED` + `the server rejected this string as an API key`；
  `S7B` 重复删除 → `deleted=false reason="no key was stored"`；`S9` 插件树零残留。
- 活进程（重载后通过 `utilities/disable_plugin` + `enable_plugin`）：`api_key_status` → `configured=false
  state=missing mode_requested="0o600" posix=true`；`set_api_key("<24 chars>")` → `stored=true mode_actual="0o600"`；
  `nexus_validate()` → `401` + `Please provide a valid API Key`，**该 key 字符串未出现在任何返回中**；
  `delete_api_key()` → `deleted=true`，再查 → `state=missing`。

**仍 OPEN / 未证明**：真实 Nexus 个人 key 的 200（本轮只用垃圾 key 验证 401 路径，真 key 需用户在
QAM 里自己填或提供）；QAM 面板形态与中文渲染未目视；`nxm://` 与第三方 mod manager
共存未做交互测试；「按游戏分类浏览 Nexus」只能剥离手写的 `game_domain`（见
`registry/games/stardew.json` 的 `download_sources.nexus_metadata`）。状态纪律不变。

## §6.8 Round 41 添加段：把「进入相关网页」从一句文案变成一次真实跳转

§6.7 里这一条还写着「仍 OPEN：QAM 面板形态与中文渲染未目视」。真正没做的是另一半 ——
goal 第二条要求「可以通过已安装游戏进入相关网页下载」，而此前面板只把 URL 渲染成**文本**，
用户得自己抄到浏览器里。本轮先量出这件事在 Game Mode 到底能不能做，再决定做不做。

### 真机实测：三条路，只有一条通

插件进程的环境与 Steam 客户端不同，这一点决定了全部结论：

| 事实 | 值 |
|---|---|
| 插件进程 | `uid=1000 (deck)`；`DISPLAY` **未设置**；`WAYLAND_DISPLAY` **未设置**；有 `XDG_RUNTIME_DIR=/run/user/1000` 与 `DBUS_SESSION_BUS_ADDRESS` |
| `steamwebhelper` | 每个进程都是 `XDG_SESSION_TYPE=x11 DISPLAY=:0` |
| gamescope | `--generate-drm-mode fixed --xwayland-count 2 -w 1280 -h 800 ... -O *,eDP-1` |
| scheme handler | `https → org.mozilla.firefox.desktop`、`steam → steam.desktop` |

三条机制逐一试，每步后读一次 CEF tab 列表判定「是否真的出现」：

| # | 命令 | 结果 |
|---|---|---|
| A | `env -u DISPLAY -u WAYLAND_DISPLAY xdg-open <url>`（插件的真实状态） | `www-browser / links2 / elinks / links / lynx` 全部 command not found，**退出码 0，零 tab 变化** |
| B | `env DISPLAY=:0 xdg-open <url>` | `appstream://org.mozilla.firefox': -c: line 1: unexpected EOF while looking for matching \``（desktop 文件命令被畸形拼接），**零 tab 变化** |
| C | `env DISPLAY=:0 /usr/bin/steam "steam://openurl/<url>"` | **成功**：tab 列表出现该 URL，主窗口落到 `https://steamloopback.host/routes/externalweb` |

**A 是最坏的失败模式：退出码 0 却什么都没发生。** 这一条直接决定了实现里不能用退出码判断成功。

### 实现

- `C:\ai\SD\deckymod\openurl.py`：`ALLOWED_HOSTS = {"www.nexusmods.com", "nexusmods.com"}`、
  `STEAM_BIN = "/usr/bin/steam"`、`MAX_URL_LEN = 512`；只接受 https、拒 userinfo、拒空白/控制字符；
  `subprocess.run(argv, shell=False)`（argv 列表，永不拼字符串）；runner 可注入（同 `sevenzip.py` 模式）。
- `main.py::open_mod_page(mod_id)`（第 25 个公开 RPC）：**只收整数，不收 URL** —— 地址由描述符的
  `game_domain` 在本地拼出，所以这个调用不可能被用来显示任意页面。**刻意不走
  `_network_download_gate()`**：什么都没下载，只是把一个 URI 交给一个已在运行、自有网络的进程；
  门控它等于宣称「看页面就是下载」。
- 前端 `src/index.tsx`：mod 详情与 recent 行各加一个「在浏览器中打开」按钮；失败分支**不用通用错误弹窗**，
  而是明说「页面没有出现」并给出可复制的 URL（5 个 i18n 键：`OPEN_PAGE_BTN/OK/FAIL/WHY/FREE`）。

### 真机证据（本轮，活进程）

- 重载用 Decky 自己的 `utilities/disable_plugin` + `utilities/enable_plugin`（传 plugin.json 的**显示名**
  `"Decky MOD Manager"`；传目录名报 `Python KeyError`），**未 pkill、未热替换**。
- `open_mod_page(1915)` → `{"url":"https://www.nexusmods.com/stardewvalley/mods/1915","opened":true}`；
  tab 列表从 `.../mods/2400` **变成** `.../mods/1915` —— 同一个 tab 真的导航了，不只是返回 ok。
- 失败路径：`open_mod_page(0)` 与 `open_mod_page(-5)` → `E_PATH_INVALID`，
  `detail="[open_mod_page] mod_id must be positive"`，**没有启动任何进程**。
- 构建：`TSC_EXIT=0` / `ROLLUP_EXIT=0` / `DIST_SIZE=204742` /
  `DIST_SHA=2df9656f7da35eb6a8c98ed3103184826f8c6d7cb375263b52a3f38c78633cba`；
  `Ran 440 tests OK`；部署 `CHECKED=34 VERIFY_FAIL=0`；ZIP `250361` B / 42 entries。

**仍 OPEN**：面板上这个按钮本身还没有人用手柄按过（本轮证明的是 RPC 与真实跳转，不是焦点可达性）；
`nxm://` 与 Amethyst 共存仍未做交互测试。

## §7 仍 OPEN / 不予翻动

- V1 唯一 CLOSED；V2–V20 / F1–F3 全 OPEN；原 G3(RimWorld 294100) OPEN / NOT SHIPPABLE。
- Step 5 写回 OUT OF SCOPE；Track C 独立门控须单独批准。
- `docs/ACCEPTANCE.md:211-213,226-228` / `docs/VERIFICATION.md` §J.10 的「不宣称完成 / 不写 CLOSED / 不勾 §B.4」纪律不变。
- hash↔已加载 bundle 仍是 MEDIUM 推断（「byte-exact 必要非充分」），不得写「已证明加载包=ee218850」。

## §8 仍须真机验证

冻结进程内字面 `import ssl` + `urlopen`（§1 第 4 点）；`DECKY_PLUGIN_RUNTIME_DIR`/inbox 位置与属主（V2/V3，`main.py:105-107`）；~~Nexus apikey/限流/download_link/CDN~~（round 19 起 Nexus 链路已 RETIRED，见 §6.5，改为 GitHub 60 次/小时无认证配额与 `browser_download_url` 502 已实测）；Amethyst 版本 + VFS 布局 + 第二写者容忍度；Flatpak 可见性（F3）；多库 `libraryfolders.vdf`/ installdir 大小写（V9/V10/V18）；microSD/exFAT + EXDEV（F1/F2）；真实「游戏运行中」检测（V20 env-only）；CEF frame 的 CORS/CSP 与下载时离线态。
