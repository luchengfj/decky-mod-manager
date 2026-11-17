# Panel layout — one section at a time (Round 30)

The user's complaint was concrete: *"优化UI，现在功能太多杂乱且不够清晰"* — the QAM
panel had grown to five always-visible `PanelSection`s (~40 focusable nodes) so
nothing read as the primary action, and every operation was reachable only by
scrolling past everything else.

This doc records what changed, why, what is proven, and what is **not** proven.

---

## 1. What the panel looked like before

Reading `src/index.tsx` before the change (1508 lines), the render tree under
`<Focusable autoFocus>` was:

| # | PanelSection | Contents |
|---|---|---|
| 1 | `TITLE_FILEDROP` / `TITLE_XML` | game line, SMAPI line, W1/W2, quarantine, FS line, read-only banner, last result, busy line, `CONSTRAINTS`, `KNOWN_LIMITS` |
| 2 | `ACTIONS` | `REFRESH`, `INBOX`, `MODLIST`, `CATALOG`, `LIB_REFRESH`, `HISTORY`, `ERRORCODES`, `RECOVERY` |
| 3 | `GH_SECTION` | query field, search button, N result rows, N release/asset rows, N import buttons, direct-URL field, 2 direct buttons, progress line, `GH_B_GATE` |
| 4 | `INSTALLED_FILEDROP` | one `ModRow` per installed mod (29 on the test device) |
| 5 | `IMPORT_OSK` | absolute-path import box |

Every one of those was mounted on open. With 29 installed mods the panel was
~40 constant focusables plus 29 rows, and the D-pad had to walk all of it.

---

## 2. What it looks like now

```
┌─ status summary (always visible, one block) ──────────────┐
│ game · AppID · platform · state                           │
│ SMAPI: detected/missing · launcher option                 │
│ W2 (mods root)                                            │
│ FS posix · flatpak                                        │
│ [read-only banner — only when writes are blocked]         │
│ Last result: …                                            │
│ Working…/Idle                                             │
└───────────────────────────────────────────────────────────┘
┌─ Sections ────────────────────────────────────────────────┐
│ ▾ 我的 MOD (29)      My mods                              │
│ ▸ 下载 MOD           Download                             │
│ ▸ 游戏 (4)           Games                                │
│ ▸ 系统               System                               │
└───────────────────────────────────────────────────────────┘
┌─ only the open section renders below ─────────────────────┐
│  my mods → inbox / mod list / installed rows / OSK import │
│  download → full GitHub + direct-URL flow                 │
│  games    → game catalog + Steam library                  │
│  system   → refresh / history / error codes / recovery /  │
│             quarantine path / constraints / known limits  │
└───────────────────────────────────────────────────────────┘
```

Design decisions and why:

- **The switcher is four `ButtonItem`s, not a tab strip.** Decky's QAM has no
  tab primitive that behaves reliably under gamepad focus; using the same
  component as every other row means the D-pad model does not change between
  the switcher and the content.
- **`openSection` defaults to `"mods"`.** Opening the panel should land on the
  action most users came for. It can be collapsed to `""` by tapping the open
  section again, so a user who only wants the status line is not forced into a
  section.
- **Exactly one section body is mounted.** This is what removes the scroll
  problem: the download flow's ~6 result rows no longer sit between the user
  and the uninstall button.
- **Counts are in the switcher labels** (`我的 MOD (29)`, `游戏 (4)`), so the
  collapsed state still tells you how much is in each area.
- **Nothing was moved across capability boundaries.** The read-only banner,
  `GH_B_GATE`, confirm dialogs, guards and the 16 RPCs are untouched; only the
  arrangement changed.

---

## 3. The mechanical change

`C:\ai\SD\.decky-probe\r29_ui_reorg.py` replaces the single block between
`    <Focusable autoFocus` and `\n    </Focusable>` and inserts one state hook
after `directUrlValue`:

```tsx
// Round 30: one section visible at a time. Before this the panel
// stacked five PanelSections (~40 focusables) at once, so nothing
// read as the primary action. "" = every section collapsed.
const [openSection, setOpenSection] = useState<string>("mods");
```

`C:\ai\SD\.decky-probe\r30_i18n_nav.py` adds the 11 `NAV_*` keys to both
dictionaries (`en` 309 → 320, `zh-CN` 309 → 320).

The script asserts `out.count("<Focusable autoFocus") == 1` and
`out.count("\n    </Focusable>") == 1` before writing, so a partial match
cannot silently produce unbalanced JSX.

---

## 4. Evidence

Local (Windows dev box, offline):

