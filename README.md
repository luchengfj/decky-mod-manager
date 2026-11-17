# Decky MOD Manager

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin that manages game mods from the
Steam Deck Quick Access Menu (QAM) in Game Mode — gamepad only, no terminal, no root.

It answers one question: **which mods does this game actually have, and can I turn them on and off?**
It reads the Steam library and the game's mod folder, imports a mod, enables or disables it, uninstalls it,
and rolls back an install that went wrong.

> **Scope, honestly stated.** One game is fully managed today: Stardew Valley (AppID 413150) with SMAPI,
> and even there the plugin is **detect-only** — it never installs SMAPI, never edits your launch options,
> and never writes into a Proton prefix. Every other game in your library is **identified read-only**: the
> plugin tells you which folder that game's mods live in and how many are there, and refuses to write.
> There is no universal one-click install, and this README will not pretend otherwise.

## What it does

| Area | Behaviour |
| --- | --- |
| **Library** | Lists installed Steam games from every library folder, including SD cards mounted at either `/run/media/mmcblk0p1` or `/run/media/<user>/mmcblk0p1`. Identifies each game's mod directory from its own manifest, never by guessing a folder list. |
| **Mods on disk** | Shows what is actually in the mod folder right now — including mods you installed yourself, which the plugin has no record of. Dot-directories are ignored, because loaders ignore them. |
| **By game** | Groups your installed mods per game, so a library with several modded games is readable instead of one flat list. |
| **Import** | Takes a local ZIP (and `.7z` on a device that has `/usr/bin/7z`), rejects path traversal, symlinks, executable installers, and archives that expand beyond a size cap. A wrapper directory inside the archive is stripped automatically. |
| **Install / enable / disable / uninstall** | Moves the mod directory between the game's mod folder and a sibling park directory on the same filesystem — so it is an atomic rename, not a copy. |
| **Rollback** | Every mutation is journalled. A bad install can be rolled back to the exact previous state, or the plugin reports honestly that it could not. |
| **Dependencies** | Reads each mod's declared dependencies, reports which are missing, and can fetch a missing dependency **only** when the downloaded archive's own manifest names the same mod ID. |
| **Download (optional)** | HTTPS download from an allow-listed host into an inbox, then the same import path. Two-phase: a read-only plan, then an explicit confirm. |
| **Errors** | 50 stable error codes, each with a category and a suggested next step, shown in the QAM — never a raw traceback. |

## Hard limits (by design, not by accident)

- **No root, ever.** The plugin runs as the Decky user and does not escalate.
- **No `steamos-readonly disable`.** Nothing in this plugin touches the read-only root filesystem.
- **No loader installation.** SMAPI, BepInEx, xNVSE and friends are *detected*, never installed or updated.
- **No launch-option editing.** If a loader needs a launch option, you set it in Steam; the plugin only reports that it is missing.
- **No Proton prefix writes.** Mod files go into the game's mod folder, not into `compatdata`.
- **No cloud, no account sync, no telemetry.** The plugin has no server of its own and stores nothing off-device.

## Repository layout

```
main.py                  Decky plugin entry point; all public RPCs (positional args, JSON-safe envelopes)
deckymod/                Backend, standard library only
  engine.py               XML-list engines (enable/disable by editing a state file)
  smapi.py, file_drop.py  File-drop engines (enable/disable by directory presence)
  manifest.py             Manifest parsers, driven entirely by the game descriptor
  archive.py, sevenzip.py Archive inspection, limits, extraction
  download.py             HTTPS with a host allow-list, size cap, TLS bundle union
  deps.py                 Dependency resolution; accepts only a manifest-verified download
  paths.py, steamlib.py   Steam library discovery and path resolution
  journal.py, registry.py Transaction journal and game/loader descriptors
registry/                Game and loader descriptors (JSON); adding a game means adding a file
src/                     Frontend (TypeScript + React), QAM panel
tests/                   Standard-library self-tests over synthetic Steam trees
docs/                    Design notes, verification records, acceptance criteria
```

## Building

```bash
pnpm install --frozen-lockfile
pnpm run typecheck     # tsc --noEmit, strict
pnpm run build         # rollup -> dist/index.js
```

Then package the plugin directory (with `dist/index.js`, `main.py`, `deckymod/` and `registry/`) as a ZIP and
install it with Decky Loader's "Install from ZIP", or drop it into `~/homebrew/plugins/`.

CI (`.github/workflows/build.yml`) runs the backend self-tests, validates every registry JSON file, and builds
the frontend on every push.

## Adding a game

A game is a JSON descriptor, not a code change:

```json
{
  "id": "mygame",
  "status": "planned",
  "identity": { "appid": 123456, "name": "My Game" },
  "paths": { "mod_root": "${GAME_ROOT}/Mods" },
  "mod_package": {
    "manifest_globs": ["manifest.json", "*/manifest.json"],
    "manifest_format": "json",
    "id_extraction": { "json": "UniqueID" }
  },
  "state_mutator": { "strategy": "file_drop" }
}
```

Drop it in `registry/games/` and add it to `registry/registry.json`. `status: "planned"` keeps it discoverable
in the UI but refuses writes until you have verified the paths on a real install.

## Status and documentation

This is a working plugin, not a finished product. What is proven on real hardware, what is only proven in
tests, and what is still open is recorded per item in [`docs/VERIFICATION.md`](docs/VERIFICATION.md);
[`docs/ACCEPTANCE.md`](docs/ACCEPTANCE.md) holds the acceptance criteria. Start at
[`docs/README.md`](docs/README.md) for the index.

Known gaps, stated plainly:

- Stardew Valley is the only game with a write path, and it is detect-only.
- The Nexus Mods integration is **not** included; see [`docs/NEXUS_ROADMAP.md`](docs/NEXUS_ROADMAP.md) for why
  (free accounts cannot obtain a download link through the API) and what a manual `nxm://` hand-off would require.
- Dependency resolution goes one level deep. A dependency that itself needs a dependency is not chased.

## License

See [LICENSE](LICENSE).
