"""End-to-end .7z lifecycle through the REAL engine (goal item 3).

`tests/test_sevenzip.py` proves the validator. This file proves the wiring: that
a .7z goes all the way through `StardewEngine.inspect` -> `install` ->
`uninstall` -> `rollback` and lands on disk with the same layout a ZIP would.

There is no 7z binary on the Windows dev box, so `sevenzip.set_runner()` pins a
fake runner that understands the two commands production issues:

  * `7z l -slt -ba <archive>`  -> an entry listing
  * `7z x -y -bd -o<dir> <archive>` -> materialise the entries into <dir>

The fake reads a small archive model the test keeps in memory (ARCHIVES), keyed
by absolute path. Everything else — manifest parsing, staging, os.replace,
quarantine, journal, rollback — is the unmodified production code. This is
deliberately NOT a stub of the engine: only the external archiver is faked,
which is the exact boundary the Deck would cross with the real binary.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import uuid
import zipfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from deckymod import sevenzip  # noqa: E402
from deckymod.errors import ModError  # noqa: E402

# The engine resolves the active descriptor at construction time, and
# tests/test_mvp.py pins rimworld at import. Force the production game here.
_PREV_GAME_ID = None


def setUpModule():
    global _PREV_GAME_ID
    _PREV_GAME_ID = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    if _PREV_GAME_ID is not None:
        os.environ["DECKYMOD_GAME_ID"] = _PREV_GAME_ID
    else:
        os.environ.pop("DECKYMOD_GAME_ID", None)


MAGIC = b"7z\xbc\xaf'\x1c"

MANIFEST = {
    "Name": "Auto Bush",
    "Author": "TestCo",
    "Version": "1.5.2",
    "UniqueID": "TestCo.AutoBush7z",
    "EntryDll": "AutoBush.dll",
    "MinimumApiVersion": "4.0.0",
}


class _Archive:
    """In-memory model of one .7z: entry name -> bytes."""

    def __init__(self):
        self.entries = {}

    def add(self, name, data):
        self.entries[name] = data
        return self


ARCHIVES = {}


def _listing(archive):
    rows = []
    for name, data in sorted(archive.entries.items()):
        is_dir = name.endswith("/")
        rows.append("Path = %s" % name)
        rows.append("Size = %d" % (0 if is_dir else len(data)))
        rows.append("Packed Size = %d" % (0 if is_dir else max(1, len(data) // 2)))
        rows.append("Modified = 2026-11-15 10:00:00")
        rows.append("Attributes = %s" % ("D...." if is_dir else "....A"))
        rows.append("")
    return "\n".join(rows)


def _fake_runner(argv, cwd=None):
    """Understands exactly the two invocations production makes."""
    if len(argv) < 2:
        raise AssertionError("unexpected 7z invocation: %r" % (argv,))
    verb = argv[1]
    archive_path = argv[-1]
    model = ARCHIVES.get(os.path.abspath(archive_path))
    if model is None:
        return {"code": 2, "stdout": "", "stderr": "No such archive"}
    if verb == "l":
        return {"code": 0, "stdout": _listing(model), "stderr": ""}
    if verb == "x":
        dest = None
        for a in argv:
            if a.startswith("-o"):
                dest = a[2:]
        if not dest:
            return {"code": 2, "stdout": "", "stderr": "no -o"}
        os.makedirs(dest, exist_ok=True)
        for name, data in model.entries.items():
            if name.endswith("/"):
                os.makedirs(os.path.join(dest, *name.rstrip("/").split("/")), exist_ok=True)
                continue
            out = os.path.join(dest, *name.split("/"))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "wb") as f:
                f.write(data)
        return {"code": 0, "stdout": "", "stderr": ""}
    return {"code": 2, "stdout": "", "stderr": "unknown verb %s" % verb}


class _Tree(unittest.TestCase):
    """Synthetic Steam library + Stardew install, mirroring test_stardew."""

    def setUp(self):
        self.tmp = os.path.join(_ROOT, ".decky-test-tmp", "dz7e-" + uuid.uuid4().hex[:8])
        os.makedirs(self.tmp, exist_ok=True)
        self.home = os.path.join(self.tmp, "home", "deck")
        self.data = os.path.join(self.tmp, "data")
        self.inbox = os.path.join(self.data, "inbox")
        self.logs = os.path.join(self.tmp, "logs")
        self.steam = os.path.join(self.home, ".local", "share", "Steam")
        self.game = os.path.join(self.steam, "steamapps", "common", "Stardew Valley")
        self.mods = os.path.join(self.game, "Mods")
        for d in (self.inbox, self.logs, self.mods, os.path.join(self.steam, "steamapps")):
            os.makedirs(d, exist_ok=True)

        with open(os.path.join(self.steam, "steamapps", "libraryfolders.vdf"), "w",
                  encoding="utf-8") as f:
            f.write('"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n'
                    % self.steam.replace("\\", "/"))
        with open(os.path.join(self.steam, "steamapps", "appmanifest_413150.acf"), "w",
                  encoding="utf-8") as f:
            f.write('"AppState"\n{\n\t"appid"\t\t"413150"\n\t"installdir"\t\t"Stardew Valley"\n'
                    '\t"StateFlags"\t\t"4"\n}\n')
        # SMAPI must look present or every write is refused with E_LOADER_MISSING.
        smapi = os.path.join(self.game, "StardewModdingAPI")
        with open(smapi, "wb") as f:
            f.write(b"\x7fELF" + b"\x00" * 60)
        os.makedirs(os.path.join(self.game, "smapi-internal"), exist_ok=True)

        self._env = {k: os.environ.get(k) for k in (
            "DECKYMOD_STEAM_ROOT", "DECKYMOD_INBOX", "DECKYMOD_DATA",
            "DECKY_PLUGIN_LOG_DIR", "DECKY_USER_HOME", "DECKYMOD_GAME_ID")}
        os.environ["DECKYMOD_STEAM_ROOT"] = self.steam
        os.environ["DECKYMOD_INBOX"] = self.inbox
        os.environ["DECKYMOD_DATA"] = self.data
        os.environ["DECKY_PLUGIN_LOG_DIR"] = self.logs
        os.environ["DECKY_USER_HOME"] = self.home
        os.environ.pop("DECKYMOD_GAME_ID", None)
        sevenzip.set_runner(_fake_runner, tool="/usr/bin/7z")

    def tearDown(self):
        sevenzip.set_runner(None)
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def engine(self):
        from deckymod.smapi import StardewEngine
        return StardewEngine()

    def make_7z(self, name="autobush.7z", wrapper="AutoBush", manifest=None,
                extra=None, drop_manifest=False):
        """Write a fake .7z to the inbox and register its model.

        A wrapper directory is used by default because single-root wrapping is the
        shape real mod archives ship in, and it is the case where ZIP and 7z
        layout could silently diverge.
        """
        path = os.path.join(self.inbox, name)
        with open(path, "wb") as f:
            f.write(MAGIC + b"\x00" * 64)
        arc = _Archive()
        prefix = (wrapper + "/") if wrapper else ""
        if not drop_manifest:
            payload = dict(manifest or MANIFEST)
            arc.add(prefix + "manifest.json",
                    json.dumps(payload, indent=2).encode("utf-8"))
        arc.add(prefix + "AutoBush.dll", b"MZ" + b"\x00" * 512)
        for k, v in (extra or {}).items():
            arc.add(prefix + k, v)
        ARCHIVES[os.path.abspath(path)] = arc
        self.addCleanup(ARCHIVES.pop, os.path.abspath(path), None)
        return path


class TestInspect7z(_Tree):
    def test_inspect_reports_7z_format_and_the_descriptor_layout(self):
        path = self.make_7z()
        res = self.engine().inspect(path)
        self.assertTrue(res["ok"], res)
        mod = res["data"]["mod"]
        self.assertEqual(mod["format"], "7z")
        self.assertEqual(mod["uniqueId"], "TestCo.AutoBush7z")
        self.assertEqual(mod["dir_name"], "testco.autobush7z")
        self.assertEqual(mod["install_relpath"], "Mods/testco.autobush7z")
        self.assertEqual(mod["strip_single_root"], "AutoBush")
        # the wrapper must be stripped from the member map, exactly like ZIP
        self.assertIn("manifest.json", mod["members"])
        self.assertIn("AutoBush.dll", mod["members"])
        self.assertEqual(mod["manifest_stripped"], "manifest.json")

    def test_inspect_does_not_touch_the_mods_directory(self):
        path = self.make_7z()
        before = sorted(os.listdir(self.mods))
        self.engine().inspect(path)
        self.assertEqual(sorted(os.listdir(self.mods)), before)

    def test_inspect_without_a_manifest_names_the_missing_manifest(self):
        path = self.make_7z(drop_manifest=True)
        res = self.engine().inspect(path)
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "E_MANIFEST_MISSING")

    def test_inspect_refuses_an_exe_inside_a_7z(self):
        path = self.make_7z(extra={"setup.exe": b"MZ"})
        res = self.engine().inspect(path)
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "E_UNSAFE_ENTRY")

    def test_a_zip_renamed_to_7z_is_not_routed_to_the_7z_path(self):
        # magic mismatch -> treated as a ZIP, which then fails to open; the point
        # is that 7z is never invoked for it.
        path = os.path.join(self.inbox, "renamed.7z")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("manifest.json", json.dumps(MANIFEST))
            # The manifest declares EntryDll AutoBush.dll; ship it, or the
            # archive is one SMAPI could never load (round 64).
            zf.writestr("AutoBush.dll", b"MZ")
        calls = []

        def spy(argv, cwd=None):
            calls.append(argv)
            return _fake_runner(argv, cwd)

        sevenzip.set_runner(spy, tool="/usr/bin/7z")
        res = self.engine().inspect(path)
        self.assertTrue(res["ok"], res)
        self.assertEqual(calls, [], "a ZIP must not be passed to 7z")
        self.assertNotEqual(res["data"]["mod"].get("format"), "7z")


class TestInstall7z(_Tree):
    def test_two_phase_install_then_layout_on_disk(self):
        path = self.make_7z()
        eng = self.engine()

        first = eng.install(path, after_confirm=False)
        self.assertTrue(first["ok"], first)
        self.assertEqual(first["data"]["phase"], "confirm")
        self.assertEqual(os.listdir(self.mods), [], "confirm phase must not write")

        done = eng.install(path, after_confirm=True)
        self.assertTrue(done["ok"], done)
        target = os.path.join(self.mods, "testco.autobush7z")
        self.assertTrue(os.path.isdir(target), "install did not create the mod dir")
        # Layout parity with the ZIP path: wrapper stripped, manifest at the top.
        self.assertTrue(os.path.isfile(os.path.join(target, "manifest.json")))
        self.assertTrue(os.path.isfile(os.path.join(target, "AutoBush.dll")))
        self.assertFalse(os.path.exists(os.path.join(target, "AutoBush")),
                         "single-root wrapper leaked into the installed tree")
        with open(os.path.join(target, "manifest.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["UniqueID"], "TestCo.AutoBush7z")

    def test_install_shows_up_in_status_and_journal(self):
        path = self.make_7z()
        eng = self.engine()
        eng.install(path, after_confirm=True)
        st = eng.status()["data"]
        self.assertEqual(st["state"]["read_only"], False)
        dirs = [m["dir"] for m in st["state"]["mods"]]
        self.assertIn("testco.autobush7z", dirs)
        self.assertEqual([i["packageId"] for i in st["installed"]], ["TestCo.AutoBush7z"])

    def test_install_is_idempotent_guarded(self):
        path = self.make_7z()
        eng = self.engine()
        self.assertTrue(eng.install(path, after_confirm=True)["ok"])
        again = eng.install(path, after_confirm=False)
        self.assertFalse(again["ok"])
        self.assertEqual(again["code"], "E_DUPLICATE")

    def test_uninstall_moves_to_quarantine_and_rollback_restores(self):
        path = self.make_7z()
        eng = self.engine()
        inst = eng.install(path, after_confirm=True)
        self.assertTrue(inst["ok"], inst)
        target = os.path.join(self.mods, "testco.autobush7z")

        plan = eng.uninstall("testco.autobush7z", after_confirm=False)
        self.assertTrue(plan["ok"], plan)
        self.assertEqual(plan["data"]["phase"], "confirm")
        self.assertTrue(os.path.isdir(target), "confirm phase must not move anything")

        gone = eng.uninstall("testco.autobush7z", after_confirm=True)
        self.assertTrue(gone["ok"], gone)
        self.assertFalse(os.path.exists(target))
        qdirs = os.listdir(os.path.join(self.game, ".decky-quarantine"))
        self.assertEqual(len(qdirs), 1, qdirs)

        txn = gone["data"]["txn"]
        back = eng.rollback(txn)
        self.assertTrue(back["ok"], back)
        self.assertTrue(os.path.isdir(target))
        self.assertEqual(eng.recovery()["data"]["pending"], [])

    def test_staging_and_work_dirs_are_cleaned_up(self):
        path = self.make_7z()
        eng = self.engine()
        eng.install(path, after_confirm=True)
        staging = os.path.join(self.game, ".decky-staging")
        if os.path.isdir(staging):
            self.assertEqual(os.listdir(staging), [], "staging left files behind")


class TestExtractParity(_Tree):
    def test_zip_and_7z_produce_the_same_tree(self):
        """The whole point of the 7z branch: identical layout to ZIP."""
        eng = self.engine()

        # same content, delivered two ways
        zpath = os.path.join(self.inbox, "as_zip.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("AutoBush/manifest.json",
                        json.dumps(dict(MANIFEST, UniqueID="TestCo.AsZip"), indent=2))
            zf.writestr("AutoBush/AutoBush.dll", b"MZ" + b"\x00" * 512)
        self.assertTrue(eng.install(zpath, after_confirm=True)["ok"])

        apath = self.make_7z(name="as_7z.7z")
        self.assertTrue(eng.install(apath, after_confirm=True)["ok"])

        def tree(root):
            out = []
            for base, _dirs, files in os.walk(root):
                for fn in files:
                    rel = os.path.relpath(os.path.join(base, fn), root)
                    out.append(rel.replace("\\", "/"))
            return sorted(out)

        zip_dir = os.path.join(self.mods, "testco.aszip")
        seven_dir = os.path.join(self.mods, "testco.autobush7z")
        self.assertEqual(tree(zip_dir), tree(seven_dir),
                         "7z install layout diverged from ZIP")

    def test_7z_extraction_is_refused_before_validation(self):
        """extract_7z must not run when inspect rejected the archive."""
        path = self.make_7z(extra={"evil.exe": b"MZ"})
        before = sorted(os.listdir(self.mods))
        res = self.engine().inspect(path)
        self.assertFalse(res["ok"])
        self.assertEqual(sorted(os.listdir(self.mods)), before)


if __name__ == "__main__":
    unittest.main()
