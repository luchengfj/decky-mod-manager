"""Contract: the plugin HAS a credential surface, and it stays opaque.

History that matters here: round 29 removed the credential store because the
third-party source it served answered 403 to every free account, so a stored
key bought nothing. That file then asserted the surface was absent — an
accurate assertion for a version whose honest answer was "this cannot work".

Round 39 reverses the premise deliberately: the same API is now used for
*metadata only*, where a free key genuinely works, and the goal explicitly asks
for credentials to be entered in the panel. So the old "must not exist"
assertions are replaced by narrower, stronger ones about what the surface may
do. What is forbidden now is not the feature but the leak:

* no RPC may return the key, masked or not (``key_status`` is stat-only)
* the key must never be an argument to the validation call (it is read from
  disk, so it never crosses the bridge twice)
* no RPC may expose a keyword search, because the endpoint does not exist
"""
import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Every RPC that reads or writes the credential. Their signatures are audited
#: below for key material in the wrong direction.
CREDENTIAL_RPCS = ("api_key_status", "set_api_key", "delete_api_key",
                   "nexus_validate")


def _plugin_methods():
    with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    plugin = next(n for n in tree.body
                  if isinstance(n, ast.ClassDef) and n.name == "Plugin")
    return plugin, tree


def _public_rpc(plugin):
    return [b for b in plugin.body
            if isinstance(b, ast.AsyncFunctionDef) and not b.name.startswith("_")]


class TestRpcSurface(unittest.TestCase):
    def test_public_rpc_count(self):
        plugin, _ = _plugin_methods()
        rpc = [b.name for b in _public_rpc(plugin)]
        self.assertEqual(len(rpc), 26, rpc)

    def test_download_rpcs_are_still_present(self):
        plugin, _ = _plugin_methods()
        rpc = {b.name for b in _public_rpc(plugin)}
        for name in ("gh_search", "gh_releases", "gh_download", "download_url",
                     "fetch_dependencies"):
            self.assertIn(name, rpc, name)

    def test_credential_rpcs_are_present(self):
        plugin, _ = _plugin_methods()
        rpc = {b.name for b in _public_rpc(plugin)}
        for name in CREDENTIAL_RPCS:
            self.assertIn(name, rpc, name)

    def test_nexus_rpcs_are_present(self):
        plugin, _ = _plugin_methods()
        rpc = {b.name for b in _public_rpc(plugin)}
        for name in ("nexus_recent", "nexus_mod", "nexus_download_link"):
            self.assertIn(name, rpc, name)


class TestCredentialDirection(unittest.TestCase):
    def test_validate_takes_no_key_argument(self):
        # Reading the key from disk is what keeps the plaintext off the bridge
        # once it has been saved.
        plugin, _ = _plugin_methods()
        by_name = {b.name: b for b in _public_rpc(plugin)}
        self.assertEqual([a.arg for a in by_name["nexus_validate"].args.args],
                         ["self"],
                         "nexus_validate must not accept a key parameter")

    def test_only_set_api_key_accepts_a_key(self):
        plugin, _ = _plugin_methods()
        for node in _public_rpc(plugin):
            params = [a.arg for a in node.args.args if a.arg != "self"]
            if node.name == "set_api_key":
                self.assertEqual(params, ["api_key"])
            else:
                self.assertNotIn("api_key", params, node.name)

    def test_status_is_stat_only(self):
        # key_status must not open the file: a mode-000 file still reports.
        with open(os.path.join(ROOT, "deckymod", "credentials.py"),
                  encoding="utf-8") as f:
            tree = ast.parse(f.read())
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "key_status")
        called = {n.func.id for n in ast.walk(fn)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        attrs = {n.func.attr for n in ast.walk(fn)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertNotIn("open", called)
        self.assertIn("stat", attrs)


class TestNoSearchPromise(unittest.TestCase):
    """Search is allowed only where it is real.

    Earlier rounds asserted that NO RPC mentions "search", because the Nexus
    API cannot search and an RPC named for it would be a promise the backend
    cannot keep. Round 43 changed the premise without weakening it: the
    *website* has a working search page, so `open_search_page` exists — but it
    may only open that page. It must not return results, and it must not
    touch the network, because the plugin cannot read those results (every
    website page is behind a Cloudflare challenge).
    """

    ALLOWED = {"gh_search", "open_search_page"}

    def test_only_the_two_real_searches_exist(self):
        plugin, _ = _plugin_methods()
        for node in _public_rpc(plugin):
            has_search = "search" in node.name.lower()
            if node.name in self.ALLOWED:
                continue
            self.assertFalse(has_search, "%s looks like a search RPC" % node.name)

    def test_open_search_page_returns_no_results(self):
        # A dict with a "mods" list would be a lie: we never read the results.
        plugin, _ = _plugin_methods()
        fn = None
        for node in _public_rpc(plugin):
            if node.name == "open_search_page":
                fn = node
                break
        self.assertIsNotNone(fn, "open_search_page is missing")
        src = ast.dump(fn)
        for forbidden in ("'mods'", "'results'", "'count'"):
            self.assertNotIn(forbidden, src,
                             "open_search_page must not report results")

    def test_nexus_module_has_no_api_search_function(self):
        # mods/search.json parses "search" as a mod id -> 422. A function that
        # calls it would be dead code shaped like a feature. Building the
        # website's search ADDRESS is not fetching, so search_page_url is fine.
        with open(os.path.join(ROOT, "deckymod", "nexus.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        funcs = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
        self.assertNotIn("search", funcs)
        self.assertNotIn("mod_search", funcs)
        if "search_page_url" in funcs:
            body = ast.dump([n for n in tree.body
                             if isinstance(n, ast.FunctionDef)
                             and n.name == "search_page_url"][0])
            for call in ("_raw", "urlopen", "_get", "open("):
                self.assertNotIn(call, body,
                                 "search_page_url must build a string, not fetch")

    def test_no_html_scraping_in_the_nexus_client(self):
        # Every website page answers a Cloudflare challenge, so a scraper would
        # be dead code that looks like a feature.
        with open(os.path.join(ROOT, "deckymod", "nexus.py"), encoding="utf-8") as f:
            src = f.read()
        for banned in ("BeautifulSoup", "html.parser", "www.nexusmods.com/mods"):
            self.assertNotIn(banned, src, banned)


if __name__ == "__main__":
    unittest.main()
