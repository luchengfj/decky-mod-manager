# Decky MOD Manager — MVP (RimWorld native)

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin for Steam Deck
**Game Mode** that manages local MODs for **one** game: RimWorld (AppID `294100`,
Linux-native build). Everything is done with the gamepad (D-pad + A/B) inside the
Quick Access Menu (QAM) panel.

> **Status: implemented + locally self-tested, NOT yet verified on a real Steam Deck.**
> The frontend bundle is **uncompiled / un-type-checked** on this Windows dev box and
> the Decky/template version pins are **not confirmed**. See
> [VERIFICATION.md](VERIFICATION.md) (G3 gate) and [ACCEPTANCE.md](ACCEPTANCE.md) (DoD)
> before shipping. Do not treat this as a release.
>
> **状态更正（2026-11-13 证据回写补记，非状态变更）**：以上「uncompiled /
> un-type-checked / 未在本机构建」是**实现轮历史快照**。2026-11-13 已在一台联网
> Steam Deck（SteamOS 3.9.5 / Decky Loader v3.3.1）实跑 `pnpm install` +
> `tsc --noEmit`(strict 零错误) + `rollup -c`，改用官方 `@decky/rollup` 产出**可加载
> ESM** `dist/index.js`，`pnpm-lock.yaml` 与 `dist/` 已回传本工作区。V1 四组版本已
> 于 2026-11-12 `CLOSED`。**但**这只是构建/类型核对证据：`V2`–`V20` / `F1`–`F3`
> 状态一律未动、全部仍 `OPEN`，G3 整体仍 `OPEN`，未写新的 `CLOSED`；RimWorld 294100
> 在该 Deck 未安装，QAM/手柄 DoD 11 项与真实游戏写回仍无真值。详见
> [VERIFICATION.md](VERIFICATION.md) §H。**仍不是 release。**
>
> **状态更正（2026-11-13 晚补记，非状态变更）**：同日晚用户经 Decky UI 手柄「从 ZIP
> 安装」已把插件装上真机；首启因冻结解释器 PYZ 缺 `xml.etree` 失败，按用户批准加
> `deckymod/__init__.py` 的 XML 兼容 shim 后，**插件在真机冻结解释器里真实加载成功**
> （子进程存活、`deckymod.log` 有 loaded 行、4 个只读 RPC 全链路通过），并重建带 shim
> 的 ZIP 回传（见 [VERIFICATION.md](VERIFICATION.md) §H.7）。**但**仍不是 release：
> RimWorld 294100 未安装、QAM/手柄 DoD 11 项与真实游戏写回仍无真值，`V2`–`V20` /
> `F1`–`F3` 状态一律未动、仍全 `OPEN`、G3 仍 `OPEN`、未写新 `CLOSED`。
>
> **状态更正（2026-11-14 B 方案补记，非状态变更）**：同日按用户「B方案」授权，在真机
> 冻结解释器里用合成树跑通 11 个 RPC 全链路 + 7 类故障注入（41 项全绿，测完逐字节还原），
> 逐字证据见 [VERIFICATION.md](VERIFICATION.md) §H.9。**仍不是 release**：这是后端逻辑回归，
> RimWorld 294100 仍未安装、手柄 DoD 11 项与真实游戏写回仍无真值；`V2`–`V20` / `F1`–`F3`
> 状态一律未动、仍全 `OPEN`、G3 仍 `OPEN`、未写新 `CLOSED`。

## What this MVP is — and is NOT

| In scope | Out of scope (first version) |
| --- | --- |
| One sample game: RimWorld native `294100` | Any other enabled game |
| Local ZIP import from a fixed drop-folder (+ optional OSK path box) | Network / Steam Workshop / any download |
| Install, enable, disable, uninstall (to quarantine), rollback | Installing BepInEx / SMAPI / xNVSE / UE4SS / MelonLoader |
| Transaction journal, snapshots, quarantine, recovery | Writing Proton `pfx` / compatdata prefixes |
| Atomic, surgical edit of `ModsConfig.xml` | Editing game launch options / `WINEDLLOVERRIDES` |
| Pure-gamepad UI + structured error codes | Running Windows `.exe` / `.msi` installers |
| — | Load-order / dependency solving, "one-click for any game" |

