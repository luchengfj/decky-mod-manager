# Download sources — GitHub Releases + arbitrary HTTPS URL (round 19)

Written 2026-11-15. This document records **why** the Nexus download chain was
retired and **what replaced it**, based on real-device measurements taken over
the deck-helper terminal API (`:{{HELPER_PORT}}`) with the Deck's own `/usr/bin/python3`
(`OpenSSL 3.6.5`), i.e. real TLS against real servers, not a local mock.

Nothing in this file is a claim that the feature was seen working in the QAM
UI. The backend is proven by tests and by device probes; the frontend is
unverified until it is built and loaded.

---

## 1. Why Nexus was dropped

Round 18 wired the Nexus API end-to-end and it worked at the read layer, but
the download layer hit an external policy wall:

| Probe | Result |
| --- | --- |
| `users/validate.json` with a real 96-char key | **HTTP 200** |
| `mods/stardewvalley/mods/2400/files.json` | **HTTP 200**, 343 files |
| `download_link.json` (real key, real mod) | **HTTP 403 `NX_FORBIDDEN`** |

The 403 is Nexus's own rule for non-Premium accounts: the download-link
endpoint is not served to free accounts. That is an external business decision,
not a bug we can fix, and it is **not** something to work around. Per user
instruction (m10068: 「不走Nexus，走其他地方实现下载MOD」) the whole Nexus
credential + directory surface was removed rather than left half-working.

## 2. What was measured about the alternatives

Every candidate was probed on the device, not assumed:

| Source | Verdict |
| --- | --- |
| **GitHub Releases** | ✅ works end-to-end (see §3) |
| `api.curseforge.com` | ❌ 403 — requires an official API key |
| `api.moddrop.com` | ❌ DNS does not resolve |
| `www.moddrop.com` | ❌ SPA shell only, 2533 bytes, no API |
| `thunderstore.io` | ❌ no `stardew-valley` community (404) |
| `gitlab.com` | ❌ URLError |
| `api.mod.io` | ❌ 502 |
| `itch.io` | ❌ URLError |
| `raw.githubusercontent.com` | ⚠️ unstable (200 then 404) — unusable as a download path |
| `codeload.github.com` | ⚠️ 200, but serves **source zipballs**, not release builds |
| `smapi.io` mod list | ⚠️ has 4740 entries, but 4601 point at Nexus and only 13 at GitHub; the underlying SAS token rotates every ~300 s and the site is a SPA shell |

**smapi.io detail** because it is easy to mis-read: `GET /mods` returns a
7731-byte SPA page. The catalogue lives in a short-lived SAS URL embedded in
that page; fetching it yields 1,554,067 bytes / 4740 mods with keys
`AlternateNames, Author, Id, ModPages, Name, Slug`. Only 13 of those 4740 have
a GitHub page, so it cannot serve as a download index. The usable API is
`POST /api/v2.2/mods` with `{"mods":[{"id":...}],"includeExtendedMetadata":true}`
— note the object-array body; a plain string array silently returns `[]` — and
even that returns `null` for many real mods (`Pathoschild.SpaceCore`,
`Esca-MMC.DestroyableBushes`, …). It is a metadata lookup, not a directory.

## 3. How the GitHub path works

Two hops, and the first hop's URL is the only one that may ever be used:

```
GET https://api.github.com/repos/{owner}/{repo}/releases?per_page=5
   -> assets[].id, assets[].name, assets[].size, assets[].content_type
GET https://api.github.com/repos/{owner}/{repo}/releases/assets/{id}
    Accept: application/octet-stream
   -> 302 Location: https://release-assets.githubusercontent.com/...?sig=...
   -> (we check the host, then follow it ourselves)
```

Measured on the device: the second hop returns **302** with a signed
`release-assets.githubusercontent.com` URL; following that returns **200**,
and the bytes parse as a ZIP (`Esca-MMC/DestroyableBushes`, 44,252 B, 12
entries; `tiwe0/sdv-hd2d-release`, 2,028,243 B, SHA-256 `63a9900e8b6a21fe…`).

**Never use `browser_download_url`.** On this device `github.com` is mapped to
`127.0.0.1` in `/etc/hosts` behind a local TLS proxy, and that URL form returns
**502 with 0 bytes**, every time. The API asset endpoint is the only path that
works. This is also why `ASSET_HOSTS` is an explicit hostname allow-list and
why the redirect is *not* followed blindly: a 302 pointing anywhere else is
rejected with `NX_HOST_NOT_ALLOWED` before a second request is made.

