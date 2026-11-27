"""STEP 4 (goal-221c8ac6 rev2): prove the ManifestParser layer is PLUGGABLE.

The claim under test: adding a SECOND game (Factorio) requires ONLY a
descriptor JSON change + (if the manifest format differs) a parser class that is
already registered. NO engine-code (.py) change, and specifically NO
``if game == "stardew"`` branch in the engine/parser layer.

Design:
  * Factorio's manifest is ``info.json`` with a DIFFERENT field set
    (name / title / version / author / factorio_version / dependencies) than
    SMAPI's ``manifest.json`` (UniqueID / Name / Version / Author). Both are
    parsed by the SAME ``JsonMapParser`` driven purely by ``field_map``.
  * The device has NO Factorio install (no appmanifest_427520), so this is a
    SYNTHETIC TREE only. It is NOT a real-game write-back sign-off and does NOT
    close G3. See registry/games/factorio.json note.
  * ``paths.resolve()`` used to pin ``mod_root = <game_root>/Mods``, so the
    synthetic tree placed info.json mod dirs under game_root/Mods and the
    descriptor's own ``paths.mod_root`` was reference metadata only. As of
    Round 43 that block is honoured, so this tree places Factorio's mods at
    ``<HOME>/.factorio/mods`` -- which is both the descriptor's declared value
    and the real Factorio location on Linux.
  * ``force_read_only: true`` in the descriptor makes every write RPC return
    E_CAPABILITY_DISABLED before any file access (zero-damage proof).

STDLIB ONLY, Windows dev box AND SteamOS. No Decky runtime, no network, no
real game files, no root, no writes outside the temp tree.

Pin note: unittest discovery imports ALL modules first. test_mvp.py sets
DECKYMOD_GAME_ID=rimworld at import time; test_stardew.py pops/restores it in
its own setUpModule/tearDownModule. This module saves/restores the pin around
EACH test that needs "factorio", so no suite interferes with another.
"""

from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deckymod import manifest
from deckymod.journal import Journal
from deckymod.manifest import JsonMapParser, PARSERS, parser_for
from deckymod.smapi import FileDropEngine

REG_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "registry")


def _mod_package(game_id: str) -> dict:
    """Load a descriptor's mod_package directly (bypasses the status gate)."""
    with open(os.path.join(REG_ROOT, "games", game_id + ".json"),
              "r", encoding="utf-8") as f:
        return json.load(f)["mod_package"]


def _engine_source() -> str:
    with open(os.path.join(REG_ROOT, "..", "deckymod", "smapi.py"),
              "r", encoding="utf-8") as f:
        return f.read()


def _jsonmap_class_source() -> str:
    """Just the JsonMapParser class body (no module docstring), so we can prove
    no game-specific field-name literal is hard-coded in the parser logic."""
    with open(manifest.__file__, "r", encoding="utf-8") as f:
        src = f.read()
    return src.split("class JsonMapParser:", 1)[1].split("class XmlAboutParser:", 1)[0]


def _tree_sig(root: str) -> str:
    """Stable signature of a directory tree (names + sizes), for zero-damage."""
    out = []
    for base, dirs, files in os.walk(root):
        dirs.sort()
        files.sort()
        for d in dirs:
            out.append("D:" + os.path.relpath(os.path.join(base, d), root))
        for fn in files:
            p = os.path.join(base, fn)
            out.append("F:" + os.path.relpath(p, root) + ":" + str(os.path.getsize(p)))
    return "\n".join(sorted(out))


# Factorio info.json shapes. Note the objects in "dependencies": the parser
# extracts ids via descriptor-declared "dependency_id_keys".
INFO_BOB = {
    "name": "bobsmods", "title": "Bob's Mods", "version": "1.2.3",
    "author": "Bob", "factorio_version": "1.1",
    "dependencies": [{"name": "base"}],
}
INFO_CLEAN = {
    "name": "cleanmod", "title": "Clean Mod", "version": "0.9.0",
    "author": "Ann", "factorio_version": "1.1",
    "dependencies": [{"name": "bobsmods"}],  # SATISFIED dependency
}
INFO_SAME = {
    "name": "samemod", "title": "Same Mod", "version": "1.0.0",
    "author": "Sam", "factorio_version": "1.1",
}


