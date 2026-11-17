# End-to-end evidence: a mod installed by the plugin reaches SMAPI

Round 25. Criterion ⑥ of the goal asks for one real game to complete
"download → auto import → enable → game launches with the mod taking effect",
with the steps and results recorded. This file records that run.

Everything below is a verbatim excerpt from device output. No number here was
estimated.

---

## Environment

| fact | value |
|---|---|
| game | Stardew Valley, AppID 413150 |
| SMAPI | 4.5.2 with Stardew Valley 1.6.15 build 24356 |
| log | `/home/deck/.config/StardewValley/ErrorLogs/SMAPI-latest.txt` |
| plugin | Decky MOD Manager, deployed `dist/index.js` `6e5e42d9…` (133988 B) |
| plugin backend | `smapi.py` `eb15494b…`, `paths.py` `81dc8706…` (9/9 files byte-identical to the build tree) |
| mods on disk | 27 directories under `Mods/`, zero parked |

## Step 1 — the game had never run since the migration

The round-20 migration replaced 618 symlinks with real files. Until the game
ran again, "the mods still work" was an inference, not a fact.

```
LAST_PLAYED 2026-11-15 13:56:04      ← before the migration
AFTER_MIGRATION False
```

## Step 2 — first launch after the migration

The user launched the game. SMAPI wrote a fresh log:

```
LAST_PLAYED 2026-11-16 08:36:54
AFTER_MIGRATION True
SMAPI_VERSION ('4.5.2', '1.6.15', '24356')
LOG_STARTED 2026-11-16T00:36:43
MODS_SMAPI_SEES 27
LOADED_COUNTS  ['20']
SKIPPED_ENTRIES 0
PLUGIN_MODS 27
PLUGIN_DISABLED 0
PLUGIN_READ_ONLY False
PLUGIN_ONLY []
SMAPI_ONLY []
```

Two things matter here.

* SMAPI saw 27 mod directories and loaded 20 mods from them (the other 7 are
  content packs and libraries, which SMAPI lists but does not count as loaded
  mods).
* `PLUGIN_ONLY []` and `SMAPI_ONLY []` mean the plugin's inventory and SMAPI's
  inventory are **exactly the same set**. Neither side sees a mod the other
  misses.

This alone would be a strong result, but it only proves pre-existing mods still
work. It does not prove a mod *this plugin installed* reaches the game.

## Step 3 — install a marker mod through the plugin

A minimal but legitimate SMAPI mod was built and pushed through the plugin's
own RPC surface (not by copying files):

```
MODS_NOW 27 READ_ONLY False
ZIP /home/deck/homebrew/data/decky-mod-manager/data/inbox/std6proof.zip 4529
INSPECT_OK True CODE None UID DeckyModManager.Std6Proof
CONFIRM_PHASE confirm
UNCHANGED_AFTER_CONFIRM True
INSTALL_OK True CODE None
MODS_AFTER 28 OURS_PRESENT True
STAGED_FOR_LAUNCH DeckyModManager.Std6Proof
```

`UNCHANGED_AFTER_CONFIRM True` is the two-phase gate working: asking for a
confirm plan moved nothing.

## Step 4 — the game launched again, and SMAPI loaded it

```
LOG_MTIME 2026-11-16 08:39:18
LOG_STARTS ['2026-11-16T00:39:10']
ON_DISK_MODS True
ON_DISK_PARKED False
SMAPI_SAW_UID True
SMAPI_SAW_NAME True
SMAPI_MOD_DIRS 20
SMAPI_SAW_OUR_DIR True
SKIPPED_TOTAL 0
VERDICT LOADED
```

The decisive line, verbatim from the SMAPI log:

```
[08:39:18 TRACE SMAPI]    Decky Std6 Proof (from Mods/deckymodmanager.std6proof/Std6Proof.dll,
ID: DeckyModManager.Std6Proof, assembly version: 0.0.0)...
```

SMAPI read the DLL from the directory the plugin created, parsed its
`manifest.json`, and registered it under the plugin-generated `UniqueID`.

## Step 5 — cleanup

