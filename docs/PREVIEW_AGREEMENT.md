# The preview must agree with the execute

`inspect()` is not a diagnostic. It is the source of the confirm dialog: the
button the user presses is the button that submits the text `inspect()` returned.
If the two disagree, the user consented to a sentence about an operation that
did not happen.

## How the disagreement was found

Rounds 57 and 58 were the same defect shape twice. In the file_drop engine a mod
is disabled by MOVING ITS FOLDER into `.decky-disabled/`, so `install == enable`
because the location is the state. Two code paths resolved `Mods/` only and got
it wrong; both were found by hand, one round apart.

Round 59 stopped waiting for the third. A scanner (`r59_root_audit.py`) walks
every function in both engines and reports which of the root attributes it
mentions:

```
TOTAL_FUNCS_WITH_ROOTS 19
BOTH_ROOTS 4
MOD_ONLY 9
```

Nine functions mention `Mods/` and never mention the disabled root. Most of them
are legitimate -- `engine.py` is the RimWorld engine, where every mod stays in
`Mods/` and the state file decides, so a parked root does not exist there at
all. Filtering those out left two entries in `smapi.py`: `_check_write_allowed`
and `_probe`, both of which call `modwatch.survey(game_root, mod_root)` -- that
survey is about ownership of the tree, not about parked mods, so they are
correct as they are.

And `inspect()`, which was not.

## What it did

```
PREVIEW_TARGET        .../Steam/steamapps/common/Stardew Valley/Mods/someone.parkinspect
PREVIEW_CONFIRM_TEXT  'Install Park Inspect to .../Mods/someone.parkinspect (file_drop: install == enable)'
PREVIEW_DUPLICATE     True
PREVIEW_SAME_UID_DIRS []
REAL_DIR              .../Steam/steamapps/common/Stardew Valley/.decky-disabled/someone.parkinspect
PREVIEW_MATCHES_REAL  False
```

Three separate statements in one dialog were wrong or incomplete:

| the dialog said | the truth |
|---|---|
| it will go to `Mods/someone.parkinspect` | it goes to `.decky-disabled/someone.parkinspect` |
| nothing about the mod staying disabled | it stays disabled, which is why the path differs |
| no same-UniqueID conflict | install would have counted a parked copy |

The third one is the subtle one. `_install_inner` refuses a conflicting
same-UniqueID copy in either root, so the preview's `same_unique_id_dirs` was
incomplete -- the user could press Install, get `E_DUPLICATE`, and have seen no
warning.

## The fix

`inspect()` now computes the destination the same way `_install_inner` does:

```python
parked_target = os.path.join(r.disabled_root, dn)
parked_managed = bool(managed) and os.path.isdir(parked_target) and not os.path.islink(parked_target)
install_at = parked_target if parked_managed else os.path.join(r.mod_root, dn)
```

and uses `install_at` for `targets.w2_install_dir`, for `collision`, and for the
confirm sentence, which gains `; this mod is disabled, the new version stays
disabled` when that is the case. `same_unique_id_dirs` also scans the disabled
root, marking those entries `(disabled)` so the UI can tell the two apart.

`conflict.parked` is new and additive: the frontend may ignore it, but a caller
that wants to explain why the destination looks unusual now can.

Duplicating the target computation is not ideal -- it is the same expression in
two places, and one day they could drift again. It is chosen over extracting a
shared helper because install has to interleave the decision with staging,
journal events and rollback, and a helper that returned just a path would hide
which of those the preview is promising. The two are kept honest by a test that
asserts `PREVIEW_MATCHES_REAL` on a parked mod and on a fresh one.

## Bounds

| bound | value | why |
|---|---|---|
| functions scanned | 19 | every function in both engines that mentions a write root |
| new RPCs | 0 | this is the same preview, computed correctly |
| new error codes | 0 | no new failure mode, only a correct prediction |
| fields added to the wire | 1 (`conflict.parked`) | additive; existing callers unaffected |

## What is proven

- The preview and the execute name the same path, for a parked mod and for a
  fresh install, asserted in `tests/test_preview_agreement.py` (4 cases).
- The confirm sentence contains that path and states the mod stays disabled.
- A parked copy with the same UniqueID is reported by the preview AND refused by
  the install, so the warning precedes the refusal.
- Device probe after the fix: `PREVIEW_MATCHES_REAL True`.

## What is not proven

- That no fifth path resolves one root only. The scanner reports candidates; the
  judgement of which are legitimate is mine, and the 9 `MOD_ONLY` hits were
  reviewed by reading, not proven by a test.
- That a human reading the dialog would have noticed. `PREVIEW_MATCHES_REAL` is
  a string comparison; whether the sentence is comprehensible in the panel at
  1280x800 has never been checked by a person.
- RimWorld's `inspect()`. Its parked root does not exist, so the new branch is
  unreachable there -- compiled, not executed.
