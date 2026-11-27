# Panel layout — one section at a time (Round 30)

The user's complaint was concrete: *"优化UI，现在功能太多杂乱且不够清晰"* — the QAM
panel had grown to five always-visible `PanelSection`s (~40 focusable nodes) so
nothing read as the primary action, and every operation was reachable only by
scrolling past everything else.

This doc records what changed, why, what is proven, and what is **not** proven.

---

## 1. What the panel looked like before

Reading `src/index.tsx` before the change (1508 lines), the render tree under
`<Focusable autoFocus>` was:

| # | PanelSection | Contents |
|---|---|---|
| 1 | `TITLE_FILEDROP` / `TITLE_XML` | game line, SMAPI line, W1/W2, quarantine, FS line, read-only banner, last result, busy line, `CONSTRAINTS`, `KNOWN_LIMITS` |
| 2 | `ACTIONS` | `REFRESH`, `INBOX`, `MODLIST`, `CATALOG`, `LIB_REFRESH`, `HISTORY`, `ERRORCODES`, `RECOVERY` |
| 3 | `GH_SECTION` | query field, search button, N result rows, N release/asset rows, N import buttons, direct-URL field, 2 direct buttons, progress line, `GH_B_GATE` |
| 4 | `INSTALLED_FILEDROP` | one `ModRow` per installed mod (29 on the test device) |
| 5 | `IMPORT_OSK` | absolute-path import box |

Every one of those was mounted on open. With 29 installed mods the panel was
~40 constant focusables plus 29 rows, and the D-pad had to walk all of it.

---

## 2. What it looks like now

```
┌─ status summary (always visible, one block) ──────────────┐
│ game · AppID · platform · state                           │
│ SMAPI: detected/missing · launcher option                 │
│ W2 (mods root)                                            │
│ FS posix · flatpak                                        │
│ [read-only banner — only when writes are blocked]         │
│ Last result: …                                            │
│ Working…/Idle                                             │
└───────────────────────────────────────────────────────────┘
┌─ Sections ────────────────────────────────────────────────┐
│ ▾ 我的 MOD (29)      My mods                              │
│ ▸ 下载 MOD           Download                             │
│ ▸ 游戏 (4)           Games                                │
│ ▸ 系统               System                               │
└───────────────────────────────────────────────────────────┘
┌─ only the open section renders below ─────────────────────┐
│  my mods → inbox / mod list / installed rows / OSK import │
│  download → full GitHub + direct-URL flow                 │
│  games    → game catalog + Steam library                  │
│  system   → refresh / history / error codes / recovery /  │
│             quarantine path / constraints / known limits  │
└───────────────────────────────────────────────────────────┘
```

Design decisions and why:

- **The switcher is three `DialogButton`s, not a tab strip.** Decky's QAM has no
  tab primitive that behaves reliably under gamepad focus. (Round 30 wrote
  "four `ButtonItem`s"; Round 81 checked the code and corrected this — it is
  three `DialogButton`s, `games` / `import` / `more`.) Round 81 also removed the
  `height: "auto"` and custom `padding` those buttons used to carry: Steam draws
  a `DialogButton`'s focus ring and backing plate at the size it computes
  internally, so overriding either decouples the visible box from the artwork
  and the highlight lands off the button.
- **`openSection` defaults to `"games"`.** (Round 30 wrote `"mods"`; the code
  has defaulted to `"games"` since the Round 76 reorganisation.) Tapping the
  open section does **not** currently collapse it to `""` — Round 30's
  description of a collapse toggle was never implemented.
- **Exactly one section body is mounted.** This is what removes the scroll
  problem: the download flow's ~6 result rows no longer sit between the user
  and the uninstall button.
- **Counts are in the switcher labels** (`我的 MOD (29)`, `游戏 (4)`), so the
  collapsed state still tells you how much is in each area. Round 81 gave the
  badge a fixed-height slot, because a conditionally rendered badge made the
  tabs different heights.
- **Nothing was moved across capability boundaries.** The read-only banner,
  `GH_B_GATE`, confirm dialogs, guards and the 16 RPCs are untouched; only the
  arrangement changed.