### Rate limits and integrity

- Unauthenticated: **60 requests/hour** (`/rate_limit` confirmed,
  `core.remaining 57`). There is no `ETag` / `If-None-Match` support on these
  endpoints (verified: conditional request still returns 200 with the full
  body), so there is no 304 shortcut — the client must cache locally or the
  user will burn the budget. Nothing in this round implements that cache.
- `assets[].digest` is **`None`** on real responses, so upstream content hashes
  are not available. Integrity therefore rests on: the declared `size`, our
  own SHA-256 of the downloaded bytes (recorded and returned), and the mod
  manifest inside the archive (`UniqueID`) as parsed by the existing
  `inspect()` path.

### Coverage is genuinely limited

`Pathoschild/StardewMods` — 962 stars, home of Content Patcher, Automate and
LookupAnything — has **zero releases** (`releases?per_page=3` returns `[]`,
`releases/latest` returns 404). Several other popular mod repos behave the
same. So "search GitHub and download" cannot be sold as a general mod
browser. `LIMIT_GH_COVERAGE` in the descriptor says this to the user in the
UI, and the direct-URL source in §4 exists for exactly this gap.

## 4. The direct-URL fallback

`download_url(url, filename, allow_install, after_confirm)` accepts any HTTPS
URL the user pastes. Guard rails, all enforced before a single byte is
fetched:

- HTTPS only — plain `http` is refused (`E_PATH_INVALID`).
- No userinfo (`user:pass@`), no non-443 port.
- Hostnames that are *literally* private (`localhost`, `127.0.0.1`, `::1`,
  private/link-local/reserved IPs) are refused (`E_PATH_ESCAPE`).

**What is deliberately NOT done:** there is no "resolve the hostname and refuse
if the answer is a private IP" check. On this very device `api.github.com`
resolves to `127.0.0.1` because of the hosts file, while the traffic still
reaches the real GitHub through a local proxy. An IP-based check would have
declared the working path dead. The allow-list therefore matches **hostnames**,
never resolved addresses.

The direct URL has no trust anchor of its own — whatever it downloads still has
to pass `inspect()`, and it lands only in the inbox, never in `Mods/`.

## 5. What the three download phases do

Both `gh_download` and `download_url` are tri-state, and the states are
strictly ordered so that a mistake in the frontend cannot cause a write:

```
phase 1  allow_install=False  -> download to inbox, inspect, WRITE NOTHING
phase 2  allow_install=True, after_confirm=False -> show plan, WRITE NOTHING
phase 3  allow_install=True, after_confirm=True  -> engine.install(...)
```

Phase 3 delegates to the engine and **returns its verdict verbatim**. On the
current device that verdict is `E_EXTERNAL_MANAGER`, because Amethyst's VFS
deployment (`.mm_deployed`, `Mods_Core/`) still owns `Mods/`. The coordinator
never catches, hides, downgrades or retries that code — `auto_import._install`
is a single `return engine.install(...)` with no exception handler, and a test
asserts that shape via AST as well as by execution.

## 6. Error codes: no new ones

`errors.py` still has exactly **50** codes. The network layer uses `NX_*`
codes internally (18 of them) and `auto_import.NX_TO_E` translates every one
onto an existing shipped `E_*`:

| new internal code | maps to |
| --- | --- |
| `NX_HOST_NOT_ALLOWED` | `E_PATH_ESCAPE` |
| `NX_NO_ASSET` | `E_INBOX_UNREADABLE` |
| `NX_NOT_FOUND` | `E_INBOX_UNREADABLE` |

A test asserts both directions (every `NX_*` has a mapping, no mapping refers
to a non-existent `E_*`), which is what keeps `error_codes()` and the i18n
dictionaries stable.

## 7. State of things — read this before trusting any of the above

**Proven here (offline, deterministic):**
- 207 local tests pass, including 29 for `github_source.py` and 19 that drive
  the four RPCs through `asyncio.run` with an injected opener.
- `compileall`, `validate_i18n`, `validate_p0`, `validate_download_wiring`, the
  ZIP-layout probe and the tar-drift check all exit 0.
- The frontend is written and passes a static preflight
  (`r19_frontend_preflight.py`): all 18 + 16 + 3 imported names resolve to real
  exports, every `callableHandles` entry is invoked, every `invoke()` names an
  RPC the backend actually has, all 196 `t()` literals plus their `ERR_` codes
  exist in both dictionaries, no `as any` / `@ts-ignore` / `: any`, and
  brace/paren balance holds per file.
