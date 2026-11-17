# Disabled dependencies are not missing dependencies

Round 66. Everything below was measured against the deployed plugin on the Deck,
using a synthetic Steam tree under `/tmp` (the real `Mods/` folder was never
touched).

## The operation

1. install `probe.thedep` 1.0.0;
2. **disable** it -- in the `file_drop` engine that moves the folder to
   `.decky-disabled/`;
3. install `probe.thehost`, whose manifest declares
   `Dependencies: [{"UniqueID": "probe.thedep", "IsRequired": true}]`;
4. read `status()` and hand `state.missing_dependencies` to `fetch_dependencies`.

## What the device said

The engine reported the parked dependency as absent:

    HOST_ROW_MISSING_DEPS  ['probe.thedep']
    GLOBAL_MISSING         ['probe.thedep']    # state.missing_dependencies
    MODS_DIRS              ['probe.thehost']
    PARKED_DIRS            ['probe.thedep']    # it is right there

and the fetcher then acted on that list. With the network calls injected (so no
download left the machine) but the real install path running:

    PARKED_VERSION_BEFORE  1.0.0     # after the user disabled it
    FETCH_INSTALLED        1         # deps.run reports "resolved"
    PARKED_VERSION_AFTER   1.1.0     # the parked copy was REPLACED
    MISSING_AFTER          ['probe.thedep']   # and still reported as missing

Two harms in one call, and they are separate problems:

* **the user's switch was overwritten.** The parked folder is the user's
  decision. `_locate()` (round 60) correctly answers "this managed mod lives in
  `.decky-disabled/`", so the install landed there and swapped the version. The
  behaviour followed the rule; the rule was being applied to an operation that
  should not have started.
* **the panel still said "missing".** Because the list never cleared, the
  "download dependencies" affordance stays lit after mutating user data -- a
  report of failure that arrives *after* the damage, which is the worst order.

## Why the two lists must be separate

`.decky-disabled/` is a **sibling** of `Mods/`, and `scan_installed_mods()` only
walks the root it is given. A parked dependency is therefore invisible to the
active scan, and before this round it fell straight into
`missing_dependencies` -- precisely the list `main.py` passes to `deps.run()`.

The truth is subtler than "missing". The mod **is** installed: it is present, it
is owned by the plugin, and it is listed in the panel. The user turned it off.
The game will genuinely not load it, so the requirement is unsatisfied -- but the
remedy is one tap ("enable it"), not a download. Conflating the two lists makes
the remedy wrong in both directions: the panel asks the user to download
something they already have, and the fetcher is willing to write over it.

So `scan_installed_mods()` now takes the known-parked ids and splits its answer:

| list | meaning | who consumes it |
| --- | --- | --- |
| `missing_dependencies` | nobody on disk provides this id | `fetch_dependencies` |
| `parked_dependencies` | the user owns it and disabled it | the panel, as "enable them" |

`tests/test_parked_dependencies.py::test_the_fetcher_is_never_handed_a_parked_id`
runs the real `deps.run()` with the state's list and asserts that **no fetch is
attempted at all** and the parked copy still reads `1.0.0` afterwards.

## The code

`deckymod/manifest.py`:

```python
def scan_installed_mods(mod_root: str, mod_package: dict,
                        parked_ids=None) -> dict:
    ...
    parked = {str(x).strip().lower() for x in (parked_ids or []) if str(x).strip()}
    ...
    absent = [d for d in deps if d.lower() not in present]
    parked_here = [d for d in absent if d.lower() in parked]
    missing_here = [d for d in absent if d.lower() not in parked]
    m["missing_dependencies"] = missing_here
    m["parked_dependencies"] = parked_here
```

`deckymod/smapi.py::status()` scans the parked root **first**, so the active scan
can be told which ids are disabled rather than absent:

```python
disabled_scan = manifest.scan_installed_mods(r.disabled_root, self._mod_package())
parked_ids = [m["uniqueId"] for m in disabled_scan["mods"] if m.get("uniqueId")]
scanned = manifest.scan_installed_mods(r.mod_root, self._mod_package(),
                                       parked_ids=parked_ids)
```

`parked_ids` is optional, so every older caller keeps working; the early return
for an unusable parser carries both keys so the state block's shape never varies.

## What was deliberately not done

* **No new error code.** `errors.py` stays at 52. This is a reporting split, not
  a new failure mode.
* **The fetcher was not taught about parked ids.** `deps.run()` keeps its
  contract ("here is a list of ids nobody provides"); the split happens where the
  fact is known, in the scan. Passing parked ids to the fetcher and asking it to
  skip them would leave two places deciding the same thing -- the shape rounds
  57-60 spent three rounds removing.
* **Disabling a dependency is still not an error.** SMAPI will refuse to load the
  dependent mod, which is what the user asked for. The panel now says so in the
  words that name the fix.

## Evidence

Local: `Ran 774 tests ... OK (skipped=15)`, `compileall` clean, seven persistent
validators exit 0.

Negative proof (`.decky-probe/r66_negative_proof.py`): copy the tree, strip
`parked_ids` back out of `scan_installed_mods()` and out of `status()`, run the
new module -- `MANIFEST_PARKED_KEYS 3 -> 0`, `SMAPI_PARKED_REFS 0`,
`FAILURE_COUNT 9`, all nine cases fail, `NEGATIVE_PROOF_FIRED True`.

Device (deployed plugin, 4800-byte-true booleans recorded in the round report):
the dependency parks, the missing list empties, the row says "installed but
disabled", the fetcher plans nothing, the parked copy keeps `1.0.0`, and
uninstalling the dependency puts it back into the missing list -- because once it
is really gone it *is* missing.

## What this does not claim

* The panel **still has not been looked at by a human in Game Mode**. Every layout
  statement in this file comes from CDP DOM text, not from someone pressing
  buttons on the device.
* `test_parked_dependencies.py` proves the engine and the real `deps.run()` path.
  It does **not** prove a real download from GitHub stops -- the network handlers
  are injected, so no bytes leave the machine during the test.
* A dependency that is parked **and** broken on disk (unreadable manifest) is not
  covered: `scan_installed_mods()` skips unparsable folders, so it would be
  reported as missing. That is arguably correct (nothing loadable is there) but it
  is not a case this round designed for.
* The RimWorld `xml_list` engine was not touched; it still reports a single
  `missing_dependencies` list because it has no `.decky-disabled/` concept yet.
