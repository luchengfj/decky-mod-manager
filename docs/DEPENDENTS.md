# Who needs this mod (Round 71)

Every dependency list the plugin reported until this round answered one
direction of the question: *what does this mod need*. `missing_dependencies`
says which requirements are absent, `parked_dependencies` says which are
installed but switched off, `outdated_dependencies` says which are installed
but too old. All three are about the mod you are looking at.

A removal asks the opposite question, and nobody was answering it.

## What SMAPI actually does

SMAPI skips a mod whose **required** dependency is not present. It does not
stop the game, it does not delete anything, and it does not ask. The mod simply
does not load, and the only trace is a line in `SMAPI-latest.txt` and a row that
stops appearing.

So uninstalling a library is not a local operation. It silently stops every mod
that requires it. That is correct behaviour for a loader; it is not something a
person should have to discover afterwards.

## The probe that found it

On the device, a synthetic tree under `/tmp`, two mods:

```
install probe.thedep                -> True
install probe.thehost               (requires probe.thedep, IsRequired: true) -> True
uninstall probe.thedep           -> confirm_text:
      "Uninstall probe.thedep? The folder is moved to quarantine (not deleted)."
   MENTIONS_HOST    False
   MENTIONS_DEPEND  False
   CONFIRM_VARS     {"pid": "probe.thedep"}
uninstall ...  (confirmed)          -> True
AFTER_ROWS      [('probe.thehost', 'probe.thehost', ['probe.thedep'])]
MODS            ['probe.thehost']
```

The uninstall itself was correct — the folder really did move to the
quarantine. What was missing was the sentence. The very next `status()` call
knew that `probe.thehost` had just lost a required dependency; the confirmation
that caused it said nothing at all.

## The reverse map

`deckymod/manifest.py` gained one function:

```python
def dependents_of(target_id: str, entries) -> List[dict]:
    key = str(target_id or "").strip().lower()
    out: List[dict] = []
    if not key:
        return out
    for m in entries or []:
        uid = str(m.get("uniqueId") or "").strip()
        if uid.lower() == key:
            continue
        deps = m.get("dependencies") or []
        if not any(str(d).strip().lower() == key for d in deps):
            continue
        out.append({"id": uid or str(m.get("dir") or ""),
                    "name": str(m.get("name") or ""),
                    "dir": str(m.get("dir") or "")})
    out.sort(key=lambda r: (r["id"].lower(), r["dir"].lower()))
    return out
```

Three decisions inside it:

- **Only ids the scan actually found with the right dependency count.** An id
  that is merely mentioned somewhere is not a dependent. This is the same rule
  `missing_dependencies` already followed.
- **A mod is never its own dependent.** A manifest that lists its own UniqueID
  would otherwise report itself, which reads as a warning about nothing.
- **Case and surrounding whitespace are normalised** on both sides, because
  real manifests disagree about casing (`UniqueId` vs `UniqueID`,
  `Dependencies` vs `dependencies`).

The reverse map is filled **from the scan already in hand** — `scan_installed_mods`
walks every mod once, and every row now also carries `dependents`. No second
walk of `Mods/`, so the read cost of the panel did not change.

## Where the warning appears

Two confirmation sites, one sentence builder each, both fed by
`FileDropEngine._active_dependents()`:

| operation | condition | key |
| --- | --- | --- |
| `uninstall` | something requires it | `CONFIRM_UNINSTALL_WITH_DEPENDENTS` |
| `set_enabled(..., False)` | something requires it | `CONFIRM_DISABLE_WITH_DEPENDENTS` |
| either | nothing requires it | the plain key, as before |

Disabling is included because from the game's point of view it is the same
event: the folder leaves `Mods/` and SMAPI stops loading everything that
requires it. Round 57 established that install-time behaviour must respect a
parked mod; the same reasoning applies to a warning.

The text is English on the wire (`confirm_text`) with a stable key and
JSON-safe vars (`n`, `who`) so the panel can render it in Chinese — the same
shape every other confirmation already used, so `ConfirmModal.tsx` needed no
change.

## What it deliberately does not do

