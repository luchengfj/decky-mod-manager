# 会话交接说明（2026-11-27）

本文件用于把上一轮会话的全部结论交代给新会话。读完这一页即可接手，不需要翻历史。

---

## 一、环境与硬约束

| 项 | 值 |
| --- | --- |
| 工作区 | `C:\ai\SD` = Decky MOD Manager（`deckymod/` 纯标准库 Python 后端 + `src/` TS/React 前端，52 个稳定错误码） |
| Deck 地址 | `deck@192.168.66.191` |
| Deck SSH | `ssh -i C:/ai/SD/.decky-probe/ssh/dshdeck2 -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL deck@192.168.66.191 "<cmd>"` |
| Deck sudo 密码 | `1234`（`sudo -n` 不可用，必须 `echo 1234 \| sudo -S`） |
| Python | `C:/Users/cheng/.dsh/dsh-runtimes/dsh-next-primary-runtime/dependencies/python/python.exe` |
| Node | `.../dependencies/node/bin/node.exe` |
| pnpm | `.../dependencies/pnpm/bin/pnpm.mjs` |
| 测试启动器 | `C:\ai\SD\.decky-probe\run_tests.py`（**必须用它**，见第六节） |

**踩坑提醒**

- `pwsh` 工具已不存在，一律用 `ops_bash`（bash 语法）。
- ssh 一定往 stderr 打 "Permanently added ... known hosts"，导致 exit code 1 —— 这不代表命令失败。
- scp 后先 `ls -la` 确认文件落地再执行；heredoc 经 PowerShell 会炸，改 scp `.sh` 到 `/tmp` 再 `bash`。
- Deck 上无 node/npm，无 `dig`/`nmap`/`traceroute`/`ping6`。

**用户硬约束**

- 用户 (m00549)：「无法在局域网中连上我的手机加速游戏，**302保留**」——302 必须保留，不要再提关闭它。
- 用户只需保留雷神一个加速器（m00758），UU 与奇游均已卸载。

---

## 二、已完成的诊断结论

### 1. Deck「没法联网」= 手机热点断连，不是硬件

- 物理层健康：wlan0 `192.168.66.191/24`、SSID「苹果味」5GHz 5260MHz、signal -23~-56 dBm、tx/rx errors 0、UDP:53 打三个上游全 rcode=0。
- 真因：曾连手机热点「REDMI K100pm」（2.4GHz CH11、BSSID `f6:a8:c1:41:8b:e1`、网关 10.23.42.x、DNS 10.23.42.123），热点消失 → NetworkManager `state change: activated -> failed (reason 'ssid-not-found', managed-type: 'full')`，卡约 1 分钟后回落「苹果味」。
- 已用 sudo 把该 profile 的 `connection.autoconnect` 改为 `no`。

### 2. 302 保留，且 GitHub 模块已修

- `/etc/hosts` 有 **577 条** `127.0.0.1 <域名> #S302`，由 caddy 反代，配自签证书 `CN=steamcommunity.com`（2036 到期）。
- GitHub 约 50% 502 的真因：caddy 上游 `3.ghmain.steam302.xyz` NXDOMAIN（`dial tcp: lookup 3.ghmain.steam302.xyz on 127.0.0.53:53: no such host`）。
- 修法（已执行）：备份 `S302.ini` → `S302.ini.bak-20261125-105708`，`sed -i 's/^github=1$/github=0/'`，重启服务 → hosts 577→**534**，github.com **30/30 全 200**；商店/社区/工坊/SteamAPI 未受影响。
- 恢复命令：`sudo cp .../S302.ini.bak-20261125-105708 .../S302.ini && sudo systemctl restart steamcommunity302`。
- google/youtube 仍是 118 字节占位页（302 功能开关所致），非故障。

### 3. 手机侧

- `192.168.66.79` 反解 = **`REDMI-K100-Pro-Max.lan`**（MAC 随机化 `3a:2c:6b:6a:a7:0b`）。
- 1–65535 全端口扫描**只开 TCP 17200**（私有协议、无 banner、不响应 mDNS/SSDP）。
- 路由器 `192.168.66.1` = OpenWrt/LuCI，只开 53/80，`/cgi-bin/luci/` 返回 403 → 无法免登录读 DHCP 租约。
- `deck.uscheng.kg` / `console.uscheng.kg` / `uscheng.kg` 三处 **NXDOMAIN**（阿里 DoH `"Status":3`）→ deckbuddy 命名隧道从未生效，`tunnel_total_requests 0`。
- 局域网内真正可用的 DSH：**8790 = xinglv-remote**（真前端「行旅 · 远程控制台」）；8789 只是 API（`/` 返回 404）。8790 配对流程端到端验证通过（loopback 泄 token+pairCode、LAN 只给 6 位码、Host 白名单只认 `192.168.66.191`）。

### 4. 键盘 / OSK

- **系统 OSK 从未坏**：Game Mode 下 `SP Keyboard_uid0`（1280×360）历史成功 160+ 次。
- **插件输入框弹不出键盘不是写漏属性**：`@decky/ui` **4.16.5** 的 `TextFieldProps` 无任何 OSK 字段（无 bShowOSK）；`src/components/ImportBox.tsx` 用的就是这个组件。Steam 的 `ShowVirtualKeyboard()` 只对经 CommonUI TextField 注册过 focus/click 的元素生效，且 `pointerType==="mouse"` 会被跳过。
- 桌面模式 `plasma-keyboard` 崩溃根因（coredump 确证）：缺 `XDG_RUNTIME_DIR`/`WAYLAND_DISPLAY`（`QGuiApplicationPrivate::createEventDispatcher()` SIGABRT）；kwin 侧缺 `QT_IM_MODULES=qtvirtualkeyboard`（**复数**，必须设在 **compositor 侧**）。
- **决定性突破**：`qdbus6 org.kde.KWin /VirtualKeyboard org.kde.kwin.VirtualKeyboard.forceActivate` 能让 `visible` 从 false 变 true（三轮可重复 + grim 截图确认）。
- 已按用户要求**全部回滚** 6 处配置，`kwinrc` 恢复 fcitx5 `InputMethod[$e]`，`kxkbrc` 写 `ModelList=pc104`。
- 蓝牙键盘 `13:05:AA:11:95:14` 始终 `Connected:no`；用户已插 XCTECH 无线键盘（`sysrq kbd event7`）可用。

### 5. 加速器：只留雷神，且已验证真生效

- 原有 3 套：网易 UU（`uuplugin.service`，16363）、雷神 leigod（`leigod_plugin.service`，5588/6066/10001）、奇游 qy_acc（inactive 留 5 个孤儿进程，7169/7167）。
- **UU 与奇游已卸载**，只剩 `leigod_plugin.service`。
- 雷神绑定成立：`accelerator.ini` token `af526cc7f654413c8131969fbd586057` / `user_id 145019755`；`/tmp/acc/log/web_api.log` 有 `tag":"Android-v3.0.1"` 请求全 `code:0`，`sn` = Deck MAC `50:5a:65:5f:9a:b9`。
- **雷神协议是 HTTP+JSON over TCP 5588**（不是 WebSocket——早前 WS 握手全 badRequest 是探错角色）。
- 不加速的根因：`/tmp/acc/acc_core_conf.json` 的 `acceleration: []` 为空。
- **加速已验证生效**：`tun_PC` UP + `10.20.0.1`、`ip rule 32765: from all fwmark 0x102 lookup 102`、隧道 `114.132.244.5:26255` `lost_persent:0`、`is_acc(1)` 31–75 次命中。
- **每次关闭都是手机端主动 `stopAcc`**（`signo:10` → daemon `status:0`），不是崩溃。
- 雷神自带每日 03:30–03:59 自动重启策略（`new_upgrade_conf.json`）。

### 6. 音量键物理无响应（**未修好，等用户操作**）

- 软件链路全正常：`wpctl`/`pactl` 立即生效；uinput 注入 `KEY_VOLUMEUP` 让 0.45→0.50；`xdotool key XF86AudioRaiseVolume` 亦生效。
- Deck 扬声器在 **card 1（acp5x）**，card1 无 Master 控件（194 个里没有），音量靠 PipeWire 软件混音——`amixer sget Master` 读到的是 card 0（HDMI），这是早前误判来源。
- **物理音量键零事件**：全机只 `/dev/input/event3` 声明 `KEY_VOLUMEUP/DOWN` 且未被 EVIOCGRAB；`hid-steam` 的 `0003:28DE:1205.0003` connected 后 0.5–1 s 即 disconnected、`report_descriptor` 仅 38 字节、Usage Page `0xFFFF`、不含 Consumer 音量用法；跨 boot 长期如此。
- 待用户执行：**完全关机再开机**（非重启）重置 EC → 不行则关机按住「音量减」+电源进 BIOS 测按键 → 再不行走 Valve 售后。