**Hard constraints (self-certified in §6 of the plan):**
- SteamOS read-only root is **never** disabled (`requires_readonly_toggle:false`). All
  writes land under `$HOME`, a user Steam library, a microSD mount, or Decky-managed
  dirs. `EROFS` → `E_READONLY_FS`, operation refused, no `sudo`.
- **No root assumption**: neither "always root" nor "never root". The real game user is
  resolved via `DECKY_USER` / `pwd.getpwnam`; `chown` runs only when `geteuid()==0`;
  a wrong-owner file is refused (`E_ROOT_OWNED` / `E_STATE_OWNED`), never `chmod`-ed
  into place. Non-POSIX mounts skip ownership checks instead.
- **No universal one-click**: `universal_one_click:false`,
  `max_enabled_games_in_mvp:1`, only `rimworld` has `status:enabled`; every other
  descriptor is `planned` and the capability gate refuses it (`E_CAPABILITY_DISABLED`).

## Repository layout

```
main.py                       Decky entry point: class Plugin, 16 async positional RPCs,
                              _main/_unload/_uninstall/_migration
plugin.json                   Decky manifest (name, api_version, flags, publish tags)
package.json / tsconfig.json / rollup.config.js
                              frontend build (@decky/rollup -> dist/index.js, esm + SP_* globals)
src/
  index.tsx                   definePlugin(), QAM panel: compact status + 4-way section
                              switcher (mods / download / games / system), one body mounted
  api.ts                      @decky/api call/callable bridge, invoke() guard
  types.ts                    TS mirror of the JSON-safe envelope + per-RPC payload types
  i18n.ts                     t() / errorText() / categoryText(), zh-CN via navigator.language
  i18n/en.json, zh-CN.json    471 keys each, parity enforced by validate_i18n.py
  components/
    Modal.tsx                 gamepad-first showInfo / showListModal / showErrorModal / showFomodModal
    ConfirmModal.tsx          two-phase confirm (A=confirm, B=cancel)
    ErrorView.tsx             one code, one message, code in small text + log path
    ModRow.tsx                mod row: enable/disable / details / uninstall
    ImportBox.tsx             optional OSK path input (fully skippable)
deckymod/                     stdlib-only Python backend (no third-party deps)
  errors.py                   50 user-facing codes -> (category, message, rollback?); E_RECOVERY_PENDING only gates writes from Round 51
  envelope.py                 unified {ok,code,message,detail,data,rollback_available,log_path,ts}
  json_safe.py                to_json_safe(): Path/bytes/set/bigint/NaN -> JSON-safe
  fsops.py                    atomic writes, os.replace, chown/fchmod guards, errno mapping
  vdf.py                      dependency-free Valve VDF / ACF parser
  paths.py                    12-step Steam library / install-dir / config-path resolution
  registry.py                 loads registry.json + descriptors, capability gate, engine factory
  journal.py                  JSONL journal, snapshots, installed() reconstruction, state machine
  engine.py                   XML-list core (RimWorld, historical regression)
  state_mutator.py            ModsConfig.xml surgical line edit (Core invariant)
  archive.py                  ZIP inspection: zip-slip, zip-bomb, ratio floor, strip_single_root
  sevenzip.py                 .7z via the device's own 7z binary; runner injectable for tests
  manifest.py                 ManifestParser: json_map / xml_about, JSONC dialect, dependency ids
  modwatch.py                 structural check of Mods/ itself: symlinked folder/entries, other device
  conflicts.py                which mods ship the same path (read-only, never reordered)
  updatekeys.py               parses a mod's own UpdateKeys: the only
                              trustworthy source for its Nexus id
  quarantine.py               what the quarantine still holds, and the one
  handover.py                 what a handover moves, and the obstacles that make it refuse as a whole
  upgrade.py                  undo an upgrade: put the version the install displaced back where it was
                              path that may delete an unrecoverable folder and what can no longer come back
  procs.py                    is the game running? /proc argv[0], never a name search (Round 50)
  file_drop.py                file_drop engine helpers: presence == enabled, external-manager guard
  smapi.py                    FileDropEngine: status/inspect/install/enable/disable/uninstall/rollback
  fomod.py                    FOMOD descriptor parsing -> option-filtered extraction
  steamlib.py                 libraryfolders.vdf + /run/media enumeration (read-only)
  templates.py                per-game mod-dir templates; unknown appid -> "not adapted"
  download.py                 shared low-level HTTPS + download core (no credentials)
  github_source.py            GitHub Releases search / releases / 302 asset resolve
  auto_import.py              download -> inbox -> inspect -> confirm -> install coordinator
  credentials.py              Nexus API key at rest: 0o600, O_EXCL, atomic replace, never echoed
  nexus.py                    Nexus v1 metadata client (browse only -- download links are premium-only)
  loaderlog.py                reads the loader's own log: what actually LOADED vs merely installed
  import_root.py              the import list also reads the folder the browser saves to (READ ONLY)
registry/
  registry.json               master registry (active_game, schema, write roots, capability gate)
  games/stardew.json          the enabled descriptor (file_drop + SMAPI detect-only)
  games/rimworld.json         planned: historical regression (33 pinned tests)
  games/factorio.json         planned: json_toggle_list shape example
  games/valheim.json          planned: BepInEx/Proton example (declined, §3.8 prohibitions)
  loaders/*.json              5 loader catalogs (bepinex5/smapi/xnvse/ue4ss/melonloader)
tests/                        50 modules, 756 cases (`Ran 756 tests ... OK (skipped=14)`)
  test_mvp.py                 synthetic Steam-tree unittest, RimWorld path (pinned via env)
  test_stardew.py             file_drop engine round trip + loader-log wiring through status()
  test_loaderlog.py           real-log parsing (22/3/4/11) and the unknown-is-not-loaded rule
  test_import_root.py         declared roots, symlink refusal, read-only guarantee
  test_modwatch.py            the layout decision, with os primitives faked (Windows has no symlinks)
  test_modwatch_gate.py       the same decision through the real engine on a real tree
  test_search_page.py         query sanitising, the site's search URL, no results promised
  test_steamlib.py            library enumeration incl. both SD-card layouts
  test_download*.py           download core, integrity checks, wiring
  test_fomod.py / test_templates.py / test_toggle.py / test_duplicate_guard.py ...
  test_conflicts.py           shared paths, glob ignores, and the per-mod-directory answer
  test_conflicts_status.py    the scan is actually wired through status()
  test_updatekeys.py          site:id@channel shapes real manifests actually use
  test_quarantine.py          restorable vs orphan vs unknown; only reclaim() deletes
  test_handover.py            survey/plan/execute: nothing moves without a confirm
  test_handover_gate.py       through the engine: read-only flips, rollback restores
  test_upgrade.py             upgrading then rolling back must restore the OLD version, not refuse
test_parked_uninstall.py    a disabled mod is uninstallable; a missing one is refused, not faked
test_preview_agreement.py   the import preview must name the path the install will use
  test_single_path_decision.py  one helper decides where a mod lives; the structure cannot drift back
  test_reclaim.py             plan refuses restorable and unknown; two-phase; symlink recheck
  test_reclaim_gate.py        reclaim through the real engine, behind every write gate
test_procs.py               faked /proc: marker, path, unknown-is-not-stopped
test_running_gate.py        every destructive op refuses while the game runs
test_first_run.py           a fresh game has no Mods/ folder; not-found is not duplicate
test_external_markers.py    marker WHERE matters: a Mods_Core mod folder is not a marker
test_pending_gate.py        an unfinished txn blocks install/enable/uninstall, never rollback
test_lifecycle_hooks.py     _unload/_uninstall/_migration leave the user's Mods/ byte-identical
test_import_order.py        discovery imports everything first; no module may drop the game pin
test_multi_mod_archive.py   several mods in one zip are refused; one mod lands at the top however deep it was packed
test_entry_dll.py          a declared EntryDll must exist in the archive, or the import is refused
  _verify.py                  compileall + registry JSON validation helper
docs/                         see the index below
.github/workflows/build.yml   CI: backend selftest + frontend build
``````

## Front ↔ back communication

- `main.py` exposes `class Plugin` with **async** public methods; Decky dispatches them
  by `getattr` from the frontend. Every RPC takes **positional args** (never kwargs,
  never an object). Example: `install(zip_path, after_confirm=False)`,
  `set_enabled(package_id, enabled, after_confirm=False)`, `rollback(txn)`.
- Frontend uses `call<Envelope<T>>(method, ...args)` from `@decky/api`; `callable<Args,Ret>`
  handles exist in `api.ts` as typed references but the UI deliberately routes all calls
  through one `invoke()` guard that normalises any thrown/malformed reply into an
  `E_BACKEND_UNREACHABLE` envelope.
- Backend pushes progress via `decky.emit("deckymod:progress", payload)`
  (fire-and-forget); the frontend subscribes with `addEventListener` /
  `removeEventListener` using a **stable function reference** (§5.3 cleanup).
- **JSON-safe contract**: every reply is forced through `to_json_safe()` +
  `json.dumps(allow_nan=False)`. `pathlib.Path` → `str`, `bytes` → base64-tagged
  dict, `set` → sorted list, `datetime` → isoformat, `Decimal` → `str`, NaN/Inf →
  `None`, integers above `2^53-1` (SteamID64) → `string`, non-string dict keys →
  `str`. `default=str` is forbidden (it would hide bugs).

## The three write roots (W1 / W2 / W3)

| Root | Path (resolved each action, never cached) | FS |
| --- | --- | --- |
| **W1** state | `${XDG_CONFIG}/unity3d/Ludeon Studios/RimWorld by Ludeon Studios/Config/ModsConfig.xml` (literal spaces) | internal SSD, POSIX |
| **W2** payload | `${STEAM_LIBRARY}/steamapps/common/${APP_INSTALL_DIR}/Mods/<packageId>/` (one dir per mod) | game install, possibly microSD/exFAT |
| **W3** metadata | `${DECKY_DATA}/journal|snapshots` + `${DECKY_PLUGIN_LOG_DIR}` | Decky-managed, internal SSD, POSIX |

- Staging siblings: `Config/.decky-staging/` (W1) and `${GAME_ROOT}/.decky-staging/` (W2);
  each write root gets its own same-filesystem `mkstemp → fsync → fchmod(guarded) →
  chown(euid==0 only) → os.replace → fsync(parent)` atomic write. Cross-device
  `os.replace` raises `EXDEV(18)` → `E_CROSS_DEVICE`; we never rename across filesystems.
- **Quarantine exception**: the isolation dir MUST live on W2's filesystem →
  `${GAME_ROOT}/.decky-quarantine/${TXN_ID}/`. This is the single approved deviation
  from "journal/quarantine in DECKY_DATA": microSD↔SSD cross-device `os.replace` of a
  whole mod dir would fail. The journal still records original path, quarantine path
  and txn id.
- Staging/quarantine are **never** created inside `Mods/` (RimWorld scans child dirs for
  `About/About.xml`); guarded by `E_STAGING_IN_MODS`.
- microSD / exFAT: no POSIX ownership, no symlinks, often `noexec`. `/proc/self/mountinfo`
  decides POSIX-ness; non-POSIX ⇒ skip ownership checks, tolerate `EOPNOTSUPP` on
  `fchmod`, emit info-level `E_FS_NO_POSIX`; case-insensitive `os.listdir()` resolves
  real casing.

## The state mutator (`ModsConfig.xml`)

- `activeMods` is **ordered**. `install != enable`:
  install = unpack the ZIP dir into `Mods/<packageId>/` (top-level, via
  `strip_single_root:true`); enable = append `<li>packageId</li>` to `<activeMods>`.
- **Core invariant**: `ludeon.rimworld` must exist and be the **first** `<li>`; missing
  or out of position → `E_CORE_MISSING`, refused. DLC (`ludeon.rimworld.*`), Workshop
  entries and any `<li>` we didn't create are preserved byte-for-byte
  (`preserve_unknown_entries:true`).
- **`surgical_line_edit`**: ElementTree is used **read-only** to validate/parse. The
  WRITE inserts/removes exactly one `<li>…</li>` line inside the `<activeMods>` block
  and leaves every other byte (comments, indentation, `<version>`, `knownExpansions`)
  untouched. Re-serializing with ElementTree would drop comments/formatting — forbidden.
- RimWorld may rewrite `ModsConfig.xml` on quit ⇒ `verify_on_open` + fingerprint drift
  → `E_STATE_EXTERNAL` ("Refresh and retry") are mandatory.

## Honest limitations (shown in the UI too)

These are the ones a user will actually meet, and they are surfaced in the panel
rather than hidden in a file:

- **Stardew Valley is the only game this build can write to.** Cyberpunk 2077 and
  DAVE THE DIVER have identification templates (their mod directories are read
  and shown), but the plugin will not install into them. `max_enabled_games_in_mvp`
  is still 1, and `universal_one_click` is still `false`.
- **SMAPI must already be installed by the user.** The plugin detects
  `StardewModdingAPI` and the launch option, and refuses with `E_LOADER_MISSING` /
  `E_LAUNCH_OPTIONS_MISSING` when they are absent. It never installs a loader and
  never edits Steam launch options.
- **file_drop means "in `Mods/`" == enabled.** There is no load-order state to
  edit: disabling moves the folder to a sibling `.decky-disabled/`, enable moves
  it back, uninstall moves it to `.decky-quarantine/`. Nothing is ever deleted.
- **No load-order or dependency solver.** `dependencies` from a manifest are shown
  as information (and missing ones are listed), never resolved or reordered.
- **Downloads are GitHub Releases or a direct HTTPS URL.** No Workshop. Nexus
  was retired — see [GOAL_RECORD_DOWNLOAD_SOURCE.md](GOAL_RECORD_DOWNLOAD_SOURCE.md)
  for why its 403 is an account policy rather than a rate limit.
- **No Proton prefix writes, no `.exe` installers, no root, no SteamOS
  read-only toggle.** Downloading is opt-in per call, two-phase confirmed, and the
  final write is always gated by the engine.

## Local verification status (this Windows dev box)

```
python -m unittest discover -s tests -v  -> Ran 714 tests ... OK (skipped=14)  (LASTEXITCODE=0)
python -m compileall -q deckymod main.py tests -> 0
.decky-probe/validate_i18n.py            -> EN 470 / ZH 470, parity [] , EXIT=0
.decky-probe/validate_p0.py              -> PUBLIC_RPC_COUNT 28, ALL_STATIC_CHECKS True
.decky-probe/validate_download_wiring.py -> DOWNLOAD_WIRING_ALL_OK=True, EXIT=0
.decky-probe/validate_api_arity.py       -> BACKEND_RPCS 26 / FRONTEND_CALLS 26 / BAD 0
.decky-probe/r19_frontend_preflight.py   -> FRONTEND_PREFLIGHT_OK, BARE_BUTTON 0, EXIT=0
.decky-probe/r8_zipload_probe.py         -> PHASE2_STATUS_OK True, EXIT=0
.decky-probe/r4_tar_drift.py             -> TAR_COUNT 114 / CUR_COUNT 114, drift 0
```

Backend is stdlib-only and **runs** on this box (the Windows-portability fix in
`fsops.py` — `fchmod` guarded with `getattr`, fchmod/chown moved onto the open
write fd — keeps Linux behaviour unchanged). The synthetic tests build fake Steam
libraries, appmanifests, `ModsConfig.xml`, ZIP and `.7z` archives under
`.decky-test-tmp/`, then exercise install → enable → disable → uninstall →
rollback plus conflict/zip-slip/path-escape/game-running/drift/state-missing and
the duplicate-UniqueID guard.

**The frontend is NOT type-checked on this box** — there is no TypeScript here.
`tsc --noEmit` and `rollup -c` run on the Deck (`/home/deck/deckymod-build`), and
their green result is what makes `dist/index.js` trustworthy. The last such run
was `TSC_EXIT=0 / ROLLUP_EXIT=0` producing `dist/index.js`
`0c402ba30500fa53e01300b3e15cb737c125fd9261dd39c314b7e0a63d0579df` (147394 B),
deployed byte-identical to `/home/deck/homebrew/plugins/decky-mod-manager/`.

**What is still not proven anywhere:** a real SD card (none is inserted — the two
`/run/media` layouts and a full write flow are proven against a card-shaped tree,
see [STEAM_LIBRARY.md](STEAM_LIBRARY.md)), and a human looking at the
reorganised panel. Status discipline is unchanged: V1 is the only CLOSED item,
V2–V20 / F1–F3 stay OPEN, G3 (RimWorld 294100) stays OPEN / NOT SHIPPABLE, Step 5
is out of scope, Track C is separately gated, S9/S10 are report-only.

## Document index

Reading order for a newcomer, and what each file is for:

| file | what it answers |
|---|---|
| [ROUND30_FIVE_CRITERIA.md](ROUND30_FIVE_CRITERIA.md) | the five outstanding criteria: what is proven, what is blocked, and where the evidence lives |
| [PANEL_LAYOUT.md](PANEL_LAYOUT.md) | why the panel is now status + a four-way switcher instead of five stacked sections |
| [STEAM_LIBRARY.md](STEAM_LIBRARY.md) | Steam library enumeration, both SD-card layouts, and the SD blocker |
| [DOWNLOAD_SOURCES.md](DOWNLOAD_SOURCES.md) | GitHub Releases two-hop download, direct-URL guards, size/hash verification |
| [DEPENDENCIES.md](DEPENDENCIES.md) | downloading a mod's required dependencies, and why only the manifest can authorise one |
| [LOADER_LOG.md](LOADER_LOG.md) | what the game actually loaded on its last launch, and why an installed mod is not the same as a working one |
| [GOAL_RECORD_DOWNLOAD_SOURCE.md](GOAL_RECORD_DOWNLOAD_SOURCE.md) | the Nexus → GitHub change record and why 403 is not rate limiting |
| [ENABLE_DISABLE.md](ENABLE_DISABLE.md) | why disable parks the folder instead of reusing uninstall |
| [MOD_CONFLICTS.md](MOD_CONFLICTS.md) | the duplicate-UniqueID guard and why it cannot be confirmed away |
| [E2E_STARDEW.md](E2E_STARDEW.md) | download → import → enable → game launch, with verbatim SMAPI log lines |
| [QAM_REAL_INPUT.md](QAM_REAL_INPUT.md) | how three ButtonItems were really pressed (trusted CDP input, dialogs in another target) |
| [QAM_R25_PANEL.md](QAM_R25_PANEL.md) / [QAM_VISUAL_CHECK.md](QAM_VISUAL_CHECK.md) | earlier panel visual checks and the checker's checklist |
| [VERIFICATION.md](VERIFICATION.md) | §7 "verify on device / locked versions" ledger (V1–V20, F1–F3, G3) — the authority on status |
| [ACCEPTANCE.md](ACCEPTANCE.md) | Definition of Done and the 50-code error table |
| [RUNBOOK.md](RUNBOOK.md) / [ONDEVICE.md](ONDEVICE.md) | offline handover and on-device debugging checklists |
| [NEXUS_ROADMAP.md](NEXUS_ROADMAP.md) | historical round notes, incl. §6.7 the Nexus metadata surface and why download links stay premium-only; snapshots are never backfilled |
| [QUARANTINE.md](QUARANTINE.md) | what "uninstall" keeps, and when a kept folder can no longer be restored |
| [UPGRADE.md](UPGRADE.md) | what happens to the version an install overwrote, and why rollback used to answer "nothing to roll back" |
| [LIFECYCLE.md](LIFECYCLE.md) | what the unload/uninstall/migration hooks may touch, and how that promise is now tested |
| [ARCHIVE_LAYOUT.md](ARCHIVE_LAYOUT.md) | where a mod starts inside a zip, and why a multi-mod archive has to be refused |
| [ENTRY_DLL.md](ENTRY_DLL.md) | `EntryDll` names the file SMAPI loads; an archive that names one it does not contain is refused |
| [PATH_DECISION.md](PATH_DECISION.md) | why "disabled" is a location, and what went wrong three rounds in a row because three places computed it |
| [PREVIEW_AGREEMENT.md](PREVIEW_AGREEMENT.md) | why the confirm dialog must be generated from the same computation the write uses |
| [RUNNING_GAME.md](RUNNING_GAME.md) | is the game running right now, and why that used to be an environment variable nobody set |
| [DECLARED_VS_READ.md](DECLARED_VS_READ.md) | which descriptor keys the code actually reads, and the one that was decoration |
| [FIRST_RUN.md](FIRST_RUN.md) | what the very first install does on a game that has never had a mod, and why "not found" needed its own answer |
 what happens when a transaction did not finish, and why rollback is the one thing that must stay open |
| [UPDATE_KEYS.md](UPDATE_KEYS.md) | where a mod's Nexus id comes from, and why a guessed one would open someone else's mod |
| [MOD_FOLDER_CONFLICTS.md](MOD_FOLDER_CONFLICTS.md) | which mods ship the same file, why scope belongs to the loader, and the 27 false alarms the device found |
| [HANDOVER.md](HANDOVER.md) | handing Mods/ over from another manager without deleting anything, and what it refuses |
| [MOD_FOLDER_OWNERSHIP.md](MOD_FOLDER_OWNERSHIP.md) | who owns the Mods folder, and why a filename list can never answer that |
| [NEXT_FEATURES.md](NEXT_FEATURES.md) | what is still missing, ranked by whether it can corrupt user data or fail silently — not a wish list |

## Windows portability note

Target runtime is SteamOS (Linux), where `fchmod`/`fchown`/`statvfs`/`geteuid` all
exist. On this Windows dev box they are absent. Two defensive, Linux-equivalent fixes
were made so the backend can be self-tested here without weakening production semantics:
- `_maybe_fchmod` uses `getattr(os, "fchmod", None)` (missing ⇒ no-op, consistent with
  the existing "tolerate non-POSIX" design);
- `atomic_write_bytes` performs `fchmod`/`chown` on the open write fd inside
  `with os.fdopen(fd, "wb")`, removing a latent fd leak and a TOCTOU window.
`preflight_root` already guards `os.statvfs` with `except (OSError, AttributeError)`.
On Linux the behaviour is unchanged.

## CI

`.github/workflows/build.yml` runs two jobs on `ubuntu-latest`:
- `backend-selftest`: Python 3.11, `compileall deckymod main.py`, validate all
  `registry/**/*.json`, `python -m unittest discover -s tests -v`.
- `frontend-build`: Node 20 + pnpm 9, `pnpm install --frozen-lockfile`,
  `pnpm run typecheck` (tsc --noEmit, strict), then `pnpm run build`. **A
  `pnpm-lock.yaml` must be committed** (generated on a machine with registry
  access) for `--frozen-lockfile` to pass.

The typecheck step was added in round 46 and is the load-bearing one. Before
it, CI ran only `rollup -c`, and rollup does not type-check — so a `TS2304
Cannot find name` in the frontend could reach `main` with both CI jobs green.
That happened three times locally (rounds 41-43) before the step existed, and
each time it was caught by a Deck build after the fact instead of by CI. The
static preflight in `.decky-probe/` now also checks that every name used from
one of our own modules is actually imported, with a negative proof that it
fires on the round-43 defect; but `tsc` is the real guard, and CI is where it
now lives.

## Adding another game (future)

The registry is data, not code. To make a game **writable** you would: add a
descriptor under `registry/games/`, set `status:enabled` in `registry.json`, and —
**only after** every relevant §7 item in [VERIFICATION.md](VERIFICATION.md) is
closed — raise `max_enabled_games_in_mvp`. The capability gate refuses any
descriptor whose required capability is `false` or whose status is not `enabled`.
Planned descriptors (Factorio `json_toggle_list`, Valheim/BepInEx `file_drop` +
Proton) exist only to prove the schema scales; they are refused in MVP.

There is a second, deliberately weaker layer: `deckymod/templates.py` maps an
appid to a mod directory plus the loader it expects, and `list_games` reports it.
That layer is **identify-only** — it never writes, never installs a loader, and
returns `note: "not_adapted"` with zero paths for anything it does not know
rather than guessing. Cyberpunk 2077 and DAVE THE DIVER live there today. Adding
an identification template does not raise the writable-game count and does not
need a capability-gate change; adding a *writable* game does, and that is a
separate review.
