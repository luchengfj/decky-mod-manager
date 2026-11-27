# Handing `Mods/` over from another mod manager

Round 44 taught the engine to refuse writing into a folder somebody else owns.
Round 53 made the *names* of that other manager's markers come from the game
descriptor instead of being hard-coded. Both were correct and both left the
same hole: a user who has never heard of the other manager sees "read-only"
everywhere and concludes this plugin is broken. Refusing without offering an
exit is a dead end, and a dead end is a reason to stop using the plugin.

Round 55 adds the next sentence: **one button that hands the folder over,
without deleting anything.**

## What other managers actually leave behind

Measured on the device (`docs/DECLARED_VS_READ.md` has the marker survey):

| what it is | where it lives | why it is safe to move |
| --- | --- | --- |
| marker file (0 bytes) | inside `Mods/` | bookkeeping. Moving it is the whole change of ownership |
| symlinked entry | inside `Mods/` | a pointer. The real directory stays exactly where it is |
| deployed mod tree | a *directory* beside the game (e.g. `Mods_Core/`) | **not moved** — see the refusals below |
| `Mods/` itself as a symlink | the game root | **not moved** — see the refusals below |

## The two-phase conversation

`handover_mods(after_confirm=False)` only *looks*:

```
phase      confirm
confirm_text  Move 2 deployment entr(y/ies) out of Mods/ into the quarantine?
              This plugin will then own the folder; Rollback puts them back.
confirm_key   CONFIRM_HANDOVER
```

Nothing on disk changes — the device probe prints `B_ZERO_WRITE True` for
exactly this reason. `after_confirm=True` is a genuine second call, and only
then do the entries move.

## What the operation refuses to do

The whole operation is refused — moving **nothing** — when the obstacle cannot
be undone in one step. A half-done handover would leave the other manager's
deployment partly dismantled *and* the folder still unmanaged, which is the
worst of both states.

| refusal | why it is not attempted |
| --- | --- |
| `mods_dir_is_symlink` (`Mods/` itself is a link) | moving the link leaves `Mods/` missing while the other tool still believes it is deployed |
| `marker_beside_game` (a marker **directory** next to the game) | that is where the deployed files actually live; replacing them is not a rename |
| `mods_on_other_device` | `os.replace` across filesystems raises `EXDEV`; a copy would not be atomic and could be partial |
| no marker declared in the descriptor | this operation moves things, so an inherited default is not consent. No declaration means no action |

## Reversibility

`Rollback` restores the transaction: `_rollback_inner` in both engines reads the
`MODS_HANDOVER` event and calls `handover.restore()`, which puts each entry back
and **refuses to overwrite** anything that appeared at the destination in the
meantime (`something else is at the destination now`). That refusal matters:
between the handover and the rollback the user may have re-deployed with the
other tool, and that deployment is not ours to discard.

The device probe proves the round trip end to end:

```
B_READ_ONLY_BEFORE   True
B_ZERO_WRITE         True
B_MOVED              ["LinkedMod", ".mm_deployed"]
B_READ_ONLY_AFTER    False
B_ROLLBACK_OK        True
B_RESTORED           handover
B_BACK_MOVED         ["LinkedMod", ".mm_deployed"]
B_MARKER_BACK        True
B_LINK_BACK          True
B_READ_ONLY_RESTORED True
```

`B_LINK_BACK True` is a real symbolic link created and restored on the device,
not a mock. On Windows those cases are skipped (`WinError 1314`) — which is
precisely why the Linux run is the one that counts.

## The one write path that does not consult the ownership gate

`_handover_inner` deliberately does **not** call `_check_write_allowed`: the
external-manager refusal is the thing this operation exists to clear, so gating
on it would make the operation unreachable in every situation that needs it.
The narrower gates still run — not-running, no-pending-transaction, and the
capability gate — and the tests assert that.

Rollback has the same problem from the other side. It *does* run the gate, and
swallows exactly one code (`E_EXTERNAL_MANAGER`) and only when the transaction
being undone is a handover. Everything else still refuses. This keeps the
contract the rest of the plugin relies on: a foreign tree answers **every**
write with `E_EXTERNAL_MANAGER`, so the panel explains one reason instead of
three. The order is also load-bearing — the gate runs before the "unknown
transaction" check, because a mistyped transaction id must not make one device
look like a different class of problem than another.

