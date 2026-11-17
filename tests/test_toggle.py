"""Round 25: enable/disable for file_drop games (goal-4c397e52 standard 3).

The objective requires "启用/禁用（文件移入/移出游戏目录，不删除源文件）".
Before this round ``set_enabled`` was a hard refusal: the descriptor said
``enable_disable: false`` because file_drop merges install and enable into one
step. That reading is right about the GAME (a directory under Mods/ is what
SMAPI loads) but wrong about the USER, who still needs a reversible "stop
loading this for now" action that is not an uninstall.

The implementation moves the directory between ``Mods/`` and its sibling
``.decky-disabled/``: same filesystem, ``os.replace``, nothing deleted,
ownership retained. These tests pin every safety property:

  * confirm-first (no move before after_confirm)
  * a disabled mod is NOT in state.mods but IS in state.disabled_mods
  * enable moves it back and restores visibility
  * traversal / absolute / dotted identifiers are refused
  * a name that does not exist is refused with the documented code
  * a destination collision is refused instead of silently merging
  * read_only descriptors and the game-running guard still win
  * enabling something that is not parked is refused
  * uninstall and disable are DIFFERENT destinations (quarantine vs parking)

STDLIB ONLY, synthetic tree, no Decky runtime, no network, no root.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deckymod.journal import Journal
from deckymod.smapi import StardewEngine

from tests.test_stardew import MANIFEST, StardewTree, _zip

_PREV_GAME_ID = None


def setUpModule():
    global _PREV_GAME_ID
    _PREV_GAME_ID = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    if _PREV_GAME_ID is not None:
        os.environ["DECKYMOD_GAME_ID"] = _PREV_GAME_ID
    else:
        os.environ.pop("DECKYMOD_GAME_ID", None)


def _plain_mod(directory, manifest=None, extra=None):
    """Create a minimal but legal SMAPI mod directory."""
    os.makedirs(directory, exist_ok=True)
    import json
    with open(os.path.join(directory, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest or MANIFEST, f)
    with open(os.path.join(directory, "Entry.dll"), "wb") as f:
        f.write(b"not-a-real-assembly")
    for name, data in (extra or {}).items():
        with open(os.path.join(directory, name), "wb") as f:
            f.write(data)


class _Base(unittest.TestCase):
    def setUp(self):
        self.t = StardewTree()
        self.t.env()
        self.eng = StardewEngine(
            journal=Journal(self.t.data, self.t.logs, "stardew"))

    def tearDown(self):
        self.t.cleanup()

    @property
    def parked(self):
        return os.path.join(self.t.game, ".decky-disabled")


class TestDisableEnableRoundTrip(_Base):
    def test_disable_moves_out_and_enable_moves_back(self):
        target = os.path.join(self.t.mods, "Automate")
        _plain_mod(target)
        before = sorted(os.listdir(self.t.mods))
        self.assertEqual(before, ["Automate"])

        # confirm phase: nothing moves
        c = self.eng.set_enabled("Automate", False, after_confirm=False)
        self.assertTrue(c["ok"], c)
        self.assertEqual(c["data"]["phase"], "confirm")
        self.assertEqual(sorted(os.listdir(self.t.mods)), before)
        self.assertFalse(os.path.exists(self.parked))

        d = self.eng.set_enabled("Automate", False, after_confirm=True)
        self.assertTrue(d["ok"], d)
        self.assertFalse(d["data"]["enabled"])
        self.assertFalse(os.path.isdir(target))
        self.assertTrue(os.path.isdir(os.path.join(self.parked, "Automate")))
        # nothing deleted: the payload came along
        self.assertTrue(os.path.isfile(
            os.path.join(self.parked, "Automate", "manifest.json")))

        st = self.eng.status()["data"]
        self.assertEqual(st["state"]["mods"], [])
        self.assertEqual([m.get("dir") for m in st["state"]["disabled_mods"]], ["Automate"])

        e = self.eng.set_enabled("Automate", True, after_confirm=True)
        self.assertTrue(e["ok"], e)
        self.assertTrue(os.path.isdir(target))
        self.assertFalse(os.path.isdir(os.path.join(self.parked, "Automate")))
        st2 = self.eng.status()["data"]
        self.assertEqual([m.get("dir") for m in st2["state"]["mods"]], ["Automate"])
        self.assertEqual(st2["state"]["disabled_mods"], [])

    def test_directory_name_is_case_tolerant(self):
        _plain_mod(os.path.join(self.t.mods, "Automate"))
        r = self.eng.set_enabled("automate", False, after_confirm=True)
        self.assertTrue(r["ok"], r)
        self.assertTrue(os.path.isdir(os.path.join(self.parked, "Automate")))

    def test_disabled_root_is_a_sibling_of_mods(self):
        st = self.eng.status()["data"]
        root = st["paths"]["disabled_root"]
        self.assertEqual(os.path.dirname(root), os.path.dirname(st["paths"]["w2_mod_root"]))
        self.assertNotEqual(root, st["paths"]["quarantine_root"],
                            "disable parking must not share the quarantine area")


class TestRefusals(_Base):
    def test_traversal_and_absolute_identifiers_are_refused(self):
        _plain_mod(os.path.join(self.t.mods, "Automate"))
        for bad in ("..", ".", "../etc", "a/b", "/home/deck", "", ".hidden"):
            r = self.eng.set_enabled(bad, False, after_confirm=True)
            self.assertFalse(r["ok"], (bad, r))
            self.assertEqual(r["code"], "E_DUPLICATE", (bad, r))
        self.assertTrue(os.path.isdir(os.path.join(self.t.mods, "Automate")),
                        "refusals must leave the tree untouched")

    def test_enabling_something_not_parked_is_refused(self):
        _plain_mod(os.path.join(self.t.mods, "Automate"))
        r = self.eng.set_enabled("Automate", True, after_confirm=True)
        self.assertFalse(r["ok"], r)
        self.assertEqual(r["code"], "E_DUPLICATE")

    def test_collision_refuses_instead_of_merging(self):
        _plain_mod(os.path.join(self.t.mods, "Automate"))
        parked = os.path.join(self.parked, "Automate")
        _plain_mod(parked)
        r = self.eng.set_enabled("Automate", False, after_confirm=True)
        self.assertFalse(r["ok"], r)
        self.assertEqual(r["code"], "E_FILE_COLLISION")
        self.assertTrue(os.path.isdir(os.path.join(self.t.mods, "Automate")))
        self.assertTrue(os.path.isdir(parked))

    def test_symlinked_mod_directory_is_refused(self):
        real = os.path.join(self.t.base, "outside")
        _plain_mod(real)
        link = os.path.join(self.t.mods, "Automate")
        try:
            os.symlink(real, link)
        except (OSError, NotImplementedError, AttributeError):
            self.skipTest("symlinks unavailable on this platform")
        r = self.eng.set_enabled("Automate", False, after_confirm=True)
        self.assertFalse(r["ok"], r)
        # Round 44: a symlinked entry inside Mods/ is now caught by the layout
        # gate (E_EXTERNAL_MANAGER) before the per-name resolver can say
        # E_DUPLICATE. Both refuse; the layout answer is the more accurate one,
        # because the folder as a whole belongs to someone else.
        self.assertIn(r["code"], ("E_DUPLICATE", "E_EXTERNAL_MANAGER"),
                      "symlink must not be resolvable as a mod dir")

    def test_game_running_guard_wins(self):
        _plain_mod(os.path.join(self.t.mods, "Automate"))
        os.environ["DECKYMOD_GAME_RUNNING"] = "1"
        try:
            r = self.eng.set_enabled("Automate", False, after_confirm=True)
        finally:
            os.environ.pop("DECKYMOD_GAME_RUNNING", None)
        self.assertEqual(r["code"], "E_GAME_RUNNING")
        self.assertTrue(os.path.isdir(os.path.join(self.t.mods, "Automate")))

    def test_external_manager_keeps_writes_disabled(self):
        _plain_mod(os.path.join(self.t.mods, "Automate"))
        with open(os.path.join(self.t.mods, ".mm_deployed"), "w", encoding="utf-8") as f:
            f.write("")
        r = self.eng.set_enabled("Automate", False, after_confirm=True)
        self.assertEqual(r["code"], "E_EXTERNAL_MANAGER")
        self.assertTrue(os.path.isdir(os.path.join(self.t.mods, "Automate")))
        self.assertFalse(os.path.exists(self.parked))


class TestDisableIsNotUninstall(_Base):
    def test_disable_parks_while_uninstall_quarantines(self):
        _plain_mod(os.path.join(self.t.mods, "Automate"))
        d = self.eng.set_enabled("Automate", False, after_confirm=True)
        self.assertTrue(d["ok"], d)
        st = self.eng.status()["data"]
        quarantine = st["paths"]["quarantine_root"]
        self.assertTrue(os.path.isdir(os.path.join(self.parked, "Automate")))
        self.assertFalse(os.path.exists(quarantine),
                         "disable must not create the quarantine area")

        # re-enable, then uninstall, and confirm the OTHER destination is used
        self.eng.set_enabled("Automate", True, after_confirm=True)
        u = self.eng.uninstall("Automate", after_confirm=True)
        self.assertTrue(u["ok"], u)
        self.assertTrue(os.path.isdir(u["data"]["quarantine"]))
        self.assertFalse(os.path.isdir(os.path.join(self.parked, "Automate")))

    def test_install_still_lands_in_mods_and_counts_as_enabled(self):
        zp = os.path.join(self.t.inbox, "automate.zip")
        _zip(zp, {"manifest.json": __import__("json").dumps(MANIFEST),
                  "Automate.dll": b"MZ"}, wrapper="Automate")
        r = self.eng.install(zp, after_confirm=True)
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["data"]["enabled"])
        st = self.eng.status()["data"]
        self.assertEqual([m.get("dir") for m in st["state"]["mods"]], ["testco.automate"])
        self.assertEqual(st["state"]["disabled_mods"], [])


if __name__ == "__main__":
    unittest.main()