- Both dictionaries are at 270 keys with zero drift; the 18 `NEXUS_*` keys were
  replaced by 25 `GH_*` keys, and `NEXUS_SECTION` no longer appears anywhere.

**Proven on the device (round 19 build + probes):**
- `tsc --noEmit` exits **0** and `rollup -c` exits **0** on the Deck; the bundle
  is `dist/index.js` 120512 B `e4fa4a70bcf278295490b94e2fe59aaede2890d37eb5945f0828ffa3ee30ea9e`.
- The full suite runs **207 tests, OK** on the Deck too (same count as the dev
  box). Reaching that took two real fixes: the driver's stale-file purge now
  covers `tests/*.py` (a deleted `test_wiring.py` used to survive in the build
  tree and produce 14 phantom `AttributeError`s), and one test had a hardcoded
  `C:\ai\SD` root that is meaningless on Linux.
- A packaged ZIP was produced: **163030 B / 34 entries**,
  `SHA256 5273ce12a8994021818d55f0d729a0c73004f436034da9841cea8847c95b6603`,
  downloaded back and byte-verified locally.
- Driving the four RPCs against the **real network** from the build tree:
  `gh_search("stardew mod", 1)` → `total_count 2549`, 10 items, top hit
  `Pathoschild/StardewMods` 962★. `gh_releases("Esca-MMC","DestroyableBushes")`
  → 5 releases, 5 usable zip assets. `gh_download(..., allow_install=False)`
  → `phase=inspect`, downloaded 44252 B with
  `sha256 e8e19ad1bad80ea399789cae97143d70bb343a6ac8166f5234931d8492b502ac`
  (identical to the recon measurement), parsed `uniqueId Esca.DestroyableBushes`
  / `version 1.5.2`. With `allow_install=True, after_confirm=False` →
  `phase=confirm`, still zero writes.
- **Phase 3 is genuinely gated**: with both flags true the call returns
  `ok=False, code=E_EXTERNAL_MANAGER`, detail *"external mod manager markers in
  …/Stardew Valley/Mods; read-only mode"*, and a name/size/mtime fingerprint of
  `Mods/` is unchanged (`MODS_BEFORE 28 1c96b7a56a505b09` → `MODS_AFTER` the
  same), with no new mod directory created. `read_only` stays true, `MOD_COUNT`
  stays 27.
- Direct-URL guards hold on the device: `http://` → `E_PATH_INVALID`
  (`NX_BAD_URL`), userinfo → `E_PATH_INVALID` (`userinfo is not allowed`),
  `https://127.0.0.1/…` → `E_PATH_ESCAPE` (`NX_LOCAL_HOST`), and a real
  `codeload.github.com` zip → `phase=inspect`.

**NOT proven — do not claim otherwise:**
- The QAM panel showing the new `GH_SECTION`. The bundle compiles and type-checks,
  but **the deployed plugin is still the round-12 build**
  (`7c10bbb8…`/118664 B) while the new bundle is `e4fa4a70…`/120512 B, so nothing
  in the panel has been rendered, loaded into CEF, or looked at. Reinstalling the
  new ZIP through Decky UI is a user action.
- Any successful install into `Mods/`. Amethyst still owns the directory, so
  phase 3 returns `E_EXTERNAL_MANAGER` by design (B prerequisite, user action).
- The Nexus key/credential path: removed from the plugin. `credentials.py`
  stays on disk, unused, for a possible future optional GitHub token.
- A download of a *real* mod the user actually wants, on a machine where the
  install is permitted.

**Still open, unchanged:** V1 is the only CLOSED item; V2–V20 / F1–F3 all OPEN;
original G3 (RimWorld 294100) OPEN / NOT SHIPPABLE; Step 5 write-back out of
scope; Track C separately gated; endpoint `:{{HELPER_PORT}}` unauthenticated and V8
status flip remain reported-only, awaiting user adjudication.

## 8. Round 20 — managing mods the plugin did not install

The user's goal is *"download a mod, one-click install, one-click import, and
manage mods."* Download, install and import were already demonstrated. **Manage
was only half-true**: `uninstall` consulted the journal alone, so a mod that was
already on disk before this plugin existed could be listed but never removed —
every attempt returned `E_DUPLICATE: <id> is not installed/managed`. On the real
Deck that meant the user's 27 pre-existing mod directories were read-only in
practice.

