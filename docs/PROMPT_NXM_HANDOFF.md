# 提示词模板：给 Decky MOD Manager 加「免费账户 MOD 浏览器 + nxm 交接器」

> 用法：把下面 **「=== 提示词开始 ===」到「=== 提示词结束 ===」** 之间整段复制，投喂给要干活的 agent。
> 方括号 `[…]` 里是需要你按实际情况填的地方（主要是数值和是否授权）。
> 本文件本身也是给 agent 读的上下文，它出现在 `docs/` 里不构成状态变更。

---

## 为什么提示词要写成这样（给你看的，不要复制）

三件事决定了这段提示词必须长这个样子：

1. **旧约束和新方向直接冲突，必须写明谁作废谁。** `docs/GOAL_RECORD_DOWNLOAD_SOURCE.md:53-54`
   逐字写着 *"the Nexus download route is **not to be reintroduced**"*，
   `docs/NEXUS_ROADMAP.md` §6.6 同调。如果提示词不说清楚「作废的是哪一条、保留的是哪一条」，
   agent 要么不敢做，要么把整条 Nexus 直连 API 重新引进来（那才是被 403 打死的那条路）。
   正确的切分是：**API-key 直连下载继续禁止**（它对免费账户恒 403，是账号策略不是限流）；
   **浏览器授权后的 nxm 交接是另一条路**，正是 MO2 / Vortex 免费账户走的同一条路，
   它不在旧禁令的字面范围内。提示词里必须把这条区分写死。

2. **这个仓库有三道机械护栏会挡住"顺手加个 RPC"。**
   - `tests/test_wired_contract.py:29-33`、`tests/test_catalog.py:143-154`、
     `.decky-probe/validate_p0.py:67`、`.decky-probe/validate_download_wiring.py:80`
     四处**硬钉 public async RPC == 16**；
   - `deckymod/errors.py` 的 `ERRORS` **硬钉 50 个 E_\* 码**（`auto_import.DL_TO_E`
     就是为了不破这个数）；
   - `src/i18n/en.json` / `zh-CN.json` **各 320 键 parity**，由 `validate_i18n.py` 强制。

   所以提示词必须把「加一个 RPC 要同步改哪四处、为什么这不算放宽」写清楚，
   否则 agent 会去改测试断言把它改绿，或者偷偷加 `E_NXM_*` 错误码。

3. **这个项目只认真机证据。** `docs/ROUND30_FIVE_CRITERIA.md` 通篇在区分
   PROVEN（真机跑出来的输出）和 BLOCKED / 未证。nxm 这条路的**关键未知**
   （网站签发的 key 能不能在 `download_link.json` 换到 CDN 直链）只能在 Deck 上验，
   不在提示词里写明「标 UNVERIFIED 也算交付」，agent 就会拿记忆当证据。

---

=== 提示词开始 ===

## 角色

你是 `C:\ai\SD`（Decky MOD Manager，Steam Deck Game Mode 的 Decky Loader 插件）的实现 agent。
后端 Python 3 stdlib-only（`main.py` + `deckymod/`），前端 React/TS（`src/`），
游戏能力全部由 `registry/` 下的 **descriptor JSON 数据**驱动，游戏名**不许**出现在 Python 的
`if game == "..."` 分支里（`main.py:50-74` 的 `ENGINE_FACTORY` / `_make_engine()` 就是这个规矩）。

## 目标（用户原话，逐字）

> 做一个优雅的免费账户 MOD 浏览器 + nxm 交接器。核心逻辑是：插件负责发现、选择和后续处理，
> 而"获取下载权限"这一步，合法且唯一地交由用户在 Nexus 网页上完成一次点击。

拆成三条可验收的行为：

- **A. 发现**：在 QAM 面板里浏览、检索 Nexus 上的 MOD（只读，不需要插件持有任何凭据）。
- **B. 交接**：用户在 Nexus 网页（自己的浏览器、自己的登录态）点一次「Mod manager download」，
  网站签发一条短时效 `nxm://…?key=…&expires=…&user_id=…` 授权链接；这条链接被交到插件手里。
- **C. 后续处理**：插件用这条链接换到真实文件 → 落到 inbox → **只读 inspect** →
  用户确认 → 走引擎的 `install()`（引擎门禁原样透传）→ 进「我的 MOD」可管可卸。

