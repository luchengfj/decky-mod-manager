# Crash recovery: an interrupted install must put the old copy back

Round 68. `_install_inner` moves the previous copy into the transaction's
quarantine folder and only then unpacks the new one. Between those two renames
the mod **does not exist** in `Mods/` -- the user's only copy is sitting in
`<quarantine>/<txn>/<dir>.replaced`.

A crash in that window (OOM kill, sleep/resume, power, the user pulling the
microSD) leaves exactly that state, and the journal holds nothing but
`PREPARED`/`APPLYING`.

## What was measured, verbatim

On the deployed build, before this round:

```
CRASH_STATE_MODS          []
CRASH_STATE_Q             ["probe.crashy.replaced"]
BLOCKED_CODE              E_RECOVERY_PENDING        (correct)
PENDING                   ["20260101T120000-crash068"]
ROLLBACK_OK               True
DATA                      {"recovered": true, "txn": "..."}
MOD_BACK_AFTER_ROLLBACK   False                     <-- the defect
QUARANTINE                state "orphan", restorable false
```

Three things were already right: the write gate refused every other operation
while the transaction was pending, `recovery()` listed it, and `status()`
reported `read_only` correctly. One thing was wrong, and it was the one that
matters: **the recovery step answered "recovered" while the mod stayed
missing.**

The second probe showed the same folder from the other side. After a
*successful, committed* upgrade, `rollback(txn)` restores the old version --
measured, `VERSION_AFTER_ROLLBACK 1.0.0` -- and yet:

```
THIS_TXN_STATE            orphan
VERDICT_AUDIT_DISAGREES_WITH_ROLLBACK  True
```

So two features disagreed about one folder: rollback says "this is what I will
put back", the audit says "nobody claims this, it is litter", and
`reclaim_quarantine` is allowed to delete litter.

## Why both halves are the same bug

The code knew two ways a quarantine folder could matter: an uninstall
(`MOD_UNINSTALLED` records the source path) and a handover. A *displaced copy*
-- the thing an install or upgrade leaves behind -- was never a case the
rollback path considered when the transaction had not committed.

The audit then had the same blind spot from the other side: it counted
`MOD_UNINSTALLED` rows only, so every displaced copy looked unclaimed.

Fixing one without the other would have been worse than fixing neither: a
rollback that restores the copy, next to an audit that offers to delete it.

## The fix

`deckymod/smapi.py`, `_replaced_copy_for(txn)`:

```python
root = os.path.join(self._resolve().quarantine_root, txn)
names = sorted(os.listdir(root))
cands = [os.path.join(root, n) for n in names if n.endswith(".replaced")]
cands = [c for c in cands if os.path.isdir(c) and not os.path.islink(c)]
return cands[0] if len(cands) == 1 else None
```

Only that exact suffix, only one candidate. Guessing between two would be
picking which version of the user's mod to put back, which is not a decision to
make silently.

The `PREPARED`/`APPLYING` branch of `_rollback_inner` now asks for that copy
first, and goes through `upgrade.undo_install()` -- the same function the
committed-upgrade path uses, so both routes refuse identically:

- no copy recorded and none on disk -> mark recovered, and say so without
  claiming a restore;
- copy present -> restore it, record `MOD_ROLLBACK_RESTORED` with
  `restored_from`, then mark the transaction rolled back;
- copy present but the destination cannot be freed -> `E_OP_FAILED`, refuse.

`deckymod/quarantine.py`, `referenced_txns()`: an install row counts only when
it actually displaced something (`replaced_old`), and a **pending** transaction
claims its folder too -- because a crash mid-install never wrote
`MOD_INSTALLED`, so no record names the copy even though rollback will use it.

## What it changes on the device

| | before | after |
|---|---|---|
| `rollback(txn)` after a crash | `ok`, `{"recovered": true}` | `ok`, `{"recovered": true, "restored_from": ...}`, **copy back** |
| mod on disk | absent | `1.0.0`, the version the user had |
| quarantine entry while pending | `orphan`, `restorable: false` | `restorable`, so `reclaim_quarantine` refuses it |
| transaction folder afterwards | left behind | removed (`rmdir`, refuses if non-empty) |
| writes afterwards | unblocked by the rollback | unblocked, verified by a following install |

The audit change is visible on the real device too. With the real journal
(143 rows, 16 `MOD_UNINSTALLED`) the survey still reports
`DIRS 45 RESTORABLE 16 ORPHANS 29` -- the same numbers as before the round,
because none of the existing folders is a displaced copy. The 29 orphans are
genuinely unreachable (probe installs whose journal rows are gone), and the fix
does not reclassify them.

## Evidence

- New tests `tests/test_crash_recovery.py` (9 cases): the copy comes back, the
  transaction folder is cleaned up, a second recovery is refused rather than
  faked, "nothing to restore" still answers honestly, and both halves read the
  same record.
- One existing test had to be **rewritten, not deleted**:
  `test_the_displaced_copy_is_no_longer_an_orphan` (round 56) asserted
  `before["orphans"] >= 1` -- it *required* the defect. It is now
  `test_the_displaced_copy_is_restorable_not_an_orphan`, with the old assertion
  quoted in its docstring so the change is auditable. **A test that requires a
  defect is worse than no test, because it makes the fix look like a
  regression.**
- Negative proof, each mutation verified separately and the plain case checked
  each time (`NEGATIVE_PROOF_FIRED True`):
  - M1 revert the audit to `MOD_UNINSTALLED` only -> 1 failure,
    `M1_PLAIN_CASE_STILL_PASSES True`;
  - M2 remove the restore from the pending branch -> 4 failures,
    `M2_PLAIN_CASE_STILL_PASSES True`.
- Local suite: `Ran 794 tests, OK (skipped=15)`; `compileall` 0; all 7 validators
  exit 0 (`r4_tar_drift` 118/118 after re-tarring).
- Deck build: `TSC_EXIT=0`, `ROLLUP_EXIT=0`,
  `DIST_SHA=5108f3e70a37f7171c5cd6d6c97eca91c7f97e37e315804a387e267df907eb88`
  (unchanged -- no frontend edit this round), `Ran 794 tests ... OK (skipped=1)`.
- Deployed and re-probed on the device: `PASS_COUNT 15 / 15`,
  `VERDICT_CRASH_RECOVERY_RESTORES True`, including
  `C_AUDIT_SAYS_RESTORABLE`, `G_VERSION_RESTORED` and `H_FOLDER_GONE`.

## What this does not claim

- **No real crash was induced.** The window was forged by driving the plugin's
  own `journal.begin/applying` and then moving the folder, which produces the
  same on-disk state a crash would. A SIGKILL between the two `os.replace`
  calls is still not something this session has actually performed.
- Only the **one** copy shape `_install_inner` produces is handled. A crash
  between `journal.begin` and the extract (nothing displaced yet) leaves nothing
  to restore, and that path returns `recovered` without a restore -- correct,
  but it means "recovered" is not synonymous with "something was put back".
- `engine.py` (the RimWorld `xml_list` engine) has the same two-rename window
  and its own rollback branch; this round changed only the file-drop engine,
  because only Stardew is enabled. The gap is real and is recorded, not fixed.
- The panel has still never been looked at by a person in Game Mode, so nothing
  here is a claim about what the recovery screen looks like. All of it is
  measured through the plugin's own API and the journal on disk.
- The 29 real orphans on the device are untouched: this round changes *who may
  count as an orphan*, not what already is one.
