"""Round 71: removing a dependency must say who needs it.

Device evidence (synthetic tree, deployed plugin), before the fix:

    DEP_INSTALL     True None
    HOST_INSTALL    True None
    MISSING         []
    PLAN_OK         True None
    CONFIRM_TEXT    "Uninstall probe.thedep? The folder is moved to quarantine (not deleted)."
    MENTIONS_HOST   False
    UNINSTALL_OK    True None
    AFTER_MISSING   ['probe.thedep']
    AFTER_ROWS      [('probe.thehost', 'probe.thehost', ['probe.thedep'])]

The uninstall succeeded, which is correct -- the folder really did move. What
the user never saw is that a second mod had just stopped loading: SMAPI skips a
mod whose required dependency is absent. The plugin knew the dependency graph
(it reports ``missing_dependencies`` on the very next status call) but asked
nobody before acting.

Why the answer belongs in the confirmation, not in a new error
-------------------------------------------------------------
The operation is legitimate and reversible. Refusing would be a new failure
mode for a normal user action (removing a library you no longer need). The
missing piece was information at the moment of choice, so it goes where the
choice is made: the confirm step of ``uninstall`` and of ``disable``.

The reverse map is computed in one place
----------------------------------------
``manifest.dependents_of()`` is the only definition; ``scan_installed_mods``
reports it per row from the pass it already does, and the engine's
``_active_dependents()`` is a thin read-only call around the same helper. A
second implementation would be a second chance to disagree -- the shape rounds
57-60 spent three rounds removing.
"""

import json
import os
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
OTHER_UID = "probe.unrelated"

_SAVED_GAME_ID = None


def setUpModule():
    # Discovery imports every test module before running any, so a module-level
    # pop() would strip test_mvp's RimWorld pin. Rounds 47, 50 and 61 each lost
    # this; the setUpModule form is the one that survives.
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
    base = os.path.join(_TMP_ROOT, "r71_%s_%s" % (tag, uuid.uuid4().hex[:8]))
    os.makedirs(base, exist_ok=False)
    return base


def _make_zip(path, uid, name, version="1.0.0", depends=None):
    duck = uid.split(".")[-1].capitalize() + ".dll"
    data = {"Name": name, "Author": "probe", "Version": version,
            "UniqueID": uid, "EntryDll": duck, "MinimumApiVersion": "4.0.0"}
    if depends:
        data["Dependencies"] = [{"UniqueID": d, "IsRequired": True} for d in depends]
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
        self.parked = os.path.join(self.game, ".decky-disabled")
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
                    '\t"installdir"\t\t"Stardew Valley"\n'
                    '\t"StateFlags"\t\t"4"\n}\n')
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


class TestTheReverseMapAnswersOnlyWhatItKnows(unittest.TestCase):

    def test_only_entries_that_declare_the_dependency_count(self):
        rows = [
            {"uniqueId": HOST_UID, "name": "The Host", "dir": "probe.thehost",
             "dependencies": [DEP_UID]},
            {"uniqueId": OTHER_UID, "name": "Unrelated", "dir": "probe.unrelated",
             "dependencies": []},
            {"uniqueId": DEP_UID, "name": "The Dep", "dir": "probe.thedep",
             "dependencies": []},
        ]
        got = manifest_mod.dependents_of(DEP_UID, rows)
        self.assertEqual([r["id"] for r in got], [HOST_UID])
        self.assertEqual(got[0]["name"], "The Host")

    def test_the_mod_itself_is_never_its_own_dependent(self):
        rows = [{"uniqueId": DEP_UID, "name": "The Dep", "dir": "probe.thedep",
                 "dependencies": [DEP_UID]}]
        self.assertEqual(manifest_mod.dependents_of(DEP_UID, rows), [])

    def test_case_and_whitespace_do_not_change_the_answer(self):
        rows = [{"uniqueId": HOST_UID, "name": "The Host", "dir": "probe.thehost",
                 "dependencies": ["  PROBE.TheDep "]}]
        self.assertEqual(len(manifest_mod.dependents_of(DEP_UID, rows)), 1)

    def test_an_empty_or_missing_id_answers_nothing(self):
        rows = [{"uniqueId": HOST_UID, "dependencies": [DEP_UID]}]
        self.assertEqual(manifest_mod.dependents_of("", rows), [])
        self.assertEqual(manifest_mod.dependents_of(None, rows), [])

    def test_the_scan_reports_the_reverse_map_per_row(self):
        t = _Tree()
        self.addCleanup(t.cleanup)
        eng = t.engine()
        dep = _make_zip(os.path.join(t.inbox, "dep.zip"), DEP_UID, "The Dep")
        host = _make_zip(os.path.join(t.inbox, "host.zip"), HOST_UID,
                         "The Host", depends=[DEP_UID])
        self.assertTrue(eng.install(dep, after_confirm=True)["ok"])
        self.assertTrue(eng.install(host, after_confirm=True)["ok"])
        st = eng.status()["data"]["state"]
        dep_row = next(m for m in st["mods"] if m.get("uniqueId") == DEP_UID)
        host_row = next(m for m in st["mods"] if m.get("uniqueId") == HOST_UID)
        self.assertEqual([r["id"] for r in dep_row["dependents"]], [HOST_UID])
        self.assertEqual(host_row["dependents"], [])


