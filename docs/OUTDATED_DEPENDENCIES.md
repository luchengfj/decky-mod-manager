# A dependency that is installed but too old

Round 67. The plugin already told the user about dependencies that are **not on
disk** (`missing_dependencies`, round 45) and about dependencies the user has
**deliberately disabled** (`parked_dependencies`, round 66). There is a third
state, and until this round it was invisible: the dependency is present, its
version is readable, and it is **older than the mod asks for**.

SMAPI does not load such a mod at all. It writes

    Skipped mods
    --------------
    these mods could not be added to your game.
    - TheHost 1.0.0 because it requires TheDep 2.0.0 or later, but you have 1.0.0

and the panel said nothing was wrong.

## What the plugin knew and did not use

`ParsedManifest` already carried the *host's* requirement as plain ids:
`_coerce_dep_ids()` read `{"UniqueID": "probe.thedep", "MinimumVersion": "2.0.0"}`
and returned `["probe.thedep"]`. The version half of the same object was read
and thrown away in the same expression, so nothing downstream could compare it.

## The report

`scan_installed_mods()` now keeps the minimum next to the id and compares it
against the version it read from the dependency's own manifest:

    want_t, have_t = _version_tuple(need), _version_tuple(have)
    if not want_t or not have_t:
        continue
    if have_t < want_t:
        stale.append({"id": d, "required": need, "installed": have})

Three deliberate decisions in those four lines:

1. **A version with no digits is not "too old", it is unknown.** `snapshot`,
   `1.0-beta-hotfix` (no usable number after the first) and an empty string all
   give `have_t == ()`, and the `continue` keeps them quiet. Reporting "too old"
   for a version the plugin failed to understand would be a guess, and the user
   cannot act on a guess.
2. **Comparison is on numeric tuples, not strings.** `2.0` and `2.0.0.0` are the
   same version; `"10.0" < "9.0"` as strings, which is wrong.
3. **Only *declared* minimums are compared.** A dependency with no
   `MinimumVersion` is not compared against anything — the descriptor decides
   what the key is called (`mod_package.field_map.dependency_minimum_key`), and
   a descriptor that does not name one produces no comparison at all. There is
   no built-in field name in the parser.

## Three lists, three different fixes

| List | Means | The user's fix |
| --- | --- | --- |
| `missing_dependencies` | nobody on disk provides it | **download** it |
| `parked_dependencies` | the user owns it and turned it off | **enable** it |
| `outdated_dependencies` | on disk, but older than asked for | **update** it |

The panel uses the same three verbs. `outdated_dependencies` carries
`{from, id, required, installed}` so the row can say
`probe.thedep 1.0.0 < 2.0.0` instead of just "something is wrong".

No error code was added (`errors.py` still 52). This is a report, not a new
failure mode — the same reasoning as round 66.

## What was NOT done

- **No update was performed.** This round only makes the state visible. Fetching
  a newer version of an installed dependency is a distinct operation with its
  own questions (which release, does it still declare the same id, what happens
  to the old one) and it is not in this round.
- **The fetcher was not taught about this state.** `fetch_dependencies` is still
  handed only `missing_dependencies`, so it will not try to download something
  that is already here. Making it "helpfully" upgrade would put a second
  decision in a second place — the shape rounds 57–60 spent three rounds
  removing.
- **Real-device population is empty for this state.** I surveyed all 28 real
  mods: 18 minimum declarations, 10 satisfied, 8 pointing at mods that are not
  installed at all, and **0 present-but-too-old**. So the device proof below is
  a synthetic tree; the real tree cannot exhibit this state today.

## Evidence

Real device, deployed build, synthetic tree, all 12 checks green:

    PASS A_DEP_INSTALL_OK
    PASS B_HOST_INSTALL_OK
    STATE_OUTDATED [{"from": "probe.thehost", "id": "probe.thedep",
                     "required": "2.0.0", "installed": "1.0.0"}]
    HOST_ROW_OUTDATED [{"id": "probe.thedep", "required": "2.0.0", "installed": "1.0.0"}]
    STILL_MISSING []
    PASS C_STATE_HAS_KEY
    PASS D_STATE_REPORTS_ONE
    PASS E_FROM_IS_HOST      probe.thehost
    PASS F_ID_IS_DEP         probe.thedep
    PASS G_REQUIRED          2.0.0
    PASS H_INSTALLED         1.0.0
    PASS I_ROW_HAS_KEY
    PASS J_NOT_REPORTED_AS_MISSING
    PASS K_JSON_SAFE
    PASS L_NEW_ENOUGH_IS_QUIET
    PASS_COUNT 12 / CHECK_COUNT 12

The same probe against the **previous** build printed
`VERDICT_REPORTS_TOO_OLD False` and `MISSING []` — the panel said the mod was
fine while SMAPI would have skipped it.

Local: `Ran 785 tests / OK (skipped=15)` (11 new), `compileall` 0, 7 validators
green, `tsc --noEmit` 0 and `rollup -c` 0 on the device.

Negative proof: with the comparison block replaced by `pass`, three tests fail
(`test_an_older_dependency_is_reported_not_silent`,
`test_a_removed_dependency_is_missing_not_outdated`,
`test_the_scanner_reports_then_compares`) while the new-enough case still
passes — so the mutation broke the code under test, not the fixture.

## What this does not claim

- The panel has never been opened by a human in Game Mode. Every layout
  statement here comes from CDP DOM text.
- The minimum key name (`MinimumVersion`) is verified against the real device
  manifests, but a different game's descriptor would need its own key.
- No real mod on the device is in this state, so the real-world frequency of it
  is unknown.
- RimWorld's `xml_list` engine is untouched: it has no dependency versions.
