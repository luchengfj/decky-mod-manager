"""Round 59: the preview must name the destination the install will use.

Rounds 57 and 58 were the same root cause twice -- in the file_drop engine
"disabled" is a LOCATION, not a flag, and several paths resolved one root only.
Round 59 asked the machine instead of waiting for the next one to surface: every
function in the two engines was scanned for which roots it mentions.

That found the remaining one. ``inspect()`` is the preview the confirm dialog is
built from, and it still computed ``targets.w2_install_dir`` as
``Mods/<dir>`` and looked for duplicates in ``Mods/`` only, while
``_install_inner`` had moved to landing parked mods in ``.decky-disabled/`` and
counting parked copies. Device probe:

    PREVIEW_TARGET        .../Mods/someone.parkinspect
    PREVIEW_DUPLICATE     True
    PREVIEW_SAME_UID_DIRS []
    REAL_DIR              .../.decky-disabled/someone.parkinspect
    PREVIEW_MATCHES_REAL  False

The dialog said one thing and the install did another. A preview that disagrees
with its execute is worse than no preview, because the user's consent was given
for the text on screen.
"""

import json
import os
import shutil
import unittest
import uuid
import zipfile

from deckymod.journal import Journal
from deckymod.smapi import StardewEngine

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP_ROOT = os.path.join(_ROOT, ".decky-test-tmp")

UID = "someone.parkinspect"
NAME = "Park Inspect"

_SAVED_GAME_ID = None


def setUpModule():
    global _SAVED_GAME_ID
    _SAVED_GAME_ID = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    if _SAVED_GAME_ID is not None:
        os.environ["DECKYMOD_GAME_ID"] = _SAVED_GAME_ID
    else:
        os.environ.pop("DECKYMOD_GAME_ID", None)


def _tmpdir(tag):
    os.makedirs(_TMP_ROOT, exist_ok=True)
    base = os.path.join(_TMP_ROOT, "r59_%s_%s" % (tag, uuid.uuid4().hex[:8]))
    os.makedirs(base, exist_ok=False)
    return base


def _zip(path, version="1.0.0", uid=UID, name=NAME):
    manifest = {
        "Name": name, "Author": "someone", "Version": version,
        "UniqueID": uid, "EntryDll": "ParkInspect.dll",
        "MinimumApiVersion": "4.0.0",
    }
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("ParkInspect/manifest.json", json.dumps(manifest))
        z.writestr("ParkInspect/ParkInspect.dll", b"MZ")
    return path


class _Tree(object):

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
        with open(os.path.join(sapps, "libraryfolders.vdf"), "w", encoding="utf-8") as f:
            f.write('"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n'
                    % self.steam.replace("\\", "\\\\"))
        with open(os.path.join(sapps, "appmanifest_413150.acf"), "w", encoding="utf-8") as f:
            f.write('"AppState"\n{\n\t"appid"\t\t"413150"\n'
                    '\t"installdir"\t\t"Stardew Valley"\n\t"StateFlags"\t\t"4"\n}\n')
        with open(os.path.join(self.game, "StardewModdingAPI"), "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n")
        os.makedirs(os.path.join(self.game, "smapi-internal"), exist_ok=True)
        ud = os.path.join(self.steam, "userdata", "123", "config")
        os.makedirs(ud, exist_ok=True)
        with open(os.path.join(ud, "localconfig.vdf"), "w", encoding="utf-8") as f:
            f.write('"UserLocalConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n'
                    '\t\t\t"Steam"\n\t\t\t{\n\t\t\t\t"apps"\n\t\t\t\t{\n'
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


class TestPreviewAgreesWithExecute(unittest.TestCase):

    def setUp(self):
        self.t = _Tree()
        self.eng = self.t.engine()
        self.zp = _zip(os.path.join(self.t.inbox, "mod.zip"))

    def tearDown(self):
        self.t.cleanup()

    def _park(self):
        res = self.eng.install(self.zp, after_confirm=True)
        self.assertTrue(res["ok"], res)
        folder = os.path.basename(res["data"]["dir"])
        off = self.eng.set_enabled(folder, False, after_confirm=True)
        self.assertTrue(off["ok"], off)
        return folder

    def test_preview_target_equals_real_destination_for_a_parked_mod(self):
        folder = self._park()
        _zip(self.zp, "2.0.0")

        preview = self.eng.inspect(self.zp)
        self.assertTrue(preview["ok"], preview)
        promised = preview["data"]["targets"]["w2_install_dir"]
        self.assertTrue(preview["data"]["conflict"]["parked"],
                        "the preview must know this mod is parked")

        real = self.eng.install(self.zp, after_confirm=True)
        self.assertTrue(real["ok"], real)
        self.assertEqual(
            promised, real["data"]["dir"],
            "the dialog promised one destination and the install used another")

        self.assertEqual(os.path.dirname(promised), self.t.parked)
        self.assertEqual(os.path.dirname(real["data"]["dir"]), self.t.parked)

    def test_the_confirm_text_names_the_real_destination(self):
        self._park()
        _zip(self.zp, "2.0.0")
        preview = self.eng.inspect(self.zp)
        text = preview["data"]["confirm_text"]
        self.assertIn(
            os.path.join(self.t.parked, "someone.parkinspect"), text,
            "the sentence the user agrees to must contain the path the install uses")
        self.assertIn("stays disabled", text,
                      "and it must say the mod remains disabled")

    def test_a_fresh_install_still_previews_mods(self):
        """No regression for the ordinary case."""
        preview = self.eng.inspect(self.zp)
        self.assertTrue(preview["ok"], preview)
        self.assertFalse(preview["data"]["conflict"]["parked"])
        self.assertEqual(
            preview["data"]["targets"]["w2_install_dir"],
            os.path.join(self.t.mods, "someone.parkinspect"))
        real = self.eng.install(self.zp, after_confirm=True)
        self.assertEqual(preview["data"]["targets"]["w2_install_dir"],
                         real["data"]["dir"])

    def test_the_preview_counts_a_parked_copy_as_a_duplicate(self):
        """A hand-placed mod parked under a different name is still a copy.

        install() refuses this; the preview has to warn about the same thing or
        the user only learns after pressing Install.
        """
        foreign = os.path.join(self.t.parked, "SomeOtherFolderName")
        os.makedirs(foreign)
        with open(os.path.join(foreign, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump({"Name": NAME, "Author": "someone", "Version": "0.9.0",
                       "UniqueID": UID, "EntryDll": "ParkInspect.dll",
                       "MinimumApiVersion": "4.0.0"}, f)

        preview = self.eng.inspect(self.zp)
        dirs = preview["data"]["conflict"]["same_unique_id_dirs"]
        self.assertTrue(
            any("SomeOtherFolderName" in d for d in dirs),
            "a parked copy with the same UniqueID must be reported: %r" % (dirs,))

        refused = self.eng.install(self.zp, after_confirm=True)
        self.assertFalse(refused["ok"], refused)
        self.assertEqual(refused["code"], "E_DUPLICATE")


if __name__ == "__main__":
    unittest.main()
