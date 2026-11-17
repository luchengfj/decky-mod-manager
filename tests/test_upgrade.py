"""Round 56: an upgrade must be undoable.

The device probe that started this round installed 1.0.0, installed 2.0.0 over
it, then asked for a rollback and got

    nothing to roll back for txn 20261117T183305-86d7c8c8 (state=COMMITTED)

while the old version sat in the quarantine as an ORPHAN -- which is exactly
what round 54's reclaim is allowed to delete. Two separately-correct features
combined into losing the user's old version.
"""
import ast
import io
import json
import os
import unittest
import uuid
import zipfile

from deckymod import upgrade
from deckymod.journal import Journal
from deckymod.smapi import FileDropEngine as StardewEngine

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BASE = os.path.join(_REPO, ".decky-test-tmp")


def _tmpdir(tag):
    # os.makedirs, never tempfile.mkdtemp: the latter's 0o700 DACL makes writes
    # fail with WinError 5 under the Windows sandbox.
    d = os.path.join(_BASE, "r56_%s_%s" % (tag, uuid.uuid4().hex[:8]))
    os.makedirs(d, exist_ok=False)
    return d


def _moddir(parent, name):
    d = os.path.join(parent, name)
    os.makedirs(d, exist_ok=True)
    return d


_SAVED_GAME_ID = None


def setUpModule():
    # tests/test_mvp.py sets DECKYMOD_GAME_ID=rimworld at import time, so a pin
    # removed at import is already too late -- discovery imports every module
    # before running any of them.
    global _SAVED_GAME_ID
    _SAVED_GAME_ID = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    if _SAVED_GAME_ID is not None:
        os.environ["DECKYMOD_GAME_ID"] = _SAVED_GAME_ID


