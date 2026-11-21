# Decky MOD Manager

中文 | [English](README.md)

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin that manages game mods from the
Steam Deck Quick Access Menu (QAM) in Game Mode — gamepad only, no terminal, no root.

It answers one question: **which mods does this game actually have, and can I turn them on and off?**
It reads the Steam library and the game's mod folder, imports a mod, enables or disables it, uninstalls it,
and rolls back an install that went wrong.

> **Scope, honestly stated.** Three tiers of game support, one active at a time:
>
> 1. **Stardew Valley** (AppID 413150) with SMAPI — the `file_drop` engine: one folder per mod into
>    `Mods/`, with enable / disable / uninstall / rollback. SMAPI itself is **detect-only** — the plugin
>    never installs it and never edits launch options.
> 2. **Cyberpunk 2077** (AppID 1091500) — the `root_merge` engine: a mod archive is routed **file by file**
>    into declared write roots (`archive/pc/mod`, `mods/`, `bin/x64/plugins`, `r6/scripts`, `red4ext`),
>    never into game payload; every file is journaled and anything replaced is backed up, so uninstall and
>    rollback are exact.
> 3. **Any other Steam game, configured by you** — the panel asks where that game's loader reads mods from;
>    the same `root_merge` engine then writes only inside the folder you picked. Games with anti-cheat are
>    refused outright, and a game you configure never gets a loader installed silently: the panel opens the
>    loader's official download page, and only extracts the ZIP **you** downloaded, with your explicit tap.
>
> Exactly one game is managed at a time (`switch_game` moves the panel between supported games). There is
> no universal one-click install, and this README will not pretend otherwise.

## What it does

| Area | Behaviour |
| --- | --- |
| **Library** | Lists installed Steam games from every library folder, including SD cards mounted at either `/run/media/mmcblk0p1` or `/run/media/<user>/mmcblk0p1`. Identifies each game's mod directory from its own manifest, never by guessing a folder list. |
| **Mods on disk** | Shows what is actually in the mod folder right now — including mods you installed yourself, which the plugin has no record of. Dot-directories are ignored, because loaders ignore them. |
| **By game** | Groups your installed mods per game, so a library with several modded games is readable instead of one flat list. |
| **Switch games** | Stardew and Cyberpunk ship as descriptors; any other game can be configured once (you name the mod folder) from the Games section. Switching rewrites `active_game` atomically and rebuilds the engine — no restart. A wrong configuration can be changed or removed from the panel. |
| **Import** | Takes a local ZIP (and `.7z` on a device that has `/usr/bin/7z`), rejects path traversal, symlinks, executable installers, and archives that expand beyond a size cap. A wrapper directory inside the archive is stripped automatically. For Cyberpunk and user-configured games the archive is routed file-by-file into the declared mod folders instead. |
| **Install / enable / disable / uninstall** | Moves the mod directory between the game's mod folder and a sibling park directory on the same filesystem — so it is an atomic rename, not a copy. |
| **Rollback** | Every mutation is journalled. A bad install can be rolled back to the exact previous state, or the plugin reports honestly that it could not. |
| **Dependencies** | Reads each mod's declared dependencies, reports which are missing, and can fetch a missing dependency **only** when the downloaded archive's own manifest names the same mod ID. |
| **Download (optional)** | HTTPS download from an allow-listed host into an inbox, then the same import path. Two-phase: a read-only plan, then an explicit confirm. |
| **Loader hand-off** | In the mod-folder setup screen: open a loader's official download page (BepInEx 5 / BepInEx 6 IL2CPP / MelonLoader, fit-ranked by the game's Unity flavour), then extract the ZIP you downloaded — one tap, per-file journal, backups, removable. Built-in games and launch options stay out of reach. |
| **Delete source ZIP** | The import and loader confirm dialogs offer "install and delete the ZIP" — a separate, explicit action (never automatic), restricted to files inside the declared import roots. |
| **Errors** | 52 stable error codes, each with a category and a suggested next step, shown in the QAM — never a raw traceback. |

## Hard limits (by design, not by accident)

