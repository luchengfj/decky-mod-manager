"""Synthetic-tree self-tests for the Decky MOD Manager MVP (RimWorld / selection A).

These run with the STDLIB ONLY, on a Windows dev box AND on SteamOS: they build
a fake Steam library under a temp dir and inject it through the documented env
overrides (DECKYMOD_STEAM_ROOT / DECKY_USER_HOME / XDG_CONFIG_HOME /
DECKYMOD_INBOX / DECKYMOD_DATA). No Decky runtime, no network, no real game
files, no root, and no writes outside the temp tree.

Run (from repo root):  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import zipfile

# Make the repo importable regardless of the caller's cwd.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# HISTORICAL REGRESSION PIN (2026-11-14): production active_game is now
# 'stardew'; these 33 tests exercise the original RimWorld selection-A code
# path, so pin the descriptor before Registry/Engine construction. Production
# leaves DECKYMOD_GAME_ID unset and uses the registry.json enabled descriptor.
os.environ.setdefault("DECKYMOD_GAME_ID", "rimworld")

from deckymod import archive, fsops, json_safe, paths, state_mutator, vdf  # noqa: E402
from deckymod.envelope import envelope, err, ok  # noqa: E402
from deckymod.errors import ERRORS, ModError  # noqa: E402
from deckymod.journal import Journal  # noqa: E402
from deckymod.registry import Registry  # noqa: E402
from deckymod.engine import Engine  # noqa: E402

VALID_STATE = (
    b'<?xml version="1.0" encoding="utf-8"?>\n'
    b"<!-- RimWorld config; comments must survive surgical_line_edit -->\n"
    b"<ModsConfigData>\n"
    b"  <version>1.4.3704</version>\n"
    b"  <activeMods>\n"
    b"    <li>ludeon.rimworld</li>\n"
    b"    <li>ludeon.rimworld.royalty</li>\n"
    b"  </activeMods>\n"
    b"  <knownExpansions>\n"
    b"    <li>ludeon.rimworld.royalty</li>\n"
    b"  </knownExpansions>\n"
    b"</ModsConfigData>\n"
)

ABOUT_XML = (
    b"<ModMetaData>\n"
    b"  <packageId>myco.testmod</packageId>\n"
    b"  <name>Test Mod</name>\n"
    b"  <author>Tester</author>\n"
    b"  <supportedVersions><li>1.4</li><li>1.5</li></supportedVersions>\n"
    b"  <modVersion>1.2.3</modVersion>\n"
    b"  <loadAfter><li>brrainz.harmony</li></loadAfter>\n"
    b"  <dependencies><li>brrainz.harmony</li></dependencies>\n"
    b"</ModMetaData>\n"
)


def _write(path: str, data: bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _vdf_escape_path(p: str) -> str:
    """Steam KeyValues uses \\ as an escape; a literal Windows backslash is \\\\."""
    return p.replace("\\", "\\\\")


def _make_zip(path: str, entries: dict, *, wrapper: str | None = None):
    """entries: {member_name: bytes}. If wrapper, prefix all member names."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            full = (wrapper + "/" + name) if wrapper else name
            zf.writestr(full, data)


def workspace_tmpdir() -> str:
    """A writable temp dir inside the workspace (avoids sandbox-denied %TEMP%).

    tempfile.TemporaryDirectory/mkdtemp use mode 0o700, whose restrictive
    Windows DACL the DSH sandbox denies for child creation/listing. A plain
    os.makedirs with default mode works on Windows and SteamOS alike.
    """
    import uuid
    test_root = os.path.join(ROOT, ".decky-test-tmp")
    os.makedirs(test_root, exist_ok=True)
    d = os.path.join(test_root, "decky-unit-" + uuid.uuid4().hex[:12])
    os.makedirs(d, exist_ok=False)
    return d


