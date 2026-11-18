# Downloading a mod's dependencies

Round 38 answers a user question: *"还有以及MOD下载的过程，能否把依赖项一起下载"* —
when a mod is downloaded, can its required dependencies come along?

The answer is yes, with one rule that turned out to be the whole problem:
**a downloaded file is only a dependency if the manifest inside it says so.**

## Why the obvious implementation is wrong

Two facts, both measured on the Deck rather than assumed:

1. **A monorepo publishes one release per mod.** `zombifier/My_Stardew_Mods`
   has four releases and four assets:

   | tag | asset | id |
   |---|---|---|
   | `custom-builders/0.0.2` | `CustomBuilders.0.0.2.zip` | 242074360 |
   | `custom-builders/0.0.1` | `CustomBuilders.0.0.1.zip` | 241151493 |
   | `furniture-machine/0.0.2` | `FurnitureMachine.0.0.2.zip` | 212285549 |
   | `furniture-machine/0.0.1` | `FurnitureMachine.0.0.1.zip` | 211996093 |

   So "take the first usable `.zip` in the repo the index named" is a guess,
   and it is frequently wrong. Both `selph.ExtraMachineConfig` and
   `selph.FurnitureMachine` resolve to this same repo.

2. **The public index covers less than it appears to.** Of the four
   dependencies actually missing on the test device, two are not in the index
   with any usable repository at all.

## The rule

Resolution is two stages, and the second stage is not optional:

1. Ask `smapi.io/api/v2.2/mods` which GitHub repo (if any) publishes the id.
2. Download candidate assets, open each one, and accept it **only** when
   `manifest.json` declares the same `UniqueID`. Anything else is deleted and
   the next candidate is tried, within a fixed budget
   (`MAX_CANDIDATES_PER_DEP = 4`, `MAX_DEPS = 20`).

Ordering candidates by name similarity is only a hint. It never authorises an
install.

## What a device run actually did

Plan phase (`allow_install=False`) — inert, inbox unchanged:

```
MISSING 4
OK True  PHASE inspect  TOTAL 4 FETCHABLE 2  INBOX_UNCHANGED True
  Xiddav.tilesheet        resolvable=False reason=no_repo_in_index
  hxw.tilesheets          resolvable=False reason=no_repo_in_index
  selph.ExtraMachineConfig resolvable=True  repo=zombifier/My_Stardew_Mods candidates=4
      cand 242074360 CustomBuilders.0.0.2.zip 31511
  selph.FurnitureMachine  resolvable=True  repo=zombifier/My_Stardew_Mods candidates=4
      cand 212285549 FurnitureMachine.0.0.2.zip 34005
```

Note the first candidate for `ExtraMachineConfig` is `CustomBuilders` — a
different mod. Install phase, after verification:

```
MODS_BEFORE 29
PHASE installed  INSTALLED 1  ATTEMPTED 4
  Xiddav.tilesheet         installed=False reason=no_repo_in_index
  hxw.tilesheets           installed=False reason=no_repo_in_index
  selph.ExtraMachineConfig installed=False reason=candidate_failed
      detail=asset declares 'selph.FurnitureMachine', expected 'selph.ExtraMachineConfig'
  selph.FurnitureMachine   installed=True  asset=FurnitureMachine.0.0.2.zip
MODS_AFTER 30  ADDED ['selph.furnituremachine']
```

The wrong mod was refused by name; the right one landed. A follow-up query of
the repo with `per_page=100` confirmed the index claim is simply wrong —
there is no `ExtraMachineConfig` asset in that repository, so refusing was the
only honest outcome.

## The bug that run found

The first implementation stopped at the first dependency it could not install.
On the device that meant `ExtraMachineConfig` failing **prevented
`FurnitureMachine` from ever being attempted**, even though it was
downloadable. Dependencies are independent, so the loop now continues and
reports each failure separately. `tests/test_deps.py::test_a_refused_install_does_not_block_the_other_dependencies`
pins this; it failed against the old code (`attempted == 1`) and passes now
(`attempted == 2`).

## Surface

* New RPC `fetch_dependencies(allow_install, after_confirm)` — the 17th. Same
  TRI-STATE contract as every other download: plan / confirm / execute, and
  phase 3 returns the engine's own `E_EXTERNAL_MANAGER` verbatim.