### Button inventory (Round 81)

Round 81 counted what the panel actually offers, because "too many buttons" is
a feeling until it is a number. Per section, with the condition that makes each
one appear:

| Section | Buttons | Conditional? |
| --- | --- | --- |
| always visible | `HANDOVER_BTN` | only when `fd && readOnly` (another manager owns the folder) |
| always visible | `QUAR_RECLAIM_BTN` | only when `!readOnly` and the quarantine holds unreachable folders |
| `games` | `GAME_SWITCH` (one per catalog row) | one per installable game |
| `games` | `LIB_REFRESH` | always |
| `import` | `AI_BTN` (auto-import new downloads) | always |
| `import` | `INBOX_LABEL` (browse local ZIPs) | always |
| `import` | `ImportBox` (absolute path field) | always |
| `import` | `DEPS_BTN` (install missing dependencies) | always |
| `import` | `NEXUS_MOD_FETCH` (fetch by mod id) | always |
| `import` | `NEXUS_RECENT_*` (3 buttons: added / updated / trending) | always |
| `import` | `SEARCH_BTN` (open the Nexus search page) | disabled until a domain and a query exist |
| `more` | `REFRESH_LABEL` | always |
| `more` | `HISTORY_LABEL` | always |
| `more` | `ERRORCODES_LABEL` | always |
| `more` | `RECOVERY_LABEL` | only when `status.recovery_needed` |

That is **8 buttons in the `import` section** and **4 in `more`**, against 2 in
`games`. The imbalance is the one layout fact Round 81 did not change, and it is
recorded here rather than fixed, because every candidate fix trades a real
capability for density:

- `NEXUS_RECENT_*` (3) could collapse into one button plus a sort selector. It
  saves 2 rows and costs one extra tap on every browse.
- `DEPS_BTN` and `AI_BTN` are both "install things I did not pick". They stay
  separate because one reads a manifest's declared dependencies and the other
  scans the Downloads folder — merging them would make a failure impossible to
  attribute.
- `ImportBox` is the only way to name a path the import-root scan does not
  cover, and it is the surface whose OSK never worked (see `docs/ACCEPTANCE.md`
  item 10). It stays, but it is a candidate for deletion if the browser-download
  scan covers every real case.

Nothing was removed in Round 81. The only frontend deletions were two imports
(`rollbackTxn`, `fetchDependencies`) that `index.tsx` no longer calls — both
live in `rollbackFlow.tsx` and `depsFlow.tsx` respectively, so the capability is
unchanged and `tsc --noEmit` stays green.

---

## 3. The mechanical change

`C:\ai\SD\.decky-probe\r29_ui_reorg.py` replaces the single block between
`    <Focusable autoFocus` and `\n    </Focusable>` and inserts one state hook
after `directUrlValue`:

```tsx
// Round 30: one section visible at a time. Before this the panel
// stacked five PanelSections (~40 focusables) at once, so nothing
// read as the primary action. "" = every section collapsed.
const [openSection, setOpenSection] = useState<string>("mods");
```

`C:\ai\SD\.decky-probe\r30_i18n_nav.py` adds the 11 `NAV_*` keys to both
dictionaries (`en` 309 → 320, `zh-CN` 309 → 320).

The script asserts `out.count("<Focusable autoFocus") == 1` and
`out.count("\n    </Focusable>") == 1` before writing, so a partial match
cannot silently produce unbalanced JSX.

---

## 4. Evidence

Local (Windows dev box, offline):

- `python -m unittest discover -s tests` → `Ran 301 tests in 3.330s` / `OK (skipped=3)` / `UT_EXIT=0`.
- `python -m compileall -q deckymod main.py tests` → `COMPILE=0`.
- `.decky-probe\validate_i18n.py` → rc=0, `EN_KEYS 320 / ZH_KEYS 320`, `EN_MINUS_ZH []`,
  `ZH_MINUS_EN []`, `USED_BUT_MISSING_* []`, `DATA_KEYS 8`, `DATA_KEYS_MISSING_* []`.
