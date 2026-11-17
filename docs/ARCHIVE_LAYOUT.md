# Archive layout: where a mod starts inside the zip

A Stardew mod is only loaded if `manifest.json` sits at the **top level** of the
mod's directory. SMAPI does not search downwards. That single fact is what makes
archive layout a safety question rather than a cosmetic one: if the plugin
unpacks a mod one directory too deep, the install reports success and nothing
ever loads.

## The three layouts that exist in the wild

| Archive shape | What it is | What must happen |
| --- | --- | --- |
| `manifest.json`, `Foo.dll` at the root | a bare mod | install as `Mods/<UniqueID>/` |
| `Foo-1.0.0/manifest.json`, `Foo-1.0.0/Foo.dll` | one wrapper folder, the usual GitHub-release shape | strip the wrapper, install at the top |
| `Pack/v1/manifest.json` | one mod wrapped twice | strip **both**, install at the top |
| `Pack/ModA/manifest.json` + `Pack/ModB/manifest.json` | several mods in one zip | **refuse**: they are separate mods and need separate folders |
| `Mod/manifest.json` + `Mod/Pack/manifest.json` | a mod that bundles a content pack | **refuse**: the content pack has its own UniqueID and is its own mod |

The fourth and fifth rows are the ones Round 62 was about. Both used to install
"successfully".

## What went wrong

The old code answered "how deep does this mod start" twice, with two different
methods, and the two answers could disagree:

- `archive._strip_single_root()` stripped exactly **one** top-level directory,
  and only when every entry shared it.
- `manifest._match_member()` then matched the descriptor globs against the
  stripped names with `fnmatch`. Its `*` matches `/` as well as any other
  character, so `*/manifest.json` matched `Pack/ModA/manifest.json` — two levels
  below the directory that had been stripped.

With one wrapper this coincidence held. With two wrappers, or with several mods
in one archive, the manifest was found at a depth the extraction mapping did not
know about. The observable result:

``````
Mods/probe.a/
    ModA/manifest.json      <- SMAPI never looks here
    ModB/manifest.json      <- a second mod, silently dropped
``````

and then three follow-on failures, each of which made the other worse:

1. `status()` scans only the **top level** of `Mods/` for a manifest, so the
   folder it had just created was invisible to it (`MOD_COUNT 0`).
2. Because it was invisible, `uninstall()` could not find it either —
   `E_MOD_NOT_FOUND` on a directory the plugin itself had made.
3. The second mod was not merely misplaced; it was never reported at all.

## The fix: one member decides both facts

The root and the member mapping now come from the **same** manifest hit:

``````python
def locate_manifest(entries, relpaths):
    # for each file, is it a manifest (compared by suffix, NOT by fnmatch)?
    # base = everything above it; mapping = {stripped: original} under base
    ...
    return ManifestLocation(base=..., orig_name=..., mapping=..., others=[...])
``````

Consequences, in order of importance:

- **`base` and `mapping` cannot disagree.** They are produced by the same loop
  from the same member, so the depth a file is stripped to is by construction
  the directory the mod was found in.
- **`fnmatch` is gone from the matching path.** The suffix comparison is
  `low == relpath` or `low.endswith("/" + relpath)`, which has no cross-`/`
  wildcard to be surprised by. Re-introducing `fnmatch` now requires a
  deliberate decision; `tests/test_multi_mod_archive.py` asserts the import
  stays absent.
- **`others` is reported, not discarded.** When more than one manifest is
  found, the caller raises `E_MULTI_MOD_ARCHIVE` and the message names the mods
  (`this archive holds 2 mods (Pack/ModA, Pack/ModB); import them one at a
  time`) so the user can act on it.
- **Depth is no longer a limit.** Any wrapper depth resolves, because the
  manifest is what defines the root rather than a count of folders above it.

## Why this is a refusal and not a "pick the first one"

Picking a mod silently is what the old code did, and it is indistinguishable
from success in the UI. Splitting the archive is a decision the plugin cannot
make safely: it does not know which of the two mods the user wanted, and
installing the wrong one into a live save is not reversible by us. Refusing with
a message that names both is the only outcome that cannot lose work.

The same reasoning applies to a mod that bundles a content pack. A content pack
has its own `UniqueID` and `manifest.json`, so it *is* a second mod; it belongs
in its own directory where it can be enabled, disabled and removed on its own.

## Evidence

Device probe, six layouts, after the fix (`E_MULTI_MOD_ARCHIVE` cases show the
verbatim `detail`):

``````
one_wrapped           ok  dir=probe.thing  members=['Thing.dll','manifest.json']         strip=Thing-1.0.0
one_wrapped_twice     ok  dir=probe.deep   members=['Thing.dll','assets/tile.png','manifest.json']  strip=Pack/v1
two_in_wrapper        E_MULTI_MOD_ARCHIVE  this archive holds 2 mods (Pack/ModA, Pack/ModB); import them one at a time
two_at_root           E_MULTI_MOD_ARCHIVE  this archive holds 2 mods (ModA, ModB); import them one at a time
mod_with_content_pack E_MULTI_MOD_ARCHIVE  this archive holds 2 mods (Outer, Outer/Pack); import them one at a time
one_mod_plus_docs     ok  dir=probe.docmod  members=['README.txt','manifest.json']        strip=Docs
``````