---

## 三、Round 81（已完成）

对应任务 ①③⑤⑥。

- **① root_merge 补 handover**：
  - `deckymod/smapi.py` 加钩子 `def _handover_roots(self, r) -> list: return [r.mod_root]`。
  - `_handover_inner` 重构为多根（逐根 survey → 整体裁决 → 每根一个 quarantine 子目录 → **每根一条 `MODS_HANDOVER` 事件**）；单根保持历史布局字节不变。
  - 新增模块级 `def _slug(path)`（绝对路径 → `[A-Za-z0-9._-]`，末 120 字符）。
  - `deckymod/root_merge.py` 覆写 `_handover_roots`，走 `self._write_roots()`（绝对路径，因 survey 要比 `st_dev`）。
  - `deckymod/engine.py` 与 `deckymod/smapi.py` 回滚由 `next(...)` 改为遍历**全部** `MODS_HANDOVER` 事件（原只还原第一个根）。
  - `tests/test_handover_multiroot.py` 19 用例；反向验证 `hands[:1]` 精确失败 `second root was not restored`。
- **⑥ 分辨率 / 「贴图位移」**：真因是内联 `height:"auto"` + 自定义 `padding` 覆盖 Steam `DialogButton` 自身几何，使焦点环/底图脱钩（代码里 0 张图片、0 处 absolute）。已删覆盖、badge 改固定高度、`PanelSectionRow`→`div`、统一导出 `MODAL_BODY_STYLE`（含 `minHeight:0`）、补 `wordBreak`。`tests/test_panel_layout_rules.py` 10 用例（**断言前必须 `_strip_comments`**）。
- **⑤ 按钮审计**：15 个按钮（`import` 8 / `more` 4 / `games` 2 / 常驻 2 条件）写入 `docs/PANEL_LAYOUT.md`，并纠正三处过期描述。

## 四、Round 82（已完成）

对应任务 ③。

- 新增 `deckymod/update_check.py`：四态 `current|outdated|unknown|error`、`MAX_CHECKS=25`、**只报告不下载**（免费账号 403 是政策）。
- 三条诚实规则：只查 manifest 里写了 Nexus id 的；版本比重复用 `manifest._version_tuple`（"1.2"=="1.2.0"）；无数字版本返 `unknown`，**绝不为 `current`**。
- 接线：`main.py` RPC `check_mod_updates`、`src/api.ts`、`src/types.ts`、`src/index.tsx` 按钮、i18n 中英各 6 个 key。
- `tests/test_update_check.py` 24 用例。
- **关键教训**：fake opener 必须返回带 `.status`/`.read()` 的 **response 对象**；返回 dict 会让 `nexus._raw` 读成 status 0、全员报 error。
- 文档：新增 `docs/UPDATE_CHECK.md`；更新 `docs/NEXT_FEATURES.md` P2#8、`docs/HANDOVER.md`、`docs/README.md`、`README.md`。

---

## 五、当前验证状态

```
1052 用例全绿（skipped=16）
tsc --noEmit → exit 0
rollup -c    → exit 0（dist/index.js 248544 B，Round 88 产物）
```

公共 RPC 从 38 降到 **30**（Round 88 删了 8 个），i18n 从 473 降到 **447** 键。
用例数下降不是退化：删掉了 `test_nexus_credentials.py`（446 行）与
`test_update_check.py`（248 行）两个整套，新增的比删掉的少。

Round 86 比 Round 85 多 28 个用例（`tests/test_engine_capabilities.py` 的 19 个 +
修测试时补的 9 个断言），产物大 593 B（多了两句 `getattr` 守卫，没删代码）。
`0.6875rem` 仍 1 次、`border-box` 3 次、`ERRR_` 48 次（新增 `ERRR_NO_FOMOD` /
`ERRR_NO_MEMBER_ROOT` 两条）。

Round 87 比 Round 86 多 14 个用例（`tests/test_reinstall_ownership.py`），**产物一个字节没变**
——这一轮只改 `deckymod/root_merge.py`，`dist/` 无需重新部署。

Round 88 的产物**小了 15759 B**（264303 → 248544），这是删掉 key 界面与更新检查按钮的直接结果。

`tsconfig.json` 现在带 `noUnusedLocals` + `noUnusedParameters`，由
`tests/test_suite_hygiene.py::TestTheCompilerStillLooksForDeadCode` 钉住。

**变异验证**（`.decky-probe/r86_mutate.py`）：在副本里逐个改坏 Round 86 的每处修复，
确认对应用例真的会红。10 个 mutation 全部被抓，零存活。详见 §十三。

命令：

```bash
cd /c/ai/SD
PY="C:/Users/cheng/.dsh/dsh-runtimes/dsh-next-primary-runtime/dependencies/python/python.exe"
"$PY" .decky-probe/run_tests.py          # 全量
"$PY" .decky-probe/run_tests.py tests.test_handover_multiroot -v

PNPM="C:/Users/cheng/.dsh/dsh-runtimes/dsh-next-primary-runtime/dependencies/pnpm/bin/pnpm.mjs"
NODE="C:/Users/cheng/.dsh/dsh-runtimes/dsh-next-primary-runtime/dependencies/node/bin/node.exe"
"$NODE" "$PNPM" run typecheck
"$NODE" "$PNPM" run build
```

---

## 六、测试基建的坑（必须知道）

`C:\ai\SD\.decky-probe\run_tests.py` 存在的唯一理由：Windows DSH 沙箱下 `tempfile.mkdtemp()` 用 `mode=0o700` 建目录，其内部**再也无法 makedirs**（22 个假 PermissionError，`os.chmod` 也修不了，必须在创建时不给 mode）。

另外 `tests/` 没有 `__init__.py`，discovery 必须用 `top_level_dir=tests`。

**不要用 `python -m unittest` 直接跑**，会有 22 个假失败。

---

## 七、仍然开放的事项

| # | 事项 | 需要谁 |
| --- | --- | --- |
| 1 | **真机目视 Decky 面板**（`docs/ACCEPTANCE.md` 里 54 处 `DEVICE`、28 处 `OPEN` 全未签核；Round 83 又新增 §B.5 的 4 项 R1–R4） | 用户：在 Game Mode 打开 QAM，agent 无法按 `⋯` |
| 2 | **真机写入签核改 Stardew Valley（413150）** —— Deck 上**没有 RimWorld**（无 `appmanifest_294100.acf`），用户已同意换目标 | 用户 + agent（agent 可 SSH，但需用户在场确认） |
| 3 | **音量键物理无响应** | 用户：完全关机重置 EC 后复测 |
| 4 | ~~px→rem、1920×1080 验收项、`boxSizing`~~ **Round 83 已完成**（代码+测试+文档；仅剩 §B.5 的真机目视，已并入第 1 项） | — |
| 5 | 插件自身版本过期检测（`docs/NEXT_FEATURES.md` P2#8 残留） | agent（本项目无版本端点） |
| 6 | ~~Deck 上是 Round 80 前后的旧构建~~ **已部署**（2026-11-27 20:30 UTC，见 §九） | — |
| 7 | ~~Round 83 全部改动仍未 commit~~ **已提交** `d7cb6a8`（37 文件 / 2819 增 / 188 删） | — |
| 8 | ~~`check_mod_updates` 需要 Nexus API key~~ **用户决定不做（m05103），Round 88 把整套 key 功能删了**。真机实测是决定依据：免费 key 读得到元数据，但 `download_link` 一律 403「premium only」，API 没有关键词搜索端点，网站 HTML 对非浏览器客户端一律 403 —— key 换不到任何一次真实下载。三个不需要 key 的网站打开器保留 | — |
| 9 | ~~Round 84 全部改动未 commit、未部署~~ **已提交 `9bebbbf`、已部署**（2026-11-27 22:47 UTC，见 §十一） | — |
| 10 | ~~`.7z` + `member_root` 无任何测试~~ **已在真机验证**（§十一：`r84_twomod.7z` 报 count=2，选根后 inspect 成功） | — |
| 11 | **归档选择器没在屏幕上见过**——RPC 与写入路径都在真机验过了，但 `showListModal` 的像素没人看过 | 并入第 1 项 |
| 12 | ~~Round 84 报告 item 10 声称删了死代码，实际没删~~ **Round 85 已真删**（五个函数 + `ModRow.tsx` + 104 个 i18n 键），报告已加更正说明 | — |
| 13 | ~~Round 85 全部改动未 commit、未部署~~ **已提交 `f7dbd2b`、已部署两个 bundle**（§十二）。面板像素仍未目视 → 并入第 1 项 | — |
| 14 | ~~Round 86 全部改动未 commit、未部署~~ **已提交 `ed9f1d7`、已部署 54 文件**（§十三）。真机 12 项 RPC + 7 项真实写入全 PASS | — |
| 15 | ~~Round 87 全部改动未 commit~~ **已提交**（`deckymod/root_merge.py` + `tests/test_reinstall_ownership.py` + 文档） | — |
| 16 | **Round 88 全部改动未 commit、未部署**（8 个 RPC + 3 个模块 + 前端 + 447 键 i18n + 6 个测试文件）。这一轮改了 `main.py`、`deckymod/{nexus,user_games,registry}.py` 且**删了两个模块**，部署必须走完整 tgz 并核对 tar 内 `py_modules/` 路径（Round 84 就在这里翻过车） | agent（提交 + 部署） |
| 17 | **删 key 之后的面板没人看过**——`docs/ACCEPTANCE.md` §B.7 的 X1–X5 全 `DEVICE`。「下载 MOD」区从约 86% 降到约 45% 是算出来的，不是量出来的 | 并入第 1 项 |

