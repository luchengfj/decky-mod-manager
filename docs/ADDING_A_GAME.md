# Adding a game: what one descriptor buys you, and what it does not

This document is the recipe `docs/NEXT_FEATURES.md` P1#5 asked for. It was
written in Round 43 together with the change that makes it true: until then the
descriptor's `paths` block was **reference metadata only** and
`paths.resolve()` hard-coded `Mods/`, `.decky-staging`, `.decky-quarantine` and
`.decky-disabled` under the game root. A second game whose mod folder is
anywhere else therefore could not have worked, no matter what its descriptor
said.

**Proven by `C:\ai\SD\tests\test_second_game.py`** (14 cases, all passing). The
suite builds a synthetic game that differs from Stardew Valley in every
dimension the engine could plausibly have hard-coded — AppID, installdir, mod
folder location, manifest file name, manifest field names, launcher marker,
launch-option token, external-manager marker, extension policy — wraps it in a
private registry, and drives the **real** `FileDropEngine` through
`status → inspect → install (two-phase) → disable → enable → uninstall →
rollback`. Nothing in `deckymod/` is mocked.

---

## 1. Honest scope of that proof

| Claim | Status |
| --- | --- |
| The write path is descriptor-driven, not Stardew-specific | **Proven** (synthetic second game, full lifecycle) |
| A second game's mod folder can live outside the game root | **Proven** (`${HOME}/.secondgame/mods` in the suite) |
| Every gate (external manager, launcher, launch options, capabilities) reads the descriptor | **Proven** (one case per gate, each flipping only descriptor data) |
| Any *real* second game works | **Not proven.** No second real game install has been used for a write sign-off. A synthetic tree proves the mechanism, not a game's truth. |
| 全游戏通用一键装 | **Not claimed, and not implemented.** `capability_gate.max_enabled_games_in_mvp` is `1`: exactly one game is operable at a time. |
| Original G3 (RimWorld 294100) sign-off | **Still OPEN.** Unrelated to this document. |

The reason to keep the scope narrow is the project's own history: every serious
defect in the last twenty rounds was a **promise the code did not keep**
(a declared key nobody read, a marker that was hard-coded, a flag that could
never fire). This document exists to stop a future descriptor from making the
same kind of promise.

---

## 2. Files a new game touches

```
registry/registry.json              <- add one entry under "descriptors"
registry/games/<game-id>.json       <- the whole adaptation lives here
```

Nothing else. `Registry.__init__` loads `registry.json`, then every
`descriptors[<id>]["file"]`, then every `loader_catalog` entry; a missing or
malformed file raises `E_UNKNOWN` with the path in `detail`
(`C:\ai\SD\deckymod\registry.py:36-42`).

`registry/registry.json` entry:

```json
"descriptors": {
  "mygame": { "file": "registry/games/mygame.json" }
}
```

Start from `C:\ai\SD\registry\games\stardew.json` (309 lines) — it is a
`file_drop` descriptor and the most completely exercised one — and change the
values below.

> Only **one** descriptor may have `"status": "enabled"` at a time. A second
> enabled descriptor makes `Registry.assert_enabled_count()` raise
> `E_CAPABILITY_DISABLED` (`deckymod/registry.py:77-85`) on every call. The
> supported shapes are "replace the enabled game" or "add it as
> `"status": "planned"` so the catalog can list it read-only".

---

## 3. Which descriptor key is read by which code

Everything in this table is verified by the round-43 census (grep + the
negative proof in `.decky-probe/r43_negative_proof.py`); a key that is *not* in
this table is not read, and adding it changes nothing.

### 3.1 Identity and dispatch

