# Where a mod lives, and why one helper decides it

In the Stardew / SMAPI backend, "disabled" is not a flag. It is a **location**:

| folder is in | the loader sees | the plugin calls it |
|---|---|---|
| `Mods/<name>/` | the mod, loaded | enabled |
| `.decky-disabled/<name>/` | nothing | disabled |

That is a deliberate design — it means a disabled mod costs nothing at load
time and cannot be half-loaded — but it has a consequence that took three
rounds to fully appreciate: **every code path that needs to know a mod's
location has to ask the same question, and each one that asks it separately
gets its own chance to be wrong.**

## Three rounds, one defect

Each of these was found separately, fixed separately, and each fix was correct
where it landed.

**Round 57 — `install()`** always unpacked into `Mods/`. Importing a newer
version of a mod the user had disabled therefore silently re-enabled it *and*
left the old version parked, so two folders declared the same `UniqueID` and
SMAPI loaded both. The user's "disabled" decision was reversed by an unrelated
action, and re-enabling afterwards failed with `E_FILE_COLLISION`.

**Round 58 — `uninstall()`** only resolved `Mods/`. On a parked mod the move
was skipped, but the transaction was opened, `MOD_UNINSTALLED` was recorded
anyway and the call returned `ok: True`. The mod stayed exactly where it was
and the plugin forgot it existed.

**Round 59 — `inspect()`** previewed a destination `install()` would not use.
`inspect()` is the confirm dialog's data source, so the sentence the user read
and agreed to described a different operation than the one that ran — and the
same-UniqueID collision that would block the install was not warned about at
all.

The fixes were each ~5 lines. The reason there were three of them is that the
*shape* of the bug was never addressed.

## Round 60: one expression

`FileDropEngine._locate()` now answers the question, and everything reads its
answer:

```python
def _locate(self, r, dn: str, managed) -> dict:
    target = os.path.join(r.mod_root, dn)
    parked_at = os.path.join(r.disabled_root, dn)
    parked = bool(managed) and os.path.isdir(parked_at) and not os.path.islink(parked_at)
    return {
        "target": target,      # the Mods/ path, always
        "parked_at": parked_at,
        "parked": bool(parked),
        "install_at": parked_at if parked else target,
    }
```

It returns a dict rather than a tuple so call sites read as what they mean.
`parked` deliberately requires `managed`: a folder that merely shares the name
is not ours, and install and uninstall each refuse that case on their own terms
rather than silently adopting somebody else's directory.

Three call sites now read from it — `inspect()`, `_install_inner()`,
`_uninstall_inner()`. After the refactor the whole module contains **zero**
`os.path.join(r.disabled_root, …)` outside the helper, and `_install_inner`
reads its destination from the dict instead of recomputing it.

### The smaller consequence that made it worth doing

`_install_inner` still needs the `Mods/` path specifically, because "a
non-managed folder already sits at that name" must stay a question about
`Mods/` — a parked folder of the same name is a different situation, handled
separately. That one join is now read from the same dict rather than written
out again, so there is no expression left that could drift.

## How this is kept from regressing

`tests/test_single_path_decision.py` (6 tests) asserts the *structure*, not the
behaviour. Each of rounds 57–59 would have passed a behavioural test at the
moment it shipped, because two duplicated expressions agree until one is
changed. So the tests check:

- `_locate()` exists and returns exactly the four keys, and does not write
- no function except `_locate` builds a `.decky-disabled` path itself
- `inspect`, `_install_inner` and `_uninstall_inner` each call `_locate()`
  exactly once
- `_install_inner`'s `install_at` is a subscript of the helper's return value,
  assigned once

The last one is the specific shape round 59 had: `install_at` computed from
`r.disabled_root` locally.

### Negative proof

A structural test that cannot fail is a comment. `r60_negative_proof.py` copies
`deckymod/` to a scratch tree, puts back the exact round-59 expression inside
`inspect()`, points the test module at the copy, and runs it:

```
RETURNCODE 1
   FAIL: test_the_helper_is_the_only_place_that_builds_both_roots
   FAILED (failures=1)
GUARD_NAMED_A_PLACE True
NEGATIVE_PROOF_FIRED True
```

## Device evidence

`r60_device_probe.py` walks a synthetic tree through every state a parked mod
can be in and prints both sides of each question. One line is a probe bug worth
recording: the first run passed `set_enabled(name, False)` without the third
`after_confirm` argument, so it stopped at the confirm phase and nothing moved
— `C_MODS_EMPTY False`. With the argument supplied:

```
B_INSTALL_OK                 True
B_LANDS_IN_MODS              True
E_LIVE_PREVIEW_TARGET        True          # live mod previews Mods/
C_DISABLE_OK                 True
C_MODS_EMPTY                 True
C_PARKED                     ['probe.parker']
E_PARKED_PREVIEW_TARGET      '.../.decky-disabled/probe.parker'
E_PARKED_NAMES_PARKED        True          # round-59 defect
E_PREVIEW_SAYS_DISABLED      True
E_PREVIEW_DUPLICATE          True
D_UPGRADE_OK                 True
D_WENT_TO_PARKED             True          # round-57 defect
D_STILL_DISABLED             True
D_MODS_STILL_EMPTY           True
D_PARKED_VERSION             '2.0.0'
F_UNINSTALL_OK               True
F_PARKED_GONE                True          # round-58 defect
F_NOT_LISTED_AS_DISABLED     True
G_ROLLBACK_OK                True
G_BACK_IN_PARKED             True
G_MODS_STILL_EMPTY           True          # back where it was, i.e. parked
JSON_SAFE                    True
SCRATCH_REMOVED              True
```

The live `Mods/` folder was never involved: the probe runs on a synthetic tree
and the real tree's 30 mods are untouched.

## Bounds

| bound | value | why |
|---|---|---|
| new modules | 0 | a helper inside the existing engine |
| new error codes | 0 | no new failure mode; the refactor changed no message |
| new RPCs | 0 | the surface is unchanged |
| new public API | 1 private method | `_locate`, underscore-prefixed |
| paths decided in one place | 3 call sites | `inspect`, `_install_inner`, `_uninstall_inner` |
| tests added | 6 structural + 1 negative proof script | |

## Proven, and not proven

Proven: the three call sites now read one expression; the structure cannot
degrade silently (negative proof above); all 24 device assertions hold; 720
tests pass with 7 validators green; the deployed bundle hash matches the build.

Not proven: that this is the last place in the codebase where one fact is
encoded twice. Round 59's audit script looked for functions that reference only
one of the two roots; it reports candidates, and judging which are legitimate
was my reading of nine functions, not an automated result. The RimWorld engine
has the same *class* of question but a different answer (all mods stay in
`Mods/`, a state file decides), so this helper does not apply there.