---

## 八、几条重要的历史教训

- `deckymod/root_merge.py` **不重写** `_rollback_inner`（只有 `deckymod/smapi.py` 定义），所以 handover 回滚语义必须与基类兼容：事件名 `MODS_HANDOVER`、字段 `quarantine`/`from_path`/`moved`。
- 排查 Deck/手机连通性**不能信 Windows 开发机**：本机有链路但无出网（`curl` 全 000、`ping` 100% loss、沙箱拦 `Test-Connection`）。所有结论必须来自 Deck 侧 SSH。
- Deck 曾被全端口扫描后 reboot，已归因为**用户在 Konsole 手敲 `reboot`**（`reboot requested from client PID 1818626 ('reboot')`，conntrack 峰值仅 232/262144），不是扫描所致。
- 压缩服务在本会话长期不可用（反复 `t0:error` 超时），不要在同参上反复重试。**根因（2026-11-27 查清）**：`C:\Users\cheng\.config\billion-context\billion-context.json` 里 `compress.externalSummary` 指向的 `magpie` provider `baseUrl` 是 `http://127.0.0.1:3425/v1`，而该端口无进程监听（`curl` 返回 `000`；8787 网关同样无监听）。配置改成 `enabled:false` 后**必须重启宿主**才生效——进程只在启动时解析一次配置，会话持旧快照。重启后压缩恢复正常。
- **写测试要防"恒真断言"**：Round 83 首版 `test_the_arithmetic_holds_for_every_value_in_the_table` 拿表里的数字乘回 16 再和它自己比，从不读 `rem()` 实现——把 `rem` 改成 `(v*2)+"rem"` 它照样绿。任何"用输入验证输入"的测试都是零信息。同理，`assertIn("boxSizing", line)` 挡不住 `boxSizing: "content-box"`，子串匹配挡不住 `FONT.body` 被 `FONT.bodyLg` 满足。**验证方式是变异测试**：在副本里改坏代码，确认对应用例真的会红。
- **Windows 上编辑文件会把行尾改成 CRLF**，而 HEAD 是 LF，导致 `git diff` 变成上万行噪音、真实改动无法 review。改完先查 `git diff --stat`，若行数远超预期就用 `.decky-probe/r83_eol.py` 那样的脚本还原 LF。建议后续加 `.gitattributes`（`* text=auto eol=lf`）。
- 复制整个工作区做变异/试验时会撞上 `.tmp/mt_mode700`（`mode=0o700` 目录，`WinError 5` 拒绝访问）。只复制 `src/`、`tests/`、`.decky-probe/` 三目录，不要 `copytree` 整个仓库。
- **「tsc exit 0」不等于「前端干净」**。Round 84 就是这样漏掉五个死函数的：`tsconfig.json` 有 `strict: true` 但没有 `noUnusedLocals`/`noUnusedParameters`，而 `strict` 管的是类型不是可达性——没人调用的函数照样通过类型检查。打开这两个开关立刻报出 10 条诊断。教训有两条：① 报告里的"已完成"要回代码里数一遍再写（我当时是照着计划写的，没数）；② 任何"绿灯"都要问它到底检查了什么。
- **`hasattr(engine, "_set_enabled_inner")` 不是「这是不是 file_drop 引擎」的答案**。三个引擎（`Engine` / `FileDropEngine` / `RootMergeEngine`）**全都**实现这个方法，所以这个探针在三个类上都返回 True。Round 84 用它区分引擎能力，结果是 `RootMergeEngine._install_inner` 收到 5 个位置参数、抛 `TypeError`、被 `except Exception` 吞成 `E_UNKNOWN`——**每个 root_merge 游戏（含用户自建游戏）的安装都废了六个星期**，而 1073 个测试里没有一个调过 `RootMergeEngine.install()`。正确做法是显式能力标志（`SUPPORTS_FOMOD` / `SUPPORTS_MEMBER_ROOT` / `SUPPORTS_ARCHIVE_MODS`），并且**为「转发者与接收者的参数表必须一致」写一条测试**——缺陷 B 的本质就是基类转发 4 个、子类只收 3 个。
- **「没报错」和「做对了」是两件事**。缺陷 B 的 `except Exception as e: return err("E_UNKNOWN", ...)` 把 `TypeError` 变成了一句「An unexpected error occurred. See the log for details.」，用户和测试都只能看见这个笼统句。**宽泛的 except 会把编程错误伪装成运行时错误**，这是它能活六周的直接原因。
- **变异 harness 的基线必须自己先全绿**，否则每个「caught」都是假的。第一版副本漏了 `src/` 和 `docs/`，基线自带 55 个失败（前端/文档文本测试），全部「caught」都要作废。还有一个更隐蔽的：副本放在 `%TEMP%` 下时 `test_handover_multiroot` 的 4 个用例必失败——handover 的 quarantine 子目录名是**写根绝对路径的 slug**，副本根路径每深一层都会在目标路径里重复一次，跨过 `MAX_PATH` 后 `os.replace` 报 `WinError 3`。真仓根下实测目标 149 字符，`C:\ai\SD\.r86mut\baseline` 下 279 字符。**结论：变异副本要放在短路径下（`C:\ai\SD\b`、`C:\ai\SD\m01`），并把这件事写进 harness 注释。**
- **变异测试自己也会写错，而写错的变异看起来像「测试太弱」**。Round 87 想验证「剪枝必须尊重非空文件夹」，第一个变异写成 `os.rmdir(current) if not os.listdir(current) else os.rmdir(current)` —— 两个分支都调 `os.rmdir`，而 `os.rmdir` 对非空目录本来就会失败，所以变异体的行为与原代码**完全一致**（等价变异 / equivalent mutant），`caught=0`。差一点据此判定「`test_a_folder_holding_something_else_is_kept` 没用」。换成 `shutil.rmtree(current)` 后立刻 caught=2。**判据：变异之后必须先问「这行代码的行为真的变了吗」，而不是「测试怎么没红」。**
- **`status()` 的返回是双层的**：mod 表在 `data["state"]["mods"]`，不在 `data["mods"]`。Round 87 的第一版真机探针读错了层级、拿到空列表，差点报成「插件把装好的 mod 弄丢了」。**写探针时先打印一格结构（`sorted(data.keys())`），不要凭印象取字段。**
- **「删掉文件」和「删掉文件夹」是两件事**。`_uninstall_inner` 从 Round 81 起就只 `os.remove(dest)`，所以每次卸载都在游戏目录里留一个空壳；`mods/` 下堆了 `R86Write/`、`R87First/`、`R87Second/`。这类残留不会让任何测试变红，只会让用户的 Mods 目录越来越脏——**只有真机 `ls` 看得见**。
- **数 i18n 孤儿键不能只数 `t("...")` 字面量**。`ERR_<code>`、`CAT_<category>`、`ERRR_<reason>` 三族是运行时拼出来的（`src/i18n.ts:62/68/88`），它们的键永远不会以字面量出现。按字面量数会得出 208 个"未使用"，其中 76 个是活的。正确判据是"这个名字除了字典以外，在前后端和 registry 里是否出现过"，剩下 104 个才是真孤儿。

