# A failed rollback is not the end of the road

## The operation

The user presses **A** on a row in the recovery panel after a modification
reported `E_ROLLBACK_FAILED`. The repair is two-phase: the first press shows a
confirmation, the second actually retries the restore. Nothing moves on the
first press.

Before this change, `E_ROLLBACK_FAILED` was a dead end with a misleading
promise. `errors.py` describes it as "Your data is preserved in the quarantine
folder; see the log" and marks it `rollback_available=True`, but:

- `rollback(txn)` answered `E_UNKNOWN "nothing to roll back for txn … (state=ROLLBACK_FAILED)"`;
- `recovery()` listed only `pending()` (PREPARED/APPLYING), so a failed rollback
  did not even appear as something that could be retried;
- the audit called the folder `restorable: true`, so three parts of the plugin
  disagreed about whether anything could still be done.

## The state the repair has to understand

A `ROLLBACK_FAILED` transaction is neither healthy nor pending. Its directory
holds the displaced copy — that is *why* the rollback failed — but the journal
will not let the normal path touch it again:

- `journal.pending()` is PREPARED/APPLYING; folding ROLLBACK_FAILED into it
  would block **every other write** forever (a stuck transaction is not a live
  one).
- `journal.installed()` rebuilds ownership from `MOD_ROLLBACK_RESTORED`; a
  failed rollback records none, so the plugin does not claim the mod.
- `quarantine.survey()` used to mark the folder `orphan` unless an
  `MOD_UNINSTALLED` record claimed it, which would let `reclaim_quarantine`
  delete the user's only remaining copy.

## Device evidence (before the fix)

`C:\ai\SD\.decky-probe\r72_rollback_failed_probe.py`, 12/12 checks on the
deployed plugin, synthetic tree under `/tmp/r72_*` — the real `Mods/` (30 mods)
was never touched:

```
B_INSTALL2 {"ok":false,"code":"E_ROLLBACK_FAILED",
            "detail":"install failed ([Errno 28] No space left on device) and the
                      previous copy could not be restored: restore refused for this probe"}
D_RECOVERY_DATA {"pending":[],"log_path":…}
E_QUARANTINE_ENTRY [{"state":"restorable","restorable":true,
                     "names":["probe.rbf.replaced"]}]
F_ROLLBACK {"ok":false,"code":"E_UNKNOWN",
            "detail":"nothing to roll back for txn … (state=ROLLBACK_FAILED)"}
```

A second probe, `C:\ai\SD\.decky-probe\r72_device_probe.py`, initially returned
20/22. The two failures were real, not harness noise:

- `H_REFUSES_HONESTLY` / `H_NAMES_THE_FOLDER`: a stuck transaction whose
  `.replaced` folder had been removed fell through to the Round 68 "nothing was
  displaced → mark recovered" fallback and answered `ok({recovered: true})` —
  the same lie Round 68 removed from a different branch, one level down.

## What changed

Four small decisions, each in one place:

1. **`smapi.py::_rollback_inner`** — the committed-upgrade branch accepts
   `ROLLBACK_FAILED`, and a *standalone* `if state == "ROLLBACK_FAILED":`
   branch owns the retry. With a saved copy it restores and records; with no
   copy it raises `E_ROLLBACK_FAILED "…there is no copy left to restore; the
   quarantine folder is at …"`. It never reports `recovered: true`.
2. **`journal.py::stuck()`** lists ROLLBACK_FAILED separately from
   `pending()`. A stuck transaction is *visible and retryable* without
   freezing every other write. `pending()` is unchanged.
3. **`quarantine.py::referenced_txns()`** counts a ROLLBACK_FAILED transaction
   as owning its quarantine folder, so the audit reports `restorable`, not
   `orphan`, and reclaim cannot delete it.
4. **`smapi.py::recovery()`** returns `{"pending": [...], "stuck": [...], ...}`;
   the frontend renders stuck rows with a distinct description
   (`RECOVERY_STUCK_SUB`) and the same confirm-then-retry action.

Because three branches now had to do the same restore, they share one helper —
`smapi.py::_restore_displaced(txn, saved, target, pid, name=None, version=None,
*, error_detail=...)`. It is the single place that calls `upgrade.undo_install`
on the rollback side, reads the folder's real identity (`_read_dir_identity`),
and records `MOD_ROLLBACK_RESTORED`. Adding a fourth branch must not add a
fourth copy of those decisions.

## Checks

- New `tests/test_stuck_rollback.py` — 10 cases: retry succeeds with a saved
  copy; without one it refuses and names the folder; a stuck txn does not block
  writes; `recovery()` lists it; the audit marks its folder restorable; and
  structural assertions pin the helper (one `undo_install`, one identity read,
  three callers).
- Negative proof `C:\ai\SD\.decky-probe\r72_negative_proof.py`: M1 disables the
  standalone stuck branch (5 fails), M2 folds `stuck()` into the write gate
  (3 fails); the ordinary cases still pass under both mutations.
- Full local suite: `Ran 841 tests ... OK (skipped=15)`, `compileall` 0, seven
  validators exit 0, sync tar 123/123 (drift 0).
- Final Deck build of the committed tree: `TSC_EXIT=0 / ROLLUP_EXIT=0`,
  `Ran 841 tests in 4.600s OK (skipped=1)`, deployed via the enumerated
  `r52_deploy.sh` (`COPIED=1 VERIFY_FAIL=0`, `DIST_SHA=b9174423…` matching).
  Artifact: `DeckyModManager-0.1.0-mvp.zip` 318505 B /
  `13948dddf579bf315ca9b3dc9a393ffd0e60edb88e7e5da953d7ad562d272474`.

### Device evidence (after the fix)

`C:\ai\SD\.decky-probe\r72_device_probe.py` re-run on the deployed plugin,
synthetic tree under `/tmp/r72dev_*` — the real `Mods/` (30 mods) untouched.
**22/22 PASS**, including the two earlier failures:

```
PASS F_ROLLBACK_OK
PASS F_OLD_VERSION_BACK  1.0.0
PASS F_CONTAINER_GONE  /tmp/r72dev_3385531b/…/.decky-quarantine/20260101T000000-stuck072
PASS G_ROW_VERSION_IS_OLD  1.0.0
PASS H_REFUSES_HONESTLY  E_ROLLBACK_FAILED
PASS H_NOT_NOTHING_TO_ROLL_BACK  the automatic rollback for txn … did not finish and
                                 there is no copy left to restore; the quarantine
                                 folder is at /tmp/r72dev_3385531b/…/…stuck073
PASS H_NAMES_THE_FOLDER  (same detail names the exact quarantine folder)
PASS I_JSON_SAFE
PASS_COUNT 22 / 22
VERDICT_FAILED_ROLLBACK_IS_NOT_A_DEAD_END True
```

## What this does not claim

- The retry was driven through a synthetic tree on the real device. No real
  filesystem failure was induced on a user's installed mod: the stuck state was
  entered through a test seam (`journal.committed` raising `OSError(28)`), like
  every other failure-path check in this project.
- Only the Stardew `file_drop` engine is affected. `engine.py` (RimWorld
  `xml_list`, planned) has the same shape and was intentionally left alone.
- The panel has not been seen by a human in Game Mode; all UI claims come from
  DOM text, not visual inspection.