class FactorioTree:
    """Fake Steam library for AppID 427520 / installdir "Factorio"."""

    def __init__(self):
        self.base = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".decky-test-tmp", "factorio-step4-" + os.urandom(6).hex())
        self.home = os.path.join(self.base, "home")
        self.xdg = os.path.join(self.base, "xdg")
        self.inbox = os.path.join(self.base, "inbox")
        self.data = os.path.join(self.base, "data")
        self.logs = os.path.join(self.data, "logs")
        for d in (self.home, self.xdg, self.inbox, self.data, self.logs):
            os.makedirs(d, exist_ok=True)
        self.steam = os.path.join(self.base, "Steam")
        self.sapps = os.path.join(self.steam, "steamapps")
        self.game = os.path.join(self.sapps, "common", "Factorio")
        # Round 43: the descriptor declares ``mod_root: "${HOME}/.factorio/mods"``
        # -- the real Factorio location, OUTSIDE the game directory and not named
        # ``Mods``. Since Round 43 that block is honoured, so the tree has to put
        # the mods where the descriptor says. Before, this line was
        # ``os.path.join(self.game, "Mods")`` purely to accommodate the
        # hard-coded folder name in ``paths.resolve()``.
        self.mods = os.path.join(self.home, ".factorio", "mods")
        os.makedirs(self.mods, exist_ok=True)
        os.makedirs(self.game, exist_ok=True)

        def put_mod(dirname, info):
            d = os.path.join(self.mods, dirname)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "info.json"), "w", encoding="utf-8") as f:
                json.dump(info, f)

        put_mod("bobsmods", INFO_BOB)
        put_mod("cleanmod", INFO_CLEAN)
        put_mod("duplicatemod_a", INFO_SAME)
        put_mod("duplicatemod_b", INFO_SAME)
        # one BAD mod: no manifest -> isolated parse_error, never aborts scan
        os.makedirs(os.path.join(self.mods, "badmod"), exist_ok=True)
        # dot-directory must be skipped (SMAPI/Amethyst-hidden siblings)
        hidden = os.path.join(self.mods, ".hidden")
        os.makedirs(hidden, exist_ok=True)
        with open(os.path.join(hidden, "info.json"), "w", encoding="utf-8") as f:
            json.dump(INFO_SAME, f)

        with open(os.path.join(self.sapps, "libraryfolders.vdf"), "w",
                  encoding="utf-8") as f:
            f.write('"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"'
                    + self.steam + '"\n\t\t"apps"\n\t\t{\n\t\t}\n\t}\n}\n')
        with open(os.path.join(self.sapps, "appmanifest_427520.acf"), "w",
                  encoding="utf-8") as f:
            f.write('"AppState"\n{\n\t"appid"\t\t"427520"\n\t"installdir"\t\t'
                    '"Factorio"\n\t"name"\t\t"Factorio"\n}\n')

    def env(self):
        os.environ.update({
            "DECKY_USER_HOME": self.home,
            "XDG_CONFIG_HOME": self.xdg,
            "DECKYMOD_INBOX": self.inbox,
            "DECKYMOD_DATA": self.data,
            "DECKYMOD_STEAM_ROOT": self.steam,
            "DECKY_PLUGIN_RUNTIME_DIR": self.data,
            "DECKY_PLUGIN_LOG_DIR": self.logs,
        })
        for k in ("DECKYMOD_GAME_RUNNING", "DECKYMOD_EXTRA_IMPORT_ROOT", "DECKY_USER"):
            os.environ.pop(k, None)

    def cleanup(self):
        import shutil
        shutil.rmtree(self.base, ignore_errors=True)


class _PinnedTreeMixin:
    """Save/restore DECKYMOD_GAME_ID around each test (no module-level pop)."""

    def setUp(self):
        self._prev_pin = os.environ.get("DECKYMOD_GAME_ID")
        self.t = FactorioTree()
        self.t.env()

    def tearDown(self):
        if self._prev_pin is None:
            os.environ.pop("DECKYMOD_GAME_ID", None)
        else:
            os.environ["DECKYMOD_GAME_ID"] = self._prev_pin
        self.t.cleanup()

    def pin(self, gid):
        os.environ["DECKYMOD_GAME_ID"] = gid

    def engine(self):
        return FileDropEngine(
            game_id="factorio",
            journal=Journal(self.t.data, self.t.logs, "factorio"))