class _TreeMixin:
    """Builds an isolated synthetic Steam tree and injects env overrides."""

    def build_tree(self, *, state: bytes = VALID_STATE, with_game: bool = True,
                   flatpak: bool = False):
        # Anchor the synthetic tree inside the writable workspace, NOT the OS
        # temp dir (the DSH sandbox denies %TEMP% with WinError 5). Also avoid
        # tempfile.mkdtemp: its 0o700 mode yields a restrictive Windows DACL
        # that the sandbox denies for any child creation/listing. A plain
        # os.makedirs with default mode works on both Windows and SteamOS.
        import shutil as _shutil
        import uuid as _uuid
        test_root = os.path.join(ROOT, ".decky-test-tmp")
        os.makedirs(test_root, exist_ok=True)
        base = os.path.join(test_root, "decky-mvp-" + _uuid.uuid4().hex[:12])
        os.makedirs(base, exist_ok=False)
        self.addCleanup(lambda: _shutil.rmtree(base, ignore_errors=True))
        self.tmp_name = base
        self.home = os.path.join(base, "home")
        self.xdg = os.path.join(base, "xdg")
        self.inbox = os.path.join(base, "inbox")
        self.data = os.path.join(base, "data")
        for d in (self.home, self.xdg, self.inbox, self.data):
            os.makedirs(d, exist_ok=True)

        self._saved_env = {}
        env = {
            "DECKY_USER_HOME": self.home,
            "XDG_CONFIG_HOME": self.xdg,
            "DECKYMOD_INBOX": self.inbox,
            "DECKYMOD_DATA": self.data,
            "DECKYMOD_STEAM_ROOT": "",
            "DECKYMOD_EXTRA_IMPORT_ROOT": "",
            "DECKYMOD_GAME_RUNNING": "",
            "DECKY_USER": "",
            "DECKY_PLUGIN_RUNTIME_DIR": "",
            "DECKY_PLUGIN_LOG_DIR": "",
        }
        for k, v in env.items():
            self._saved_env[k] = os.environ.get(k)
            if v == "":
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.addCleanup(self._restore_env)

        self.steam_root = os.path.join(base, "Steam")
        if flatpak:
            self.steam_root = os.path.join(self.home, ".var", "app", "com.valvesoftware.Steam")
        self.game_root = os.path.join(self.steam_root, "steamapps", "common", "RimWorld")
        self.mod_root = os.path.join(self.game_root, "Mods")
        self.cfg_dir = os.path.join(self.xdg, "unity3d", "Ludeon Studios",
                                    "RimWorld by Ludeon Studios", "Config")
        self.state_file = os.path.join(self.cfg_dir, "ModsConfig.xml")

        if with_game:
            os.makedirs(self.mod_root, exist_ok=True)
            os.makedirs(self.cfg_dir, exist_ok=True)
            _write(self.state_file, state)
            lib_vdf = (
                '"libraryfolders"\n{\n'
                '\t"0"\n\t{\n'
                '\t\t"path"\t\t"' + _vdf_escape_path(self.steam_root) + '"\n'
                '\t\t"apps"\n\t\t{\n\t\t}\n'
                '\t}\n}\n'
            )
            _write(os.path.join(self.steam_root, "steamapps", "libraryfolders.vdf"),
                   lib_vdf.encode("utf-8"))
            acf = ('"AppState"\n{\n\t"appid"\t\t"294100"\n'
                   '\t"installdir"\t\t"RimWorld"\n\t"name"\t\t"RimWorld"\n}\n')
            _write(os.path.join(self.steam_root, "steamapps", "appmanifest_294100.acf"),
                   acf.encode("utf-8"))
            # env override so resolve() sees exactly this one root (native case)
            if not flatpak:
                os.environ["DECKYMOD_STEAM_ROOT"] = self.steam_root

        return self

    def _restore_env(self):
        for k, v in getattr(self, "_saved_env", {}).items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def make_mod_zip(self, name="testmod.zip", *, about=ABOUT_XML,
                     extra=None, wrapper="MyCoolMod"):
        p = os.path.join(self.inbox, name)
        entries = {"About/About.xml": about}
        if extra:
            entries.update(extra)
        _make_zip(p, entries, wrapper=wrapper)
        return p


