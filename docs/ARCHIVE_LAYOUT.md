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

## What this does not claim

- **Not tested against a real community multi-mod archive.** The layouts are
  constructed. They follow real shapes (GitHub release wrapper folders, mods
  that ship content packs), but no such archive from Nexus or the SMAPI index
  has been run through the plugin.
- **The refusal is per-archive, not per-game.** Anything using
  `manifest_globs` gets it, because it lives in `_match_member`. The RimWorld
  path keeps its old non-refusing `_find_manifest`, since RimWorld's `xml_list`
  engine is still `planned` and never installs.
- **Nothing was verified in Game Mode.** All of this is backend behaviour, seen
  through probes and unit tests; the panel itself was not opened.
