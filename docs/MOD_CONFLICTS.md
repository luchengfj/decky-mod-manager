# Duplicate detection: why reporting a conflict is not enough

Round 27. Criterion 3 asks the plugin to "detect file conflicts within the same
game". Today it did detect them — `status()` has carried `duplicate_ids` since
round 20 — and that was worth exactly nothing, because `install` never consulted
it. This file records the defect, the fix, and the evidence.

## The defect, found on the device

While verifying criterion 6 end-to-end, the plugin was asked to install
`Esca.DestroyableBushes` from its GitHub release. The user already had that mod,
hand-installed, at:

```
/home/deck/.local/share/Steam/steamapps/common/Stardew Valley/Mods/DestroyableBushes
```

The plugin unpacked a second copy:

```
/home/deck/.local/share/Steam/steamapps/common/Stardew Valley/Mods/esca.destroyablebushes
```

and then reported, in its own words:

```
MODS=28
ENTRY uid=Esca.DestroyableBushes dir=DestroyableBushes      ver=1.5.2
ENTRY uid=Esca.DestroyableBushes dir=esca.destroyablebushes ver=1.5.2
```

Two directories, one UniqueID. SMAPI loads both. The player gets two
half-configured copies with different `config.json` files, and `status()`
happily listed 28 mods as though that were fine.

`duplicate_ids` **was** computed and **was** returned. Nothing acted on it.

## Root cause

`install` compared three things before writing:

| check | what it compared | why it missed this |
|---|---|---|
| `managed = self._existing_managed(uid)` | journal entries | the user installed this mod by hand; the journal is empty |
| `os.path.exists(target)` | the incoming `dir_name` | the existing folder is `DestroyableBushes`, ours is `esca.destroyablebushes` |
| `_resolve_disk_dir` (uninstall only) | a single directory name | install never called it |

The install path was name-based. Identity is the `UniqueID`, and on disk the
folder name is chosen by whoever installed the mod — the author's release
sometimes, the mod manager sometimes, the user sometimes.

## The fix

Three pieces, all in `deckymod/smapi.py`:

**1. A read-only identity lookup** (`_disk_dirs_with_uid`). Scans `Mods/` through
the descriptor parser and returns every directory whose manifest declares the
given UniqueID, compared case-insensitively. A scan failure returns `[]` rather
than raising: a broken folder must not make every install fail.

**2. `inspect` reports it before anything is attempted**:

```python
same_uid_dirs = self._disk_dirs_with_uid(r.mod_root, uid)
"conflict": {..., "same_unique_id_dirs": same_uid_dirs},
```

so the QAM panel can warn while the user is still looking at the details.

**3. `install` refuses it** — and the refusal is *not* confirmable:

```python
if not managed:
    same_uid = self._disk_dirs_with_uid(r.mod_root, uid, exclude=dn)
    if same_uid:
        raise ModError(
            "E_DUPLICATE",
            detail=(f"{uid} is already on disk as {', '.join(same_uid)}; "
                    f"disable or uninstall that copy before installing {dn}"),
            context={"packageId": uid, "existing_dirs": same_uid})
```

Design note: `after_confirm=True` deliberately does **not** bypass this guard.
A journal "duplicate" can be confirmed because the plugin owns both sides and
can roll back; two on-disk copies with one UniqueID is a broken install no
matter who asked for it, so the only honest answer is to name the existing
folder and let the user decide what to do with it.

## A parked copy is not a live duplicate

`Mods/.decky-disabled/` holds disabled mods. They are not in `Mods/`, so SMAPI
does not load them, and installing a fresh copy into `Mods/` does not create two
live mods. The guard therefore scans `mod_root` only — and the test
`test_parked_copy_is_visible_but_not_a_live_duplicate` pins that choice so a
later change cannot silently start refusing a legitimate workflow.

## Evidence

Local, 324 tests:

```
Ran 324 tests in 3.549s
OK (skipped=4)
```

The 8 new cases live in `tests/test_duplicate_guard.py`. They cover: the refusal
itself and that it leaves `Mods/` untouched; that `inspect` surfaces the
collision before the confirm step; that an unrelated mod still installs; that a
parked copy is not treated as live; that the detector and the enforcement agree;
case-insensitive matching; no false positives on a clean tree; and that one
unreadable manifest does not block installs.

On the device, through the running plugin process:

```
MODS=27
ASSET=DestroyableBushes.1.5.2.zip ID=252770482
INSPECT_OK=True phase=inspect
SAME_UID_DIRS=[DestroyableBushes]
=== now actually try to install it (should be REFUSED) ===
IMPORT_OK=False CODE=E_DUPLICATE
IMPORT_DETAIL=Esca.DestroyableBushes is already on disk as DestroyableBushes;
              disable or uninstall that copy before installing esca.destroyablebushes
MODS_AFTER=27  (must stay 27)
```

Build and deploy: `Ran 324 tests` on the Deck, ZIP 187561 B /
`89d2a606f3a616d2bccb621038d838b9d1a6d3ed20438de2659b022ee7c1f754` /
36 entries; 25 files byte-identical between the build tree and the deployed
plugin (`VERIFY_FAIL=0`).

## What this does not prove

* The QAM panel itself was not re-opened after this change, so the
  `same_unique_id_dirs` warning has not been seen rendered. The RPC response
  carrying it has been seen.
* Only SMAPI-style mods are covered. The RimWorld engine has its own
  `<activeMods>` list and was not touched.
* A mod whose manifest cannot be parsed is invisible to this check, since the
  UniqueID comes from the manifest. That is a real gap, and it is the same gap
  `duplicate_ids` has always had.

Status discipline: no CLOSED item added, no `[ ]` box ticked, no V#/F# flipped.
