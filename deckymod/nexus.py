"""Nexus Mods — the website URLs only. No API, no key, no network.

Round 88 removed the ``api.nexusmods.com`` half of this module along with the
Nexus API key. What is left builds three addresses that the user's own
signed-in browser opens:

====================  =====================================================
what                  address
====================  =====================================================
a mod page            ``/GAME/mods/ID`` (or ``/GAME`` when there is no id)
a keyword search      ``/GAME/search/?gsearch=...``
a browse/sort page    ``/GAME/mods?sort=trending|newest|updated``
====================  =====================================================

Why this is all that remains, measured on the device before Round 88:

* the API required a personal key for every call (anonymous answered 401
  "Please provide an authentication method" — there is no anonymous tier);
* a FREE key could read metadata but ``download_link`` still answered 403
  "this is for premium users only", so the key never bought a download;
* the API has no keyword-search endpoint at all (``mods/search.json`` parses
  ``search`` as a mod id and answers 422);
* the website's HTML answers 403 Cloudflare to every non-browser client, so
  scraping was never a fallback.

The honest product was therefore always "browse and inspect, then hand the
download to the browser". Round 88 dropped the key, so the metadata half had
no remaining user: what a free key could do, the website already does better.

Nothing here fetches. ``openurl`` is the only thing that opens these, and it
is what enforces the https/host policy — building a string is not a request.
"""

from __future__ import annotations

import urllib.parse


def mod_page_url(game_domain: str, mod_id) -> str:
    """The human-facing mod page — the deliverable a free account can use."""
    if mod_id is None:
        return "https://www.nexusmods.com/%s" % game_domain
    return "https://www.nexusmods.com/%s/mods/%s" % (game_domain, mod_id)


#: A search keyword is a user string that ends up in a URL another program
#: opens, so it is bounded and stripped of anything that could change the
#: meaning of the address.
MAX_QUERY_CHARS = 64


def clean_query(query) -> tuple[str, str | None]:
    """Return ``(query, problem)``; problem is None when the query is usable."""
    if not isinstance(query, str):
        return "", "query must be text"
    text = query.strip()
    if not text:
        return "", "query is empty"
    if len(text) > MAX_QUERY_CHARS:
        return "", "query is longer than %d characters" % MAX_QUERY_CHARS
    for ch in text:
        if ch in "\r\n\t" or ord(ch) < 0x20 or ord(ch) == 0x7F:
            return "", "query contains a control character"
    return text, None


def search_page_url(game_domain: str, query: str) -> str:
    """The WEBSITE search page for a keyword.

    The API has no keyword search (``mods/search.json`` parses ``search`` as a
    mod id and answers 422), so the only real search is the site's own. This
    builds that address; opening it is ``openurl``'s job. Nothing here fetches.
    """
    return "https://www.nexusmods.com/%s/search/?gsearch=%s" % (
        game_domain, urllib.parse.quote(query, safe=""))


#: Sort values the website's /mods listing accepts. The caller passes one of
#: these KEYS (never a URL); we map to the site's own parameter so a free
#: account can browse "trending / newest / updated" with no API key at all.
_BROWSE_SORTS = {
    "trending": "trending",
    "latest_added": "newest",
    "latest_updated": "updated",
}


def browse_page_url(game_domain: str, sort: str) -> str | None:
    """WEBSITE browse/sort page for a game. Returns None for an unknown sort.

    This is the no-key replacement for the API's recent() endpoint: the site
    already shows Trending / Newest / Updated, and the browser is signed in.
    Nothing is fetched here — the caller hands the URL to openurl.
    """
    param = _BROWSE_SORTS.get(sort)
    if param is None:
        return None
    return "https://www.nexusmods.com/%s/mods?sort=%s" % (game_domain, param)
