# Decky MOD Manager

中文 | [English](README.en.md)

一个 [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) 插件，在 Steam Deck 游戏模式的
快捷菜单（QAM）里管理游戏 MOD——纯手柄操作，无需终端、无需 root。

它回答一个问题：**这个游戏到底有哪些 MOD，我能不能把它们随时开和关？**
它读取 Steam 游戏库和游戏的 MOD 目录，导入 MOD、启用或禁用、卸载，并在安装出错时回滚。

> **范围，如实陈述。** 三档游戏支持，同一时刻只管理一个：
>
> 1. **星露谷物语**（AppID 413150）+ SMAPI —— `file_drop` 引擎：一个 MOD 一个文件夹放进 `Mods/`，
>    支持启用 / 禁用 / 卸载 / 回滚。SMAPI 本体**只检测**——插件永不安装它、永不改启动项。
> 2. **赛博朋克 2077**（AppID 1091500）—— `root_merge` 引擎：MOD 压缩包**按文件逐个路由**进声明的写入根
>    （`archive/pc/mod`、`mods/`、`bin/x64/plugins`、`r6/scripts`、`red4ext`），永不碰游戏本体文件；
>    每个文件都记 journal，被覆盖的文件先备份，因此卸载与回滚是精确的。
> 3. **其它任何 Steam 游戏，由你配置** —— 面板会问"你的加载器从哪个文件夹读 MOD"；同一个 `root_merge`
>    引擎之后只写入你选定的文件夹。带反作弊的游戏直接拒绝，且不会悄悄替你装加载器：面板只负责打开
>    加载器的官方下载页，解压的也是**你亲手下载**的 ZIP，需你明确按键确认。
>
> 同一时刻只管理一个游戏（`switch_game` 在受支持的游戏间切换面板）。没有"全游戏通用一键安装"，
> 本 README 不会假装有。

## 功能一览

| 功能 | 行为 |
| --- | --- |
| **游戏库** | 列出所有 Steam 库分区里已安装的游戏，包括挂载在 `/run/media/mmcblk0p1` 或 `/run/media/<user>/mmcblk0p1` 的 SD 卡。每个游戏的 MOD 目录由它自己的 manifest 识别，绝不靠猜文件夹列表。 |
| **磁盘上的 MOD** | 显示 MOD 目录里此刻实际存在的东西——包括你自己手动装的、插件毫无记录的 MOD。点开头的目录会被忽略，因为加载器也忽略它们。 |
| **按游戏分组** | 把你装的 MOD 按游戏分组，多个有 MOD 的游戏一目了然，而不是一锅粥。 |
| **切换游戏** | 星露谷和赛博朋克以内置描述符交付；其它游戏在"游戏"区配置一次（你指定 MOD 文件夹）即可。切换会原子化重写 `active_game` 并重建引擎——无需重启插件。配错的配置可以随时在面板里修改或移除。 |
| **导入** | 接收本地 ZIP（装有 `/usr/bin/7z` 的设备也支持 `.7z`），拒绝路径穿越、符号链接、可执行安装器，超出体积上限的压缩包一律拒收。压缩包里的单一包裹目录会自动剥掉。对赛博朋克和用户配置的游戏，压缩包改为按文件逐个路由进声明的 MOD 目录。 |
| **安装 / 启用 / 禁用 / 卸载** | 在游戏的 MOD 目录和同文件系统的旁路目录之间移动 MOD 文件夹——是原子重命名，不是复制。 |
| **回滚** | 每次变更都记 journal。装坏的安装可以回滚到精确的先前状态；做不到时，插件会如实说做不到。 |
| **依赖** | 读取每个 MOD 声明的依赖，报告缺失项，只有当下载包自带的 manifest 指名同一个 MOD ID 时才会代为拉取。 |
| **下载（可选）** | 从白名单主机 HTTPS 下载进收件箱，然后走同一条导入路径。两阶段：先只读计划，再明确确认。 |
| **加载器交接** | 在 MOD 目录设置页：打开加载器的官方下载页（BepInEx 5 / BepInEx 6 IL2CPP / MelonLoader，按游戏的 Unity 形态排序提示），然后解压你下载的 ZIP——一键完成，逐文件 journal，覆盖先备份，可随时移除。内置游戏和启动项不在此列。 |
| **删除源 ZIP** | 导入与加载器确认弹窗提供「安装并删除 ZIP」——独立的显式动作（绝不自动执行），且只允许删声明过的导入目录里的文件。 |
| **MOD 更新检查** | 向你已装 MOD 的 Nexus 页面查询是否有新版本。**只报告，不下载**——免费账号下载被 Nexus 政策禁止（403）。只查 manifest 里写了 Nexus id 的 MOD；版本号无法解析时如实报「无法判断」，绝不报「已最新」。单次上限 25 个并明确告知（第 82 轮，`docs/UPDATE_CHECK.md`）。 |
| **接管 MOD 目录** | 别的管理器占着目录时，一次两阶段确认把它的部署条目移进隔离区，可回滚。星露谷（单目录）与赛博朋克/自定义游戏（多目录，逐目录记录）都支持（第 55 轮 / 第 81 轮，`docs/HANDOVER.md`）。 |
| **错误码** | 52 个稳定错误码，每个都带分类和建议下一步，直接显示在 QAM 里——绝不把堆栈甩你脸上。 |

## 硬性限制（是设计，不是事故）

