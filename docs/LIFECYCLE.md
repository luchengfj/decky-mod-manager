# Lifecycle hooks: what unload and uninstall are allowed to touch

Decky calls three hooks on a plugin besides its RPCs. They live in `main.py`
and were written in the first round; until Round 61 nothing tested them.

| hook | when Decky calls it | what it does |
| --- | --- | --- |
| `_unload` | plugin is being unloaded / reloaded | drops in-memory caches, flushes the log |
| `_uninstall` | user uninstalls the plugin | writes one log line, drops the engine |
| `_migration` | settings schema changed | logs, returns `None` |

All three are `async`. All three do nothing to the filesystem.

## Why "nothing to the filesystem" is a promise worth testing

The user's `Mods/` folder is not ours. A plugin that removes itself should
remove *itself*: its data directory, its journal. It should not take the
user's 30 mods with it as a side effect of being uninstalled.

The three hooks are exactly where that mistake would be easy to make. A
`_uninstall` that says `shutil.rmtree(game_root)` looks like tidying up. It is
also irreversible, it happens at a moment when the user is not thinking about
mods at all, and — because the plugin is being removed — there is no rollback
path left afterwards.

The journal is deliberately *not* deleted either. An uninstalled plugin can be
reinstalled, and the journal is how it remembers what it owns. Deleting it on
the way out would strand every mod it installed: still on disk, no longer
claimed, and — via Round 48's orphan rule — deletable as garbage.

## How it is tested now

`tests/test_lifecycle_hooks.py` builds a synthetic Steam tree with two
hand-installed mods in `Mods/` and one journal record, then for each hook:

1. fingerprints the whole tree — every file's `(size, st_mtime_ns, sha256)` and
   every directory's existence;
2. calls the hook;
3. fingerprints again and asserts the two are equal.

The fingerprint includes `mtime` on purpose. "The bytes are the same" is a
weaker claim than "nothing opened the file for writing", and a test that only
compares content would pass a hook that rewrote a file byte-identically.

A second class covers the same promise structurally: an AST walk asserts no
hook body calls any of `remove / unlink / rmtree / rmdir / makedirs / mkdir /
rename / replace / chmod / symlink / copy / move / write / truncate`, and that
no hook calls an engine mutating method (`install`, `uninstall`, `set_enabled`,
`rollback`, `handover_mods`, `reclaim_quarantine`).

### Why both, and not just the behaviour test

The behaviour test is the one that matters, but it only covers the tree it
built. The AST test covers the code that exists now and fails the moment
someone adds a `rmtree` anywhere in a hook, including on a branch the synthetic
tree never exercises.

### Proven to fire

A guard nobody has seen fail is a guess. Injecting one plausible line into
`_uninstall`:

```python
_sh.rmtree(self.engine.journal.decky_data, ignore_errors=True) if self.engine is not None else None
```

…turns three tests red:

```
FAIL: test_uninstall_does_not_delete_anything_under_the_game_folder
FAIL: test_no_hook_calls_a_write_primitive
FAIL: test_uninstall_only_mentions_its_own_data_in_comments
NEGATIVE_PROOF_FIRED True
```

## The neighbouring trap: `DECKYMOD_GAME_ID`

`tests/test_mvp.py` pins `DECKYMOD_GAME_ID=rimworld` with `setdefault` at
import time, so its 33 historical RimWorld cases keep testing the RimWorld
descriptor. Stardew-oriented modules have to step around that pin.

unittest's discovery imports *every* module before running *any* of them. So a
module that does

```python
_SAVED = os.environ.pop("DECKYMOD_GAME_ID", None)   # module level
```

removes the pin during discovery — before `test_mvp`'s tests run — and nine of
them then resolve AppID 413150 against a RimWorld-shaped tree and fail with
`E_CAPABILITY_DISABLED rimworld status=planned`.

This was fixed by hand three times (rounds 47, 50, 61). The correct shape is
`setUpModule()` / `tearDownModule()` with a module-level `global`, which run
around that module's tests only.

`tests/test_import_order.py` now enforces it: it parses every test module,
collects calls executed at import time, and fails if any of them is a
`pop` / `update` / `clear` on `DECKYMOD_GAME_ID`. Its first run found a
leftover line in `test_conflicts_status.py` — dead code whose own comment two
lines below already said the pop had to happen at run time.

## What this does not claim

- No hook was run by Decky itself in this round. The tests call them directly on
  a synthetic tree. Round 39 and later deployments did exercise `_main`, and the
  Decky-side uninstall path has been used, but not with a fingerprint watching.
- The plugin's own data directory is not asserted untouched by `_uninstall`;
  the test asserts the *game* folder and the journal are untouched, because
  those are the ones whose loss is irreversible.
- This says nothing about the update check, which is still missing — a stale
  plugin cannot tell its user it is stale.
