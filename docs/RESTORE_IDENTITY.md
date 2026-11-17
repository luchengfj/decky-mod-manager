# What a restore records

`rollback` puts a folder back. This page is about the record it leaves behind,
because the panel reads that record, not the disk.

## The operation

Both engines restore through the same two helpers:

| step | code |
| --- | --- |
| find the saved copy | `_replaced_copy_for(txn)` / the `MOD_UNINSTALLED` path |
| move it back | `os.replace(saved, target)` (or `os.rmdir` cleanup) |
| record it | `journal.record("MOD_ROLLBACK_RESTORED", ...)` |

`Journal.installed()` rebuilds the panel's mod list from those records:

```python
mods[pid] = {**r.get("mod", {}), "packageId": pid,
             "enabled": r.get("enabled", False)}
```

So whatever dictionary the restore writes into `mod` **is** the version the
user sees. Before this round that dictionary was copied from the record of
the transaction being undone — a memory of what used to be there, not a
reading of what is there now.

## What went wrong

`rollback` of an uninstall, run against a folder whose contents had been
replaced by another mod (hand-installed, hand-edited, or swapped by a user
who did not use this plugin):

```
A_INSTALLED [{"packageId":"probe.alpha","version":"1.0.0","dir":".../Mods/probe.alpha"}]
B_UID probe.beta                       # the folder now holds a different mod
C_UNINSTALL True None 20261117T225502-8bb20c86
C_ROLLBACK {"ok": true}
C_ROLLBACK_DATA {"restored": "probe.alpha", "dir": ".../Mods/probe.alpha"}
D_UID_ON_DISK probe.beta
D_VERSION_ON_DISK 9.0.0
D_INSTALLED [{"packageId":"probe.alpha","version":null,"dir":".../Mods/probe.alpha","enabled":true}]
D_ROWS [{"dir":"probe.alpha","uniqueId":"probe.beta","version":"9.0.0"}]
E_INSTALL_AGAIN {"ok": true}
E_HELD 20261117T225502-08169c45 probe.alpha.replaced
```

Three separate lies in one transaction:

1. `data["installed"]` said `probe.alpha` was installed while the folder held
   `probe.beta`. The scanner (`D_ROWS`) disagreed with the journal, and the
   scanner was right.
2. `version` was `null` — a row that cannot say what it is looking at.
3. The next install read the journal, believed `probe.beta` was "the old copy
   of probe.alpha", and moved it into the quarantine as
   `probe.alpha.replaced` (`E_HELD`).

The other APIs were already honest: `status()`, `uninstall` and `set_enabled`
all locate a mod on disk and report its real UniqueID. Only the write-back
path repeated a remembered identity.

## The fix

One helper asks the disk, and every restore branch uses it:

```python
def _read_dir_identity(self, dirpath: str):
    if not dirpath or not os.path.isdir(dirpath) or os.path.islink(dirpath):
        return None
    parser = manifest.parser_for(self._mod_package())
    globs = list(self._mod_package().get("manifest_globs") or [])
    mfile = manifest._find_manifest_in_dir(dirpath, globs)
    if not mfile:
        return None
    try:
        pm = parser.parse(read_bytes(mfile), mfile)
    except Exception:
        return None
    return {"packageId": pm.uid, "name": pm.name, "version": pm.version}
```

`None` is a legitimate answer: a folder with no readable manifest is not a
mod, and guessing would be the same mistake in a new place.

Three call sites read it — the uninstall branch, the upgrade branch, and the
round-68 interrupted-install branch. Two behavioural consequences:

- when the folder holds a **different** mod, the zero-damage case is still a
  success, but the record names the mod that is actually there and the answer
  carries `restored_uid`, `expected_uid` and a `note`:
  `"the folder was restored, but it now holds probe.beta, not probe.alpha"`;
- the record is marked `unmanaged=True` in that case, so the plugin does not
  claim ownership of somebody else's folder (the same rule as round 21).

## Evidence

`tests/test_restore_identity.py`, 8 cases:

- the swapped folder is not registered as the old mod;
- the panel list does not name a mod that is absent;
- the answer says the folder holds something else;
- a normal restore still registers the mod with its version and `enabled`;
- an upgrade rollback reports the version that came back;
- structure: the helper exists once, is called three times, no branch
  reconstructs a remembered identity, and the helper writes nothing.

Negative proof (`r70_negative_proof.py`): reverting only the identity half of
the uninstall branch (keeping the disk-read version) fails 3 of the 8 cases
while the plain case still passes — so the guard names this defect and not
merely "the code changed".

On the Deck, against the deployed plugin and a synthetic tree
(`r70_device_probe.py`, 23/23 PASS):

```
A_PANEL_DOES_NOT_NAME_ABSENT_MOD   the absent mod is gone from data.installed
A_ANSWER_SAYS_RESTORED_UID  probe.beta
A_ANSWER_SAYS_EXPECTED      probe.alpha
A_ANSWER_HAS_NOTE           yes
A_SCANNER_READS_BETA        uniqueId probe.beta, version 9.0.0
B_OLD_VERSION_ON_DISK       1.0.0 after an upgrade rollback
B_ROW_HAS_A_VERSION         version 1.0.0
C_ROW_VERSION / C_ROW_ENABLED   1.0.0 / true
```

## What this does not claim

- The folder is still restored even when its contents changed. This round
  makes the plugin **describe** that honestly; it does not decide whether a
  mismatched folder should be restored at all. Refusing would be a second
  product decision with its own failure mode (the user asked for the undo of
  the uninstall, and the bytes are theirs).
- Only `deckymod/smapi.py` was changed. The RimWorld engine (`deckymod/engine.py`,
  `xml_list`) has the same restore branches, but that game is `planned` and is
  never dispatched, so its behaviour was not re-verified here.
- The 23 checks ran with the plugin's own engine against a synthetic tree.
  The QAM panel itself has still never been opened by a human in Game Mode, so
  "the panel list does not name an absent mod" means the RPC payload, not
  pixels.
- A journal row whose folder was deleted outside the plugin (`plans` state from
  round 69) is a different case and is handled there, not here.
