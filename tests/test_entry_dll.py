"""Round 64: an EntryDll that is not in the archive must be refused.

SMAPI loads a mod by reading ``EntryDll`` from its manifest and opening that file
relative to the mod directory. If the file is not there the mod installs, appears
in the panel as installed-and-enabled, and never loads. The panel then reports a
broken mod as a working one, which is worse than refusing the import.

Two things are pinned here:

* a declared EntryDll that the archive does not contain is refused at inspect
  time, before anything is written;
* a declared EntryDll that escapes the mod directory (``..``, an absolute path,
  a Windows drive) is refused as unsafe rather than normalised, because a mod
  folder must not be able to name a file outside itself.

and the negative half: a mod with no EntryDll at all (content packs) and a mod
whose EntryDll IS present both still work. A check that rejects everything would
pass only the first two assertions and break every real content pack.
"""
import io
import json
import os
import unittest
import uuid
import zipfile

from deckymod import file_drop, manifest
from deckymod.errors import ModError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = os.path.join(ROOT, ".decky-test-tmp")

# Mirrors what registry/games/stardew.json declares. Passed explicitly because
# tests/test_mvp.py pins DECKYMOD_GAME_ID=rimworld at import time, so the
# "active game" is not stable under discovery (round 62 lesson).
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


def _manifest_json(uid="probe.mod", name="Probe", entry_dll=None):
    doc = {"Name": name, "Author": "someone", "Version": "1.0.0", "UniqueID": uid}
    if entry_dll is not None:
        doc["EntryDll"] = entry_dll
    return json.dumps(doc)


class _Base(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.join(TMP, "r64_" + uuid.uuid4().hex[:8])
        os.makedirs(self.dir, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def _inspect(self, entries, name="mod.zip"):
        path = os.path.join(self.dir, name)
        with zipfile.ZipFile(path, "w") as zf:
            for member, data in entries:
                zf.writestr(member, data)
        return file_drop.inspect_mod(path, mod_package=STARDEW_MOD_PACKAGE)


class TestADeclaredButAbsentDllIsRefused(_Base):
    def test_the_archive_does_not_contain_the_dll(self):
        with self.assertRaises(ModError) as ctx:
            self._inspect([
                ("manifest.json", _manifest_json(entry_dll="ProbeMod.dll")),
                ("Other.dll", b"MZ"),
            ])
        self.assertEqual(ctx.exception.code, "E_MANIFEST_INVALID")
        self.assertIn("ProbeMod.dll", ctx.exception.detail)

    def test_the_dll_sits_in_a_subdirectory_but_not_at_the_root(self):
        # SMAPI resolves EntryDll against the mod directory, not recursively.
        with self.assertRaises(ModError) as ctx:
            self._inspect([
                ("manifest.json", _manifest_json(entry_dll="ProbeMod.dll")),
                ("lib/ProbeMod.dll", b"MZ"),
            ])
        self.assertEqual(ctx.exception.code, "E_MANIFEST_INVALID")

    def test_an_entry_dll_naming_a_subdirectory_is_accepted_when_present(self):
        info = self._inspect([
            ("manifest.json", _manifest_json(entry_dll="bin/ProbeMod.dll")),
            ("bin/ProbeMod.dll", b"MZ"),
        ])
        self.assertEqual(info["dir_name"], "probe.mod")
        self.assertEqual(info["entryDll"], "bin/ProbeMod.dll")

    def test_the_message_says_what_the_consequence_was(self):
        with self.assertRaises(ModError) as ctx:
            self._inspect([
                ("manifest.json", _manifest_json(entry_dll="Missing.dll")),
            ])
        self.assertIn("fail to load", ctx.exception.detail)


class TestAnEntryDllMayNotEscapeTheModFolder(_Base):
    def _assert_unsafe(self, entry_dll):
        with self.assertRaises(ModError) as ctx:
            self._inspect([
                ("manifest.json", _manifest_json(entry_dll=entry_dll)),
                ("ProbeMod.dll", b"MZ"),
            ])
        self.assertEqual(ctx.exception.code, "E_MANIFEST_UNSAFE", entry_dll)
        self.assertIn("outside the mod folder", ctx.exception.detail)

    def test_parent_traversal(self):
        self._assert_unsafe("../../etc/passwd")

    def test_absolute_posix_path(self):
        self._assert_unsafe("/etc/passwd")

    def test_absolute_windows_path(self):
        self._assert_unsafe("C:/Windows/System32/evil.dll")

    def test_traversal_in_the_middle(self):
        self._assert_unsafe("bin/../../../evil.dll")

    def test_backslashes_are_traversal_too(self):
        self._assert_unsafe("..\\..\\evil.dll")


class TestTheNegativeHalfStillWorks(_Base):
    def test_a_content_pack_declares_no_entry_dll(self):
        # Content packs are data-only; SMAPI loads them without an EntryDll.
        info = self._inspect([
            ("manifest.json", _manifest_json(uid="probe.pack", name="Pack")),
            ("content.json", b"{}"),
        ])
        self.assertEqual(info["dir_name"], "probe.pack")
        self.assertIsNone(info["entryDll"])

    def test_a_mod_that_ships_its_dll_is_accepted(self):
        info = self._inspect([
            ("manifest.json", _manifest_json(entry_dll="ProbeMod.dll")),
            ("ProbeMod.dll", b"MZ"),
        ])
        self.assertEqual(info["dir_name"], "probe.mod")
        self.assertEqual(info["entryDll"], "ProbeMod.dll")

    def test_the_wrapper_is_still_stripped(self):
        info = self._inspect([
            ("Pack-1.0.0/manifest.json", _manifest_json(entry_dll="ProbeMod.dll")),
            ("Pack-1.0.0/ProbeMod.dll", b"MZ"),
        ])
        self.assertEqual(info["manifest_stripped"], "manifest.json")
        self.assertIn("ProbeMod.dll", info["members"])


class TestTheCheckIsCalledOnBothPaths(unittest.TestCase):
    def test_zip_and_7z_both_call_it(self):
        # Round 63 proved the .7z reader is a parallel implementation; a check
        # added to only one of them would leave a whole format unguarded.
        src = io.open(os.path.join(ROOT, "deckymod", "file_drop.py"),
                      encoding="utf-8").read()
        self.assertEqual(src.count("manifest.check_entry_dll("), 2,
                         "the EntryDll check must run on the ZIP and .7z paths")

    def test_the_helper_lives_next_to_the_parser(self):
        # It reads the parsed manifest, so it belongs with manifest.py; putting
        # it in file_drop.py would tempt a second copy later.
        src = io.open(os.path.join(ROOT, "deckymod", "manifest.py"),
                      encoding="utf-8").read()
        self.assertIn("def check_entry_dll(", src)
        self.assertEqual(
            io.open(os.path.join(ROOT, "deckymod", "file_drop.py"),
                    encoding="utf-8").read().count("def check_entry_dll("), 0)


if __name__ == "__main__":
    unittest.main()
