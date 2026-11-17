# Enable / Disable — moving a mod out of the game folder and back

Round 25. This document explains the one capability the plugin previously
refused to provide, why it was refused, and exactly what changed.

Status discipline: this is an additive round note. It does not flip any V#/F#
status, does not tick any `[ ]` box in existing checklists, and does not claim
any status that is not backed by the evidence quoted below.

---

## 1. Why this existed as a refusal

For a SMAPI (Stardew Valley) install the plugin uses the `file_drop` strategy:
the game loads every directory it finds under `Mods/`. There is no
`ModsConfig.xml`, no `<activeMods>` list, no separate "enabled" flag inside the
game's own state. **A mod is enabled exactly when its directory is inside
`Mods/`.**

That made `install` and `enable` the same operation, so `set_enabled` was
implemented as a refusal:

```python
def set_enabled(self, package_id: str, enabled: bool, *, after_confirm: bool = False):
    self._gate("enable_disable")          # descriptor: enable_disable = false
    return err("E_CAPABILITY_DISABLED", ...)
```

The descriptor carried `"enable_disable": false` with a note explaining that
`file_drop` merges install and enable into one step.

The user goal requires something different:

> 支持启用/禁用（文件移入/移出游戏目录，不删除源文件）

So "disable" has to be a real, reversible, non-destructive move — not a
refusal, and not `uninstall`.

## 2. Why `uninstall` cannot be reused as "disable"

`uninstall` moves the directory into `<GAME_ROOT>/.decky-quarantine/<txn>/` and
records `MOD_UNINSTALLED` in the journal. Its semantics are "this mod is gone,
and here is how to bring it back if the user asks". Reusing it for a daily,
cheap toggle would:

* grow a quarantine directory on every disable,
* make `status().installed` claim the mod is uninstalled when the user only
  wanted it off,
* and imply the mod is no longer owned by the plugin.

So the two operations stay separate, with separate storage.

## 3. What was added

### 3.1 A sibling parking area

`deckymod/paths.py` — `ResolvedPaths.disabled_root`:

```python
r.disabled_root = os.path.join(r.game_root, ".decky-disabled")
```

It is a **sibling of `Mods/`**, never a child. Two reasons:

1. SMAPI scans `Mods/`; a directory parked *inside* `Mods/` would still be
   loaded, so disable would silently do nothing.
2. `os.replace` is only atomic within one filesystem. Parking outside the game
   root would hit `EXDEV (18)` on a microSD library, exactly where users are
   most likely to keep mods. Keeping `.decky-disabled/` next to `Mods/`
   guarantees the same mount.

### 3.2 `set_enabled` became a real move

`deckymod/smapi.py::_set_enabled_inner`:

| step | behaviour |
|---|---|
| gate | `_gate("enable_disable")` (now `true` in the descriptor) |
| preconditions | `_check_not_running()`, `_resolve()`, `_check_write_allowed(r)` |
| direction | disable: `Mods/ → .decky-disabled/`; enable: the reverse |
| name resolution | `_pick_dir_name(package_id, known_dir, [src_root])` |
| confirm | `after_confirm=False` returns `phase="confirm"` and moves nothing |
| execute | `os.replace(src, dst)` inside a journal transaction |
| journal | `MOD_ENABLED` / `MOD_DISABLED` with `packageId`, `dir`, `name`, `from_path`, `to_path` |
| failure | reverse `os.replace` then `rolled_back` / `rollback_failed` |

Every refusal is explicit and leaves the tree untouched:

* unknown / not-in-that-direction name → `E_DUPLICATE`
* `../etc`, `a/b`, `""`, `.hidden`, `.`/`..` → `E_DUPLICATE`
* destination already exists → `E_FILE_COLLISION`
* source is a symlink or not a directory → `E_PATH_INVALID`
* game running → `E_GAME_RUNNING`
* external manager markers present → `E_EXTERNAL_MANAGER`
* different filesystem → `E_CROSS_DEVICE`

`_pick_dir_name` accepts only a single path component, refuses anything
starting with `.`, refuses if `os.path.dirname(os.path.realpath(candidate)) !=
os.path.realpath(root)`, and refuses symlinks. A crafted `packageId` therefore
cannot escape the mod tree.

### 3.3 Parked mods stay visible

`status()` now scans both roots and reports two lists:

```python
"mods":          [...],   # scanned from Mods/
"disabled_mods": [...],   # scanned from .decky-disabled/
"disabled_root": "...",   # in paths
```

Without this, disabling a mod would make it vanish from the UI and the user
would have no way to turn it back on.

## 4. Frontend

* `types.ts`: `StatusPaths.disabled_root?: string`,
  `StateInfo.disabled_mods?: ModListEntry[]`.
* `index.tsx::toggle()` was rewritten: for `file_drop` games it asks the backend
  for the confirm plan (`setModEnabled(..., false)`), hands the complete
  `ConfirmData` straight to `showConfirm`, and only then performs the move.
  The non-`file_drop` path keeps its single-step behaviour.
