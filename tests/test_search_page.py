"""Round 43: the keyword search that does not exist in the API.

The Nexus API has no keyword search endpoint — ``mods/search.json`` parses
``search`` as a mod id and answers 422, and ``q=`` / ``game_id=`` /
``/v2/search.json`` are 404. The website has one. So the honest product is:
build the site's search address and open it, rather than pretend to search,
return an empty list, or scrape a Cloudflare challenge.

These tests pin the parts that must not drift: what a query may contain, how
it is escaped into the address, and that the RPC neither downloads nor asks
for a key.
"""

import ast
import io
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from deckymod import nexus, openurl  # noqa: E402


def _main_tree():
    with io.open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
        return ast.parse(f.read())


def _rpc(name):
    for node in ast.walk(_main_tree()):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _calls(fn):
    names, attrs = set(), set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                names.add(f.id)
            elif isinstance(f, ast.Attribute):
                attrs.add(f.attr)
    return names, attrs


class TestCleanQuery(unittest.TestCase):
    def test_a_plain_keyword_is_accepted(self):
        self.assertEqual(nexus.clean_query("SMAPI"), ("SMAPI", None))

    def test_surrounding_whitespace_is_stripped(self):
        self.assertEqual(nexus.clean_query("  automate  "), ("automate", None))

    def test_empty_and_non_text_are_refused(self):
        for bad in ("", "   ", None, 12, 3.5, [], {}):
            query, problem = nexus.clean_query(bad)
            self.assertEqual(query, "", "accepted %r" % (bad,))
            self.assertIsNotNone(problem, "no reason for %r" % (bad,))

    def test_an_over_long_query_is_refused(self):
        query, problem = nexus.clean_query("a" * (nexus.MAX_QUERY_CHARS + 1))
        self.assertEqual(query, "")
        self.assertIn(str(nexus.MAX_QUERY_CHARS), problem)

    def test_a_query_at_the_limit_is_accepted(self):
        text = "a" * nexus.MAX_QUERY_CHARS
        self.assertEqual(nexus.clean_query(text), (text, None))

    def test_control_characters_are_refused(self):
        for ch in ("\n", "\r", "\t", "\x00", "\x1f", "\x7f"):
            query, problem = nexus.clean_query("a%sb" % ch)
            self.assertEqual(query, "", "accepted %r" % (ch,))
            self.assertIsNotNone(problem)

    def test_punctuation_is_legal_text_not_a_control_character(self):
        # A search for "farmer's chests & more" is a normal thing to type.
        text = "farmer's chests & more"
        self.assertEqual(nexus.clean_query(text), (text, None))


class TestSearchUrl(unittest.TestCase):
    def test_the_address_is_the_sites_own_search_page(self):
        self.assertEqual(
            nexus.search_page_url("stardewvalley", "SMAPI"),
            "https://www.nexusmods.com/stardewvalley/search/?gsearch=SMAPI")

    def test_the_query_is_percent_escaped(self):
        url = nexus.search_page_url("stardewvalley", "automate & chests")
        self.assertIn("gsearch=automate%20%26%20chests", url)
        self.assertNotIn(" ", url)
        self.assertEqual(url.count("&"), 0, "an ampersand would add a parameter")

    def test_path_separators_and_fragments_are_escaped(self):
        url = nexus.search_page_url("stardewvalley", "a/b?c#d")
        self.assertIn("/search/?gsearch=a%2Fb%3Fc%23d", url)

    def test_the_game_domain_selects_the_site_section(self):
        self.assertIn("/valheim/search/?", nexus.search_page_url("valheim", "x"))

    def test_the_result_passes_the_open_url_whitelist(self):
        url = nexus.search_page_url("stardewvalley", "SMAPI")
        self.assertIsNone(openurl.validate_url(url),
                          "the page we build must be one we will open")

    def test_a_built_address_is_never_a_plain_http_url(self):
        self.assertTrue(
            nexus.search_page_url("stardewvalley", "q").startswith("https://"))


class TestSearchRpc(unittest.TestCase):
    def test_the_rpc_exists(self):
        self.assertIsNotNone(_rpc("open_search_page"))

    def test_it_takes_a_query_not_a_url(self):
        fn = _rpc("open_search_page")
        self.assertEqual([a.arg for a in fn.args.args], ["self", "query"])

    def test_it_does_not_call_the_download_gate(self):
        # A docstring that names the gate is not a call to it; check the calls.
        names, _attrs = _calls(_rpc("open_search_page"))
        self.assertNotIn("_network_download_gate", names)

    def test_it_does_not_call_any_network_helper(self):
        _names, attrs = _calls(_rpc("open_search_page"))
        for forbidden in ("validate", "recent", "mod_info", "mod_files",
                          "download_link", "download_to_inbox"):
            self.assertNotIn(forbidden, attrs)

    def test_it_builds_the_address_locally_and_opens_it(self):
        _names, attrs = _calls(_rpc("open_search_page"))
        self.assertIn("search_page_url", attrs)
        self.assertIn("open_url", attrs)

    def test_it_never_reads_a_stored_key(self):
        _names, attrs = _calls(_rpc("open_search_page"))
        self.assertNotIn("read_key", attrs)


if __name__ == "__main__":
    unittest.main()
