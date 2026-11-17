"""Round 28 (criterion 3): safe, minimal FOMOD moduleconfig.xml support.

Covers the parser (single/multi groups, DTD refusal, bad XML), the choice
resolver, the member-map mapping, and an end-to-end engine install that only
writes the selected files. Everything is offline with a synthetic Steam tree.
"""
import json
import os
import sys
import unittest
import uuid
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deckymod import archive, fomod
from deckymod.smapi import StardewEngine

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP = os.path.join(_ROOT, ".decky-test-tmp")

_PREV = None


def setUpModule():
    global _PREV
    _PREV = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    if _PREV is not None:
        os.environ["DECKYMOD_GAME_ID"] = _PREV


def _tmp():
    p = os.path.join(_TMP, "fomod-" + uuid.uuid4().hex[:8])
    os.makedirs(p, exist_ok=True)
    return p


def _cfg(body):
    return ('<?xml version="1.0" encoding="utf-8"?>'
            '<module><name>Test</name><installSteps>'
            + body +
            '</installSteps></module>').encode("utf-8")


_GROUP = (
    '<installStep name="Main"><optionalFileGroups>'
    '<group name="Core" type="{gtype}"><plugins>'
    '<plugin name="Small"><description>Small texture</description>'
    '<files>{small}</files>'
    '<typeDescriptor name="Optional"><type name="Optional"/></typeDescriptor></plugin>'
    '<plugin name="Big"><description>Big texture</description>'
    '<files>{big}</files>'
    '<typeDescriptor name="Recommended"><type name="Recommended"/></typeDescriptor></plugin>'
    '</plugins></group></optionalFileGroups></installStep>'
)


def _group_cfg(gtype="SelectOne"):
    return _cfg(_GROUP.format(
        gtype=gtype,
        small='<file source="tex/small.dds" destination="tex/small.dds"/>',
        big='<file source="tex/big.dds" destination="tex/big.dds"/>'))


class TestParse(unittest.TestCase):
    def test_single_group_defaults_to_recommended(self):
        parsed = fomod.parse(_group_cfg("SelectOne"))
        self.assertEqual(len(parsed["steps"]), 1)
        g = parsed["steps"][0]["groups"][0]
        self.assertEqual(g["mode"], "single")
        self.assertEqual([o["name"] for o in g["options"]], ["Small", "Big"])
        self.assertEqual([o["name"] for o in g["options"] if o["selected"]], ["Big"])

    def test_multi_group_mode(self):
        parsed = fomod.parse(_group_cfg("SelectAny"))
        self.assertEqual(parsed["steps"][0]["groups"][0]["mode"], "multi")

    def test_options_carry_file_lists(self):
        parsed = fomod.parse(_group_cfg("SelectOne"))
        opts = parsed["steps"][0]["groups"][0]["options"]
        self.assertEqual(opts[1]["files"][0]["source"], "tex/big.dds")

    def test_dtd_is_refused(self):
        raw = b'<!DOCTYPE module [<!ENTITY x "y">]><module></module>'
        with self.assertRaises(fomod.FomodError) as cm:
            fomod.parse(raw)
        self.assertIn("UNSAFE", cm.exception.code)

    def test_broken_xml_is_readable(self):
        with self.assertRaises(fomod.FomodError) as cm:
            fomod.parse(b"<module><broken></module>")
        self.assertTrue(cm.exception.detail)

    def test_find_moduleconfig_case_and_wrapper(self):
        self.assertEqual(fomod.find_moduleconfig(["Mod/fomod/ModuleConfig.xml"]),
                         "Mod/fomod/ModuleConfig.xml")
        self.assertIsNone(fomod.find_moduleconfig(["manifest.json"]))


class TestChooseAndApply(unittest.TestCase):
    def setUp(self):
        self.parsed = fomod.parse(_group_cfg("SelectAny"))

    def test_multi_select_both(self):
        chosen = fomod.choose(self.parsed, {"0.0": ["Small", "Big"]})
        self.assertEqual({f["source"] for f in chosen["files"]},
                         {"tex/small.dds", "tex/big.dds"})

    def test_single_select_keeps_first_with_warning(self):
        single = fomod.parse(_group_cfg("SelectOne"))
        chosen = fomod.choose(single, {"0.0": ["Small", "Big"]})
        self.assertEqual([f["source"] for f in chosen["files"]], ["tex/small.dds"])
        self.assertTrue(any("single-select" in w for w in chosen["warnings"]))

    def test_unmentioned_group_uses_default(self):
        chosen = fomod.choose(self.parsed, {})
        self.assertEqual([f["source"] for f in chosen["files"]], ["tex/big.dds"])

    def test_apply_maps_members_and_destination(self):
        info = {"members": {"tex/small.dds": {"orig": "tex/small.dds", "size": 1},
                            "tex/big.dds": {"orig": "tex/big.dds", "size": 2}}}
        chosen = fomod.choose(self.parsed, {"0.0": ["Small"]})
        applied = fomod.apply_to_members(info, chosen["files"])
        self.assertEqual(list(applied["members"]), ["tex/small.dds"])

    def test_unsafe_destination_is_skipped(self):
        parsed = fomod.parse(_cfg(
            '<installStep name="M"><optionalFileGroups><group name="G" type="SelectAny">'
            '<plugins><plugin name="Evil"><files>'
            '<file source="a.dds" destination="../escape.dds"/>'
            '</files><typeDescriptor><type name="Optional"/></typeDescriptor></plugin>'
            '</plugins></group></optionalFileGroups></installStep>'))
        with self.assertRaises(fomod.FomodError) as cm:
            fomod.choose(parsed, {"0.0": ["Evil"]})
        self.assertEqual(cm.exception.code, "FOMOD_EMPTY_SELECTION")