* `openModList()` merges `mods` and `disabled_mods` into one list, marks parked
  rows with `MODLIST_BADGE_DISABLED`, adds a `MODDETAIL_DISABLED` line in the
  detail dialog, and offers Enable / Disable / Uninstall according to the
  row's actual state.
* Two i18n keys were added in both dictionaries (`MODDETAIL_DISABLED`,
  `MODLIST_BADGE_DISABLED`); `BTN_ENABLE` / `BTN_DISABLE` already existed.
  EN 293 / ZH 293, full parity.

## 5. Evidence

### 5.1 Local

```
Ran 301 tests in 2.599s
OK (skipped=4)
UT_EXIT=0
```

Validators (all exit 0): `validate_i18n`, `validate_p0`, `validate_download_wiring`,
`r8_zipload_probe`, `r19_frontend_preflight`, `validate_api_arity`.

New tests: `tests/test_toggle.py` (10 + 1 platform skip) plus a rewritten
assertion block in `tests/test_stardew.py` that now exercises a real round trip
instead of expecting `E_CAPABILITY_DISABLED`.

### 5.2 Device build

```
TSC_EXIT=0
ROLLUP_EXIT=0
dist/index.js  6e5e42d99a67e3ea3dd0ae4e147333ee2408db467eb2f8d5536b239ea011c3d2
               133988 bytes
Ran 301 tests ... UT_RC=0
ZIP 184049 bytes / 36 entries
```

The build failed twice before passing, and both failures were real:

1. `TS2345` — a hand-built confirm object was missing `phase` and `plan`.
   Fixed by passing the backend's own `ConfirmData` through unchanged
   (strict mode was **not** relaxed).
2. `test_extract_refuses_without_a_tool` failed on the Deck because the Deck
   really has `/usr/bin/7z`, so the "no tool" premise did not hold. Fixed by
   skipping the case when a tool exists, rather than weakening the assertion.

### 5.3 Deployed

```
SAME dist/index.js                        6e5e42d9...
SAME py_modules/deckymod/smapi.py         eb15494b...
SAME py_modules/deckymod/paths.py         81dc8706...
SAME py_modules/deckymod/sevenzip.py      bef8f773...
SAME py_modules/deckymod/file_drop.py     c571be91...
SAME py_modules/deckymod/archive.py       e40a01b7...
SAME py_modules/deckymod/journal.py       f4adefd5...
SAME py_modules/deckymod/steamlib.py      1ae17d0e...
SAME py_modules/registry/games/stardew.json b9fc6a8e...
VERIFY_FAIL=0
```

(The first verification pass reported four `DIFF`s. They were false negatives:
the build tree is flat `deckymod/*.py` while the installed plugin uses
`py_modules/deckymod/*.py`, and the script compared the same relative path on
both sides. The rewritten script maps each pair explicitly.)

### 5.4 Inside the running plugin process

Driven through the real RPC route
(`DeckyBackend.call('loader/call_plugin_method', 'Decky MOD Manager', ...)`),
after `utilities/enable_plugin` reloaded the backend:

```
STATUS_OK=True
APPID=413150  CAP=True  READ_ONLY=False
DISABLED_ROOT=.../Stardew Valley/.decky-disabled
ENABLED_BEFORE=27  DISABLED_BEFORE=0
TARGET=Automate
CONFIRM_OK=True  PHASE=confirm
UNCHANGED_AFTER_CONFIRM=True
DISABLE_OK=True
ENABLED_AFTER=26  DISABLED_AFTER=1  PARKED_LISTED=True
ENABLE_OK=True
ENABLED_FINAL=27  DISABLED_FINAL=0
MATCHES_BEFORE=True
TRAVERSAL_CODE=E_DUPLICATE
RECOVERY_PENDING=0
ERROR_CODES=50
```

`Automate` is one of the user's own pre-existing mods, so this also proves the
toggle works on mods the plugin did not install.

The same round trip was independently reproduced against the build tree before
deployment, including `PAYLOAD_KEPT` (the `.dll` and `manifest.json` are intact
while parked) and `TREE_STILL_SAME` after the traversal attempt.

## 6. Still not proven

* **Nobody has looked at the panel.** The enable/disable buttons exist in the
  bundle and are wired, but `quickaccess_content_999` currently reports
  `vis:"hidden", len:0` — the QAM panel is closed, and the agent cannot open it.
  Every statement in section 5 is about the backend and the bundle, not about
  what a human sees.
* The parking area was verified on the internal library only. microSD was not
  mounted during this round, so `E_CROSS_DEVICE` is exercised by unit test
  rather than by a real card.
* Game ⑥ (end-to-end "mod actually takes effect in a running game") is still
  recorded nowhere.

## 7. Status

V1 remains the only CLOSED item. V2–V20 / F1–F3 stay OPEN. The original G3
(RimWorld 294100) stays OPEN / NOT SHIPPABLE. Step 5 write-back stays out of
scope. Track C stays independently gated. S9 (unauthenticated endpoint) and S10
(V8 flip) remain report-only.