## 这条路的边界（先说清楚，避免你把我下面的话当耳旁风）

**作废的约束**：`docs/GOAL_RECORD_DOWNLOAD_SOURCE.md:20-54` 里「Nexus 下载路线不得重新引入」
这一条，**仅就"由插件自己持 API key 直连下载"而言继续有效**——那条路对免费账户
`download_link.json` 恒返回 **403**，是**账号策略不是限流**，重试、退避、加 token 都不可能成功
（那台 Deck 上 `RAW_STATUS 200` 证明 key 本身被接受，是下载端点拒绝）。

**本次新增的、不受该禁令约束的路线**：把用户浏览器里**已经获得网站授权**的 `nxm://` 链接
当作输入。插件不登录、不存 cookie、不存 API key、不碰用户会话；它只是接收并消费一条
用户已经付过「一次点击」代价的授权凭证。MO2 / Vortex 免费账户走的正是这条路。

**你必须做的第一件事不是写代码，是验证这条路的最后一步真能成立**（见 P0）。
如果 P0 证伪，就停在那里如实报告，不许编造"等价实现"。

## 不可放宽的硬约束（违反任何一条，整轮作废）

1. SteamOS 只读根**永不**关闭；不假设 root；不 `sudo`；不写 `/usr`、`/usr/share`、`/etc`。
2. 插件**不持有、不读取、不写入、不发送任何长期凭据**：不存 API key、不存 cookie、
   不存 OAuth token。`nxm` 链接里的 `key` 是**一次性的短时效凭证**：
   只允许存在于内存和 RPC 参数里，**绝不**进 journal、日志、`detail`、`data`、
   `dist/`、`registry/`、任何落盘文件；日志里出现必须打码成 `key=***`。
3. 不实现"插件内浏览器登录 / 抓 cookie / 模拟点击"——那是绕过用户授权，不做。
4. 不新增 `E_*` 错误码（`errors.py` 保持 **50** 个）。所有新失败路径复用
   `deckymod/auto_import.py:32-55` 的 `DL_* → E_*` 映射表，把真实原因留在 `detail` 里。
5. 不加新 Python 依赖、不加新 npm 依赖；`rollup.config.js` 与 `strict: true` 不得放宽，
   不新增 `as any` / `@ts-ignore` / `: any`。
6. **绝不**自己写 `Mods/`：唯一写入口是引擎的 `install()`。它返回
   `E_EXTERNAL_MANAGER` / `E_LOADER_MISSING` / `E_LAUNCH_OPTIONS_MISSING` 时**原样透传**，
   不许 catch-and-soften，不许为了"跑通"去删 `.mm_deployed` 或 `Mods_Core`。
7. 不回归到旧的 `E_*`/`CAT_*`/`ERR_E_*` i18n 之外新增键而不补 parity：
   `en.json` / `zh-CN.json` 必须同步，`validate_i18n.py` 要保持 EXIT 0。
8. 游戏差异只准写进 descriptor；`stardew` 的 domain、hosts、开关都进 JSON。
9. 不许为了让测试变绿而改断言、删测试、放宽 `== 16` 之外的任何守卫。
   如果确实要改 RPC 计数，见 P1 的"合同变更三步"。
10. 报告里必须区分 **PROVEN**（真机逐字输出）/ **UNVERIFIED**（推测）/ **BLOCKED**（缺硬件）。
    把没跑过的东西写成跑过，是本项目唯一的不可接受错误。

## 现在的事实基线（自己核对，不要照抄我的说法）

- 16 个 public async RPC，`main.py:303-518`；下载相关的 4 个在 `main.py:411-518`，
  每个都先过 `_network_download_gate()`（`main.py:202-222`，读 descriptor 的
  `capabilities.network_download`，非抛出）。
- `download_url`（`main.py:488`）是**URL 已到手**之后的所有处理，你的 nxm 流程
  90% 应该复用它后面的东西：`auto_import.download_and_import(...)`
  （`deckymod/auto_import.py:113`）三态 gate：inspect / confirm / install。
- 共享下载核 `deckymod/download.py`：只接受 https、无 userinfo、只走 443、
  拒私网/loopback **字面量**、按 hostname 而非解析 IP 匹配、
  `allowed_hosts` 可钉死重定向、256 MiB 上限、
  `expected_size` / `expected_sha256` **写盘前**校验并如实回报 `verified` 列表。