**What changed (two small, additive edits):**

- `deckymod/smapi.py` gained `_resolve_disk_dir(name, mod_root)`. When the
  journal has no record, `_uninstall_inner` now asks it whether `name` is a real
  directory sitting directly inside `Mods/`. The identifier is a **directory
  name, never a path**: no separators, no `.`/`..`, nothing starting with `.`,
  no symlink, and the `realpath` parent must equal `realpath(Mods/)`. Anything
  else returns `None` and the caller raises the original `E_DUPLICATE`.
- The plan record now carries `previously_managed: false` for such mods, which
  is honest about rollback: it returns the folder, but the journal never owned
  it, so there is no "re-enable" semantics to fake.
- `src/index.tsx` shows an uninstall action in the *Detected mods* detail sheet,
  but only when `file_drop && !readOnly`, so the button exists exactly when the
  engine would actually allow the write.

**What did NOT change:** every write still passes `_check_write_allowed()`,
the quarantine is still a move (never a delete), rollback is still
`os.replace` back, and the read-only posture still outranks the new branch.

**Proven offline (round 20):** `Ran 221 tests, OK (skipped=2)` — 207 previous
plus 14 new in `tests/test_manage_existing.py` covering a plain pre-existing
directory (list → confirm does not touch disk → quarantine → rollback restores),
the journal-managed path keeping `previously_managed=True`, and refusals for
`..`, `a/../b`, `a/b`, absolute paths, `.hidden`, `.`, empty string, a regular
file, a nested directory, a symlink, the read-only tree and a running game.
`compileall` and all six static validators exit 0.

**Proven on the device (round 20):** built from the deployed tree on the Deck,
`python3 /tmp/r20_manage_existing_probe.py` printed

```
MODS_ROOT …/Stardew Valley/Mods
READ_ONLY False
CREATED …/Mods/zz.r20.existing.dir files 2
LISTED True TOTAL 28
JOURNAL_MANAGED True
CONFIRM_OK True PHASE confirm
CONFIRM_PREV_MANAGED False
STILL_ON_DISK_AFTER_CONFIRM True
UNINSTALL_OK True
QUARANTINE …/.decky-quarantine/20261115T143749-67f4d533/zz.r20.existing.dir
GONE_FROM_MODS True
QUARANTINE_FILES ['Round20Existing.dll', 'manifest.json']
ROLLBACK_OK True
RESTORED True
RECOVERY_PENDING []
REFUSE '..' False E_DUPLICATE        (same for 'a/b', '/home/deck', '.hidden', 'no.such.mod')
MOD_COUNT_AFTER 27
```

i.e. a directory the plugin never installed is now listed, confirmable,
quarantined, and restorable — and every malformed identifier is still refused.

**Device build numbers (round 20):** `TSC_EXIT=0`, `ROLLUP_EXIT=0`,
`dist/index.js` 122825 B
`dd13a7a35c174c74695808e6f8b1ae1d31b07ca5da699f57fa666b4a7df652fd`,
`Ran 222 tests OK` on the Deck, ZIP 165331 B
`fc29422905285ce126a9f5fb06dfe29710749a0397b6195a62941ea9cb9d3523`, 34 entries.
The deployed plugin now serves a bundle containing `doUninstallDir` and
`canRemove` (verified by fetching it through
`http://127.0.0.1:1337/plugins/Decky MOD Manager/dist/index.js`), and
`py_modules/deckymod/smapi.py` on the Deck is
`4f4d0085a53ac605177d6e6059f95c846d8d343bf7298a2586dca66ceee80695`.

**A real bug the device found, and the fix.** `uninstall` was reachable with a
*directory name* (that is what the detected-mod list shows) while the journal is
keyed by *UniqueID*. The `MOD_UNINSTALLED` event was therefore written under the
directory name, `installed()` never popped the original key, and a stale record
survived every uninstall — visible as `MODS` shrinking on disk while the plugin
still claimed to own a mod. Fix in `deckymod/smapi.py`: when the journal does not
own the identifier, `_uninstall_inner` now looks for a journal record whose
`dir` realpaths to the same directory and adopts that record's `packageId`; all
events are then recorded under `journal_id`. Proven on the device:

