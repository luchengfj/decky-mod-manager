# A failed install or upgrade says what actually happened

Installing a mod is two renames. The old copy (if any) is moved into the
quarantine, then the staged copy is moved into place:

```
Mods/<dir>  ──rename──▶  .decky-quarantine/<txn>/<dir>.replaced
<staging>/<txn>/<dir>  ──rename──▶  Mods/<dir>
journal: MOD_INSTALLED → MOD_ENABLED → COMMITTED
```

Anything can fail after the first rename and before `COMMITTED`: the data
partition fills up, the archive verifies badly, the plugin data directory is on
a different, fuller filesystem. This page is about what the plugin promises in
that window.

## The two defects (measured, not imagined)

### 1. A failed upgrade silently completed itself

Round 69 was opened by pointing the probe at that window: let `journal.committed`
raise `OSError(28, "No space left on device")` -- a real disk condition, the game
partition has room and the plugin data directory does not -- after an upgrade
from 1.0.0 to 2.0.0. Verbatim from the device, before the fix:

```
A_INSTALL1 True
B_INSTALL2_OK False
B_CODE E_NO_SPACE
B_VERSION_ON_DISK 2.0.0              <-- the new version is live
B_QUARANTINE [{"txn": "...", "names": ["probe.upgradefail.replaced"]}]
C_STATUS_ROWS [{"dir": "probe.upgradefail", "uniqueId": "probe.upgradefail", "version": "2.0.0"}]
C_INSTALLED [{"pid": "probe.upgradefail", "version": "2.0.0", ...}]
D_ROLLBACK ... False E_UNKNOWN
E_VERSION_AFTER_ROLLBACKS 2.0.0
F_QUARANTINE_DIGEST {"dirs": 1, "restorable": 1, "orphans": 0, "empty": 0}
```

The user was told the upgrade failed. The disk, `status()` and
`journal.installed()` all said 2.0.0. The old 1.0.0 was in the quarantine, and
`rollback(txn)` answered `nothing to roll back for txn ... (state=ROLLED_BACK)`.
Nothing in the API could bring the old version back, and once the transaction was
recorded as rolled back the saved copy became an orphan -- a folder
`reclaim_quarantine` is explicitly allowed to delete.

The handler had one branch, written for a first install:

```python
elif os.path.isdir(install_at) and not managed:
    shutil.rmtree(install_at, ignore_errors=True)
```

An upgrade is `managed`, so this branch skipped, the transaction was recorded as
rolled back, and the replacement stayed on disk. "Failed" meant "you now have the
version you did not ask for".

### 2. The clean-up asked the journal instead of asking what it did

Even the first-install branch was wrong, because its guard was ownership rather
than action. `_existing_managed()` reads the journal. A journal row whose folder
is gone is not hypothetical:

* the user deleted the folder in the file manager;
* the microSD card or the library is not mounted this boot;
* a different tree is active than the one the record was written against.

Verbatim from the device (round 69b, its own check):

```
E2_JOURNAL_CLAIMS_IT {'packageId': 'probe.staleclaim', 'name': 'StaleClaim',
                      'version': '0.9.0', 'enabled': False,
                      'dir': '.../Mods/probe.staleclaim', 'txn': 'seed-stale'}
E2_DISK_DOES_NOT_HAVE_IT
E2_INSTALL_REFUSED E_NO_SPACE
FAIL E2_NOTHING_LEFT_BEHIND ['probe.freshfail', ...]   <-- before the fix
PASS E2_NOTHING_LEFT_BEHIND ['probe.upgradefail']      <-- after the fix
```

So the second defect is not a probe artefact: whenever the journal names a mod
the disk does not have, a **first** install is treated as an upgrade, takes the
`managed` path, and its failure leaves the half-written folder in `Mods/` where
SMAPI will try to load it.

## What the plugin promises now

| situation | what happens | what the answer says |
| --- | --- | --- |
| upgrade fails after both renames | the displaced copy is put back, the new copy is removed | `data.restored_old: true`, `data.removed_new: true` |
| upgrade fails and the restore itself fails | nothing is deleted; both copies stay | `E_ROLLBACK_FAILED`, `detail` names the restore error |
| first install fails | the copy this transaction wrote is removed | `data.restored_old: false`, `data.removed_new: true` |
| first install fails while the journal claims the mod | the same: the copy this transaction wrote is removed | `data.restored_old: false` |
| `rollback(txn)` on a failed upgrade | no longer a dead end: the `ROLLED_BACK` state is accepted when a replacement was recorded | restore, or a refusal that names its reason |