- **「不做某个功能」有两种含义，代价差一个量级，必须问清**。用户说「不需要第 8 项了」，字面上可以是不填 key（0 行），也可以是把整套 key 功能删掉（约 1090 行 + 14 个 i18n 键 + 8 个 RPC 契约变更）。我给了三选一（不填 / 只摘界面 / 整套删）并推荐最轻的那个，用户选了最彻底的——所以**先量代价再问，别按自己的偏好替人省事**。
- **用户说「小字不要了」，量完之后结论可能是「删错东西了」**。真机截图实测：caption 字形带 12–13px、body 17–18px，11px 在 1280×800 上可读；垂直预算算下来「下载 MOD」区 600px 里 432px 是按钮、168px 是小字——小字从来不是空间问题，那个区的 key 输入框（4 个可聚焦行）才是。**用户描述的是一阶症状，测量才给得出一阶原因。** 于是照原计划删小字会省 24% 且仍挤，删 key 框省 48%。
- **「三文件共享的词表」要有一条双向断言**。`main.py` 发 `data={"reason": "<word>"}`，`reasonText()` 把它拼成 `ERRR_<WORD>`，两个字典里得有这个键。三处没有任何测试对齐，于是 Round 88 删 RPC 之后 `ERRR_NO_KEY` / `ERRR_KEY_REJECTED` 变成了「没有任何代码能发出的句子」——死翻译，看着还活着。`tests/test_wired_contract.py::TestEveryReasonWordHasASentence` 现在双向查（发出的都有句、有句的都被发），并且**先断言 regex 有命中**，否则正则坏了会静默通过。
- **删代码也要用行号切片，但必须先把所有断言做完**。Round 88 删 `main.py` 两段时连续三次 `AssertionError`：前一块 `del` 之后行号立刻偏移，而断言是拿偏移后的数组去比对原始行号。可行写法：断言全做完再删，且**从后往前删**。
- **docstring 里含 `"""` 时不能用字符串字面量做 replace**。用 `find` 定位起止索引、从原片段 `rindex('\"\"\"')` 取回结尾引号才写对。
- **`| head -20` 之后的 `$?` 是 head 的退出码**。Round 88 第一次跑 `tsc --noEmit | head -20` 得到 `TSC_EXIT=0`，其实编译是失败的。单独跑命令再取 `$?`。
- **断言要检查「这件事存在」，而不是「这个域名字符串不出现」**。Round 88 的 `TestNexusModuleIsUrlOnly` 第一版禁掉整个 `nexusmods.com`，结果把必须保留的 `https://www.nexusmods.com/...` 模板也禁了。正确边界是：**API 子域名不许回来**（它才需要 key），网站域名必须在。同理 import 集合要排除 `__future__`（它是编译指令不是运行时 import）。

---

## 九、Round 81/82/83 部署记录（2026-11-27 20:28–20:31 UTC）

提交 `d7cb6a8` 之后按 Round 78 的既有流程部署到 `deck@192.168.66.191`。

**打包**：`.decky-probe/r83_deploy.tgz`（53 条目，272167 B，sha256 `2089b112…4fcd51`）——`deckymod/*.py` 38 个 + `main.py` + `dist/index.js` + `registry/**/*.json` 14 个。同时生成 `.decky-probe/r83_local_hashes.txt`（53 行 sha256 基线）。

**备份**：`cp -a ~/homebrew/plugins/decky-mod-manager ~/DeckyModManager-Archive/backups/plugin-before-round83`（2.1M，`BACKUP_OK`）。

**解包**：`sudo tar -xzf /tmp/r83_deploy.tgz -C ~/homebrew/plugins/decky-mod-manager --no-same-owner`（插件顶层目录 root 属主，ZIP 安装所致；`--no-same-owner` 沿用 R78 做法）。注意 tar 的退出码是 1，但文件全部落位——`--no-same-owner` 对目录本身仍有告警，属预期。

**逐文件校验**：部署后对 `main.py`、`dist/index.js`、`py_modules/deckymod/*.py`（38）、`py_modules/registry/**/*.json`（14）共 **58 个文件**做 sha256 全量比对，结果 `NO_LOCAL=0 DIFF=0`。关键单点：

```text
0001bf08…2fe2a7  main.py
983601bd…8f0ced  dist/index.js            (257740 B)
243b24fa…075b3b  py_modules/deckymod/update_check.py   ← 新增文件，之前不存在
50d692c2…344d9   py_modules/deckymod/smapi.py          (含 _handover_roots ×2)
f01e4e99…0bda0   py_modules/deckymod/root_merge.py     (含 _handover_roots ×1)
```

**surface 标志**（本地基线对照）：`_handover_roots` smapi=2 / root_merge=1、`check_mod_updates` main.py=3、`MODAL_BODY_STYLE`=5、`0.6875rem`=1、`border-box`=3、`UPDATE_CHECK_LABEL`=5、`DIST_SIZE=257740`。全部一致。

**重载**：`sudo systemctl restart plugin_loader.service` → `active`；子进程 `Decky MOD Manager (/home/deck/homebrew/plugins/decky-mod-manager/main.py)`（PID 1652863）；日志 `2026-11-27T12:29:55Z [info] Decky MOD Manager loaded (Stardew Valley / SMAPI (detect-only))` + `plugin loaded`，无 traceback。

**真机 RPC 冒烟**（`.decky-probe/r83_smoke.py`，经真实 Decky WS `127.0.0.1:1337` 的 `loader/call_plugin_method`，只读）：

| RPC | 结果 |
| --- | --- |
| `error_codes` | `ok:true`，52 码（与本地 `ERRORS` 一致） |
| `status` | `ok:true`，32024 B，Stardew Valley 413150 / SMAPI `file_drop` / 已识别 Automate、AutomaticGates 等 |
| `recovery` | `ok:true`，`pending:[] stuck:[]` |
| `check_mod_updates` | **`E_CAPABILITY_DISABLED`**，`detail` = `no usable stored key: …/data/nexus_api_key`，`data.configured=false` |

最后一项**不是部署缺陷**：RPC 存在、dispatch 正常、信封结构完整，返回的是设计好的前置条件应答（无 key 时不该去问 Nexus）。它证明 Round 82 的新 RPC 已上线；未证明的是「有 key 时」和「免费账号 403」两条分支，二者都需要用户提供 Nexus API key。

**后端自检**（Deck 侧 system python3）：`from deckymod import update_check` 成功，导出 `MAX_CHECKS`/`STATE_CURRENT`/`STATE_OUTDATED`/`STATE_UNKNOWN`/`STATE_ERROR`/`check`/`compare`；`from deckymod.errors import ERRORS` → 52。

**本轮未证明**：任何布局与交互的视觉效果。所有结论仍来自文件哈希与 RPC 返回值，`docs/ACCEPTANCE.md` §B.5 的 R1–R4 依旧 `DEVICE`/`OPEN`。

**补遗**：`dist/index.js.map` 首次打包时漏了（Deck 上仍是 11-21 的旧 map，291006 B，与 257740 B 的 bundle 行号错位）。已单独推送并校验：297991 B，sha256 `753edc76…74db97f`，与本地一致。补完后插件未重启——map 只被 devtools 读取，不参与运行。

**另**：`rollup -c` 重跑后 bundle 字节一致（257740 B / `983601bd…`），所以早前文档里的 257411 B 是一次过期测量，已在 `docs/PANEL_LAYOUT.md` 与本文修正为 257740 B。

## 十、Round 84（已完成；标题里的"未提交未部署"是当时的记录，后已提交 `9bebbbf` 并部署，见 §十一）

起因：用户 m01522「检查功能性是否需要补充」。不是加功能，是找「用户会撞到但没有
可用路径」的地方。审计方式是把 37 个 RPC 逐个对到面板上的控件，再派两个只读
subagent 交叉验证；它们报的 3 条结论被我回代码否掉了（cyberpunk loader 段、
`operable` 语义、Downloads READ ONLY 与 `delete_source_zip` 的矛盾），都不成立。