* New module `deckymod/deps.py`. It reuses `deckymod/download.py` for all HTTP
  (pinned hosts, capped reads, the shared error codes) — it opens no socket of
  its own, which `test_it_does_not_open_its_own_sockets` asserts.
* `download.default_opener` gained an optional `body` argument, because the
  index endpoint answers `405` to `GET`. Default `None` leaves every existing
  call unchanged.
* UI: two ButtonItems in the download section (`DEPS_BTN` / `DEPS_INSTALL_BTN`)
  and a per-dependency report. 21 new i18n keys, en/zh parity 357.
* No new error codes: `errors.py` is still 50. The resolver's failures are
  reported as a per-row `reason` inside a successful envelope, because "four
  dependencies were checked and two could not be fetched" is information, not
  an error.

## Bounded by design

| limit | value | why |
|---|---|---|
| dependencies per call | 20 | a download that fans out without bound is a denial of service on yourself |
| candidates per dependency | 4 | enough for versioned assets, small enough to stay inside the GitHub rate limit |
| install rounds | 3 | a dependency may itself need others; three rounds covers that, and a lower number stops a cycle in the index from spinning forever |
| index response | 4 MiB | refused rather than buffered |
| one download | 256 MiB | the existing shared cap |

The round cap is not silent. Every row carries the `round` it was resolved in,
the result carries `rounds`, `max_rounds` and `still_missing`, and `note`
distinguishes the two different reasons a dependency can survive: the loop ran
out of rounds (there is more to fetch) versus nothing on the index offers it
(there is not). Reporting both with one sentence would be a lie in one of the
two directions.

## Round 41: .7z is a fetchable archive too

The engine has installed `.7z` end-to-end since round 63 (41/41 device checks:
inspect, install, status, uninstall, rollback all worked on a real `.7z` built
with the device's own `7z`). But `deps.candidate_assets` filtered release assets
on `.zip` only. A dependency published solely as `.7z` was therefore reported
`no_zip_asset` ("该仓库没有发布 zip") and never fetched — a capability gap
dressed up as a content policy, and a contradiction of goal item 3, which asks
for ".zip and .7z".

The fix is deliberately small: `candidate_assets` now accepts `.zip` and `.7z`
suffixes with their known content types (`.7z` is often mislabelled
`application/octet-stream`, which is accepted too). Nothing changed in the
acceptance decision: a candidate is still accepted only when
`verify_candidate` opens its archive and reads a manifest whose `UniqueID`
equals the requested id. Content type is a first-pass filter, not evidence —
so widening it cannot install a wrong mod. `.rar`/`.exe` are still refused, as
the engine cannot read them. The `no_zip_asset` wire key and the
`DEPS_R_NO_ZIP` i18n key are unchanged for compatibility; only the English and
Chinese wording now says "zip or 7z" so the panel stops naming a capability
the resolver does not have.

Six offline tests in `tests/test_deps_7z.py` cover: a repo with only a `.7z`
yields a candidate; `.zip` and `.7z` are both usable; an octet-stream-labelled
`.7z` still works; `.rar`/`.exe` remain refused; the id-name ordering hint
still prefers the matching `.7z`; and the reason wording matches the capability.
Reverting the filter to `.zip`-only fails the three `.7z` cases while the
ordinary deps tests still pass. 850 tests OK, compileall 0, seven validators 0.
Deck was unreachable this round, so no device claim is made here — the change
is offline-verified and reaches the bundle on the next connected build.

## What is proven, and what is not

Proven on the device: the plan phase writes nothing; the wrong-mod candidate is
refused with the declaring vs expected ids in the detail; the correct
dependency installs and its manifest is on disk; a failed dependency no longer
blocks the others; nothing else in `Mods/` changed. Also proven on the device
after round 45: the confirm phase writes nothing while promising the bounded
depth, and the inspect phase reports the same three dependencies with
`fetchable=1`.

Not proven: that a game session actually loads the freshly installed
dependency (that needs a game launch after the install), and that the resolver
behaves well for a mod whose dependencies form a chain deeper than three —
the loop is depth-aware but capped, and a chain longer than `MAX_ROUNDS`
reports its remainder through `still_missing` instead of pretending to be
finished.