- **永不 root。** 插件以 Decky 用户身份运行，不提权。
- **不碰 `steamos-readonly disable`。** 任何路径都不会动只读根文件系统。
- **加载器安装，限定范围。** 对所有内置游戏（星露谷、赛博朋克），SMAPI、BepInEx、xNVSE 之类一律
  **只检测、永不安装**——不变。对**你自己配置**的游戏，面板可以打开加载器的官方下载页，并把
  你下载的 ZIP 解压进游戏目录：两阶段确认、逐文件 journal、覆盖先备份、像普通 MOD 一样可移除
  （第 79 轮；经用户批准，把旧的"对所有游戏、永久永不安装"收窄到此）。Steam 启动项**仍然永不代改**
  ——如果加载器需要 `WINEDLLOVERRIDES`，面板把要填的文本给你，你自己粘到 Steam 里。
- **不改启动项。** 加载器需要启动项时，由你在 Steam 里设置；插件只负责报告它缺失。
- **不写 Proton prefix。** MOD 文件进游戏的 MOD 目录，不进 `compatdata`。
- **无云、无账号同步、无遥测。** 插件没有自己的服务器，任何数据都不出设备。

## 仓库结构

```
main.py                  Decky 插件入口；全部公开 RPC（位置参数，JSON 安全信封）
deckymod/                后端，仅标准库
  engine.py              XML 列表引擎（通过编辑状态文件启用/禁用）
  smapi.py, file_drop.py 文件投放引擎（目录存在即启用）
  root_merge.py          按文件安装引擎（赛博朋克、用户配置游戏、加载器 ZIP）
  user_games.py          用户自定义游戏描述符（data/games/<appid>.json，由面板写入）
  manifest.py            Manifest 解析器，完全由游戏描述符驱动
  archive.py, sevenzip.py 压缩包检查、上限、解压
  download.py            带主机白名单的 HTTPS、体积上限、TLS 证书包合并
  deps.py                依赖解析；只接受 manifest 验证过的下载
  paths.py, steamlib.py  Steam 库发现与路径解析
  journal.py, registry.py 事务 journal 与游戏/加载器描述符
registry/                游戏与加载器描述符（JSON）；加一个游戏 = 加一个文件
src/                     前端（TypeScript + React），QAM 面板
tests/                   基于合成 Steam 树的标准库自测
docs/                    设计笔记、验证台账、验收标准
```

## 构建

```bash
pnpm install --frozen-lockfile
pnpm run typecheck     # tsc --noEmit，严格模式
pnpm run build         # rollup -> dist/index.js
```

然后把插件目录（含 `dist/index.js`、`main.py`、`deckymod/`、`registry/`）打成 ZIP，用 Decky Loader 的
"从 ZIP 安装"，或直接放进 `~/homebrew/plugins/`。

CI（`.github/workflows/build.yml`）在每次 push 时运行后端自测、校验所有 registry JSON、构建前端。

## 添加新游戏

一个游戏就是一个 JSON 描述符，不需要改代码：

```json
{
  "id": "mygame",
  "status": "planned",
  "identity": { "appid": 123456, "name": "My Game" },
  "paths": {
    "mod_root": "${GAME_ROOT}/Mods",
    "staging": "${GAME_ROOT}/.decky-staging",
    "quarantine": "${GAME_ROOT}/.decky-quarantine/${TXN_ID}",
    "disabled": "${GAME_ROOT}/.decky-disabled"
  },
  "mod_package": {
    "manifest_globs": ["manifest.json", "*/manifest.json"],
    "manifest_format": "json",
    "id_extraction": { "json": "UniqueID" }
  },
  "state_mutator": { "strategy": "file_drop" }
}
```

放进 `registry/games/`，再在 `registry/registry.json` 里登记一行。`paths` 块是真配置：
`mod_root`、`staging`、`quarantine`、`disabled` 都由它解析，支持 `${GAME_ROOT}`、`${HOME}`、
`${XDG_CONFIG}` 展开。`quarantine` 可以以 `/${TXN_ID}` 结尾——插件存根目录、自己追加事务 id。
未知占位符一律拒绝。`status: "planned"` 让游戏在 UI 里可见但拒绝写入，直到你在真机核实过路径；
合成 Factorio 树验证过游戏目录之外的 MOD 文件夹，但那**不是**第二个真机写回签核。

## 状态与文档

这是一个能用的插件，不是成品。哪些在真机上验证过、哪些只在测试里验证过、哪些还没做——逐条记录在
[`docs/VERIFICATION.md`](docs/VERIFICATION.md)；验收标准在 [`docs/ACCEPTANCE.md`](docs/ACCEPTANCE.md)。
文档索引见 [`docs/README.md`](docs/README.md)。

已知边界，如实说：

- 星露谷的写路径是纯文件夹式（SMAPI 只检测）；赛博朋克和用户配置的游戏按文件安装，但没有
  启用/禁用开关——"已安装"就是"文件在场"，因为它们的加载器没有插件能编辑的状态文件。
- 只有两个内置游戏有真机验证过的描述符。用户配置的游戏按其描述符工作（合成树已验证），
  但你自己的文件夹选择没有针对你的游戏验证过——先拿丢得起的 MOD 试，装完确认游戏还能启动。
- **SMAPI 的启动项必须用完整路径。** `StardewModdingAPI %command%` 看着对，但这个名字不在
  Steam shell 的 PATH 里——启动会失败、游戏打不开（真机实测）。请用
  `"<游戏目录>/StardewModdingAPI" %command%`；插件只能报告启动项缺失或异常，不能替你修。
- Nexus Mods **只做元数据和浏览器交接**。插件能浏览、能打开页面；API 给下载链接是 Premium 账号的
  权利，免费账号请在浏览器里下载。详见 [`docs/NEXUS_ROADMAP.md`](docs/NEXUS_ROADMAP.md)。
- 依赖解析最多三层，能拉取 manifest 验证过的依赖，但不解决加载顺序，也不追任意深的依赖图。

## 许可证

见 [LICENSE](LICENSE)。