- `python -m unittest discover -s tests` → `Ran 301 tests in 3.330s` / `OK (skipped=3)` / `UT_EXIT=0`.
- `python -m compileall -q deckymod main.py tests` → `COMPILE=0`.
- `.decky-probe\validate_i18n.py` → rc=0, `EN_KEYS 320 / ZH_KEYS 320`, `EN_MINUS_ZH []`,
  `ZH_MINUS_EN []`, `USED_BUT_MISSING_* []`, `DATA_KEYS 8`, `DATA_KEYS_MISSING_* []`.
- `.decky-probe\r19_frontend_preflight.py` → `FRONTEND_PREFLIGHT_OK`,
  `BALANCE index.tsx ok`, `BARE_BUTTON_COUNT 0`, `BUTTONITEM_COUNT 15`,
  `DIALOGBUTTON_COUNT 16`, `I18N_KEYS en=320 zh=320`.
- `.decky-probe\validate_p0.py` → `ALL_STATIC_CHECKS True`.
- `.decky-probe\validate_download_wiring.py` → `DOWNLOAD_WIRING_ALL_OK=True`.
- `.decky-probe\validate_api_arity.py` → `BAD 0`.
- `.decky-probe\r8_zipload_probe.py` → `PHASE2_STATUS_OK True`.
- `.decky-probe\r4_tar_drift.py` → `TAR_COUNT 73 CUR_COUNT 73`, `MISSING_FROM_TAR` empty,
  `STALE_IN_TAR` empty, `BYTE_CHANGED_COMMON 0`.

Deck (`rebuild_final.sh` on `/home/deck/deckymod-build`):

```
TAR_OK
I18N_KEYS_EN=1 ZH=1
NO_BARE_LEAK
TSC_EXIT=0
ROLLUP_EXIT=0
DIST_SIZE=147394
DIST_SHA=0c402ba30500fa53e01300b3e15cb737c125fd9261dd39c314b7e0a63d0579df
Ran 301 tests in 0.719s
OK (skipped=1)
UT_RC=0
STATUS_OK True
STATE read_only false
MOD_COUNT 29
ZERO_DAMAGE True
SIZE 195512
SHA256 32f26b296dc926174c8644b1dc32044860401dc7f137329dda774366cbb6cf83
ENTRIES 37
REBUILD_DONE
```

`tsc --noEmit` exiting 0 is the meaningful part: the reorganised JSX genuinely
type-checks under `strict: true`. The local preflight is an import/export/balance
check and is **not** a type check.

Deploy (`r30_deploy.sh`, run on the Deck): every file `SAME`, `VERIFY_FAIL=0`,
`DIST_SHA=0c402ba3…`, `DIST_SIZE=147394`, `NAV_TITLE_HITS=5`,
`NEXUS_IN_DIST=0`, `NEXUS_FILES=0`.

Running process after `utilities/disable_plugin` → `utilities/enable_plugin`:

```
loader/get_plugins → Decky MOD Manager 0.1.0, disabled:false (7 plugins total)
status()          → APPID=413150  NAME=Stardew Valley  MODS=29  DISABLED=0  READ_ONLY=False
error_codes()     → ERRCODES_COUNT=50
```

The bundle the CEF server actually serves was fetched directly:

```
fetch("http://127.0.0.1:1337/plugins/Decky%20MOD%20Manager/dist/index.js?t=…")
→ {"s":200,"len":140319,"nav":true,"navMods":true,"gh":true,"bare":false}
```

So the running plugin process is on the new Python, and the served frontend
bundle contains the new `NAV_*` strings and no bare `<button>`.

---

## 5. What is NOT proven

- **Nobody has looked at the reorganized panel yet.** `quickaccess_content_999`
  is absent in every CEF target right now (`has:false, len:0`), which means the
  QAM panel is closed. Decky only mounts the plugin's React tree when the panel
  is actually open, and the agent cannot press `⋯`. A DOM read after the user
  opens the QAM is required before claiming the layout renders correctly.
- **Gamepad focus order is unverified.** The switcher is built from `ButtonItem`
  like every other row, so it *should* participate in the same focus ring, but
  "should" is not evidence.
- **Collapsed-state readability is unverified on the device.** The counts and
  `▸`/`▾` prefixes are static text; whether they read well at QAM scale is a
  human judgement.
- **No screenshot of the new layout exists.** The three screenshots from
  Round 28 (`qam_import_910892_1.png`, `qam_disable_910892_1.png`,
  `qam_uninstall_910892_1.png`) show the **old** stacked layout.

---

## 6. Status discipline

- No `CLOSED` added anywhere; `[x]` boxes stay 0; §B.4 unchecked.
- V1 remains the only CLOSED item; V2–V20 / F1–F3 stay OPEN; the original
  RimWorld G3 stays OPEN / NOT SHIPPABLE.
- No capability, guard, confirm flow, or RPC signature changed — the reorg is
  presentation only.
