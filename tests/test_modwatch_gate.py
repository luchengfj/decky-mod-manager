"""Round 44: the write gate must actually consume the layout survey.

`tests/test_modwatch.py` proves the survey's decisions against faked primitives.
This file proves the opposite direction: a real engine, a real tree, and the real
error the user would see. Windows refuses `os.symlink` without developer mode
(`WinError 1314`), so the symlink cases here skip on this machine -- they are the
ones that will run on the Deck, which is where they matter.
"""

import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deckymod.journal import Journal  # noqa: E402
from deckymod.smapi import StardewEngine  # noqa: E402
from tests.test_stardew import StardewTree, _make_stardew_zip  # noqa: E402


def setUpModule():
    """Un-pin the RimWorld regression pin that tests/test_mvp.py sets.

    ``tests/test_mvp.py`` calls ``os.environ.setdefault("DECKYMOD_GAME_ID",
    "rimworld")`` so its 33 historical cases keep running against the old
    descriptor. Every stardew module must save and clear the variable, otherwise
    discovery order decides whether this file tests Stardew or RimWorld.
    """
    global _SAVED
    _SAVED = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    os.environ.pop("DECKYMOD_GAME_ID", None)
    if _SAVED is not None:
        os.environ["DECKYMOD_GAME_ID"] = _SAVED


def _first_zip(tree):
    for name in sorted(os.listdir(tree.inbox)):
        if name.endswith(".zip"):
            return os.path.join(tree.inbox, name)
    raise AssertionError("no zip in the inbox")


class TestLayoutGate(unittest.TestCase):
    def setUp(self):
        self.t = StardewTree()
        self.t.env()
        self.addCleanup(self.t.cleanup)
        self.eng = StardewEngine(journal=Journal(self.t.data, self.t.logs, "stardew"))
        _make_stardew_zip(os.path.join(self.t.inbox, "Gate.zip"))

    def test_a_plain_mods_dir_is_not_read_only(self):
        st = self.eng.status()
        self.assertTrue(st["ok"], st)
        state = st["data"]["state"]
        self.assertFalse(state["read_only"], state.get("layout"))
        self.assertEqual(state["layout"]["reasons"], [])

    def test_a_missing_mods_dir_is_not_treated_as_foreign(self):
        """Refusing here would make a clean first install impossible."""
        shutil.rmtree(self.t.mods, ignore_errors=True)
        st = self.eng.status()
        self.assertTrue(st["ok"], st)
        state = st["data"]["state"]
        self.assertFalse(state["read_only"], state.get("layout"))
        self.assertIn("mods_dir_missing", state["layout"]["reasons"])

    def test_hand_copied_plain_folders_keep_working(self):
        """A user who unzips by hand must not be locked out."""
        d = os.path.join(self.t.mods, "ByHand")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as f:
            f.write('{"UniqueID": "by.hand", "Name": "ByHand", "Version": "1.0.0"}')
        st = self.eng.status()
        self.assertTrue(st["ok"], st)
        self.assertFalse(st["data"]["state"]["read_only"])
        self.assertEqual(st["data"]["state"]["layout"]["reasons"], [])

    def test_symlinked_mods_dir_refuses_install(self):
        """The case the marker list could never see: the FOLDER is a link."""
        mods = self.t.mods
        real = mods + "-real"
        os.rename(mods, real)
        try:
            os.symlink(real, mods, target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError) as e:
            os.rename(real, mods)
            self.skipTest("symlinks unavailable here: %s" % e)
        try:
            st = self.eng.status()
            self.assertTrue(st["ok"], st)
            self.assertTrue(st["data"]["state"]["read_only"])
            self.assertIn("mods_dir_is_symlink", st["data"]["state"]["layout"]["reasons"])
            r = self.eng.install(_first_zip(self.t), after_confirm=True)
            self.assertFalse(r["ok"], r)
            self.assertEqual(r["code"], "E_EXTERNAL_MANAGER")
            self.assertIn("symlink", r["detail"])
        finally:
            os.unlink(mods)
            os.rename(real, mods)

    def test_symlinked_entry_refuses_and_names_it(self):
        """A deployed-per-mod tree: one entry inside Mods/ is a link."""
        target = os.path.join(self.t.base, "elsewhere")
        os.makedirs(target, exist_ok=True)
        link = os.path.join(self.t.mods, "LinkedMod")
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError) as e:
            self.skipTest("symlinks unavailable here: %s" % e)
        try:
            st = self.eng.status()
            self.assertTrue(st["ok"], st)
            layout = st["data"]["state"]["layout"]
            self.assertTrue(st["data"]["state"]["read_only"], layout)
            self.assertIn("symlinked_entry", layout["reasons"])
            self.assertIn("LinkedMod", layout["symlinked"])
            r = self.eng.set_enabled("Some.Mod", True, after_confirm=True)
            self.assertFalse(r["ok"], r)
            self.assertEqual(r["code"], "E_EXTERNAL_MANAGER")
            self.assertIn("LinkedMod", r["detail"])
        finally:
            if os.path.islink(link):
                os.unlink(link)


if __name__ == "__main__":
    unittest.main()
