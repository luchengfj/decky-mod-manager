"""Round 67: a dependency that is INSTALLED but TOO OLD is not reported.

Device evidence (synthetic tree, deployed plugin):

    DEP_INSTALL_OK   True                    # probe.thedep  1.0.0
    HOST_INSTALL_OK  True                    # probe.thehost needs >= 2.0.0
    MISSING          []
    PARKED           []
    HOST_SAYS_MISSING []
    DEP_VERSION      1.0.0

SMAPI skips the host outright in this state ("requires probe.thedep 2.0.0 or
later, but you have 1.0.0"), so the panel was calling a mod that will never
load "installed" and "nothing missing".

Why this is a THIRD list and not a fourth kind of missing
---------------------------------------------------------
Three different states, three different remedies:

    missing_dependencies   -- nobody on disk provides it  -> download it
    parked_dependencies    -- the user switched it off    -> enable it
    outdated_dependencies  -- there, but older than asked -> update it

Collapsing ``outdated`` into ``missing`` would make the fetcher download a mod
the user already owns (round 66's harm, one step over), and would hide from the
panel that the user already has the thing and only needs a newer copy.

The version comparison is deliberately conservative: if either side has no
readable version, the pair is NOT reported. "I cannot tell" must not be
rendered as "yours is wrong" -- the same rule the process scan (round 50) and
the quarantine audit (round 48) follow for unreadable inputs.
"""

import json
import os
import re
import shutil
import unittest
import uuid
import zipfile

import deckymod.manifest as manifest_mod
from deckymod.journal import Journal
from deckymod.smapi import StardewEngine

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP_ROOT = os.path.join(_ROOT, ".decky-test-tmp")

DEP_UID = "probe.thedep"
HOST_UID = "probe.thehost"

_SAVED_GAME_ID = None


def setUpModule():
    global _SAVED_GAME_ID
    _SAVED_GAME_ID = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    global _SAVED_GAME_ID
    if _SAVED_GAME_ID is not None:
        os.environ["DECKYMOD_GAME_ID"] = _SAVED_GAME_ID
    else:
        os.environ.pop("DECKYMOD_GAME_ID", None)
    _SAVED_GAME_ID = None


def _tmpdir(tag):
    os.makedirs(_TMP_ROOT, exist_ok=True)
    base = os.path.join(_TMP_ROOT, "r67_%s_%s" % (tag, uuid.uuid4().hex[:8]))
    os.makedirs(base, exist_ok=False)
    return base


def _make_zip(path, uid, name, version="1.0.0", needs=None):
    """``needs`` is [(dep_uid, minimum_version_or_None)]."""
    duck = uid.split(".")[-1].capitalize() + ".dll"
    data = {
        "Name": name,
        "Author": "probe",
        "Version": version,
        "UniqueID": uid,
        "EntryDll": duck,
        "MinimumApiVersion": "4.0.0",
    }
    if needs:
        rows = []
        for dep, minimum in needs:
            row = {"UniqueID": dep, "IsRequired": True}
            if minimum:
                row["MinimumVersion"] = minimum
            rows.append(row)
        data["Dependencies"] = rows
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Pkg/manifest.json", json.dumps(data))
        z.writestr("Pkg/" + duck, b"MZ")
    return path


class _Tree(object):
    """A synthetic Steam library with SMAPI present, no real game."""

    def __init__(self):
        self.base = _tmpdir("tree")
        home = os.path.join(self.base, "home")
        xdg = os.path.join(home, ".config")
        self.steam = os.path.join(self.base, "Steam")
        sapps = os.path.join(self.steam, "steamapps")
        self.game = os.path.join(sapps, "common", "Stardew Valley")
        self.mods = os.path.join(self.game, "Mods")
        self.data = os.path.join(self.base, "data")
        self.inbox = os.path.join(self.data, "inbox")
        self.logs = os.path.join(self.base, "logs")
        for d in (xdg, sapps, self.game, self.mods, self.inbox, self.data, self.logs):
            os.makedirs(d, exist_ok=True)
        with open(os.path.join(sapps, "libraryfolders.vdf"), "w",
                  encoding="utf-8") as f:
            f.write('"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n'
                    % self.steam.replace("\\", "\\\\"))
        with open(os.path.join(sapps, "appmanifest_413150.acf"), "w",
                  encoding="utf-8") as f:
            f.write('"AppState"\n{\n\t"appid"\t\t"413150"\n'
                    '\t"installdir"\t\t"Stardew Valley"\n\t"StateFlags"\t\t"4"\n}\n')
        with open(os.path.join(self.game, "StardewModdingAPI"), "w",
                  encoding="utf-8") as f:
            f.write("#!/bin/sh\n")
        os.makedirs(os.path.join(self.game, "smapi-internal"), exist_ok=True)
        userdata = os.path.join(self.steam, "userdata", "123", "config")
        os.makedirs(userdata, exist_ok=True)
        with open(os.path.join(userdata, "localconfig.vdf"), "w",
                  encoding="utf-8") as f:
            f.write('"UserLocalConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n'
                    '\t\t{\n\t\t\t"Steam"\n\t\t\t{\n\t\t\t\t"apps"\n\t\t\t\t{\n'
                    '\t\t\t\t\t"413150"\n\t\t\t\t\t{\n'
                    '\t\t\t\t\t\t"LaunchOptions"\t\t"\\"%s/StardewModdingAPI\\" '
                    '%%command%%"\n\t\t\t\t\t}\n\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n'
                    % self.game.replace("\\", "\\\\"))
        self._saved = {k: os.environ.get(k) for k in (
            "DECKYMOD_STEAM_ROOT", "DECKY_USER_HOME", "XDG_CONFIG_HOME",
            "DECKYMOD_DATA", "DECKYMOD_INBOX", "DECKY_PLUGIN_LOG_DIR",
            "DECKYMOD_GAME_RUNNING", "DECKYMOD_GAME_ID")}
        os.environ["DECKYMOD_STEAM_ROOT"] = self.steam
        os.environ["DECKY_USER_HOME"] = home
        os.environ["XDG_CONFIG_HOME"] = xdg
        os.environ["DECKYMOD_DATA"] = self.data
        os.environ["DECKYMOD_INBOX"] = self.inbox
        os.environ["DECKY_PLUGIN_LOG_DIR"] = self.logs
        for k in ("DECKYMOD_GAME_RUNNING", "DECKYMOD_GAME_ID"):
            os.environ.pop(k, None)

    def engine(self):
        return StardewEngine(journal=Journal(self.data, self.logs, "stardew"))

    def cleanup(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.base, ignore_errors=True)


