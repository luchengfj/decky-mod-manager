# Upgrading a mod, and undoing it

Round 56. The plugin has always been able to import a newer ZIP over an
installed mod. This page is about what happens to the version that got
overwritten, and about a defect in that path that lived for about twenty rounds
before anything looked at it.

## What an upgrade does

`_install_inner` in both engines, on the replace path:

1. stages the new ZIP in `.decky-staging/<txn>`;
2. **moves the installed directory into the quarantine** at
   `.decky-quarantine/<txn>/<id>.replaced` -- never deleting it;
3. records `MOD_INSTALLED` with `replaced_old` pointing at step 2;
4. renames the staged copy into `Mods/<id>`.

Step 2 and step 3 exist precisely so the operation is reversible. That was the
intent from the beginning.

## The defect

Nothing read `replaced_old`. `replaced_old` appeared exactly once in each
engine, as the keyword argument of the `journal.record` call that wrote it.

Measured on the device, with a 1.0.0 ZIP installed and then a 2.0.0 ZIP
installed over it:

```
V1_VERSION_ON_DISK         1.0.0
V2_VERSION_ON_DISK         2.0.0
RECORDED_REPLACED_OLD      .../.decky-quarantine/20261117T183305-86d7c8c8/someone.upgrademe.replaced
REPLACED_EXISTS            True
ROLLBACK_OK                False
ROLLBACK_CODE              E_UNKNOWN
ROLLBACK_DETAIL            nothing to roll back for txn 20261117T183305-86d7c8c8 (state=COMMITTED)
VERSION_AFTER_ROLLBACK     2.0.0
QUARANTINE_ORPHANS         [["20261117T183305-86d7c8c8", 219]]
OLD_VERSION_DELETABLE      True
```

Three separate harms from one missing branch:

1. **The rollback was refused.** `_rollback_inner` knew three cases --
   `MOD_UNINSTALLED`, `MODS_HANDOVER`, and an unfinished `PREPARED`/`APPLYING`
   transaction -- and an upgrade matched none of them, so it fell through to
   `nothing to roll back for txn ... (state=COMMITTED)`.
2. **The new version stayed on disk.** A refused rollback at least does no
   harm, so this was the "safe" half.
3. **The old version became litter.** With no journal event referencing it, the
   `.replaced` folder was reported as an **orphan** -- and Round 54, twenty
   rounds of careful work later, added `reclaim_quarantine`, which is allowed to
   delete orphans after a two-phase confirmation. So the plugin was one user
   click away from permanently deleting the only copy of the version the user
   was trying to get back to.

That is the general shape worth remembering: **two features that are each
individually correct can combine into data loss.** Round 54 audited the
quarantine honestly and found orphans; Round 56 found that one class of those
orphans should never have been orphans.

## The fix

One new branch in each engine's `_rollback_inner`, sharing one module so the two
cannot drift:

```python
inst = next((e for e in events
             if e.get("event") == "MOD_INSTALLED" and e.get("replaced_old")), None)
if inst and state in ("COMMITTED", "APPLYING", "PREPARED"):
    got = upgrade.undo_install(inst.get("replaced_old"), inst.get("dir"))
    if not got.get("ok"):
        raise ModError(got.get("code") or "E_OP_FAILED", detail=got.get("detail"))
    self.journal.record("MOD_ROLLBACK_RESTORED", txn, ...)
    self.journal.committed(txn, {"rollback_of": "upgrade", ...})
    return ok({...})
```

`deckymod/upgrade.py::undo_install(replaced_old, target, *, mover=None)` does the
work, and refuses in four situations:

| situation | answer | why not guess |
|---|---|---|
| no `replaced_old` recorded | `E_UNKNOWN` "no replaced copy" | a plain first install has nothing to undo; saying so is not an error |
| the source left the quarantine | `E_UNKNOWN` "no longer in the quarantine" | someone may have reclaimed it; the new copy stays untouched |
| the source is a symlink, or not a directory | `E_UNKNOWN` | whatever it points at is not the version we displaced |
| the destination became a symlink | `E_PATH_INVALID` | `shutil.move` would shadow the link rather than replace it, and the thing it points at is not ours |
| the destination is `.`/`..`/empty basename | `E_PATH_INVALID` | checked on the **raw** trailing component, because `os.path.normpath("a/b/..")` erases the `..` -- the first version of this guard did exactly that and a test caught it |

After a successful move it calls `os.rmdir` on the transaction folder. `rmdir`
refuses a non-empty directory, which is exactly the guard wanted: the emptied
folder is litter, and Round 54 taught us that litter in the quarantine gets
counted, shown, and eventually offered for deletion.

It deliberately **does not delete the new copy if the destination cannot be
freed**. A half-finished rollback leaves the user with neither version;
"nothing happened, here is why" is always recoverable, "half happened" is not.

## Device evidence, after the fix

Same probe, same synthetic tree, only the code changed:

```
ROLLBACK_OK                True
ROLLBACK_CODE              None
VERSION_AFTER_ROLLBACK     1.0.0
QUARANTINE_ORPHANS         []
OLD_VERSION_DELETABLE      False
```

`OLD_VERSION_DELETABLE False` is the one that matters most: the old version is
no longer offered up as garbage, because it is no longer garbage -- it is on
disk, where the user asked for it.

## Bounds

| bound | value | why |
|---|---|---|
| new error codes | 0 | `E_UNKNOWN`, `E_PATH_INVALID`, `E_OP_FAILED` already describe all five refusals |
| new RPCs | 0 | rollback already existed; it just answered a question it had the data for |
| new modules | 1 (`upgrade.py`) | shared so the two engines cannot diverge |
| branches added per engine | 1 | the third case, in the same shape as the other two |

## What is proven, and what is not

Proven on the device: a 1.0.0 -> 2.0.0 upgrade, then `rollback`, puts 1.0.0 back
on disk, empties the quarantine of that transaction, and leaves nothing
deletable. A second rollback of the same transaction is refused rather than
faked. A plain first install still answers "nothing to roll back" and does not
damage the installed copy.

Not proven: the RimWorld engine's branch is covered by the same module and
compiles, but the RimWorld path cannot be exercised here (no RimWorld install);
the panel has still never had a human press its Rollback button on a real
upgrade; and nothing prevents a future round from adding a fourth case that
forgets this one -- the only guard is the test in `tests/test_upgrade.py`.