| Key | Read by | Effect |
| --- | --- | --- |
| `id` | `registry.raw["descriptors"]` key | how every RPC names the game |
| `status` | `Registry.enabled_games` / `get_game` / `catalog` (`deckymod/registry.py:56-75`) | `"enabled"` is the operable one; anything else is refused with `E_CAPABILITY_DISABLED` (unless a `DECKYMOD_GAME_ID` pin overrides, which is a test-only seam) |
| `engine` | `main.ENGINE_FACTORY` (`main.py:59-62`, lookup at `main.py:65-80`) | must be `"file_drop"` or `"xml_list"`; anything else raises `RuntimeError("no engine registered ...")` |
| `identity.appid` | `Registry.appid_for` → `smapi._resolve` (`deckymod/smapi.py:89-94`), `file_drop.check_launch_options` | which `appmanifest_<appid>.acf` is looked for |
| `identity.name`, `identity.platform`, `identity.status` | `status()` → `data.game`, `Registry.catalog` | display only |
| `display_label` | `main._selection_label` (`main.py:82-89`), catalog | panel title |
| `note` | catalog | shown to the user, not parsed |

### 3.2 Folders (`paths`)

Read by `paths.resolve(..., descriptor_paths=...)`, called from
`smapi._resolve()` (`deckymod/smapi.py:89-98`) and `engine._resolve()`
(`deckymod/engine.py:72-79`).

| Key | Placeholders | Notes |
| --- | --- | --- |
| `paths.mod_root` | `${GAME_ROOT}` `${HOME}` `${XDG_CONFIG}` | where mod folders live. May be **outside** the game root (Factorio: `${HOME}/.factorio/mods`). |
| `paths.staging` | same | must NOT be inside `mod_root`, else `E_STAGING_IN_MODS` (`deckymod/paths.py:244-247`) |
| `paths.quarantine` | same, plus `${TXN_ID}` | the trailing `/${TXN_ID}` is **stripped**: `ResolvedPaths` stores the root and every caller appends the transaction id itself. A `${TXN_ID}` anywhere else raises `E_PATH_INVALID`. |
| `paths.disabled` | same | where "disabled" mod folders are parked |
| `paths.state_file`, `paths.state_staging` | — | **Not read by `file_drop`** (`resolve(..., no_state_file=True)` blanks both). `xml_list` (RimWorld) also does not read them: `deckymod/paths.py` builds the RimWorld `ModsConfig.xml` path from the XDG config dir. Documentation only today. |

Omitting the whole `paths` block reproduces the four historical names exactly
(`_LAYOUT_DEFAULTS` in `C:\ai\SD\deckymod\paths.py`), which is why the RimWorld
and Stardew descriptors resolve byte-for-byte as before Round 43.

Relative values are anchored at the game root and normalised with
`os.path.normpath`, so a descriptor that writes `${GAME_ROOT}/Mods` and code
that writes `os.path.join(root, "Mods")` produce the same string. An unknown
placeholder is an error, never an empty path.

### 3.3 Launcher detection (`loader_detection`)

Read by `smapi._probe()` (read-only, for `status`) and
`smapi._check_write_allowed()` (the write gate, `deckymod/smapi.py:226-266`).
The gate's **order** is the safety design:

1. `force_read_only` → every write refused before any file access
2. external-manager markers → `E_EXTERNAL_MANAGER`
3. structural layout check (`Mods/` is a symlink / contains symlinks / on
   another filesystem) → `E_EXTERNAL_MANAGER`
4. launcher patterns → `on_missing_launcher` (default `E_LOADER_MISSING`)
5. launch options → `E_LAUNCH_OPTIONS_MISSING`

| Key | Notes |
| --- | --- |
| `patterns` | file **or** directory names that must exist in the game root. Empty list = "nothing to detect", which is honest for a game with no loader, but it means step 4 can never fire. |
| `on_missing_launcher` | error code used when step 4 fires |
| `external_manager_markers` | names checked by `file_drop.detect_external_manager` (`deckymod/file_drop.py:41-70`). **Where** the name sits is part of the evidence: inside `mod_root` it must be a *file*, beside `mod_root` in the game root it must be a *directory*. Empty/absent → the historical Stardew pair (`.mm_deployed`, `Mods_Core`) is used, so a new descriptor must set this if its game has no such manager — otherwise a Stardew-shaped marker would still block it. |
| `launch_options_must_already_be_set` | if true, step 5 runs |
| `launcher_token` | substring that must appear in the Steam launch options |
| `running_detection` / `running_process_markers` | `smapi._running()` → `procs.is_running`. `{"enabled": false}` reports `unknown`; `unknown` deliberately does **not** refuse a write (a host without `/proc` would otherwise be write-nothing). |
| `loader_log` | `loaderlog.inspect` — lets `status()` report what the loader itself accepted |

