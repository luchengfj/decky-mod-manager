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
| `Pack/ModA/manifest.json` + `Pack/ModB/manifest.json` | several mods in one zip | **ask which one**, then install just that one (Round 84; before that: refuse) |
| `Mod/manifest.json` + `Mod/Pack/manifest.json` | a mod that bundles a content pack | **ask which one**, then install just that one (Round 84; before that: refuse) |

The fourth and fifth rows are the ones Round 62 was about. Both used to install
"successfully". Round 84 changed what happens to them: refusing was correct but
left the user with no next step, because Game Mode has no file manager to
unpack the archive in (see `## Round 84: the refusal gets a next step` below).

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

## Round 84: the refusal gets a next step

`E_MULTI_MOD_ARCHIVE` was a dead end. It named the mods, which is more than most
errors do, and then stopped: the only way to install any of them was to unpack
the archive by hand and feed the plugin one folder at a time. Game Mode has no
file manager, so on the device the user could not do that at all. The plugin was
asking its user to perform a task the plugin does not provide.

What happens now, in order:

1. `install()` still raises `E_MULTI_MOD_ARCHIVE`. Nothing about the guard
   changed -- an archive with several mods still cannot be installed as one.
2. The panel catches that specific code and calls the new `archive_mods` RPC,
   which returns every mod root in the archive with its name, version, manifest
   path and file count (`file_drop.list_mod_roots`).
3. The user picks one from a list. The panel then re-runs `inspect` **with that
   root**, and the normal preview / confirm / install flow continues with only
   that mod's members.

The root travels as a new `member_root` parameter through four layers, and each
one has to forward it or the feature silently degrades to the old refusal:

| Layer | What it does with `member_root` |
| --- | --- |
| `main.py` `install` / `inspect` / `archive_mods` | forwards only to engines that declare `_set_enabled_inner` (the file_drop engine). `engine.py` and `root_merge.py` take no such parameter, so passing it blindly would turn a refusal into `E_UNKNOWN` TypeError. |
| `deckymod/smapi.py` `inspect` / `install` / `_install_inner` | forwards to `file_drop` |
| `deckymod/file_drop.py` `inspect_mod` / `list_mod_roots` | `parser.find_member(names, only_root=...)` |
| `deckymod/manifest.py` `_match_member` | re-runs `locate_manifest` on the subtree, re-anchors `orig_name` and `mapping` to that root |

`extract_to` needed no change: it already accepted `member_override`, which is
how the FOMOD flow installs a chosen subset. Selecting a root is the same shape.

Three things this round had to get right, each caught by a test that fails
without the fix:

- **The picker must not loop.** The first wiring forwarded `member_root` to
  `install` but not to `inspect`, so choosing a root re-raised
  `E_MULTI_MOD_ARCHIVE` and put the user back in front of the picker they had
  just answered. `tests/test_multi_mod.py::test_the_inspect_rpc_forwards_the_chosen_root`
  pins the RPC layer specifically, because the engine-layer tests stayed green
  while the RPC dropped the argument.
- **The preview must not lie.** `install_relpath` was briefly changed to include
  the archive root (`Mods/Pack/ModA/a.mod`). The bytes do not land there: the
  destination directory comes from the manifest's `UniqueID`, not from the
  archive layout, so the real path is `Mods/a.mod`. A preview that names a
  different path than the install writes is the exact defect class Round 59/60
  were about.
- **`""` is a real choice.** An archive whose mods sit at the root has an empty
  root string, so the parameter is `None` for "not chosen" and `""` for "the
  root itself". Conflating them makes root-level multi-mod archives
  unselectable.

Not proven:

- **`.7z` + `member_root` has no test.** `_inspect_7z` and `list_mod_roots`'s 7z
  branch mirror the ZIP branch line for line, but this box has no `7z` binary,
  so `tests/test_multi_mod.py::test_7z_listing_with_the_real_binary` skips.
  Reading code is not the same as running it; this needs the device.
- **No real community archive was used.** Same caveat as Round 63: the shapes
  are constructed from real release layouts, not taken from Nexus.
- **The picker was never seen on a screen.** It is a `showListModal` with rows
  built from `ArchiveModsData`; the backend and the RPC are tested, the pixels
  are not.
