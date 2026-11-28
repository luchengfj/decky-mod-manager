"""Contract: the plugin stores no credential at all, and promises no search.

Full circle, and the reasoning is worth keeping because it repeated:

* round 29 removed the credential store — the source it served answered 403 to
  every free account, so a stored key bought nothing.
* round 39 brought it back for *metadata only*, where a free key did work: mod
  info, file lists and the three feeds answered 200.
* round 88 removes it again, for a different and stronger reason. A free key
  could read metadata but never download (``download_link`` answers 403 "this
  is for premium users only"), the API has no keyword-search endpoint, and the
  website's HTML is behind Cloudflare for every non-browser client. So the key
  bought nothing the panel could turn into a mod on disk. What it did buy was a
  secret to hold, a file to protect at 0600 and a "no usable stored key" dead
  end on the update check. The website openers replaced it: they need no key
  and they are where a download actually happens.

The assertions that matter now are the negative ones — the surface, its file
and its RPCs must stay gone — plus the positive one that the no-key openers
survived. Search is still forbidden as an RPC: the endpoint does not exist, so
a ``nexus_search`` would be a promise the backend cannot keep.
"""
import ast
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: RPCs that read, wrote or served a credential, plus the two that existed only
#: to spend one. All eight must stay gone: their absence is the invariant.
RETIRED_RPCS = ("api_key_status", "set_api_key", "delete_api_key",
                "nexus_validate", "nexus_recent", "nexus_mod",
                "nexus_download_link", "check_mod_updates")

#: RPCs that open a Nexus page in the signed-in browser. These never needed a
#: key, which is exactly why they are what remains of the Nexus surface.
NO_KEY_OPENERS = ("open_mod_page", "open_search_page", "open_browse_page")


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
        # Round 79: +install_loader, +open_loader_page (loader hand-off).
        # Round 84: +archive_mods (multi-mod archives get a picker).
        # Round 88: -8 credential/metadata/update-check RPCs.
        self.assertEqual(len(rpc), 30, rpc)

    def test_download_rpcs_are_still_present(self):
        plugin, _ = _plugin_methods()
        rpc = {b.name for b in _public_rpc(plugin)}
        for name in ("gh_search", "gh_releases", "gh_download", "download_url",
                     "fetch_dependencies"):
            self.assertIn(name, rpc, name)

    def test_the_credential_rpcs_are_gone(self):
        plugin, _ = _plugin_methods()
        rpc = {b.name for b in _public_rpc(plugin)}
        for name in RETIRED_RPCS:
            self.assertNotIn(name, rpc, name)

    def test_the_no_key_openers_survived(self):
        plugin, _ = _plugin_methods()
        rpc = {b.name for b in _public_rpc(plugin)}
        for name in NO_KEY_OPENERS:
            self.assertIn(name, rpc, name)


class TestNoCredentialLeftBehind(unittest.TestCase):
    """Deleting the RPCs is not enough: the store, the secret's file name and
    the update check that spent it must all be gone too. A leftover
    ``credentials.py`` would be dead code that still looks callable."""

    def test_the_credential_module_is_deleted(self):
        self.assertFalse(os.path.exists(
            os.path.join(ROOT, "deckymod", "credentials.py")))
        self.assertFalse(os.path.exists(
            os.path.join(ROOT, "deckymod", "update_check.py")))

    def test_main_imports_neither(self):
        with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("from deckymod import credentials", src)
        self.assertNotIn("from deckymod import update_check", src)
        self.assertNotIn("api_key", src)

    def test_no_rpc_takes_a_key_argument(self):
        plugin, _ = _plugin_methods()
        for node in _public_rpc(plugin):
            params = [a.arg for a in node.args.args if a.arg != "self"]
            self.assertNotIn("api_key", params, node.name)

    def test_the_named_key_file_is_gone(self):
        # The filename is the one string that would survive a refactor: if it
        # is back, so is the store.
        for root, dirs, files in os.walk(os.path.join(ROOT, "deckymod")):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                with open(os.path.join(root, fn), encoding="utf-8") as f:
                    body = f.read()
                self.assertNotIn("nexus_api_key", body, fn)


