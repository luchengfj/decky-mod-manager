# Mod conflicts: what this plugin reports, and what it refuses to

Round 47 added a read-only scan of `Mods/` that answers one question: **do two
mods ship the same file?** It reports the answer and never acts on it.

## Why it does not resolve anything

Load order is per-game knowledge this plugin does not have. A shared-tree game
may need mod A to win over mod B; a per-mod-directory loader may not care at
all. Sorting that out would mean inventing rules for games nobody here has
tested, and a wrong order is a worse outcome than an honest list of shared
paths. So the panel says "these two mods ship `X`" and stops.

## Scope is a property of the loader (the bug the device found)

The first version walked every mod folder and compared relative paths. On the
real 30-mod Stardew tree it reported **27 conflicts**, and every single one was
a per-mod file:

```
TOTAL=27  TRUNCATED=False  MODS_SCANNED=30
  ROW config.json <- ['Automate', 'AutomaticGates', 'BetterRanching', ...]
  ROW i18n/default.json <- ['Automate', 'BetterRanching', 'BiggerBackpack', ...]
  ROW i18n/zh.json <- [...]
```

That is not a conflict. SMAPI gives every mod its own folder, so twenty
`config.json` files are twenty unrelated files. Reporting them would teach the
user to ignore the line entirely — a false alarm that costs more than silence.

Two defects were behind it:

1. **No notion of scope.** "Two mods ship the same relative path" only means a
   collision when the loader copies everything into one directory (BepInEx, a
   game's own asset root). For a per-mod-directory loader the answer is zero.
2. **Wildcard patterns were compared literally.** The descriptor wrote
   `i18n/*.json` and the code used string equality, so the pattern could never
   match. A pattern that never matches is worse than no pattern, because it
   looks like protection.

Both are now descriptor-driven: `mod_package.conflicts.scope` is either
`shared_tree` or `per_mod_directory`, and `ignore` entries are matched with
`fnmatch` against both the full relative path and the bare filename.

## The descriptor block

```json
"conflicts": {
  "enabled": true,
  "scope": "per_mod_directory",
  "ignore": ["manifest.json", "about/about.xml", "readme.md", "readme.txt",
             "changelog.md", "license", "license.md", "i18n/*.json",
             "config.json"],
  "max_files_per_mod": 2000,
  "max_conflicts": 50
}
```

`scope_note` in the same block records why Stardew is `per_mod_directory` and
when `shared_tree` is the right value.

## What the two scopes answer on the same tree

Device run, synthetic tree with `plugins/X.dll` shipped by three mods plus
per-mod `config.json` and `i18n/zh.json` in each:

```
PER_MOD checked=False reason=per_mod_directory_loader total=0
SHARED checked=True total=1
  ROW plugins/X.dll <- ['Alpha', 'Beta', 'Gamma']
SHARED_DESCRIBE 1 shared path(s): plugins/X.dll
PER_DESCRIBE ''
```

Same fixture, opposite answers: the scope flag is what changed, not the data.

## What the real device answers now

```
OK=True
CONFLICTS_PRESENT=True
CHECKED=False
REASON='per_mod_directory_loader'
TOTAL=0
TRUNCATED=False
MODS_SCANNED=30
ROWS=0
JSON_SAFE=True
MOD_COUNT=30
```

And the panel prints nothing, because `conflictLine()` returns `""` when the
scan did not check anything. That is the intended behaviour: a section that is
not applicable should not occupy a line.

## Bounds

| limit | value | why |
| --- | --- | --- |
| `max_files_per_mod` | 2000 | a mod with 40 000 textures must not turn every `status()` into a full disk walk |
| `max_conflicts` | 50 | the panel shows a summary; a diff view is not a panel's job |

Both set `truncated: true` when hit, and the panel appends
`CONFLICT_TRUNCATED` so a capped list is never presented as the whole truth.

## What is proven, and what is not

**Proven, on the device:** the scan runs inside `status()`; the real Stardew
tree yields `checked=false` with the reason `per_mod_directory_loader`; the same
code under `shared_tree` finds a three-mod collision; `manifest.json`, nested
readme/license and wildcard `i18n/*.json` are ignored; a scan that raises
leaves `status()` successful with `checked=false` and the exception in `detail`;
a mod whose manifest will not parse still participates (the collision is about
directory contents, not manifest fields); file sizes and mtimes are unchanged
across a scan.

**Not proven:** that a human can read the line on a Deck — no hand has pressed
the button since round 47; hardlinks and bind mounts are invisible to this scan
(only symlinks are detected); and duplicate-UniqueID is still the only
*ordering-independent* conflict the plugin reports, because that one is a fact
about mod ids rather than about files.