class TestParserPluggability(_PinnedTreeMixin, unittest.TestCase):
    """Structural proof: one parser, two descriptors, zero engine .py changes."""

    def test_same_parser_class_for_both_descriptors(self):
        p_s = parser_for(_mod_package("stardew"))
        p_f = parser_for(_mod_package("factorio"))
        self.assertIs(type(p_s), JsonMapParser)
        self.assertIs(type(p_s), type(p_f))
        # Both descriptors declare the SAME parser name; only field maps differ.
        self.assertEqual(_mod_package("stardew")["parser"], "json_map")
        self.assertEqual(_mod_package("factorio")["parser"], "json_map")

    def test_field_names_live_only_in_descriptors(self):
        p_s = parser_for(_mod_package("stardew"))
        p_f = parser_for(_mod_package("factorio"))
        self.assertEqual(p_s.field_map["id"], "UniqueID")
        self.assertEqual(p_f.field_map["id"], "name")
        self.assertEqual(p_s.globs[0], "manifest.json")
        self.assertEqual(p_f.globs[0], "info.json")
        # NO game-specific field-name literal inside the parser LOGIC.
        body = _jsonmap_class_source()
        for literal in ("UniqueID", "MinimumApiVersion", "EntryDll",
                        "factorio_version", "info.json", "manifest.json", "$.name",
                        '"Name"', '"Version"'):
            self.assertNotIn(literal, body, f"{literal} leaked into JsonMapParser")

    def test_two_manifest_formats_registered(self):
        self.assertIn("json_map", PARSERS)
        self.assertIn("xml_about", PARSERS)  # RimWorld XML plugs into same registry
        self.assertIs(PARSERS["json_map"], JsonMapParser)

    def test_engine_source_has_no_game_id_branch(self):
        # Inspect REAL comparison nodes, not raw text: the module docstring and
        # comments legitimately mention "there is no `if game == ...`" as prose.
        import ast
        tree = ast.parse(_engine_source())
        game_ids = {"stardew", "factorio", "rimworld", "valheim"}
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                for c in [node.left] + list(node.comparators):
                    if isinstance(c, ast.Constant) and isinstance(c.value, str) \
                            and c.value in game_ids:
                        offenders.append((node.lineno, c.value))
        self.assertEqual(offenders, [],
                         f"real game-id comparison found in engine code: {offenders}")

    def test_parse_factorio_info_json(self):
        p = parser_for(_mod_package("factorio"))
        raw = json.dumps(INFO_BOB).encode("utf-8")
        pm = p.parse(raw, "info.json")
        self.assertEqual(pm.uid, "bobsmods")
        self.assertEqual(pm.dir_name, "bobsmods")  # id_normalize: none
        self.assertEqual(pm.name, "Bob's Mods")
        self.assertEqual(pm.version, "1.2.3")
        self.assertEqual(pm.author, "Bob")
        self.assertEqual(pm.minimum_api_version, "1.1")
        self.assertEqual(pm.dependencies, ["base"])
        self.assertEqual(pm.badges["author"], "Bob")


