"""No test module may drop the game-id pin at import time.

`tests/test_mvp.py` sets ``os.environ.setdefault("DECKYMOD_GAME_ID", "rimworld")``
at import so its 33 RimWorld assertions keep running against the historical
descriptor. Every Stardew-oriented test module has to step around that pin.

The trap: unittest's discovery imports *every* module before running *any* of
them. So a module that does

    _SAVED = os.environ.pop("DECKYMOD_GAME_ID", None)      # at module level
    def tearDownModule(): os.environ[...] = _SAVED

removes the pin during discovery -- before test_mvp's tests run -- and nine of
them then resolve AppID 413150 against a RimWorld-shaped tree and fail with
``E_CAPABILITY_DISABLED rimworld status=planned``.

That exact mistake has now been made three times in this repository (rounds 47,
50 and 61). The first two were fixed by remembering; this test replaces
remembering. The correct shape is ``setUpModule()`` / ``tearDownModule()``,
which run around this module's tests only.
"""
import ast
import io
import os
import unittest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TESTS = os.path.join(_REPO, "tests")


def _modules():
    for name in sorted(os.listdir(_TESTS)):
        if name.startswith("test_") and name.endswith(".py"):
            yield name, os.path.join(_TESTS, name)


def _import_level_calls(tree):
    """Calls executed as a side effect of importing the module."""
    out = []
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            out.append(node.value)
        elif isinstance(node, ast.Assign):
            v = node.value
            if isinstance(v, ast.Call):
                out.append(v)
            elif isinstance(v, ast.Subscript):
                # d["X"] = os.environ.pop(...) is the same hazard
                if isinstance(v.value, ast.Call):
                    out.append(v.value)
    return out


def _touches_game_id(call):
    seg = ast.dump(call)
    return "DECKYMOD_GAME_ID" in seg


class TestThePinSurvivesDiscovery(unittest.TestCase):
    def test_no_module_pops_the_pin_at_import_time(self):
        offenders = []
        for name, path in _modules():
            with io.open(path, encoding="utf-8") as f:
                src = f.read()
            tree = ast.parse(src)
            for call in _import_level_calls(tree):
                if _touches_game_id(call) and isinstance(call.func, ast.Attribute) \
                        and call.func.attr in ("pop", "update", "clear"):
                    offenders.append("%s:%d %s" % (name, call.lineno, call.func.attr))
        self.assertEqual(
            offenders, [],
            "these modules mutate DECKYMOD_GAME_ID while being imported, which "
            "happens before test_mvp runs: %s" % offenders,
        )

    def test_the_known_module_uses_setup_module(self):
        """The specific shape, stated once so a rewrite cannot quietly drop it."""
        path = os.path.join(_TESTS, "test_lifecycle_hooks.py")
        if not os.path.exists(path):
            self.skipTest("module removed")
        with io.open(path, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("def setUpModule():", src)
        self.assertIn("global _SAVED_GAME_ID", src)

    def test_test_mvp_still_sets_the_pin(self):
        """The other half: the pin has to exist for this rule to mean anything."""
        with io.open(os.path.join(_TESTS, "test_mvp.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('setdefault("DECKYMOD_GAME_ID", "rimworld")', src)


if __name__ == "__main__":
    unittest.main()