- **No root, ever.** The plugin runs as the Decky user and does not escalate.
- **No `steamos-readonly disable`.** Nothing in this plugin touches the read-only root filesystem.
- **Loader installation, scoped.** For every built-in game (Stardew, Cyberpunk) SMAPI, BepInEx,
  xNVSE and friends are *detected*, never installed — unchanged. For a game **you configure**,
  the panel may open the loader's official download page and extract the ZIP you downloaded into
  the game folder: two-phase confirmed, journaled per file, backed up, removable like any mod
  (Round 79; a user-approved scoping of the old "never, for every game, permanently" rule).
  Steam launch options are **still never edited** — if a loader needs `WINEDLLOVERRIDES`, the
  panel shows the text and you paste it in Steam yourself.
- **No launch-option editing.** If a loader needs a launch option, you set it in Steam; the plugin only reports that it is missing.
- **No Proton prefix writes.** Mod files go into the game's mod folder, not into `compatdata`.
- **No cloud, no account sync, no telemetry.** The plugin has no server of its own and stores nothing off-device.

## Repository layout

```
main.py                  Decky plugin entry point; all public RPCs (positional args, JSON-safe envelopes)
deckymod/                Backend, standard library only
  engine.py              XML-list engines (enable/disable by editing a state file)
  smapi.py, file_drop.py File-drop engines (enable/disable by directory presence)
  root_merge.py          Per-file install engine (Cyberpunk, user-configured games, loader ZIPs)
  user_games.py          User-defined game descriptors (data/games/<appid>.json, written by the panel)
  manifest.py            Manifest parsers, driven entirely by the game descriptor
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
  "paths": {
    "mod_root": "${GAME_ROOT}/Mods",
    "staging": "${GAME_ROOT}/.decky-staging",
    "quarantine": "${GAME_ROOT}/.decky-quarantine/${TXN_ID}",
    "disabled": "${GAME_ROOT}/.decky-disabled"
  },
  "mod_package": {
    "manifest_globs": ["manifest.json", "*/manifest.json"],
    "manifest_format": "json",
    "id_extraction": { "json": "UniqueID" }
  },
  "state_mutator": { "strategy": "file_drop" }
}
```

Drop it in `registry/games/` and add it to `registry/registry.json`. The `paths` block is now real
configuration: `mod_root`, `staging`, `quarantine` and `disabled` are resolved from it, with
`${GAME_ROOT}`, `${HOME}` and `${XDG_CONFIG}` expanded. A `quarantine` value may end in `/${TXN_ID}`;
the plugin stores the root and appends the transaction id itself. Unknown placeholders are refused.
`status: "planned"` keeps the game discoverable in the UI but refuses writes until you have verified the
paths on a real install; the synthetic Factorio tree exercises a mod folder outside the game directory,
but it is **not** a second real-game write sign-off.

## Status and documentation

This is a working plugin, not a finished product. What is proven on real hardware, what is only proven in
tests, and what is still open is recorded per item in [`docs/VERIFICATION.md`](docs/VERIFICATION.md);
[`docs/ACCEPTANCE.md`](docs/ACCEPTANCE.md) holds the acceptance criteria. Start at
[`docs/README.md`](docs/README.md) for the index.

Known gaps, stated plainly:

- Stardew Valley's write path is folder-based only (SMAPI detect-only); Cyberpunk and user-configured
  games install files but have no enable/disable switch — "installed" means "present", because their
  loaders have no state file the plugin could edit.
- Only the two built-in games have device-verified descriptors. A user-configured game works the way
  its descriptor says (synthetic-tree proven), but your own folder choice has not been verified against
  your game — start with a mod you can afford to lose, and check the game still launches.
- **SMAPI's launch option must use the FULL PATH.** `StardewModdingAPI %command%` looks right but the
  name is not on Steam's shell PATH — the launch fails and the game never opens (measured on device).
  Use `"<game folder>/StardewModdingAPI" %command%` instead; the plugin can only report that the option
  is missing or malformed, never fix it for you.
- Nexus Mods is **metadata and browser hand-off only**. The plugin can browse and open pages; the API gives
  download links to premium accounts, and free accounts must download in the browser. See
  [`docs/NEXUS_ROADMAP.md`](docs/NEXUS_ROADMAP.md).
- Dependency resolution goes up to three levels and can fetch manifest-verified dependencies, but it does not
  solve load order or chase arbitrary transitive graphs.

## License

See [LICENSE](LICENSE).