## Bounds

| bound | value | why |
| --- | --- | --- |
| entries moved per call | all movable entries (the survey is bounded by the folder listing itself) | the operation is a whole-folder act, not a per-file one |
| new error codes | 0 | reuses `E_CAPABILITY_DISABLED`, `E_PATH_INVALID`, `E_EXTERNAL_MANAGER`, `E_GAME_RUNNING`, `E_RECOVERY_PENDING` |
| new RPCs | 1 (`handover_mods`) | public RPC count 27 → 28 (37 after Round 82's `check_mod_updates`) |
| scheduled or automatic runs | none | it is only ever a user action plus a confirm |

## Round 81: a game whose mods are not one folder

Everything above describes the `file_drop` engine, where a mod *is* a directory
inside `Mods/`. `RootMergeEngine` (Cyberpunk 2077, and every user-configured
game) has no such folder: files land in `archive/pc/mod`, `mods`,
`bin/x64/plugins`, `r6/scripts` and `red4ext`, routed per file by `_route()`.
It inherited the round-44 *refusal* but not the round-55 *exit* —
`handover_mods` answered `E_CAPABILITY_DISABLED / "handover is not implemented
for this game"` — so exactly the users who need it most had no way forward.

The fix is one hook rather than a second implementation:

```python
def _handover_roots(self, r) -> list:
    return [r.mod_root]            # FileDropEngine: exactly one folder
```

`RootMergeEngine` overrides it with every declared write root, resolved to an
absolute path (absolute because `handover.survey()` compares `st_dev` against
`game_root` and calls `os.lstat()` on each). `_handover_inner` then surveys
**every** root before deciding anything, and refuses as a whole if any one of
them cannot be undone in one step — half a takeover leaves the other manager's
deployment partly dismantled with nothing gained.

Two details exist only because a single folder was the old assumption:

- **Each root gets its own quarantine subfolder**, named by `_slug()` from the
  absolute path, so two roots with the same basename cannot collide. A
  one-folder game keeps the historical `<quarantine>/<txn>/<name>` layout byte
  for byte — tested, because gaining a nesting level would silently change
  where every existing user's quarantine lives.
- **Each root gets its own journal event.** The rollback block used to take
  `next(...)` — the first `MODS_HANDOVER` it found — which restored the first
  folder and abandoned the rest in the quarantine with no record that they
  were ever meant to come back. It now replays all of them, and names a failure
  `<from_path>: <name>` only when there was more than one root (a single root
  keeps the bare name so the historical tests and any recovered journal still
  read the same).

`tests/test_handover_multiroot.py` (19 cases) drives a synthetic two-root game.
The negative proof is deliberate: narrowing the replay back to `hands[:1]`
makes exactly one test fail with `second root was not restored`.

**Still not covered:** a root that is itself a symlink blocks the whole
operation (correct — the plugin cannot take apart a deployment it cannot see),
and no real Cyberpunk install has been used for a sign-off.

## What is proven, and what is not

Proven on the device (synthetic tree, real engine, real symlink):

- the panel's read-only state flips to false after the handover and back after
  rollback;
- the confirm phase writes nothing;
- a marker file and a symlinked entry both move, and both come back;
- the real `Mods/` folder on this device is untouched: `A_READ_ONLY False`,
  `A_MARKERS []`, and `handover_mods` answers `nothing to hand over`, because
  nothing here is deployed by another manager any more.

Not proven:

- a handover on a machine where `Mods_Core/` really exists — the refusal path is
  tested (`marker_beside_game` is refused as a whole), but no device here has
  that layout any more;
- the panel button has never been pressed with a gamepad. The DOM proves the
  handler is wired; only a human pressing `⋯` → the button proves the D-pad
  reaches it;
- a handover interrupted mid-move (SIGKILL between two `os.replace` calls) is
  covered by the pending-transaction gate and rollback, but has not been
  triggered on the device.
