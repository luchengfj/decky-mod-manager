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
| Enable / disable / uninstall / roll back | works (folder move in and out of the game's `Mods/`) |
| See required dependencies and download the ones that are fetchable | works, one level deep |
| Download mods | GitHub Releases + direct HTTPS URL only |
| Nexus | **metadata only** — browse and open the mod page; download links are premium-only, by Nexus policy |
| Chinese / English UI | works, 409 keys each, parity enforced |

## P0 — must exist before this is safe to hand to a stranger

1. **Second-writer detection is Stardew-specific and marker-based.**
   `deckymod/smapi.py::_check_write_allowed()` looks for `.mm_deployed` and
   `Mods_Core/`, which is how *Amethyst* announces ownership. Any other mod
   manager, or a user who keeps both tools in different moods, is invisible.
   The honest fix is a pre-write stat of `Mods/` compared against the last
   observed state, not a longer list of magic filenames.
2. **The dependency resolver only goes one level deep and trusts an index that
   is provably stale.** `selph.ExtraMachineConfig` is mapped by the SMAPI index
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
4. **Nothing verifies what the game actually loaded.** The plugin knows what is
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
6. **No conflict detection beyond duplicate UniqueIDs.** Two mods editing the
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