# --------------------------------------------------------------------------- pure units
class TestVDF(unittest.TestCase):
    def test_library_paths_and_installdir(self):
        lib = '"libraryfolders" { "0" { "path" "/home/deck/Steam" "apps" { } } "1" { "path" "/run/media/mmcblk0p1" } }'
        self.assertEqual(vdf.find_library_paths(vdf.parse_vdf(lib)),
                         ["/home/deck/Steam", "/run/media/mmcblk0p1"])
        acf = '"AppState" { "appid" "294100" "installdir" "RimWorld" }'
        self.assertEqual(vdf.get_installdir(vdf.parse_vdf(acf)), "RimWorld")

    def test_comments_and_escapes(self):
        txt = '// header\n"root" { /* block */ "path" "C:\\\\Steam" }'
        parsed = vdf.parse_vdf(txt)
        self.assertEqual(vdf.find_library_paths(parsed), [r"C:\Steam"])


class TestJsonSafe(unittest.TestCase):
    def test_path_bytes_set_bigint_nan_decimal(self):
        import datetime
        import decimal
        import math
        from pathlib import Path
        payload = {
            "p": Path("/tmp/x"),
            "b": b"\x00\xff",
            "s": {3, 1, 2},
            "big": 76561198000000000,   # SteamID64
            "nan": float("nan"),
            "dec": decimal.Decimal("1.25"),
            "dt": datetime.date(2026, 1, 2),
            "nested": {1: "intkey"},
        }
        out = json_safe.to_json_safe(payload)
        # final gate: must serialize with allow_nan=False
        json.dumps(out, allow_nan=False)
        self.assertEqual(out["p"], str(Path("/tmp/x")))
        self.assertEqual(out["b"]["len"], 2)
        self.assertEqual(out["b"]["__b64__"], "AP8=")
        self.assertEqual(out["s"], [1, 2, 3])
        self.assertEqual(out["big"], "76561198000000000")
        self.assertIsNone(out["nan"])
        self.assertEqual(out["dec"], "1.25")
        self.assertEqual(out["dt"], "2026-01-02")
        self.assertEqual(out["nested"], {"1": "intkey"})

    def test_envelope_roundtrip(self):
        e = ok({"items": [1, 2]}, message="fine")
        self.assertTrue(e["ok"])
        self.assertEqual(e["data"]["items"], [1, 2])
        self.assertTrue(e["ts"].endswith("Z"))
        bad = err("E_ACCESS", detail="nope")
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["code"], "E_ACCESS")
        self.assertEqual(bad["rollback_available"], False)
        json.dumps(bad, allow_nan=False)


class TestStateMutator(unittest.TestCase):
    def test_add_remove_idempotent_and_byte_preserving(self):
        data = VALID_STATE
        added = state_mutator.add_entry(data, "myco.testmod")
        self.assertIn(b"<li>myco.testmod</li>", added)
        # comments / version / DLC / knownExpansions preserved verbatim
        for token in (b"<!-- RimWorld config", b"<version>1.4.3704</version>",
                      b"ludeon.rimworld.royalty", b"<knownExpansions>"):
            self.assertIn(token, added)
        # Core still first
        self.assertEqual(state_mutator.parse_state(added)["activeMods"][0], "ludeon.rimworld")
        # idempotent
        self.assertEqual(state_mutator.add_entry(added, "myco.testmod"), added)
        removed = state_mutator.remove_entry(added, "myco.testmod")
        self.assertNotIn(b"myco.testmod", removed)
        self.assertEqual(removed, data)  # byte-for-byte restoration

    def test_core_invariant(self):
        bad = b"<ModsConfigData><activeMods><li>some.other</li></activeMods></ModsConfigData>"
        with self.assertRaises(ModError) as cm:
            state_mutator.parse_state(bad)
        self.assertEqual(cm.exception.code, "E_CORE_MISSING")

    def test_cannot_remove_core(self):
        with self.assertRaises(ModError) as cm:
            state_mutator.remove_entry(VALID_STATE, "ludeon.rimworld")
        self.assertEqual(cm.exception.code, "E_CORE_MISSING")

    def test_corrupt(self):
        with self.assertRaises(ModError) as cm:
            state_mutator.parse_state(b"not xml")
        self.assertEqual(cm.exception.code, "E_STATE_CORRUPT")


