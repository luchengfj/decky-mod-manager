# EntryDll: the file SMAPI loads

Steam Deck Game Mode plugin for Stardew Valley. This page records one defect found
on the device and what changed, in the same shape as `PATH_DECISION.md` and
`ARCHIVE_LAYOUT.md`.

## What SMAPI actually does

A Stardew mod's `manifest.json` may declare:

```json
{ "Name": "Automate", "UniqueID": "Pathoschild.Automate",
  "Version": "2.6.1", "EntryDll": "Automate.dll" }
```

SMAPI reads `EntryDll` and opens **that file, relative to the mod directory**. If
it is not there, the mod does not load. Content packs have no `EntryDll` at all --
that is normal and must keep working.

## What the plugin did before

`JsonMapParser` parsed `EntryDll` into `ParsedManifest.entry_dll`, and then
nothing compared it to the archive. `parse_manifest()` -- the only function that
exposed it -- had **no callers**, so the value did not even reach the frontend
(`src/types.ts` had `entryDll?: string | null` with nobody filling it).

A probe on the device, before the fix, over five archives:

| archive | inspect | installed? | panel says |
|---|---|---|---|
| manifest names `ProbeMod.dll`, archive ships `Other.dll` | ok | **yes** | installed + enabled |
| manifest names `../../etc/passwd` | ok | **yes** | installed + enabled |
| `EntryDll` in a subdirectory, present | ok | yes | installed + enabled |
| content pack, no `EntryDll` | ok | yes | installed + enabled |

```
MISSING_DLL_INSTALL_OK True
MISSING_DLL_LISTED_AS_INSTALLED True
MISSING_DLL_NO_PARSE_ERROR None
ROW {"dir":"probe.entry","uniqueId":"probe.entry","version":"1.0.0","parse_error":null}
EVIL_DLL_REFUSED True   # want False: a traversal path was accepted
```

So a package that could never load was imported, listed, and reported as working.
That is the failure mode this project keeps coming back to: the panel claiming
something it never verified.

## What changed

`deckymod/manifest.py` gained one function, and `deckymod/file_drop.py` calls it on
both reader paths (ZIP and `.7z`):

```python
def check_entry_dll(entry_dll, members) -> None:
    if entry_dll is None:
        return                     # content packs legitimately have none
    rel = str(entry_dll).strip().replace("\\", "/")
    if not rel:
        return
    if rel.startswith("/") or (len(rel) > 1 and rel[1] == ":") or ".." in rel.split("/"):
        raise ModError("E_MANIFEST_UNSAFE",
                       detail="EntryDll %r points outside the mod folder" % entry_dll)
    want = rel.lower()
    have = {str(k).replace("\\", "/").lower() for k in (members or {})}
    if want in have:
        return
    squashed = "/".join(p for p in want.split("/") if p not in ("", "."))
    if squashed in have:
        return
    raise ModError("E_MANIFEST_INVALID",
                   detail="EntryDll %r is not in this archive; the mod would be "
                          "installed but fail to load" % entry_dll)
```

Four decisions worth naming:

1. **Only a *declared* EntryDll is checked.** No `EntryDll` means a content pack,
   and content packs are the majority of what a Stardew mod list contains.
2. **Relative to the mod root**, which is the manifest's own directory -- that is
   where SMAPI resolves it from, so matching anywhere in the archive would be
   wrong in the permissive direction.
3. **Traversal is refused, not normalised.** `/etc/passwd`, `C:/...`,
   `../../x` and `..\\..\\x` all raise `E_MANIFEST_UNSAFE`. Normalising would
   silently rewrite a manifest the author wrote, and the mod would still not load.
4. **Case-insensitive**, because the same archive is offered to Windows and Linux
   users and `EntryDll` casing varies in the wild.

No new error code: `E_MANIFEST_INVALID` and `E_MANIFEST_UNSAFE` already existed,
so `errors.py` stays at 52 and the four places that assert that count did
not move.

## The fixtures were wrong, not the check

