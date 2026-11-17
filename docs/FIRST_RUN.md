# The first run

What happens to somebody who installs this plugin and has never installed a mod
in their life. Round 52 asked that question on the device and found two defects
that had been shipped for many rounds, because every test and every probe
started from a tree where the work had already been done once.

## The state a new user is actually in

A game that has never had a mod installed has **no `Mods/` folder**. Not an empty
one — none. `Mods/` is created by the first mod manager, or by the game on first
launch in some titles, but on a fresh Stardew Valley install the folder simply
does not exist.

Every fixture in the test suite created `Mods/` up front, because that is what
you need to put a mod in it. That one line of fixture setup is why nobody
noticed.

## Defect 1 — the very first install failed

```
F1. first ever install, no Mods/ folder
  F1_MODS_EXISTS_BEFORE   False
  F1_INSTALL_OK           False
  F1_CODE                 E_OP_FAILED
  F1_DETAIL               [Errno 2] No such file or directory:
                          '.../Stardew Valley/.decky-staging/20261117T16593...'
  F1_MODS_EXISTS_AFTER    False
```

The install stages the unpacked mod in `.decky-staging/<txn>/<id>` and then
renames it into `Mods/<id>` with a single `os.replace`. A rename cannot create
the parent of its destination: with `Mods/` absent, `os.replace` raises ENOENT,
the transaction rolls back, and the user sees a failure naming a staging path
they never asked about.

Isolated to one primitive:

```
REPLACE_FAILED              2 系统找不到指定的路径 | ...\stage\mod
REPLACE_OK_AFTER_MODS_CREATED
```

The fix is one line in each engine, placed after staging has already succeeded so
a failure above it still leaves nothing half-made:

```python
ensure_dir(r.mod_root)
os.replace(stage_dest, target)
```

Both engines had it: `deckymod/smapi.py` (Stardew / file_drop) and
`deckymod/engine.py` (RimWorld / xml_list). The second one has no device to test
against, which is exactly why the same bug was worth fixing in both.

## Defect 2 — "not found" said the opposite of what happened

```
C7. uninstall something never installed
  C7_OK      False
  C7_CODE    E_DUPLICATE
  C7_DETAIL  nobody.at.all is not installed/managed
```

`E_DUPLICATE`'s user-facing message is *"This mod (same packageId) is already
installed. Use Replace instead."* — the precise opposite of what occurred. It
was reachable from three operations (`uninstall`, disable, enable) with any
mistyped or stale name, which is the most likely mistake a user makes after
mid-typing a mod name from a list.

Five sites raised it for not-found:

| file | site |
| --- | --- |
| `deckymod/smapi.py` | uninstall: directory not resolvable in `Mods/` |
| `deckymod/smapi.py` | disable: nothing parked in `.decky-disabled/` |
| `deckymod/smapi.py` | enable: identifier is not an enabled mod directory |
| `deckymod/engine.py` | set_enabled: not managed |
| `deckymod/engine.py` | uninstall: not managed |

The legitimate users of `E_DUPLICATE` stay: the confirm-phase "already managed"
answer and the on-disk "second copy with the same UniqueID" answer. Both of those
mean *already installed*, which is what the code's message says.

### Why a new code instead of reusing one

The table had 50 codes and none of them said "there is nothing by that name".
The nearest neighbours are wrong in different directions:

| candidate | why not |
| --- | --- |
| `E_DUPLICATE` | says already installed — the opposite |
| `E_FILE_COLLISION` | a folder exists that this plugin does not manage; not "nothing exists" |
| `E_ID_INVALID` | the identifier is malformed, not merely unmatched |
| `E_STATE_MISSING` | about a state file, not a mod |

So `E_MOD_NOT_FOUND` (`discovery`) was added, the 51st. Adding a code is not free
— it touches the count assertions in three test modules, one validator, three
documents and both i18n dictionaries (458 keys each, parity enforced) — but the
alternative is a message that lies, and messages are what the user acts on.