class TestArchive(unittest.TestCase, _TreeMixin):
    def setUp(self):
        self.build_tree(with_game=False)

    def _inspect(self, zip_path):
        try:
            return archive.inspect_mod(zip_path, {})
        except ModError as e:
            return e

    def test_valid_single_root_zip(self):
        p = self.make_mod_zip(extra={"Defs/Thing.xml": b"<Defs/>"})
        info = self._inspect(p)
        self.assertIsInstance(info, dict)
        self.assertEqual(info["packageId"], "myco.testmod")
        self.assertEqual(info["version"], "1.2.3")
        self.assertFalse(info["version_is_fallback"])
        self.assertEqual(info["supportedVersions"], ["1.4", "1.5"])
        self.assertEqual(info["badges"]["dependencies"], ["brrainz.harmony"])
        self.assertEqual(info["install_relpath"], "Mods/myco.testmod")
        self.assertEqual(info["strip_single_root"], "MyCoolMod")

    def test_version_fallback(self):
        about = ABOUT_XML.replace(b"<modVersion>1.2.3</modVersion>", b"")
        p = self.make_mod_zip(about=about)
        info = self._inspect(p)
        self.assertTrue(info["version_is_fallback"])
        self.assertTrue(info["version"].startswith("sha256:12:"))

    def test_zip_slip(self):
        p = os.path.join(self.inbox, "slip.zip")
        _make_zip(p, {"../evil.txt": b"x"})
        e = self._inspect(p)
        self.assertIsInstance(e, ModError)
        self.assertEqual(e.code, "E_ZIP_SLIP")

    def test_forbidden_extension(self):
        p = os.path.join(self.inbox, "exe.zip")
        _make_zip(p, {"About/About.xml": ABOUT_XML, "run.exe": b"MZ"})
        e = self._inspect(p)
        self.assertEqual(e.code, "E_UNSAFE_ENTRY")

    def test_backslash_path(self):
        # On Windows, zipfile.writestr NORMALIZES a backslash member name to
        # "/", so a round-tripped ZIP can't carry a literal backslash. Test the
        # security gate directly instead; this is the code path that would
        # reject a crafted archive whose central directory keeps "\\".
        from deckymod.errors import ModError as _ME
        with self.assertRaises(_ME) as cm:
            archive._validate_member_name("About\\About.xml", 16)
        self.assertEqual(cm.exception.code, "E_UNSAFE_ENTRY")

    def test_duplicate_entries(self):
        p = os.path.join(self.inbox, "dup.zip")
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("About/About.xml", ABOUT_XML)
            zf.writestr("About/About.xml", ABOUT_XML)
        e = self._inspect(p)
        self.assertEqual(e.code, "E_DUPLICATE_ENTRY")

    def test_manifest_missing(self):
        p = os.path.join(self.inbox, "nomani.zip")
        _make_zip(p, {"Defs/Thing.xml": b"x"})
        e = self._inspect(p)
        self.assertEqual(e.code, "E_MANIFEST_MISSING")

    def test_bad_package_id(self):
        about = ABOUT_XML.replace(b"<packageId>myco.testmod</packageId>",
                                  b"<packageId>BAD ID!</packageId>")
        p = self.make_mod_zip(about=about)
        e = self._inspect(p)
        self.assertEqual(e.code, "E_ID_INVALID")

    def test_missing_supported_versions(self):
        about = ABOUT_XML.replace(b"<supportedVersions><li>1.4</li><li>1.5</li></supportedVersions>", b"")
        p = self.make_mod_zip(about=about)
        e = self._inspect(p)
        self.assertEqual(e.code, "E_FIELD_MISSING")

    def test_not_a_zip(self):
        p = os.path.join(self.inbox, "bad.zip")
        _write(p, b"hello")
        e = self._inspect(p)
        self.assertEqual(e.code, "E_BAD_ARCHIVE")


