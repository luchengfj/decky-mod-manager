"""Round 55: hand the ``Mods/`` folder over from another mod manager.

The operation exists because Round 44 taught the engine to refuse writing into a
folder somebody else owns, and refusing without offering an exit is a dead end:
a user who has never heard of the other manager sees "read-only" everywhere and
concludes the plugin is broken.

Everything here proves one of two things: that the operation moves only what it
can put back, or that it refuses instead of half-doing it.
"""
from __future__ import annotations

import ast
import os
import sys
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deckymod import handover  # noqa: E402

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BASE = os.path.join(_REPO, ".decky-test-tmp")


def _tmpdir(tag):
    """A fresh writable directory (never tempfile: 0o700 DACL breaks on Windows)."""
    d = os.path.join(_BASE, "r55_%s_%s" % (tag, uuid.uuid4().hex[:8]))
    os.makedirs(d, exist_ok=False)
    return d


class TestSurveySeparatesMovableFromBlocking(unittest.TestCase):
    def setUp(self):
        self.base = _tmpdir("survey")
        self.game = os.path.join(self.base, "Stardew Valley")
        self.mods = os.path.join(self.game, "Mods")
        os.makedirs(self.mods)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        import shutil
        shutil.rmtree(self.base, ignore_errors=True)

    def test_a_clean_folder_has_nothing_to_move(self):
        got = handover.survey(self.game, self.mods, [".mm_deployed"])
        self.assertTrue(got["ok"])
        self.assertEqual(got["movable"], [])
        self.assertEqual(got["blocking"], [])
        self.assertEqual(got["explain"], "")

    def test_a_marker_file_inside_mods_is_movable(self):
        # Amethyst's 0-byte bookkeeping file: moving it is reversible and does
        # not touch any mod it deployed.
        with open(os.path.join(self.mods, ".mm_deployed"), "wb") as f:
            f.write(b"")
        got = handover.survey(self.game, self.mods, [".mm_deployed", "Mods_Core"])
        self.assertEqual(got["blocking"], [])
        self.assertEqual([r["kind"] for r in got["movable"]],
                         [handover.R_MARKER_FILE])
        self.assertEqual(got["movable"][0]["name"], ".mm_deployed")

    def test_a_marker_directory_beside_the_game_blocks(self):
        # This is where the other manager's real deployed files live. Moving it
        # would break that deployment in ways this plugin cannot see.
        os.makedirs(os.path.join(self.game, "Mods_Core", "deployed"))
        got = handover.survey(self.game, self.mods, [".mm_deployed", "Mods_Core"])
        self.assertIn(handover.R_MARKER_DIR, got["blocking"])
        self.assertIn("Mods_Core/", got["explain"])

    def test_no_marker_list_means_nothing_to_move(self):
        # No default inherited from another module: this operation MOVES things,
        # so an undeclared list must not make it act on a guess.
        with open(os.path.join(self.mods, ".mm_deployed"), "wb") as f:
            f.write(b"")
        got = handover.survey(self.game, self.mods, None)
        self.assertEqual(got["movable"], [])
        self.assertEqual(got["blocking"], [])

    def test_a_missing_mods_folder_is_not_a_blocker(self):
        # Nothing to hand over, and "we could not look" must not become
        # "you must act".
        gone = os.path.join(self.game, "Nope")
        got = handover.survey(self.game, gone, [".mm_deployed"])
        self.assertEqual(got["blocking"], [])
        self.assertEqual(got["movable"], [])

    @unittest.skipIf(not hasattr(os, "symlink"), "no symlink support")
    def test_a_symlinked_mods_dir_blocks_and_is_never_moved(self):
        # Moving the link would leave Mods/ missing while the other tool still
        # believes it is deployed.
        real = os.path.join(self.base, "elsewhere")
        os.makedirs(real)
        linked = os.path.join(self.game, "ModsLinked")
        try:
            os.symlink(real, linked)
        except (OSError, NotImplementedError) as exc:      # pragma: no cover
            self.skipTest("cannot create a symlink here: %s" % exc)
        got = handover.survey(self.game, linked, [".mm_deployed"])
        self.assertIn(handover.R_MODS_SYMLINK, got["blocking"])
        self.assertEqual(got["movable"], [])


class TestPlanRefusesTheWholeThing(unittest.TestCase):
    def test_blocking_means_nothing_moves(self):
        # Half a handover is worse than none: the user would be left with the
        # other manager's deployment partly dismantled and still read-only.
        got = handover.plan(
            {"ok": True, "movable": [{"kind": handover.R_SYMLINKED_ENTRY,
                                      "name": "x", "path": "/x"}],
             "blocking": [handover.R_MARKER_DIR], "explain": "Mods_Core/ ..."},
            "/q/t1")
        self.assertFalse(got["ok"])
        self.assertEqual(got["code"], "E_CAPABILITY_DISABLED")
        self.assertEqual(got["movable"], [])
        self.assertIn("Mods_Core", got["detail"])

    def test_nothing_movable_is_reported_not_silently_successful(self):
        got = handover.plan({"ok": True, "movable": [], "blocking": [],
                             "explain": ""}, "/q/t1")
        self.assertFalse(got["ok"])
        self.assertIn("nothing to hand over", got["detail"])

    def test_a_failed_survey_is_not_treated_as_success(self):
        got = handover.plan({"ok": False, "code": "E_ACCESS",
                             "detail": "nope"}, "/q/t1")
        self.assertFalse(got["ok"])
        self.assertEqual(got["code"], "E_ACCESS")

    def test_a_clean_survey_is_accepted(self):
        got = handover.plan(
            {"ok": True, "movable": [{"kind": handover.R_MARKER_FILE,
                                      "name": ".mm_deployed", "path": "/m"}],
             "blocking": [], "explain": ""}, "/q/t1")
        self.assertTrue(got["ok"])
        self.assertEqual(len(got["movable"]), 1)


