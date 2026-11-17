# Round 30 — the five outstanding criteria, one page of evidence

This file exists because the request ended with *"按 1→2→3→4→5 顺序推进，每完成
一项立即记录证据"*. It is an index, not a replacement: every claim below points at
the probe or doc that holds the verbatim output.

Status words are used the way this project uses them. **Proven** means a real
device produced the output shown. **Blocked** means the hardware needed is not
attached. Nothing here is marked CLOSED, no `[ ]` box is ticked, and no V#/F#
status moved.

---

## 1. SD card — BLOCKED (hardware), code path proven

**Hardware reality**, `r30_sdcard_check.sh`:

```
lsblk          -> zram0, nvme0n1 (p1..p8; / and /home both on nvme)
/run/media      -> 0 entries
/dev/mmcblk*    -> 0 nodes
/dev/sd[a-z]    -> 0 nodes
```

There is no card in the slot, so the criterion's literal requirement — install a
game **on** a real card and drive the flow there — cannot be met this round.

**What was proven instead**, and it is more than a unit test:

*Both layouts are discovered.* `steamlib._sd_card_libraries(parents=None)` walks
`/run/media` and `/run/media/<user>` and accepts any child containing `steamapps`.
On the device, with a synthetic tree carrying **both** layouts simultaneously
(`r30_sd_scan.py`):

```
FOUND_COUNT 2
LIB /run/media/deck/mmcblk0p1
LIB /run/media/mmcblk0p1
GAME 632470 Disco Elysium     | installed | removable = True
     compatdata /run/media/mmcblk0p1/steamapps/compatdata/632470
GAME 588430 Fallout Shelter   | installed | removable = True
     compatdata /run/media/deck/mmcblk0p1/steamapps/compatdata/588430
REMOVABLE_GAMES 2
REAL_SCAN_TOTAL 29          <- production call unaffected
CRIT1_LAYOUTS_OK True
```

*The full write flow works when the game root is outside `$HOME`* — the layout
where a staging or quarantine area placed on another filesystem would fail with
`EXDEV`. `r30_sd_flow2.py`, on a root shaped like
`/tmp/.../run/media/mmcblk0p1/Steam/steamapps/common/Stardew Valley`:

```
RESOLVED_MOD_ROOT .../mmcblk0p1/Steam/steamapps/common/Stardew Valley/Mods
  on_the_card   = True
DISABLED_ROOT   .../Stardew Valley/.decky-disabled
QUARANTINE_ROOT .../Stardew Valley/.decky-quarantine
MODS_BEFORE 0
1_INSPECT_OK True   UID TestCo.SDFlowProof
2_INSTALL_OK True   DIR .../Mods/testco.sdflowproof        MODS_NOW 1
3_DISABLE_OK True   parked on the card, gone from Mods/
4_ENABLE_OK True    back in Mods/
5_UNINSTALL_OK True TXN 20261116T155016-2275aeb7
6_ROLLBACK_OK True  RESTORED
7_CLEANUP_OK True   MODS_AFTER 0
REAL_MODS_UNTOUCHED True
SD_FLOW_OK True
```

Every path — staging, parking, quarantine — resolves on the same card-shaped
root, and the real `Mods/` folder was never touched (follow-up listing: 29
directories, unchanged).

**Two probes were discarded before this one was trustworthy.**
`r30_sd_flow.py` wrote the manifest for appid 632470 but let the engine resolve
413150; the engine ignored the synthetic root and wrote into the *real* Stardew
`Mods/`. It cleaned up and printed the real paths, but it proved nothing. The
corrected probe asserts the resolved `mod_root` sits under the card root
**before** any write. Related finding: pointing `DECKYMOD_STEAM_ROOT` at a second
library claiming the same appid gives `E_GAME_AMBIGUOUS` rather than a silent
guess — correct behaviour, and why the probe also sets a synthetic
`DECKY_USER_HOME`.

**To close this criterion:** insert a card with at least one Steam game, then
re-run `r30_sd_scan.py` (should report the real mount, `removable = True`) and
`r30_sd_flow2.py` retargeted at that install. No code change is expected; the
evidence simply has to come from media that can be unplugged.

---

## 2. QAM buttons — PROVEN (three real presses, screenshots)

`docs/QAM_REAL_INPUT.md` holds the full write-up. Summary of what makes it real:

* Decky's `ButtonItem` fires on **`onMouseDown`**, and a synthetic
  `MouseEvent`/`.click()`/React-fiber invocation carries `isTrusted = false`, so
  it is ignored. Only CDP `Input.dispatchMouseEvent` produces accepted input.
* Decky's confirm dialogs render in a **different CEF target** than the QAM
  panel (`Steam 大屏幕模式`, target `91089272…`), which is why earlier attempts
  looked like "the dialog never opened".
* Three different `ButtonItem`s were pressed for real, each producing its dialog:

| control | evidence |
|---|---|
| `导入目录 — 本地 ZIP（11）(A)` | `qam_import_910892_1.png` (154088 B) |
| `禁用 (A)` | `qam_disable_910892_1.png` (94005 B) |
| `卸载 (A)` | `qam_uninstall_910892_1.png` (106013 B) |

The uninstall screenshot was re-read as pixels, not inferred: title
「卸载 focustense.StardewUI？文件夹将移入隔离区（不会删除）。」, path line
`w2_quarantine: …/.decky-quarantine/20261116T124930-0923e7cf/focustense.stardewui`,
two `DialogButton`s 「确认 (A)」/「取消 (B)」, footer `Shift+Tab 菜单 / Enter 选择 / Esc 返回`.

All three dialogs were dismissed with Escape, and the folder count was checked
afterwards (`MOD_DIRS` unchanged) — no state was mutated by the demonstration.

**No bare `<button>` anywhere.** `r19_frontend_preflight.py` asserts it
mechanically after the reorg: `BARE_BUTTON_COUNT 0 / BUTTONITEM_COUNT 15 /
DIALOGBUTTON_COUNT 16`.

---

## 3. FOMOD — PROVEN on the deployed build

Re-run against the current deployment (`r28_fomod_probe.py` → `/tmp/r30_fomod.py`):

```
INSPECT_OK True  FOMOD_PRESENT True  USABLE True
GROUPS [('single', ['Low','High']), ('multi', ['Readme','License'])]
INSTALL_OK True
LANDED ['manifest.json', 'readme.txt', 'tex/low.dds']
LOW_YES True   HIGH_NO True          <- the other radio was not installed
README_YES True LICENSE_NO True      <- the other checkbox was not installed
MANIFEST_YES True
WARNINGS ['kept manifest so the mod can be verified']
CLEANUP_OK True
```

Single-select and multi-select both work, unselected options are not extracted,
and the manifest is retained because post-commit verification depends on it.
Rules: `fomod.py` refuses DTD/ENTITY, caps the config at 2 MB, 20 steps, 20
groups/step, 40 options/group, 400 files/option, and any unparseable config
degrades to plain extraction with a readable reason — never a silent failure.

---

## 4. Multi-game templates — PROVEN against the real library

`deckymod/templates.py` adds three descriptors (Stardew `Mods`/SMAPI —
`writable=True`; Cyberpunk 2077 `archive/pc/content`/REDmod — identify-only;
DAVE THE DIVER `BepInEx/plugins`/BepInEx IL2CPP — identify-only). Only the
Stardew one is writable, so `max_enabled_games_in_mvp: 1` and "no universal
one-click install" both still hold. No new RPC: `list_games` carries it.

Device run against the real Steam library (`r28_templates_verify.py`):

```
KNOWN [413150, 1091500, 1868140]
CP2077  adapted=True writable=False dir .../Cyberpunk 2077/archive/pc/content exists=True
DAVE    adapted=True writable=False dir .../Dave the Diver/BepInEx/plugins  exists=False
Warframe 230410 adapted=False note=not_adapted dirs=[]
SCAN games=29 prefix=23
```

`exists=False` for DAVE the DIVER is reported honestly rather than papered over,
and an unknown appid yields `not_adapted` with **zero** guessed paths.

---

## 5. Technical debt — PROVEN, both halves

**The file is gone.** `/home/deck/homebrew/data/decky-mod-manager/data/nexus_api_key`
was listed (`-rw------- 1 deck deck 96`), removed, and the data directory now
holds only `inbox journal logs snapshots` (`KEY_PRESENT=no`).

