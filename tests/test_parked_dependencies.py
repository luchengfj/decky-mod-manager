"""Round 66: a DISABLED dependency is not a MISSING dependency.

Device evidence (synthetic tree, deployed plugin, real ``deps.run`` with the
network calls injected):

    PARKED_VERSION_BEFORE   1.0.0            # probe.thedep, parked on purpose
    FETCH_INSTALLED         1                # deps.run "resolved" it
    PARKED_VERSION_AFTER    1.1.0            # the parked copy was REPLACED
    MISSING_AFTER           ['probe.thedep'] # and still reported as missing

Two harms in one call: the plugin overwrote a mod the user had deliberately
switched off, and then told the user it was still missing -- so the panel
reports failure after mutating user data, and the "download dependencies"
button stays lit.

Why the two lists must be separate
----------------------------------
``.decky-disabled/`` is a *sibling* of ``Mods/`` and ``scan_installed_mods``
only walks the root it is given, so a parked dependency is invisible to the
active scan. Before this round it therefore fell into ``missing_dependencies``,
which is exactly the list handed to ``deps.run``. The truth is subtler: the mod
IS installed (present, owned, visible in the panel) and the user turned it off.
The game genuinely will not load it, so the requirement is not satisfied -- but
the remedy is one tap ("enable it"), not a download.

So the engine reports:
    missing_dependencies  -- ids nobody on disk provides (download candidate)
    parked_dependencies   -- ids the user owns but has disabled (enable them)

and only the first one feeds the fetcher.
"""

import json
import os
import shutil
import unittest
import uuid
import zipfile

import deckymod.manifest as manifest_mod
from deckymod import deps
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
    base = os.path.join(_TMP_ROOT, "r66_%s_%s" % (tag, uuid.uuid4().hex[:8]))
    os.makedirs(base, exist_ok=False)
    return base


def _make_zip(path, uid, name, version="1.0.0", depends=None):
    duck = uid.split(".")[-1].capitalize() + ".dll"
    data = {
        "Name": name,
        "Author": "probe",
        "Version": version,
        "UniqueID": uid,
        "EntryDll": duck,
        "MinimumApiVersion": "4.0.0",
    }
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


class TestAParkedDependencyIsNotMissing(unittest.TestCase):

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

    def _state(self):
        return self.eng.status()["data"]["state"]

    def _row(self, state, uid):
        for m in state["mods"]:
            if m.get("uniqueId") == uid:
                return m
        return None

    def test_a_present_dependency_is_missing_nowhere(self):
        self._install(self.dep_zip)
        self._install(self.host_zip)
        st = self._state()
        self.assertEqual(st["missing_dependencies"], [])
        self.assertEqual(st["parked_dependencies"], [])
        self.assertEqual(self._row(st, HOST_UID)["missing_dependencies"], [])
        self.assertEqual(self._row(st, HOST_UID)["parked_dependencies"], [])

    def test_disabling_the_dependency_moves_it_out_of_the_missing_list(self):
        dep_dir = self._install(self.dep_zip)
        self._install(self.host_zip)
        off = self.eng.set_enabled(dep_dir, False, after_confirm=True)
        self.assertTrue(off["ok"], off)

        st = self._state()
        self.assertEqual(
            st["missing_dependencies"], [],
            "a mod the user parked is owned and visible; reporting it missing "
            "is what made the fetcher replace it")
        self.assertEqual(st["parked_dependencies"], [DEP_UID])

        row = self._row(st, HOST_UID)
        self.assertEqual(row["missing_dependencies"], [],
                         "the row must not claim the dependency is absent")
        self.assertEqual(row["parked_dependencies"], [DEP_UID])

        parked_row = st["disabled_mods"][0]
        self.assertEqual(parked_row["dir"], dep_dir,
                         "the parked copy must still be the one on disk")

    def test_the_fetcher_is_never_handed_a_parked_id(self):
        """``main.py`` passes ``state['missing_dependencies']`` to ``deps.run``.

        With the dependency parked that list is empty, so the fetcher plans
        nothing at all -- which is the whole point: the parked folder cannot be
        overwritten by a download.
        """
        dep_dir = self._install(self.dep_zip)
        self._install(self.host_zip)
        self.eng.set_enabled(dep_dir, False, after_confirm=True)

        missing = list(self._state()["missing_dependencies"])
        self.assertEqual(missing, [])

        attempted = []

        def fake_fetch(repo, asset_id, filename):
            attempted.append((repo, asset_id, filename))

        got = deps.run(
            None, self.eng, missing_ids=missing, allow_install=True,
            after_confirm=True,
            lookup=lambda ids: {DEP_UID: {"gitHubRepo": "probe/dep"}},
            candidates_for=lambda repo, uid: [{"asset_id": 1, "name": "dep.zip"}],
            fetch=fake_fetch)
        self.assertTrue(got["ok"], got)
        self.assertEqual(attempted, [], "no download may start for a parked id")
        self.assertEqual(got["installed"], 0)

        # and the parked copy is byte-for-byte still the one that was there
        still = self._state()["disabled_mods"][0]
        self.assertEqual(still["version"], "1.0.0")

    def test_an_uninstalled_dependency_is_missing_again(self):
        dep_dir = self._install(self.dep_zip)
        self._install(self.host_zip)
        gone = self.eng.uninstall(dep_dir, after_confirm=True)
        self.assertTrue(gone["ok"], gone)

        st = self._state()
        self.assertEqual(
            st["missing_dependencies"], [DEP_UID],
            "once it is really gone it IS missing -- the split must not hide it")
        self.assertEqual(st["parked_dependencies"], [])
        self.assertEqual(self._row(st, HOST_UID)["missing_dependencies"], [DEP_UID])


class TestTheTwoListsComeFromOneScan(unittest.TestCase):
    """Structural pins: the split cannot be re-derived in a second place."""

    def _src(self, name):
        with open(os.path.join(_ROOT, "deckymod", name), encoding="utf-8") as f:
            return f.read()

    def test_scan_takes_the_parked_ids_as_a_parameter(self):
        src = self._src("manifest.py")
        self.assertIn("def scan_installed_mods(mod_root: str, mod_package: dict,",
                      src)
        self.assertIn("parked_ids=None", src)

    def test_the_early_return_keeps_both_keys(self):
        src = self._src("manifest.py")
        i = src.index("def scan_installed_mods(")
        body = src[i:]
        self.assertIn('"missing_dependencies": []', body)
        self.assertIn('"parked_dependencies": []', body)

    def test_status_scans_the_parked_root_first(self):
        src = self._src("smapi.py")
        i = src.index("Round 66: the parked root is scanned FIRST")
        before = src[:i]
        self.assertIn("def status(self)", before)
        # the disabled scan must be handed to the active scan as parked_ids
        tail = src[i:]
        self.assertIn("parked_ids=parked_ids", tail[:4000])

    def test_the_state_block_exposes_both_lists(self):
        src = self._src("smapi.py")
        self.assertIn('"missing_dependencies": scanned["missing_dependencies"],', src)
        self.assertIn('"parked_dependencies": scanned["parked_dependencies"],', src)

    def test_an_absent_parked_list_is_treated_as_empty(self):
        """``parked_ids`` is optional so older callers keep working."""
        self.assertIn("for x in (parked_ids or [])",
                      self._src("manifest.py"))


if __name__ == "__main__":
    unittest.main()
