"""Round 62: an archive that ships several mods must be refused, not merged.

The bug this pins was silent. ``_match_member`` stripped ONE wrapper directory
off the archive and then matched descriptor globs against the stripped names
with ``fnmatch``, where ``*`` also matches ``/``. So ``*/manifest.json`` matched
``Pack/ModA/manifest.json`` -- two levels below the stripped root -- while the
extraction mapping only knew about ``Pack``. The mod was written to
``Mods/<id>/ModA/``: SMAPI only reads a manifest at a mod directory's top level,
so nothing loaded, and because ``status()`` scans that top level the plugin
could not see or uninstall the folder it had just created.

Two invariants are asserted here, and they are the reason this is worth a test
rather than a patch: the mod root and the member mapping must come from the SAME
member, and an archive with more than one mod must be refused.
"""
import io
import json
import os
import re
import unittest
import uuid
import zipfile

from deckymod import archive, file_drop, manifest
from deckymod.errors import ERRORS, ModError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = os.path.join(ROOT, ".decky-test-tmp")

# Passed explicitly rather than left to the active descriptor: tests/test_mvp.py
# pins DECKYMOD_GAME_ID=rimworld at import time, so "the active game" is not a
# stable thing to depend on inside discovery. This mirrors what a Stardew
# descriptor actually declares.
STARDEW_MOD_PACKAGE = {
    "parser": "json_map",
    "manifest_globs": ["manifest.json", "*/manifest.json"],
    "install_relpath_prefix": "Mods/",
    "json_dialect": "jsonc",
    "field_map": {
        "id": "UniqueID", "name": "Name", "version": "Version",
        "author": "Author", "entry_dll": "EntryDll",
        "minimum_api_version": "MinimumApiVersion",
        "dependencies": ["Dependencies", "ContentPackFor"],
    },
    "required_manifest_fields": ["UniqueID", "Name"],
}


def _manifest_json(uid, name="Thing", version="1.0.0", extra=None):
    doc = {
        "Name": name, "Author": "someone", "Version": version,
        "UniqueID": uid, "EntryDll": name + ".dll",
    }
    if extra:
        doc.update(extra)
    return json.dumps(doc)