- `.decky-probe\r19_frontend_preflight.py` → `FRONTEND_PREFLIGHT_OK`,
  `BALANCE index.tsx ok`, `BARE_BUTTON_COUNT 0`, `BUTTONITEM_COUNT 15`,
  `DIALOGBUTTON_COUNT 16`, `I18N_KEYS en=320 zh=320`.
- `.decky-probe\validate_p0.py` → `ALL_STATIC_CHECKS True`.
- `.decky-probe\validate_download_wiring.py` → `DOWNLOAD_WIRING_ALL_OK=True`.
- `.decky-probe\validate_api_arity.py` → `BAD 0`.
- `.decky-probe\r8_zipload_probe.py` → `PHASE2_STATUS_OK True`.
- `.decky-probe\r4_tar_drift.py` → `TAR_COUNT 73 CUR_COUNT 73`, `MISSING_FROM_TAR` empty,
  `STALE_IN_TAR` empty, `BYTE_CHANGED_COMMON 0`.

Deck (`rebuild_final.sh` on `/home/deck/deckymod-build`):

```
TAR_OK
I18N_KEYS_EN=1 ZH=1
NO_BARE_LEAK
TSC_EXIT=0
ROLLUP_EXIT=0
DIST_SIZE=147394
DIST_SHA=0c402ba30500fa53e01300b3e15cb737c125fd9261dd39c314b7e0a63d0579df
Ran 301 tests in 0.719s
OK (skipped=1)
UT_RC=0
STATUS_OK True
STATE read_only false
MOD_COUNT 29
ZERO_DAMAGE True
SIZE 195512
SHA256 32f26b296dc926174c8644b1dc32044860401dc7f137329dda774366cbb6cf83
ENTRIES 37
REBUILD_DONE
```

`tsc --noEmit` exiting 0 is the meaningful part: the reorganised JSX genuinely
type-checks under `strict: true`. The local preflight is an import/export/balance
check and is **not** a type check.

Deploy (`r30_deploy.sh`, run on the Deck): every file `SAME`, `VERIFY_FAIL=0`,
`DIST_SHA=0c402ba3…`, `DIST_SIZE=147394`, `NAV_TITLE_HITS=5`,
`NEXUS_IN_DIST=0`, `NEXUS_FILES=0`.

Running process after `utilities/disable_plugin` → `utilities/enable_plugin`:

```
loader/get_plugins → Decky MOD Manager 0.1.0, disabled:false (7 plugins total)
status()          → APPID=413150  NAME=Stardew Valley  MODS=29  DISABLED=0  READ_ONLY=False
error_codes()     → ERRCODES_COUNT=50
```

The bundle the CEF server actually serves was fetched directly:

```
fetch("http://127.0.0.1:1337/plugins/Decky%20MOD%20Manager/dist/index.js?t=…")
→ {"s":200,"len":140319,"nav":true,"navMods":true,"gh":true,"bare":false}
```

So the running plugin process is on the new Python, and the served frontend
bundle contains the new `NAV_*` strings and no bare `<button>`.

---

## 5. What is NOT proven

- **Nobody has looked at the reorganized panel yet.** `quickaccess_content_999`
  is absent in every CEF target right now (`has:false, len:0`), which means the
  QAM panel is closed. Decky only mounts the plugin's React tree when the panel
  is actually open, and the agent cannot press `⋯`. A DOM read after the user
  opens the QAM is required before claiming the layout renders correctly.
- **Gamepad focus order is unverified.** The switcher is built from `ButtonItem`
  like every other row, so it *should* participate in the same focus ring, but
  "should" is not evidence.
- **Collapsed-state readability is unverified on the device.** The counts and
  `▸`/`▾` prefixes are static text; whether they read well at QAM scale is a
  human judgement.
- **No screenshot of the new layout exists.** The three screenshots from
  Round 28 (`qam_import_910892_1.png`, `qam_disable_910892_1.png`,
  `qam_uninstall_910892_1.png`) show the **old** stacked layout.

---

## 6. Status discipline

