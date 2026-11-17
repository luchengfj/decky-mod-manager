"""Tests for conflict reporting (round 47).

Two mods shipping the same path is a filesystem fact, so most of this is real
directories rather than mocks. The one thing that is checked structurally is
that the module never writes and never contains a game-specific literal --
those would both rot silently.
"""

import ast
import io
import os
import sys
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deckymod import conflicts  # noqa: E402

BASE = r"C:\ai\SD\.decky-test-tmp"


def _tmpdir(tag):
    p = os.path.join(BASE, "r47_%s_%s" % (tag, uuid.uuid4().hex[:8]))
    os.makedirs(p, exist_ok=True)  # NOT mkdtemp: 0o700 DACL breaks sandbox writes
    return p


def _write(root, rel, data=b"x"):
    full = os.path.join(root, rel)
    d = os.path.dirname(full)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(full, "wb") as f:
        f.write(data)


class _Mods(object):
    def __init__(self, mod_root, spec):
        for name, files in spec.items():
            for rel in files:
                _write(os.path.join(mod_root, name), rel)


class TestSharedPathsRealDirs(unittest.TestCase):
    def setUp(self):
        super(TestSharedPathsRealDirs, self).setUp()
        self.root = _tmpdir("real")
        self.mod_root = os.path.join(self.root, "Mods")
        os.makedirs(self.mod_root, exist_ok=True)

    def _survey(self, spec, cfg=None, mods=None):
        _Mods(self.mod_root, spec)
        names = mods if mods is not None else sorted(spec)
        return conflicts.survey(self.mod_root, [{"dir": n} for n in names], cfg or {})

    def test_two_mods_shipping_the_same_dll_are_reported(self):
        r = self._survey({
            "Alpha": ["Alpha.dll", "manifest.json"],
            "Beta": ["Beta.dll", "Alpha.dll"],
        })
        assert r["checked"] is True
        assert r["total"] == 1
        assert r["conflicts"][0]["path"].lower().endswith("alpha.dll")
        assert r["conflicts"][0]["mods"] == ["Alpha", "Beta"]

    def test_manifest_json_is_not_a_conflict(self):
        # Every SMAPI mod ships manifest.json. Reporting it would label the
        # whole folder as one big conflict, which is noise, not information.
        r = self._survey({
            "Alpha": ["manifest.json", "Alpha.dll"],
            "Beta": ["manifest.json", "Beta.dll"],
        })
        assert r["total"] == 0

    def test_nested_readme_and_license_are_ignored(self):
        r = self._survey({
            "Alpha": ["docs/README.md", "LICENSE.md", "Alpha.dll"],
            "Beta": ["other/readme.txt", "license", "Beta.dll"],
        })
        assert r["total"] == 0

    def test_same_relative_path_under_different_folders_is_not_a_conflict(self):
        r = self._survey({
            "Alpha": ["assets/a.png"],
            "Beta": ["textures/a.png"],
        })
        assert r["total"] == 0

    def test_case_differences_still_conflict(self):
        r = self._survey({
            "Alpha": ["Assets/Tex.PNG"],
            "Beta": ["assets/tex.png"],
        })
        assert r["total"] == 1

    def test_three_way_conflict_sorts_first(self):
        r = self._survey({
            "Alpha": ["shared/x.bin", "only-a.bin"],
            "Beta": ["shared/x.bin"],
            "Gamma": ["shared/x.bin", "pair/y.bin"],
            "Delta": ["pair/y.bin"],
        })
        assert r["total"] == 2
        assert r["conflicts"][0]["path"].lower().endswith("shared/x.bin")
        assert len(r["conflicts"][0]["mods"]) == 3
        assert len(r["conflicts"][1]["mods"]) == 2

    def test_dot_directories_are_not_walked(self):
        r = self._survey({
            "Alpha": ["Alpha.dll"],
            "Beta": [".hidden/secret.dll", "Beta.dll"],
        })
        assert r["total"] == 0

    def test_the_scan_writes_nothing(self):
        spec = {"Alpha": ["Alpha.dll"], "Beta": ["Alpha.dll"]}
        _Mods(self.mod_root, spec)
        before = {}
        for dirpath, _d, files in os.walk(self.mod_root):
            for fn in files:
                p = os.path.join(dirpath, fn)
                before[p] = (os.path.getsize(p), os.path.getmtime(p))
        conflicts.survey(self.mod_root, [{"dir": "Alpha"}, {"dir": "Beta"}], {})
        after = {}
        for dirpath, _d, files in os.walk(self.mod_root):
            for fn in files:
                p = os.path.join(dirpath, fn)
                after[p] = (os.path.getsize(p), os.path.getmtime(p))
        assert before == after


