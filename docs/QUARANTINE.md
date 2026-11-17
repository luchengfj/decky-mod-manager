# The quarantine: what "uninstall" actually means, and when it stops being true

Uninstalling a mod does not delete it. The folder moves to
`GAME_ROOT/.decky-quarantine/<txn>/`, and the journal records both the original
path and the quarantine path so Rollback can put it back. That is the right
default — an uninstall the user regrets is recoverable.

**But the record is what makes it recoverable, not the folder.** A quarantine
folder whose `MOD_UNINSTALLED` record is no longer in the journal occupies
space, looks recoverable to a user reading the panel, and cannot be brought
back by any code path. Round 48 added a read-only audit that says so.

## What the device actually had

```
QUARANTINE_DIRS 45
REFERENCED_BY_JOURNAL 16
ORPHANS 29          (13 of them empty)
ORPHAN 20261115T144322-65429fcd children=1 bytes=114308
```

After wiring the audit into `status()`:

```
OK=True
PRESENT=True
CHECKED=True
EXISTS=True
JOURNAL=readable
DIRS=45
TOTAL_BYTES=1321331
RESTORABLE=16
ORPHANS=29
EMPTY=21
ORPHANS_WITH_BYTES=16
DESCRIBE='16 quarantine folder(s) no longer restorable: 20261115T144322-65429fcd (114308 B), 20261115T144611-2ab8d3c7 (114308 B) (+14 more)'
JSON_SAFE=True
```

Sixteen folders hold real files and can never be restored. Four of them hold a
114 KB mod each. Total is 1.3 MB — so this is **not** a disk-full problem, and
`docs/NEXT_FEATURES.md` P1 #7 was written assuming it would be. The actual
problem is unresolvable data the user believes is safe.

## Why it is reported and not cleaned

The obvious "fix" — delete orphaned folders — is the one thing this plugin must
not do. A folder in the quarantine was put there by *this* plugin, but the
question "nobody claims this any more" is answered by the journal, and a journal
that has been truncated, rotated, or restored from a backup looks exactly like
"nothing claims any of these". Acting on that answer means deleting mods the
user wanted. So:

* **Nothing is ever created, moved or deleted** by this module.
* The panel prints a line, and the line exists only when a folder actually
  holds bytes — an empty orphan is clutter, not a warning.
* The reason is spelled out (`no longer restorable`), not softened, because a
  vague warning is indistinguishable from noise.

## The distinction that matters most: unknown ≠ orphan

`referenced_txns()` returns `None` when the journal cannot be read at all, and
*not* an empty set. The two mean different things:

| journal state | folder state | what the panel says |
| --- | --- | --- |
| readable, record present | `restorable` | nothing |
| readable, no record | `orphan` | the warning line |
| unreadable | `unknown` | `QUAR_UNKNOWN` — "not orphans" |

An empty set would present "I cannot read the journal" as "nobody claims these
folders", which is the exact shape of a bug that deletes user data. There is a
test for it: `test_an_unreadable_journal_labels_everything_unknown`.

## Bounds

| limit | value | why |
| --- | --- | --- |
| `max_dirs` | 200 | a quarantine is not worth a slow `status()` call |
| `max_files` | 5000 | per-folder walk stops; `truncated` is set and shown |

Symlinked directories inside a quarantine folder are not followed — a link
points at data this scan does not own, and following it would double-count or
walk outside the quarantine entirely.

## What is proven, and what is not

**Proven on the device:** the audit runs inside `status()`; the real tree yields
45 folders / 16 restorable / 29 orphans / 16 holding bytes; the summary line
names the two largest and elides the rest; the whole payload is JSON-safe; a
scan that raises leaves `status()` successful; a folder with no record is called
an orphan only when the journal is readable.

**Not proven:** that a human has read this line on a Deck — no hand has pressed
the button since round 48. And the plugin still cannot tell you *why* a record
went missing: a rotated journal and a restored backup are indistinguishable from
inside.
