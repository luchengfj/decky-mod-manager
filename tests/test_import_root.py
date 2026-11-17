"""Round 42 tests: the import surface must see files the user downloaded.

The whole point of this round is a directory the plugin does not own, so these
tests are built around real temporary directories rather than mocks: the failure
being guarded against (a file exists on disk and the panel does not show it) is
invisible to a mock.
"""
import io
import json
import os
import shutil
import sys
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from deckymod import import_root


def _tmpdir(tag):
    """A fresh directory under the workspace.

    NOT ``tempfile.mkdtemp``: it creates the directory with a 0o700 DACL, and
    creating anything INSIDE it then fails with WinError 5 under this sandbox —
    the exact trap other test modules in this repo hit before. ``os.makedirs``
    inherits the workspace ACL, which is what we want.
    """
    base = os.path.join(ROOT, ".decky-test-tmp")
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, "r42_%s_%s" % (tag, uuid.uuid4().hex[:8]))
    os.makedirs(path, exist_ok=False)
    return path


def _touch(path, data=b"PK\x03\x04"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


class TestDescriptorDeclaration(unittest.TestCase):
    """The root set must be DECLARED by the game, not discovered by scanning."""

    def test_stardew_declares_a_downloads_root(self):
        with io.open(os.path.join(ROOT, "registry", "games", "stardew.json"),
                     encoding="utf-8") as f:
            d = json.load(f)
        roots = d["mod_package"].get("import_roots")
        self.assertTrue(roots, "stardew must declare import_roots")
        paths = [r["path"] for r in roots]
        self.assertIn("${XDG_DOWNLOAD}", paths)

    def test_module_never_scans_the_home_directory(self):
        """A plugin that walks $HOME looking for ZIPs is a privacy problem.

        Checked on the AST rather than as a string, because the docstring above
        uses the word 'scan' when explaining why we do not.
        """
        import ast
        with io.open(os.path.join(ROOT, "deckymod", "import_root.py"),
                     encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                names.append(node.attr)
        for forbidden in ("walk", "scandir", "glob"):
            self.assertNotIn(forbidden, names)


class TestRoots(unittest.TestCase):
    def setUp(self):
        self.base = _tmpdir("roots")
        self.addCleanup(shutil.rmtree, self.base, True)
        self.home = os.path.join(self.base, "home")
        self.inbox = os.path.join(self.base, "inbox")
        os.makedirs(self.home, exist_ok=True)
        os.makedirs(self.inbox, exist_ok=True)

    def _desc(self, roots):
        return {"mod_package": {"import_roots": roots}}

    def test_inbox_is_always_first(self):
        os.makedirs(os.path.join(self.home, "Downloads"))
        got = import_root.roots_for(self.inbox, self._desc([
            {"label": "downloads", "path": "${XDG_DOWNLOAD}"}]), self.home)
        self.assertEqual(got[0]["label"], "inbox")
        self.assertEqual(got[0]["path"], self.inbox)

    def test_xdg_download_dir_is_read_from_user_dirs(self):
        with io.open(os.path.join(self.home, ".config", "user-dirs.dirs")
                     if os.path.isdir(os.path.join(self.home, ".config"))
                     else self._mkdir_userdirs(), "w", encoding="utf-8") as f:
            f.write('XDG_DOWNLOAD_DIR="$HOME/MyDownloads"\n')
        os.makedirs(os.path.join(self.home, "MyDownloads"))
        got = import_root.roots_for(self.inbox, self._desc([
            {"label": "downloads", "path": "${XDG_DOWNLOAD}"}]), self.home)
        self.assertEqual(got[1]["path"], os.path.join(self.home, "MyDownloads"))
        self.assertTrue(got[1]["exists"])

    def _mkdir_userdirs(self):
        cfg = os.path.join(self.home, ".config")
        os.makedirs(cfg, exist_ok=True)
        return os.path.join(cfg, "user-dirs.dirs")

    def test_absent_root_is_reported_not_raised(self):
        got = import_root.roots_for(self.inbox, self._desc([
            {"label": "downloads", "path": "${XDG_DOWNLOAD}"}]), self.home)
        self.assertFalse(got[1]["exists"])
        self.assertEqual(got[1]["path"], os.path.join(self.home, "Downloads"))

    def test_unknown_token_is_kept_verbatim(self):
        got = import_root.roots_for(self.inbox, self._desc([
            {"label": "odd", "path": "${NOPE}/x"}]), self.home)
        self.assertIn("${NOPE}", got[1]["path"])

    def test_same_directory_is_not_listed_twice(self):
        got = import_root.roots_for(self.inbox, self._desc([
            {"label": "a", "path": "${USER_HOME}"},
            {"label": "b", "path": "${USER_HOME}"}]), self.home)
        self.assertEqual(len(got), 2)


class TestListing(unittest.TestCase):
    def setUp(self):
        self.base = _tmpdir("list")
        self.addCleanup(shutil.rmtree, self.base, True)
        self.inbox = os.path.join(self.base, "inbox")
        self.dl = os.path.join(self.base, "Downloads")
        os.makedirs(self.inbox)
        os.makedirs(self.dl)

    def _roots(self):
        return [
            {"label": "inbox", "path": self.inbox, "exists": True},
            {"label": "downloads", "path": self.dl, "exists": True},
        ]

    def test_user_download_is_listed_with_its_root(self):
        _touch(os.path.join(self.dl, "CoolMod.zip"), b"PK\x03\x04user")
        items = import_root.list_files(self._roots())
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "CoolMod.zip")
        self.assertEqual(items[0]["root"], "downloads")

    def test_both_roots_appear_and_are_distinguishable(self):
        _touch(os.path.join(self.inbox, "a.zip"))
        _touch(os.path.join(self.dl, "b.zip"))
        items = import_root.list_files(self._roots())
        by_root = {i["root"]: i["name"] for i in items}
        self.assertEqual(by_root, {"inbox": "a.zip", "downloads": "b.zip"})

    def test_same_name_in_both_roots_stays_two_entries(self):
        _touch(os.path.join(self.inbox, "same.zip"), b"PK\x03\x04in")
        _touch(os.path.join(self.dl, "same.zip"), b"PK\x03\x04dl")
        items = import_root.list_files(self._roots())
        self.assertEqual(len(items), 2)
        self.assertEqual({i["root"] for i in items}, {"inbox", "downloads"})

    def test_non_archives_and_symlinks_are_skipped(self):
        _touch(os.path.join(self.dl, "notes.txt"))
        _touch(os.path.join(self.dl, "real.zip"))
        if hasattr(os, "symlink"):
            try:
                os.symlink(os.path.join(self.dl, "real.zip"),
                           os.path.join(self.dl, "link.zip"))
            except (OSError, NotImplementedError):
                pass
        items = import_root.list_files(self._roots())
        names = [i["name"] for i in items]
        self.assertIn("real.zip", names)
        self.assertNotIn("notes.txt", names)
        self.assertNotIn("link.zip", names)

    def test_missing_root_does_not_blank_the_list(self):
        roots = self._roots() + [
            {"label": "gone", "path": os.path.join(self.base, "nope"), "exists": False}]
        _touch(os.path.join(self.dl, "x.zip"))
        items = import_root.list_files(roots)
        self.assertEqual([i["name"] for i in items], ["x.zip"])

    def test_unreadable_root_is_skipped_not_fatal(self):
        ghost = os.path.join(self.base, "ghost")
        roots = [{"label": "ghost", "path": ghost, "exists": True},
                 {"label": "downloads", "path": self.dl, "exists": True}]
        _touch(os.path.join(self.dl, "ok.zip"))
        items = import_root.list_files(roots)
        self.assertEqual([i["name"] for i in items], ["ok.zip"])

    def test_limit_is_applied_per_root(self):
        for i in range(12):
            _touch(os.path.join(self.dl, "m%02d.zip" % i))
        items = import_root.list_files(self._roots(), limit=5)
        self.assertEqual(len(items), 5)

    def test_7z_is_listed_too(self):
        _touch(os.path.join(self.dl, "pack.7z"))
        items = import_root.list_files(self._roots())
        self.assertEqual([i["name"] for i in items], ["pack.7z"])


class TestReadOnly(unittest.TestCase):
    def test_listing_creates_nothing(self):
        base = _tmpdir("ro")
        self.addCleanup(shutil.rmtree, base, True)
        dl = os.path.join(base, "Downloads")
        os.makedirs(dl)
        inbox = os.path.join(base, "inbox")
        os.makedirs(inbox)
        before = sorted(os.listdir(base))
        import_root.roots_for(inbox, {"mod_package": {"import_roots": [
            {"label": "downloads", "path": os.path.join(base, "Downloads")}]}},
            os.path.join(base, "home"))
        import_root.list_files([
            {"label": "downloads", "path": dl, "exists": True}])
        self.assertEqual(sorted(os.listdir(base)), before)
