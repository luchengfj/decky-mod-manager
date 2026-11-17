"""Removing the plugin must not touch the user's mods.

docs/NEXT_FEATURES.md item 8 has said, since the first draft, that the plugin
"removes only its own data directory" and that "no test asserts that about the
user's Mods/". The first half was true when written -- `_uninstall` sets
`self.engine = None` and logs a line -- but a claim with no test is a claim that
survives only until somebody edits the hook.

This is the cheapest possible version of that test: call the three lifecycle
hooks the way Decky does, with a real engine pointed at a real tree, and assert
byte-for-byte that nothing under the game folder changed.

The awkward part is worth spelling out, because it is the reason this was never
tested before: the hooks are meant to be called by Decky, and a test that calls
them directly proves only what the code does when called directly. That is
still the whole of the contract here -- `_uninstall` has no branch that depends
on how it was invoked -- so the test is honest as long as it says what it is.
"""
import hashlib
import io
import os
import sys
import unittest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

import main as plugin_main  # noqa: E402  (after sys.path fix)

# The pin must be dropped when THIS module starts running, never at import.
# unittest discovery imports every module before running any of them, so
# popping at module level (which is what the first draft did) removes
# test_mvp.py's setdefault("DECKYMOD_GAME_ID", "rimworld") before test_mvp
# executes -- nine of its tests then resolve 413150 against a RimWorld-shaped
# tree. This is the third time this exact trap has been hit in this repo.
_SAVED_GAME_ID = None


def setUpModule():
    global _SAVED_GAME_ID
    _SAVED_GAME_ID = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    global _SAVED_GAME_ID
    if _SAVED_GAME_ID is not None:
        os.environ["DECKYMOD_GAME_ID"] = _SAVED_GAME_ID
    else:
        os.environ.pop("DECKYMOD_GAME_ID", None)
    _SAVED_GAME_ID = None


def _fingerprint(root):
    """Every path under root, with size, mtime and a hash of the bytes.

    mtime is included on purpose: a hook that rewrote a file with identical
    content would still have touched the user's tree, and "the bytes are the
    same" is a weaker promise than "nothing was opened for writing".
    """
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            p = os.path.join(dirpath, name)
            rel = os.path.relpath(p, root).replace("\\", "/")
            try:
                st = os.stat(p)
                with io.open(p, "rb") as f:
                    digest = hashlib.sha256(f.read()).hexdigest()
            except OSError as exc:
                out[rel] = ("unreadable", str(exc))
                continue
            out[rel] = (st.st_size, st.st_mtime_ns, digest)
        for name in sorted(dirnames):
            rel = os.path.relpath(os.path.join(dirpath, name), root).replace("\\", "/")
            out[rel + "/"] = ("dir",)
    return out