class TestBounds(unittest.TestCase):
    def setUp(self):
        super(TestBounds, self).setUp()
        self.root = _tmpdir("bounds")
        self.mod_root = os.path.join(self.root, "Mods")
        os.makedirs(self.mod_root, exist_ok=True)

    def test_per_mod_file_cap_sets_truncated(self):
        spec = {"Big": ["f%04d.bin" % i for i in range(30)], "Small": ["s.bin"]}
        _Mods(self.mod_root, spec)
        r = conflicts.survey(self.mod_root, [{"dir": "Big"}, {"dir": "Small"}],
                             {"max_files_per_mod": 10})
        assert r["truncated"] is True
        assert r["checked"] is True

    def test_conflict_cap_sets_truncated_and_limits_rows(self):
        spec = {
            "Alpha": ["c%d.bin" % i for i in range(10)],
            "Beta": ["c%d.bin" % i for i in range(10)],
        }
        _Mods(self.mod_root, spec)
        r = conflicts.survey(self.mod_root, [{"dir": "Alpha"}, {"dir": "Beta"}],
                             {"max_conflicts": 4})
        assert r["truncated"] is True
        assert len(r["conflicts"]) == 4
        assert r["total"] == 4

    def test_missing_mod_directory_is_skipped_not_fatal(self):
        _Mods(self.mod_root, {"Alpha": ["Alpha.dll"]})
        r = conflicts.survey(self.mod_root, [{"dir": "Alpha"}, {"dir": "Ghost"}], {})
        assert r["checked"] is True
        assert r["mods_scanned"] == 1

    def test_disabled_in_descriptor_reports_so_without_scanning(self):
        r = conflicts.survey(self.mod_root, [{"dir": "Alpha"}], {"enabled": False})
        assert r["checked"] is False
        assert r["reason"] == "disabled_in_descriptor"
        assert r["conflicts"] == []

    def test_a_per_mod_directory_loader_reports_no_conflicts(self):
        # The device measured 27 of 27 "conflicts" on a real Stardew tree, and
        # every one of them was a per-mod file (config.json / i18n/*.json) that
        # a per-mod-directory loader cannot collide on. The descriptor now says
        # which model it is, and this loader must answer zero rather than lie.
        spec = {
            "Alpha": ["config.json", "i18n/zh.json", "Alpha.dll"],
            "Beta": ["config.json", "i18n/zh.json", "Beta.dll"],
        }
        _Mods(self.mod_root, spec)
        r = conflicts.survey(self.mod_root, [{"dir": "Alpha"}, {"dir": "Beta"}],
                             {"scope": "per_mod_directory"})
        assert r["checked"] is False
        assert r["reason"] == "per_mod_directory_loader"
        assert r["total"] == 0
        assert r["conflicts"] == []

    def test_a_shared_tree_loader_still_reports_the_same_fixture(self):
        # Same tree, opposite scope: the collision is real again, which proves
        # the scope flag is what changed the answer and not the fixture.
        spec = {
            "Alpha": ["plugins/X.dll", "readme.md"],
            "Beta": ["plugins/X.dll", "readme.md"],
        }
        _Mods(self.mod_root, spec)
        r = conflicts.survey(self.mod_root, [{"dir": "Alpha"}, {"dir": "Beta"}],
                             {"scope": "shared_tree", "ignore": ["readme.md"]})
        assert r["checked"] is True
        assert r["total"] == 1
        assert r["conflicts"][0]["path"].lower().endswith("x.dll")


