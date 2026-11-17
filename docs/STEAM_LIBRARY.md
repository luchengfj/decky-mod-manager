# Round 23 — goal item 2 (Steam library enumeration)

**Status: shipped and proven on the device.** Additive section; nothing above this
point is rewritten, and no V#/F# status is flipped.

## Why this round exists

The goal's acceptance criteria were replaced with six concrete items. Five of
them were already demonstrated in earlier rounds on the real Deck (install,
mod lifecycle, download, UI bridge). Item 2 was not: the plugin only ever
resolved **one** appid from a descriptor. It could not answer "what games do I
have installed, where, and which of them have a Proton prefix?".

That is a real gap, not a cosmetic one: an SD card library and an internal
library are two different roots, and a game can be half-downloaded
(`StateFlags != 4`) or have a manifest that no longer parses. Reporting any of
those as "installed" would be a lie the UI then repeats.

## What was added

`deckymod/steamlib.py` — read-only, no writes, never raises:

* `library_roots(user_home)` — roots from `libraryfolders.vdf` (parsed by the
  existing schema-independent `deckymod/vdf.py`) **plus** the known native roots
  and a `/run/media` scan for SD cards. A declared library that is no longer
  mounted is skipped rather than reported as an error.
* `scan_games(user_home)` — one entry per `appmanifest_<appid>.acf`:
  `appid`, `name`, `installdir`, `library`, `install_path`, `compatdata`,
  `state`, `state_flags`, `size_on_disk`, `manifest`, `removable`.
* `summarize(user_home)` — the payload the RPC returns.

Deliberate decisions, each with its reason:

| Decision | Reason |
| --- | --- |
| An `appmanifest_*.acf` is the only proof of installation | A folder under `steamapps/common` proves nothing — the device has folders Steam no longer tracks. |
| `StateFlags == 4` → `installed`; anything else → `incomplete`; unparseable → `unknown` | A half-downloaded game must not be presented as playable. |
| `compatdata` missing → `null`, not an error | Native Linux titles never run Proton. Reporting absence as failure would be wrong for most of this library. |
| `removable` derived from "outside the user's home", not `/run/media` | Keeps the flag honest on any layout, and makes it testable off-device. |
| Module never creates directories | It is called from a read path; a listing must not change the disk. |

`main.py` gained exactly one RPC, `list_games()` (16 public async methods, was
15). It deliberately does **not** go through an engine: the game list is a
machine-level fact and must keep working for games no descriptor covers.
`src/api.ts`, `src/types.ts`, `src/index.tsx` and both i18n dictionaries carry
it to the panel (14 + 5 = 19 `LIB_*` keys; 291 keys per dictionary, parity held).

## Deviation from the criterion, stated plainly

The criterion mentions the SD card path `/run/media/...`. On this Deck the SD
card is **not mounted**, so `libraryfolders.vdf` names only the internal root
and the scan finds 1 library / 29 games / 0 removable. The SD path is
implemented and unit-tested with a synthetic second root, but it has **not** been
exercised against a real card. Claiming otherwise would be exactly the kind of
shell-true/product-false evidence this project has been burned by before.

### Round 30 update — both layouts, and a full write flow on a card-shaped root

Two things were proven here, and one is still open.

**Layouts.** `_sd_card_libraries(parents=None)` now walks `/run/media` and
`/run/media/<user>` and accepts any child that actually contains `steamapps`,
so both real layouts (`/run/media/mmcblk0p1` and
`/run/media/deck/mmcblk0p1`) are found without hard-coding a device name or a
label. `sd_parents` exists purely as a test seam; production passes nothing and
scans the real `/run/media`. Proven on the device with a synthetic tree carrying
**both** layouts at once:

```
FOUND_COUNT 2
LIB /run/media/deck/mmcblk0p1
LIB /run/media/mmcblk0p1
SCAN_TOTAL 2
GAME 632470 Disco Elysium | installed | removable = True
     install_path /run/media/mmcblk0p1/steamapps/common/Disco Elysium
     compatdata  /run/media/mmcblk0p1/steamapps/compatdata/632470
GAME 588430 Fallout Shelter | installed | removable = True
     install_path /run/media/deck/mmcblk0p1/steamapps/common/Fallout Shelter
     compatdata  /run/media/deck/mmcblk0p1/steamapps/compatdata/588430
REMOVABLE_GAMES 2
REAL_SCAN_TOTAL 29          <- the production call is unaffected
CRIT1_LAYOUTS_OK True
```

**Full write flow on a root outside `$HOME`.** `r30_sd_flow2.py` builds a game
root at `/tmp/.../run/media/mmcblk0p1/Steam/steamapps/common/Stardew Valley`,
puts the right manifest (`appid 413150`, `installdir "Stardew Valley"`) in that
library, and asserts **before** touching anything that the engine resolved *that*
root — that guard is the whole point, see below. Output:

```
RESOLVED_MOD_ROOT .../mmcblk0p1/Steam/steamapps/common/Stardew Valley/Mods
  on_the_card   = True
DISABLED_ROOT   .../Stardew Valley/.decky-disabled
QUARANTINE_ROOT .../Stardew Valley/.decky-quarantine
READ_ONLY False
MODS_BEFORE 0
1_INSPECT_OK True UID TestCo.SDFlowProof
2_INSTALL_OK True  DIR .../Mods/testco.sdflowproof        in_mods = True  MODS_NOW 1
3_DISABLE_OK True  PARKED .../.decky-disabled/testco.sdflowproof
   gone_from_mods = True | parked_on_card = True | parked_in_disabled = True
4_ENABLE_OK True   BACK .../Mods/testco.sdflowproof        isdir = True
5_UNINSTALL_OK True TXN 20261116T155016-2275aeb7           gone = True
6_ROLLBACK_OK True RESTORED TestCo.SDFlowProof             isdir = True
7_CLEANUP_OK True  MODS_AFTER 0
RECOVERY_PENDING []
REAL_MODS_UNTOUCHED True
SD_FLOW_OK True
```