十项全部修完，明细见 `docs/NEXT_FEATURES.md` §「Round 84 — the ten gaps a
functional audit found」。最重的两项：

1. **Nexus API key 在面板里根本没有入口。** `src/api.ts` 有四个 key 函数，
   `src/` 下除 api.ts 自身零引用。后果是 `check_mod_updates` 唯一能成功的路径
   是那个文件存在，而用户无法通过面板创建它——按按钮永远得到
   `E_CAPABILITY_DISABLED`。新建 `src/components/ApiKeyBox.tsx` 接上。
2. **`E_MULTI_MOD_ARCHIVE` 是死胡同。** 它报了 mod 名字，然后停住；唯一出路是
   手工拆包，而 Game Mode 没有文件管理器。现在 `install` 仍拒绝，面板接住这个码
   调新 RPC `archive_mods` 列出所有根，用户选一个，`inspect`/`install` 带
   `member_root` 只装那一个。四层转发任何一层漏掉，功能就静默退回拒绝——
   `tests/test_multi_mod.py` 专门钉 RPC 层，因为引擎层测试在 RPC 丢参数时仍全绿。

**没有新增错误码。** 三处测试硬断言 `len(ERRORS) == 52`（`test_auto_import.py:183`、
`test_download_wiring.py:387`、`test_pending_gate.py:134`），六处文档也锁着这个数，
`deckymod/auto_import.py:28-31` 更写明了理由。改用 `data.reason` 十词表 +
`reasonText()` 走 `ERRR_*` i18n；未知词返回空串，旧后端自动回落到通用文案。

### 本轮修掉的两个套件缺陷（值得单独记）

全量套件开始间歇性失败，每次失败的模块都不同（`test_fomod`、`test_rollback_undo`、
`test_multi_mod`、`test_parser_pluggability`），而每个模块单跑全绿。

排查手段：`.decky-probe/trace_rm.py` monkey-patch `shutil.rmtree` / `os.rmdir`，
命中共享根时打印调用栈。**这是唯一有效的手段**——普通报错只说"文件不存在"，不说
是谁删的。两处根因：

- `tests/test_deps.py` 的 cleanup 写的是 `rmtree(os.path.dirname(self.inbox))`，
  而 `self.inbox` 就在 `.decky-test-tmp/` 下一层，于是 `dirname` 正好是**全套件共享
  的根**。一个测试跑完删掉了所有人的 fixture 树。
- `tests/test_parser_pluggability.py` 用固定名 `.decky-test-tmp/jsonc-scan` 且开头
  `rmtree`，第二次跑套件时复用同名目录、删掉上一次的树，结果取决于目录是否已存在。

两者都已修，并新建 `tests/test_suite_hygiene.py` 用 AST 钉住（正则不行：真实的
`join` 嵌在 `dirname(abspath(__file__))` 里，正则版对缺陷本身是通过的）。变异验证：
把两处缺陷还原，卫生测试各红一次。

### 本轮没证明的

- **`.7z` + `member_root`**：无测试，只读了代码。
- **归档选择器、ApiKeyBox 的视觉效果**：零像素验证，`docs/ACCEPTANCE.md` 的
  `DEVICE`/`OPEN` 一项未减。
- **真机**：本轮没连 Deck，全部结论来自本地测试与 RPC 契约。

## 十一、Round 84 部署与真机验证（2026-11-27 22:44–22:49 UTC）

**提交**：`9bebbbf Round 84: the ten gaps a functional audit found`，31 文件 / 1117 增 / 131 删。

**打包踩了一个坑，值得记**：第一次打的 tgz 把后端放进了 `deckymod/`（仓库根布局），
而插件运行时读的是 `py_modules/deckymod/`。解包后 `grep archive_mods main.py` = 6
（main.py 对了），但 `archive_mods` RPC 返回
`E_CAPABILITY_DISABLED "[archive_mods] this engine has no archive inspection path"`——
因为加载的是 `py_modules/` 下的旧引擎。**校验哈希时必须用远端路径**：把本地
`deckymod/*.py` 的哈希写成 `py_modules/deckymod/*.py` 再比对，否则比的是两个不存在的路径。
第二版 tgz（`ec2ba260…`，60 条目）才正确；同时删掉了第一版误建在插件根的 `deckymod/`
和 `registry/`（备份里没有这两个目录，可确认是误建）。

**备份**：`~/DeckyModManager-Archive/backups/plugin-before-round84`（1.6M）。

**校验**：54 个文件 sha256 全量比对 `NO_LOCAL=0 DIFF=0`。关键值：

```text
f1ef9b59…511c752  main.py
4bf99e7d…7e206d0  dist/index.js                      (285056 B)
254384f0…8a42895  dist/index.js.map
2d5cef53…875d27   py_modules/deckymod/smapi.py
900257ee…a28108   py_modules/deckymod/file_drop.py
```

Deck 上另有 5 个顶层 `py_modules/registry/*.json`（bepinex5/melonloader/smapi/ue4ss/xnvse），
Round 84 的备份里同样存在——是更早布局遗留，不是本轮产物。

**surface**（本地基线对照，全部一致）：`archive_mods` main.py=6、`member_root` main.py=9、
`list_mod_roots` file_drop=2、`only_root` manifest=8、`ERRR_` bundle=46、
`BTN_KEY_SAVE` bundle=5、`ARCHIVE_TITLE_N` bundle=5、`DIST_SIZE=285056`。

**重载**：`sudo systemctl restart plugin_loader.service` → `active`；
日志 `2026-11-27T14:47:44Z [info] Decky MOD Manager loaded (Stardew Valley / SMAPI (detect-only))` + `plugin loaded`，无 traceback。

**真机 RPC 冒烟**（`.decky-probe/r84_smoke.py`，经真实 Decky WS）：

| RPC | 结果 |
| --- | --- |
| `error_codes` | `ok:true`，52 码——**本轮没有新增错误码**，契约未破 |
| `status` | `ok:true`，32024 B |
| `recovery` | `ok:true`，`pending:[] stuck:[]` |
| `check_mod_updates` | `E_CAPABILITY_DISABLED`，**`data.reason="no_key"`**（这是 Round 84 的新词汇表生效的证据），`detail` 与 `hint` 同前 |
| `archive_mods`（真实单 mod 包） | `ok:true`，`count:1`，`roots:[{root:"BetterRanching",name:"Better Ranching",version:"2.0.5",files:8}]` |
| `archive_mods`（`/etc/hostname`） | `E_PATH_ESCAPE`，`detail` 明确列出两个允许根 |

**多 mod 通路（真机，这一项本机测不了）**：12 个 inbox 归档全部 `count:1`，没有一个真实
多 mod 包，所以在 Deck 上用它的 `/usr/bin/7z` 现做了 `r84_twomod.zip` 与 `r84_twomod.7z`
（各含 `Pack/ModA`、`Pack/ModB`）：

| 调用 | 结果 |
| --- | --- |
| `archive_mods` zip | `count:2`，`roots:["Pack/ModA","Pack/ModB"]` |
| `archive_mods` 7z | `count:2`，同上——**.7z 分支与 ZIP 分支行为一致** |
| `inspect(zip)` 不带根 | `E_MULTI_MOD_ARCHIVE this archive holds 2 mods (Pack/ModA, Pack/ModB)` |
| `inspect(zip, "Pack/ModA")` | `ok`，`uniqueId=probe.mod.a`，`members=['A.dll','config.json','manifest.json']`，`install_relpath=Mods/probe.mod.a` |
| `inspect(7z)` 不带根 | 同样 `E_MULTI_MOD_ARCHIVE` |
| `inspect(7z, "Pack/ModA")` | `ok`，`uniqueId=probe.7z.a`，`members=['A.dll','manifest.json']` |

**写入路径（真机）**：`install(zip, true, null, "Pack/ModA")` → `ok`，
`dir=.../Mods/probe.mod.a`，`dir_name=probe.mod.a`，`enabled:true`，`txn=20261127T144859-c28cf9b1`。
随后读该目录实际内容：`['A.dll','config.json','manifest.json']`，
**`HAS_B_DLL False`、`MODS_DIR_HAS_MODB False`**——选中的根确实只装了那一个 mod。
`uninstall("probe.mod.a", true)` → `ok`，目录消失，`Mods/` 恢复 28 项、0 个 probe 残留。