- No `CLOSED` added anywhere; `[x]` boxes stay 0; §B.4 unchecked.
- V1 remains the only CLOSED item; V2–V20 / F1–F3 stay OPEN; the original
  RimWorld G3 stays OPEN / NOT SHIPPABLE.
- No capability, guard, confirm flow, or RPC signature changed — the reorg is
  presentation only.

---

## 7. Round 83 — sizes come from one table, measured in rem

### The complaint this answers

Round 81 fixed the *mechanical* half of "分辨率问题，就是贴图位移" (removing style
overrides that decoupled a `DialogButton` from the box Steam draws). What it left
in place was the reason a resize is risky in the first place: every size in the
frontend was a raw pixel literal written where it was used.

Measured before the change:

| what | how many | where |
| --- | --- | --- |
| `fontSize: "NNpx"` | 54 | 9 files (`index.tsx` 47, `Modal.tsx` 18, …) |
| `gap` / `marginTop` / `padding` in px | 40 | same 9 files |
| fixed `height`/`lineHeight` in px | 2 | the switcher badge slot |

Two consequences, and only the second is a defect:

1. No single knob. Changing the caption size meant finding every copy, and the
   copy that got missed is exactly what makes a panel look uneven at one
   resolution and fine at another.
2. A raw `px` font size ignores the root font size completely. If the host ever
   scales the UI by setting that base, our text stays put while everything
   around it grows.

### What changed

`src/theme.ts` is now the only place a size is written down:

```ts
export const REM_BASE = 16;
export function rem(px: number): string { … }        // px / 16 → "0.6875rem"

export const FONT  = { badge, caption, body, bodyLg, lead, strong, title, heading };
export const SPACE = { xs, sm, md, lg, xl };
export const HEIGHT = { badgeSlot };  export const LINE_HEIGHT = { badgeSlot };
export const BORDER = { tabActive, tabIdle };        // the only px left, on purpose
export const BOX_SIZING = "border-box" as const;
export const PANEL_ROOT_STYLE / FULL_WIDTH_STYLE;
```

94 literals across 10 files became token references. The substitution was done
by `.decky-probe/r83_units.py`, which counts every replacement and **exits
non-zero if any `px` outside a border survives** — a partial pass cannot be
mistaken for a finished one.

### `box-sizing: border-box` — where it actually matters

`box-sizing: content-box` is the CSS default, so a box's declared `width` does
**not** include its padding or border: the rendered box is wider than the number
written. A QAM panel has no horizontal scrollbar, so the overflow does not
scroll — it simply falls off the right edge where the D-pad cannot reach it.

Where this actually bites in this panel, measured rather than assumed:

| element | `width: "100%"`? | padding / border? | `box-sizing` changes anything? |
| --- | --- | --- | --- |
| `MODAL_BODY_STYLE` / `colStyle` (`Modal.tsx`) | no — it is a stretched flex child | `padding: SPACE.xl` (ours) | **yes** — this is the one proven case |
| the 10 `width: "100%"` containers | yes | none in our own style | **unknown** — see below |
| the tab strip's `borderBottom` | no | a bottom border | no — vertical only |

So the honest statement is: **one container is provably mis-sized by content-box
today** (`colStyle`, which carries our own `padding: SPACE.xl` and is stretched
by its flex parent). The other ten are declared border-box as a guard, not
because a defect was observed there.