Every path — staging, parking, quarantine — lands on the same synthetic card
root, which is the situation that would produce `EXDEV` if the staging or
quarantine area were placed on a different filesystem. Nothing touched the real
`Mods/` folder (`REAL_MODS_UNTOUCHED True`, and a follow-up listing still reads
29 directories).

**Two probes had to be thrown away before this one was honest.**
`r30_sd_flow.py` created a manifest for appid **632470** but let the engine
resolve **413150**; the engine ignored the synthetic root entirely and wrote into
the *real* Stardew `Mods/` folder. It printed absolute paths that said so, and
cleaned up after itself, but it proved nothing about removable media. The
corrected probe asserts the resolved `mod_root` is under the card root **first**
and aborts otherwise. Related: pointing `DECKYMOD_STEAM_ROOT` at a second library
that also claims appid 413150 yields `E_GAME_AMBIGUOUS`
(`AppID 413150 found in 2 libraries: ['/tmp/.../Steam', '/home/deck/.local/share/Steam']`)
rather than a silent guess — which is the resolver behaving correctly, and the
reason the corrected probe also sets a synthetic `DECKY_USER_HOME`.

**Still open:** physical media. `lsblk` shows only `zram0` and `nvme0n1`; there
are no `/dev/mmcblk*` and no `/dev/sd*` nodes; `/run/media` is empty. Criterion 1
keeps its hardware blocker until a card is actually inserted — a directory tree
under `/tmp` is not a mounted card, however many paths it prints.

## Evidence

Local (Windows dev box, no TS/shell to the device for this step):

```
Ran 239 tests OK (skipped=2)
compileall RC=0
validate_i18n / validate_p0 / validate_download_wiring /
r8_zipload_probe / r19_frontend_preflight / r4_tar_drift /
validate_api_arity  -> all EXIT=0
```

New tests: `tests/test_steamlib.py`, 15 cases — both roots read out of the vdf,
removable flag, a declared-but-unmounted library ignored, duplicate roots
collapsed, every manifest listed, AppID/path/prefix surfaced, native game has no
prefix, incomplete install flagged, SD-card game keeps its library, a folder
without a manifest is **not** a game, an unreadable manifest does not abort the
scan, a missing `installdir` falls back to the AppID, and the scan leaves the
directory listing unchanged.

Device (SSH, `/usr/bin/python3`, deployed tree):

```
LIBS 1  GAMES 29  REMOVABLE 0  PREFIX 23
1091500 | Cyberpunk 2077 | installed | .../compatdata/1091500
1868140 | DAVE THE DIVER  | installed | .../compatdata/1868140
632470  | Disco Elysium   | installed | .../compatdata/632470
2622380 | ELDEN RING NIGHTREIGN | installed | .../compatdata/2622380
588430  | Fallout Shelter | installed | .../compatdata/588430
LIBRARIES [('/home/deck/.local/share/Steam', 'libraryfolders.vdf', False)]
```

Build and deploy: `TSC_EXIT=0`, `ROLLUP_EXIT=0`, `DIST_SIZE=130537`,
`DIST_SHA=94542000b6de10aae9a2be10997d3739960924a5848409cdf89bab10ae2ed84c`,
`Ran 239 tests OK`, `UT_RC=0`, ZIP 174493 B / 35 entries. Deployed files are
byte-identical to the build tree (`dist/index.js`, `main.py`, `steamlib.py`,
`smapi.py`, `nexus.py`, `journal.py` all reported `SAME`).

**Live plugin process** (this is the part that matters — the frozen interpreter
has its own copy of the code):

```json
{"ok":true,"libraries":1,"games":29,"removable":0,"prefix":23,
 "first":[[1091500,"Cyberpunk 2077","installed",".../compatdata/1091500"], ...],
 "libpaths":[["/home/deck/.local/share/Steam","libraryfolders.vdf",false]]}
```

The first `list_games` call against the running process returned
`Python Exception`, because the loader was still serving the previous module
set; `utilities/enable_plugin` + a 5 s wait reloaded the backend and the same
call then succeeded. That is recorded here rather than smoothed over — a
deployment is not live until the running process answers, which is why the probe
drives the RPC and not the file on disk.

The served bundle also carries the new section (`HTTP=200`, `LEN=130537`, 11
`LIB_SECTION` hits), so the panel has the code even though no human has looked
at it yet.

## Still not proven

* **No human has seen the game list in the panel.** QAM was closed during this
  round and the agent cannot open it. The DOM text, the list rendering and the
  "not adapted yet" note are unverified visually.
* **No SD card was present**, so both `/run/media` layouts and the full
  import → disable → enable → uninstall → rollback flow were exercised against a
  synthetic tree whose paths look like a mounted card, not against physical
  media. The code path and every filesystem operation are proven; the hardware
  is not.
* Goal items 1/3/4/5/6 are unchanged by this round and were proven earlier;
  item 6's write-up is still outstanding.

Unchanged and untouched: V1 remains the only CLOSED item, V2–V20 / F1–F3 stay
OPEN, G3 (RimWorld 294100) stays OPEN / NOT SHIPPABLE, Step 5 remains out of
scope, Track C stays separately gated, and S9/S10 remain report-only.