```
CLEARED Esca.DestroyableBushes True      # historical stale entry, folder already gone
JOURNAL_CLEAN True
INSTALL_OK True
OWNED_BEFORE ['Esca.DestroyableBushes']
UNINSTALL_BY_DIR_OK True
PACKAGE_ID_USED Esca.DestroyableBushes    # recorded under the journal's key, not the dir name
OWNED_AFTER []
JOURNAL_EMPTY_AFTER True
DISK_MODS 27
```

**Full user story, proven end to end on the device** (`r20_e2e_story.py`, a real
network download of `DestroyableBushes.1.5.2.zip`):

```
READ_ONLY False
MODS_BEFORE 27
RESOLVE_OK True release-assets.githubusercontent.com
DOWNLOAD_OK True PHASE inspect
DOWNLOADED DestroyableBushes.1.5.2.zip 44252 e8e19ad1bad80ea3
MODS_UNCHANGED_AFTER_DOWNLOAD True
CONFIRM_OK True PHASE confirm
MODS_UNCHANGED_AFTER_CONFIRM True
INSTALL_OK True
INSTALLED_DIR esca.destroyablebushes
MODS_AFTER_INSTALL 28
VISIBLE_IN_LIST True TOTAL 28
UNINSTALL_OK True
GONE_FROM_MODS True
QUARANTINED True
MODS_AFTER_UNINSTALL 27
ROLLBACK_OK True
RESTORED True
MODS_FINAL 27 EXPECTED 27
RECOVERY_PENDING []
READ_ONLY_STILL False
```

That is download → one-click install → managed/visible → uninstall →
rollback, on the real Deck, with the tree returned to its original 27 mods.

**Still not proven for round 20:** the *panel* rendering the new uninstall
action. The plugin was reloaded through `DeckyPluginLoader`, but the QAM keeps
the React tree that was mounted when it was opened, so the visible text still
came from the previous bundle. Reopening QAM (press `⋯` twice) is a user action
and is the only remaining step for this item.

### Round 20b — the whole objective, driven through the real RPC surface

The round-20 runs above called the engine directly. The Qt panel does not: it
calls the plugin's positional RPCs over Decky's socket. Round 20b therefore
re-ran the *entire* objective through `main.Plugin()` itself
(`r20c_rpc_story.py` / `r20c_local_rpc.py`, both executed on the device against
the deployed plugin tree):

```
STATUS_OK True APPID 413150
MODS_BEFORE 27 READ_ONLY False
RPC_SEARCH_OK True N 10
RPC_RELEASES_OK True N 5
ASSET DestroyableBushes.1.5.2.zip 252770482
RPC_INSPECT ok= True phase= inspect  unchanged= True     # zero writes
RPC_CONFIRM ok= True phase= confirm  unchanged= True     # zero writes
RPC_INSTALL ok= True dir= …/Mods/esca.destroyablebushes mods= 28
RPC_UNINSTALL ok= True mods= 27
RPC_ROLLBACK ok= True mods= 28
RPC_CLEAN ok= True mods= 27
RPC_HISTORY ok= True N 5
RPC_ERRCODES ok= True COUNT 50
FINAL_MODS 27 EXPECTED 27
FINAL_JOURNAL []   FINAL_RECOVERY []   FINAL_READ_ONLY False
```

and the local-ZIP half of the objective through the same RPCs:

```
RPC_INSPECT ok= True id= DeckyModManager.R20cLocalZip
RPC_CONFIRM ok= True phase= confirm  unchanged= True
RPC_INSTALL ok= True mods= 28
VISIBLE True TOTAL 28
RPC_UNINSTALL ok= True mods= 27
RPC_ROLLBACK ok= True mods= 28
RPC_CLEAN ok= True
FINAL_MODS 27 EXPECTED 27   FINAL_JOURNAL []   FINAL_RECOVERY []
```

So all four verbs in the objective — download, one-click install, one-click
import, manage — are exercised on the device through the exact surface the panel
uses, with the Mods tree returned to its original 27 directories each time.

### Round 20b — two more real bugs the device found

**1. A second rollback of the same transaction claimed success.** The restore
step was a no-op because the source directory already existed again, but the
caller was told the mod had been restored once more. Fixed in
`_rollback_inner` (`deckymod/smapi.py`) by refusing when the journal already has
a `MOD_ROLLBACK_RESTORED` event for that txn; covered by
`tests/test_manage_existing.py::test_second_rollback_of_the_same_txn_is_refused`.
On the device the matrix now reads:

```
A_INSTALL_OK True / A_UNINSTALL_BY_ID_OK True / A_JOURNAL_EMPTY True
B_DOUBLE_UNINSTALL_REFUSED True / B_JOURNAL_STILL_EMPTY True
C_ROLLBACK1_OK True / C_ROLLBACK2_OK False / C_ROLLBACK2_CODE E_UNKNOWN
D_CLEAN_OK True / D_BACK_TO_BEFORE True
E_EXEC_AFTER_VANISH_CODE E_DUPLICATE (folder removed between confirm and execute)
F_GAME_RUNNING_CODE E_GAME_RUNNING / UNTOUCHED True
G_MODS 27 EXPECTED 27 / G_JOURNAL [] / G_RECOVERY [] / G_READ_ONLY False
```

**2. The detected-mod list still advertised itself as read-only.** After round
20 made pre-existing directories removable, `MODLIST_TITLE` still said
「检测到的 MOD（只读，{n}）」/ "Detected mods (read-only, {n})", and the English
fallback in `src/index.tsx` had the same stale wording. Both dictionaries and
the fallback now say 「检测到的 MOD（{n}）」, and `MODLIST_SUB` explains that
opening an entry offers Uninstall when writes are allowed. Verified in the
deployed bundle: `OLD_READONLY_TITLE 0`, `NEW_TITLE 2`, `CAN_REMOVE 2`.

**Deck build numbers (round 20b):** `TSC_EXIT=0`, `ROLLUP_EXIT=0`,
`Ran 223 tests OK (skipped=2)` on the device, `dist/index.js` 122960 B
`702acd652af944857aedef7d3ffadc52215d7eb662908c6f3d02d2932e11f7ef`, ZIP 165553 B,
34 entries, `main.py`
`f80e1663ab21571cbba87252d7b91477bb9d3558dee52cbab230a2f95528459b`.
After the final rebuild, `dist/index.js`, `main.py` and
`py_modules/deckymod/smapi.py` on the Deck hash equal to the build tree
(`702acd65…` / `f80e1663…` / `8fd3fa38…`), confirmed by `sha256sum` on both
paths rather than by trusting the copy exit code. The ZIP hash changes between
rebuilds (zip timestamps), so it is a per-build artifact id, not a stable
identity.

**Tooling lesson, recorded because it silently corrupted two runs:** converting
an uploaded script with `sed -i "s/\r$//"` does not strip CR — in GNU sed `\r`
is a literal `r`, so it deletes every trailing `r` and turned
`…/decky-mod-manager` into `…/decky-mod-manage` (and `import` into `impot`).
`tr -d "\r"` is worse: it removes every `r` in the file. Upload scripts
base64-encoded (`echo <b64> | base64 -d > x.sh`) or with `\r\n` already
normalised before transfer; a deployment that reports `CP=0` still has to be
confirmed with `sha256sum` on both sides.

**A gap the type checker cannot see, now covered by a validator.**
`tsc --noEmit` proves the TypeScript types line up, but `invoke()` is variadic,
so a wrapper that passed `(assetId, owner, repo, …)` would still type-check and
fail only at runtime with a confusing backend error. `validate_api_arity.py`
(added this round) parses `src/api.ts` for every `invoke<…>("rpc", a, b, …)` and
compares it against the parameter list of the matching `main.py::Plugin` method,
by name and arity:

```
BACKEND_RPCS 15
FRONTEND_CALLS 15
OK gh_download 6 → ['owner', 'repo', 'asset_id', 'filename', 'allow_install', 'after_confirm']
OK download_url 4 → ['url', 'filename', 'allow_install', 'after_confirm']
BAD 0
```

All seven validators now exit 0: `validate_i18n.py`, `validate_p0.py`,
`validate_download_wiring.py`, `r8_zipload_probe.py`, `r19_frontend_preflight.py`,
`r4_tar_drift.py`, `validate_api_arity.py`.

### Round 20b — what is live right now, and what is not

The two layers reload differently, and the difference matters when reading the
evidence above:

* **Frontend** — `dist/index.js` is fetched by Decky through
  `http://127.0.0.1:1337/plugins/…/dist/index.js?t=<cache-buster>` every time the
  QAM panel mounts, so the *next* time the panel is opened it renders the new
  bundle (served copy verified: 116788 B, `OLD_READONLY_TITLE 0`,
  `NEW_TITLE 2`, `CAN_REMOVE 2`).
