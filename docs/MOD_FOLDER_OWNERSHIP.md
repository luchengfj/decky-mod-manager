# Who owns the Mods folder

Round 44 replaced a marker list with a **structural check**. This page records
what the old check could not see, what the new one measures, and what it still
does not claim.

## The old check, and why it was the wrong shape

`deckymod/file_drop.py` decided whether "somebody else manages this mod tree"
by looking for two names:

```python
def detect_external_manager(game_root, mod_root):
    return (os.path.exists(os.path.join(mod_root, ".mm_deployed"))
            or os.path.isdir(os.path.join(game_root, "Mods_Core")))
```

Those are Amethyst Mod Manager's markers. A device survey in Round 44 showed
both are now **absent**:

```
ABSENT  /home/deck/.local/share/Steam/steamapps/common/Stardew Valley/Mods/.mm_deployed
ABSENT  /home/deck/.local/share/Steam/steamapps/common/Stardew Valley/Mods_Core
ENTRIES=30 SYMLINKED=0
```

So the function had become a constant `False` on the one machine it was
written for. That is not a bug in the markers — it is the shape of the
approach. **A list of marker filenames can only recognise managers somebody
already thought of.** Every new manager needs a new name in the list, and the
plugin ships with no way to discover it.

The durable signal is not a name. It is the **layout**: every manager that
"takes over" a mod tree has to make the folder stop being an ordinary
directory of ordinary directories. On Linux that shows up in exactly three
ways, and each has precisely one explanation.

## What is measured now

`deckymod/modwatch.py::survey(game_root, mod_root)` returns:

| field | meaning |
|---|---|
| `checked` | whether the filesystem answered at all |
| `exists` | `Mods/` exists |
| `is_symlink` | `Mods/` itself is a symlink (the folder-level case) |
| `device` / `game_device` | `st_dev` of `Mods/` and of the game root |
| `entries` | direct children counted |
| `symlinked` / `symlinked_count` | child names that are symlinks, capped at 20 named |
| `reasons` | zero or more of the four reason codes |
| `explain` | one human-readable sentence |

The four reason codes:

- `mods_dir_is_symlink` — the whole folder is a link. A VFS manager deployed it.
- `symlinked_entry` — one or more children are links (a per-mod deployment).
- `mods_on_other_device` — `Mods/` is on a different filesystem than the game.
- `mods_dir_missing` — not a foreign signal; a first install must be allowed to
  create the folder.

`is_foreign()` is true for the first three and **deliberately false** for
`mods_dir_missing`.

## Where it is enforced

Two places, both existing:

1. **The gate.** `smapi.py::_check_write_allowed()` runs the survey *after* the
   legacy marker check and raises `E_EXTERNAL_MANAGER` with the explain string
   when the layout is foreign. This covers `install`, `set_enabled`,
   `uninstall`, and `rollback` — every write.
2. **The report.** `_probe()` puts the survey into `read_only` and exposes it as
   `status().state.layout`, so the panel can say *why* it is read-only instead
   of just that it is. Four new i18n keys carry the reasons
   (`LAYOUT_WHY_TITLE`, `LAYOUT_WHY_SYMLINK`, `LAYOUT_WHY_ENTRIES`,
   `LAYOUT_WHY_DEVICE`).

No new error code was added: this is the same condition the marker check was
already raising, detected more reliably.

## What the device proved

The interesting half of this cannot run on the development machine. Windows
without developer mode answers `os.symlink` with
`WinError 1314 客户端没有所需的特权`, so the local suite covers the decision
logic with faked primitives, and the real links are exercised on the Steam Deck:

```
test_symlinked_entry_refuses_and_names_it ... ok
test_symlinked_mods_dir_refuses_install ... ok
Ran 5 tests OK
```

And the survey against the real, healthy tree:

```
READ_ONLY= False
LAYOUT_PRESENT= True
  checked          True
  exists           True
  is_symlink       False
  entries          30
  symlinked_count  0
  reasons          []
  explain          ''
  device/ game_device= 66312 66312
```

That last pair matters: both numbers are equal, so `Mods/` is on the same
filesystem as the game. The plugin's staging and quarantine directories rely on
that (a cross-device `os.replace` fails with `EXDEV`).

## One test that had to change, and why it was not weakened

Two older cases asserted `E_DUPLICATE` for a symlinked mod directory. With the
layout gate in place the same call now returns `E_EXTERNAL_MANAGER` first:

```
AssertionError: 'E_EXTERNAL_MANAGER' != 'E_DUPLICATE'
detail='the mod folder contains symlinked entries (a deployed mod tree): linked.mod; read-only mode'
```

Both codes refuse the write; neither is wrong. The new one is **more accurate**
— one symlinked entry means the tree as a whole was deployed by something
else, so refusing the whole write surface is more honest than picking off one
name. The assertions were widened to accept either code, and the comment
records why. What was *not* done: deleting the assertion, or relaxing the gate.

## Still open

- **Read-only is not the same as safe to read.** The survey lists and links but
  never follows a symlinked mod directory, so a mod that lives outside the game
  folder shows up as unreadable rather than as its real contents. That is
  deliberate; resolving it would reintroduce the escape this check exists to
  prevent.
- **The panel has still not been pressed on a controller.** It has been proven
  that the strings are in the bundle and that `status()` returns them; nobody
  has physically held the Deck and read the banner.
- **A per-mod deployment that uses hardlinks or bind mounts** is invisible to
  this survey. It is also invisible to every other check the plugin has, and
  detecting it would mean stat-ing every file in the tree on every status call.
  Named here so it is a known gap rather than a surprise.
