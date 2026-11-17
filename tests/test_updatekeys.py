"""Tests for deckymod/updatekeys.py.

The two channel shapes here are copied verbatim from manifests on the device
(``Nexus:21147@New``, ``Nexus:9695@Regular``). A strict id-only pattern would
drop both silently, which is the failure this module exists to avoid.
"""
import io
import os
import unittest

from deckymod import updatekeys


class TestParse(unittest.TestCase):
    def test_plain_nexus_key(self):
        self.assertEqual(updatekeys.parse(["Nexus:1063"]),
                         [{"site": "nexus", "id": "1063", "channel": ""}])

    def test_channel_suffix_is_kept_off_the_id(self):
        got = updatekeys.parse(["Nexus:21147@New"])
        self.assertEqual(got, [{"site": "nexus", "id": "21147",
                                "channel": "New"}])

    def test_regular_channel_shape(self):
        got = updatekeys.parse(["Nexus:9695@Regular"])
        self.assertEqual(got[0]["id"], "9695")
        self.assertEqual(got[0]["channel"], "Regular")

    def test_bare_string_is_accepted(self):
        self.assertEqual(len(updatekeys.parse("Nexus:42")), 1)

    def test_surrounding_space_is_tolerated(self):
        self.assertEqual(updatekeys.parse("  Nexus : 42  ")[0]["id"], "42")

    def test_site_is_lowercased(self):
        self.assertEqual(updatekeys.parse(["GitHub:owner/repo"])[0]["site"],
                         "github")

    def test_nexus_sorts_first(self):
        got = updatekeys.parse(["GitHub:a/b", "Nexus:7"])
        self.assertEqual([g["site"] for g in got], ["nexus", "github"])

    def test_duplicates_collapse(self):
        got = updatekeys.parse(["Nexus:7", "nexus:7", "NEXUS:7"])
        self.assertEqual(len(got), 1)

    def test_junk_is_dropped_not_reported(self):
        for bad in ([None, 3, {}, [], ""], {"a": 1}, None, 7):
            self.assertEqual(updatekeys.parse(bad), [])

    def test_a_url_is_not_an_update_key(self):
        # "https://example.com/x" would parse as site=https otherwise: a shape
        # that looks valid and means nothing.
        self.assertEqual(updatekeys.parse(["https://example.com/x"]), [])

    def test_empty_id_is_dropped(self):
        self.assertEqual(updatekeys.parse(["Nexus:"]), [])

    def test_overlong_id_is_dropped(self):
        self.assertEqual(updatekeys.parse(["Nexus:" + "9" * 40]), [])

    def test_list_is_capped(self):
        many = ["Nexus:%d" % i for i in range(200)]
        self.assertLessEqual(len(updatekeys.parse(many)), updatekeys.MAX_KEYS)


class TestIdFor(unittest.TestCase):
    def test_returns_the_id_for_the_site(self):
        self.assertEqual(updatekeys.id_for(["Nexus:1063", "GitHub:a/b"],
                                           "nexus"), "1063")

    def test_site_match_is_case_insensitive(self):
        self.assertEqual(updatekeys.id_for(["Nexus:1063"], "NEXUS"), "1063")

    def test_absent_site_is_empty_not_none(self):
        self.assertEqual(updatekeys.id_for(["GitHub:a/b"], "nexus"), "")

    def test_channel_does_not_contaminate_the_id(self):
        self.assertEqual(updatekeys.id_for(["Nexus:21147@New"], "nexus"),
                         "21147")

    def test_parsed_entries_are_accepted_as_input(self):
        # A caller holding the wire payload must not silently get "" back.
        parsed = updatekeys.parse(["Nexus:1063"])
        self.assertEqual(updatekeys.id_for(parsed, "nexus"), "1063")

    def test_parsed_channel_entries_survive_a_round_trip(self):
        parsed = updatekeys.parse(["Nexus:21147@New"])
        self.assertEqual(updatekeys.id_for(parsed, "nexus"), "21147")
        self.assertEqual(updatekeys.parse(parsed)[0]["channel"], "New")


class TestNoGameLiterals(unittest.TestCase):
    def setUp(self):
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "deckymod", "updatekeys.py")
        with io.open(path, encoding="utf-8") as f:
            self.src = f.read()

    def test_module_has_no_game_literals(self):
        low = self.src.lower()
        for bad in ("stardew", "413150", "smapi", "stardewvalley"):
            self.assertNotIn(bad, low)

    def test_module_does_not_write(self):
        import ast
        tree = ast.parse(self.src)
        called = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name):
                    called.add(fn.id)
                elif isinstance(fn, ast.Attribute):
                    called.add(fn.attr)
        for banned in ("open", "makedirs", "mkdir", "remove", "unlink",
                       "rename", "replace", "write", "write_text"):
            self.assertNotIn(banned, called)


if __name__ == "__main__":
    unittest.main()