class TestAnInstalledDependencyCanStillBeTooOld(unittest.TestCase):

    def setUp(self):
        self.t = _Tree()
        self.eng = self.t.engine()
        self.addCleanup(self.t.cleanup)

    def _install(self, zp):
        res = self.eng.install(zp, after_confirm=True)
        self.assertTrue(res["ok"], res)
        return os.path.basename(res["data"]["dir"])

    def _state(self):
        return self.eng.status()["data"]["state"]

    def _row(self, state, uid):
        for m in state["mods"]:
            if m.get("uniqueId") == uid:
                return m
        return None

    def _zip(self, tag, uid, name, version, needs=None):
        return _make_zip(os.path.join(self.t.inbox, tag + ".zip"),
                         uid, name, version, needs)

    def test_a_new_enough_dependency_is_quiet(self):
        self._install(self._zip("dep", DEP_UID, "The Dep", "2.0.0"))
        self._install(self._zip("host", HOST_UID, "The Host", "1.0.0",
                                needs=[(DEP_UID, "2.0.0")]))
        st = self._state()
        self.assertEqual(st["outdated_dependencies"], [])
        self.assertEqual(st["missing_dependencies"], [])
        self.assertEqual(self._row(st, HOST_UID)["outdated_dependencies"], [])

    def test_an_older_dependency_is_reported_not_silent(self):
        self._install(self._zip("dep", DEP_UID, "The Dep", "1.0.0"))
        self._install(self._zip("host", HOST_UID, "The Host", "1.0.0",
                                needs=[(DEP_UID, "2.0.0")]))
        st = self._state()
        self.assertEqual(
            st["outdated_dependencies"],
            [{"from": HOST_UID, "id": DEP_UID,
              "required": "2.0.0", "installed": "1.0.0"}],
            "SMAPI skips the host when its dependency is too old; the panel "
            "must not call that state healthy")
        row = self._row(st, HOST_UID)
        self.assertEqual(row["outdated_dependencies"],
                         [{"id": DEP_UID, "required": "2.0.0",
                           "installed": "1.0.0"}])
        # and it is NOT a missing dependency: the user already has it
        self.assertEqual(st["missing_dependencies"], [])
        self.assertEqual(row["missing_dependencies"], [])

    def test_the_fetcher_is_not_asked_to_download_what_is_already_here(self):
        """``main.py`` feeds ``missing_dependencies`` to ``deps.run``.

        An outdated dependency is present, so it must never appear there --
        downloading it would overwrite a folder the user owns (round 66).
        """
        self._install(self._zip("dep", DEP_UID, "The Dep", "1.0.0"))
        self._install(self._zip("host", HOST_UID, "The Host", "1.0.0",
                                needs=[(DEP_UID, "2.0.0")]))
        self.assertEqual(list(self._state()["missing_dependencies"]), [])

    def test_a_dependency_version_with_a_trailing_zero_is_equal(self):
        self._install(self._zip("dep", DEP_UID, "The Dep", "2.0.0.0"))
        self._install(self._zip("host", HOST_UID, "The Host", "1.0.0",
                                needs=[(DEP_UID, "2.0")]))
        self.assertEqual(self._state()["outdated_dependencies"], [],
                         "'2.0' and '2.0.0.0' are the same version to a mod author")

    def test_an_unreadable_version_is_neither_here_nor_there(self):
        """A manifest whose version has no digits must not read as outdated."""
        dep_dir = self._install(self._zip("dep", DEP_UID, "The Dep", "1.0.0"))
        self._install(self._zip("host", HOST_UID, "The Host", "1.0.0",
                                needs=[(DEP_UID, "2.0.0")]))
        # rewrite the installed dependency's version to something unorderable
        mpath = os.path.join(self.t.mods, dep_dir, "manifest.json")
        with open(mpath, "r", encoding="utf-8") as f:
            m = json.load(f)
        m["Version"] = "snapshot"
        with open(mpath, "w", encoding="utf-8") as f:
            json.dump(m, f)
        self.assertEqual(self._state()["outdated_dependencies"], [],
                         "cannot-tell must not be rendered as outdated")

    def test_a_removed_dependency_is_missing_not_outdated(self):
        dep_dir = self._install(self._zip("dep", DEP_UID, "The Dep", "1.0.0"))
        self._install(self._zip("host", HOST_UID, "The Host", "1.0.0",
                                needs=[(DEP_UID, "2.0.0")]))
        self.assertEqual(len(self._state()["outdated_dependencies"]), 1)
        res = self.eng.uninstall(dep_dir, after_confirm=True)
        self.assertTrue(res["ok"], res)
        st = self._state()
        self.assertEqual(st["outdated_dependencies"], [],
                         "gone is not old")
        self.assertEqual(st["missing_dependencies"], [DEP_UID])

    def test_a_parked_dependency_is_parked_not_outdated(self):
        dep_dir = self._install(self._zip("dep", DEP_UID, "The Dep", "1.0.0"))
        self._install(self._zip("host", HOST_UID, "The Host", "1.0.0",
                                needs=[(DEP_UID, "2.0.0")]))
        self.assertTrue(self.eng.set_enabled(dep_dir, False,
                                             after_confirm=True)["ok"])
        st = self._state()
        self.assertEqual(st["outdated_dependencies"], [],
                         "the remedy for a parked mod is enable, not update")
        self.assertEqual(st["parked_dependencies"], [DEP_UID])


