"""Round 53: the marker check, and the fact that the descriptor drives it.

Why this file did not exist before: ``detect_external_manager`` lived in
``deckymod/file_drop.py`` and was only ever exercised THROUGH the engine, with
the two Amethyst strings baked in on both sides. Tests that planted
``.mm_deployed`` proved the engine refuses -- they could not show whether the
descriptor's marker list was used or ignored, because the two agreed.

The distinction matters the moment a second game is described: a marker the
plugin does not recognise is a mod tree the plugin will happily write into.
"""

import os
import unittest
import uuid

from deckymod import file_drop

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
"""Repository root, derived from THIS file rather than hard-coded.

The first draft of these three tests wrote ``C:\\ai\\SD\\...`` literally, which
passes on the Windows dev box and fails on the Deck with
``FileNotFoundError: 'C:\\ai\\SD\\deckymod\\smapi.py'`` -- a test that can only
run on one machine proves nothing about the other. The plugin ships to a Deck.
"""

_BASE = os.path.join(_REPO, ".decky-test-tmp")


def _tmpdir(tag):
    path = os.path.join(_BASE, "r53_%s_%s" % (tag, uuid.uuid4().hex[:8]))
    os.makedirs(path)
    return path


class _TreeMixin(object):
    def setUp(self):
        super().setUp()
        self.base = _tmpdir(self._testMethodName[:20])
        self.game = os.path.join(self.base, "Stardew Valley")
        self.mods = os.path.join(self.game, "Mods")
        os.makedirs(self.mods)

    def tearDown(self):
        try:
            import shutil
            shutil.rmtree(self.base, ignore_errors=True)
        finally:
            super().tearDown()


class TestMarkerDetection(_TreeMixin, unittest.TestCase):
    def test_plain_tree_has_no_marker(self):
        self.assertFalse(file_drop.detect_external_manager(self.game, self.mods))

    def test_marker_file_inside_mods_counts(self):
        with open(os.path.join(self.mods, ".mm_deployed"), "wb"):
            pass
        self.assertTrue(file_drop.detect_external_manager(self.game, self.mods))

    def test_marker_directory_beside_mods_counts(self):
        os.makedirs(os.path.join(self.game, "Mods_Core"))
        self.assertTrue(file_drop.detect_external_manager(self.game, self.mods))

    def test_empty_marker_file_is_enough(self):
        """The real Amethyst marker is 0 bytes; size must not matter."""
        path = os.path.join(self.mods, ".mm_deployed")
        with open(path, "wb"):
            pass
        self.assertEqual(os.path.getsize(path), 0)
        self.assertTrue(file_drop.detect_external_manager(self.game, self.mods))

    def test_a_mod_folder_named_like_the_directory_marker_is_not_a_marker(self):
        """WHERE is part of the evidence.

        ``Mods_Core`` is a *directory* marker beside Mods/. A user mod folder
        that happens to be called ``Mods_Core`` sits INSIDE Mods/, and treating
        that as another manager's tree would silently make the plugin read-only
        for someone who did nothing wrong.
        """
        os.makedirs(os.path.join(self.mods, "Mods_Core"))
        self.assertFalse(file_drop.detect_external_manager(self.game, self.mods))

    def test_a_file_beside_mods_is_not_the_directory_marker(self):
        """The mirror case: a *file* named Mods_Core in the game root is not it."""
        with open(os.path.join(self.game, "Mods_Core"), "wb"):
            pass
        self.assertFalse(file_drop.detect_external_manager(self.game, self.mods))


class TestDescriptorDecidesTheMarkers(_TreeMixin, unittest.TestCase):
    def test_a_declared_marker_is_honoured(self):
        with open(os.path.join(self.mods, ".othermgr"), "wb"):
            pass
        self.assertTrue(file_drop.detect_external_manager(
            self.game, self.mods, [".othermgr"]))

    def test_declaring_markers_replaces_the_defaults(self):
        """A descriptor that names its own markers must not inherit Amethyst's.

        Otherwise a plugin for a game whose manager leaves ``.othermgr`` would
        ALSO go read-only on a Stardew-shaped tree it has nothing to do with.
        """
        with open(os.path.join(self.mods, ".mm_deployed"), "wb"):
            pass
        self.assertFalse(file_drop.detect_external_manager(
            self.game, self.mods, [".othermgr"]))

    def test_none_falls_back_to_the_historical_pair(self):
        with open(os.path.join(self.mods, ".mm_deployed"), "wb"):
            pass
        self.assertTrue(file_drop.detect_external_manager(self.game, self.mods, None))

    def test_empty_list_also_falls_back(self):
        """``or`` treats [] as falsy -- pin that, because it is a real choice.

        An empty declaration cannot mean "detect nothing": that would let a
        descriptor typo disable the only guard against writing into another
        manager's tree.
        """
        with open(os.path.join(self.mods, ".mm_deployed"), "wb"):
            pass
        self.assertTrue(file_drop.detect_external_manager(self.game, self.mods, []))

    def test_blank_names_are_ignored(self):
        with open(os.path.join(self.mods, ".othermgr"), "wb"):
            pass
        self.assertTrue(file_drop.detect_external_manager(
            self.game, self.mods, ["", None, ".othermgr"]))


class TestTheDescriptorIsActuallyRead(unittest.TestCase):
    """The engine must pass the descriptor's list through, not just accept one.

    ``file_drop`` accepting a parameter proves nothing about whether any caller
    supplies it -- Round 50's defect was exactly that shape.
    """

    def test_engine_passes_the_descriptor_markers(self):
        import ast
        import io

        path = os.path.join(_REPO, "deckymod", "smapi.py")
        with io.open(path, encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)

        calls = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "detect_external_manager":
                calls.append(node)
        self.assertEqual(len(calls), 2, "both the gate and the probe must pass it")
        for call in calls:
            self.assertEqual(len(call.args), 3,
                             "markers must be the third positional argument")
            third = call.args[2]
            self.assertIsInstance(third, ast.Call)
            self.assertEqual(getattr(third.func, "attr", ""), "_external_markers",
                             "third argument must be self._external_markers()")
            self.assertEqual(third.args, [])
            self.assertEqual(third.keywords, [])

    def test_the_helper_reads_the_declared_key(self):
        import io

        with io.open(os.path.join(_REPO, "deckymod", "smapi.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('det.get("external_manager_markers")', src)

    def test_the_stardew_descriptor_declares_the_amethyst_markers(self):
        import io
        import json

        with io.open(os.path.join(_REPO, "registry", "games", "stardew.json"), encoding="utf-8") as f:
            desc = json.load(f)
        markers = desc["loader_detection"]["external_manager_markers"]
        self.assertEqual(markers, [".mm_deployed", "Mods_Core"])


if __name__ == "__main__":
    unittest.main()