**No Nexus references in the product.** `grep -ril nexus` over the whole deployed
plugin tree returns **0** files (`TREE_NEXUS=0`), which required fixing three
things beyond the source: a stale `dist/index.js.map`, two prose mentions inside
`registry/games/stardew.json`, and six `.pyc` files. Locally,
`BACKEND_HITS=0 FRONTEND_HITS=0`. Remaining mentions are deliberate and are
listed in `docs/GOAL_RECORD_DOWNLOAD_SOURCE.md`: historical round notes in
`docs/NEXUS_ROADMAP.md` (snapshots are never backfilled), the change record
itself, and real SMAPI `UpdateKeys: ["Nexus:NNNN"]` test data.

**The change note exists** — `docs/GOAL_RECORD_DOWNLOAD_SOURCE.md` — and states
the part that is easy to get wrong: Nexus free accounts cannot fetch download
links at all. `download_link.json` answers **403**, which is an account-policy
refusal, *not* rate limiting (that would be 429). A valid 96-character personal
key receives `200` from the API and is still refused at the download endpoint;
the paid path is a short-lived `nxm://` authorisation link issued by the website,
which is exactly what a free account cannot obtain. Therefore the constraint is
recorded as permanent for free accounts, and the route must not be reintroduced.

---

## What the round changed in the product

Nothing on the capability surface. The panel was reorganised from five always-on
sections into a compact status block plus a four-way `PanelSection` switcher
(`我的 MOD` / `下载 MOD` / `游戏` / `系统`) that mounts one body at a time — see
`docs/PANEL_LAYOUT.md`. Every capability bit, write guard, confirmation flow and
RPC signature is untouched; `tsc --noEmit` exits 0 under `strict: true` and the
reorg introduced no bare `<button>`.

### Two defects the reorg itself introduced, and their fix

Reviewing the reorganised render (not the tests — the tests were green) turned up
two things a user would have met immediately:

1. **The installed-mod list lost its heading.** `INSTALLED_FILEDROP` — *"Mods
   installed by this plugin ({n})"* — was no longer referenced anywhere, so the
   `ModRow` list rendered directly beneath the "Detected mods" button with
   nothing saying what it was. Worse, the two lists hold *different* sets:
   "Detected mods" scans disk, this one is what the plugin installed. Restored as
   a `<PanelSectionRow>` heading above the list, with the key back in use
   (`installed.length` still drives the count). i18n parity re-checked: 320/320.
2. **The mods badge counted the wrong thing.** The switcher showed
   `我的 MOD (<installed.length>)`, and `installed` is *only* what this plugin
   installed. A user who brought 29 mods of their own saw **"我的 MOD (0)"** — the
   panel telling them they had no mods. The badge now uses
   `st?.mods?.length` (what is on disk), and the download badge shows the inbox
   count instead of being empty.

Both are layout/counting bugs inside the new structure; neither touches a
capability, a guard or an RPC.

**Build that carries the fix** (`/home/deck/deckymod-build`, rebuilt on the Deck):

```
TSC_EXIT=0   ROLLUP_EXIT=0
DIST_SIZE=148035
DIST_SHA=e3a35a7a8ace255ae56f876df59c67c529509337240f2ce9ca1356dcb87356b5
Ran 306 tests   OK (skipped=1)   UT_RC=0
MOD_COUNT 29    ZERO_DAMAGE True
ZIP 196293 B  SHA256 766e44d63585e0b0c96aaf21630c07154ea8aea08e7ef4a8958d2bb8e1ce6e17  37 entries
```

Deployed byte-identical (`r30b_verify.sh`: **CHECKED 36 / VERIFY_FAIL=0
ALL_SAME**), `NEXUS_IN_TREE=0`, `KEY_PRESENT=no`. After a
`utilities/disable_plugin` → `utilities/enable_plugin` reload the running process
answers `status()` with `APPID=413150 MODS=29 READ_ONLY=False` and `list_games`
reports 29 games with 3 carrying an adapted template.

## Round 5 re-verification (2026-11-17) — re-checked against the live device, not against memory

Every claim below was re-run this round instead of being carried forward from
the notes. Anything that could be re-measured was re-measured.

