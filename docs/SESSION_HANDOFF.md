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
1070 用例全绿（skipped=18）
tsc --noEmit → exit 0
rollup -c    → exit 0（dist/index.js 285056 B，sha256 4bf99e7d…，Round 84 产物）
```

Round 84 的产物比 Round 83 大 27316 B：新增 `ApiKeyBox`、归档选择器、确认流程与
`ERRR_*` 词汇表。`0.6875rem` 仍出现 1 次、`border-box` 3 次。

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
| 8 | **`check_mod_updates` 首次真机调用返回 `E_CAPABILITY_DISABLED`**——不是缺陷，是设计前置条件：`~/homebrew/data/decky-mod-manager/data/nexus_api_key` 不存在。**Round 84 补上了面板里的 key 入口**（`ApiKeyBox`），所以用户现在有路径自己解决；但要走通「有 key 的路径」和「Nexus 免费账号 403」两条分支，仍需真机上实际填一次 key | 用户提供 key 或明确不做 |
| 9 | ~~Round 84 全部改动未 commit、未部署~~ **已提交 `9bebbbf`、已部署**（2026-11-27 22:47 UTC，见 §十一） | — |
| 10 | ~~`.7z` + `member_root` 无任何测试~~ **已在真机验证**（§十一：`r84_twomod.7z` 报 count=2，选根后 inspect 成功） | — |
| 11 | **归档选择器没在屏幕上见过**——RPC 与写入路径都在真机验过了，但 `showListModal` 的像素没人看过 | 并入第 1 项 |

---

## 八、几条重要的历史教训

- `deckymod/root_merge.py` **不重写** `_rollback_inner`（只有 `deckymod/smapi.py` 定义），所以 handover 回滚语义必须与基类兼容：事件名 `MODS_HANDOVER`、字段 `quarantine`/`from_path`/`moved`。
- 排查 Deck/手机连通性**不能信 Windows 开发机**：本机有链路但无出网（`curl` 全 000、`ping` 100% loss、沙箱拦 `Test-Connection`）。所有结论必须来自 Deck 侧 SSH。
- Deck 曾被全端口扫描后 reboot，已归因为**用户在 Konsole 手敲 `reboot`**（`reboot requested from client PID 1818626 ('reboot')`，conntrack 峰值仅 232/262144），不是扫描所致。
- 压缩服务在本会话长期不可用（反复 `t0:error` 超时），不要在同参上反复重试。**根因（2026-11-27 查清）**：`C:\Users\cheng\.config\billion-context\billion-context.json` 里 `compress.externalSummary` 指向的 `magpie` provider `baseUrl` 是 `http://127.0.0.1:3425/v1`，而该端口无进程监听（`curl` 返回 `000`；8787 网关同样无监听）。配置改成 `enabled:false` 后**必须重启宿主**才生效——进程只在启动时解析一次配置，会话持旧快照。重启后压缩恢复正常。
- **写测试要防"恒真断言"**：Round 83 首版 `test_the_arithmetic_holds_for_every_value_in_the_table` 拿表里的数字乘回 16 再和它自己比，从不读 `rem()` 实现——把 `rem` 改成 `(v*2)+"rem"` 它照样绿。任何"用输入验证输入"的测试都是零信息。同理，`assertIn("boxSizing", line)` 挡不住 `boxSizing: "content-box"`，子串匹配挡不住 `FONT.body` 被 `FONT.bodyLg` 满足。**验证方式是变异测试**：在副本里改坏代码，确认对应用例真的会红。
- **Windows 上编辑文件会把行尾改成 CRLF**，而 HEAD 是 LF，导致 `git diff` 变成上万行噪音、真实改动无法 review。改完先查 `git diff --stat`，若行数远超预期就用 `.decky-probe/r83_eol.py` 那样的脚本还原 LF。建议后续加 `.gitattributes`（`* text=auto eol=lf`）。
- 复制整个工作区做变异/试验时会撞上 `.tmp/mt_mode700`（`mode=0o700` 目录，`WinError 5` 拒绝访问）。只复制 `src/`、`tests/`、`.decky-probe/` 三目录，不要 `copytree` 整个仓库。

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

## 十、Round 84（已完成，未提交未部署）

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