**为什么第一次写入验证不算数**：第一次在 `uninstall` **之后**才 `ls` 目录，看到的「不存在」
证明不了写入时没写 ModB。第二次改成装完立刻 `os.walk` 读内容、再卸载，才真正闭合。
记这条是因为「验证顺序错了会得到正确答案」这类事最容易骗过自己。

**本轮仍未证明**：`ApiKeyBox`、归档选择器、四个确认框的**视觉效果**——零像素验证，
`docs/ACCEPTANCE.md` §B.6 的 K1–K5 全部 `DEVICE`/`OPEN`。RPC 契约与写入路径已验，
「按下去好不好看、D-pad 能不能走到」仍未验。

---

## 十二、Round 85（2026-11-28 01:0x–01:3x UTC+8；标题里的"未提交未部署"是当时记录，后已提交 `f7dbd2b` 并部署两个 bundle）

起因：Round 84 的报告里 item 10 写着「删 `openGameLibrary`/`openGameCatalog`/`openModsByGame`/死 import」，
实际一个都没删。用户 m03194 已授权「其余你可以开始改动」，本轮把这件事做完。

### 做了什么

| 项 | 内容 |
| --- | --- |
| tsconfig | 加 `noUnusedLocals: true` + `noUnusedParameters: true`（这两个开关是暴露问题的工具） |
| 删五个死函数 | `openModsByGame`(56) / `showModDetail`(28) / `doUninstall`(8) / `openGameLibrary`(115) / `openGameCatalog`(36)，`src/index.tsx` 2701→2438 行 |
| 删悬空注释 | 四段指向已删函数的段落标题（`§5.1 #4 details`、`§Goal item 2 game library`、`P0 (round 2) read-only game catalog`、Round 37 分组说明）；`§5.1 #6 uninstall` 保留，因为 `doUninstallDir` 还在 |
| 删组件 | `src/components/ModRow.tsx`（106 行，只被一行 import 引用，从未渲染） |
| 删 state | `nexusDomain`/`setNexusDomain`——唯一写入点在 `openGameLibrary` 内；`activeNexusDomain` 改为纯 catalog 派生 |
| 删 i18n | 104 个孤儿键，en/zh 各 575→471，键集保持一致 |
| 修报告 | `docs/ROUND84_REPORT.md` item 10 改为如实描述 + 加「更正」段 |
| 加测试 | `tests/test_suite_hygiene.py::TestTheCompilerStillLooksForDeadCode` 三个用例钉住 tsconfig |

### 级联（tsc 逐轮抓出，全部已修）

删 `confirmLoaderInstall` 的 `d` 参数后 → `openLoaderZipPicker(d)` 的 `d` 也失去用途 →
`GameSetupData` import 变成未用；同时 `ModalAction` 只被两个已删函数用。三个 import/参数
在删完死函数后才暴露，说明**这些删除必须分批跑 tsc**，不能一次删完再看。

### 为什么 `nexusDomain` 是删而不是搬

后端 `main.py:1244 open_mod_page()` 第 1267 行 `domain = self._nexus_browse_domain()`——
每个 Nexus URL 都由后端的活动描述符生成。前端另存一份 domain 只可能与插件实际打开的站点
不一致。所以删掉它，而不是把它挪到别的函数里保留一份副本。

### 验证

```
1073 用例全绿（skipped=18）
tsc --noEmit → exit 0（带两个新开关）
rollup -c    → exit 0，dist/index.js 263710 B（比 Round 84 小 21346 B）
validate_i18n.py → EN/ZH 各 471 键、parity 一致、USED_BUT_MISSING 空、DATA_KEYS 11 全在
validate_p0.py   → ALL_STATIC_CHECKS True
validate_api_arity.py → BAD 0
```

产物核查：`openGameLibrary`/`openGameCatalog`/`openModsByGame`/`showModDetail`/`ModRow`/
`CATALOG_TITLE`/`MODDETAIL_PID`/`LIB_NEXUS_BY_ID` 在 bundle 里均为 0 次；
`ERRR_` 46、`archive_mods` 3、`border-box` 3、`0.6875rem` 1（该留的都还在）。

`doUninstall`→2 与 `MODS_BY_GAME`→5 两个非零计数已核实：前者是 `doUninstallDir`（活的），
后者是 `MODS_BY_GAME_TRUNCATED`（`src/index.tsx:1526` 仍在用的键）。

### 没做到的

- **真机完全没碰**：本轮 `ssh` 超时、`ping` 100% loss，Deck 不在网段上。所有结论来自
  `tsc` + 1073 用例 + bundle 字符串计数，**没有一张截图**。
- 删 `ModRow.tsx` 后 mod 行改为在 `src/index.tsx` 内联构造，编译与测试都过，但视觉效果没人看过。

---

## 十三、Round 86（2026-11-28 09:0x–10:4x UTC+8）

### 起点：一个不该出现的错误码

Round 85 部署后的真机冒烟里，`archive_mods("BetterRanching.2.0.5.zip")` 返回
`E_MANIFEST_UNSAFE`，detail 是 `no manifest parser named 'path_map'`。Round 84 的冒烟里
没见过这个。查下去发现是**两个独立缺陷**，而且第二个比第一个严重得多。

### 缺陷 A：`path_map` 是一个从未实现过的解析器名

- `deckymod/manifest.py:495` 的 `PARSERS` 只有 `json_map` 和 `xml_about`
- 但 `registry/games/cyberpunk.json` 和 `deckymod/user_games.py:245` 都声明了 `"parser": "path_map"`
- `git log -S"PathMapParser"` 为空——这个名字从来没有对应的类
- 触发点只有一处：`archive_mods` → `deckymod/file_drop.py:353 parser = manifest.parser_for(mp)`

关键在于 **root_merge 根本不需要 manifest 解析器**：`deckymod/root_merge.py:278`
`_package_id()` 自己用 `zipfile` 读 `mods/*/info.json` 的 `name`/`version`；
`_plan_archive()` 纯按路径路由。所以正确的修法**不是**去实现 `path_map`，而是把两处
声明删掉，并让 `archive_mods` 在 root_merge 上明确回答「这个概念不适用」。

### 缺陷 B：`install()` 在所有 root_merge 游戏上完全失效

Round 84（`9bebbbf`）给 `FileDropEngine.install()` 加了 `fomod_choices` 和 `member_root`
两个参数，并把它们**位置化**转发：

```python
# deckymod/smapi.py:713
return self._install_inner(zip_path, after_confirm, fomod_choices, member_root)
```

但 `RootMergeEngine._install_inner` 只收 3 个参数（第三个还是 `fomod_choices`）：

```
TypeError: RootMergeEngine._install_inner() takes from 3 to 4 positional arguments
           but 5 were given
```

被 `install()` 的 `except Exception` 吞成 `E_UNKNOWN`，日志里只有一行
`install unexpected: TypeError: ...`。**每一个 root_merge 游戏（Cyberpunk 2077 + 所有
用户自建游戏）的安装都废了**，而且连不带 `member_root` 的普通导入也一样——因为
`FileDropEngine.install` 总是转发 4 个。

真机确认（`.decky-probe/r86_deck_install.py`，经真实 Decky WS）：

```
ACTIVE_GAME 1091500 | Cyberpunk 2077 | enabled
STRATEGY root_merge
INSTALL_DRYRUN_CODE   E_UNKNOWN
INSTALL_DRYRUN_DETAIL TypeError: RootMergeEngine._install_inner() takes from 3 to 4 ...
PLAIN_CODE            E_UNKNOWN   ← 普通导入同样失败
```

### 为什么六个星期没人发现（三条同时成立）

1. Round 84 冒烟时活动游戏是 Stardew Valley（`file_drop`），`path_map` 一次没走到
2. `r84_smoke.py` 只调 `error_codes`/`status`/`recovery`/`check_mod_updates`/
   `archive_mods`/`inspect`，**从未调过 `install`**
3. 1073 个测试里 4 个文件构造 `RootMergeEngine`，**没有一个调 `.install()`**

第 3 条是最要命的：套件覆盖了 root_merge 的路径路由、`_package_id`、handover 多根、
loader 安装，唯独没有「装一个 mod」这个最核心的动作。已用 AST 核过。

### 缺陷 C：`hasattr` 探针认错了引擎