```
CLEANUP_OK True CODE None
MODS_AFTER_CLEANUP 27
```

Back to the original 27. The marker mod's directory went to quarantine (not
deleted), consistent with the plugin's uninstall semantics.

## What this proves and what it does not

**Proven:** a mod installed by this plugin, into the directory this plugin
creates, under the id this plugin generates, is loaded by SMAPI in a real game
launch with zero skips.

**Not proven by this run:**

* The download half of the chain (GitHub → inbox) was exercised in earlier
  rounds against the live process, but this particular end-to-end run started
  from a locally-built ZIP, not from a GitHub download.
* No human watched the game window. The evidence is the game's own log.
* The enable/disable toggle interacting with a *running* game was not tested
  here; the plugin refuses to write while the game is running
  (`E_GAME_RUNNING`), which is the intended behaviour.

## Reproducing

```
# 1. install the marker
python3 /tmp/std6i.py install

# 2. launch Stardew Valley, wait for the title screen, quit

# 3. check
python3 /tmp/v6.py            # exit 0 and VERDICT LOADED on success

# 4. clean up
python3 /tmp/std6i.py cleanup
```

---

# Round 27 addendum — the download half, on a real content pack

Round 25 proved "installed by the plugin → SMAPI loads it" using a ZIP built on
the device. This round drove the *download* half too, and the chain surfaced
three defects that only a real mod could expose.

## The run

Asset: `tiwe0/sdv-hd2d-release` → `SDV-HD2D-0.9.1.zip`, asset id `674790685`,
2028243 bytes, published 2026-10-25.

| step | RPC | verbatim result |
|---|---|---|
| search | `gh_search` | `TOTAL=2553`, `Pathoschild/StardewMods *964` first |
| list | `gh_releases` | `ASSET_ID=674790685 SDV-HD2D-0.9.1.zip 2028243 ct=application/x-zip-compressed` |
| download+inspect | `gh_download(false,false)` | `PHASE=inspect VERIFIED=size,sha256 SIZE=2028243` / `UID=ivory.SDVHD2D` / `DIR=ivory.sdvhd2d` / `ENTRIES=299` / `UNCOMP=32205590` |
| confirm | `gh_download(true,false)` | `PHASE=confirm PLAN_UID=ivory.SDVHD2D` |
| install | `gh_download(true,true)` | `OK DIR=.../Mods/ivory.sdvhd2d ENABLED=True TXN=20261116T102937-564b112f` |
| status | `status` | `MODS=28 DISABLED=0 INSTALLED=1` |

`VERIFIED=size,sha256` is the point of criterion ④: both a declared size *and*
a declared SHA-256 were compared before the file was written.

## Three defects this run found

1. **The ratio guard refused a real content pack.** 15 sparse `.btr` map files
   compress ~390:1 (largest 158 KB). `E_ZIP_BOMB ratio 101` rejected the mod.
   The ratio alone was never the danger — the uncompressed size is. Added
   `ratio_floor_bytes` (1 MiB): below it the ratio is ignored, above it the old
   100:1 rule still applies, and `max_uncompressed_bytes` still caps the total.
   Tests: `tests/test_ratio_floor.py` (6).

2. **An optional dependency was reported as missing.** `focustense.StardewUI`
   is declared `"IsRequired": false`; the parser collected every dependency id
   regardless, so the mod showed `missing=focustense.StardewUI` — a warning
   SMAPI would never raise. Fixed with the descriptor key
   `field_map.dependency_optional_key` (`"IsRequired"` for this game), so
   `manifest.py` still hard-codes no game field name. Effect on the device:
   `MISSING_TOTAL` went 16 → 4 and HD2D's row became `missing=[]`.
   Tests: `tests/test_optional_dependencies.py` (8).

3. **A 2 MB download outlived the CDP helper's 20 s timeout** and looked like a
   transport failure (`OperationCanceledException`, `RPC_EMPTY`). The plugin
   had done nothing wrong. `r25_rpc.ps1` gained a `-TimeoutSec` parameter;
   nothing in the shipped code changed.

## Follow-up — the missing dependency, and criterion ⑥ closed