`check_launch_options` looks in the user's **own** Steam directories
(`~/.local/share/Steam`, `~/.steam/steam`), *not* `DECKYMOD_STEAM_ROOT`; it
returns `"unknown"` rather than failing when it cannot read them.

### 3.4 The mod package (`mod_package`)

Read by `deckymod/manifest.py` (parsing/scanning), `deckymod/file_drop.py`
(inspection/extraction) and `smapi` (verify after write).

| Key | Read by | Notes |
| --- | --- | --- |
| `parser` | `manifest.PARSERS` (`deckymod/manifest.py:448-458`) | `"json_map"` or `"xml_about"` today. An unknown name raises `E_UNKNOWN` — this is where a new manifest dialect gets added. |
| `manifest_globs` | `manifest` / `file_drop.inspect_mod` | `["*"]`-style globs, matched against archive members |
| `strip_single_root` | `archive` | whether a single wrapper directory is dropped |
| `install_relpath_prefix` | `file_drop` (`deckymod/file_drop.py:235`, `:402`) | display/metadata prefix only; the bytes go to `paths.mod_root` |
| `field_map` | `JsonMapParser` | maps semantic names → this game's field names (`id`, `name`, `version`, `author`, `dependencies`, `dependency_id_keys`) |
| `field_aliases` | `manifest._apply_aliases` | e.g. `{"UniqueID": ["UniqueId"]}` — how a real-world casing variance is absorbed **without** relaxing validation |
| `json_dialect` | `manifest._strip_jsonc_text` | `"jsonc"` accepts `/* */` comments and trailing commas; string-aware |
| `required_manifest_fields` | `manifest` | a missing one is `E_MANIFEST_INVALID` / `E_MANIFEST_MISSING`, not a silently-empty mod |
| `id_regex`, `id_normalize` | `manifest` | `lowercase_for_directory` decides the folder name |
| `install_filename_template` | `file_drop` | folder name template (`${id}`) |
| `limits` | `archive` | `max_compressed_bytes`, `max_uncompressed_bytes`, `max_entries`, `max_compression_ratio`, `max_path_depth` |
| `allow_extensions` / `reject_extensions` | `file_drop.inspect_mod` (`deckymod/file_drop.py:187`) | `reject_extensions` **replaces** the Stardew default (`SMAPI_FORBIDDEN_EXT`); `.zip`/`.7z` archives are the supported containers |
| `dependency_optional_key` | `manifest._coerce_dep_specs` | a dependency flagged optional by this field is not reported missing unless explicitly required |
| `dependency_minimum_key` | `manifest` | enables `outdated_dependencies` |
| `conflicts.scope` | `conflicts.survey` | `per_mod_directory` or `shared_tree` |

### 3.5 Capabilities and safety

| Key | Read by | Notes |
| --- | --- | --- |
| `capabilities.<name>` | `Registry.require` on every RPC (`deckymod/smapi.py` `_gate` calls) | false → `E_CAPABILITY_DISABLED`. The names used today: `local_import`, `enable_disable`, `uninstall_quarantine`, `rollback`. |
| `safety.refuse_if_game_running` | `smapi._check_not_running` | `false` skips the running check; the `DECKYMOD_GAME_RUNNING` env override is honoured regardless |
| `force_read_only` | `smapi._check_write_allowed`, `_probe`, `auto_import` | the descriptor-level "identification only" switch |
| `known_limitations` / `known_limitation_keys` | `status()` | shown verbatim / mapped through i18n |

### 3.6 Keys that are declared but **not read** by `file_drop`

Documented here so nobody mistakes them for switches:

| Key | Reality |
| --- | --- |
| `conflict_policy` (top level) | unread. Conflict reporting uses `mod_package.conflicts.scope`. |
| `mod_package.install_is_directory` | unread; directories are the only shape the engine installs. |
| `state_mutator` | read only by the `xml_list` engine (RimWorld). `file_drop` has no state file. |
| `paths.state_file` / `paths.state_staging` | blanked for `file_drop`; the `xml_list` path is computed, not read. |
| `capabilities` keys other than the four gated ones | recorded and displayed (catalog, `capabilities_note`), not enforced. |

---

## 4. What still requires code

A descriptor is enough **only** for a `file_drop` game whose loader is already
installed by the user and whose manifest is `json_map`/`xml_about`. The
following are code changes, and pretending otherwise would be the "declared
but unread" class of bug again:

1. **A new manifest dialect.** Add a `ManifestParser` implementation and
   register it in `PARSERS` (`C:\ai\SD\deckymod\manifest.py:448`). The parser
   must raise `ModError` with a specific code, not return a half-empty dict.
2. **A new engine shape.** `ENGINE_FACTORY` (`C:\ai\SD\main.py:59`) only knows
   `file_drop` and `xml_list`. A game that needs a different lifecycle (load
   order solving, state-file rewrite) needs a new engine class, and that is a
   review-worthy change — it is where every past data-loss defect lived.
3. **More than one operable game.** `max_enabled_games_in_mvp` is `1`, and the
   panel is written around one active game (`status()` returns one `game`
   block). Multi-game operation is not a descriptor edit.
4. **A second `xml_list` game.** `deckymod/engine.py` still pins RimWorld
   (`GAME_ID`, `paths.resolve(294100, ...)` at `deckymod/engine.py:72-79`).
   That engine is the historical MVP path, kept byte-identical on purpose.
5. **Anything involving the loader itself** — installing BepInEx/SMAPI, editing
   Steam launch options, writing a Proton prefix. Out of scope by hard
   constraint, for every game, permanently.

---

## 5. Checklist for a new game

1. Copy `registry/games/stardew.json` → `registry/games/<id>.json`; set `id`,
   `status: "planned"` (start read-only), `engine`, `identity`.
2. Fill `paths` with the **real** folder locations. Use `${HOME}` /
   `${GAME_ROOT}` / `${XDG_CONFIG}`; do not hard-code `/home/deck`.
3. Set `loader_detection.patterns` to something the loader actually creates, and
   `external_manager_markers` to **your** game's other-manager markers (empty
   list means "no other manager known" — do not copy Stardew's).
4. Write the fixture **before** touching the production registry. Extend the
   `SecondTree` pattern in `C:\ai\SD\tests\test_second_game.py`: a fake Steam
   library (`libraryfolders.vdf`, `appmanifest_<appid>.acf`), the launcher
   marker, the user's `localconfig.vdf` with the launch options, and a private
   registry under the test's own base directory.
5. Run the suite and a full `python -m unittest discover -s tests`; the
   existing cases must be green **and** the new descriptor must be exercised by
   at least one write path.
6. Only then flip `status` to `"enabled"` — and expect the previously enabled
   game to become inoperable, because the cap is 1.
7. Run the negative proof for any decision you added:
   `python .decky-probe/r43_negative_proof.py` mutates exactly one line and
   requires the second-game suite to fail while the Stardew suite still passes.
   A proof that fails nothing proves nothing.

## 6. Failure modes worth stating out loud

- **The mod folder does not exist yet.** First install creates it
  (`ensure_dir`); `modwatch.is_foreign` deliberately treats
  `mods_dir_missing` as *not* foreign.
- **The mod folder is a symlink or lives on another device.** Refused with
  `E_EXTERNAL_MANAGER`; the plugin never writes through a link.
- **The launch options are missing.** Refused with
  `E_LAUNCH_OPTIONS_MISSING` — the plugin will not edit them for you.
- **The launcher is missing.** Refused with `E_LOADER_MISSING` (or the
  descriptor's own code) — the plugin never installs a loader.
- **`check_launch_options` returns `"unknown"`.** Not fatal, and honest: the
  plugin could not read the file, which is different from "not set".