* **Backend** — `plugin_loader` keeps the plugin's Python modules in
  `sys.modules`. The loader process started `2026-11-15 21:14:27 CST`, while
  `py_modules/deckymod/smapi.py` was last written `23:03:26 CST`, so the running
  plugin still executes the pre-fix module. `DeckyPluginLoader.importPlugin`
  answered `Plugin … is already loaded and has requested to not be re-loaded`,
  and `sudo -n true` is denied for the `deck` user, so the agent could not force
  a cold reload.

The on-disk fix is therefore verified in a **fresh interpreter against the
deployed tree** (that is how `r20b_manage_robust.py` produced
`C_ROLLBACK2_OK False`), and it reaches the live plugin after the plugin is
restarted from Decky's UI. Stated plainly: the backend behaviour claimed here is
proven for the deployed code, and the running process catches up on the next
plugin restart — not a claim that the currently-running process already has it.



**Not a bug, checked rather than assumed:** the two remaining `parse_error`
entries (`LookupAnything`, `SMAPI 4.5.2 installer`) really have no
`manifest.json` anywhere in their trees, and all 16 reported missing
dependencies (`BURAKMESE.SKE`, `Candidus42.LittleNPCs`, …) are genuinely absent
from `Mods/`. Both reports are accurate, so no code change was warranted.

## 9. Round 21 — the network was broken inside the plugin, and only the plugin could say so

Everything before this section proved downloads from an SSH shell running
`/usr/bin/python3`. The plugin does not run in that interpreter: Decky hosts it
in a PyInstaller-frozen one. Driving the **live plugin process** over Decky's own
RPC route showed that all three network RPCs failed there:

```
E_BRIDGE  [gh_search] NX_NETWORK: URLError: <urlopen error
[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed:
unable to get local issuer certificate (_ssl.c:1082)>
```

So "downloads work" was true for the shell and false for the product. This is
the single most useful thing the live-process route has produced so far.

### 9.1 Why it failed — two separate causes, and the obvious fix was wrong

* **The frozen interpreter does not consult OpenSSL's compiled-in CA paths.**
  A bare `urlopen` there has no trust anchors at all. The bundle does ship
  `certifi` (`/tmp/_MEI…/certifi/cacert.pem`), so *some* bundle was reachable.
* **This Deck's TLS is intercepted, and the interception CA lives only in the
  system store.** `sha256sum`-independent evidence:

  | bundle | certificates | contains `QiYou Game CA` |
  | --- | --- | --- |
  | `/etc/ssl/certs/ca-certificates.crt` → `/etc/ca-certificates/extracted/tls-ca-bundle.pem` | 121 | **yes** |
  | frozen `certifi/cacert.pem` | 120 | **no** |

  The first line of the system bundle is literally `# QiYou Game CA`.

The obvious fix — prefer `certifi`, because the frozen app certainly has it —
is therefore *silently wrong* on this device: the context loads 120 certificates
without complaint and then fails verification on every request, which looks
exactly like "the fix did not ship". That cost one full rebuild/deploy cycle to
discover.

### 9.2 The fix

`deckymod/nexus.py::_ssl_context()` builds **one** context and unions every
readable bundle into it with `load_verify_locations`, system store first (it is
the only one that can carry a local proxy CA), then `certifi.where()`, then the
frozen app's own copy:

```python
ctx = ssl.create_default_context()
for path in candidates:            # deduped, must exist
    ctx.load_verify_locations(cafile=path)
```

Verification is never disabled. If no bundle is readable we return the default
context and let it fail loudly, rather than trusting everything quietly.
`default_opener` now passes `HTTPSHandler(context=_ssl_context())` into
`build_opener`, and its docstring no longer says "FUTURE wiring".

### 9.3 Proven in the live process, not in a shell

After `utilities/enable_plugin` reloaded the backend (the plugin log shows a
fresh `Decky MOD Manager loaded (Stardew Valley / SMAPI (detect-only))` and the
loader logged `Loaded Decky MOD Manager (v0.1.0)`), the same call that had just
failed returned:

```json
{"ok": true, "total": 2549, "n": 10}
```

The whole objective was then driven through the real RPC route in that one
process:

| step | call | result |
| --- | --- | --- |
| search | `gh_search('stardew mod', 1)` | `ok`, 10 items, 2549 total |
| releases | `gh_releases('Esca-MMC','DestroyableBushes')` | `ok`, 5 releases, asset `DestroyableBushes.1.5.2.zip` / 44252 B |
| inspect | `gh_download(..., false, false)` | `phase: inspect`, mods still 27 |
| confirm | `gh_download(..., true, false)` | `phase: confirm`, mods still 27 |
| **download + install** | `gh_download(..., true, true)` | `ok`, mods **27 → 28** |
| uninstall | `uninstall('esca.destroyablebushes', true)` | `ok`, mods 28 → 27 |
| manage a pre-existing mod | `uninstall('Automate', false)` then `(…, true)` | `phase: confirm`, `previously_managed` path, mods 27 → 26 |
| rollback | `rollback(txn)` | `ok`, mods 26 → 27, `recovery().pending == []` |
| local ZIP import | `inspect` → `install` ×2 | `ok`, mods 27 → 28, `installed` shows the id |
| guard | `uninstall('../etc', false)` | `E_DUPLICATE` — still refused |

Disk afterwards is exactly the user's original state: 27 directories, 0
symlinks, 869 real files, no `.mm_deployed`, no `Mods_Core`, `Automate` present,
and every test artifact gone.

### 9.4 Still not proven

* The QAM panel has not been looked at since this build (`quickaccess_content_999`
  reports `vis: hidden`, `len: 0`). The agent cannot press `⋯`; this needs the
  user. Everything above is RPC truth, not visual truth.
* `dist/index.js` is unchanged by this round (`702acd65…`), so the frontend
  question is exactly as it was: correct bytes on disk, unverified on screen.
* The `--frozen` CA story is proven on *this* Deck, whose TLS is intercepted.
  A Deck without interception would have worked through `certifi` alone; the
  union makes both cases work, but only one of them was measured.

### 9.5 Deploy hygiene that this round made worth writing down

* `rebuild_final.sh` cleans stale `tests/*.py` as well as `deckymod/*.py`
  before unpacking, because `tar -xzf` overlays rather than replaces — a deleted
  test file otherwise resurrects and fails the run on the device only.
* Every deploy ends with a byte comparison of **all 20 python modules + 9
  registry JSONs + `dist/index.js`** between build tree and plugin directory.
  Final state: 30/30 `SAME`.
* `sed -i "s/$//"` is a trap on GNU sed (`` is a literal `r`, so it deletes
  every `r` in the file, including inside paths). Ship scripts as PowerShell
  `-replace "\`r\`n","\`n"` → base64 → `base64 -d`, and never trust a `CP=0`.


### 9.6 Round 21b — one more ownership bug, and why the fix is history-aware

Driving the objective end-to-end in the live process surfaced a second
ownership defect that no static check would have found:

1. Uninstall the pre-existing `Automate` → rollback → the folder comes back
   (correct), but `status().installed` now lists `Automate` (wrong). The user's
   own mod had been reclassified as one the plugin manages.
2. First fix: record `unmanaged=True` on `MOD_UNINSTALLED` and carry it onto
   `MOD_ROLLBACK_RESTORED`, skipping restores flagged that way. Correct for new
   writes — but the journal on the device already contained restore rows from
   before the fix, with no flag at all, so `installed` stayed dirty.
3. Real rule, now in `journal.installed()`: a restore re-establishes ownership
   **only if a prior `MOD_INSTALLED` row exists for that id**. The flag is a
   fast path; the `MOD_INSTALLED` history is the authority. Pre-fix rows are
   therefore harmless instead of permanently poisoning the table.

Verified live, on the dirty journal, after `utilities/enable_plugin`:

```
installed_dirty_journal : []          # was ["Automate"] before the fix
uninstall Automate      : ok, 27 -> 26
rollback                : ok, 26 -> 27, Automate back on disk
installed_after_rollback: []
```

The final end-to-end pass in the same live process then covered the whole
objective with the disk left exactly as found:

```
search      ok, 10 items          releases   ok, 5
inspect     ok, phase=inspect     confirm    ok, phase=confirm
install     ok, 27 -> 28          owned      ["Esca.DestroyableBushes"]
uninstall   ok, 28 -> 27          owned_after []
pending     []                    read_only  false
```

Disk after everything: 27 dirs, 0 symlinks, 869 real files, no `.mm_deployed`,
no `Mods_Core`, `Automate` present, no leftover `esca.destroyablebushes`, backup
manifest intact. Build tree vs deployed plugin: **22/22 python modules and
registry files identical, `dist/index.js` identical** (`702acd65…`).

Lesson worth keeping: "rollback worked" and "rollback told the truth" are two
different claims. The first one was green for a whole round while the second
was false.