class TestFactorioReadOnlyEngine(_PinnedTreeMixin, unittest.TestCase):
    """The SAME FileDropEngine enumerates Factorio mods via the descriptor."""

    def test_scan_installed_mods_pure(self):
        before = _tree_sig(self.t.mods)
        scanned = manifest.scan_installed_mods(self.t.mods, _mod_package("factorio"))
        self.assertEqual(_tree_sig(self.t.mods), before, "scan must be read-only")

        by_dir = {m["dir"]: m for m in scanned["mods"]}
        self.assertEqual(len(by_dir), 5, "dot-directory must be skipped")
        self.assertNotIn(".hidden", by_dir)

        bob = by_dir["bobsmods"]
        self.assertEqual(bob["uniqueId"], "bobsmods")
        self.assertEqual(bob["name"], "Bob's Mods")
        self.assertEqual(bob["version"], "1.2.3")
        self.assertEqual(bob["author"], "Bob")
        self.assertEqual(bob["dependencies"], ["base"])
        self.assertEqual(bob["missing_dependencies"], ["base"])

        clean = by_dir["cleanmod"]
        self.assertEqual(clean["dependencies"], ["bobsmods"])
        self.assertEqual(clean["missing_dependencies"], [],
                         "dependency present on disk must be satisfied")

        self.assertEqual(by_dir["badmod"].get("parse_error"), "E_MANIFEST_MISSING",
                         "one bad manifest must be isolated, not abort the scan")

        self.assertEqual(scanned["duplicate_ids"],
                         [["samemod", ["duplicatemod_a", "duplicatemod_b"]]])
        self.assertEqual(scanned["missing_dependencies"], ["base"])

    def test_status_is_descriptor_driven_and_read_only(self):
        self.pin("factorio")
        r = self.engine().status()
        self.assertTrue(r["ok"], r)
        d = r["data"]
        self.assertEqual(d["game"]["appid"], 427520)
        self.assertEqual(d["game"]["name"], "Factorio")
        self.assertEqual(d["game"]["platform"], "linux-native")
        self.assertIsNone(d["paths"]["w1_state_file"], "file_drop has NO W1 state file")
        # Round 43: the descriptor's ``paths.mod_root`` is now READ, not inert
        # reference metadata. Factorio's real mod folder is ``~/.factorio/mods``
        # -- outside the game directory and not called ``Mods`` -- so this
        # assertion is what proves a second game needs no ``paths.py`` edit.
        self.assertEqual(
            os.path.normcase(d["paths"]["w2_mod_root"]),
            os.path.normcase(os.path.join(self.t.home, ".factorio", "mods")))

        st = d["state"]
        self.assertEqual(st["strategy"], "file_drop")
        self.assertTrue(st["read_only"], "force_read_only descriptor gate")
        self.assertFalse(st["external_manager"])
        self.assertTrue(st["loader_detected"])
        self.assertEqual(st["launch_options"], "n/a",
                         "no loader_detection declared -> nothing to check")
        self.assertEqual(st["missing_dependencies"], ["base"])
        self.assertEqual(st["duplicate_ids"],
                         [["samemod", ["duplicatemod_a", "duplicatemod_b"]]])
        names = {m.get("name") for m in st["mods"]}
        self.assertIn("Bob's Mods", names)
        self.assertIn("Clean Mod", names)
        # NO SMAPI-specific identity leaked into this game's status.
        self.assertNotIn("Stardew Valley", json.dumps(d))
        self.assertNotIn("413150", json.dumps(d))
        self.assertTrue(d["capabilities"]["detection_only"])
        self.assertFalse(d["capabilities"]["enable_disable"])

    def test_writes_refused_and_zero_damage(self):
        self.pin("factorio")
        before = _tree_sig(self.t.game)
        eng = self.engine()
        # install: _check_write_allowed fires BEFORE _validate_import_path, so a
        # nonexistent zip is fine and proves no file access happened.
        calls = [
            eng.install("does-not-exist.zip"),
            eng.uninstall("bobsmods"),
            eng.rollback("no-such-txn"),
            eng.set_enabled("bobsmods", True),
        ]
        for r in calls:
            self.assertFalse(r["ok"], r)
            self.assertEqual(r["code"], "E_CAPABILITY_DISABLED", r)
        self.assertEqual(_tree_sig(self.t.game), before,
                         "read-only descriptor must not touch the tree")
        self.assertFalse(os.path.exists(os.path.join(self.t.game, ".decky-staging")))
        self.assertFalse(os.path.exists(os.path.join(self.t.game, ".decky-quarantine")))


