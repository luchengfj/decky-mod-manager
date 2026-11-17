# RUNBOOK — 换机执行清单（V1 版本锁定 + V8 前端构建）

> ## 状态：**全清单「待执行」，无一项「已通过」**
>
> 本文件由**无网环境离线编写**，只记录命令、判据与回写方式。
> - 本会话**未执行任何命令、未运行任何脚本**：下列命令均为「换机后待执行」，不是已运行结果。
> - **未修改任何 V# 状态**，`docs/VERIFICATION.md` 的 V1 / V3 / V8 仍为 `OPEN`。
> - **未产生任何 `CLOSED` 状态**；本文件不预置、不预填、不代判任何状态变更。
> - 文中所有 `<...>` 均为**输出形态占位符**，不是实测值；**没有编造任何输出示例冒充真实结果**。
> - **不为通过构建放宽类型**：不关 `strict`、不加 `@ts-ignore`/`as any`、不删 `typecheck`、不降级到伪版本。
>
> 关联：[VERIFICATION.md](VERIFICATION.md)（V1 在 §A、V3 在 §A、V8 在 §A）、[ACCEPTANCE.md](ACCEPTANCE.md)（G3 门）。
> 本轮**不编辑** `VERIFICATION.md`；§5 只是回写模板，供后续轮次拿到真实证据后使用。
>
> **状态更正（2026-11-12 后续轮次补记，非本 RUNBOOK 的状态变更）**：本文件开头的
> 「V1 / V3 / V8 仍为 `OPEN`」与 §8 表格是**本文撰写那一轮的历史快照**，不是实时状态。
> C1–C3 真实证据已由用户在联网侧补齐，并据其回写块把 **V1 置为 `CLOSED`** —— 权威记录见
> [VERIFICATION.md](VERIFICATION.md) §A（template commit `90d0780…`、Decky Loader `v3.3.1`、
> `@decky/api 1.1.3`、`@decky/ui 4.16.5`）；V3 / V8 仍 `OPEN`。§8 的「本轮之前 / 本轮之后」
> 列**保留原样**（当时真实记录，不回填改写）。本补记未执行任何 C1–C4 命令、未放宽类型、
> 未在本文件内新增任何 V#/F# 的 `CLOSED` 判定。
>
> **状态更正（2026-11-13 证据回写补记，非本 RUNBOOK 的状态变更）**：C4（精确版本写入
> → `pnpm install` → `tsc --noEmit` → `rollup -c` → 产出 `pnpm-lock.yaml` +
> 可加载 ESM `dist/index.js`）已于 2026-11-13 在**一台联网 Steam Deck** 上实跑全绿，
> 逐字 stdout 与产物已回写至 [VERIFICATION.md](VERIFICATION.md) §H（§H.2/H.5）。本文件
> §1–§8 的命令/判据/「待执行」状态字是**本文撰写那一轮的历史快照**，保留原样不回填
> （本 RUNBOOK 只是执行清单与模板，不是证据汇总处）。按本轮授权「只回写证据、状态
> 一律不动」：**V8 及所有 V#/F# 仍 `OPEN`、未写任何 `CLOSED`**、G3 整体仍 `OPEN`；
> 真实游戏/手柄 DoD 仍无真值。CI 的 `--frozen-lockfile` 前提（§5）现已具备已生成并回传
> 的 `pnpm-lock.yaml`，但仍须按流程在 CI 上复验。
>
> **状态更正（2026-11-13 晚补记，非本 RUNBOOK 的状态变更）**：同日晚用户经 Decky UI
> 手柄「从 ZIP 安装」已把插件装上真机，首启因冻结解释器 PYZ 缺 `xml.etree` 失败，按用户
> 批准加 `deckymod/__init__.py` 的 XML 兼容 shim 后**真机加载成功**（4 个只读 RPC 全链路
> 通过），并重建带 shim 的 ZIP 回传。逐字证据见 [VERIFICATION.md](VERIFICATION.md) §H.7。
> **因此本文 §4/§5 表格里「`dist/index.js` 为 `cjs` 产物 / 不是 `cjs` 即失败」是撰写时的
> 历史快照**：实际已改用官方 `@decky/rollup` 产出**可加载 ESM**（`SP_REACT/SP_JSX/DFL`
> globals，见 §H.2/V6），CJS 包在真机会 `require is not defined`。这些判据列按「历史快照
> 不回填」保留原样，请以 §H 为准。**但**按授权 V8 及所有 V#/F# 仍 `OPEN`、未写任何
> `CLOSED`、G3 整体仍 `OPEN`；RimWorld 294100 未安装、手柄 DoD 与真实写回仍无真值。
>
> **状态更正（2026-11-14 B 方案补记，非本 RUNBOOK 的状态变更）**：同日按用户「B方案」
> 授权，在真机冻结解释器里用合成树跑通 11 个 RPC 全链路 + 7 类故障注入（41 项全绿，
> 测完逐字节还原）；逐字证据见 [VERIFICATION.md](VERIFICATION.md) §H.9。**这不改变
> 本 RUNBOOK 的 C1–C4 / 待执行状态字**：它是后端逻辑回归，不是真游戏 DoD 签核；
> V8 及所有 V#/F# 仍 `OPEN`、未写任何 `CLOSED`、G3 仍 `OPEN`。