**Why the ten are "unknown" rather than "fine":** they are all `Focusable`
elements, and `Focusable` is Decky's wrapper around a Steam component whose
padding comes from Steam's runtime stylesheet, not from our source. That sheet
is not in this repo (`node_modules/@decky/ui` ships no CSS; the styles live in
the Deck's own frontend bundle), so whether those elements carry padding could
not be established offline. If they do, content-box would have made each of them
overflow its parent by exactly that padding — which is a plausible shape for the
reported "elements drift off the panel". Declaring border-box makes the question
moot either way, and costs nothing if they carry none.

**This is the honest limit of the change:** it removes a whole class of
horizontal overflow, but it was not shown to fix an observed overflow at any of
the ten sites. Confirming which (if any) of them were actually overflowing needs
the device — see `docs/ACCEPTANCE.md` §B.5, R1/R2.

A global `* { box-sizing }` rule was deliberately **not** used: this plugin would
be restyling Steam's own components, which is the same class of mistake Round 81
spent its time undoing.

### What this does and does not prove

**Proven (local, offline):**

- 1033 tests `OK (skipped=17)`; `tsc --noEmit` exit 0; `rollup -c` exit 0
  (`dist/index.js` 257740 B).
- `tests/test_style_units.py` (21 cases) pins the rules:
  - no `fontSize`/`gap`/`margin`/`padding` in px anywhere in `src/` (a px left
    over fails by name and file), and no px on **any** sizing longhand either —
    `paddingTop`, `minHeight`, `maxHeight`, `lineHeight`, `width` are all in
    `LENGTH_PROPS`, so a new one cannot slip in beside the converted ones;
  - every token still reproduces the exact pixel value it replaced, checked by
    re-applying the implementation's own `parseFloat(v.toFixed(6))` rounding;
  - the token **census** matches: every (file, token) pair must be used exactly
    as many times as recorded, which is what catches a wrong-token swap;
  - no token is unused (word-boundary match, so `FONT.body` is not satisfied by
    `FONT.bodyLg`), and no JSX file names a token it did not import;
  - every `width: "100%"` line sets `boxSizing: BOX_SIZING` — the *value* is
    checked, not just the presence of the word;
  - `HEIGHT.badgeSlot` and `LINE_HEIGHT.badgeSlot` are each pinned inside their
    own block and must agree;
  - no global `*` rule and no `insertRule` was added; no dead style export.

### The audit that changed this section

The first version of this round shipped 16 tests that passed while proving much
less than they appeared to. A read-only auditor mutated a copy of the tree and
demonstrated the gaps; the table below is the result *after* the rewrite, and
each row was re-run against a scratch copy of `src/`+`tests/`:

| mutation | caught by |
| --- | --- |
| `fontSize: FONT.caption` → `fontSize: "11px"` | `test_no_px_font_size_survives_anywhere` |
| `fontSize: FONT.caption` → `fontSize: 11` | `test_no_px_font_size_written_as_a_bare_number` |
| new `paddingTop: "4px"` / `height: "20px"` / `margin: "8px"` | `test_no_px_length_on_any_sizing_property` |
| `caption: rem(11)` → `rem(12)` | `test_every_token_reproduces_the_number_it_replaced` |
| `boxSizing: BOX_SIZING` → `"content-box"` | `test_the_declared_value_is_border_box_not_merely_present` |
| one `boxSizing` line deleted | `test_the_modal_body_is_border_box` |
| `FONT.caption` → `FONT.body` (wrong token) | `test_the_token_usage_census_matches` |
| `FONT.body` → `FONT.bodyLg` | `test_the_token_usage_census_matches` |
| `SPACE.md` → `SPACE.sm` | `test_the_token_usage_census_matches` |

The first draft's `test_the_arithmetic_holds_for_every_value_in_the_table` was
**tautological**: it took each number from the table, multiplied it back by 16,
and compared it to itself — never reading `rem()`. Rewriting `rem` to return
`(v * 2) + "rem"` left it green. It has been replaced by a test that asserts the
implementation's rounding expression is present and applies that expression.

Two other draft assertions were weaker than they read and are fixed: the
`badgeSlot` regex was unanchored (either of two blocks satisfied it), and the
unused-token check used a substring test (`FONT.body` was satisfied by
`FONT.bodyLg`).

**Still not caught by any test, and known:** the census is a snapshot, so a
deliberate new row requires editing the census too — it will fail loudly rather
than silently, which is the intent, but it is bookkeeping, not verification.

**NOT proven, and not claimed:**

- **`rem` is not magic and changes nothing today.** `1rem` is the root font
  size, which with no override is 16px — so `rem(11)` and `"11px"` render
  identically. That equality is the whole of the claim. Whether the Deck's QAM
  ever sets a non-16px root font size is unknown; if it does, this change makes
  the panel follow it, which is the point, but no device observation of that
  exists.
- **No human has looked at the panel at any resolution.** Every layout
  conclusion in this document still comes from DOM text over CDP. 1280×800 and
  1920×1080 remain unverified by eye — see `docs/ACCEPTANCE.md` §B.5, added in
  this round as the checklist that would close it.
- **The px→rem swap is not a visual fix.** If the panel looks wrong at
  1920×1080, this round did not change how it looks at 16px root; it changed how
  many places have to be edited to fix it.

### Status discipline (unchanged)

- No `CLOSED` added; `[x]` boxes stay 0; §B.4 unchecked.
- V1 remains the only CLOSED item; V2–V20 / F1–F3 stay OPEN; G3 stays OPEN.
- No capability, guard, confirm flow, RPC signature, or i18n key changed.

## 8. Round 84 — the panel gains the controls it was describing

Round 84 came out of a functional audit, not a layout one, but four of its ten
items are panel structure, so the layout record has to change with them.

### New: `src/components/ApiKeyBox.tsx`

The Nexus section now owns the API key. Before this round the panel *described*
a key ("enter your Nexus API key in this panel first", in a `data.hint` no
control could act on) while `src/api.ts`'s four key functions had no caller
anywhere in `src/`. That is the worst shape a panel can be in: text that tells
the user to do something the panel does not offer.

The box is a `PanelSectionRow` holding:

| Element | Notes |
| --- | --- |
| status line | three states (`present` / `unreadable` / `missing`), from `apiKeyStatus().state` |
| `TextField` | the key itself, `width: "100%", boxSizing: BOX_SIZING` on the same line (see below) |
| `BTN_KEY_SAVE` | disabled while empty or busy |
| `BTN_KEY_VALIDATE` | disabled unless the status is `present` — validating a key that is not stored asks the network about nothing |
| `BTN_KEY_DELETE` | disabled when the status is `missing` |

Two behaviours worth naming, because both are about not leaking or lying:

- **Saving clears the field.** The key is on disk after the RPC; leaving it in
  the `TextField` keeps the plaintext in the DOM for the rest of the session.
- **`posix: false` is shown.** On a filesystem that cannot hold `0600` the
  status says so rather than claiming the file is protected.

A layout trap, caught by an existing test rather than by review:
`test_every_hundred_percent_width_declares_border_box` reads **one line at a
time**. Writing

```tsx
width: "100%",
boxSizing: BOX_SIZING,
```

fails it, because `boxSizing` is not on the same line as the `width`. The pair
has to be `width: "100%", boxSizing: BOX_SIZING,` on one line. The test is
right to be strict here: it is checking that the two declarations travel
together, and a reviewer reading a diff sees them together or not at all.

### New: the archive picker

`pickArchiveMod()` lives in `src/index.tsx` (not a component file) and is a
`showListModal` whose rows come from the `archive_mods` RPC. Each row's label is
the mod's `name`, falling back to its root path; the subtitle carries the root,
the version and the file count.

The `onActivate` handler closes the picker and re-enters `inspectAndImport`
after a 250 ms delay via the existing `later()` helper. The delay is not
cosmetic: opening one `showModal` from inside another's callback drops the
second one, which is the same failure the FOMOD flow already worked around.

### Changed: rows that used to do nothing

`doCheckModUpdates` used to build rows with `onActivate: () => {}`. A list whose
rows are pressable and inert is worse than a plain list: the focus ring says
"there is something here" and pressing proves there is not. Rows now open the
mod's Nexus page when the row declares a Nexus id, which is a real destination
(`open_mod_page` needs no API key).

### Style discipline

`tests/test_style_units.py` covers two more files this round:
`src/components/ApiKeyBox.tsx` and `src/depsFlow.tsx` (the latter had never been
in `UI_FILES` at all — it happened to use zero tokens, which is a fact worth
asserting rather than assuming). The per-(file, token) census gained
`ApiKeyBox.tsx: {FONT.body: 1, FONT.caption: 4, SPACE.md: 2}`.

Status discipline is unchanged: no `CLOSED` added, `[x]` boxes stay 0, §B.4
unchecked, V2–V20 / F1–F3 / G3 stay OPEN.
