"""The suite's fixtures must not delete or reuse each other's directories.

Two real defects, found while finishing Round 84. Both were invisible when a
module ran alone and only appeared in a full run, which is why they survived:
they look like flakiness in unrelated modules.

  1. ``tests/test_deps.py`` cleaned up ``os.path.dirname(self.inbox)``, and
     ``self.inbox`` was ``<workspace>/.decky-test-tmp/r38v_xxxx``. The parent of
     that is the SHARED root, so one test deleted every other module's fixture
     tree while the suite was still running. The visible symptoms were
     ``FileNotFoundError`` in test_fomod, ``E_OP_FAILED`` in test_rollback_undo
     and ``E_PATH_ESCAPE`` in test_multi_mod -- three unrelated failures, one
     cause.

  2. ``tests/test_parser_pluggability.py`` used the FIXED directory name
     ``.decky-test-tmp/jsonc-scan`` and began with ``rmtree(root)``. A second
     run of the suite reused the name and deleted the tree the previous run had
     left behind, so results depended on whether the directory already existed.

The invariant both violated: a fixture owns exactly the directory it created,
and that directory's name is unique per run.
"""
import ast
import io
import os
import re
import unittest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TESTS = os.path.join(_REPO, "tests")

#: The one directory the whole suite shares. Nothing may remove it, and nothing
#: may assume a name under it is its own without adding a unique suffix.
SHARED = ".decky-test-tmp"


def _test_modules():
    for name in sorted(os.listdir(_TESTS)):
        if name.startswith("test_") and name.endswith(".py"):
            yield name, os.path.join(_TESTS, name)


def _calls(tree, func_names):
    """Every ``func(...)`` call node whose function name is in ``func_names``."""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        if name in func_names:
            out.append(node)
    return out


class TestNoTestDeletesTheSharedRoot(unittest.TestCase):
    """Catches defect 1: a cleanup that removes the suite-wide directory."""

    def test_no_removal_call_targets_a_parent_directory(self):
        offenders = []
        for name, path in _test_modules():
            with io.open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read())
            for call in _calls(tree, {"rmtree", "rmdir", "remove", "unlink"}):
                if not call.args:
                    continue
                arg = call.args[0]
                # `os.path.dirname(<something>)` as the thing being deleted is
                # the exact shape that removed the shared root. It is almost
                # never what a fixture means: it deletes a sibling's tree too.
                if (isinstance(arg, ast.Call)
                        and isinstance(arg.func, ast.Attribute)
                        and arg.func.attr == "dirname"):
                    offenders.append("%s:%d deletes a dirname()" % (name, call.lineno))
        self.assertEqual(
            offenders, [],
            "these tests delete the PARENT of a fixture directory, which is the "
            "shared .decky-test-tmp root when the fixture sits one level below "
            "it -- delete the fixture itself instead: %s" % offenders)

    def test_the_shared_root_is_never_named_as_a_deletion_target(self):
        offenders = []
        for name, path in _test_modules():
            with io.open(path, encoding="utf-8") as f:
                src = f.read()
            tree = ast.parse(src)
            for call in _calls(tree, {"rmtree", "rmdir"}):
                if not call.args:
                    continue
                seg = ast.dump(call.args[0])
                if SHARED in seg and "uuid" not in seg and "urandom" not in seg \
                        and "hex" not in seg:
                    offenders.append("%s:%d" % (name, call.lineno))
        self.assertEqual(offenders, [],
                         "these tests remove the shared fixture root itself: %s"
                         % offenders)