---

## 0. 适用范围与前置条件（待执行前先逐项确认）

| # | 前置项 | 期望形态 | 不满足时 |
| --- | --- | --- | --- |
| P1 | 换机具备真实公网与可用 TLS 凭据 | `curl -sS -o decky-preflight.json -w "%{http_code}\n" https://registry.npmjs.org/` 形如 `200`（`-o` 用普通相对文件名，避免 `NUL`/`/dev/null` 的平台差异；本行按 §0 的 bash 兼容 shell 执行） | 出现 `SEC_E_NO_CREDENTIALS` / DNS 落到保留网段（如 `198.18.x`）/ `000` → **立即停止**，本清单不可执行，所有 V# 保留 `OPEN` |
| P2 | 工具链可用 | `git --version`、`curl --version`、`node --version`、`npm --version`、`pnpm --version` 均有输出且退出码 0 | 任一缺失 → 停止；不得用 mock 工具替代 |
| P3 | 真实 registry | `npm config get registry` 与 `pnpm config get registry` 均形如 `https://registry.npmjs.org/` | 指向镜像/占位地址且取不到 `@decky` scope → 记录真实输出并停止，不猜测版本 |
| P4 | 同一份仓库 | 工作目录为本仓库副本（`package.json` / `tsconfig.json` / `rollup.config.js` / `src/` / `docs/` 齐全），且**尚无** `pnpm-lock.yaml` | 已有伪造的 lockfile → 先删除伪造物再开始，不得沿用 |
| P5 | 权限边界 | 仅允许改 `package.json` 的 `devDependencies` 版本号（V1 锁定）与新增 `pnpm-lock.yaml`；**不改** `deckymod/`、`main.py`、`src/`、`tsconfig.json`、`rollup.config.js` 的任何语义 | 越界即违反「不新增功能、不改后端语义」 |

> **调用口径（两条，执行前先确定并全程一致）**：
> 1. `pnpm`：本清单假设换机已全局安装 `pnpm` CLI。若沿用本会话自带的
>    `pnpm.mjs`，须统一写成 `node <abs>/pnpm.mjs <args>` 且**全程只用一种**调用形式，
>    避免版本漂移。二者择一，记录实际使用的那一种。
> 2. **执行 shell**：本文所有 `bash` 代码块须在 **bash 兼容 shell** 中执行
>    （Linux / macOS 原生终端，或 Windows 上的 Git Bash / WSL），
>    这样 `curl` 才是真正的 curl 可执行程序、反斜杠续行也成立。
>    **不要**直接在 Windows PowerShell 里跑这些块：PowerShell 的 `curl` 是
>    `Invoke-WebRequest` 别名、不认 `-w`/`-o`/`-H` 等 flag。P1 与 C2 都受此约束。
>    本文 curl 的 `-o` 一律用普通相对文件名，不依赖 `NUL` / `/dev/null`。

