"""One expression decides where a mod lives.

Rounds 57, 58 and 59 were all the same defect wearing different clothes: in the
file_drop engine "disabled" is a LOCATION (a folder in ``Mods/`` is loaded, a
folder in the sibling ``.decky-disabled/`` is parked), and three separate code
paths each recomputed that answer themselves. Each recomputation was correct
where it was written and wrong somewhere else:

  round 57  install()  always unpacked into Mods/, silently re-enabling a
                       disabled mod and leaving two copies with one UniqueID
  round 58  uninstall() only resolved Mods/, so a parked mod reported success
                       while staying exactly where it was
  round 59  inspect()  previewed a destination install() would not use, so the
                       confirm dialog -- the sentence the user agrees to --
                       described a different operation than the one that ran

Fixing them one at a time is what produced three rounds. This file exists to
make the fourth impossible: after round 60 the answer comes from a single
helper, ``FileDropEngine._locate()``, and these tests fail if any of the three
call sites starts building the paths itself again.

The assertions are structural on purpose. A behavioural test would pass while
the duplication is reintroduced, because duplicated expressions agree until
somebody changes one of them -- which is exactly how rounds 57-59 shipped.
"""
import ast
import io
import os
import unittest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SMAPI = os.path.join(_REPO, "deckymod", "smapi.py")

# The functions that must ask _locate() rather than computing paths.
_CALLERS = ("inspect", "_install_inner", "_uninstall_inner")


def _source():
    with io.open(_SMAPI, encoding="utf-8") as f:
        return f.read()


def _tree():
    return ast.parse(_source())


def _funcs(tree):
    """Top-level-of-class function nodes, by name."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            out.setdefault(node.name, node)
    return out


def _joins_on(func, root_attr):
    """Count ``os.path.join(<root>.<root_attr>, ...)`` inside one function.

    Matches the shape the duplication took, not any use of os.path.join: a
    join onto something else (a quarantine dir, a constant) is fine here.
    """
    hits = 0
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "join"):
            continue
        owner = fn.value
        if not (isinstance(owner, ast.Attribute) and owner.attr == "path"):
            continue
        if not node.args:
            continue
        first = node.args[0]
        if not isinstance(first, ast.Attribute):
            continue
        if first.attr != root_attr:
            continue
        base = first.value
        if isinstance(base, ast.Name) and base.id == "r":
            hits += 1
    return hits


class TestOnePlaceDecidesThePath(unittest.TestCase):
    def test_the_helper_exists_and_answers_all_four_questions(self):
        tree = _tree()
        fn = _funcs(tree).get("_locate")
        self.assertIsNotNone(fn, "_locate() is gone; the whole point of round 60")
        returned = [n for n in ast.walk(fn) if isinstance(n, ast.Return)]
        self.assertEqual(len(returned), 1)
        value = returned[0].value
        self.assertIsInstance(value, ast.Dict)
        keys = sorted(
            (k.value for k in value.keys if isinstance(k, ast.Constant)),
        )
        self.assertEqual(keys, ["install_at", "parked", "parked_at", "target"])

    def test_the_helper_is_the_only_place_that_builds_both_roots(self):
        tree = _tree()
        funcs = _funcs(tree)

        located = funcs["_locate"]
        self.assertEqual(_joins_on(located, "mod_root"), 1)
        self.assertEqual(_joins_on(located, "disabled_root"), 1)

        # Every other function may keep at most the one legitimate Mods/ join
        # that is not a "which copy is live" decision: uninstall()'s fallback
        # for a mod the journal never recorded a directory for.
        for name, fn in funcs.items():
            if name == "_locate":
                continue
            self.assertEqual(
                _joins_on(fn, "disabled_root"), 0,
                "%s builds a .decky-disabled path itself instead of asking "
                "_locate(); that is how rounds 57-59 each shipped a bug" % name,
            )

    def test_the_three_callers_ask_the_helper(self):
        tree = _tree()
        funcs = _funcs(tree)
        for name in _CALLERS:
            fn = funcs.get(name)
            self.assertIsNotNone(fn, "%s" % name)
            called = [
                n for n in ast.walk(fn)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "_locate"
            ]
            self.assertEqual(
                len(called), 1,
                "%s must call _locate() exactly once; found %d"
                % (name, len(called)),
            )

    def test_install_reads_its_destination_from_the_helper(self):
        """The specific regression: install must not recompute install_at."""
        fn = _funcs(_tree())["_install_inner"]
        assigned = {}
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                tgt = node.targets[0]
                if isinstance(tgt, ast.Name):
                    assigned.setdefault(tgt.id, []).append(node.value)

        self.assertIn("install_at", assigned)
        # Exactly one assignment, and it reads the helper's answer.
        self.assertEqual(len(assigned["install_at"]), 1)
        value = assigned["install_at"][0]
        self.assertIsInstance(value, ast.Subscript)
        self.assertEqual(value.slice.value, "install_at")
        base = value.value
        self.assertIsInstance(base, ast.Name)
        self.assertIn(
            base.id, assigned,
            "install_at should come from a dict the helper returned",
        )


class TestTheHelperMatchesTheEnginesStateModel(unittest.TestCase):
    """Read-only checks that do not need a filesystem.

    The behavioural half lives in tests/test_preview_agreement.py and
    tests/test_duplicate_guard.py, which build real trees. These assert the
    parts of the contract that are cheap to state and expensive to rediscover.
    """

    def test_parked_requires_managed(self):
        """A same-named folder that is not ours must not count as our copy."""
        fn = _funcs(_tree())["_locate"]
        src = ast.get_source_segment(_source(), fn) or ""
        self.assertIn("bool(managed) and", src)
        self.assertIn('"parked_at": parked_at', src)
        self.assertIn('"install_at": parked_at if parked else target', src)

    def test_helper_does_not_write(self):
        fn = _funcs(_tree())["_locate"]
        banned = {
            "makedirs", "mkdir", "remove", "unlink", "rmtree", "rename",
            "replace", "chmod", "symlink", "copy", "copy2", "move",
        }
        hit = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Attribute) and f.attr in banned:
                    hit.add(f.attr)
        self.assertEqual(sorted(hit), [], "a read must stay a read")


if __name__ == "__main__":
    unittest.main()