- descriptor 里已有 `download_sources.github` / `download_sources.direct` 两块
  （`registry/games/stardew.json`），`_source_cfg(name)`（`main.py:225-238`）负责读。
- 三道机械护栏：RPC == 16（4 处）、`E_*` == 50、i18n 320/320 parity。
- 前端：`src/index.tsx:142` 的 `openSection` 四路切换器，下载区在 `:1338`，
  已有 `TextField` + 直连 URL 两段流程可以照抄；`src/api.ts:57` 的 `invoke()` 是唯一调用路径。
- 仓库里 **`nxm` 零命中**（`grep -ri nxm *.py deckymod src` 无结果），这是全新功能。

## 分阶段任务

### P0 — 取证（只读，不改代码；**做完必须停下来等我确认**）

在 Steam Deck 真机上，用**免费 Nexus 账户**、在**桌面模式的 Firefox**里：

1. 打开一个 MOD 的文件页，点「Mod manager download」，把弹出的 `nxm://` 链接抓下来
   （Firefox 会提示"选择应用打开"，先复制链接即可）。**逐字记录完整 URL**（key 打码，但要记长度）。
2. 记下 URL 结构：`nxm://<domain>/mods/<mod_id>/files/<file_id>?key=…&expires=…&user_id=…`。
   `domain` 是否就是 descriptor 里的游戏 domain？`expires` 是什么 epoch 单位？
3. **关键未知**：用这条链接在 `https://api.nexusmods.com/v1/games/<domain>/mods/<id>/files/<fid>/download_link.json`
   上换直链，免费账户是否返回 **200 + 一个 CDN URL**？
   - 请求方式：`GET`，**不带** `apikey` 头，查询串附加 `?key=…&expires=…&user_id=…`。
   - 若 200：记下返回 JSON 的字段（`name` / `category_id` / `size` / `md5` / `mod_file` 等），
     以及 CDN 直链的 **host**（通常是 `files.nexus-cdn.com` 或 `supporter-files.nexus-cdn.com`）。
   - 若 403：**立即停止**，把逐字响应体贴给我。不要换别的方式硬凑。
4. 顺手记：链接的 `expires` 距离签发时刻大约多久（单次下载用多久会过期）。
5. 顺带确认 `md5` 字段是否存在——本项目核验的是 sha256（`download.py` 的 `expected_sha256`），
   只有 md5 就**只能**做 size 校验，并在 UI 上如实显示 `verified=["size"]`，不许假装校验过哈希。

**P0 交付**：一份 `docs/NXM_HANDOFF_EVIDENCE.md`，每条一个 `PROVEN`/`UNVERIFIED` 标注 + 逐字输出。
**P0 之后等我一句「继续」再进 P1。** 如果 P0 证伪，把「为什么这条路在免费账户上不成立」
写成同等级的证据，然后停。

### P1 — 最小可用交接器（一个新 RPC）

新增 `download_sources.nxm` 到 `registry/games/stardew.json`（字段建议，按 P0 实测调整）：

```json
"nxm": {
  "enabled": true,
  "scheme": "nxm",
  "game_domain": "stardewvalley",
  "exchange_host": "api.nexusmods.com",
  "file_hosts": ["files.nexus-cdn.com", "supporter-files.nexus-cdn.com"],
  "max_link_age_seconds": 3600
}
```

**新模块 `deckymod/nxm.py`**（stdlib-only，可离线单测，注入 opener）：

- `parse_nxm(url: str) -> dict`：严格正则
  `^nxm://([a-z0-9]+)/mods/(\d+)/files/(\d+)(\?(.*))?$`；
  `urllib.parse.parse_qs` 解 `key` / `expires` / `user_id`，三者缺一 → `DL_BAD_URL`；
  `expires` 解析失败或已过期 → `DL_AUTH_REQUIRED`（detail 写 `nxm link expired`）；
  domain 不在 descriptor 白名单 → `DL_BAD_URL`。
- `exchange(nxm: dict, opener, timeout) -> dict`：`GET https://{exchange_host}/v1/games/{domain}/mods/{mod_id}/files/{file_id}/download_link.json`
  **不带任何 header 凭据**，查询串只带 `key`/`expires`/`user_id`；
  返回 `{"ok": True, "url": <首个数组元素的 URI>, "size": …, "md5": …, "filename": …}` 或
  `{"ok": False, "code": "DL_*", "detail": …}`。**任何情况下不得把 key 放进返回值。**