---

## 1. 四条命令总览

| 编号 | 目的 | 命令（组） | 证据回写目标 | 状态 |
| --- | --- | --- | --- | --- |
| **C1** | 取 `decky-plugin-template` 具体 commit | `git ls-remote … HEAD` / `--tags` | V1 | **待执行** |
| **C2** | 取 Decky Loader 目标版本（GitHub releases） | `curl … /releases/latest` | V1 | **待执行** |
| **C3** | 取 `@decky/api` 与 `@decky/ui` 实际版本号 | `npm view … version` | V1（并影响 V3） | **待执行** |
| **C4** | `pnpm install` + `tsc --noEmit` + `rollup build` | 三步组合 + `--frozen-lockfile` 复验 | V8（typecheck 报错另供 V3 核对） | **待执行** |

C1/C2/C3 相互独立、可并行；**C4 依赖 C3**（先把确切版本锁定进 `package.json` 再安装）。
证据回写的分工：**C1–C3 回写 V1**、**C4 回写 V8**（typecheck 证据另附 V3）；§2–§5 每一节末尾都给出对应的 `VERIFICATION.md` 回写步骤，四条命令合起来覆盖 V1 与 V8。

---

## 2. C1 — 取模板 commit

### 命令（待执行）

```bash
git ls-remote https://github.com/SteamDeckHomebrew/decky-plugin-template.git HEAD
git ls-remote --tags https://github.com/SteamDeckHomebrew/decky-plugin-template.git
```

说明：第一条取默认分支 HEAD 的 commit；第二条列出 tag 用于「锁定一个 commit/tag」的取舍（评审 #2 已接受「锁一个、不追新」）。若选 tag，注意 peeled 行 `refs/tags/<tag>^{}` 才是 tag 指向的真实 commit，须记录**完整 40 位十六进制 SHA**，而非短 SHA 或 tag 名。

### 预期输出形态（形态说明，非实测结果）

- 第一条：单行，形如 `<40位小写十六进制 SHA>\tHEAD`。
- 第二条：若干行，形如 `<40位十六进制 SHA>\trefs/tags/<tag>`，可能伴随 `…^{}` peeled 行。
- 退出码 `0`。
- 上面 `<...>` 全是占位符；**真实 SHA / tag 列表以换机实跑为准，本文件不填**。

### 失败判据（命中任一即停止，保留 `OPEN`）

- 退出码非 0；出现 `fatal: unable to access`、`schannel: AcquireCredentialsHandle failed: SEC_E_NO_CREDENTIALS`、`Could not resolve host`、证书校验失败。
- DNS 解析到保留/拦截网段（如 `198.18.0.0/15`）而非真实 GitHub IP。
- 输出为空；`HEAD` 行多于一行；SHA 不是 40 位十六进制。
- 只拿到短 SHA 或只有 tag 名、拿不到 peeled commit → 视为「未锁定」，不得用猜测补齐。

### 回到本机后如何更新 `docs/VERIFICATION.md` 的 V1 条目

1. 在 V1 的「证据」区粘贴 C1 **逐字** stdout + 退出码 + 执行日期 + 机器 OS。
2. 填入 `decky-plugin-template commit = <40-hex>` 与所选 ref（`<HEAD>` 或 `<tag>` + peeled SHA）。
3. 「获取方式」写：命令全文 + 仓库 URL。
4. **状态字不改**：V1 仍写 `OPEN`；是否调整由后续轮次在拿到 C1–C3 全部真实证据后人工判定。本清单不写 `CLOSED`。

---

## 3. C2 — 取 Decky Loader 目标版本（GitHub releases）