Adding the check turned 12 tests red at once. Every one of them was a
fixture that declared an `EntryDll` and then shipped a differently named file (or
nothing). A real mod cannot be shaped like that, so the fixtures were describing
impossible packages. They were corrected to ship the DLL they declare:

| file | before | after |
|---|---|---|
| `tests/test_sevenzip_engine.py` | manifest named `AutoBush.dll`, zip had only a manifest | ships `AutoBush.dll` |
| `tests/test_stardew.py` `_make_stardew_zip` | manifest named `Visible.dll`, zip had only a manifest | ships `Visible/Visible.dll` |
| `tests/test_stardew.py` `TestLoaderLogInStatus._install` | manifest named `<uid>.dll`, zip had `x.dll` | ships the declared name |
| `tests/test_multi_mod_archive.py` | four layouts named `Thing.dll` but shipped `One/Two/Three/Bare.dll` | name matches the DLL |

This is worth stating plainly: the check was right and the tests encoded a
package that could not exist. Rescuing the tests by weakening the check would
have preserved the bug.

## Evidence

`tests/test_entry_dll.py`, 14 cases:

* `TestADeclaredButAbsentDllIsRefused` -- absent DLL, DLL present only in a
  subdirectory, a declared subdirectory path that *is* present (accepted), and the
  message naming the consequence (`"fail to load"`).
* `TestAnEntryDllMayNotEscapeTheModFolder` -- `..` traversal, absolute POSIX path,
  absolute Windows drive, traversal in the middle, and backslash traversal.
* `TestTheNegativeHalfStillWorks` -- content pack without `EntryDll`, mod that
  ships its DLL, and the wrapper still stripped.
* `TestTheCheckIsCalledOnBothPaths` -- exactly two call sites in `file_drop.py`,
  the helper defined in `manifest.py` and not duplicated into `file_drop.py`.

Negative proof (`r64_negative_proof.py`): delete both call sites from a copy of
the tree and re-run the module.

```
CALL_SITES_BEFORE 2
CALL_SITES_AFTER 0
RETURNCODE 1
FAILURES 9
NEGATIVE_PROOF_FIRED True
```

Nine of fourteen fail without the fix, including `test_zip_and_7z_both_call_it`,
so the structural assertion is load-bearing rather than decorative.

On the device, against the **deployed** plugin (synthetic tree in `/tmp`, the
real `Mods/` untouched):

```
HAS_CHECK True
A_CODE 'E_MANIFEST_INVALID'      A_SAYS_DLL True          B_MODS_EMPTY True
C_CODE 'E_MANIFEST_UNSAFE'       C_SAYS_OUTSIDE True      C_MODS_EMPTY True
D_ENTRY_DLL 'Good.dll'           D_OK True
E_INSTALL_OK True                E_MODS ['probe.good']    E_STATUS_SEES True
E_NO_PARSE_ERROR True            F_OK True                F_ENTRY_DLL None
G_JSON_SAFE True                 SCRATCH_REMOVED True
```

Ten of thirteen booleans are true; the three false ones are the refusals the fix
exists to produce (`A_INSPECT_OK`, `B_INSTALL_OK`). Nothing was written to `Mods/`
in either refusal case.

Full local suite: `Ran 756 tests / OK (skipped=14)`, `compileall` exit 0, the
seven persistent validators exit 0.

## What this does not claim

* **Not tested against a real broken community mod.** The archives are
  constructed. It is likely the check also rejects some real packages whose
  manifests are simply sloppy; that is the intended trade (refuse at import beats
  a silent non-loading mod), but it has not been measured.
* **`EntryDll` is now on the wire, not yet rendered.** `inspect()` returns
  `entryDll`, and the panel does not display it. Showing it next to the version
  would make a bad package diagnosable before import.
* **RimWorld's `xml_list` engine is unaffected.** It has no `EntryDll` concept and
  that game remains `planned`; only the `json_map` family is covered, which today
  means Stardew Valley.
* **The panel has still never been opened in Game Mode by a human.** Every layout
  statement in this repository comes from CDP DOM text, and this round adds no
  layout change.