class _Tree(object):
    """A game folder with mods already in it, plus a plugin data dir."""

    def __init__(self, tag):
        import uuid
        base = os.path.join(_REPO, ".decky-test-tmp",
                            "r61_%s_%s" % (tag, uuid.uuid4().hex[:8]))
        os.makedirs(base)
        self.base = base
        steam = os.path.join(base, "Steam")
        self.sapps = os.path.join(steam, "steamapps")
        self.game = os.path.join(self.sapps, "common", "Stardew Valley")
        self.mods = os.path.join(self.game, "Mods")
        self.data = os.path.join(base, "data")
        self.home = os.path.join(base, "home")
        self.xdg = os.path.join(base, "xdg")
        self.logs = os.path.join(base, "logs")
        for d in (self.mods, self.data, self.home, self.xdg, self.logs,
                  os.path.join(self.game, "smapi-internal")):
            os.makedirs(d, exist_ok=True)
        self._write(os.path.join(self.game, "StardewModdingAPI"), b"\x7fELF")
        self._write(os.path.join(self.game, "StardewModdingAPI.dll"), b"MZ")
        self._write(os.path.join(self.sapps, "libraryfolders.vdf"),
                    ('"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n'
                     % steam).encode())
        self._write(os.path.join(self.sapps, "appmanifest_413150.acf"),
                    b'"AppState"\n{\n\t"appid"\t\t"413150"\n\t"installdir"\t\t"Stardew Valley"\n}\n')
        # Two mods the user installed by hand: the plugin does not own them.
        self.mods_of_user = []
        for name, uid in (("Automate", "Pathoschild.Automate"),
                          ("ContentPatcher", "Pathoschild.ContentPatcher")):
            d = os.path.join(self.mods, name)
            os.makedirs(d, exist_ok=True)
            self._write(os.path.join(d, "manifest.json"),
                        ('{"Name":"%s","Version":"1.0.0","UniqueID":"%s"}'
                         % (name, uid)).encode())
            self._write(os.path.join(d, name + ".dll"), b"MZ" + b"\0" * 32)
            self.mods_of_user.append(name)
        # Something the plugin does own, so the journal is not empty.
        self._write(os.path.join(self.data, "journal", "stardew.jsonl"),
                    b'{"event":"MOD_INSTALLED","txn":"20260101T000000-aaaaaaaa",'
                    b'"packageId":"someone.owned","dir":"someone.owned"}\n')
        self._env = {}

    def _write(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with io.open(path, "wb") as f:
            f.write(data)

    def enter(self):
        self._env = {k: os.environ.get(k) for k in (
            "DECKYMOD_STEAM_ROOT", "DECKY_USER_HOME", "XDG_CONFIG_HOME",
            "DECKYMOD_DATA", "DECKYMOD_INBOX", "DECKY_MOD_LOG_DIR", "DECKYMOD_GAME_RUNNING")}
        os.environ["DECKYMOD_STEAM_ROOT"] = os.path.join(self.base, "Steam")
        os.environ["DECKY_USER_HOME"] = self.home
        os.environ["XDG_CONFIG_HOME"] = self.xdg
        os.environ["DECKYMOD_DATA"] = self.data
        os.environ["DECKYMOD_INBOX"] = os.path.join(self.base, "inbox")
        os.environ["DECKY_MOD_LOG_DIR"] = self.logs
        os.environ.pop("DECKYMOD_GAME_RUNNING", None)

    def leave(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def remove(self):
        import shutil
        shutil.rmtree(self.base, ignore_errors=True)


class TestLifecycleHooksLeaveUserDataAlone(unittest.TestCase):
    def setUp(self):
        self.t = _Tree("life")
        self.addCleanup(self.t.remove)
        self.t.enter()
        self.addCleanup(self.t.leave)
        self.p = plugin_main.Plugin()

    def test_unload_does_not_touch_the_game_folder(self):
        """_unload drops caches; it must not write into Mods/."""
        import asyncio
        # Build an engine first, so the hook has something to tear down.
        asyncio.run(self.p._main())
        self.assertIsNotNone(self.p.engine)
        before = _fingerprint(self.t.game)
        asyncio.run(self.p._unload())
        after = _fingerprint(self.t.game)
        self.assertEqual(sorted(before), sorted(after))
        for rel, sig in before.items():
            self.assertEqual(after.get(rel), sig, "%s changed during _unload" % rel)
        self.assertIsNone(self.p.engine, "the engine should be released")

    def test_uninstall_does_not_delete_anything_under_the_game_folder(self):
        """Decky calls this when the user removes the plugin.

        The hard promise is narrow and total: every file that existed before
        still exists, with the same bytes. The plugin's own data directory is
        outside the game folder, so nothing here may be removed "because the
        plugin is going away".
        """
        import asyncio
        asyncio.run(self.p._main())
        before_game = _fingerprint(self.t.game)
        before_data = _fingerprint(self.t.data)
        for name in self.t.mods_of_user:
            self.assertTrue(os.path.isdir(os.path.join(self.t.mods, name)))

        asyncio.run(self.p._uninstall())

        after_game = _fingerprint(self.t.game)
        after_data = _fingerprint(self.t.data)
        self.assertEqual(sorted(before_game), sorted(after_game),
                         "the game folder gained or lost entries during _uninstall")
        for rel, sig in before_game.items():
            self.assertEqual(after_game.get(rel), sig,
                             "%s was modified by _uninstall" % rel)
        # The journal is the rollback history; removal must not silently drop it.
        self.assertEqual(sorted(before_data), sorted(after_data),
                         "the plugin data directory changed during _uninstall")

    def test_migration_does_not_touch_the_game_folder(self):
        import asyncio
        asyncio.run(self.p._main())
        before = _fingerprint(self.t.game)
        result = asyncio.run(self.p._migration())
        self.assertIsNone(result)
        after = _fingerprint(self.t.game)
        self.assertEqual(before, after, "_migration wrote inside the game folder")

    def test_the_hooks_are_harmless_before_the_engine_exists(self):
        """Decky may unload a plugin whose _main() never finished."""
        import asyncio
        self.assertIsNone(self.p.engine)
        asyncio.run(self.p._unload())
        asyncio.run(self.p._uninstall())
        asyncio.run(self.p._migration())
        self.assertIsNone(self.p.engine)


class TestTheHooksDoNotCallWritePaths(unittest.TestCase):
    """Structural half: the promise should not depend on the tree we picked.

    A behavioural test above only proves the hooks are innocent on one tree.
    This asserts they contain no call that could write -- so a future edit that
    adds `self.engine.uninstall(...)` to `_uninstall` fails here even if the
    tree happens to survive it.
    """

    _BANNED = {
        "remove", "unlink", "rmtree", "rmdir", "makedirs", "mkdir", "rename",
        "replace", "chmod", "symlink", "copy", "copy2", "move", "write",
        "write_text", "write_bytes", "truncate", "fsync",
    }
    _ENGINE_WRITES = {
        "install", "uninstall", "set_enabled", "rollback", "handover_mods",
        "reclaim_quarantine",
    }

    def _hook(self, name):
        import ast
        with io.open(os.path.join(_REPO, "main.py"), encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "Plugin":
                for m in node.body:
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name == name:
                        return m
        self.fail("hook %s not found" % name)

    def test_no_hook_calls_a_write_primitive(self):
        import ast
        for hook in ("_unload", "_uninstall", "_migration"):
            fn = self._hook(hook)
            hits = []
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                f = node.func
                name = None
                if isinstance(f, ast.Attribute):
                    name = f.attr
                elif isinstance(f, ast.Name):
                    name = f.id
                if name in self._BANNED:
                    hits.append(name)
            self.assertEqual(hits, [], "%s calls a write primitive: %s" % (hook, hits))

    def test_no_hook_calls_an_engine_mutating_method(self):
        for hook in ("_unload", "_uninstall", "_migration"):
            fn = self._hook(hook)
            src = self._source_of(fn)
            for meth in self._ENGINE_WRITES:
                self.assertNotIn(
                    "." + meth + "(", src,
                    "%s calls engine.%s(); removing the plugin must not "
                    "mutate game state" % (hook, meth),
                )

    def test_uninstall_only_mentions_its_own_data_in_comments(self):
        """The docstring may promise things; the body must actually do nothing."""
        fn = self._hook("_uninstall")
        body = self._source_of(fn)
        # Strip the docstring, then look for any path manipulation at all.
        import ast
        stmt_wo_doc = [s for s in fn.body
                       if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
        self.assertLessEqual(len(stmt_wo_doc), 3,
                             "_uninstall grew: %d statements besides its docstring" % len(stmt_wo_doc))
        # The hook is exactly a log line and a release; no return statement is
        # needed and asserting one would fail on correct code (it did, first run).
        for word in ("self.engine =", "_log("):
            self.assertIn(word, body)

    def _source_of(self, fn):
        import ast
        with io.open(os.path.join(_REPO, "main.py"), encoding="utf-8") as f:
            src = f.read()
        return ast.get_source_segment(src, fn) or ""


if __name__ == "__main__":
    unittest.main()