class TestExecuteIsTwoPhase(unittest.TestCase):
    def setUp(self):
        self.base = _tmpdir("exec")
        self.game = os.path.join(self.base, "Game")
        self.mods = os.path.join(self.game, "Mods")
        self.quar = os.path.join(self.game, ".decky-quarantine")
        os.makedirs(self.mods)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        import shutil
        shutil.rmtree(self.base, ignore_errors=True)

    def _plan(self):
        with open(os.path.join(self.mods, ".mm_deployed"), "wb") as f:
            f.write(b"")
        survey = handover.survey(self.game, self.mods, [".mm_deployed"])
        got = handover.plan(survey, os.path.join(self.quar, "t1"))
        self.assertTrue(got["ok"], got)
        return got

    def test_without_confirm_nothing_moves(self):
        planned = self._plan()
        out = handover.execute(planned, after_confirm=False,
                               quarantine_root=self.quar, txn="t1")
        self.assertEqual(out["phase"], "confirm")
        self.assertEqual(out["count"], 1)
        self.assertTrue(os.path.isfile(os.path.join(self.mods, ".mm_deployed")))
        self.assertFalse(os.path.exists(os.path.join(self.quar, "t1")))

    def test_with_confirm_the_marker_moves_and_is_still_there(self):
        planned = self._plan()
        out = handover.execute(planned, after_confirm=True,
                               quarantine_root=self.quar, txn="t1")
        self.assertEqual(out["phase"], "moved")
        self.assertEqual(out["moved"], [".mm_deployed"])
        self.assertFalse(os.path.exists(os.path.join(self.mods, ".mm_deployed")))
        self.assertTrue(os.path.isfile(
            os.path.join(self.quar, "t1", ".mm_deployed")))

    def test_the_entry_is_rechecked_before_it_moves(self):
        # The survey is a snapshot; a folder can change between the dialog and
        # the confirm. An entry that vanished is reported, not invented.
        planned = self._plan()
        os.remove(os.path.join(self.mods, ".mm_deployed"))
        out = handover.execute(planned, after_confirm=True,
                               quarantine_root=self.quar, txn="t1")
        self.assertEqual(out["moved"], [])
        self.assertEqual(out["failed"][".mm_deployed"], "already gone")

    def test_a_failed_move_does_not_stop_the_others(self):
        planned = {
            "ok": True,
            "movable": [
                {"kind": handover.R_MARKER_FILE, "name": "bad", "path": "/nope/bad"},
                {"kind": handover.R_MARKER_FILE, "name": ".mm_deployed",
                 "path": os.path.join(self.mods, ".mm_deployed")},
            ],
        }
        with open(os.path.join(self.mods, ".mm_deployed"), "wb") as f:
            f.write(b"")
        out = handover.execute(planned, after_confirm=True,
                               quarantine_root=self.quar, txn="t1")
        self.assertEqual(out["moved"], [".mm_deployed"])
        self.assertIn("bad", out["failed"])

    def test_missing_quarantine_or_txn_is_refused(self):
        planned = self._plan()
        out = handover.execute(planned, after_confirm=True, quarantine_root="",
                               txn="")
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "E_PATH_INVALID")


class TestModuleShape(unittest.TestCase):
    def test_no_game_literals(self):
        # Same rule as every other game-agnostic module: a literal here is the
        # first step toward ``if game == ...``.
        with open(os.path.join(_REPO, "deckymod", "handover.py"),
                  encoding="utf-8") as f:
            src = f.read()
        doc = ast.get_docstring(ast.parse(src)) or ""
        body = src.replace(doc, "")
        for banned in ("stardew", "413150", "smapi", "stardewvalley"):
            self.assertNotIn(banned, body.lower(), banned)

    def test_only_move_functions_write(self):
        # Round 55 added ``restore``: putting entries back is the other half of
        # what makes the confirm dialog's promise true, so it has to write too.
        # The claim narrows rather than disappears -- exactly two functions in
        # this module may touch the filesystem, and both are moves, not deletes.
        with open(os.path.join(_REPO, "deckymod", "handover.py"),
                  encoding="utf-8") as f:
            tree = ast.parse(f.read())
        banned = {"makedirs", "mkdir", "remove", "unlink", "rmtree", "rename",
                  "replace", "chmod", "symlink", "copy", "copy2", "move",
                  "write", "write_text", "write_bytes", "fsync", "truncate"}
        offenders = set()
        for fn in tree.body:
            if not isinstance(fn, ast.FunctionDef):
                continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                f = node.func
                if isinstance(f, ast.Attribute):
                    if (isinstance(f.value, ast.Name)
                            and f.value.id in ("os", "shutil") and f.attr in banned):
                        offenders.add(fn.name)
                elif isinstance(f, ast.Name) and f.id == "open":
                    offenders.add(fn.name)
        self.assertEqual(sorted(offenders), ["execute", "restore"])


if __name__ == "__main__":
    unittest.main()