### 命令（待执行）

```bash
curl -sS -fL \
  -H "Accept: application/vnd.github+json" \
  -o decky-loader-release.json \
  -w "http_code=%{http_code}\n" \
  https://api.github.com/repos/SteamDeckHomebrew/decky-loader/releases/latest

node -e "const j=JSON.parse(require('fs').readFileSync('decky-loader-release.json','utf8'));console.log(j.tag_name+' | '+j.name+' | '+j.published_at)"
```

说明：`-f` 使 HTTP ≥ 400 直接失败，`-w` 暴露状态码，`-o` 留档供逐字引用。第二条仅从留档 JSON 读出三个字段；本节按 §0 的 bash 兼容 shell 执行（反斜杠续行、`node -e` 的单/双引号在该环境下成立）。若 GitHub API 触发未认证限流，需按真实返回处理（见失败判据），不得改猜一个版本号。

### 预期输出形态（形态说明，非实测结果）

- 第一条 stdout 形如 `http_code=<200>`；`decky-loader-release.json` 为一个 JSON 对象。
- 第二条单行，形如 `<tag_name> | <name> | <ISO-8601 UTC 时间>`。
- `tag_name` 形态通常为 `v<major>.<minor>.<patch>`，也可能是预发布 tag；`published_at` 为 ISO-8601。
- 上面 `<...>` 全是占位符；**真实版本与时间以换机实跑为准，本文件不填**。

### 失败判据（命中任一即停止，保留 `OPEN`）

- `http_code` 非 `200`；curl 退出码非 0；`curl: (35)` / TLS 凭据错误 / `000`。
- 响应不是单个 JSON 对象，或缺 `tag_name` / `published_at`；`/releases/latest` 返回 `404`（无正式 latest release）。
- API 限流（`403` + `rate limit exceeded` 形态）且无法以合法方式取得真实值 → 记录真实响应，不臆造版本。
- `tag_name` 不是可辨识的发布标签形态 → 视为未锁定。

### 回到本机后如何更新 `docs/VERIFICATION.md` 的 V1 条目

1. 在 V1「证据」区粘贴 `-w` 行、第二条命令的逐字输出、退出码与 `decky-loader-release.json` 的来源 URL。
2. 填入 `Decky Loader 目标版本 = <tag_name>`、`published_at = <ISO-8601>`、`name = <name>`。
3. 「获取方式」写：API URL + 两条命令全文。
4. **状态字不改**：V1 仍 `OPEN`；本清单不写 `CLOSED`。

---

## 4. C3 — 取 `@decky/api` 与 `@decky/ui` 实际版本号

### 命令（待执行）

```bash
npm config get registry
npm view @decky/api version
npm view @decky/ui version
npm view @decky/api dist-tags --json
npm view @decky/ui dist-tags --json
```

说明：前两条 `npm view … version` 是取确切版本号的主命令；`dist-tags --json` 用于确认 `latest` 指向、避免把 dist-tag 名当版本号。按 P3 先确认 registry 是真实 npmjs。

### 预期输出形态（形态说明，非实测结果）

- `npm config get registry`：单行，形如 `https://registry.npmjs.org/`。
- 每条 `npm view … version`：单行 semver，形如 `<major>.<minor>.<patch>`（可能带预发布后缀），**不带** `^` / `~` / `latest` 前缀。
- 每条 `dist-tags --json`：合法 JSON 对象，形如 `{ "latest": "<semver>", ... }`。
- 退出码均为 `0`。
- 上面 `<...>` 全是占位符；**真实版本号以换机实跑为准，本文件不填**。

### 失败判据（命中任一即停止，保留 `OPEN`）

