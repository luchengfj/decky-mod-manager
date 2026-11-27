"""Round 84: a bundle of several mods can be listed, and one root installed.

Before this round a ZIP holding more than one mod was a dead end: the import
refused it with ``E_MULTI_MOD_ARCHIVE`` and told the user to split the archive
by hand. The refusal was right -- installing "the archive" would have written one
mod and silently dropped the rest -- but there was no way to see what was inside
or to say "install THIS one".

Two capabilities are pinned here, and they are deliberately tested against each
other:

  * ``file_drop.list_mod_roots`` ENUMERATES every root (never refusing), so the
    panel can show the user a choice.
  * ``file_drop.inspect_mod(..., member_root=...)`` narrows that choice to one
    root, and ``E_MULTI_MOD_ARCHIVE`` still fires when no root is given -- the
    old behaviour must survive verbatim, because it is what protects the user
    who did not read the list.

The invariant worth a test rather than a patch: the root the list reports and
the root the install extracts must be the SAME string, and the members map must
be re-anchored at it (keys relative to the root), otherwise the mod lands one
directory too deep where SMAPI never looks for a manifest.

No ``tempfile.mkdtemp``: it creates a 0o700 DACL that the Windows sandbox cannot
write through (see .decky-probe/run_tests.py). Everything is anchored under the
workspace's .decky-test-tmp instead.
"""

import json
import os
import shutil
import sys
import unittest
import uuid
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from deckymod import archive, file_drop, sevenzip  # noqa: E402
from deckymod.errors import ModError  # noqa: E402
from deckymod.journal import Journal  # noqa: E402
from deckymod.smapi import StardewEngine  # noqa: E402

TMP_ROOT = os.path.join(ROOT, ".decky-test-tmp")

# Passed explicitly, never taken from "the active game": tests/test_mvp.py pins
# DECKYMOD_GAME_ID=rimworld at import time, so discovery order would otherwise
# decide which parser these fixtures are read with.
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

_PREV_GAME_ID = None


def setUpModule():
    global _PREV_GAME_ID
    _PREV_GAME_ID = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    if _PREV_GAME_ID is not None:
        os.environ["DECKYMOD_GAME_ID"] = _PREV_GAME_ID
    else:
        os.environ.pop("DECKYMOD_GAME_ID", None)


def _tmpdir(tag):
    os.makedirs(TMP_ROOT, exist_ok=True)
    path = os.path.join(TMP_ROOT, "r70_%s_%s" % (tag, uuid.uuid4().hex[:8]))
    os.makedirs(path, exist_ok=False)
    return path


def _manifest(uid, name="Thing", version="1.0.0", entry_dll=None):
    doc = {"Name": name, "Author": "someone", "Version": version, "UniqueID": uid}
    if entry_dll:
        doc["EntryDll"] = entry_dll
    return json.dumps(doc)


class _Base(unittest.TestCase):
    def setUp(self):
        self.dir = _tmpdir(self.__class__.__name__[:10])

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _zip(self, entries, name="pack.zip"):
        path = os.path.join(self.dir, name)
        with zipfile.ZipFile(path, "w") as zf:
            for member, data in entries:
                zf.writestr(member, data)
        return path

    def _two_mod_zip(self):
        """Pack/ModA and Pack/ModB, one wrapper directory around both."""
        return self._zip([
            ("Pack/ModA/manifest.json", _manifest("a.mod", "Mod A", "1.2.3", "A.dll")),
            ("Pack/ModA/A.dll", b"MZ"),
            ("Pack/ModA/assets/tex.png", b"\x89PNG"),
            ("Pack/ModB/manifest.json", _manifest("b.mod", "Mod B", "2.0.0")),
            ("Pack/ModB/data.json", "{}"),
        ])