class TestJsoncDialect(unittest.TestCase):
    """Real SMAPI community manifests (probed on-device 2026-11-14) are JSONC:

    * ModManifestBuilder emits ``/* */`` header comments;
    * several ship arrays/objects with trailing commas;
    * SMAPI built-ins use ``UniqueId`` casing instead of ``UniqueID``.

    All three are legal in the wild, so the descriptor opts into a generic
    json_dialect + field_aliases. This locks the behaviour with unit tests and
    proves the URL ``//`` and escaped quotes inside strings are NOT mangled.
    """

    def _parser(self):
        return parser_for(_mod_package("stardew"))

    def test_jsonc_comments_and_trailing_commas(self):
        raw = (b'{\r\n  /* generated by ModManifestBuilder */\r\n'
               b'  "$schema": "https://smapi.io/schemas/manifest.json",\r\n'
               b'  "UniqueID": "spacechase0.GenericModConfigMenu",\r\n'
               b'  "Name": "Generic Mod Config Menu",\r\n'
               b'  "Author": "kittycatcasey",\r\n'
               b'  "Version": "1.16.0",\r\n'
               b'  "UpdateKeys": [ "Nexus:5098", ],\r\n'
               b'  "ContentPackFor": { "UniqueID": "Pathoschild.ContentPatcher", },\r\n'
               b'}\r\n')
        pm = self._parser().parse(raw, "manifest.json")
        self.assertEqual(pm.uid, "spacechase0.GenericModConfigMenu")
        self.assertEqual(pm.name, "Generic Mod Config Menu")
        self.assertEqual(pm.dependencies, ["Pathoschild.ContentPatcher"])

    def test_field_alias_uniqueid_casing(self):
        raw = (b'{"Name": "Console Commands", "Author": "SMAPI", '
               b'"Version": "4.5.2", "UniqueId": "SMAPI.ConsoleCommands"}')
        pm = self._parser().parse(raw, "manifest.json")
        self.assertEqual(pm.uid, "SMAPI.ConsoleCommands")
        self.assertEqual(pm.dir_name, "smapi.consolecommands")

    def test_strict_dialect_still_rejects_bad_json(self):
        # factorio descriptor has no json_dialect -> strict json
        p = parser_for(_mod_package("factorio"))
        with self.assertRaises(Exception) as ctx:
            p.parse(b'{ "name": "x", /* comment */ }', "info.json")
        self.assertEqual(getattr(ctx.exception, "code", None), "E_MANIFEST_INVALID")

    def test_string_literals_with_slashes_and_escapes_survive(self):
        raw = (b'{\n  /* header */\n'
               b'  "UniqueID": "a.b",\n'
               b'  "Name": "He said \\"hi\\" // not a comment",\n'
               b'  "Version": "1.0",\n'
               b'  "Description": "https://smapi.io/x//y",\n'
               b'  "Dependencies": [ ],\n'
               b'}\n')
        pm = self._parser().parse(raw, "manifest.json")
        self.assertEqual(pm.uid, "a.b")
        self.assertEqual(pm.name, 'He said "hi" // not a comment')

    def test_scan_recovers_previously_false_missing_dependency(self):
        """A JSONC manifest that WAS a parse_error must now resolve and clear
        the bogus 'missing dependency' that its failed parse caused."""
        import uuid
        import shutil
        # Unique per run: a fixed name here collides with nothing in isolation
        # but is reused by a second invocation, and `rmtree` at the start of the
        # test deletes whatever the previous process left behind.
        root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            ".decky-test-tmp", "jsonc-scan-" + uuid.uuid4().hex[:8])
        os.makedirs(os.path.join(root, "Mods", "GenericModConfigMenu"), exist_ok=True)
        os.makedirs(os.path.join(root, "Mods", "BetterRanching"), exist_ok=True)
        mp = _mod_package("stardew")
        with open(os.path.join(root, "Mods", "GenericModConfigMenu", "manifest.json"),
                  "wb") as f:
            f.write(b'{\r\n /* generated */\r\n "UniqueID": "spacechase0.GenericModConfigMenu",\r\n'
                    b' "Name": "GMCM", "Author": "k", "Version": "1.16.0",\r\n'
                    b' "UpdateKeys": [ "Nexus:5098", ],\r\n}\r\n')
        with open(os.path.join(root, "Mods", "BetterRanching", "manifest.json"),
                  "wb") as f:
            f.write(b'{"UniqueID":"B.R","Name":"Better Ranching","Version":"2.0.5",'
                    b'"Dependencies":[{"UniqueID":"spacechase0.GenericModConfigMenu"}]}')
        try:
            scanned = manifest.scan_installed_mods(os.path.join(root, "Mods"), mp)
            errors = [m for m in scanned["mods"] if m.get("parse_error")]
            self.assertEqual(errors, [], "JSONC manifest must parse, not be a false error")
            self.assertEqual(scanned["missing_dependencies"], [],
                             "a present JSONC mod must NOT be reported as missing")
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