- `npm ERR!` 任一：`ENOTFOUND` / `EAI_AGAIN` / `ETIMEDOUT` / `E403` / `E404` / 证书错误。
- `@decky/ui` 返回 `404`（该包可能未以此名发布）：这是**真实证据**，必须逐字记录并保留 V3 `OPEN`；**禁止**用臆测版本、`^0.0.0` 之类的占位范围或改用别包名来「补齐」。
- 输出为空、含 `^`/`~`/`latest`、不是 semver、或 `dist-tags` 不是合法 JSON。
- registry 输出不是真实 npmjs 地址。

### 附：版本锁定写入（待执行，属于 V1，**不属于放宽类型**）

拿到 C3 的确切版本后，把 `package.json` 中 `devDependencies` 里 `@decky/api` / `@decky/ui` 的**范围**改成**精确版本**（无 `^`/`~`/`*`）。这一步是 V1「锁版本」，不是类型放宽；同时不得改动 `typescript` / `rollup` 等其余依赖的语义、不得改 `src/`、不得改后端。若 `@decky/ui` 上一步为 `404`，**跳过该包的写入并把 404 证据留给 V1/V3**，不要伪造一个可安装的版本。

### 回到本机后如何更新 `docs/VERIFICATION.md` 的 V1 条目

1. 在 V1「证据」区粘贴五条命令的逐字输出、退出码、registry 值、执行日期。
2. 填入 `@decky/api = <version>`、`@decky/ui = <version 或「未发布/404，证据见上」>`，以及 `package.json` 实际写入的精确版本串。
3. 「获取方式」写：命令全文 + `npm view` 的 registry。
4. 若 `@decky/ui` 为 `404`，在 V1 与 V3 同时注明「包不可解析、保留 OPEN」。
5. **状态字不改**：V1 仍 `OPEN`；本清单不写 `CLOSED`。

---

## 5. C4 — `pnpm install` + `tsc --noEmit` + `rollup build`

> 前置：C3 已完成版本锁定写入（或已记录 `@decky/ui` 404 的真实处置），P1–P5 全部满足。

### 命令（待执行）

```bash
pnpm install
pnpm run typecheck
pnpm run build
```

其中按当前仓库 `package.json` 的 `scripts` 记载，`typecheck` 对应 `tsc --noEmit`、`build` 对应 `rollup -c`；**以换机处 `package.json` 的实际定义为准**。等价直写形式（二选一，不与上面重复执行）：

```bash
pnpm exec tsc --noEmit
pnpm exec rollup -c
```

生成 lockfile 后，为验证 CI 的 `--frozen-lockfile` 路径，追加（待执行）：

```bash
pnpm install --frozen-lockfile
git status --short
```

### 预期输出形态（形态说明，非实测结果）

| 步骤 | 成功形态 | 关键判据 |
| --- | --- | --- |
| `pnpm install` | 进度行 + `Packages: +<N>` 形态 + `Done in <Xs>`；生成 `node_modules/` 与 `pnpm-lock.yaml` | 退出码 0，无 `ERR_PNPM_*`；`pnpm-lock.yaml` 存在且含 `lockfileVersion: <N>` 形态 |
| `pnpm run typecheck`（`tsc --noEmit`） | **成功时 stdout 通常为空** | 退出码 0 且**无任何** `error TS<编号>:` 行；空输出不等于失败 |
| `pnpm run build`（`rollup -c`） | 形如 `created dist/index.js in <Xs>` | 退出码 0；`dist/index.js` 存在、非空、为 `cjs` 产物 |
| `pnpm install --frozen-lockfile` | 形如「lockfile 已最新、跳过 resolution」 | 退出码 0（证明 `.github/workflows/build.yml` 的 frontend job 前提成立） |
| `git status --short` | 出现 `?? pnpm-lock.yaml`（及 `dist/` 是否被 ignore 以 `.gitignore` 为准） | 确认 lockfile 可提交；不得提交伪造输出 |

> 上表全部为**形态/占位符**，不是实测输出；真实 stdout/stderr、退出码、`+<N>`、`<Xs>`、`lockfileVersion`、`dist/index.js` 字节数以换机实跑为准，**本文件不填具体值**。