class TestRegistry(unittest.TestCase):
    def test_capability_gate(self):
        r = Registry()
        self.assertEqual(r.assert_enabled_count(), ["rimworld"])
        self.assertEqual(r.single_enabled_game(), "rimworld")
        self.assertTrue(r.require("rimworld", "local_import")["capabilities"]["local_import"])
        for cap in ("workshop", "network_download", "loader_install",
                    "universal_one_click", "load_order_solver"):
            with self.assertRaises(ModError) as cm:
                r.require("rimworld", cap)
            self.assertEqual(cm.exception.code, "E_CAPABILITY_DISABLED")
        for planned in ("factorio", "valheim"):
            with self.assertRaises(ModError) as cm:
                r.get_game(planned)
            self.assertEqual(cm.exception.code, "E_CAPABILITY_DISABLED")

    def test_error_messages_have_no_forbidden_instructions(self):
        forbidden = ("steamos-readonly disable", "sudo", "flatpak override")
        for code, (_cat, msg, _rb) in ERRORS.items():
            low = msg.lower()
            for f in forbidden:
                self.assertNotIn(f, low, f"{code} message leaks forbidden instruction {f!r}")


class TestFsops(unittest.TestCase):
    def test_atomic_write_works_without_posix_fns(self):
        import shutil
        d = workspace_tmpdir()
        try:
            target = os.path.join(d, "file.bin")
            fsops.atomic_write_bytes(target, b"abc", mode=0o644)
            with open(target, "rb") as f:
                self.assertEqual(f.read(), b"abc")
            fsops.atomic_write_text(target, "hello")
            with open(target, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "hello")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_bad_parent(self):
        import shutil
        d = workspace_tmpdir()
        try:
            with self.assertRaises(ModError) as cm:
                fsops.atomic_write_bytes(os.path.join(d, "missing", "x"), b"a")
            self.assertEqual(cm.exception.code, "E_PATH_INVALID")
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestPaths(unittest.TestCase, _TreeMixin):
    def test_resolve_native(self):
        self.build_tree()
        r = paths.resolve(294100, preflight=True)
        self.assertEqual(r.appid, 294100)
        self.assertEqual(r.install_dir, "RimWorld")
        self.assertEqual(os.path.realpath(r.mod_root), os.path.realpath(self.mod_root))
        self.assertEqual(os.path.realpath(r.state_file), os.path.realpath(self.state_file))
        self.assertIsNone(r.proton_prefix)          # native Linux, no pfx
        self.assertFalse(r.flatpak)
        # staging/quarantine are siblings, NOT inside Mods/
        self.assertNotIn(os.path.realpath(self.mod_root) + os.sep,
                         os.path.realpath(r.staging))
        # containment
        self.assertTrue(os.path.realpath(r.game_root).startswith(os.path.realpath(r.library_root)))
        # fully JSON-safe
        json.dumps(r.to_json_safe(), allow_nan=False)

    def test_game_not_found(self):
        self.build_tree(with_game=False)
        with self.assertRaises(ModError) as cm:
            paths.resolve(294100)
        self.assertEqual(cm.exception.code, "E_GAME_NOT_FOUND")

    def test_flatpak_is_refused_not_silently_overridden(self):
        self.build_tree(with_game=True, flatpak=True)
        with self.assertRaises(ModError) as cm:
            paths.resolve(294100)
        self.assertEqual(cm.exception.code, "E_FLATPAK_PERMISSION")