The clean-up is guarded by a flag only the write path sets:

```python
placed = False          # set immediately after os.replace(stage_dest, install_at)
...
if replaced_qdir and os.path.isdir(replaced_qdir):
    undo = upgrade.undo_install(replaced_qdir, install_at)
    ...
elif placed and os.path.isdir(install_at):
    shutil.rmtree(install_at, ignore_errors=True)
    removed_new = True
```

`placed` answers "did our bytes reach the destination", which is the only
question that matters when deciding whether to delete what is there. Ownership
is a different question, answered by a different source, and the two can
disagree -- which is exactly what round 69b measured.

Restoring keeps going through `upgrade.undo_install()`, the helper round 56
introduced: refuse rather than half-undo, and if the new copy cannot be removed,
leave both. A user with two copies can recover; a user with neither cannot.

## Evidence

* `tests/test_failed_install.py` -- 14 cases. The window is entered the same way
  the device entered it: `_break_commit()` makes `journal.committed` raise
  `OSError(28)`. Includes `test_a_journal_row_without_a_folder_does_not_skip_the_cleanup`,
  which seeds a `MOD_INSTALLED` record for a folder that does not exist.
* Negative proof (`C:\ai\SD\.decky-probe\r69b_negative_proof.py`): the cleanup is
  flipped back to `and not managed`. Exactly one case fails --
  `test_a_journal_row_without_a_folder_does_not_skip_the_cleanup` -- and the plain
  case still passes:

```
MUTATED_PLACED 0 MUTATED_BACK 0
RETURNCODE 1
   FAIL: test_a_journal_row_without_a_folder_does_not_skip_the_cleanup
FAILURE_COUNT 1
PLAIN_CASE_STILL_PASSES True
NEGATIVE_PROOF_FIRED True
```

* Device (deployed plugin, synthetic tree, real `Mods/` untouched), 21/21:

```
PASS B_INSTALL2_REFUSED E_NO_SPACE
PASS B_OLD_VERSION_STILL_ON_DISK 1.0.0
PASS B_SAYS_IT_RESTORED {"restored_old": true, "removed_new": true}
PASS C_STATUS_VERSION_IS_1 1.0.0
PASS C_JOURNAL_VERSION_IS_1 [{'version': '1.0.0', 'enabled': True, ...}]
PASS D_NO_NEW_QUARANTINE_FOLDER {'before': [], 'after': []}
PASS E_NOTHING_IN_MODS ['probe.upgradefail']
PASS E2_JOURNAL_CLAIMS_IT {...}
PASS E2_NOTHING_LEFT_BEHIND ['probe.upgradefail']
PASS F_WRITES_NOT_BLOCKED
PASS_COUNT 21 / 21
```

* Whole suite: `Ran 808 tests in 9.084s / OK (skipped=15)`, `compileall 0`,
  seven validators `RC=0`.

## What this does not claim

* The failure window is entered by making the commit step raise. No real
  full-disk was used for this round; the error code path is the same, but the
  sequence was not produced by filling a partition.
* Only `_install_inner` in the Stardew engine (`deckymod/smapi.py`) is covered.
  The RimWorld engine (`deckymod/engine.py`, `xml_list`) has the same two-rename
  shape and the same single-branch handler. It is `planned` -- not enabled on any
  device in this workspace -- so it was not touched; enabling it without doing
  this round again would be a regression.
* The probe entry point (`_break_commit`) is a test seam. The device runs used
  the deployed plugin but reached the window through that seam, not through a
  real out-of-space condition.
* The panel was never looked at by a human in Game Mode this round. All backend
  behaviour above is backend behaviour; the QAM wording for these two codes has
  not been read on a screen.
* A restore that fails leaves both copies in place by design. There is no
  automatic retry and no background reconciliation -- the next `rollback(txn)`
  is the retry, and if the cause is still there it will refuse again.