- **A parked dependent is not reported.** It is already not loading, so
  removing its dependency changes nothing today. `_active_dependents()` scans
  `Mods/` only, and there is a test for it.
- **It is not a lock.** The user may have a reason to remove the library;
  nothing here refuses. The plugin says who will be affected and lets the
  person decide. Refusing would be a different product.
- **It does not recurse.** If `A` needs `B` and `B` needs `C`, removing `C`
  names `B` — not `A`. `A` is not directly broken yet; it becomes broken when
  `B` is, and the panel will say so at that point.
- **It does not touch the game folder.** `dependents_of` reads and sorts.
  A structural test asserts the helper calls no write primitive.
- **Optional dependencies are excluded.** `_coerce_dep_specs` already drops
  entries with `IsRequired: false`, so they never reach the reverse map — an
  optional dependency being absent does not stop a mod from loading.

## Evidence

Local suite: `Ran 831 tests ... OK (skipped=15)` — 15 of them new
(`tests/test_dependents.py`), covering the reverse map directly, both
confirmation sites, the parked-dependent silence, and the shape rule that the
engine calls the helper instead of reimplementing it.

Two negative proofs, each narrow enough that the normal flow still passed:

```
M1  confirmation stops using the dependents it computed
    M1_PLAIN_CASE_STILL_PASSES True
    M1_FAILURES 2   (test_the_confirmation_says_who_will_stop_loading,
                     test_both_confirm_sites_ask)
M2  reverse map compares ids byte-identically instead of case-insensitively
    M2_PLAIN_CASE_STILL_PASSES True
    M2_FAILURES 1   (test_case_and_whitespace_do_not_change_the_answer)
NEGATIVE_PROOF_FIRED True
```

Device, against the deployed plugin (synthetic tree under `/tmp`, the real
`Mods/` never touched) — **27 / 27**:

```
PASS A_LIB_INSTALLED / A_HOST_INSTALLED
PASS A_NAMES_A_DEPENDENT          [{'id': 'probe.host', 'name': 'Probe Host', ...}]
PASS A_TEXT_SAYS_STOPS_LOADING    "Uninstall probe.lib? The folder is moved to
                                   quarantine (not deleted). 1 installed mod(s)
                                   need it and will stop loading: Probe Host."
PASS A_KEY_IS_THE_WARNING         CONFIRM_UNINSTALL_WITH_DEPENDENTS
PASS A_VARS_CARRY_THE_COUNT       {'pid': 'probe.lib', 'n': 1, 'who': 'Probe Host'}
PASS A_UNINSTALL_COMPLETED / A_LIB_IS_GONE
PASS A_HOST_NOW_MISSING_THE_LIB   ['probe.lib']
PASS B_KEY_IS_THE_WARNING         CONFIRM_DISABLE_WITH_DEPENDENTS
PASS B_NO_DEPENDENTS_IS_QUIET / B_QUIET_KEY_IS_PLAIN
PASS C_PARKED_DEPENDENT_NOT_REPORTED / C_KEY_IS_PLAIN
PASS D_STATUS_ROWS_HAVE_THE_FIELD / D_ROW_IS_QUIET_WITH_NO_ACTIVE_DEPENDENT
PASS JSON_SAFE
PASS_COUNT 27 / 27   VERDICT_WARNS_BEFORE_BREAKING True
```

## What this does not claim

- **Nobody has read the two new sentences on screen.** The panel has never
  been opened in Game Mode by a person in this whole line of work; every
  layout conclusion comes from CDP text. The strings are asserted at the
  engine boundary and rendered by the same `t()` path as the others, but
  "renders in Chinese at 1280×800" is still unverified.
- **The dependent list is one level deep, by design.** A chain of three mods
  reports one name, not two.
- **Parked dependents are invisible here.** They are reported on their own row
  (`MODLIST_BADGE_DISABLED`), not in the confirmation.
- **The warning does not prevent anything.** It is information, not a gate.
- **`engine.py` (the RimWorld `xml_list` path) does not have the reverse map.**
  That engine is not the active one; adding a confirmation there without a
  second enabled game to exercise it would be untested code.
