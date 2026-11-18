# What this plugin still needs — the honest supplement

Goal item 6 asked what else is *required*, not what would be nice. This page
answers that narrowly: every entry below is either a **gap that can corrupt
user data**, a **gap that makes a feature fail silently**, or a **gap that
blocks a normal user from ever reaching the working parts**. Convenience
features are deliberately excluded.

## Shipped now (so the gaps below are read in context)

| Capability | State |
| --- | --- |
| Find installed Steam games + the mods each one actually has on disk | works, read-only |
| Import a local ZIP / `.7z` into the game's mod folder, unzip, verify | works for Stardew Valley |
| See files the user downloaded in the browser, not only the plugin inbox | works, read-only (Round 42) |
| See which mods ship the same file, without pretending to fix load order | works, read-only (Round 47) |
| Tell you which quarantined mods can still come back, and which cannot | works, read-only (Round 48) |
| Delete the quarantine folders that can no longer be restored | works, two-phase + all write gates (Round 54) |
| Roll back an upgrade to the version it displaced | works, one branch in each engine (Round 56) |
| Upgrade a disabled mod without enabling or duplicating it | works, lands in place (Round 57) |
| Uninstall a disabled mod, and refuse instead of faking it | works, resolves the parked path (Round 58) |
| Preview the import exactly as it will execute | works, one target computation (Round 59) |
| Take Mods/ over from another mod manager without deleting anything | works, two-phase, reversible (Round 55) |
| Know which Nexus page a mod you already installed came from | works, read-only (Round 49) |
| Refuse to change mods while the game is actually running | works, read-only check (Round 50, docs/RUNNING_GAME.md) |
| Refuse to start a new operation while a previous one never finished | works (Round 51, docs/RECOVERY.md) |
| Enable / disable / uninstall / roll back | works (folder move in and out of the game's `Mods/`) |
| See required dependencies and download the ones that are fetchable | works, up to 3 levels deep (Round 45) |
| Download mods | GitHub Releases + direct HTTPS URL only |
| Nexus | **metadata only** — browse and open the mod page; download links are premium-only, by Nexus policy |
| Know whether the game actually loaded a mod (not just that it is on disk) | works, read-only (Round 40, docs/LOADER_LOG.md) |
| Refuse writes when Mods/ belongs to another manager, and say why | works, structural (Round 44, docs/MOD_FOLDER_OWNERSHIP.md) |
| Chinese / English UI | works, 471 keys each, parity enforced |
| Let a descriptor name its own third-party-manager marker | works (Round 53, docs/DECLARED_VS_READ.md) |
| Refuse a mod whose manifest names an `EntryDll` it does not ship | works on both ZIP and `.7z` (Round 64, docs/ENTRY_DLL.md) |
| Make an undo that cannot undo say so | `rollback` of an uninstall refuses instead of reporting a restore that did not happen (Round 65, docs/ROLLBACK.md) |
| Report a dependency that is installed but too old | global + per-row `outdated_dependencies`; no update performed (Round 67, docs/OUTDATED_DEPENDENCIES.md) |
| Make a failed install or upgrade say what actually happened | the old version stays or the leftover goes, and the answer matches the disk (Round 69, docs/FAILED_INSTALL.md) |
| Record the mod that a restore actually put back | reads the folder's manifest instead of repeating the old record (Round 70, docs/RESTORE_IDENTITY.md) |
| Report a disabled dependency as disabled, not as missing | the fetcher is no longer handed an id the user parked, so a download cannot overwrite it (Round 66, docs/PARKED_DEPENDENCIES.md) |
| Warn who will stop loading before a library is removed | the reverse dependency map, in both confirmation sites (Round 71, docs/DEPENDENTS.md) |
| Make a failed rollback retryable instead of a dead end | stuck transactions surface in recovery and never fake a recovery (Round 72, docs/STUCK_ROLLBACK.md) |

0h. **The reverse question: who needs this mod.**

   Every dependency list until Round 71 answered "what does this mod need".
   A removal asks the other direction, and nothing answered it: uninstalling a
   library printed a confirmation about the quarantine folder and said nothing
   about the mods that require it. SMAPI skips those silently, so the first
   evidence was a row that had stopped appearing. The probe was two mods on a
   synthetic tree; the confirmation text did not mention the dependent, and the
   `status()` call immediately afterwards already knew.

   `manifest.dependents_of(target_id, entries)` walks the entries the scan
   already has, so the reverse map costs no second pass, and every row now
   carries `dependents`. `FileDropEngine._active_dependents()` feeds the two
   confirmation sites (`uninstall`, and disabling via `set_enabled`), which
   switch to `CONFIRM_UNINSTALL_WITH_DEPENDENTS` /
   `CONFIRM_DISABLE_WITH_DEPENDENTS` when the list is non-empty. A parked
   dependent is not reported -- it is already not loading.

   Nothing refuses. The plugin says who is affected and lets the person decide,
   which is the same posture as the rest of the surface, and the row also shows
   "Other mods need this one: ..." so the answer is visible before anyone asks.
   15 tests, two negative proofs (confirmation ignores its own list; the map
   compares ids byte-identically), and 27/27 checks against the deployed plugin
   on the device.

0g. **Multi-mod archives, and any archive nested more than one folder deep.**

   One `manifest.json` glob was matching members two levels below the directory
   the extraction mapping had stripped. A zip holding several mods installed as
   `Mods/<first-id>/ModA/`, `ModB/` -- a folder no game loads -- and the plugin
   could not even uninstall it afterwards, because `status()` scans only the
   top level it had just skipped. Now the mod root comes from the manifest
   member itself, and more than one mod in one archive is refused with
   `E_MULTI_MOD_ARCHIVE` instead of silently picking one.

   Found by Round 62; see `docs/ARCHIVE_LAYOUT.md`.

   Round 63 checked the other half. `.7z` has its own extractor
   (`file_drop._inspect_7z`) written in parallel with the ZIP one, so the ZIP
   fix proved nothing about it by itself. A device probe that built seven
   archives with the console's own `/usr/bin/7z` ran them through the deployed
   plugin: 41/41 checks pass, including the deep-wrapper case landing at
   `Mods/probe.twice/` with `manifest.json` on top and all three multi-mod
   shapes refused with nothing written. No product code changed for it -- the
   round existed to stop assuming.

0h. **A declared `EntryDll` is now checked against the archive (round 64).**
   `ParsedManifest.entry_dll` was parsed and then never compared to anything;
   `parse_manifest()` had no callers, so the value did not even reach the panel.
   A package naming a DLL it does not ship installed, appeared as installed and
   enabled, and never loaded -- and a traversal path like `../../etc/passwd` was
   accepted. `manifest.check_entry_dll()` now runs on both the ZIP and `.7z`
   readers: an absent DLL is `E_MANIFEST_INVALID`, an escaping one is
   `E_MANIFEST_UNSAFE`, and a mod with no `EntryDll` (content pack) is untouched.
   Twelve fixtures that declared a DLL they never shipped were corrected -- the
   check was right and the fixtures described impossible packages. Proven by
   `tests/test_entry_dll.py` (14 cases), a nine-failure negative proof, and ten
   true booleans against the deployed plugin on the Deck.

### `0i.` Undoing an uninstall reported success without restoring anything

`rollback(txn)` of an uninstall guarded the restore with
`if os.path.isdir(qdir) and not os.path.isdir(src)`, then wrote
`MOD_ROLLBACK_RESTORED` and committed the transaction regardless. On the device
that produced `ok:True / restored 'probe.reinstall'` in two cases where nothing
was restored: the user had reinstalled the mod (so a *different* version was on
disk), and the quarantined copy had been cleaned up (so nothing was on disk).
The second is the dangerous one -- the journal then treated the real bytes as an
orphan, and round 54's `reclaim_quarantine` may delete orphans, so a false
success fed user data to a deleter.

Both engines now refuse with `E_MOD_NOT_FOUND` / `E_PATH_INVALID` /
`E_FILE_COLLISION` before recording anything, and clear the emptied transaction
folder with `os.rmdir` (the round 56 lesson: quarantine litter gets counted and
offered for deletion). No new error codes. Proven by
`tests/test_rollback_undo.py` (9 cases), a 7-failure negative proof whose plain
case still passes, and 18 checks against the deployed plugin. Details:
`docs/ROLLBACK.md`.

### `0j.` A disabled dependency was downloaded over and still reported missing

Round 66. `.decky-disabled/` is a sibling of `Mods/`, and
`scan_installed_mods()` only walks the root it is handed, so a dependency the
user had parked fell into `missing_dependencies` -- the exact list `main.py`
hands to `fetch_dependencies`. On the device, with the network handlers injected
so nothing left the machine:

    PARKED_VERSION_BEFORE  1.0.0
    FETCH_INSTALLED        1              # deps.run says "resolved"
    PARKED_VERSION_AFTER   1.1.0          # the parked copy was replaced
    MISSING_AFTER          ['probe.thedep']   # still reported as missing

Two harms that are worth separating: the user's "off" switch was overwritten by
a download they never asked for, and the panel then reported failure *after*
mutating their data. The mod was never missing -- it was installed, owned,
visible, and switched off, so the remedy is one tap, not a fetch.

`scan_installed_mods()` now takes the known parked ids and answers with two
lists: `missing_dependencies` (nobody provides it -> download) and
`parked_dependencies` (the user disabled it -> enable it). `status()` scans the
parked root first so the active scan can be told the difference, and the panel
renders the second list with the action that fixes it. No new error code; the
fetcher keeps its contract and simply stops being handed ids it must not touch.
Tests: `tests/test_parked_dependencies.py` (9 cases) including one that runs the
real `deps.run()` and asserts no fetch is attempted at all. Details:
`docs/PARKED_DEPENDENCIES.md`.

0k. A dependency that is present but too old used to be invisible (Round 67).

    `ParsedManifest` read `{"UniqueID": "...", "MinimumVersion": "2.0.0"}` and
    kept only the id; the version half was discarded in the same expression.
    `scan_installed_mods()` now compares it against the version it already reads
    from the dependency's manifest and reports
    `outdated_dependencies: [{from, id, required, installed}]`, both globally and
    per row. On the deployed build a synthetic host requiring `>= 2.0.0` of an
    installed `1.0.0` dependency is now reported 12/12; the previous build said
    "nothing missing". Three deliberate limits: a version with no digits is
    "unknown" not "too old"; comparison is numeric (`2.0 == 2.0.0.0`); only
    declared minimums are compared and the field name comes from the descriptor.
    No update is performed and the fetcher was NOT taught about this state --
    the same one-decision-one-place rule as round 66. All 28 real mods were
    surveyed: 18 declarations, 10 satisfied, 8 absent, 0 present-but-too-old, so
    this state is currently unreachable on the real tree.
    See docs/OUTDATED_DEPENDENCIES.md.

0l. An interrupted install is now undoable (Round 68).

    `_install_inner` moves the previous copy into the transaction's quarantine
    folder and only then unpacks the new one. A crash between those two renames
    leaves `Mods/<dir>` absent and the user's only copy at
    `<quarantine>/<txn>/<dir>.replaced`, with nothing in the journal but
    `PREPARED`/`APPLYING`.

    Measured on the deployed build: the write gate was right
    (`E_RECOVERY_PENDING`), `recovery()` listed the transaction, and
    `rollback(txn)` answered `{"recovered": true}` -- while
    `MOD_BACK_AFTER_ROLLBACK` stayed `False`. The quarantine then classified
    that copy `orphan` / `restorable: false`, and orphans are what
    `reclaim_quarantine` may delete. A second probe showed the same folder
    called an orphan after a *successful* upgrade, while `rollback(txn)`
    restored it (`VERSION_AFTER_ROLLBACK 1.0.0`).

    Both halves now read one record: the pending branch goes through
    `upgrade.undo_install()` with `_replaced_copy_for(txn)`, and
    `quarantine.referenced_txns()` counts `MOD_INSTALLED` rows that displaced
    something plus pending transactions. `tests/test_crash_recovery.py` (9
    cases) pins it; one round-56 test that *required* the defect was rewritten
    rather than deleted. See `docs/CRASH_RECOVERY.md`.

0m. A failed install or upgrade says what actually happened (Round 69)

Measured on the device, then fixed in two steps.

* A failed **upgrade** left the NEW version on disk, kept the old one in the
  quarantine, and answered `E_UNKNOWN nothing to roll back for txn ... (state=ROLLED_BACK)`
  if the user tried to undo it. The handler had only one branch -- "this was a
  first install, delete the leftover" -- so an upgrade fell through it. It now
  puts the displaced copy back before it reports anything, and if that restore
  fails it says `E_ROLLBACK_FAILED` instead of pretending (`docs/FAILED_INSTALL.md`).
* The same handler asked `_existing_managed()` before cleaning up, i.e. it asked
  the journal whether we own the mod instead of asking what this transaction did.
  A journal row whose folder is gone (deleted by hand, library not mounted, a
  different tree active) made a first install look like an upgrade, and its
  failure left the half-written folder inside `Mods/`. Cleanup is now guarded by
  a `placed` flag that only the write path sets.

Evidence: `tests/test_failed_install.py` (14 cases, one of them seeding a
journal row with no folder), a mutation run that flips the cleanup back and
fails exactly the new case, and 21/21 device checks including
`E2_NOTHING_LEFT_BEHIND ['probe.upgradefail']`.

0n. A restore recorded a remembered identity, not the disk.

    `rollback` of an uninstall copied the `mod` dictionary out of the record of
    the transaction being undone, so after the folder's contents had been
    replaced by another mod the journal still named the old one (with
    `version: null`) while the scanner reported the new one -- and the next
    install moved the impostor folder into the quarantine as "the old copy".
    A single `_read_dir_identity()` helper now reads the manifest of the folder
    that came back, and the three restore branches use it. When the folder
    holds a different mod the restore still succeeds but says so
    (`restored_uid`, `expected_uid`, `note`) and does not claim ownership.
    8 new cases in tests/test_restore_identity.py; 23 device checks on the
    deployed plugin; see docs/RESTORE_IDENTITY.md.

0o. A failed rollback was a dead end with a false promise.

    `E_ROLLBACK_FAILED` told the user their data was preserved and marked
    the transaction `rollback_available=True`, yet `rollback(txn)` replied
    `E_UNKNOWN "nothing to roll back … (state=ROLLBACK_FAILED)"` and
    `recovery()` did not list it. Worse, a stuck txn whose `.replaced`
    folder had vanished fell through an older branch that answered
    `ok({recovered: true})` without restoring anything.
    The upgrade and interrupted-install branches now accept
    `ROLLBACK_FAILED`; a standalone retry branch owns the decision and
    shares one `_restore_displaced()` helper with them. With no copy left
    it refuses and names the quarantine folder. `journal.stuck()` is
    separate from `pending()` so a stuck txn is visible without freezing
    every other write; `referenced_txns()` counts it so reclaim cannot
    delete the last copy. 10 new cases in tests/test_stuck_rollback.py;
    two mutations of the fix both fail the new tests while ordinary cases
    still pass; see docs/STUCK_ROLLBACK.md.

0p. The panel promised an update action the plugin does not have (Round 40).

    Round 67 added `outdated_dependencies` reporting with the user-facing
    wording "Dependencies too old: {v} (update them)" / "依赖版本过旧：{v}（请更新）".
    But `fetch_dependencies` reads ONLY `state.missing_dependencies` -- an
    outdated dependency never enters that flow, so pressing the download
    button answered "no required dependency is missing". The panel told the
    user to do something that had no button. Rather than add an automatic
    upgrade path (which would treat "latest in a repo" as "the version this
    host asked for", risk overwriting a parked copy, and add an RPC to a
    28-RPC contract), the wording was corrected to name the action that
    DOES exist: download a newer copy and import it here, which goes through
    the normal manifest-verified upgrade flow. Three tests in
    tests/test_outdated_dependencies.py pin the honesty (no false promise in
    en/zh/index.tsx, text names the import path, fetcher still ignores
    outdated); reintroducing the old strings fails them while plain cases
    pass. No backend or RPC change; Deck unreachable this round so no device
    rebuild -- the frontend string change reaches the panel on the next
    connected build.

0q. A dependency published only as .7z was silently unfetchable (Round 41).

    The engine installs `.7z` end-to-end (round 63, 41/41 device checks) and
    goal item 3 asks for ".zip and .7z", but `deps.candidate_assets` filtered
    release assets on `.zip` only. A dependency whose repo published a single
    `.7z` was reported `no_zip_asset` and never fetched -- a capability gap
    presented as a content policy. The filter now accepts `.zip` and `.7z`
    (including the octet-stream label GitHub often uses), but the acceptance
    authority is unchanged: `verify_candidate` still opens the archive and
    requires the manifest UniqueID to match. `.rar`/`.exe` stay refused. The
    wire key and i18n key are unchanged for compatibility; only the English
    and Chinese reason wording now says "zip or 7z". Six offline tests in
    tests/test_deps_7z.py; reverting the filter fails the three `.7z` cases
    while ordinary deps tests pass. 850 tests OK, compileall 0, seven
    validators 0. Deck unreachable this round: offline-verified only, no
    device claim. See docs/DEPENDENCIES.md.

## Closed since this page was written

- **The import surface could only see its own inbox.** The plugin read
  `${DECKY_DATA}/inbox` and nothing else, while the Game Mode browser saves
  to `$XDG_DOWNLOAD_DIR`. Game Mode has no file manager, so "download the
  mod, then import the ZIP" was an instruction the user could not follow.
  Round 42 added `deckymod/import_root.py`: a declared, bounded, read-only
  set of extra roots (`mod_package.import_roots` in the descriptor, inbox
  always first). It never walks `$HOME` — that would be both slow and a
  privacy problem — and it refuses symlinks. Measured on the device:
  `root: "downloads"` now appears next to the 13 inbox entries.

0c. ~~**An upgrade could not be undone.**~~ **SHIPPED in Round 56** (`docs/UPGRADE.md`). `_install_inner` had always recorded `replaced_old`, the quarantine path the previous copy was moved into, and nothing read it. On the device a 1.0.0 -> 2.0.0 upgrade followed by `rollback` answered "nothing to roll back for txn ... (state=COMMITTED)", left 2.0.0 on disk, and turned the 1.0.0 folder into a quarantine ORPHAN -- which is exactly what Round 54's `reclaim_quarantine` is allowed to delete. Two separately correct features combined into losing the user's old version. The fix is a `MOD_INSTALLED` branch in each engine's `_rollback_inner`, sharing `deckymod/upgrade.py::undo_install`, which refuses a symlinked destination rather than shadowing it, refuses a source that left the quarantine, and cleans up the emptied transaction folder so it does not become fresh litter.

0d. ~~**Upgrading a DISABLED mod silently re-enabled it and duplicated it.**~~ **SHIPPED in Round 57.** In the file_drop engine a mod is disabled by moving its folder to `.decky-disabled/`, and `install == enable` because the directory's LOCATION is the state. `_install_inner` computed `target = Mods/<dir>` and checked only that path, so upgrading a parked mod saw nothing there, unpacked a second copy into `Mods/` -- turning the mod back ON -- and left the old version parked. Measured on the device:

    MODS_AFTER   ['someone.parkable']       # 2.0.0, now enabled
    PARKED_AFTER ['someone.parkable']       # 1.0.0
    SAME_UID_COPIES 2
    STATUS_DUP_IDS []                       # not even reported
    REENABLE_CODE  E_FILE_COLLISION         # wedged

Two harms in one: the user's decision to disable the mod was reversed without being asked, and one UniqueID existed twice, which SMAPI loads both of. The rule is now "the new bytes go where the old bytes are": a parked mod stays parked and only its version changes, `MOD_ENABLED` is not written for a copy that stayed parked, `duplicate_ids` also consults the disabled root, and a foreign folder parked under the same name is a collision rather than an overwrite. `tests/test_duplicate_guard.py` had a test that asserted the old behaviour; it was rewritten, not deleted.

0e. ~~**Uninstalling a DISABLED mod reported success and moved nothing.**~~ **SHIPPED in Round 58.** `status().state.disabled_mods` lists parked mods, so the panel offers them, so uninstall has to work on them. Every lookup in `_uninstall_inner` resolved into `Mods/` only, and the execute branch guarded the move with `if os.path.isdir(src): os.replace(...)`. For a parked source that guard was false, so the move was skipped -- while the transaction was opened, `MOD_UNINSTALLED` was written and the call returned `ok:True`. Measured on the device:

    UNINSTALL_OK      True
    MODS_AFTER        []
    PARKED_AFTER      ['someone.parkuninstall']     # still there
    QUARANTINE_TXNS   ['20261117T185221-0d2dc400']  # a txn was opened
    AFTER_STATUS_DISABLED ['someone.parkuninstall'] # still listed

So the plugin forgot a mod it had not removed: `journal.installed()` dropped the id, which is the same silent corruption the duplicate guard exists to prevent, just in the other direction. Two corrections -- resolve the parked path when the recorded dir is not on disk, and refuse with `E_MOD_NOT_FOUND` when the folder is nowhere, instead of reporting success. The `if os.path.isdir` guard was replaced with a raise, so the shape cannot come back.

0f. ~~**The import preview named a destination the install would not use.**~~ **SHIPPED in Round 59.** Rounds 57-58 were the same root cause twice: in the file_drop engine "disabled" is a LOCATION, not a flag, and several paths resolved one root only. Round 59 stopped finding them by hand and asked the machine instead -- every function in both engines was scanned for which roots it mentions (`TOTAL_FUNCS_WITH_ROOTS 19`, `BOTH_ROOTS 4`, `MOD_ONLY 9`). That surfaced the last real one.

`inspect()` is the preview the confirm dialog is built from, and it still computed `targets.w2_install_dir` as `Mods/<dir>` while `_install_inner` had moved to landing parked mods in `.decky-disabled/`. Measured on the device:

    PREVIEW_TARGET        .../Mods/someone.parkinspect
    PREVIEW_DUPLICATE     True
    PREVIEW_SAME_UID_DIRS []
    REAL_DIR              .../.decky-disabled/someone.parkinspect
    PREVIEW_MATCHES_REAL  False

The user agreed to one sentence and a different operation ran. A preview that disagrees with its execute is worse than no preview, because consent was given for the text on screen. The preview now resolves the same target install does, carries `conflict.parked`, says "(this mod is disabled, the new version stays disabled)" when that applies, and counts parked copies in `same_unique_id_dirs` so the warning appears before the refusal rather than after it.

0f. **Three rounds, one shape (round 60).** Rounds 57, 58 and 59 each fixed
a different consequence of the same fact: in the file_drop engine "disabled" is
a location, and three code paths computed it separately. One helper now answers
it and `tests/test_single_path_decision.py` asserts the structure, with a
negative proof that reintroducing the duplication fails the suite. See
`docs/PATH_DECISION.md`.

## P0 — must exist before this is safe to hand to a stranger

0b. ~~**The first install on a fresh game failed, and "not found" said the
   opposite of what happened.**~~ **SHIPPED in Round 52**
   (`tests/test_first_run.py`). Both were found on the device by asking what a
   user who has never installed a mod meets first. A game that has never had a
   mod has no `Mods/` folder, and `os.replace(staged, target)` fails with
   ENOENT when the target's parent is missing, so the very first import died
   with `E_OP_FAILED` naming a staging path. And every "no such mod" answer
   was `E_DUPLICATE`, whose message is "already installed, use Replace" --
   reachable from uninstall, disable and enable with any mistyped name. That
   now has its own code, `E_MOD_NOT_FOUND` (the 51st), because none of the
   existing 50 could say it without lying.

0. ~~**`refuse_if_game_running` was a promise the code did not keep.**~~
   **SHIPPED in Round 50** (`deckymod/procs.py`, see `docs/RUNNING_GAME.md`).
   The descriptor said `true` since Round 39 and all four destructive call
   sites were present, but the only implementation read
   `DECKYMOD_GAME_RUNNING` -- a test seam that production never sets. So a
   mod could be uninstalled with the game holding its `.dll` files open, the
   one failure a rollback cannot repair. Now decided from `/proc`
   `argv[0]` (marker basename, or a path inside `GAME_ROOT`), with
   `unknown` kept distinct from `stopped`. Proven on the device with a
   stand-in launcher: `GATE_OK=False CODE=E_GAME_RUNNING`.

1. ~~**Second-writer detection is Stardew-specific and marker-based.**~~
   **SHIPPED in Round 44** (`deckymod/modwatch.py`, see
   `docs/MOD_FOLDER_OWNERSHIP.md`). The marker list was replaced by a
   structural survey of `Mods/` itself: is the folder a symlink, are any of its
   children symlinks, is it on another device. Measured on the device, the two
   Amethyst markers are now *absent*, which had turned the old check into a
   constant `False` — the failure mode a filename list always has. The same
   `E_EXTERNAL_MANAGER` code is raised, from a signal that does not need to
   know the other manager's name.
2. ~~**The dependency resolver only goes one level deep.**~~ **Depth SHIPPED in
   Round 45**; the stale index is still real. `deps.run()` now re-asks "what is
   still missing" after each round of installs, so a dependency of a
   dependency gets resolved too — bounded by `MAX_ROUNDS = 3`, with every row
   carrying the `round` it was resolved in and the result carrying
   `still_missing` plus a `note` that distinguishes "ran out of rounds" from
   "nothing on the index offers them". The index problem is untouched and
   unfixable from here: `selph.ExtraMachineConfig` is mapped by the SMAPI index
   to a repository that does not contain it (verified twice with
   `per_page=100`). Today that produces an honest refusal. It would stop being
   honest the moment someone "fixes" it by accepting the first plausible ZIP —
   see `DEPENDENCIES.md` for why only the downloaded manifest can authorise an
   install.
3. ~~**`E_EXTERNAL_MANAGER` makes the whole write surface unreachable on this
   device.**~~ **SHIPPED in Round 55** (`deckymod/handover.py`, see
   `docs/HANDOVER.md`). A user whose `Mods/` is deployed by another manager now
   gets one guided action instead of a dead end: symlinked entries inside
   `Mods/` and the marker file the descriptor names are moved into the
   quarantine under a single transaction, and Rollback puts them back. It
   refuses as a whole — moving nothing — when the obstacle cannot be undone in
   one step (`Mods/` itself is a symlink, a marker *directory* sits beside the
   game, the folder is on another device), because half a handover leaves the
   other manager's deployment partly dismantled and the folder still unmanaged.
   Nothing is ever deleted, and it never runs on a schedule or during
   `status()`: only a user pressing the button and then confirming starts it.
4. ~~**Nothing verifies what the game actually loaded.**~~ **SHIPPED in Round 40** (`deckymod/loaderlog.py`, see `docs/LOADER_LOG.md`). The plugin knows what is
   in `Mods/`; it cannot know what SMAPI accepted. The one real proof we have
   (`[18:57:19 TRACE SMAPI] SDV-HD2D ... Patches: 12 groups installed.`) was
   read by hand from a log file. Reading `${GAME_ROOT}/SMAPI-latest.txt` and
   surfacing "loaded / skipped / errored" per mod is the single highest-value
   addition, because it turns "installed" into "working".

## P1 — required for the plugin to be trusted with more than one game

5. **Only Stardew Valley has a write path.** Every other game is identified
   read-only by design (`templates.py` returns `identification_only`). That is
   the right default. The missing piece is a documented, tested recipe for
   adding a descriptor — the README sketch is not yet exercised by a second
   real game, so its shape is unproven.
6. ~~**No conflict detection beyond duplicate UniqueIDs.**~~ **SHIPPED in Round 47** -- see `docs/MOD_FOLDER_CONFLICTS.md`. Shared paths are reported for `shared_tree` loaders and honestly declared inapplicable for per-mod-directory ones; nothing is reordered. Two mods editing the
   same game file, or load-order-sensitive mods, are silently accepted. The
   plugin should not solve ordering (that needs game knowledge), but it should
   at least report "these two mods both ship `X.dll`".
7. ~~**Rollback has no expiry and no storage bound.**~~ **Gap closed in Round 54**
   for the part that mattered. Measured in Round 48 (`docs/QUARANTINE.md`): the
   risk was not disk-full -- the whole quarantine is 1.3 MB on a 64 GB Deck --
   it was *unreachable* data. 29 of 45 folders had no `MOD_UNINSTALLED` record
   left in the journal, so nothing could restore them, and 16 of those held real
   files (four held a 114 KB mod). The audit reported this and deliberately
   deleted nothing, because "nobody claims this" is answered by the journal and
   a rotated journal looks identical to "nothing claims any of these".
   `reclaim_quarantine(txns, after_confirm)` now lets the user say "yes, drop
   these" -- naming each transaction id, only for `orphan` entries, behind every
   write gate, with a two-phase confirm. **Still open:** nothing expires a
   *restorable* folder either, so a quarantine can still hold every uninstall
   forever; that is a policy decision (how long is a rollback worth keeping?)
   this round did not make.

## P2 — needed for a real release, not for correctness

8. **No update check. The hooks are now pinned (Round 61).**
   The lifecycle hooks (`main.py` `_unload` / `_uninstall` / `_migration`) only
   drop in-memory state; they do not touch the game folder. That used to be an
   untested promise, and it is now asserted from two directions:
   `tests/test_lifecycle_hooks.py` fingerprints every file under the synthetic
   game tree (size, mtime, sha256) before and after each hook, and an AST check
   forbids the hooks from naming any write primitive at all. Both were proven
   to fire by injecting a plausible "cleanup" line into `_uninstall`.

   `tests/test_import_order.py` pins a neighbouring trap: unittest imports every
   module before running any of them, so a module-level
   `os.environ.pop("DECKYMOD_GAME_ID")` silently unpins the 33 historical
   RimWorld cases. That had been fixed by hand three times (rounds 47, 50, 61).

   What is genuinely still missing is an update check: a stale plugin has no way
   to tell its user it is stale.
9. **The panel has never been seen by a human in Game Mode.** Every claim
   about layout comes from DOM text captured over CDP. Reading text is not the
   same as looking at it, and it cannot prove the D-pad reaches every control.
10. ~~**No CI on the frontend.**~~ **SHIPPED in Round 46.**
    `.github/workflows/build.yml` now runs `pnpm run typecheck`
    (`tsc --noEmit`, `strict`) before `pnpm run build`. The script existed from
    the start and was never called; rollup does not type-check, so three
    `TS2304 Cannot find name` defects reached `main` behind two green CI jobs
    and were caught by a Deck build afterwards. A local pre-check
    (`USED_BUT_UNIMPORTED` in `r19_frontend_preflight.py`) now covers the same
    shape offline, and was proven to fire by deleting an import on purpose.

## Deliberately not planned

- Installing BepInEx / SMAPI / xNVSE. That edits a Proton prefix or a launch
  option, both of which the plugin refuses on principle.
- Cloud sync, accounts, telemetry.
- A universal "one-click install any game" claim. The registry is per-game on
  purpose; pretending otherwise is how mod managers break people's saves.
- Any bypass of a Nexus account restriction. The 403 is a policy, not a bug.