`main.py` 用 `hasattr(engine, "_set_enabled_inner")` 当「这是不是 file_drop」的判据。
但三个引擎**全都**实现 `_set_enabled_inner`，所以这个探针永远为 True。三处受影响：

- `main.py:626` `inspect` 的 `member_root` 分支
- `main.py:632` `archive_mods` 的 `hasattr(engine, "archive_mods")`（RootMergeEngine 继承它）
- `main.py:696` `install` 的 `fd_engine`

### 修法

**能力标志代替 `hasattr`**（`main.py` 唯一诚实的问法）：

| 标志 | `Engine` | `FileDropEngine` | `RootMergeEngine` |
|---|---|---|---|
| `SUPPORTS_FOMOD` | False | True | False |
| `SUPPORTS_MEMBER_ROOT` | False | True | False |
| `SUPPORTS_ARCHIVE_MODS` | False | True | False |

`main.py` 的三处判据全改为 `getattr(engine, "SUPPORTS_X", False)`，`install()` 的
`fd_engine and (...)` 改成两条前置守卫，各自返回带 `reason` 的
`E_CAPABILITY_DISABLED`（`no_fomod` / `no_member_root`）。RimWorld 的 `xml_list` 路径
仍然走原来的 3 参调用，byte-identical。

**签名补齐 + 显式拒绝**：`RootMergeEngine._install_inner` 补上 `member_root` 参数，
并在函数体最前面拒绝：

```python
if fomod_choices:
    raise ModError("E_CAPABILITY_DISABLED",
                   detail="[root_merge] this engine has no FOMOD installer: "
                          "the package is installed file by file",
                   context={"reason": "no_fomod"})
if isinstance(member_root, str):
    raise ModError("E_CAPABILITY_DISABLED",
                   detail="[root_merge] this engine installs the whole archive: "
                          "it has no member-root selection",
                   context={"reason": "no_member_root"})
```

注释里记了原始 `TypeError` 文本，以及「静默忽略比 TypeError 更糟」的理由。

**`archive_mods` 覆盖为返回信封**（第一次写成 `raise` 是错的——所有调用者都当它返回
信封，不包 try，探针立刻报 `ModError` 未捕获）：

```python
def archive_mods(self, zip_path: str) -> dict:
    return err("E_CAPABILITY_DISABLED",
               detail="[archive_mods] this engine installs the whole "
                      "archive, so there is no mod root to pick",
               data={"reason": "no_archive_mods"})
```

**`smapi.py` 的 `except ModError` 补 `data`**——否则子类拒绝的理由词会在出口丢失，
UI 只能显示笼统句，正是本轮要修的东西。

**registry 加载期校验**：新增 `Registry._check_parser_declaration()`，描述符声明了
未注册的 parser 名就在加载时 `raise ModError`，detail 里列出全部已知名字。这是防
「缺陷 A 再发生一次」的根本手段——它让错拼的解析器名在**加载时**就炸，而不是等用户
点开某个文件才看见。

### 回归测试（`tests/test_engine_capabilities.py`，19 用例）

八组：hook 签名与基类一致 / 声明的能力标志与实际一致 / root_merge 装机真的成功且文件
落盘 / 三种不支持的参数各自被拒并带 reason / `archive_mods` 在 file_drop 上仍工作 /
registry 拒绝未注册 parser / RPC 边界用词句回答而不是异常。

写测试时踩的两个坑都记在这里：

- **独立继承链不能当子类比**。第一版要求所有引擎的 `_install_inner` 都是 4 参，把
  `Engine`（自己一条链，`install` 只转发 2 个）也算进去 → 误报。改为
  `if not issubclass(cls, FileDropEngine): continue`，另加
  `test_every_engine_hook_matches_the_wrapper_that_calls_it` 按各自链比较。
- **patch `main.Registry` 影响不到引擎内部**。`deckymod/smapi.py:52` 有
  `from .registry import Registry`，`FileDropEngine.__init__` 用自己模块命名空间的
  `Registry()`，而 `main.py:70 _make_engine()` 只传 `decky=`、不传 `registry=`。修法是
  测试里直接把 fixture 建好的引擎交给 `plugin.engine`。

### 验证

```
1101 用例全绿（skipped=18）
tsc --noEmit → exit 0
rollup -c    → exit 0，dist/index.js 264303 B
validate_i18n.py → EN/ZH 各 473 键、parity 一致、ERROR_CODES 52、USED_BUT_MISSING 空
```

### 变异验证（`.decky-probe/r86_mutate.py`）：10 个 mutation，零存活

| 改坏什么 | 谁抓到 |
|---|---|
| `_install_inner` 丢掉 `member_root` 参数 | `test_the_files_really_land_and_the_journal_records_them` |
| `member_root` 静默忽略而非拒绝 | `test_member_root_is_refused_not_ignored` |
| `ModError` 的 context 不再进 `data` | `test_auto_import` |
| root_merge 谎称支持 `archive_mods` | `test_file_drop_still_declares_support_and_answers_real_roots` |
| `archive_mods` 改抛异常而非返回信封 | `test_archive_mods_is_refused_with_its_own_envelope` |
| 描述符重新声明 `path_map` | `test_11_production_is_wired` |
| registry 停止校验 parser 名 | `test_an_unregistered_parser_name_fails_the_load` |
| `inspect` 恢复 `hasattr` 探针 | `test_no_engine_probes_another_engine_by_hasattr_in_main` |
| `install` 去掉 `member_root` 守卫 | `test_the_source_actually_asks_the_declared_flags` |
| `install` 去掉 `fomod` 守卫 | `test_the_source_actually_asks_the_declared_flags` |

harness 自己踩了三个坑，都写进了注释：① 第一版副本漏 `src/` 和 `docs/`，基线自带
55 个失败，所有「caught」作废 ② 仓库根的 `tmpg7_5o_1s` 是 ACL 锁定的崩溃残留，
`copytree` 直接 `WinError 5` ③ **副本路径必须短**——handover 的 quarantine 子目录名是
写根绝对路径的 slug，副本每深一层都会在目标路径里重复，跨过 `MAX_PATH` 后
`os.replace` 报 `WinError 3`（真仓根下 149 字符，`.r86mut\baseline` 下 279 字符）。

### 没做到的

- **真机一次没跑过**。修复有两个独立证据（1101 用例 + 10 个变异），但「Deck 上的
  `install` 到底恢复没有」只有真机能答。`cyberpunk.json` 的 `EnableDisable` 是 false，
  所以真机 dry-run（`after_confirm=False`）是零风险的第一步。
- **`E_CAPABILITY_DISABLED` 的 message 仍是「This action is not available in this
  version.」**，对「这个引擎不做这件事」是错的话术。没改是因为它被 52 个错误码表统一
  管理，改 message 会动到所有调用点；本轮靠 `data.reason` + `ERRR_*` 两层兜住措辞。
- **没加错误码**。新增一个 `E_NOT_APPLICABLE` 更准确，但会让错误码表从 52 变 53，
  影响 `error_codes` RPC 契约与三个校验脚本。留给后续轮次决定。

## 十四、Round 87（2026-11-28 10:46–11:0x UTC+8）

起点不是计划，是 Round 86 部署后的一次真机探针。`status` 报 `mods=[]`，我先误判成
「插件把装好的 mod 弄丢了」，实际是探针读错了层级（`data["state"]["mods"]`）。读对之后
暴露出两个真缺陷，**都是 Round 81 前后就存在的，不是 Round 86 引入的**。

### 缺陷 D — 重装之后 `files` 翻倍、`present` 撒谎

`deckymod/root_merge.py:523 _placed_for(package_id)` 返回该 packageId **历史上所有**
`FILE_PLACED` 行，不按 txn 过滤。于是一个两文件包装第二次报 `files=4`；`present` 遍历
全部历史行，旧 txn 的 target 早已不存在，所以**明明在盘上的 mod 报 `present=False`**，
面板提示用户重新安装。真机 journal 里 `r86.write` 有 6 条 `FILE_PLACED`（两个 txn 各 2
条 + 2 条 Round 78 的测试残留）。

修法：取该 id **最后一条 `MOD_INSTALLED` 的 txn** 作为「当前安装」，只认这个 txn 的行。
旧 journal 可能只有 `FILE_PLACED` 没有 `MOD_INSTALLED`（早期 loader 安装），那种情况
回退到全部行——**宁可多认几行，也不能丢掉用户再也删不掉的文件**。

