# Goal record — download source change (Nexus → GitHub Releases + direct URL)

This file exists because the round-30 goal statement requires the change to be
**recorded in the goal record**, not only buried in a roadmap section:

> 5.【技术债清理，硬判据】… 在 goal 记录中补一条变更说明：下载源由 Nexus 改为
> GitHub Releases + 直连 URL，依据 m10068 指令，Nexus 403 为免费账户硬限制
> （免费账户无直连下载权，必须经网站授权签发 nxm:// 短时效链接，不是限流问题）。

---

> **Round 88 补记（2026-11-28）**：本文件记录的第 30 轮「Nexus → GitHub Releases +
> 直连 URL」变更，在第 39 轮被部分撤销（为了 metadata 恢复了 4 个 key RPC），
> 现在**第 88 轮把它重新且更彻底地执行了一遍** —— 恢复的 4 个 key RPC 连同
> `check_mod_updates` 一起删除，`deckymod/credentials.py` 再次删除。
> 下面这段「Nexus 下载路线不得重新引入」的约束**依然成立**，而且现在代码结构与它一致
> （第 39–88 轮之间那段时间，代码是与本约束矛盾的：它带着 key 和 API 客户端）。
> 唯一新增的例外是三个**不需要 key、只构造网站 URL** 的打开器，它们不下载任何东西。

## The record

**Change:** the plugin's download source moved from the Nexus Mods API to
**GitHub Releases (primary) + direct HTTPS URL (fallback)**.

**Authority:** user instruction `m10068` — *"不走Nexus，走其他地方实现下载MOD"* —
and the plan approved in the same round.

**Why Nexus could not be kept:** HTTP **403** from
`api.nexusmods.com/v1/games/{domain}/mods/{id}/files/{file_id}/download_link.json`
for a **free** Nexus account. This is an **account-policy restriction, not
rate-limiting**:

- a rate limit would answer **429** with `Retry-After`, or eventually clear;
- this answers **403** on every attempt, immediately, with a valid 96-character
  personal API key (verified on-device: `RAW_STATUS 200` for the key itself, so
  the credential was accepted — the *download-link endpoint* is what refuses);
- the paid path is a website-issued, short-lived `nxm://` authorisation link, and
  that flow is exactly what free accounts are not granted.

So the 403 is **not fixable by retrying, backing off, or adding a token** — only
by upgrading to a Premium account, which is out of scope.

**What replaced it:**

| source | mechanism | verified on device |
|---|---|---|
| GitHub Releases | `GET /repos/{o}/{r}/releases/assets/{id}` with `Accept: application/octet-stream` → **302** → signed `release-assets.githubusercontent.com` URL → 200 | yes — `gh_search` total 2553, `gh_releases` 5 assets, `gh_download` inspect phase `verified=["size"]`, 44252 B |
| direct HTTPS URL | user-supplied URL, https-only, no userinfo, non-443 ports rejected, private-IP *literals* rejected, written only into the inbox | yes — `http://` → `E_PATH_INVALID`, `https://u:p@…` → `E_PATH_INVALID`, `https://127.0.0.1/…` → `E_PATH_ESCAPE` |

**What was removed with it** (round 29 refactor):

- `deckymod/nexus.py` → replaced by `deckymod/download.py` (neutral shared
  network layer; no API host, no credential parameter, `NX_*` → `DL_*`).
- `deckymod/credentials.py` → **deleted**; the six credential/list/download-link
  RPCs (`api_key_status`, `set_api_key`, `delete_api_key`, `nexus_validate`,
  `list_mod_files`, `nexus_fetch`) were retired and replaced by four
  (`gh_search`, `gh_releases`, `gh_download`, `download_url`).
- device residue `/home/deck/homebrew/data/decky-mod-manager/data/nexus_api_key`
  (96 B, `-rw-------`) → **deleted on the Deck**, verified `DELETE_OK`.

**Constraint that must not be relaxed:** the Nexus download route is **not to be
reintroduced**. Free-account 403 is account policy; retrying it cannot work.

---

## Verification of "no Nexus reference remains"

Run from `C:\ai\SD`:

```
grep -ric 'nexus' deckymod\*.py main.py src\*.ts src\*.tsx src\**\*.tsx src\i18n\*.json
→ (no matches)
```

On-device, after the round-30 build and deploy:

```
NEXUS_IN_DIST=0     # grep -ic nexus dist/index.js
NEXUS_FILES=0       # grep -ril nexus main.py py_modules/deckymod/
```

The only surviving occurrences of the string in the repository are:

1. `docs/NEXUS_ROADMAP.md` — a **historical** roadmap. Per the project's
   standing discipline, historical snapshots are never back-filled; §6.6 is an
   additive round-29 section that *records* the retirement rather than erasing
   the history that produced it.
2. `Nexus:NNNNN` inside **real SMAPI `manifest.json` data** on the Deck (for
   example `"UpdateKeys": ["Nexus:14293", "Github:slothsoft/stardew-informant"]`).
   That is user data written by mod authors, not a plugin reference, and it is
   deliberately preserved by the refactor's scrub guard.

---

## Status discipline

- No `CLOSED` added; `[x]` count stays 0; §B.4 unchecked.
- V1 remains the only CLOSED item; V2–V20 / F1–F3 stay OPEN.
- The original RimWorld G3 (AppID 294100) stays OPEN / NOT SHIPPABLE.
