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
| Enable / disable / uninstall / roll back | works (folder move in and out of the game's `Mods/`) |
| See required dependencies and download the ones that are fetchable | works, up to 3 levels deep (Round 45) |
| Download mods | GitHub Releases + direct HTTPS URL only |
| Nexus | **metadata only** — browse and open the mod page; download links are premium-only, by Nexus policy |
| Know whether the game actually loaded a mod (not just that it is on disk) | works, read-only (Round 40, docs/LOADER_LOG.md) |
| Refuse writes when Mods/ belongs to another manager, and say why | works, structural (Round 44, docs/MOD_FOLDER_OWNERSHIP.md) |
| Chinese / English UI | works, 448 keys each, parity enforced |

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

## P0 — must exist before this is safe to hand to a stranger

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
3. **`E_EXTERNAL_MANAGER` makes the whole write surface unreachable on this
   device.** The plugin is correct to refuse. But a user who does not know what
   Amethyst is will see "read-only" everywhere and conclude the plugin is
   broken. A guided "hand ownership over" flow — which parks the deployed mods
   into `.decky-disabled/`, never deletes them — is the missing piece. It must
   stay a user action with a confirm, never something the plugin decides.
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
7. **Rollback has no expiry and no storage bound.** Snapshots and the
   quarantine grow without limit. On a 64 GB Deck that is a slow-motion disk
   full, and `E_NO_SPACE` already exists because it was expected.

## P2 — needed for a real release, not for correctness

8. **No install lifecycle.** There is no update check, no version migration
   hook beyond `_migration`, and no way to uninstall the plugin while leaving
   the user's mods untouched — documented, but not enforced by a test.
9. **The panel has never been seen by a human in Game Mode.** Every claim
   about layout comes from DOM text captured over CDP. Reading text is not the
   same as looking at it, and it cannot prove the D-pad reaches every control.
10. **No CI on the frontend.** `.github/workflows/build.yml` builds it, but the
    type check that caught eight real `strict` null-payload errors only runs
    when someone remembers to run it on a device with `node_modules`.

## Deliberately not planned

- Installing BepInEx / SMAPI / xNVSE. That edits a Proton prefix or a launch
  option, both of which the plugin refuses on principle.
- Cloud sync, accounts, telemetry.
- A universal "one-click install any game" claim. The registry is per-game on
  purpose; pretending otherwise is how mod managers break people's saves.
- Any bypass of a Nexus account restriction. The 403 is a policy, not a bug.