The first real launch after installing HD2D (18:51:31) skipped it:

```
[18:51:39 TRACE SMAPI]    SDV-HD2D (from Mods/ivory.sdvhd2d/SDV-HD2D.dll, ID: ivory.SDVHD2D, assembly version: 0.9.1)...
[18:51:40 ERROR SMAPI]       - SDV-HD2D 0.9.1 because its DLL couldn't be loaded.
(Error: System.Exception: Rewriting Hd2d.GameAdapters.dll failed.
 ---> Mono.Cecil.AssemblyResolutionException: Failed to resolve assembly: 'StardewUI, Version=0.6.1.0, Culture=neutral, PublicKeyToken=null')
```

HD2D's own `manifest.json` declares `focustense.StardewUI` with
`"IsRequired": false`, but its DLL needs that assembly at load time. That is an
error in the mod's manifest, not in the plugin: the plugin faithfully reported
exactly what the manifest said. The fix was to download and install the declared
dependency — through the same plugin RPCs under test:

| step | RPC | verbatim result |
|---|---|---|
| search | `gh_search("StardewUI", 1)` | `total_count=4`, `focustense/StardewUI` ★24 first |
| list | `gh_releases("focustense","StardewUI")` | `228530514 StardewUI.0.6.1.zip 844205 usable=true` |
| inspect | `gh_download(...,false,false)` | `PHASE=inspect VERIFIED=size SIZE=844205` / `UID=focustense.StardewUI` / `VER=0.6.1` |
| confirm | `gh_download(...,true,false)` | `PHASE=confirm PLAN_UID=focustense.StardewUI` |
| install | `gh_download(...,true,true)` | `OK DIR=.../Mods/focustense.stardewui ENABLED=True TXN=20261116T105439-6f0679e8` |

A fresh game launch at **18:57:11** (SMAPI 4.5.2 / Stardew Valley 1.6.15)
then produced the decisive evidence:

```
[18:57:20 INFO  SMAPI] Loaded 22 mods:
[18:57:18 TRACE SMAPI]    StardewUI (from Mods/focustense.stardewui/StardewUI.dll, ID: focustense.StardewUI, assembly version: 0.6.1)...
[18:57:19 TRACE SMAPI]    SDV-HD2D (from Mods/ivory.sdvhd2d/SDV-HD2D.dll, ID: ivory.SDVHD2D, assembly version: 0.9.1)...
[18:57:20 TRACE SMAPI]       Detected game patcher in assembly SDV-HD2D.dll.
[18:57:20 INFO  SMAPI]    SDV-HD2D 0.9.1 by ivory | Octopath-style HD-2D rendering ... Public beta.
[18:57:21 TRACE SDV-HD2D] Map groups: loaded 28 groups across 9 maps.
[18:57:21 TRACE SDV-HD2D] Patches: 12 groups installed.        (line 210)
grep -c "SDV-HD2D 0.9.1 because" SMAPI-latest.txt  → 0
```

SDV-HD2D is in the loaded-mod list, emitted its own runtime trace lines, and
appears in **no** skipped-mod entry. This closes criterion ⑥ on a real game:
**download → auto import → enabled → game launched → mod active**, all driven
through the running plugin's callable RPCs and verified by the game's own log.

Launch method note: `steam steam://rungameid/413150` alone did not start the
game from SSH; `/home/deck/.local/share/Steam/steam.sh -applaunch 413150` with
`DISPLAY=:0` and `XDG_RUNTIME_DIR=/run/user/1000` did (this is how the 18:51 and
18:57 launches happened). The 18:55 relaunch attempt after a graceful SIGTERM
did not start it; the subsequent 18:57 attempt did. Each claim above is tied to
the log timestamp that supports it.

Still skipped, all pre-existing user mods unrelated to this run: `(CP) Laundry
Machines` (missing deps), `LookupAnything/i18n` (no manifest), `SMAPI installer`
(not a mod), `Xiddav's Little Red School House` (missing dep).

Status discipline unchanged: no CLOSED item added, no `[ ]` ticked, no V#/F#
flipped, no `update_goal(complete)` call.