class TestNexusModuleIsUrlOnly(unittest.TestCase):
    """``deckymod/nexus.py`` survives as a URL builder. It must not have
    regained a transport, an API host or a header carrying a secret."""

    def _tree(self):
        with open(os.path.join(ROOT, "deckymod", "nexus.py"),
                  encoding="utf-8") as f:
            return ast.parse(f.read())

    def test_it_imports_no_network_layer(self):
        tree = self._tree()
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                # ``from __future__ import annotations`` is a compiler flag,
                # not an import of anything at run time.
                if node.module != "__future__":
                    imported.add(node.module or "")
        self.assertEqual(imported, {"urllib.parse"}, imported)

    def test_it_declares_no_api_host(self):
        # Checked against the CODE, not the prose: the docstring deliberately
        # names the host while explaining why it was removed.
        tree = self._tree()
        doc = ast.get_docstring(tree, clean=False) or ""
        strings = [n.value for n in ast.walk(tree)
                   if isinstance(n, ast.Constant) and isinstance(n.value, str)
                   and n.value != doc]
        joined = "\n".join(strings)
        # The website host is the whole point; it is the API subdomain that
        # must not come back, because that is the one that needs a key.
        self.assertNotIn("api.nexusmods.com", joined)
        self.assertIn("www.nexusmods.com", joined)
        self.assertNotIn("apikey", joined.lower())
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        names |= {t.id for n in ast.walk(tree) if isinstance(n, ast.Assign)
                  for t in n.targets if isinstance(t, ast.Name)}
        self.assertNotIn("API_ROOT", names)
        self.assertNotIn("API_HOST", names)
        self.assertNotIn("H_KEY", names)

    def test_the_three_url_builders_are_public(self):
        tree = self._tree()
        names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
        for name in ("mod_page_url", "search_page_url", "browse_page_url"):
            self.assertIn(name, names)


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


class TestEveryReasonWordHasASentence(unittest.TestCase):
    """The reason vocabulary is a contract between three files.

    ``main.py`` emits ``data={"reason": "<word>"}``, ``reasonText()`` turns that
    word into ``ERRR_<WORD>``, and the two dictionaries have to hold that key.
    Nothing used to check the three-way agreement, so Round 88's deletion left
    ``ERRR_NO_KEY`` and ``ERRR_KEY_REJECTED`` behind as sentences for reasons no
    code could emit any more — dead translations that still looked live. This
    test is the check that would have caught it.
    """

    def _emitted(self) -> set:
        with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
            src = f.read()
        return {"ERRR_" + w.upper()
                for w in re.findall(r'"reason": "([a-z_]+)"', src)}

    def _declared(self, lang: str) -> set:
        with open(os.path.join(ROOT, "src", "i18n", lang + ".json"),
                  encoding="utf-8") as f:
            return {k for k in json.load(f) if k.startswith("ERRR_")}

    def test_every_emitted_reason_has_en_and_zh_text(self):
        emitted = self._emitted()
        self.assertTrue(emitted, "no reason words found — the regex broke")
        for lang in ("en", "zh-CN"):
            missing = emitted - self._declared(lang)
            self.assertEqual(missing, set(), "%s lacks %s" % (lang, missing))

    def test_no_reason_sentence_is_left_without_an_emitter(self):
        # The reverse direction: a sentence nobody can trigger is dead weight
        # in two dictionaries and a lie about what the plugin can say.
        for lang in ("en", "zh-CN"):
            orphans = self._declared(lang) - self._emitted()
            self.assertEqual(orphans, set(), "%s has orphans %s"
                             % (lang, orphans))

    def test_the_two_dictionaries_agree(self):
        self.assertEqual(self._declared("en"), self._declared("zh-CN"))