class TestIgnorePatterns(unittest.TestCase):
    """Glob patterns, because a literal ``i18n/*.json`` matched nothing."""

    def setUp(self):
        super(TestIgnorePatterns, self).setUp()
        self.root = _tmpdir("glob")
        self.mod_root = os.path.join(self.root, "Mods")
        os.makedirs(self.mod_root, exist_ok=True)

    def test_a_wildcard_pattern_ignores_every_translation_file(self):
        spec = {
            "Alpha": ["i18n/zh.json", "i18n/de.json", "Alpha.dll"],
            "Beta": ["i18n/zh.json", "i18n/de.json", "Beta.dll"],
        }
        _Mods(self.mod_root, spec)
        r = conflicts.survey(self.mod_root, [{"dir": "Alpha"}, {"dir": "Beta"}],
                             {"scope": "shared_tree", "ignore": ["i18n/*.json"]})
        assert r["total"] == 0, r

    def test_a_bare_filename_pattern_matches_at_any_depth(self):
        spec = {
            "Alpha": ["nested/deep/config.json", "Alpha.dll"],
            "Beta": ["config.json", "Beta.dll"],
        }
        _Mods(self.mod_root, spec)
        r = conflicts.survey(self.mod_root, [{"dir": "Alpha"}, {"dir": "Beta"}],
                             {"scope": "shared_tree", "ignore": ["config.json"]})
        assert r["total"] == 0, r

    def test_a_pattern_that_matches_nothing_changes_nothing(self):
        # The failure mode that made the bug invisible: a pattern that can
        # never match must not silently swallow the whole report.
        spec = {"Alpha": ["a.dll"], "Beta": ["a.dll"]}
        _Mods(self.mod_root, spec)
        r = conflicts.survey(self.mod_root, [{"dir": "Alpha"}, {"dir": "Beta"}],
                             {"scope": "shared_tree", "ignore": ["*.css"]})
        assert r["total"] == 1, r


class TestModuleShape(unittest.TestCase):
    def _src(self):
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "deckymod", "conflicts.py")
        with io.open(p, encoding="utf-8") as f:
            return f.read()

    def test_module_contains_no_game_specific_literal(self):
        low = self._src().lower()
        for bad in ("stardew", "413150", "smapi", "stardewvalley"):
            assert bad not in low, bad

    def test_module_performs_no_write_operations(self):
        tree = ast.parse(self._src())
        roots = ("os", "shutil")
        banned = {"makedirs", "mkdir", "remove", "unlink", "rmtree", "rename",
                  "replace", "chmod", "symlink", "copy", "copy2", "move",
                  "write", "write_text", "write_bytes"}
        called = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute):
                chain = []
                cur = func
                while isinstance(cur, ast.Attribute):
                    chain.append(cur.attr)
                    cur = cur.value
                if isinstance(cur, ast.Name):
                    chain.append(cur.id)
                    chain.reverse()
                    if chain[0] in roots and chain[-1] in banned:
                        called.add(".".join(chain))
        assert not called, called
        # open() must never be used in a write mode
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "open":
                for arg in node.args[1:2]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        assert not (set(arg.value) & set("wax+")), arg.value


class TestDescribe(unittest.TestCase):
    def test_unchecked_reports_empty(self):
        assert conflicts.describe({"checked": False}) == ""

    def test_no_conflicts_reports_empty(self):
        assert conflicts.describe({"checked": True, "total": 0, "conflicts": []}) == ""

    def test_more_than_limit_is_summarised(self):
        r = {"checked": True, "total": 5,
             "conflicts": [{"path": "p%d.bin" % i, "mods": ["A", "B"]} for i in range(5)]}
        s = conflicts.describe(r, limit=2)
        assert "p0.bin" in s and "p1.bin" in s and "+3 more" in s