## Device evidence

Read-only against the live plugin, then a scratch tree with no `Mods/`:

```
=== A. live plugin (read only)
A_STATUS_OK                        True
A_MOD_COUNT                        30
A_ERROR_CODE_COUNT                 51
A_HAS_MOD_NOT_FOUND                True
A_RPC_COUNT_MATCHES                True
=== B. fresh synthetic tree (no Mods/ folder)
B_MODS_EXISTS_BEFORE               False
B_CONFIRM_PHASE                    confirm
B_INSTALL_OK                       True
B_MODS_EXISTS_AFTER                True
B_DIR_LANDED                       True
B_MANIFEST_LANDED                  True
B_UNINSTALL_MISSING_CODE           E_MOD_NOT_FOUND
B_DISABLE_MISSING_CODE             E_MOD_NOT_FOUND
B_ENABLE_MISSING_CODE              E_MOD_NOT_FOUND
B_MESSAGE                          No installed mod matches this name. Refresh the
                                   list; it may have been removed already.
B_DUPLICATE_PHASE                  E_DUPLICATE
B_UNINSTALL_REAL_OK                True
B_DIR_REMOVED                      True
```

`B_DUPLICATE_PHASE E_DUPLICATE` is in the same run on purpose: it shows the two
answers are now distinguishable, and that the duplicate answer was not weakened
while fixing the not-found one.

## The deploy bug this round found

The first deploy in this round updated `smapi.py` (which raises
`E_MOD_NOT_FOUND`) but not `errors.py` (which defines it), because the deploy
script carried a hand-written file list that had never included `errors.py`.
`ModError.__init__` rewrites an unknown code to `E_UNKNOWN`, so the device
returned:

```
A_ERROR_CODE_COUNT          50
A_HAS_MOD_NOT_FOUND         False
B_UNINSTALL_MISSING_CODE    E_UNKNOWN
```

The plugin looked like it had a worse bug than the one being fixed. The lesson is
not "remember `errors.py`": a list that has to be edited whenever a module is
added will be wrong again. `r52_deploy.sh` now enumerates
`$BUILD/deckymod/*.py` and reports `MODULE_FILES=33 BUILD_MODULES=33`, so a
missing module is visible as a count mismatch instead of as a strange runtime
behaviour.

This is the second time a literal deploy list shipped an incomplete plugin
(round 39 skipped `main.py`).

## Bounds

| thing | value | why |
| --- | --- | --- |
| new error codes | 1 (`E_MOD_NOT_FOUND`) | none of the existing 50 could say it without lying |
| edits to engines | 2 lines | one `ensure_dir` before each `os.replace` |
| file lists in deploy | 0 | enumeration replaced the literal list |
| new RPCs | 0 | the surface was already sufficient |

## What is proven

- First install succeeds on a game with no `Mods/` folder, and leaves a real
  directory with its manifest (`tests/test_first_run.py`, and the device run).
- Not-found is a distinct answer from already-installed, from three operations,
  and the two messages differ (`test_the_two_answers_are_told_apart`).
- The duplicate answer still fires for the case it is meant for
  (`B_DUPLICATE_PHASE E_DUPLICATE`).
- The confirm phase still writes nothing on a fresh tree.
- Both engines carry the fix; the RimWorld one is checked by AST, because there
  is no RimWorld install on this device.

## What is not proven

- The RimWorld path was fixed and compiled but not exercised against a real
  RimWorld install — there is none on this Deck.
- Nobody has watched a first install through the panel with a controller; the
  device evidence is RPC-level. See the note in `docs/QAM_VISUAL_CHECK.md`.
- The `ModError` fallback that turned `E_MOD_NOT_FOUND` into `E_UNKNOWN` is
  reasonable in isolation (never leak an unknown code to the UI) but it made a
  deploy error look like a logic error. It has not been changed; the deploy is
  now counted instead.
