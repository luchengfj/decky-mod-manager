"""Round 50: is the game running? Layered the same way as the rest of the repo.

Why two files
-------------
``test_procs.py`` fakes ``/proc`` so the decision logic is tested on any host
(Windows has no /proc at all). ``test_running_gate.py`` drives the real engine so
we prove the gate is actually WIRED -- a correct detector that nothing calls is
the exact bug this round exists to fix.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deckymod import procs  # noqa: E402

GAME_ROOT = "/home/deck/.local/share/Steam/steamapps/common/Stardew Valley"


class _FakeProc(object):
    """Replaces /proc for the duration of one test."""

    def __init__(self, procs_map):
        # procs_map: {"101": "/usr/bin/bash", ...}
        self.procs_map = procs_map
        self._old_lister = None
        self._old_reader = None

    def __enter__(self):
        self._old_lister = procs._lister
        self._old_reader = procs._reader

        def lister():
            return ["1", "self", "meminfo"] + list(self.procs_map.keys())

        def reader(pid):
            head = self.procs_map.get(pid)
            if head is None:
                # The real _reader swallows OSError and returns b""; a fake that
                # raises would test the fake, not the module.
                return b""
            return head.encode("utf-8") + b"\0--some\0args\0"

        procs._lister = lister
        procs._reader = reader
        return self

    def __exit__(self, *exc):
        procs._lister = self._old_lister
        procs._reader = self._old_reader
        return False


class TestDetection(unittest.TestCase):
    def test_a_marker_basename_is_running(self):
        with _FakeProc({"101": "/usr/bin/bash",
                        "202": GAME_ROOT + "/StardewModdingAPI"}):
            got = procs.is_running(GAME_ROOT, ["StardewModdingAPI"])
        self.assertEqual(got["state"], "running")
        self.assertEqual(got["pid"], "202")

    def test_an_executable_inside_game_root_is_running(self):
        # The marker list may be incomplete; the path is the second signal and
        # it does not depend on knowing a name.
        with _FakeProc({"303": GAME_ROOT + "/Stardew Valley"}):
            got = procs.is_running(GAME_ROOT, ["smapi"])
        self.assertEqual(got["state"], "running")
        self.assertEqual(got["match"], GAME_ROOT + "/Stardew Valley")

    def test_a_terminal_sitting_in_the_mods_folder_is_not_the_game(self):
        # This is why only argv[0] is inspected: a shell whose CWD or arguments
        # mention the game must not be mistaken for it.
        with _FakeProc({"404": "/usr/bin/bash"}):
            got = procs.is_running(GAME_ROOT + "/Mods", ["StardewModdingAPI"])
        self.assertEqual(got["state"], "stopped")

    def test_nothing_running_is_stopped(self):
        with _FakeProc({"505": "/usr/bin/bash", "506": "/usr/bin/sshd"}):
            got = procs.is_running(GAME_ROOT, ["StardewModdingAPI"])
        self.assertEqual(got["state"], "stopped")
        # "1", "505", "506" are the numeric entries the fake lister offers.
        self.assertEqual(got["scanned"], 3)

    def test_our_own_pid_is_skipped(self):
        # The plugin's own argv can name the game folder (it is passed as an
        # argument); counting that would make every write refuse forever.
        with _FakeProc({str(os.getpid()): GAME_ROOT + "/StardewModdingAPI"}):
            got = procs.is_running(GAME_ROOT, ["StardewModdingAPI"])
        self.assertEqual(got["state"], "stopped")

    def test_empty_proc_is_unknown_not_stopped(self):
        # "I could not check" must never be reported as "it is not running".
        with _FakeProc({}):
            procs._lister = lambda: []
            got = procs.is_running(GAME_ROOT, ["StardewModdingAPI"])
        self.assertEqual(got["state"], "unknown")
        self.assertIn("cannot tell", got["detail"])

    def test_unreadable_proc_is_unknown(self):
        old = procs._lister

        def boom():
            raise OSError(13, "permission denied")

        procs._lister = boom
        try:
            got = procs.is_running(GAME_ROOT, ["StardewModdingAPI"])
        finally:
            procs._lister = old
        self.assertEqual(got["state"], "unknown")
        self.assertIn("permission denied", got["detail"])

    def test_an_unreadable_cmdline_is_skipped_not_fatal(self):
        with _FakeProc({"606": "/usr/bin/bash"}):
            got = procs.is_running(GAME_ROOT, ["StardewModdingAPI"])
        self.assertEqual(got["state"], "stopped")

    def test_marker_match_is_case_insensitive(self):
        with _FakeProc({"707": "/opt/x/stardewmoddingapi"}):
            got = procs.is_running(GAME_ROOT, ["StardewModdingAPI"])
        self.assertEqual(got["state"], "running")

    def test_a_partial_name_does_not_match(self):
        # basename comparison, not substring: StardewModdingAPI.bak is not it.
        with _FakeProc({"808": "/opt/StardewModdingAPI.bak"}):
            got = procs.is_running("", ["StardewModdingAPI"])
        self.assertEqual(got["state"], "stopped")

    def test_no_markers_and_no_root_is_stopped(self):
        with _FakeProc({"909": "/usr/bin/bash"}):
            got = procs.is_running("", [])
        self.assertEqual(got["state"], "stopped")


class TestDescribe(unittest.TestCase):
    def test_running_names_the_evidence(self):
        text = procs.describe({"state": "running", "pid": "42",
                               "match": "/x/StardewModdingAPI"})
        self.assertIn("42", text)
        self.assertIn("StardewModdingAPI", text)

    def test_stopped_says_nothing(self):
        self.assertEqual(procs.describe({"state": "stopped"}), "")

    def test_unknown_admits_it(self):
        text = procs.describe({"state": "unknown", "detail": "no /proc"})
        self.assertIn("could not check", text)
        self.assertIn("no /proc", text)


class TestModuleShape(unittest.TestCase):
    def test_no_game_literal_in_executable_code(self):
        # The docstring legitimately names the game it was written for. What must
        # never appear is a game literal in CODE -- that would be the start of an
        # ``if game == ...`` branch, which this module exists to avoid.
        import ast
        import io
        with io.open(procs.__file__, "r", encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef,
                                 ast.AsyncFunctionDef)):
                body = getattr(node, "body", None) or []
                if body and isinstance(body[0], ast.Expr) and \
                        isinstance(body[0].value, ast.Constant) and \
                        isinstance(body[0].value.value, str):
                    docstrings.add(id(body[0].value))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and id(node) not in docstrings:
                low = node.value.lower()
                for bad in ("stardew", "413150", "smapi", "stardewvalley"):
                    self.assertNotIn(bad, low, "game literal in code: %r" % node.value)

    def test_module_never_writes(self):
        # `replace` is a red herring here: str.replace is how a POSIX path gets
        # normalised on a Windows host. Only os/shutil-rooted calls count.
        import ast
        import io

        def chain(node):
            parts = []
            while isinstance(node, ast.Attribute):
                parts.append(node.attr)
                node = node.value
            if isinstance(node, ast.Name):
                parts.append(node.id)
            return list(reversed(parts))

        with io.open(procs.__file__, "r", encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
        banned = {"makedirs", "mkdir", "remove", "unlink", "rmtree", "rename",
                  "replace", "chmod", "symlink", "copy", "copy2", "move",
                  "write", "write_text", "write_bytes", "kill", "terminate",
                  "signal"}
        hits = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                parts = chain(node.func)
                if parts and parts[0] in ("os", "shutil") and \
                        parts[-1] in banned:
                    hits.append(".".join(parts))
        self.assertEqual(hits, [])

    def test_only_opens_proc_read_only(self):
        import ast
        import io
        with io.open(procs.__file__, "r", encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
        opens = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "open"]
        self.assertEqual(len(opens), 1)
        mode = opens[0].args[1] if len(opens[0].args) > 1 else None
        if isinstance(mode, ast.Constant):
            self.assertNotIn("w", str(mode.value))
            self.assertNotIn("a", str(mode.value))


if __name__ == "__main__":
    unittest.main()