The last row is the honest edge case: a folder that *contains* a `manifest.json`
is a mod by this definition, whatever the folder is called. That is a
consequence of defining a mod as "a directory with a manifest", and it is
recorded here rather than special-cased away.

Before the fix the same probe produced:

``````
two_mods_in_wrapper   ok=True  dir_name=probe.a  members=4  strip_single_root=Pack
                      member_sample ['ModA/ModA.dll','ModA/manifest.json','ModB/ModB.dll','ModB/manifest.json']
two_mods_at_root      ok=True  members=4     strip_single_root None
mod_plus_content_pack ok=True  members=4     strip_single_root Pack
``````

and installing one of those produced `Mods/probe.a/ModA/manifest.json`,
`MANIFEST_AT_EXPECTED_PLACE False`, `STATUS_MOD_COUNT 0`, and
`UNINSTALL_OK False E_MOD_NOT_FOUND`.

### Negative proof

`tests/test_multi_mod_archive.py` was run against a copy of the tree with the
old `_strip_single_root` + `fnmatch` matcher restored verbatim. Six of its
twelve tests fail on that copy — including both refusal tests and the
deep-wrapper test — and all twelve pass on the current code. A test that cannot
fail is not evidence, so this is recorded rather than assumed.

### The .7z path is a second implementation, and it was verified separately

`deckymod/file_drop.py` has two extractors: `inspect_mod()` for ZIP and
`_inspect_7z()` for .7z. They are written in parallel, not shared, so a fix in
one says nothing about the other. Round 62 changed the manifest matcher both of
them call, which meant the .7z path should have inherited the fix -- but "should"
is not evidence, and .7z is common on Nexus.

The device has `/usr/bin/7z`, so the probe built seven archives on the console
itself (`r63_sevenz_probe.py`) and ran them through the deployed plugin. All 41
checks pass:

``````
TWICE_IS_7Z            7z          TWICE_DIR            probe.twice
TWICE_INSTALL_PATH     Mods/probe.twice
TWICE_MANIFEST_TOP     manifest.json        TWICE_NO_V1     False
REFUSE_two_in_wrapper  E_MULTI_MOD_ARCHIVE  NAMES True  NOTHING_WRITTEN []
REFUSE_two_at_root     E_MULTI_MOD_ARCHIVE  NAMES True  NOTHING_WRITTEN []
REFUSE_mod_plus_pack   E_MULTI_MOD_ARCHIVE  NAMES True  NOTHING_WRITTEN []
NO_MANIFEST_CODE       E_MANIFEST_MISSING
INSTALL_OK True  INSTALL_UNIQUE_ID probe.twice  INSTALL_ENABLED True  INSTALL_NOT_PARKED False
ON_DISK ['probe.twice']  MANIFEST_AT_TOP True  NO_WRAPPER_DIR False  ASSET_KEPT True
STATUS_SEES_IT True  STATUS_NO_DUP []  UNINSTALL_OK True  MODS_EMPTY []
TXN_PRESENT True  ROLLBACK_OK True  RESTORED ['probe.twice']
JSON_SAFE True  SCRATCH_REMOVED True
PASS_COUNT 41 FAIL_COUNT 0
``````

So the deep-wrapper case (`Pack/v1/manifest.json`) lands at `Mods/probe.twice/`
with `manifest.json` at the top, the three multi-mod shapes are refused with
nothing written, and install/uninstall/rollback all still work on the .7z path.
No product code changed in Round 63; the point of the round was to stop
assuming.

Three ways this probe was wrong before it was right, all worth keeping:

1. **Read the wrong level of the envelope.** The install facts live under
   `data["mod"]`, not `data` and not `data["install"]`. Reading the wrong level
   gives `None` for every field, which looks exactly like the defect being
   hunted -- the first run reported five failures that were the probe's own.
2. **Asserted a key that does not exist.** `install()` returns
   `{dir, dir_name, enabled, packageId, parked, txn, uniqueId}`; there is no
   `format`. The first version asserted `format == "7z"` and got `None`. Worse,
   the "fix" `format or "7z"` would pass with `None` -- a vacuous assertion is
   more dangerous than none, because it reports success.
3. **A synthetic tree without the loader files.** With no `StardewModdingAPI`
   the engine correctly returns `E_LOADER_MISSING`; the probe had to create the
   same two files a real install has before `install` would proceed.

## What this does not claim

- **Not tested against a real community multi-mod archive.** The layouts are
  constructed. They follow real shapes (GitHub release wrapper folders, mods
  that ship content packs), but no such archive from Nexus or the SMAPI index
  has been run through the plugin.
- **The refusal is per-archive, not per-game.** Anything using
  `manifest_globs` gets it, because it lives in `_match_member`. The RimWorld
  path keeps its old non-refusing `_find_manifest`, since RimWorld's `xml_list`
  engine is still `planned` and never installs.
- **The .7z path was verified only with constructed archives too.** Round 63
  proved the second extractor inherits the fix, not that real archives behave.
- **Nothing was verified in Game Mode.** All of this is backend behaviour, seen
  through probes and unit tests; the panel itself was not opened.
