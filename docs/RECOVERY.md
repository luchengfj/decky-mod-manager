# An unfinished transaction blocks the next one

`deckymod/journal.py` has always described a state machine:

```text
PREPARED -> APPLYING -> COMMITTED | ROLLED_BACK | ROLLBACK_FAILED
```

`status()` has always reported it (`pending_recovery`, `recovery_needed`), and
`errors.py` has always contained the code for it. What was missing was the part
that acts on it: **between rounds 39 and 50 no write path ever read
`journal.pending()`**, so a crash mid-operation left a transaction that the
plugin would happily write on top of.

## What the device showed before the change

Probe: `C:\ai\SD\.decky-probe\r51_pending2.py`, on a synthetic tree so the real
`Mods/` folder is untouched.

```text
BEFORE pending_recovery=[] recovery_needed=False
AFTER  pending_recovery=['20260101T000000-crash001'] recovery_needed=True
WRITE_DESPITE_PENDING ok=True code=None phase=confirm
ROLLBACK_ON_PENDING ok=True data={'recovered': True, ...}
PENDING_NOW []
```

`WRITE_DESPITE_PENDING ok=True` is the whole finding: the status said a
transaction was unfinished, and `install()` started a new one anyway.

## Why this matters and not "concurrency"

The obvious story is two RPCs racing. That is not what can be proven here:
`await` does not appear anywhere in `main.py` or `deckymod/*.py`, so every RPC
body is fully synchronous and there is no suspension point for a race to
interleave on. What *can* be proven, offline and on the device, is the
invariant the journal already documents — and an interrupted operation is
reachable without any concurrency at all (the user closes the QAM, the plugin is
disabled, the process dies).

## The gate

`deckymod/smapi.py` and `deckymod/engine.py` gained `_check_no_pending()`, called
at the top of the three destructive paths and **deliberately not** from
`rollback()`:

| Path | Gated | Why |
| --- | --- | --- |
| `_install_inner` | yes | starts a second transaction |
| `_set_enabled_inner` | yes | starts a second transaction |
| `_uninstall_inner` | yes | starts a second transaction |
| `_rollback_inner` | **no** | rollback *is* the recovery; gating it would leave a stuck journal with no exit |

Two deliberate non-failures:

- If the journal cannot be read, the gate lets the write through. A plugin that
  refuses to work because it cannot read its own log is worse than the bug it is
  trying to prevent.
- The code is `E_RECOVERY_PENDING`, already in `errors.py` with
  `rollback_available = True` and already translated in the panel
  (`ERR_E_RECOVERY_PENDING`). No 51st code was added.

## Device evidence after the change

Probe: `C:\ai\SD\.decky-probe\r51_device_probe.py`.

```text
=== A. live plugin
STATUS_OK True
A_RECOVERY_NEEDED False
A_PENDING_RECOVERY []
A_RECOVERY_RPC_OK True
A_RECOVERY_RPC_PENDING []
=== B. synthetic tree
B_STATUS_OK True
B_READ_ONLY False
B_PENDING_BEFORE []
B_RECOVERY_NEEDED_AFTER True
B_INSTALL_CODE E_RECOVERY_PENDING
B_INSTALL_DETAIL 1 unfinished transaction(s): 20260101T000000-crash001 -- use Recover / Rollback before starting a new one
B_INSTALL_ROLLBACK_OK True
B_SET_ENABLED_CODE E_RECOVERY_PENDING
B_UNINSTALL_CODE E_RECOVERY_PENDING
B_ROLLBACK_OK True
B_PENDING_AFTER_ROLLBACK []
B_INSTALL_AFTER_ROLLBACK_CODE E_INBOX_UNREADABLE
SCRATCH_REMOVED True
```

`B_INSTALL_AFTER_ROLLBACK_CODE E_INBOX_UNREADABLE` is the point of the last line:
after recovery the path is open again and fails only because the probe's zip does
not exist. The gate is not a dead end.

The live half is read-only on purpose: forging a pending transaction inside the
real journal would leave the user's plugin refusing to work until they ran a
recovery they never asked for.

## The first probe was wrong, and why that is recorded here

The first probe printed `E_PENDING_IN_STATUS None` because it looked for
`data["pending"]`. The real keys are `pending_recovery` and `recovery_needed`.
`grep -n pending` would have shown that in one second. A probe that reads the
wrong key produces a confident wrong answer, and this repository has already
paid for that mistake more than once.

## Surface

| Where | What |
| --- | --- |
| `status().pending_recovery` | the txn ids still unfinished (unchanged) |
| `status().recovery_needed` | bool (unchanged) |
| error envelope | `code = "E_RECOVERY_PENDING"`, `rollback_available = true` |
| panel | the existing Recovery button (`RECOVERY_LABEL`) lists and rolls back the txn |
| read-only RPCs | unaffected: status / history / recovery / inspect / list_inbox all still answer |

## Proven, and not proven

Proven: a forged PREPARED or APPLYING transaction makes install, enable, disable
and uninstall return `E_RECOVERY_PENDING` on the device; rollback still succeeds
and clears it; the next write is then allowed; 12 unit tests plus 607 total stay
green; the panel already had the exit.

Not proven: that two RPCs can actually overlap (no suspension point exists in the
code); that a real power loss leaves exactly this journal shape (the forged state
reproduces the state machine, not the crash); that the Recovery button itself is
reachable with a gamepad — nobody has pressed it yet.