### 缺陷 E — 卸载删了文件，留下空文件夹

`_uninstall_inner` 只 `os.remove(dest)`，从不删目录（全文件的 `grep rmdir` 只有
`_drop_staging` 与 quarantine 清理）。真机上卸载 `r86.write` 后 `Cyberpunk 2077/mods/`
下留着 `R86Write/`。

修法：新增 `_prune_empty_dirs(r, dest)`，从文件所在目录向上走。三重保护写在循环顺序里：

1. 只用 `os.rmdir`——非空目录必失败，所以任何还装着东西的文件夹天然不会被碰；
2. 永不删声明的 write root 本身、`_protected()` 里的路径、game root；
3. 只在 `game_root` 之内向上走，而 `_route` 当初就把每个 target 放进 write roots 了。

`_uninstall_inner` 的返回信封新增 `"pruned_dirs"`。

### 验证

- `Ran 1114 tests` / `OK (skipped=19)`；`tsc --noEmit` exit 0；`rollup -c` exit 0
  （`dist/index.js` 264303 B，**一个字节没变**——这轮只改后端）。
- 新建 `tests/test_reinstall_ownership.py`（14 用例）：当前安装只拥有自己的文件、重装
  从空列表开始、重装到新目录报 present=True、卸载找到全部当前文件、旧 journal 仍可卸载、
  文件夹被剪掉、write root 不被剪、装着别人文件的文件夹不被剪、`pruned_dirs` 有值。
- **变异验证**（两轮）：`_placed_for` 换回累加全部行 → 4 个用例失败；剪枝禁用 → 2 个；
  剪枝忽略 write roots → 1 个；剪枝改成 `shutil.rmtree` → 2 个。**第一条「忽略非空检查」
  的变异是等价变异（两个分支都调 `os.rmdir`），caught=0 是变异写错，不是测试弱。**
- **真机前后对比**（`.decky-probe/r87_deck_write.py`）：修复前 4 项 FAIL（`files=4`、
  `present=False`、confirm 数 4、两个文件夹残留）；修复后 14 项全 PASS
  （`files=2 present=True`、列表里消失、无残留文件、无残留空目录）。
- 部署：只改一个文件，`scp` + `sudo cp` 进 `py_modules/deckymod/root_merge.py`，
  sha256 `4cc61558…d454496d` 设备与本地一致，重载后 `active`，无 traceback。

### 没做到的

- **只在 Cyberpunk 的合成/真实目录树上验过**。`_prune_empty_dirs` 对 `bin/x64/plugins`
  这类多层 write root 没在真机跑过——逻辑上等价，但没有证据。
- **`status()` 里 `present` 的语义仍只对 root_merge 成立**。file_drop 引擎那边用的是
  `scan_installed_mods` 的目录扫描，两套判据并存，没有统一的「这个 mod 现在算不算装着」
  定义。这是结构问题，留给后续轮次。

---

## 十五、Round 88 — 删掉整套 Nexus key（2026-11-28 11:5x–12:2x UTC+8）

用户 m05103 逐字：「那就不需要第8项了，然后一些小字我认为也不要，你从多角度分析，
是否需要，也可以反驳」。我要的是决策依据，不是执行指令，所以按 spec-first 走 L2：
先量，再给三选一。用户 m05240 逐字回「B」——最彻底的那条。

### 决定依据（全部来自真机与算术，不是偏好）

| 事实 | 来源 |
| --- | --- |
| 免费 key 能读元数据（`mod info` / 文件列表 / 三个 feed 都 200） | Round 20 真机实测 |
| 但 `download_link` 对免费账号一律 403「this is for premium users only」 | Round 18 起多次实测 |
| Nexus API 没有关键词搜索端点（`mods/search.json` 把 `search` 当 mod id，422） | Round 20 |
| 网站 HTML 对非浏览器客户端一律 403 Cloudflare | Round 18 |
| 「下载 MOD」区占 QAM 700px 视口的约 86%，其中按钮 432px、小字 168px | 本次算术 |
| 该区里有 4 个可聚焦行属于 API key 输入框 | 代码计数 |

结论：**key 换不到任何一次真实下载**，只换来一个要保护的秘密和一个「没有可用 key」的
死胡同。留下来的是三个不需要 key 的网站打开器。

### 删了什么

| 类别 | 内容 |
| --- | --- |
| 后端 RPC | `api_key_status` / `set_api_key` / `delete_api_key` / `nexus_validate` / `nexus_recent` / `nexus_mod` / `nexus_download_link` / `check_mod_updates`（公开 RPC 38 → **30**） |
| 后端模块 | `deckymod/credentials.py`（整删）、`deckymod/update_check.py`（整删）、`deckymod/nexus.py` 395 行 → 98 行纯 URL 构造器 |
| 后端私有方法 | `_nexus_domain()`（只服务那 8 个 RPC）、`_nexus_key()` |
| 前端 | `src/components/ApiKeyBox.tsx`（整删）、`doCheckModUpdates`、`UPDATE_CHECK_*` 按钮、`src/api.ts` 7 个 wrapper、`src/types.ts` 12 个类型 |
| i18n | 473 → **447** 键（24 个孤儿 + `ERRR_NO_KEY` / `ERRR_KEY_REJECTED` 两个失联句子） |
| 小字 | `WRITE_GATE_NOTE`（与 `READ_ONLY_BANNER` 重复）、`IMPORT_OSK`（与 placeholder 重复） |
| 测试 | 删 `test_nexus_credentials.py`（446 行）、`test_update_check.py`（248 行）；`test_wired_contract.py` 整类重写为「凭证必须不在」 |

**保留**：`open_mod_page` / `open_search_page` / `open_browse_page`（从不需要 key）、
`_nexus_browse_domain()`、`deckymod/nexus.py` 的三个 URL 构造器与 `MAX_QUERY_CHARS`、
`ERRR_NO_NEXUS_DOMAIN` / `ERRR_SOURCE_DISABLED`（其余 RPC 仍在用这两个 reason）。

### 新增的守护

`tests/test_wired_contract.py` 新增四类：
- `TestRpcSurface`：30 个 RPC 的计数快照 + 8 个退休 RPC 必须缺席 + 3 个打开器必须存在
- `TestNoCredentialLeftBehind`：`credentials.py`/`update_check.py` 不存在、`main.py` 无那两行 import 且 `api_key` 零出现、没有 RPC 收 `api_key` 参数、`deckymod/*.py` 里无 `nexus_api_key` 字符串
- `TestNexusModuleIsUrlOnly`：`nexus.py` 只 import `urllib.parse`（排除 `__future__`）、代码里无 `api.nexusmods.com`（docstring 里写这个域名是**故意的**，它解释为什么删）、**必须有** `www.nexusmods.com`、三个构造器仍在
- `TestEveryReasonWordHasASentence`：`main.py` 发出的每个 `reason` 词在两个字典里都有句子，且每个 `ERRR_` 句子都有对应的发射者；先断言 regex 有命中，否则正则坏了会静默通过

变异验证：往 en.json 加回一条孤儿句子 → 2 例红；从 zh 删掉一个在用的键 → 2 例红；
只改值不改键 → 仍绿（正确）。

### 验证

```
Ran 1052 tests in 27.663s   OK (skipped=16)
tsc --noEmit                exit 0
rollup -c                   exit 0   dist/index.js 248544 B（-15759 B）
validate_i18n.py            EN 447 / ZH 447, parity [], EXIT=0
validate_p0.py              PUBLIC_RPC_COUNT 30, ALL_STATIC_CHECKS True
validate_api_arity.py       BAD 0
```

bundle 逐项：`ApiKeyBox` 0、`UPDATE_CHECK` 0、`api_key` 0、`check_mod_updates` 0、
`nexus_validate` 0；`ERRR_` 68 次、`archive_mods` 4、`border-box` 3、`0.6875rem` 1 全在。

### 没做到的

- **面板没目视**：§B.7 的 X1–X5 全 `DEVICE`。「86% → 45%」是算术，不是测量。
- **没部署**：这一轮改了 `main.py` + 3 个后端模块并删了 2 个文件，必须走完整 tgz，
  且要核对 tar 内的 `py_modules/` 路径（Round 84 正是在这里把后端打到了错误目录，
  文件哈希全对、RPC 却加载的是旧引擎）。
