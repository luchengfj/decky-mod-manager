# Undoing an uninstall, honestly

Round 65. Found on the device with a synthetic Steam tree, the same way rounds
56-60 were found: take a basic operation nobody had ever exercised, run it
against the real deployed plugin, and read the answer instead of reading the
code.

## The operation

`rollback(txn)` is the plugin's undo. For an uninstall it is the only way back:
`uninstall` moves the folder into the quarantine and refuses to delete anything,
so the bytes are still there and the rollback is supposed to put them back where
they were.

## What it used to do

```python
if os.path.isdir(qdir) and not os.path.isdir(src):
    os.replace(qdir, src)
... journal.record("MOD_ROLLBACK_RESTORED", ...) ...
... journal.committed(txn, {"rollback_of": "uninstall"}) ...
```

Both halves of that guard fail silently, and the bookkeeping ran either way:

| Situation | What is on disk | Answer given |
| --- | --- | --- |
| the user reinstalled the mod after uninstalling it | the user's newer version | `ok:True`, `restored: 'probe.reinstall'` |
| the quarantined copy was cleaned up | nothing | `ok:True`, `restored: 'probe.reinstall'` |

Measured, not inferred (`r65_rollback_uninstall_probe.py`, deployed plugin):

```
D_VERSION_AFTER        '9.9.9'             # the user's reinstall
D_SAYS_RESTORED        'probe.reinstall'
D_RESTORED_THE_OLD_ONE False

E_QDIR_REMOVED         True                # the saved copy was gone
E_MODS_AFTER           []
E_SAYS_RESTORED        'probe.reinstall'   # and it still said "restored"
E_ACTUALLY_RESTORED    False
```

## Why it mattered twice

The first harm is the obvious one: the user is told a mod came back when it did
not, and in the first case a **different version** is what is actually on disk.
Anyone reasoning from the plugin's own answer would conclude their mods are fine.

The second harm is worse and less visible. `MOD_ROLLBACK_RESTORED` was written
regardless, so the journal considered the transaction finished. The quarantined
bytes were then owned by nobody -- an orphan -- and round 54 added
`reclaim_quarantine`, which is *allowed to delete orphans*. A false success
therefore hands real user data to the deleter: the user's only copy of the old
version disappears after a message saying it had been restored.

The RimWorld engine (`deckymod/engine.py`) carried the same line. There it is
worse, because the rollback also rewrites `ModsConfig.xml` from the snapshot, so
the game is told to load a folder that does not exist. That path is unreachable
from the panel today (Stardew is the enabled game) -- round 57 is the case study
for how much "unreachable today" is worth.

## What it does now

Three refusals before anything is touched, in both engines:

| Condition | Code | Why this one |
| --- | --- | --- |
| the saved copy is not there any more | `E_MOD_NOT_FOUND` | there is nothing to restore |
| the restore target became a symbolic link | `E_PATH_INVALID` | `os.replace` would replace the link, not what it points at |
| the target exists again | `E_FILE_COLLISION` | something else is there now; overwriting it destroys the user's newer file |

No new error codes: all three already existed and are already translated, so
`errors.py` stays at 52 and the i18n dictionaries stay in step. The guard order
is pinned by a test -- the refusals are computed *before*
`journal.record("MOD_ROLLBACK_RESTORED")`, because the defect was precisely a
decision taken after the success had already been written down.

## A second defect the fix exposed

With the refusals in place the plain case still left litter:

```
TXN_DIR_EXISTS_AFTER_ROLLBACK True
TXN_DIR_CONTENTS              []
```

`os.replace(qdir, src)` empties the transaction folder but does not remove it, so
every undone uninstall deposits one empty directory in the quarantine. Round 54
counts quarantine directories, classifies unreferenced ones as orphans, and
offers orphans for deletion; round 56 met the same thing on the upgrade path and
cleared it with `os.rmdir(os.path.dirname(replaced_old))`. That one line now
runs on the uninstall-undo path in both engines. `os.rmdir` refuses a non-empty
directory, which is the guard we want: if the transaction folder still holds
anything, nothing is removed.

## Evidence

Local: `Ran 765 tests / OK (skipped=15)`, `compileall` 0, all seven validators
exit 0.

Deck, after building and deploying: `TSC_EXIT=0`, `ROLLUP_EXIT=0`,
`Ran 765 tests / OK (skipped=1)`, `MODULE_FILES=35 BUILD_MODULES=35`,
`COPIED=2 VERIFY_FAIL=0`, live `status()` `MOD_COUNT 30` with the real `Mods/`
untouched.

Device probe against the deployed plugin (`r65_device_probe.py`, 18/18):

```
A_INSTALL_OK True / A_UNINSTALL_OK True / A_ROLLBACK_OK True
A_VERSION_RESTORED '1.0.0' / A_TXN_FOLDER_GONE False

D_ROLLBACK_OK False / D_CODE 'E_FILE_COLLISION'
D_SAYS_ALREADY_EXISTS True / D_DID_NOT_OVERWRITE '2.0.0'

E_ROLLBACK_OK False / E_CODE 'E_MOD_NOT_FOUND' / E_MODS_EMPTY []

F_FIRST_REFUSED False / F_COPY_STILL_THERE True
F_SECOND_SUCCEEDS True / F_OLD_VERSION_BACK '1.0.0'

PASS_COUNT 18 CHECK_COUNT 18
```

Negative proof (`r65_negative_proof.py`): copy the tree, restore the exact
pre-round-65 guard, drop the rmdir cleanup, run the new tests. A negative proof
only counts if the tests fail for the behaviour they describe, so the script
reports the plain case separately:

```
PLAIN_CASE_STILL_PASSES True
FAILURE_COUNT 7
  test_a_refused_rollback_does_not_erase_the_transaction
  test_no_event_is_recorded_when_it_refuses
  test_the_folder_came_back_while_undone
  test_the_saved_copy_is_gone
  test_the_quarantine_folder_is_gone_afterwards
  test_the_engine_has_the_same_three_refusals
  test_both_engines_check_before_recording
NEGATIVE_PROOF_FIRED True
```

The first version of that mutation left a duplicate `os.replace(qdir, src)`
behind, which made the *plain* case fail with `E_OP_FAILED` ("the system cannot
find the file specified"). That failure was caused by the mutation, not by the
behaviour under test, so it proved nothing -- hence the separate check.

## What this does not claim

* It is not a guarantee that a rollback always succeeds. It guarantees that one
  which cannot succeed says so instead of reporting success.
* The symlink refusal is skipped on this Windows box (no symlink privilege,
  `WinError 1314`); it runs on the Deck. The Deck run showed that a symlinked
  entry under `Mods/` is caught slightly earlier by round 44's structural
  second-writer gate, so the answer there is `E_EXTERNAL_MANAGER` rather than
  `E_PATH_INVALID`; both are refusals and neither writes through the link, which
  is the property the test pins.
* The panel was not opened by a person in Game Mode. Everything here is about the
  RPC layer, measured on a synthetic tree -- not the real `Mods/` directory.
