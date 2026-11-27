# Which installed mods have a newer version published

Round 82. `docs/NEXT_FEATURES.md` P2#8 recorded the gap: nothing in the plugin
answered *"is there a new version of the thing I installed"* — Round 67 only
asked that about **dependencies**.

## What it is not

It is not a download. A free Nexus account cannot download (403 by policy), so
`check_mod_updates` reports and stops: no archive is opened, no file is written,
the mod folder is never touched. The panel button says so in its own subtitle
("A free Nexus account cannot download, so this only tells you what is stale")
rather than letting a user infer that pressing it will update anything.

## Why it cannot simply say "up to date"

Three facts make a naive answer a lie:

1. **No Nexus id, no question.** The id comes from the mod's own `UpdateKeys`
   (`updatekeys.parse`). A mod that declares none has no known page; reporting
   it as current would be the same class of error Round 40 removed from the
   panel. `nexus_ids()` drops such mods instead of guessing by name.
2. **A version string is not a number.** `compare()` reuses
   `manifest._version_tuple`, the same helper the dependency check uses, so
   "1.2" and "1.2.0" compare equal and a string with no digits yields `()`.
   `()` reads as `unknown`, never as newer or older — the rule round 67 and
   round 50 (`/proc` unreadable) and round 48 (journal unreadable) all follow.
3. **The newest file is not the highest version string.** Authors re-upload old
   builds; the file a user would get is the one with the latest
   `uploaded_timestamp`, so `_newest_version()` sorts on that and prefers
   `mod_version` over `version` (the mod's version rather than the packaging
   revision).

## The four states

| state | meaning | what the user does |
| --- | --- | --- |
| `current` | installed ≥ published | nothing |
| `outdated` | installed < published | open the mod page and download it themselves |
| `unknown` | no readable version on one side | nothing — the plugin cannot tell |
| `error` | the API refused or the network failed | read the reason shown on the row |

`unknown` and `error` are kept apart on purpose: the first is a fact about the
manifest, the second is a fact about the network, and merging them would hide
which one to fix.

## The cap

`MAX_CHECKS = 25`, sorted by Nexus id so the same mods are checked every run.
One API call per **id**, not per mod — a framework and its content pack inside
one package legitimately share an id, and asking twice would waste a request
from a per-hour budget. When more than 25 ids exist, the result carries
`skipped` and a note explaining the cap instead of silently truncating.

## Cost of a wrong answer here

The dangerous direction is a false `current`: a user who believes a mod is up to
date stops looking. That is why an unparsable version is `unknown` rather than
`current`, and why a locally *newer* version (a downgrade the user chose, or a
beta channel) is `current` rather than `outdated` — suggesting an older file
would be worse than saying nothing.

## Tests

`tests/test_update_check.py`, 24 cases. The fixture is a fake opener, because
`nexus.mod_files` takes one — no network is reached and the API's exact response
shape is what the test controls.

One trap is pinned by the fixture itself: `nexus._raw` reads
`resp.status` and `resp.read()`, so the fake must return an **object**. An early
version returned a dict, which made `status` read as 0 and turned every mod into
`error` — a plausible-looking failure that this suite would have accepted if the
assertions had only checked `ok: True`.
