# What the game actually loaded (Round 40)

`status()` used to answer only one question: *which mod folders are on disk?*
That is not the question a user asks. A mod can sit in `Mods/`, be perfectly
valid, and still never load — most often because a dependency is missing. The
only place that truth exists is the loader's own log.

This document records what that log really looks like on a device, what the
parser does with it, and what it deliberately refuses to claim.

## Why this came first

`docs/NEXT_FEATURES.md` P0 item 4 said it plainly: nothing in the plugin
verified what the game loaded, and the only real evidence anyone had was a line
a human had read out of a log by hand:

```
[18:57:19 TRACE SMAPI] SDV-HD2D (from Mods/ivory.sdvhd2d/SDV-HD2D.dll, ID: ivory.SDVHD2D, assembly version: 0.9.1)
Patches: 12 groups installed.
```

Turning "installed" into "working" is worth more than ten more convenience
buttons, so it came before any of the P1/P2 items.

## Where the log actually is

A device probe settled this, because the obvious guess is wrong:

| candidate | present |
| --- | --- |
| `~/.config/StardewValley/ErrorLogs/SMAPI-latest.txt` | **yes** (14779 B) |
| `<GAME_ROOT>/SMAPI-latest.txt` | no |
| `<GAME_ROOT>/smapi-internal/SMAPI-latest.txt` | no |

The descriptor lists all four in `loader_detection.loader_log.candidates`, with
`${USER_HOME}` first: inside the plugin process `XDG_CONFIG_HOME` is often
unset, so `${XDG_CONFIG}/...` would expand to `/StardewValley` — a path that can
never exist. The `${XDG_CONFIG}` entries stay in the list anyway, for machines
where that variable *is* set.

## What a real log contains

From `SMAPI 4.5.2` / `Stardew Valley 1.6.15 build 24356`, 150 lines:

```
[18:42:08 INFO  SMAPI] Loaded 22 mods:
[18:42:08 INFO  SMAPI]    Automate 2.6.1 by Pathoschild | Lets you automate crafting machines, ...
[18:42:08 INFO  SMAPI] Loaded 3 content packs:
[18:42:08 INFO  SMAPI]    Place Furniture Outside (Furniture Anywhere Redux) by glymr 1.0.5 by glymr | for Content Patcher | ...
[18:42:08 ERROR SMAPI]    Skipped mods
[18:42:08 ERROR SMAPI]       - (CP) Laundry Machines 1.1.0 because it requires mods which aren't installed (hxw.tilesheets, selph.ExtraMachineConfig, selph.FurnitureMachine).
[18:42:08 ERROR SMAPI]       - LookupAnything/i18n because it contains files, but none of them are manifest.json.
[18:42:08 ERROR SMAPI]       - SMAPI 4.5.2 installer because the SMAPI installer isn't a mod (...).
[18:42:08 ERROR SMAPI]       - Xiddav's Little Red School House 2.3.0 because it requires mods which aren't installed (Xiddav.tilesheet).
[18:42:08 INFO  SMAPI]    Patched game code
```

Four shapes that break a naive parser, all present in that one file:

1. **A mod name containing " by "** — `Place Furniture Outside (...) by glymr 1.0.5 by glymr`. A greedy name match swallows the version.
2. **A pre-release version** — `2.3.1-SNT`. A `\d+(\.\d+)*` version pattern alone rejects it.
3. **A skipped row with no version** — `SMAPI 4.5.2 installer because ...`. Here `4.5.2` is part of the *name*, not a version field.
4. **A skipped sub-folder** — `LookupAnything/i18n`, while the directory is `LookupAnything`.

## The rule

Everything is descriptor-driven (`registry/games/stardew.json` →
`loader_detection.loader_log`), so the module holds no game literals: patterns,
candidate paths and the 4 MB cap all come from JSON. The module is read-only,
never raises, and returns a `reason` string rather than an `E_*` code — a log
that does not exist yet is the normal state on a fresh install, not a fault, and
`errors.py` is a closed set of 50 codes that already has a translation table.

Correlation is by normalized display name, then by normalized directory name.
Anything the log does not mention becomes `load_status = "unknown"` with the note
*"not listed in the log (installed after the last launch?)"*. It is **never**
reported as loaded, because absence from the log is not evidence of success.

## What a device run found

The first live probe produced `skipped: 2` of 4 — the parser was right and the
correlation was silently blind. Two real defects, both only visible on a device:

- `manifest.scan_installed_mods()` returns `dir`, not `dir_name`. The folder
  fallback read a key that never exists, so every mod whose manifest name differs
  from its folder — or whose manifest failed to parse, leaving `name = None` —
  fell through to `unknown`.
- `LookupAnything/i18n` normalizes differently from `LookupAnything`, so a
  skipped sub-folder never matched its parent. A row whose name contains `/` now
  also offers its first segment as a key.

After the fix, on the real 30-directory install:

```
LOADER_LOG {"available": true, "loaded": 22, "content_packs": 3, "skipped": 4,
            "patched": 11, "truncated": false}
LOAD_STATUS_COUNTS {"loaded": 25, "skipped": 4, "unknown": 1}
```

The single `unknown` is `selph.furnituremachine`, installed at 12:24 while the
log was written at 18:42 — exactly the case the note describes. The four
`skipped` rows carry their reasons, e.g. `[CP] Laundry Machines` →
`it requires mods which aren't installed (hxw.tilesheets, selph.ExtraMachineConfig, selph.FurnitureMachine).`

## Surface

| where | what |
| --- | --- |
| `status().state.mods[].load_status` | `loaded` / `content_pack` / `skipped` / `patched` / `unknown` |
| `status().state.mods[].load_version` | version from the log (it can differ from the manifest's) |
| `status().state.mods[].load_reason` | the loader's own sentence for a skip |
| `status().state.mods[].load_missing_ids` | dependency ids parsed out of that sentence |
| `status().loader_log` | summary: counts, `available`, `reason`, `truncated` |
| panel | one quiet line under the paths, plus a badge per mod row |

Disabled mods are deliberately **not** annotated: a parked mod is absent from the
log by construction, so marking it `unknown` would present the user's own choice
as a fault.

## What is proven, and what is not

Proven on the device: the real log parses to 22 / 3 / 4 / 11, all four skipped
rows correlate to their directories with reasons, the one post-log install is
reported `unknown`, and the live plugin process serves this through
`loader_plugin_method → status` (28 public RPCs, unchanged shape).

Not proven: the panel has not been looked at by a human in Game Mode. The badge
and the summary line are in the shipped bundle (`LOAD_STATUS_UNKNOWN`,
`loadStatusLabel`, `LOADER_LOG_LINE` all present in `dist/index.js`) but D-pad
reachability of any new control is still unverified — see `docs/NEXT_FEATURES.md`
P2 item 9. And this reader understands SMAPI's dialect only; another loader
would need its own regexes in its own descriptor, and until then it reports
`log_unrecognized` rather than guessing.