class TestFixtureNamesAreUniquePerRun(unittest.TestCase):
    """Catches defect 2: a fixed directory name reused by the next run."""

    def test_no_fixture_dir_has_a_fixed_name_under_the_shared_root(self):
        """AST, not regex: the join is nested inside dirname(abspath(__file__)).

        A regex over `join(...)` cannot see through those parens, so the first
        draft of this test passed on the very defect it was written for.
        """
        offenders = []
        for name, path in _test_modules():
            with io.open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "join"):
                    continue
                consts = [a.value for a in node.args
                          if isinstance(a, ast.Constant) and isinstance(a.value, str)]
                if SHARED not in consts:
                    continue
                # Everything after the shared-root segment: if any of it is a
                # bare constant with no unique part, the name is fixed.
                tail = consts[consts.index(SHARED) + 1:]
                if not tail:
                    continue
                seg = ast.dump(node)
                if any(tok in seg for tok in ("uuid", "urandom", "hex", "getpid")):
                    continue
                # A `%` format or `+` concat is how the rest of the suite builds
                # unique names, so an expression (not a bare constant) is fine.
                literal_tail = [a for a in node.args[node.args.index(
                    next(a for a in node.args
                         if isinstance(a, ast.Constant) and a.value == SHARED)) + 1:]
                    if isinstance(a, ast.Constant)]
                if literal_tail:
                    offenders.append(
                        "%s:%d uses the fixed name %r under %s"
                        % (name, node.lineno, tail[0], SHARED))
        self.assertEqual(
            offenders, [],
            "a fixture directory under .decky-test-tmp must be unique per run; "
            "a fixed name is reused by the next run and one run deletes the "
            "other's tree: %s" % offenders)


class TestTheLauncherIsDocumentedAsTheEntryPoint(unittest.TestCase):
    """`python -m unittest` produces 22 fake PermissionErrors on this box.

    The handoff document has to say so, because the failure looks like the
    product and the next person will spend an afternoon on it. README's CI
    section legitimately runs plain unittest on ubuntu-latest, so the rule is
    "the Windows-specific warning exists", not "nobody may mention the command".
    """

    def test_the_handoff_warns_about_running_unittest_directly(self):
        path = os.path.join(_REPO, "docs/SESSION_HANDOFF.md")
        self.assertTrue(os.path.isfile(path), path)
        with io.open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertRegex(text, r"python\s+-m\s+unittest",
                         "the handoff must name the command it is warning about, "
                         "or the warning reads as a general prohibition")
        self.assertIn("run_tests.py", text,
                      "the handoff must name the launcher that works")
        # The warning has to be adjacent to the command, not 100 lines away.
        idx = text.find("-m unittest")
        window = text[max(0, idx - 400): idx + 400]
        self.assertTrue(
            ("不要用" in window) or ("must not" in window.lower())
            or ("do not" in window.lower()) or ("假失败" in window),
            "the mention of `python -m unittest` in the handoff is not marked as "
            "forbidden nearby, so a reader will run it and see 22 fake failures")


class TestTheCompilerStillLooksForDeadCode(unittest.TestCase):
    """`tsc --noEmit` passing did not mean the frontend was clean.

    Round 84 shipped a report claiming five dead functions had been deleted.
    They were still there. Nothing caught it, because ``tsconfig.json`` had
    ``strict: true`` but not ``noUnusedLocals`` / ``noUnusedParameters`` -- so
    the compiler resolved every one of those symbols and reported no error.
    Turning the two flags on immediately produced ten diagnostics, including
    ``'openGameLibrary' is declared but its value is never read``.

    ``strict`` covers types, not reachability. These tests exist so the flags
    cannot be dropped again without someone noticing: with them off, "the build
    is green" says nothing about whether the code is reachable.
    """

    def _opts(self):
        import json
        path = os.path.join(_REPO, "tsconfig.json")
        with io.open(path, encoding="utf-8") as f:
            return json.load(f)["compilerOptions"]

    def test_unused_locals_is_an_error(self):
        self.assertIs(self._opts().get("noUnusedLocals"), True,
                      "tsconfig must keep noUnusedLocals: without it a function "
                      "nothing calls still compiles, which is how Round 84's "
                      "five dead functions survived a green build")

    def test_unused_parameters_is_an_error(self):
        self.assertIs(self._opts().get("noUnusedParameters"), True,
                      "tsconfig must keep noUnusedParameters: a parameter the "
                      "body ignores is either a leftover or a bug in the call")

    def test_strict_is_still_on(self):
        self.assertIs(self._opts().get("strict"), True,
                      "strict has to stay on for the two flags above to mean "
                      "what they say")

if __name__ == "__main__":
    unittest.main()