### 失败判据（命中任一即停止，保留 `OPEN`，逐字记录真实输出）

- 任一步退出码非 0；出现 `ERR_PNPM_*`、`command not found`（`tsc` / `rollup` 缺失）、`Cannot find module`。
- `pnpm-lock.yaml` 未生成 / 为空；`--frozen-lockfile` 报 lockfile 与 `package.json` 不一致 → 说明锁定没落地，必须回到 C3 重做，不得手工编 lockfile。
- `dist/index.js` 缺失、为空、或不是 `cjs`。
- **typecheck 报 `error TS<编号>:`**：这是 **V3 的真实证据**，必须逐字记录并**保留 V3 `OPEN`**。
  严禁以下「让它变绿」的做法——均违反本轮硬约束：
  - 关闭/削弱 `tsconfig.json` 的 `strict`（或改 `noEmit`、改 `include` 绕过）；
  - 在 `src/` 加 `// @ts-ignore`、`@ts-expect-error`、`as any`；
  - 删掉 `typecheck` 步骤、用 `--noEmitOnError false` 之类绕过、或只跑 build 冒充 typecheck 通过；
  - 把 `@decky/*` 换成伪版本/`file:` 占位包以消除类型错误。
- 构建报错源于 `@decky/api` / `@decky/ui` API 形状不符（V3）时，同样**只记录、不修类型、不标 CLOSED**。
- 任何一步被以 mock、stub、跳过、`echo` 假输出替代 → 视为未执行，全部保留 `OPEN`。

### 回到本机后如何更新 `docs/VERIFICATION.md` 的 V8 条目（及 V3）

1. 在 V8「证据」区按命令顺序粘贴**逐字** stdout/stderr，每条附退出码、执行日期、机器 OS、`pnpm --version` / `node --version`、registry 值、实际使用的调用形式（CLI 或 `pnpm.mjs`）。
2. 记录 `pnpm-lock.yaml` 的 `lockfileVersion`、文件是否存在、是否已纳入 `git status --short`；记录 `dist/index.js` 是否生成及其大小（真实值）。
3. `--frozen-lockfile` 的真实结果单独列出（这是 CI frontend job 能不能过的前提）。
4. 若 `tsc --noEmit` 有 `error TS...` 行：把逐字报错另附到 **V3**，写清「因 API 形状未确认而保留 `OPEN`」，并注明**未放宽类型**；不得据失败输出把 V3 标 `CLOSED`。
5. **状态字不改**：V8 仍 `OPEN`；V3 仍 `OPEN`。是否调整由后续轮次在拿到全部真实输出并人工核对后决定，**本清单不写 `CLOSED`**。

---

## 6. 回写模板（占位符，供后续轮次使用；本轮不写入 `VERIFICATION.md`）

> 以下 `<...>` 全为占位符，**非实测值**。本节只是模板，不是本轮的状态变更。

```
### V1 — Pin decky-plugin-template commit + Decky Loader version
- status: OPEN（本 RUNBOOK 不改状态；是否调整由后续轮次人工判定）
- 获取方式: C1/C2/C3 命令全文 + 仓库 URL + API URL + registry；执行日期 <date>；机器 <os>
- decky-plugin-template commit: <40-hex>  ref: <HEAD|tag>
- Decky Loader 版本: <tag_name>  published_at: <ISO-8601>
- @decky/api: <version>   @decky/ui: <version | 404 未发布>
- package.json 锁定后精确版本串: <exact>
- 证据: <粘贴 C1/C2/C3 逐字输出与退出码>

### V8 — 前端构建
- status: OPEN（本 RUNBOOK 不改状态；是否调整由后续轮次人工判定）
- 证据: <粘贴 pnpm install / pnpm run typecheck / pnpm run build / --frozen-lockfile 逐字输出与退出码>
- pnpm-lock.yaml: <存在/不存在>  lockfileVersion: <N>
- dist/index.js: <存在/不存在>  大小: <bytes>
- 备注: <若为 TS 报错，逐字附于 V3 并保留 V3 OPEN；未放宽类型>
```

