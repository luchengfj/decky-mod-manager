"""Round 44: structural detection of a foreign mod-folder deployment.

Two layers here on purpose:

* The survey itself is tested against **faked** filesystem primitives
  (``os.lstat``/``os.scandir``/``os.path.islink``). Windows refuses
  ``os.symlink`` without developer mode (``WinError 1314``), so building a real
  symlinked tree is impossible on this machine -- but the *decision logic* is
  what can be wrong, and faking the primitives tests it exactly and portably.
* The gate that consumes the survey is tested separately in
  ``tests/test_modwatch_gate.py`` against a real tree.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deckymod import modwatch  # noqa: E402

GAME = os.path.join("C:", os.sep, "game")
MODS = os.path.join(GAME, "Mods")


class _Stat:
    def __init__(self, dev):
        self.st_dev = dev


class _Entry:
    def __init__(self, name, link=False):
        self.name = name
        self.path = os.path.join(MODS, name)
        self._link = link

    def is_symlink(self):
        return self._link


class _Scandir:
    def __init__(self, entries):
        self._entries = entries

    def __iter__(self):
        return iter(self._entries)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch(*, mods_dev=1, game_dev=1, mods_link=False, entries=(), entries_raises=False,
           mods_missing=False):
    """Patch the three primitives survey() uses."""
    def fake_lstat(path):
        if mods_missing and os.path.normpath(path) == os.path.normpath(MODS):
            raise FileNotFoundError(path)
        if os.path.normpath(path) == os.path.normpath(MODS):
            return _Stat(mods_dev)
        return _Stat(game_dev)

    def fake_scandir(path):
        if entries_raises:
            raise PermissionError(path)
        return _Scandir(list(entries))

    return [
        mock.patch.object(modwatch.os, "lstat", fake_lstat),
        mock.patch.object(modwatch.os, "scandir", fake_scandir),
        mock.patch.object(modwatch.os.path, "islink",
                          lambda p: mods_link and os.path.normpath(p) == os.path.normpath(MODS)),
    ]


class TestSurvey(unittest.TestCase):
    def _run(self, **kw):
        pills = _patch(**kw)
        for p in pills:
            p.start()
            self.addCleanup(p.stop)
        return modwatch.survey(GAME, MODS)

    def test_plain_directory_is_clean(self):
        s = self._run(entries=[_Entry("Automate"), _Entry("LookupAnything")])
        self.assertTrue(s["exists"])
        self.assertFalse(s["is_symlink"])
        self.assertEqual(s["reasons"], [])
        self.assertEqual(s["explain"], "")
        self.assertEqual(s["entries"], 2)
        self.assertFalse(modwatch.is_foreign(s))

    def test_an_empty_directory_is_clean(self):
        s = self._run(entries=[])
        self.assertEqual(s["reasons"], [])
        self.assertFalse(modwatch.is_foreign(s))

    def test_mods_is_a_symlink_is_foreign(self):
        s = self._run(mods_link=True, entries=[_Entry("x")])
        self.assertTrue(s["is_symlink"])
        self.assertIn(modwatch.R_MODS_SYMLINK, s["reasons"])
        self.assertTrue(modwatch.is_foreign(s))
        self.assertIn("symlink", modwatch.describe(s))

    def test_symlink_entries_are_foreign_and_named(self):
        s = self._run(entries=[_Entry("A", link=True), _Entry("B"), _Entry("C", link=True)])
        self.assertIn(modwatch.R_SYMLINKED_ENTRY, s["reasons"])
        self.assertEqual(s["symlinked"], ["A", "C"])
        self.assertEqual(s["symlinked_count"], 2)
        self.assertTrue(modwatch.is_foreign(s))
        desc = modwatch.describe(s)
        self.assertIn("A", desc)
        self.assertIn("C", desc)

    def test_symlink_listing_is_capped_but_counted(self):
        names = ["m%03d" % i for i in range(50)]
        s = self._run(entries=[_Entry(n, link=True) for n in names])
        self.assertEqual(s["symlinked_count"], 50)
        self.assertEqual(len(s["symlinked"]), modwatch.MAX_NAMED)
        self.assertIn("+30 more", modwatch.describe(s))

    def test_other_device_is_foreign(self):
        s = self._run(mods_dev=1, game_dev=2, entries=[_Entry("A")])
        self.assertIn(modwatch.R_OTHER_DEVICE, s["reasons"])
        self.assertTrue(modwatch.is_foreign(s))

    def test_missing_mods_dir_is_reported_but_not_foreign(self):
        """A first install creates the folder; refusing there would be absurd."""
        s = self._run(mods_missing=True)
        self.assertFalse(s["exists"])
        self.assertIn(modwatch.R_MODS_MISSING, s["reasons"])
        self.assertFalse(modwatch.is_foreign(s))
        self.assertEqual(modwatch.describe(s), "")

    def test_unreadable_dir_is_not_reported_as_foreign(self):
        """'I could not look' must not become 'someone else owns it'."""
        s = self._run(entries_raises=True)
        self.assertTrue(s["checked"])
        self.assertEqual(s["entries"], 0)
        self.assertEqual(s["reasons"], [])
        self.assertFalse(modwatch.is_foreign(s))

    def test_symlinked_dir_is_not_walked(self):
        """The other tool's tree may be huge; only the real dir is scanned."""
        s = self._run(mods_link=True, entries=[_Entry("A", link=True)])
        self.assertEqual(s["entries"], 0)
        self.assertNotIn(modwatch.R_SYMLINKED_ENTRY, s["reasons"])

    def test_describe_joins_multiple_reasons(self):
        s = self._run(mods_link=True, mods_dev=1, game_dev=2)
        desc = modwatch.describe(s)
        self.assertIn("symlink", desc)
        self.assertIn("filesystem", desc)


class TestNoWrites(unittest.TestCase):
    def test_module_never_opens_for_writing_or_creates(self):
        """AST check: this module must stay read-only by construction."""
        import ast
        path = sys.modules["deckymod.modwatch"].__file__
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
        banned = {"makedirs", "mkdir", "remove", "unlink", "rmtree", "rename", "replace",
                  "chmod", "symlink", "open", "fdopen", "copy", "copy2", "move", "walk"}
        hits = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else (
                fn.id if isinstance(fn, ast.Name) else "")
            if name in banned:
                hits.append(name)
        self.assertEqual(hits, [], "modwatch.py must not mutate the filesystem")


if __name__ == "__main__":
    unittest.main()