class TestEngineLifecycle(unittest.TestCase, _TreeMixin):
    def setUp(self):
        self.build_tree()

    def _engine(self):
        return Engine(registry=Registry(), journal=Journal(self.data, os.path.join(self.data, "logs")))

    def _assert_ok(self, env, label=""):
        self.assertTrue(env["ok"], f"{label}: {env.get('code')} {env.get('detail')}")
        return env["data"]

    def _read_state_bytes(self) -> bytes:
        with open(self.state_file, "rb") as f:
            return f.read()

    def test_full_install_enable_disable_uninstall_rollback(self):
        eng = self._engine()
        # 1) status / bootstrap
        st = self._assert_ok(eng.status(), "status")
        self.assertEqual(st["game"]["appid"], 294100)
        self.assertEqual(st["paths"]["w1_state_file"], self.state_file)
        self.assertFalse(st["recovery_needed"])

        # 2) inbox + inspect (dry-run, no writes)
        inbox = self._assert_ok(eng.list_inbox(), "list_inbox")
        self.assertEqual(len(inbox["items"]), 0)  # no zip yet
        zp = self.make_mod_zip()
        insp = self._assert_ok(eng.inspect(zp), "inspect")
        self.assertEqual(insp["mod"]["packageId"], "myco.testmod")
        self.assertFalse(insp["conflict"]["duplicate"])
        self.assertIn("w1_state_file", insp["targets"])
        self.assertIn("w2_install_dir", insp["targets"])
        # inspect must not have written anything into Mods/
        self.assertEqual(os.listdir(self.mod_root), [])

        # 3) install phase 1 = confirm payload (NO writes)
        c = self._assert_ok(eng.install(zp, after_confirm=False), "install-confirm")
        self.assertEqual(c["phase"], "confirm")
        self.assertEqual(os.listdir(self.mod_root), [])

        # 4) install phase 2 = execute
        ins = self._assert_ok(eng.install(zp, after_confirm=True), "install-execute")
        self.assertEqual(ins["packageId"], "myco.testmod")
        self.assertFalse(ins["enabled"])            # install != enable
        self.assertTrue(os.path.isfile(os.path.join(self.mod_root, "myco.testmod", "About", "About.xml")))
        # state file untouched by install
        self.assertEqual(state_mutator.parse_state(self._read_state_bytes())["activeMods"],
                         ["ludeon.rimworld", "ludeon.rimworld.royalty"])

        # 5) enable (surgical line edit)
        en = self._assert_ok(eng.set_enabled("myco.testmod", True, after_confirm=True), "enable")
        self.assertTrue(en["enabled"])
        active = state_mutator.parse_state(self._read_state_bytes())["activeMods"]
        self.assertEqual(active, ["ludeon.rimworld", "ludeon.rimworld.royalty", "myco.testmod"])
        # comments / version preserved
        self.assertIn(b"<!-- RimWorld config", self._read_state_bytes())

        # 6) disable
        dis = self._assert_ok(eng.set_enabled("myco.testmod", False, after_confirm=True), "disable")
        self.assertFalse(dis["enabled"])
        self.assertNotIn(b"myco.testmod", self._read_state_bytes())

        # 7) uninstall: phase 1 confirm, phase 2 -> quarantine (never delete)
        uconfirm = self._assert_ok(eng.uninstall("myco.testmod", after_confirm=False), "uninstall-confirm")
        self.assertEqual(uconfirm["phase"], "confirm")
        u = self._assert_ok(eng.uninstall("myco.testmod", after_confirm=True), "uninstall-execute")
        self.assertFalse(os.path.exists(os.path.join(self.mod_root, "myco.testmod")))
        self.assertTrue(os.path.isdir(u["quarantine"]))   # preserved, not deleted

        # 8) rollback restores the directory + state bytes
        rb = self._assert_ok(eng.rollback(u["txn"]), "rollback")
        self.assertEqual(rb["restored"], "myco.testmod")
        self.assertTrue(os.path.isfile(os.path.join(self.mod_root, "myco.testmod", "About", "About.xml")))

        # 9) history + recovery + refresh
        hist = self._assert_ok(eng.history(50), "history")
        self.assertTrue(any(x.get("event") == "MOD_UNINSTALLED" for x in hist["items"]))
        rec = self._assert_ok(eng.recovery(), "recovery")
        self.assertFalse(rec["pending"])            # all committed
        ref = self._assert_ok(eng.refresh(), "refresh")
        self.assertEqual(ref["game"]["appid"], 294100)

    def test_install_rejects_duplicate_packageid(self):
        eng = self._engine()
        zp = self.make_mod_zip()
        self._assert_ok(eng.install(zp, after_confirm=True), "first install")
        env = eng.install(zp, after_confirm=False)
        self.assertFalse(env["ok"])
        self.assertEqual(env["code"], "E_DUPLICATE")

    def test_install_rejects_untracked_folder_collision(self):
        eng = self._engine()
        zp = self.make_mod_zip()
        os.makedirs(os.path.join(self.mod_root, "myco.testmod"), exist_ok=True)
        env = eng.install(zp, after_confirm=False)
        self.assertEqual(env["code"], "E_FILE_COLLISION")

    def test_import_path_escape_refused(self):
        eng = self._engine()
        outside = os.path.join(self.tmp_name, "outside.zip")
        _make_zip(outside, {"About/About.xml": ABOUT_XML}, wrapper="W")
        env = eng.inspect(outside)
        self.assertFalse(env["ok"])
        self.assertEqual(env["code"], "E_PATH_ESCAPE")

    def test_game_running_refused(self):
        eng = self._engine()
        zp = self.make_mod_zip()
        os.environ["DECKYMOD_GAME_RUNNING"] = "1"
        env = eng.install(zp, after_confirm=True)
        self.assertEqual(env["code"], "E_GAME_RUNNING")

    def test_verify_on_open_drift_detection(self):
        eng = self._engine()
        zp = self.make_mod_zip()
        self._assert_ok(eng.install(zp, after_confirm=True), "install")
        self._assert_ok(eng.refresh(), "refresh")           # caches fp
        # simulate RimWorld rewriting the config on quit
        _write(self.state_file, state_mutator.add_entry(VALID_STATE, "external.mod"))
        env = eng.set_enabled("myco.testmod", True, after_confirm=True)
        self.assertEqual(env["code"], "E_STATE_EXTERNAL")

    def test_status_when_state_file_missing(self):
        os.remove(self.state_file)
        eng = self._engine()
        st = self._assert_ok(eng.status(), "status")
        # status() is read-only; it reports the error but does not crash
        self.assertIn("error", st["state"])