class TestListModRoots(_Base):
    """The enumeration the picker is built from: never refuses, always reports."""

    def test_two_mod_zip_lists_both_roots_with_name_and_version(self):
        listed = file_drop.list_mod_roots(self._two_mod_zip(),
                                          mod_package=STARDEW_MOD_PACKAGE)
        self.assertEqual(listed["format"], "zip")
        self.assertEqual(listed["count"], 2)
        roots = {r["root"]: r for r in listed["roots"]}
        self.assertEqual(sorted(roots), ["Pack/ModA", "Pack/ModB"])
        self.assertEqual(roots["Pack/ModA"]["name"], "Mod A")
        self.assertEqual(roots["Pack/ModA"]["version"], "1.2.3")
        self.assertEqual(roots["Pack/ModB"]["name"], "Mod B")
        self.assertEqual(roots["Pack/ModB"]["version"], "2.0.0")
        # The manifest is reported RELATIVE to its own root: that is the string
        # the caller hands back as member_root, so it must not be archive-wide.
        self.assertEqual(roots["Pack/ModA"]["manifest"], "manifest.json")
        self.assertEqual(roots["Pack/ModA"]["files"], 3)
        self.assertEqual(roots["Pack/ModB"]["files"], 2)
        self.assertEqual(listed["path"], os.path.abspath(self._two_mod_zip()))

    def test_single_mod_zip_reports_the_archive_root(self):
        zp = self._zip([
            ("manifest.json", _manifest("solo.mod", "Solo", "0.9")),
            ("solo.dll", b"MZ"),
        ])
        listed = file_drop.list_mod_roots(zp, mod_package=STARDEW_MOD_PACKAGE)
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["roots"][0]["root"], "")
        self.assertEqual(listed["roots"][0]["name"], "Solo")
        self.assertEqual(listed["roots"][0]["version"], "0.9")
        self.assertEqual(listed["roots"][0]["manifest"], "manifest.json")

    def test_one_root_at_the_archive_root_and_one_in_a_folder(self):
        """``""`` is a real root, not a placeholder: it sorts first and is listed."""
        zp = self._zip([
            ("manifest.json", _manifest("at.root", "At Root", "1.0")),
            ("Pack/ModB/manifest.json", _manifest("b.mod", "Mod B", "2.0")),
        ])
        listed = file_drop.list_mod_roots(zp, mod_package=STARDEW_MOD_PACKAGE)
        self.assertEqual(listed["count"], 2)
        self.assertEqual(listed["roots"][0]["root"], "")
        self.assertEqual(listed["roots"][0]["name"], "At Root")
        self.assertEqual(listed["roots"][1]["root"], "Pack/ModB")

    def test_a_root_with_an_unreadable_manifest_does_not_fail_the_listing(self):
        """One broken mod in a bundle must not hide the healthy ones."""
        zp = self._zip([
            ("Pack/Good/manifest.json", _manifest("good.mod", "Good", "3.1")),
            ("Pack/Broken/manifest.json", "{ this is not json"),
        ])
        listed = file_drop.list_mod_roots(zp, mod_package=STARDEW_MOD_PACKAGE)
        self.assertEqual(listed["count"], 2)
        by_root = {r["root"]: r for r in listed["roots"]}
        self.assertEqual(by_root["Pack/Good"]["name"], "Good")
        broken = by_root["Pack/Broken"]
        self.assertEqual((broken["name"], broken["version"], broken["manifest"]),
                         ("", "", ""))
        self.assertEqual(broken["files"], 1)

    def test_listing_does_not_raise_multi_mod_archive(self):
        """The whole point: the enumeration path never refuses a bundle."""
        listed = file_drop.list_mod_roots(self._two_mod_zip(),
                                          mod_package=STARDEW_MOD_PACKAGE)
        self.assertEqual(listed["count"], 2)  # would have raised E_MULTI_MOD_ARCHIVE

    def test_7z_listing_matches_the_zip_shape(self):
        """Same wire shape for .7z.

        There is no 7z binary on the Windows dev box, so the external archiver is
        pinned with ``sevenzip.set_runner`` -- the same seam tests/test_sevenzip.py
        uses. Only the archiver is faked; the listing, the root scan and the
        manifest parse are the unmodified production code.
        """
        zp = self._zip([("placeholder", b"x")], name="pack.7z")
        model = {
            "Pack/ModA/manifest.json": _manifest("a.mod", "Mod A", "1.2.3").encode(),
            "Pack/ModA/A.dll": b"MZ",
            "Pack/ModB/manifest.json": _manifest("b.mod", "Mod B", "2.0.0").encode(),
        }
        with open(zp, "wb") as f:
            f.write(b"7z\xbc\xaf'\x1c" + b"\x00" * 32)   # is_7z() checks the magic

        def runner(argv, cwd=None):
            verb = argv[1]
            if verb == "l":
                rows = []
                for name, data in sorted(model.items()):
                    rows += ["Path = %s" % name, "Size = %d" % len(data),
                             "Packed Size = %d" % max(1, len(data) // 2),
                             "Modified = 2026-11-27 10:00:00",
                             "Attributes = ....A", ""]
                return {"code": 0, "stdout": "\n".join(rows), "stderr": ""}
            if verb == "x":
                dest = [a[2:] for a in argv if a.startswith("-o")][0]
                for name, data in model.items():
                    out = os.path.join(dest, *name.split("/"))
                    os.makedirs(os.path.dirname(out), exist_ok=True)
                    with open(out, "wb") as f:
                        f.write(data)
                return {"code": 0, "stdout": "", "stderr": ""}
            return {"code": 2, "stdout": "", "stderr": "unexpected verb"}

        sevenzip.set_runner(runner, tool="/fake/7z")
        try:
            listed = file_drop.list_mod_roots(zp, mod_package=STARDEW_MOD_PACKAGE)
        finally:
            sevenzip.set_runner(None)
        self.assertEqual(listed["format"], "7z")
        self.assertEqual(listed["count"], 2)
        roots = {r["root"]: r for r in listed["roots"]}
        self.assertEqual(roots["Pack/ModA"]["name"], "Mod A")
        self.assertEqual(roots["Pack/ModA"]["version"], "1.2.3")
        self.assertEqual(roots["Pack/ModB"]["name"], "Mod B")

    @unittest.skipUnless(sevenzip.find_tool() is not None,
                         "no 7z binary on this machine (7z/7za/7zr/7zz not on PATH)")
    def test_7z_listing_with_the_real_binary(self):
        """Only runs where a real 7z exists (the Deck); skipped on the dev box."""
        import subprocess
        tool = sevenzip.find_tool()
        src = os.path.join(self.dir, "src")
        for mod, uid, name, ver in (("ModA", "a.mod", "Mod A", "1.2.3"),
                                    ("ModB", "b.mod", "Mod B", "2.0.0")):
            d = os.path.join(src, "Pack", mod)
            os.makedirs(d)
            with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as f:
                f.write(_manifest(uid, name, ver))
        real = os.path.join(self.dir, "real.7z")
        proc = subprocess.run([tool, "a", "-bd", real, "Pack"], cwd=src,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        listed = file_drop.list_mod_roots(real, mod_package=STARDEW_MOD_PACKAGE)
        self.assertEqual(listed["format"], "7z")
        self.assertEqual(listed["count"], 2)
        self.assertEqual(sorted(r["root"] for r in listed["roots"]),
                         ["Pack/ModA", "Pack/ModB"])


class TestInspectOneRoot(_Base):
    """Choosing a root: members re-anchored, path keeps the root as one segment."""

    def test_member_root_narrows_the_members_map(self):
        info = file_drop.inspect_mod(self._two_mod_zip(),
                                     mod_package=STARDEW_MOD_PACKAGE,
                                     member_root="Pack/ModA")
        self.assertEqual(info["strip_single_root"], "Pack/ModA")
        self.assertEqual(info["name"], "Mod A")
        self.assertEqual(info["uniqueId"], "a.mod")
        self.assertEqual(info["manifest_member"], "Pack/ModA/manifest.json")
        self.assertEqual(sorted(info["members"]),
                         ["A.dll", "assets/tex.png", "manifest.json"])
        for key in info["members"]:
            self.assertFalse(key.startswith("Pack/ModA/"),
                             "member keys must be relative to the chosen root")
        # the sibling mod must not ride along
        self.assertNotIn("data.json", info["members"])
        self.assertEqual(info["members"]["manifest.json"]["orig"],
                         "Pack/ModA/manifest.json")
        # install_relpath names the REAL destination: the bytes land at
        # Mods/<dir_name>, and dir_name comes from the manifest UniqueID, not
        # from the archive root they were read out of.
        self.assertEqual(info["install_relpath"], "Mods/a.mod")
        self.assertEqual(info["dir_name"], "a.mod")

    def test_without_member_root_the_bundle_is_still_refused(self):
        zp = self._two_mod_zip()
        with self.assertRaises(ModError) as ctx:
            file_drop.inspect_mod(zp, mod_package=STARDEW_MOD_PACKAGE)
        self.assertEqual(ctx.exception.code, "E_MULTI_MOD_ARCHIVE")
        # the message has to name the mods: the user must know what to split
        self.assertIn("Pack/ModA", ctx.exception.detail)
        self.assertIn("Pack/ModB", ctx.exception.detail)
        self.assertIn("2 mods", ctx.exception.detail)

    def test_extract_to_writes_the_mod_content_directly(self):
        zp = self._two_mod_zip()
        info = file_drop.inspect_mod(zp, mod_package=STARDEW_MOD_PACKAGE,
                                     member_root="Pack/ModA")
        dest = os.path.join(self.dir, "staged")
        archive.extract_to(info, zp, dest)
        # no outer "Pack/" or "ModA/" directory: SMAPI reads the top level only
        self.assertTrue(os.path.isfile(os.path.join(dest, "manifest.json")))
        self.assertTrue(os.path.isfile(os.path.join(dest, "A.dll")))
        self.assertTrue(os.path.isfile(os.path.join(dest, "assets", "tex.png")))
        self.assertFalse(os.path.exists(os.path.join(dest, "Pack")))
        with open(os.path.join(dest, "manifest.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["UniqueID"], "a.mod")

    def test_a_member_root_that_holds_no_manifest_reports_missing(self):
        with self.assertRaises(ModError) as ctx:
            file_drop.inspect_mod(self._two_mod_zip(), mod_package=STARDEW_MOD_PACKAGE,
                                  member_root="Pack/Nothing")
        self.assertEqual(ctx.exception.code, "E_MANIFEST_MISSING")

    def test_member_root_is_case_insensitive_like_the_archive(self):
        """A root echoed back from a listing may differ in case from the member."""
        info = file_drop.inspect_mod(self._two_mod_zip(),
                                     mod_package=STARDEW_MOD_PACKAGE,
                                     member_root="pack/moda")
        self.assertEqual(info["uniqueId"], "a.mod")
        self.assertEqual(sorted(info["members"]),
                         ["A.dll", "assets/tex.png", "manifest.json"])


class TestArchiveModsEngineMethod(_Base):
    """The read-only engine entry point the panel calls before the picker."""

    def _engine(self):
        # _validate_import_path only accepts declared import roots; the env seam
        # is the documented way to add one for a test tree.
        os.environ["DECKYMOD_EXTRA_IMPORT_ROOT"] = self.dir
        eng = StardewEngine(journal=Journal(self.dir, self.dir, "stardew"),
                            game_id="stardew")
        return eng

    def tearDown(self):
        os.environ.pop("DECKYMOD_EXTRA_IMPORT_ROOT", None)
        super().tearDown()

    def test_archive_mods_returns_the_listing(self):
        zp = self._two_mod_zip()
        eng = self._engine()
        res = eng.archive_mods(zp)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["data"]["count"], 2)
        self.assertEqual(sorted(r["root"] for r in res["data"]["roots"]),
                         ["Pack/ModA", "Pack/ModB"])

    def test_archive_mods_refuses_a_path_outside_the_import_roots(self):
        zp = self._two_mod_zip()
        eng = self._engine()
        os.environ.pop("DECKYMOD_EXTRA_IMPORT_ROOT", None)
        res = eng.archive_mods(zp)
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "E_PATH_ESCAPE")


_FOMOD_CFG = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<module><name>T</name><installSteps>'
    '<installStep name="Main"><optionalFileGroups>'
    '<group name="Core" type="SelectOne"><plugins>'
    '<plugin name="Small"><files>'
    '<file source="tex/small.dds" destination="tex/small.dds"/></files>'
    '<typeDescriptor><type name="Optional"/></typeDescriptor></plugin>'
    '<plugin name="Big"><files>'
    '<file source="tex/big.dds" destination="tex/big.dds"/></files>'
    '<typeDescriptor><type name="Recommended"/></typeDescriptor></plugin>'
    '</plugins></group></optionalFileGroups></installStep>'
    '</installSteps></module>'
)

_ENV_KEYS = ("DECKY_USER_HOME", "DECKYMOD_STEAM_ROOT", "DECKYMOD_DATA",
             "DECKYMOD_INBOX", "XDG_CONFIG_HOME", "DECKY_PLUGIN_RUNTIME_DIR",
             "DECKYMOD_GAME_RUNNING")


class TestInstallOneRootEndToEnd(_Base):
    """The round trip that matters: pick a root, install it, look on disk.

    Everything else in this module stops at the members map. This class writes a
    real (synthetic) Steam tree and installs, because the failure being guarded
    against -- the mod landing one directory too deep, where SMAPI never looks
    for a manifest -- is invisible until something is actually extracted.
    """

    def setUp(self):
        super().setUp()
        self._saved = {k: os.environ.get(k) for k in _ENV_KEYS}
        self.data = os.path.join(self.dir, "data")
        self.inbox = os.path.join(self.data, "inbox")
        os.makedirs(self.inbox)
        home = os.path.join(self.dir, "home")
        steam = os.path.join(home, ".local", "share", "Steam")
        sapps = os.path.join(steam, "steamapps")
        game = os.path.join(sapps, "common", "Stardew Valley")
        os.makedirs(os.path.join(game, "Mods"))
        os.makedirs(os.path.join(game, "smapi-internal"))
        with open(os.path.join(game, "StardewModdingAPI"), "wb") as f:
            f.write(b"ELF")
        with open(os.path.join(sapps, "libraryfolders.vdf"), "w", encoding="utf-8") as f:
            f.write('"libraryfolders" {"0" {"path" "%s"}}' % steam.replace("\\", "/"))
        with open(os.path.join(sapps, "appmanifest_413150.acf"), "w", encoding="utf-8") as f:
            f.write('"AppState" {"appid" "413150" "name" "Stardew Valley" '
                    '"installdir" "Stardew Valley" "StateFlags" "4"}')
        self.mods = os.path.join(game, "Mods")
        os.environ["DECKY_USER_HOME"] = home
        os.environ["DECKYMOD_STEAM_ROOT"] = steam
        os.environ["DECKYMOD_DATA"] = self.data
        os.environ["DECKYMOD_INBOX"] = self.inbox
        os.environ["XDG_CONFIG_HOME"] = os.path.join(self.dir, "xdg")
        os.environ["DECKY_PLUGIN_RUNTIME_DIR"] = self.data
        os.environ["DECKYMOD_GAME_RUNNING"] = ""

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        super().tearDown()

    def _engine(self):
        return StardewEngine(journal=Journal(self.data, self.data, "stardew"),
                             game_id="stardew")

    def _inbox_zip(self, entries, name="pack.zip"):
        """Same fixture, written INSIDE the declared inbox.

        ``_validate_import_path`` only accepts declared import roots, so a ZIP
        sitting next to the test tree would be refused with E_PATH_ESCAPE.
        """
        path = os.path.join(self.inbox, name)
        with zipfile.ZipFile(path, "w") as zf:
            for member, data in entries:
                zf.writestr(member, data)
        return path

    def _walk(self, root):
        found = []
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                found.append(os.path.relpath(os.path.join(dirpath, fn), root)
                             .replace("\\", "/"))
        return sorted(found)

    def test_installing_a_picked_root_writes_the_mod_at_the_top_level(self):
        zp = self._inbox_zip([
            ("Pack/ModA/manifest.json", _manifest("a.mod", "Mod A", "1.2.3", "A.dll")),
            ("Pack/ModA/A.dll", b"MZ"),
            ("Pack/ModA/assets/tex.png", b"\x89PNG"),
            ("Pack/ModB/manifest.json", _manifest("b.mod", "Mod B", "2.0.0")),
            ("Pack/ModB/data.json", "{}"),
        ])
        res = self._engine().install(zp, after_confirm=True, member_root="Pack/ModA")
        self.assertTrue(res["ok"], res)
        dest = res["data"]["dir"]
        self.assertEqual(os.path.dirname(dest), self.mods)
        # the wrapper directories are gone: SMAPI reads manifest.json at the top
        self.assertEqual(self._walk(dest),
                         ["A.dll", "assets/tex.png", "manifest.json"])
        # and the sibling mod was NOT installed along with it
        self.assertEqual(sorted(os.listdir(self.mods)), ["a.mod"])

        other = self._engine().install(zp, after_confirm=True, member_root="Pack/ModB")
        self.assertTrue(other["ok"], other)
        self.assertEqual(sorted(os.listdir(self.mods)), ["a.mod", "b.mod"])
        self.assertEqual(self._walk(other["data"]["dir"]), ["data.json", "manifest.json"])

    def test_the_preview_and_the_install_name_the_same_destination(self):
        """A preview that disagrees with its execute is worse than no preview."""
        zp = self._inbox_zip([
            ("Pack/ModA/manifest.json", _manifest("a.mod", "Mod A", "1.2.3", "A.dll")),
            ("Pack/ModA/A.dll", b"MZ"),
            ("Pack/ModB/manifest.json", _manifest("b.mod", "Mod B", "2.0.0")),
            ("Pack/ModB/data.json", "{}"),
        ])
        eng = self._engine()
        preview = eng.inspect(zp, member_root="Pack/ModB")
        self.assertTrue(preview["ok"], preview)
        promised = preview["data"]["targets"]["w2_install_dir"]
        real = eng.install(zp, after_confirm=True, member_root="Pack/ModB")
        self.assertTrue(real["ok"], real)
        self.assertEqual(promised, real["data"]["dir"])

    def test_fomod_choices_apply_after_the_root_is_chosen(self):
        """Order matters: narrow to the root FIRST, then reduce by FOMOD.

        The other order would leave the FOMOD file list pointing at members the
        narrowed map no longer has, and the selected file would vanish.
        """
        zp = self._inbox_zip([
            ("Pack/Fom/manifest.json", _manifest("fom.mod", "Fom", "1.0.0", "Mod.dll")),
            ("Pack/Fom/Mod.dll", b"MZ"),
            ("Pack/Fom/tex/small.dds", b"SMALL"),
            ("Pack/Fom/tex/big.dds", b"BIGG"),
            ("Pack/Fom/fomod/moduleconfig.xml", _FOMOD_CFG),
            ("Pack/Other/manifest.json", _manifest("other.mod", "Other", "2.0.0", "O.dll")),
            ("Pack/Other/O.dll", b"MZ"),
        ])
        eng = self._engine()
        res = eng.install(zp, after_confirm=True, member_root="Pack/Fom",
                          fomod_choices={"0.0": ["Small"]})
        self.assertTrue(res["ok"], res)
        files = self._walk(res["data"]["dir"])
        self.assertIn("tex/small.dds", files)
        self.assertNotIn("tex/big.dds", files, "the unselected FOMOD file was written")
        self.assertNotIn("O.dll", files, "a sibling mod leaked into the install")

    # ------------------------------------------------------------- the RPC seam
    def test_the_inspect_rpc_forwards_the_chosen_root(self):
        """The picker's second pass goes through the RPC, not the engine.

        Without the forward the preview answers E_MULTI_MOD_ARCHIVE again and
        src/index.tsx sends the user straight back to the picker they just used
        -- a loop with no exit. This is the only test that pins the RPC layer;
        the engine-level test above passes even when the RPC drops the kwarg.
        """
        import asyncio
        import main as plugin_main
        zp = self._inbox_zip([
            ("Pack/ModA/manifest.json", _manifest("a.mod", "Mod A", "1.2.3", "A.dll")),
            ("Pack/ModA/A.dll", b"MZ"),
            ("Pack/ModB/manifest.json", _manifest("b.mod", "Mod B", "2.0.0")),
            ("Pack/ModB/data.json", "{}"),
        ])
        p = plugin_main.Plugin()
        refused = asyncio.run(p.inspect(zp))
        self.assertFalse(refused["ok"])
        self.assertEqual(refused["code"], "E_MULTI_MOD_ARCHIVE")
        picked = asyncio.run(p.inspect(zp, "Pack/ModB"))
        self.assertTrue(picked["ok"], picked)
        self.assertEqual(picked["data"]["mod"]["uniqueId"], "b.mod")
        self.assertEqual(sorted(picked["data"]["mod"]["members"]),
                         ["data.json", "manifest.json"])

    def test_the_archive_mods_rpc_lists_every_root(self):
        import asyncio
        import main as plugin_main
        zp = self._inbox_zip([
            ("Pack/ModA/manifest.json", _manifest("a.mod", "Mod A", "1.2.3", "A.dll")),
            ("Pack/ModA/A.dll", b"MZ"),
            ("Pack/ModB/manifest.json", _manifest("b.mod", "Mod B", "2.0.0")),
            ("Pack/ModB/data.json", "{}"),
        ])
        res = asyncio.run(plugin_main.Plugin().archive_mods(zp))
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["data"]["count"], 2)
        self.assertEqual(sorted(r["root"] for r in res["data"]["roots"]),
                         ["Pack/ModA", "Pack/ModB"])

    def test_the_install_rpc_forwards_the_chosen_root(self):
        import asyncio
        import main as plugin_main
        zp = self._inbox_zip([
            ("Pack/ModA/manifest.json", _manifest("a.mod", "Mod A", "1.2.3", "A.dll")),
            ("Pack/ModA/A.dll", b"MZ"),
            ("Pack/ModB/manifest.json", _manifest("b.mod", "Mod B", "2.0.0")),
            ("Pack/ModB/data.json", "{}"),
        ])
        p = plugin_main.Plugin()
        # Without a root the bundle is still refused -- the old behaviour has to
        # survive, it is what stops a user who never saw the picker from getting
        # one arbitrary mod out of a bundle.
        refused = asyncio.run(p.install(zp, True))
        self.assertFalse(refused["ok"])
        self.assertEqual(refused["code"], "E_MULTI_MOD_ARCHIVE")
        preview = asyncio.run(p.install(zp, False, None, "Pack/ModA"))
        self.assertTrue(preview["ok"], preview)
        self.assertEqual(preview["data"]["phase"], "confirm")
        done = asyncio.run(p.install(zp, True, None, "Pack/ModA"))
        self.assertTrue(done["ok"], done)
        self.assertEqual(self._walk(done["data"]["dir"]),
                         ["A.dll", "manifest.json"])
        self.assertEqual(sorted(os.listdir(self.mods)), ["a.mod"])


if __name__ == "__main__":
    unittest.main()