- `handoff(nxm_url, engine, opener, *, filename, allow_install, after_confirm)`：
  `parse_nxm` → `exchange` → `auto_import.download_and_import(opener, engine, url=…,
  filename=…, allow_install=…, after_confirm=…, allowed_hosts=cfg["file_hosts"],
  expected_size=<size>)`。size 有就传；只有 md5 时**不要**传 `expected_sha256`。

**新 RPC（1 个）**，签名与 `download_url` 对齐：

```python
async def nxm_download(self, nxm_url: str, filename: str,
                       allow_install: bool, after_confirm: bool):
```

流程：`_network_download_gate()` → `_source_cfg("nxm")` 且 `enabled` 为真，否则
`err("E_CAPABILITY_DISABLED", detail="[nxm] source disabled for <gid>")` →
`nxm.handoff(...)` → `_core_to_envelope(res, auto_import.DL_TO_E, "nxm_download")`。
**失败一律走 `_core_to_envelope`**，不要 `raise`（`_guard` 会把它压成 `E_UNKNOWN`，
`main.py:488-518` 的 `download_url` 就是为这个专门做了就地转换）。

**合同变更三步**（RPC 16 → 17，必须同一个提交里全做完，并在提交说明里写清理由）：

1. `tests/test_wired_contract.py:29-33` → 17，并把 `nxm_download` 加进必须存在列表；
2. `tests/test_catalog.py:143-154` → 改名 `test_rpc_count_is_17_after_nxm`，注释写清"16 → 17 是
   nxm 交接引入的，不是放宽守卫"；
3. `.decky-probe/validate_p0.py:67` 与 `.decky-probe/validate_download_wiring.py:80`
   → 17，并在后者里加一条 `nxm_download` 必须过 gate 的检查。

`errors.py` **不动**（仍 50 个码）；i18n 只新增，`en.json` / `zh-CN.json` 同步，保持 parity。

**前端**（`src/index.tsx:1338` 那段之后加，沿用现有 `TextField` + `ButtonItem` + 两段确认模式）：

- 一条 `NXH_TITLE` 说明 + 一个 `TextField`（粘贴 nxm 链接，`autocomplete` 关掉）+ 两个按钮
  （`NXH_FETCH` 只下载不装 / `NXH_IMPORT` 下载后走确认）。
- 客户端**先本地校验** URL 形状与 `expires`，明显不合法就别发 RPC（省得占着 busy 转）。
- 显示状态必须分得清：**「已下载到 inbox（未安装）」** 与 **「已安装」**，
  以及 `verified` 到底是 `size` 还是 `size + sha256`，还是 `no checksum published`。
- 明确写：`E_EXTERNAL_MANAGER` 是**正确结论**，不是 bug（另一个 mod 管理器占着 `Mods/`）。

测试：`tests/test_nxm.py`，用假 opener 覆盖——URL 解析（合法/缺参数/过期/错 domain）、
exchange 200/403/超时/重定向出白名单、下载落 inbox、inspect 三态、key 不出现在任何返回值与日志。

### P2 — 系统级协议注册（**需要我明确授权，未授权不要做**）

要能做到"浏览器里点一下就直接进插件"，需要在**用户可写**目录注册协议处理器：

- 写 `~/.local/share/applications/deckymod-nxm.desktop`（`MimeType=x-scheme-handler/nxm;`），
  其 `Exec` 指向插件自带的小入口脚本，脚本只做一件事：把收到的 URL 追加写进
  `${DECKY_DATA}/nxm-handoff/<ts>.url`（权限 0600），**不联网、不解析、不执行任何外来的东西**；
- `xdg-mime default` + `update-desktop-database ~/.local/share/applications`（都是用户级）。

注意：`~/.local/share/applications` **不在** `registry.json` 的 `allowed_write_roots` 里。
动它之前你要先向我报"新增第 6 个写根、只写 `.desktop` 一个文件、内容如下"，得到授权再动，
并把这条写进 `docs/` 与 `registry.json` 的注记。**不许**写 `/usr/share`（只读根）。

同样在 P2，`nxm_download` 之外再加 `nxm_take(self)` 把队列里最早的一条交给前端 ——
如果这样会让 RPC 变成 18，也走同样的"合同变更三步"，别偷偷加。