| criterion | this round's measurement |
|---|---|
| 1 | `lsblk` -> `zram0 nvme0n1` only; `/run/media` 0 entries; `/dev/mmcblk*` 0; `/dev/sd[a-z]` 0. Still no card. The user released this criterion ("不需要了") and the goal text now reads 标记已完成, so it is not counted as unfinished by me — the hardware facts above are unchanged. |
| 2 | Source still has `BARE_BUTTON_COUNT 0`, `BUTTONITEM_COUNT 15`, `DIALOGBUTTON_COUNT 16`. Deployed `dist/index.js` contains 18 `DialogButton` and 15 `ButtonItem` occurrences. The single `<button` match in the bundle is inside the JSDoc sentence "there are no raw <button> elements" — a text occurrence, not an element. Screenshots unchanged: 154088 / 94005 / 106013 B. |
| 3 | Re-ran `r28_fomod_probe.py` against the **current** deployment: `GROUPS [('single',['Low','High']),('multi',['Readme','License'])]`, `LANDED ['manifest.json','readme.txt','tex/low.dds']`, `HIGH_NO True` / `LICENSE_NO True`, `CLEANUP_OK True`. |
| 4 | Re-ran `r28_templates_verify.py`: `KNOWN [413150,1091500,1868140]`; CP2077 dir `exists=True`; DAVE game not installed so dir `exists=False` reported honestly; Warframe `230410 adapted=False note=not_adapted`; `SCAN games=29 prefix=23`. |
| 5 | `KEY_PRESENT=no` (data dir now only `inbox journal logs snapshots`); `grep -ril nexus` over the deployed plugin tree = **0**; same over the local repo `py_modules`/`main.py`/`src` = **0**; `docs/GOAL_RECORD_DOWNLOAD_SOURCE.md` present. |

Local suite this round: `Ran 306 tests in 3.334s`, `OK (skipped=3)`. All seven
validators EXIT 0 (`validate_i18n` EN/ZH 320 parity, `validate_p0`
`PUBLIC_RPC_COUNT 16` + `ALL_STATIC_CHECKS True`, `validate_download_wiring`
`DOWNLOAD_WIRING_ALL_OK=True`, `validate_api_arity` `BAD 0`,
`r19_frontend_preflight` `FRONTEND_PREFLIGHT_OK`, `r8_zipload_probe`
`PHASE2_STATUS_OK True`, `r4_tar_drift` `73/73` with nothing missing).

Deployed bundle identity: `sha256 e3a35a7a…56b5`, 148035 B, carrying the reorg
markers (`NAV_TITLE` 5, `NAV_MODS` 10, `NAV_DOWNLOAD` 9, `NAV_GAMES` 10,
`NAV_SYSTEM` 10, `INSTALLED_FILEDROP` 5) and the badge fix
(`mods?.length ?? 0`).

**One honest caveat about criterion 2's screenshots.** They were taken at
2026-11-16 20:48–20:50, i.e. **before** the panel reorganisation build
(`e3a35a7a…`, 2026-11-17 00:23). They prove the three ButtonItems were really
pressed and that Decky rendered real dialogs; they do **not** show the
reorganised layout. Criterion 2 asks for button presses, not for a photo of the
new layout, so it stands — but nobody should cite those PNGs as evidence that
the new four-way switcher works on screen.

Also: the toggle control was photographed in its `禁用 (A)` state, not
`启用 (A)`. They are the same `ButtonItem` in two states, so the "three
different ButtonItems" requirement (import / toggle / uninstall) is met.

## What is still open

* **Criterion 1's hardware half - released by the user, not proven by me.**
  The user said 不需要了 and the goal text now carries 标记已完成. I never inserted a
  card, so there is still no evidence of this plugin enumerating a game on real
  removable media. What exists is the code path proven on a card-shaped root plus
  a hardware survey showing the device has no card at all (`lsblk` -> `zram0
  nvme0n1`, `/run/media` empty, zero `/dev/mmcblk*`, zero `/dev/sd*`). Citing
  criterion 1 as "verified on a real SD card" would overstate it.
* **Nobody has photographed the reorganised panel.** The user reported 我已打开
  (they opened QAM) and raised no complaint about the layout, so the reorg is not
  known to be broken - but I have no DOM capture or screenshot of the four-way
  switcher as it now renders, and the three criterion-2 screenshots predate that
  build. The layout is type-checked, deployed byte-for-byte and served by Decky;
  it is not pixel-confirmed.
* Everything this project already carried: V1 is the only CLOSED item,
Step 5 is out of scope, Track C stays separately gated, S9/S10 report-only.
