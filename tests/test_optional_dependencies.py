"""Round 27: an optional dependency must not be reported as missing.

A shipped content pack (SDV-HD2D) declares ``focustense.StardewUI`` with
``"IsRequired": false``. The parser collected every object's id regardless,
so ``status()`` flagged the mod with a missing dependency that SMAPI would
never complain about — a false warning on a perfectly good install.

The fix is descriptor-driven: ``field_map.dependency_optional_key`` names the
key, so ``manifest.py`` still hard-codes no game field name. These tests pin
the behaviour and, importantly, that the key being absent changes nothing.
"""
import json
import os
import unittest

from deckymod.manifest import JsonMapParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _config(**overrides):
    """A minimal json_map config; overrides patch the field_map."""
    cfg = {
        "manifest_globs": ["manifest.json", "*/manifest.json"],
        "json_dialect": "jsonc",
        "id_regex": r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
        "id_normalize": "lowercase_for_directory",
        "required_manifest_fields": ["UniqueID", "Name", "Version"],
        "field_map": {
            "id": "UniqueID",
            "name": "Name",
            "version": "Version",
            "author": "Author",
            "minimum_api_version": "MinimumApiVersion",
            "entry_dll": "EntryDll",
            "dependencies": ["Dependencies", "ContentPackFor"],
            "dependency_id_keys": ["UniqueID", "UniqueId", "Id", "ID", "id"],
        },
    }
    fm = overrides.pop("field_map", None)
    if fm:
        cfg["field_map"].update(fm)
    cfg.update(overrides)
    return cfg


MANIFEST = {
    "Name": "SDV-HD2D",
    "Author": "ivory",
    "Version": "0.9.1",
    "UniqueID": "ivory.SDVHD2D",
    "EntryDll": "SDV-HD2D.dll",
    "MinimumApiVersion": "4.5.2",
    "Dependencies": [
        {"UniqueID": "spacechase0.GenericModConfigMenu",
         "MinimumVersion": "1.14.0", "IsRequired": True},
        {"UniqueID": "focustense.StardewUI",
         "MinimumVersion": "0.6.1", "IsRequired": False},
    ],
}


def _parse(cfg, data=None):
    raw = json.dumps(data if data is not None else MANIFEST).encode("utf-8")
    return JsonMapParser(cfg).parse(raw, "manifest.json")


class TestOptionalDependencyIsNotMissing(unittest.TestCase):
    def test_required_only_when_descriptor_declares_the_key(self):
        pm = _parse(_config(field_map={"dependency_optional_key": "IsRequired"}))
        self.assertEqual(pm.dependencies,
                         ["spacechase0.GenericModConfigMenu"],
                         "IsRequired:false must not become a missing dependency")

    def test_all_strings_still_count_as_required(self):
        cfg = _config(field_map={"dependency_optional_key": "IsRequired"})
        data = dict(MANIFEST)
        data["Dependencies"] = ["A.One", "B.Two"]
        pm = _parse(cfg, data)
        self.assertEqual(pm.dependencies, ["A.One", "B.Two"],
                         "plain string dependencies have no flag and stay required")

    def test_null_flag_is_treated_as_required(self):
        cfg = _config(field_map={"dependency_optional_key": "IsRequired"})
        data = dict(MANIFEST)
        data["Dependencies"] = [{"UniqueID": "X.Y", "IsRequired": None},
                                {"UniqueID": "Z.W"}]
        pm = _parse(cfg, data)
        self.assertEqual(pm.dependencies, ["X.Y", "Z.W"],
                         "only an explicit false means optional")

    def test_truthy_flag_stays_required(self):
        cfg = _config(field_map={"dependency_optional_key": "IsRequired"})
        data = dict(MANIFEST)
        data["Dependencies"] = [{"UniqueID": "X.Y", "IsRequired": True}]
        self.assertEqual(_parse(cfg, data).dependencies, ["X.Y"])


class TestNoKeyMeansOldBehaviour(unittest.TestCase):
    """A descriptor that never declares the key must behave exactly as before."""

    def test_optional_entries_are_still_listed_without_the_key(self):
        pm = _parse(_config())
        self.assertEqual(pm.dependencies,
                         ["spacechase0.GenericModConfigMenu",
                          "focustense.StardewUI"])

    def test_empty_key_is_the_same_as_absent(self):
        pm = _parse(_config(field_map={"dependency_optional_key": ""}))
        self.assertEqual(len(pm.dependencies), 2)


class TestShippedDescriptorWouldPass(unittest.TestCase):
    def test_stardew_descriptor_declares_the_key(self):
        with open(os.path.join(ROOT, "registry", "games", "stardew.json"),
                  encoding="utf-8") as fh:
            d = json.load(fh)
        fm = d["mod_package"]["field_map"]
        self.assertEqual(fm.get("dependency_optional_key"), "IsRequired")

    def test_status_no_longer_flags_the_real_manifest(self):
        with open(os.path.join(ROOT, "registry", "games", "stardew.json"),
                  encoding="utf-8") as fh:
            desc = json.load(fh)
        cfg = _config(field_map=dict(desc["mod_package"]["field_map"]))
        pm = _parse(cfg)
        self.assertNotIn("focustense.StardewUI", pm.dependencies)


if __name__ == "__main__":
    unittest.main()