class TestPluginRPC(unittest.TestCase, _TreeMixin):
    """Exercise the actual Decky entry-point class (async public RPC methods)."""

    def setUp(self):
        self.build_tree()

    def test_async_methods_return_envelopes(self):
        import asyncio
        import main as plugin_main
        p = plugin_main.Plugin()
        asyncio.run(p._main())

        def call(coro):
            return asyncio.run(coro)

        env = call(p.status())
        self.assertTrue(env["ok"])
        self.assertEqual(env["data"]["game"]["appid"], 294100)

        zp = self.make_mod_zip()
        ins = call(p.inspect(zp))
        self.assertTrue(ins["ok"])

        codes = call(p.error_codes())
        self.assertTrue(codes["ok"])
        self.assertEqual(codes["data"]["count"], len(ERRORS))

        c = call(p.install(zp, False))
        self.assertEqual(c["data"]["phase"], "confirm")
        done = call(p.install(zp, True))
        self.assertTrue(done["ok"], done.get("detail"))

        hist = call(p.history(10))
        self.assertTrue(hist["ok"])
        rec = call(p.recovery())
        self.assertTrue(rec["ok"])
        ref = call(p.refresh())
        self.assertTrue(ref["ok"])
        rb = call(p.rollback("no-such-txn"))
        self.assertFalse(rb["ok"])  # unknown txn -> clean envelope, no traceback
        asyncio.run(p._unload())


if __name__ == "__main__":
    unittest.main(verbosity=2)