class _Base(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.join(TMP, "r62_" + uuid.uuid4().hex[:8])
        os.makedirs(self.dir, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def _zip(self, name, entries):
        path = os.path.join(self.dir, name)
        with zipfile.ZipFile(path, "w") as zf:
            for member, data in entries:
                zf.writestr(member, data)
        return path

    def _inspect(self, name, entries):
        return file_drop.inspect_mod(self._zip(name, entries),
                                     mod_package=STARDEW_MOD_PACKAGE)


class TestSeveralModsInOneArchiveAreRefused(_Base):
    def _assert_refused(self, entries):
        with self.assertRaises(ModError) as ctx:
            self._inspect("multi.zip", entries)
        self.assertEqual(ctx.exception.code, "E_MULTI_MOD_ARCHIVE")
        # the message must name the mods: the user has to know what to split
        self.assertIn("mods", ctx.exception.detail)
        return ctx.exception.detail

    def test_two_mods_inside_one_wrapper(self):
        detail = self._assert_refused([
            ("Pack/ModA/manifest.json", _manifest_json("probe.a", "ModA")),
            ("Pack/ModA/ModA.dll", "MZ"),
            ("Pack/ModB/manifest.json", _manifest_json("probe.b", "ModB")),
            ("Pack/ModB/ModB.dll", "MZ"),
        ])
        self.assertIn("Pack/ModA", detail)
        self.assertIn("Pack/ModB", detail)

    def test_two_mods_at_the_archive_root(self):
        detail = self._assert_refused([
            ("ModA/manifest.json", _manifest_json("probe.a", "ModA")),
            ("ModA/ModA.dll", "MZ"),
            ("ModB/manifest.json", _manifest_json("probe.b", "ModB")),
            ("ModB/ModB.dll", "MZ"),
        ])
        self.assertIn("ModA", detail)

    def test_a_mod_that_bundles_a_content_pack(self):
        # A content pack is a mod in its own right (it has its own UniqueID and
        # its own manifest), so installing both as one folder is the same bug.
        self._assert_refused([
            ("Outer/manifest.json", _manifest_json("probe.outer", "Outer")),
            ("Outer/Outer.dll", "MZ"),
            ("Outer/Pack/manifest.json", json.dumps({
                "Name": "Pack", "Author": "someone", "Version": "1.0.0",
                "UniqueID": "probe.pack",
                "ContentPackFor": {"UniqueID": "Pathoschild.ContentPatcher"},
            })),
        ])

    def test_the_refusal_is_a_real_error_code_with_text(self):
        # A new code is only honest if it is wired everywhere a code must be.
        self.assertIn("E_MULTI_MOD_ARCHIVE", ERRORS)
        category, message, rollback = ERRORS["E_MULTI_MOD_ARCHIVE"]
        self.assertEqual(category, "import")
        self.assertFalse(rollback)
        self.assertTrue(message)


class TestOneModAlwaysLandsAtTheTop(_Base):
    def test_a_single_wrapper_is_stripped(self):
        info = self._inspect("one.zip", [
            ("Thing-1.0.0/manifest.json", _manifest_json("probe.thing")),
            ("Thing-1.0.0/Thing.dll", "MZ"),
        ])
        self.assertEqual(info["dir_name"], "probe.thing")
        self.assertEqual(info["install_relpath"], "Mods/probe.thing")
        self.assertIn("manifest.json", info["members"])
        self.assertEqual(info["manifest_stripped"], "manifest.json")

    def test_two_wrappers_are_stripped_both(self):
        # The old code stripped exactly one level, so this archive produced
        # Mods/<id>/v1/manifest.json -- also unloadable. Fixed by deriving the
        # root from the manifest member instead of counting wrappers.
        info = self._inspect("deep.zip", [
            ("Pack/v1/manifest.json", _manifest_json("probe.deep")),
            ("Pack/v1/Thing.dll", "MZ"),
            ("Pack/v1/assets/tile.png", "PNG"),
        ])
        self.assertEqual(info["dir_name"], "probe.deep")
        self.assertEqual(info["manifest_stripped"], "manifest.json")
        self.assertIn("assets/tile.png", info["members"])
        self.assertNotIn("v1/manifest.json", info["members"])
        self.assertEqual(info["strip_single_root"], "Pack/v1")

    def test_the_manifest_sits_at_the_extraction_root(self):
        # The property that actually matters: whatever the wrapper depth, the
        # manifest is written at the top of Mods/<dir>/.
        for entries in (
            # The name must match the DLL that ships, because the manifest's
            # EntryDll comes from it (round 64).
            [("A/manifest.json", _manifest_json("probe.one", "One")), ("A/One.dll", "MZ")],
            [("A/B/manifest.json", _manifest_json("probe.two", "Two")), ("A/B/Two.dll", "MZ")],
            [("A/B/C/manifest.json", _manifest_json("probe.three", "Three")),
             ("A/B/C/Three.dll", "MZ")],
            [("manifest.json", _manifest_json("probe.bare", "Bare")), ("Bare.dll", "MZ")],
        ):
            info = self._inspect("layout.zip", entries)
            members = info["members"]
            self.assertIn("manifest.json", members, entries[0][0])
            # nothing may sit "above" the manifest in the written tree
            above = [m for m in members
                     if m.count("/") and m.split("/")[0] in ("A", "B", "C")]
            self.assertEqual(above, [],
                             "a wrapper directory survived extraction: %r" % sorted(members))


class TestTheTwoFactsComeFromOneMember(unittest.TestCase):
    """Structural, because behaviour tests passed on every buggy release.

    Rounds 57, 58 and 59 each shipped because two places computed the same path
    and drifted. Here the equivalent risk is `root` vs `mapping`: if they are
    derived separately they can disagree, and the symptom is a silent mis-file.
    """

    def test_locate_manifest_returns_the_root_it_mapped_from(self):
        loc = archive.locate_manifest(
            ["Pack/ModA/manifest.json", "Pack/ModA/ModA.dll"],
            archive._relpaths(["manifest.json", "*/manifest.json"]),
        )
        self.assertEqual(loc.base, "Pack/ModA")
        self.assertEqual(loc.orig_name, "Pack/ModA/manifest.json")
        self.assertEqual(loc.mapping["manifest.json"], "Pack/ModA/manifest.json")
        self.assertEqual(loc.mapping["ModA.dll"], "Pack/ModA/ModA.dll")

    def test_every_mapping_key_is_relative_to_the_base(self):
        entries = ["W/x/manifest.json", "W/x/a/b.dll", "Other/manifest.json"]
        loc = archive.locate_manifest(
            entries, archive._relpaths(["manifest.json", "*/manifest.json"]))
        for stripped, orig in loc.mapping.items():
            self.assertTrue(orig.startswith(loc.base + "/"),
                            "%r is not under %r" % (orig, loc.base))
            self.assertNotIn(loc.base + "/", stripped)

    def test_the_other_mods_are_reported_not_dropped(self):
        loc = archive.locate_manifest(
            ["P/A/manifest.json", "P/B/manifest.json"],
            archive._relpaths(["manifest.json", "*/manifest.json"]))
        self.assertEqual(loc.base, "P/A")
        self.assertEqual(loc.others, ["P/B"])

    def test_globs_lose_their_leading_star_slash(self):
        rels = archive._relpaths(["*/manifest.json", "manifest.json"])
        self.assertEqual(sorted(rels), ["manifest.json"])

    def test_the_matcher_does_not_use_fnmatch_on_archive_paths(self):
        # fnmatch's `*` matches `/`, which is precisely how `*/manifest.json`
        # reached two levels down. The import is gone; keep it gone.
        path = os.path.join(ROOT, "deckymod", "manifest.py")
        with io.open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("fnmatch.fnmatch(", src)
        self.assertNotIn("import fnmatch", src)


if __name__ == "__main__":
    unittest.main()