class TestEndToEndInstall(unittest.TestCase):
    def setUp(self):
        self.base = _tmp()
        self.data = os.path.join(self.base, "data")
        self.inbox = os.path.join(self.data, "inbox")
        os.makedirs(self.inbox)
        self.home = os.path.join(self.base, "home")
        self.steam = os.path.join(self.home, ".local", "share", "Steam")
        self.steamapps = os.path.join(self.steam, "steamapps")
        self.common = os.path.join(self.steamapps, "common")
        os.makedirs(self.common)
        game = os.path.join(self.common, "Stardew Valley")
        os.makedirs(os.path.join(game, "Mods"))
        os.makedirs(os.path.join(game, "smapi-internal"))
        with open(os.path.join(game, "StardewModdingAPI"), "wb") as f:
            f.write(b"ELF")
        with open(os.path.join(self.steamapps, "libraryfolders.vdf"), "w", encoding="utf-8") as f:
            f.write('"libraryfolders" {"0" {"path" "%s"}}' % self.steam.replace("\\", "/"))
        with open(os.path.join(self.steamapps, "appmanifest_413150.acf"), "w", encoding="utf-8") as f:
            f.write('"AppState" {"appid" "413150" "name" "Stardew Valley" '
                    '"installdir" "Stardew Valley" "StateFlags" "4"}')
        os.environ["DECKY_USER_HOME"] = self.home
        os.environ["DECKYMOD_STEAM_ROOT"] = self.steam
        os.environ["DECKYMOD_DATA"] = self.data
        os.environ["DECKYMOD_INBOX"] = self.inbox
        os.environ["XDG_CONFIG_HOME"] = os.path.join(self.base, "xdg")
        os.environ["DECKY_PLUGIN_RUNTIME_DIR"] = self.data
        os.environ["DECKYMOD_GAME_RUNNING"] = ""
        self.mods = os.path.join(game, "Mods")

    def tearDown(self):
        for k in ("DECKY_USER_HOME", "DECKYMOD_STEAM_ROOT", "DECKYMOD_DATA",
                  "DECKYMOD_INBOX", "DECKY_PLUGIN_RUNTIME_DIR",
                  "DECKYMOD_GAME_RUNNING"):
            os.environ.pop(k, None)

    def _archive(self):
        p = os.path.join(self.inbox, "fomodmod.zip")
        manifest = {"UniqueID": "Test.FomodMod", "Name": "Fomod Mod",
                    "Version": "1.0.0", "MinimumApiVersion": "4.0.0",
                    "EntryDll": "Mod.dll"}
        with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps(manifest))
            z.writestr("Mod.dll", b"MZ" + b"\x00" * 100)
            z.writestr("tex/small.dds", b"SMALL")
            z.writestr("tex/big.dds", b"BIGG" * 4)
            z.writestr("fomod/moduleconfig.xml", _group_cfg("SelectAny"))
        return p

    def test_inspect_exposes_fomod_and_install_selects_files(self):
        p = self._archive()
        e = StardewEngine()
        rep = e.inspect(p)
        self.assertTrue(rep["ok"], rep)
        fd = rep["data"]["fomod"]
        self.assertTrue(fd["present"] and fd["usable"])
        self.assertEqual(fd["steps"][0]["groups"][0]["options"][1]["name"], "Big")
        # choose only the small texture; manifest must be retained for verify
        r = e.install(p, after_confirm=True, fomod_choices={"0.0": ["Small"]})
        self.assertTrue(r["ok"], r)
        target = os.path.join(self.mods, "test.fomodmod")
        self.assertTrue(os.path.isfile(os.path.join(target, "manifest.json")))
        self.assertTrue(os.path.isfile(os.path.join(target, "tex", "small.dds")))
        self.assertFalse(os.path.exists(os.path.join(target, "tex", "big.dds")))

    def test_bad_choice_falls_back_to_plain_extract(self):
        p = self._archive()
        e = StardewEngine()
        # An unknown option in the real group yields an empty selection, which
        # the resolver rejects with a readable error -> plain extract + warning.
        r = e.install(p, after_confirm=True, fomod_choices={"0.0": ["NoSuchOption"]})
        self.assertTrue(r["ok"], r)
        self.assertTrue(any("fell back" in w for w in r["data"].get("fomod_warnings", [])), r)
        target = os.path.join(self.mods, "test.fomodmod")
        # plain extract contains everything
        self.assertTrue(os.path.isfile(os.path.join(target, "tex", "small.dds")))
        self.assertTrue(os.path.isfile(os.path.join(target, "tex", "big.dds")))

    def test_unparseable_config_is_reported_and_falls_back(self):
        p = os.path.join(self.inbox, "badfomod.zip")
        manifest = {"UniqueID": "Test.BadFomod", "Name": "Bad",
                    "Version": "1.0.0", "MinimumApiVersion": "4.0.0", "EntryDll": "Mod.dll"}
        with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps(manifest))
            z.writestr("Mod.dll", b"MZ" + b"\x00" * 100)
            z.writestr("fomod/moduleconfig.xml", b"<module><broken>")
        e = StardewEngine()
        rep = e.inspect(p)
        self.assertTrue(rep["ok"], rep)
        fd = rep["data"]["fomod"]
        self.assertTrue(fd["present"])
        self.assertFalse(fd["usable"])
        self.assertTrue(fd.get("reason"))
        r = e.install(p, after_confirm=True, fomod_choices={"0.0": ["Anything"]})
        self.assertTrue(r["ok"], r)
        self.assertTrue(os.path.isfile(os.path.join(self.mods, "test.badfomod", "Mod.dll")))


if __name__ == "__main__":
    unittest.main()