---

## 7. 离线复核清单（无网环境可逐项人工核对）

| # | 复核项 | 期望 | 状态 |
| --- | --- | --- | --- |
| R1 | Markdown 结构完整（标题层级、四个命令小节、三要素齐全） | 是 | **待复核** |
| R2 | 恰含四条命令组：C1 `git ls-remote`、C2 releases `curl`、C3 `npm view`、C4 `pnpm install`+`tsc --noEmit`+`build` | 是 | **待复核** |
| R3 | 命令语法正确（无占位符混进可执行行、无未闭合引号、flag 合法） | 是 | **待复核** |
| R4 | 每条都有「预期输出形态」且明确标注为形态/占位符 | 是 | **待复核** |
| R5 | 每条都有「失败判据」且含「停止 + 保留 OPEN」 | 是 | **待复核** |
| R6 | 每条都有「回到本机后如何更新 VERIFICATION.md 的 V1/V8」 | 是 | **待复核** |
| R7 | 所有执行项标注「待执行」/「待复核」，无一处把结果声称为「已完成/已通过」（文中出现的「已通过」字样仅用于否定式说明） | 是 | **待复核** |
| R8 | 全文**不产生任何 `CLOSED` 状态**；未修改任何 V# 状态 | 是 | **待复核** |
| R9 | 无编造输出示例；无具体 commit hash / 版本号 / 退出码被当作实测值 | 是 | **待复核** |
| R10 | 明确禁止放宽类型 / 改后端语义 / mock / 跳过 tsc | 是 | **待复核** |

> R1–R10 全部为「待复核」，**不是「已通过」**。本文件在未联网的本机只做离线结构复核；
> C1–C4 的实际执行与 V1/V8 的证据回填，一律留到能联网的机器与后续轮次。

---

## 8. 每个 V# 在本轮之后的状态（无变化）

| V# | 本轮之前 | 本轮之后 | 原因 |
| --- | --- | --- | --- |
| V1 | `OPEN` | **`OPEN`（未改）** | 需 C1–C3 真实 commit/版本号 + 获取方式；本轮只产出清单 |
| V2 | `OPEN` | `OPEN`（未改） | 需锁定版本后比对 `decky` 属性名 |
| V3 | `OPEN` | **`OPEN`（未改）** | 需 `node_modules/@decky/*` 类型声明 + `tsc` 实跑；C4 若报错反而应保留 OPEN |
| V4–V7 | `OPEN` | `OPEN`（未改） | 需锁定模板 commit 后比对根文件/清单/rollup/tsconfig |
| V8 | `OPEN` | **`OPEN`（未改）** | 需 C4 真实输出；本轮未执行 |
| V9–V20 / F1–F3 | `OPEN` | `OPEN`（未改） | 需 Steam Deck 真机，本轮不涉及 |

**没有任何 V# 被改为 `CLOSED`。**

---

## 9. 下一轮建议

1. 先在一台满足 §0（P1–P5）的联网机器上按 C1→C2→C3→C4 顺序实跑，**逐字留档** stdout/stderr 与退出码。
2. 把留档带回（或在同一仓库副本上）由**后续轮次**按 §2–§5 各节末尾的回写步骤、
   并参照 §6 模板，把证据写入 [VERIFICATION.md](VERIFICATION.md) 的 V1 / V8，
   并在人工核对后再决定是否调整状态字。
3. 用装好的 `@decky/api` / `@decky/ui` 类型声明逐项核对 V3；能确认的才改状态，不能确认的保留 `OPEN` 并写明原因。
4. 全程保持：不改后端语义、不新增功能、不放宽类型、不 mock、不跳过 `tsc --noEmit`。
5. V9–V20 / F1–F3 仍需 Steam Deck 真机验收，见 [ACCEPTANCE.md](ACCEPTANCE.md) 签核清单。