### P3 — 零风险降级路径（P0 若证伪，或用户不想注册协议时用）

如果 nxm 换直链这条路在免费账户上走不通，**不要硬凑**。改成：
用户在浏览器里点"慢速下载"，文件落到 `~/Downloads`，插件扫描该目录里
最近 N 个 `.zip/.7z`，用**现有的** `inspect` 管线识别 manifest，再走同一套确认/安装。
这条路径插件不联网、不碰任何授权，代价是多一次手动搬运。
在提示词层面它和 P1 共用 `install` 之后的全部代码，所以先把 P1 的 C 段做完不吃亏。

## 每阶段的验收判据（机械可验，逐条给数字）

- `python -m pytest`/`unittest`：**全绿**，且测试数**只增不减**（改动前先记录基线 `Ran N tests`）。
- `tsc --noEmit` **EXIT 0**，`rollup -c` **EXIT 0**，`strict: true` 未改。
- 7 个校验器全 **EXIT 0**：`validate_i18n`（320 + 新增键 parity）、`validate_p0`
  （`PUBLIC_RPC_COUNT 17` + `ALL_STATIC_CHECKS True`）、`validate_download_wiring`、
  `validate_api_arity`（`BAD 0`）、`r19_frontend_preflight`（`BARE_BUTTON_COUNT 0`）、
  `r8_zipload_probe`、`r4_tar_drift`。
- `errors.py` 仍是 **50** 个码；`grep -ric 'apikey\|api_key\|cookie' deckymod/nxm.py` 为 **0**。
- 真机：一次完整的合法 nxm 交接（inspect → 确认 → 已安装 → 列表可见 → 可禁用 → 可卸载），
  和一次过期的 nxm 链接（必须是一条可读错误，不是 traceback，不是 `E_UNKNOWN`）。
- 安全负例：把 `key` 换成垃圾 → 明确失败；把 `domain` 改成别的游戏 → 明确失败；
  把返回的 CDN 直链改成白名单外 host → 明确失败。三条都要有逐字输出。

## 报告格式（我要的就是这个）

```
P0 取证        PROVEN / UNVERIFIED / BLOCKED 逐条标注 + 逐字输出
改了什么       文件:行 → 一句话
合同变更       16 → N 的具体四处，和为什么这不是放宽守卫
安全边界       key 在哪些路径上出现过、如何保证没落盘（给 grep 命令和输出）
验收           7 个校验器 + 测试数 + tsc/rollup 的 EXIT 与关键行
仍 OPEN        哪些没证、为什么没证、下一步需要我做什么
```

## 开始前先回答我三个问题

1. P0 需要我在 Deck 上配合点击浏览器，你准备让我跑哪些命令、看什么输出？
2. 如果 P0 证伪，你打算走 P3 还是先停下来讨论？
3. P2 要写 `~/.local/share/applications/deckymod-nxm.desktop`，你要我授权吗？

=== 提示词结束 ===

---

## 你（用户）还需要补的三件事

1. **P0 那句"停下来等我确认"是真停**。这条路的成败全在「免费账户拿到的 `nxm` key
   能不能在 `download_link.json` 换到 CDN 直链」这一个事实上，
   我在这个环境里查不到（本机 web 检索provider 未注册，无法取外部资料），
   所以它必须是**真机实测**，不能由 agent 凭记忆断言。
2. **P2 的授权要明说**。不改 `allowed_write_roots` 的话协议注册做不了，
   那就老实待在 P1：粘贴框 + 手动把链接贴进来，功能一样能用，只是不优雅。
3. **`docs/GOAL_RECORD_DOWNLOAD_SOURCE.md` 要补一条 supersede 注记**，
   否则下一轮 agent 读到 `:53-54` 又会把这件事当成禁区。建议加在文件末尾：

   > **2026-XX-XX 增补**：`Nexus download route is not to be reintroduced` 的含义
   > 收窄为「插件不得自持 API key 直连下载」。用户浏览器授权后的 `nxm://` 交接
   > 是另一条路线（MO2 / Vortex 免费账户同款），由 `docs/PROMPT_NXM_HANDOFF.md` 与
   > `docs/NXM_HANDOFF_EVIDENCE.md` 记录，不受本条约束。