class TestTheParsedMinimumComesFromTheDescriptor(unittest.TestCase):
    """The game field name must live in the descriptor, not in this module."""

    def _parser(self):
        return manifest_mod.parser_for({
            "parser": "json_map",
            "manifest_globs": ["manifest.json"],
            "required_manifest_fields": ["UniqueID", "Name", "Version"],
            "field_map": {
                "id": "UniqueID", "name": "Name", "version": "Version",
                "dependencies": ["Dependencies"],
                "dependency_id_keys": ["UniqueID"],
                "dependency_optional_key": "IsRequired",
                "dependency_minimum_key": "NeedsAtLeast",
            },
        })

    def test_a_declared_minimum_is_parsed(self):
        raw = json.dumps({
            "UniqueID": "a.host", "Name": "Host", "Version": "1.0.0",
            "Dependencies": [
                {"UniqueID": "a.dep", "NeedsAtLeast": "3.1.4"},
                {"UniqueID": "a.opt", "IsRequired": False, "NeedsAtLeast": "1"},
            ],
        }).encode("utf-8")
        pm = self._parser().parse(raw, "manifest.json")
        self.assertEqual(pm.dependency_minimums, {"a.dep": "3.1.4"})

    def test_no_minimum_key_declared_means_no_minimums(self):
        p = manifest_mod.parser_for({
            "parser": "json_map",
            "manifest_globs": ["manifest.json"],
            "required_manifest_fields": ["UniqueID", "Name", "Version"],
            "field_map": {"id": "UniqueID", "name": "Name",
                          "version": "Version", "dependencies": ["Dependencies"],
                          "dependency_id_keys": ["UniqueID"]},
        })
        raw = json.dumps({
            "UniqueID": "a.host", "Name": "Host", "Version": "1.0.0",
            "Dependencies": [{"UniqueID": "a.dep", "MinimumVersion": "9"}],
        }).encode("utf-8")
        pm = p.parse(raw, "manifest.json")
        self.assertEqual(pm.dependency_minimums, {},
                         "a descriptor that names no minimum field must not "
                         "start guessing one")
        self.assertEqual(pm.dependencies, ["a.dep"])

    def test_the_stardew_descriptor_declares_it(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(here, "registry", "games", "stardew.json")
        with open(path, "r", encoding="utf-8") as f:
            desc = json.load(f)
        self.assertEqual(
            desc["mod_package"]["field_map"].get("dependency_minimum_key"),
            "MinimumVersion")

    def test_the_scanner_reports_then_compares(self):
        src = open(os.path.join(_ROOT, "deckymod", "manifest.py"),
                   encoding="utf-8").read()
        self.assertIn('"outdated_dependencies": outdated,', src)
        self.assertIn("if have_t < want_t:", src)
        # the comparison must be guarded both ways, never one-sided
        self.assertRegex(src, r"if not want_t or not have_t:\s*\n\s*continue")


if __name__ == "__main__":
    unittest.main()