class TestTheUninstallConfirmationNamesThem(unittest.TestCase):

    def setUp(self):
        self.t = _Tree()
        self.eng = self.t.engine()
        self.addCleanup(self.t.cleanup)
        self.dep_zip = _make_zip(os.path.join(self.t.inbox, "dep.zip"),
                                 DEP_UID, "The Dep")
        self.host_zip = _make_zip(os.path.join(self.t.inbox, "host.zip"),
                                  HOST_UID, "The Host", depends=[DEP_UID])

    def _install(self, zp):
        res = self.eng.install(zp, after_confirm=True)
        self.assertTrue(res["ok"], res)
        return os.path.basename(res["data"]["dir"])

    def test_the_confirmation_says_who_will_stop_loading(self):
        dep_dir = self._install(self.dep_zip)
        self._install(self.host_zip)
        plan = self.eng.uninstall(dep_dir, after_confirm=False)["data"]
        self.assertEqual(plan["confirm_key"], "CONFIRM_UNINSTALL_WITH_DEPENDENTS")
        self.assertIn("The Host", plan["confirm_text"])
        self.assertIn("1 installed mod", plan["confirm_text"])
        self.assertEqual([d["id"] for d in plan["dependents"]], [HOST_UID])
        self.assertEqual(plan["confirm_vars"]["n"], 1)
        self.assertIn("The Host", plan["confirm_vars"]["who"])
        # the panel needs both languages to have the same key
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in ("en.json", "zh-CN.json"):
            with open(os.path.join(here, "src", "i18n", name), encoding="utf-8") as f:
                table = json.load(f)
            self.assertIn("CONFIRM_UNINSTALL_WITH_DEPENDENTS", table, name)
            for token in ("{pid}", "{n}", "{who}"):
                self.assertIn(token, table["CONFIRM_UNINSTALL_WITH_DEPENDENTS"], name)

    def test_nothing_extra_is_said_when_nothing_depends_on_it(self):
        dep_dir = self._install(self.dep_zip)
        plan = self.eng.uninstall(dep_dir, after_confirm=False)["data"]
        self.assertEqual(plan["confirm_key"], "CONFIRM_UNINSTALL")
        self.assertEqual(plan["dependents"], [])
        self.assertNotIn("stop loading", plan["confirm_text"])

    def test_a_parked_dependent_is_not_reported(self):
        # A disabled mod is already not loading, so its dependency going away
        # changes nothing today. Naming it would be noise in a confirmation.
        dep_dir = self._install(self.dep_zip)
        host_dir = self._install(self.host_zip)
        self.assertTrue(self.eng.set_enabled(host_dir, False,
                                             after_confirm=True)["ok"])
        plan = self.eng.uninstall(dep_dir, after_confirm=False)["data"]
        self.assertEqual(plan["dependents"], [])
        self.assertEqual(plan["confirm_key"], "CONFIRM_UNINSTALL")

    def test_disabling_the_dependency_warns_the_same_way(self):
        dep_dir = self._install(self.dep_zip)
        self._install(self.host_zip)
        plan = self.eng.set_enabled(dep_dir, False, after_confirm=False)["data"]
        self.assertEqual(plan["confirm_key"], "CONFIRM_DISABLE_WITH_DEPENDENTS")
        self.assertIn("The Host", plan["confirm_text"])
        self.assertEqual([d["id"] for d in plan["dependents"]], [HOST_UID])

    def test_enabling_says_nothing_about_dependents(self):
        dep_dir = self._install(self.dep_zip)
        self._install(self.host_zip)
        self.assertTrue(self.eng.set_enabled(dep_dir, False,
                                             after_confirm=True)["ok"])
        plan = self.eng.set_enabled(dep_dir, True, after_confirm=False)["data"]
        self.assertEqual(plan["confirm_key"], "CONFIRM_ENABLE")
        self.assertEqual(plan["dependents"], [])

    def test_the_whole_flow_still_completes(self):
        dep_dir = self._install(self.dep_zip)
        self._install(self.host_zip)
        res = self.eng.uninstall(dep_dir, after_confirm=True)
        self.assertTrue(res["ok"], res)
        st = self.eng.status()["data"]["state"]
        self.assertEqual(st["missing_dependencies"], [DEP_UID])
        self.assertEqual(sorted(os.listdir(self.t.mods)), ["probe.thehost"])


class TestOnePlaceAnswersTheQuestion(unittest.TestCase):

    def _source(self, rel):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, rel), encoding="utf-8") as f:
            return f.read()

    def test_the_helper_is_defined_once(self):
        man = self._source(os.path.join("deckymod", "manifest.py"))
        self.assertEqual(man.count("def dependents_of("), 1)

    def test_the_engine_calls_the_helper_rather_than_reimplementing_it(self):
        smapi = self._source(os.path.join("deckymod", "smapi.py"))
        self.assertEqual(smapi.count("manifest.dependents_of("), 1)
        body = smapi[smapi.index("def _active_dependents("):]
        body = body[:body.index("    def ", 10)]
        self.assertIn("manifest.dependents_of(", body)
        # it must not build a dependency map of its own
        for banned in ("dependencies\"]", "for d in ", "setdefault("):
            self.assertNotIn(banned, body, "reimplements the reverse map: %r" % banned)

    def test_both_confirm_sites_ask(self):
        smapi = self._source(os.path.join("deckymod", "smapi.py"))
        self.assertEqual(smapi.count("self._active_dependents("), 2)
        self.assertIn('"CONFIRM_UNINSTALL_WITH_DEPENDENTS"', smapi)
        self.assertIn('"CONFIRM_DISABLE_WITH_DEPENDENTS"', smapi)

    def test_the_scan_fills_the_field_without_a_second_walk(self):
        man = self._source(os.path.join("deckymod", "manifest.py"))
        self.assertEqual(man.count('m["dependents"] = dependents_of('), 1)


if __name__ == "__main__":
    unittest.main()