class TestUndoInstallRefusesWhatItMust(unittest.TestCase):
    def setUp(self):
        self.base = _tmpdir("unit")
        self.old = _moddir(self.base, "old/SomeMod")
        self.new = _moddir(self.base, "new/SomeMod")
        io.open(os.path.join(self.old, "version.txt"), "w", encoding="utf-8").write("1.0.0")
        io.open(os.path.join(self.new, "version.txt"), "w", encoding="utf-8").write("2.0.0")

    def test_no_recorded_copy_is_not_an_operator_error(self):
        for old in (None, ""):
            got = upgrade.undo_install(old, self.new)
            self.assertFalse(got["ok"])
            self.assertEqual(got["code"], "E_UNKNOWN")
            self.assertIn("no replaced copy", got["detail"])

    def test_a_source_that_left_the_quarantine_is_reported(self):
        got = upgrade.undo_install(os.path.join(self.base, "gone"), self.new)
        self.assertFalse(got["ok"])
        self.assertEqual(got["code"], "E_UNKNOWN")
        self.assertIn("no longer in the quarantine", got["detail"])
        # and the new copy is untouched: nothing half-happened
        self.assertEqual(sorted(os.listdir(self.new)), ["version.txt"])
        with io.open(os.path.join(self.new, "version.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "2.0.0")

    def test_a_symlinked_destination_is_refused_rather_than_shadowed(self):
        if not hasattr(os, "symlink"):
            self.skipTest("no symlink support")
        link = os.path.join(self.base, "link")
        try:
            os.symlink(self.new, link)
        except (OSError, NotImplementedError):  # noqa: BLE001
            self.skipTest("symlink needs privileges this platform does not grant")
        got = upgrade.undo_install(self.old, link)
        self.assertFalse(got["ok"])
        self.assertEqual(got["code"], "E_PATH_INVALID")
        self.assertIn("symbolic link", got["detail"])

    def test_a_source_that_is_a_symlink_is_refused(self):
        if not hasattr(os, "symlink"):
            self.skipTest("no symlink support")
        link = os.path.join(self.base, "oldlink")
        try:
            os.symlink(self.old, link)
        except (OSError, NotImplementedError):  # noqa: BLE001
            self.skipTest("symlink needs privileges this platform does not grant")
        got = upgrade.undo_install(link, self.new)
        self.assertFalse(got["ok"])
        self.assertEqual(got["code"], "E_UNKNOWN")

    def test_a_dot_dot_destination_is_refused(self):
        got = upgrade.undo_install(self.old, os.path.join(self.base, "x", ".."))
        self.assertFalse(got["ok"])
        self.assertEqual(got["code"], "E_PATH_INVALID")


class TestUndoInstallWorks(unittest.TestCase):
    def setUp(self):
        self.base = _tmpdir("ok")
        self.old = _moddir(self.base, "old/SomeMod")
        self.new = _moddir(self.base, "new/SomeMod")
        io.open(os.path.join(self.old, "version.txt"), "w", encoding="utf-8").write("1.0.0")
        io.open(os.path.join(self.new, "version.txt"), "w", encoding="utf-8").write("2.0.0")

    def test_the_previous_version_wins(self):
        got = upgrade.undo_install(self.old, self.new)
        self.assertTrue(got["ok"], got)
        self.assertTrue(got["removed_new"])
        self.assertEqual(got["target"], self.new)
        self.assertFalse(os.path.exists(self.old), "the quarantine copy should have moved")
        with io.open(os.path.join(self.new, "version.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "1.0.0", "the OLD version must be the one on disk")

    def test_a_missing_destination_is_created(self):
        gone = os.path.join(self.base, "fresh", "SomeMod")
        got = upgrade.undo_install(self.old, gone)
        self.assertTrue(got["ok"], got)
        self.assertFalse(got["removed_new"])
        self.assertTrue(os.path.isdir(gone))

    def test_the_mover_can_be_injected(self):
        calls = []

        def fake_mover(src, dst):
            calls.append((src, dst))
            os.makedirs(dst, exist_ok=True)

        got = upgrade.undo_install(self.old, self.new, mover=fake_mover)
        self.assertTrue(got["ok"], got)
        self.assertEqual(calls, [(self.old, self.new)])

    def test_a_failing_mover_reports_whether_the_new_copy_was_lost(self):
        def boom(src, dst):
            raise OSError("disk went away")

        got = upgrade.undo_install(self.old, self.new, mover=boom)
        self.assertFalse(got["ok"])
        self.assertEqual(got["code"], "E_OP_FAILED")
        self.assertTrue(got["removed_new"])
        self.assertIn("the new copy was removed", got["detail"])


def _make_stardew_zip(path, uid, version):
    """A minimal SMAPI mod that the real loader path will accept."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("MyMod/manifest.json", json.dumps({
            "Name": "Upgrade Me", "Author": "someone", "Version": version,
            "UniqueID": uid, "EntryDll": "MyMod.dll", "MinimumApiVersion": "4.0.0",
        }, indent=2))
        zf.writestr("MyMod/MyMod.dll", b"MZ fake dll")


_ENV_KEYS = ("DECKY_USER_HOME", "XDG_CONFIG_HOME", "DECKYMOD_INBOX",
             "DECKYMOD_DATA", "DECKYMOD_STEAM_ROOT", "DECKY_PLUGIN_RUNTIME_DIR",
             "DECKY_PLUGIN_LOG_DIR", "DECKYMOD_GAME_RUNNING",
             "DECKYMOD_EXTRA_IMPORT_ROOT", "DECKY_USER")


class _Base(object):
    def setUp(self):
        from tests.test_stardew import StardewTree
        self._saved_env = {k: os.environ.get(k) for k in _ENV_KEYS}
        self.addCleanup(self._restore_env)
        self.t = StardewTree()
        self.addCleanup(self.t.cleanup)
        self.t.env()
        self.data = _moddir(self.t.data, "d")
        self.eng = StardewEngine(journal=Journal(self.data, self.t.logs, "stardew"))
        self.uid = "someone.upgrademe"

    def _restore_env(self):
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _zip(self, version):
        p = os.path.join(self.t.inbox, "UpgradeMe-%s.zip" % version)
        _make_stardew_zip(p, self.uid, version)
        return p

    def _installed_version(self):
        man = os.path.join(self.t.mods, self.uid, "manifest.json")
        with io.open(man, encoding="utf-8") as f:
            return json.loads(f.read())["Version"]


class TestUpgradeThroughTheEngine(_Base, unittest.TestCase):
    def test_a_rollback_restores_the_previous_version(self):
        first = self.eng.install(self._zip("1.0.0"), after_confirm=True)
        self.assertTrue(first["ok"], first)
        self.assertEqual(self._installed_version(), "1.0.0")

        second = self.eng.install(self._zip("2.0.0"), after_confirm=True)
        self.assertTrue(second["ok"], second)
        self.assertEqual(self._installed_version(), "2.0.0")
        r56 = second["data"]["txn"]

        got = self.eng.rollback(r56)
        self.assertTrue(got["ok"], got)
        self.assertEqual(self._installed_version(), "1.0.0",
                         "rollback of an upgrade must put the old version back")
        self.assertEqual(got["data"]["restored"], self.uid)

    def test_the_displaced_copy_is_restorable_not_an_orphan(self):
        """Round 68: this used to REQUIRE the opposite, and that was the bug.

        The old version asserted `before["orphans"] >= 1` with the message "the
        old copy is unreachable before". It was true, and it should not have
        been: `rollback(txn)` restores that exact folder on the device (measured
        round 56 / round 68), so calling it unreachable -- orphan -- told the
        user it was litter and let reclaim_quarantine delete the one thing the
        undo still needs. A test that requires a defect is worse than no test,
        because it makes the fix look like a regression.
        """
        from deckymod import quarantine
        self.eng.install(self._zip("1.0.0"), after_confirm=True)
        r56 = self.eng.install(self._zip("2.0.0"), after_confirm=True)["data"]["txn"]
        before = quarantine.survey(self.eng._resolve().quarantine_root, self.eng.journal)
        self.assertEqual(before["orphans"], 0,
                         "a copy the rollback can still use must not be offered for deletion")
        self.assertGreaterEqual(before["restorable"], 1,
                                "the displaced copy is exactly what rollback restores")

        self.assertTrue(self.eng.rollback(r56)["ok"])
        after = quarantine.survey(self.eng._resolve().quarantine_root, self.eng.journal)
        self.assertEqual(after["orphans"], 0,
                         "after the rollback the quarantine must hold nothing unreachable")
        self.assertEqual(after["restorable"], 0,
                         "and nothing left to restore either")

    def test_a_second_rollback_is_refused_not_faked(self):
        self.eng.install(self._zip("1.0.0"), after_confirm=True)
        r56 = self.eng.install(self._zip("2.0.0"), after_confirm=True)["data"]["txn"]
        self.assertTrue(self.eng.rollback(r56)["ok"])
        again = self.eng.rollback(r56)
        self.assertFalse(again["ok"])
        self.assertEqual(again["code"], "E_UNKNOWN")
        self.assertIn("already rolled back", again["detail"])

    def test_a_plain_first_install_still_has_nothing_to_undo(self):
        r56 = self.eng.install(self._zip("1.0.0"), after_confirm=True)["data"]["txn"]
        got = self.eng.rollback(r56)
        self.assertFalse(got["ok"])
        self.assertEqual(got["code"], "E_UNKNOWN")
        self.assertIn("nothing to roll back", got["detail"])
        self.assertEqual(self._installed_version(), "1.0.0",
                         "a refused rollback must not damage the installed copy")


class TestModuleShape(unittest.TestCase):
    def setUp(self):
        self.src = io.open(os.path.join(_REPO, "deckymod", "upgrade.py"),
                           encoding="utf-8").read()

    def test_no_game_literals_outside_the_docstring(self):
        tree = ast.parse(self.src)
        doc = ast.get_docstring(tree) or ""
        body = self.src.replace(doc, "")
        low = body.lower()
        for lit in ("stardew", "413150", "smapi", "stardewvalley"):
            self.assertNotIn(lit, low, "game literal %r in upgrade.py" % lit)

    def test_only_undo_install_may_touch_the_filesystem(self):
        banned = {"makedirs", "mkdir", "remove", "unlink", "rmtree", "rename",
                  "replace", "chmod", "symlink", "copy", "copy2", "move",
                  "write", "write_text", "write_bytes", "open"}
        tree = ast.parse(self.src)
        offenders = set()
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call):
                    continue
                fn = sub.func
                name = getattr(fn, "attr", None) or getattr(fn, "id", None)
                if name in banned:
                    offenders.add(node.name)
        self.assertEqual(sorted(offenders), ["undo_install"])


if __name__ == "__main__":
    unittest.main()
