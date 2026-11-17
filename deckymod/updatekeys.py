"""Read a manifest's self-declared update channels.

A loader-family manifest may declare ``UpdateKeys``: the list of places the mod
publishes itself. Measured on the device, 21 of 30 installed mods declare a
Nexus id, which is exactly the piece needed to answer "take me to this mod's
page" for a mod the user already has -- without guessing, and without asking
anyone to search for the name.

Two real shapes sit on the device today, verbatim:

    ["Nexus:1063"]              -> site nexus, id 1063
    ["Nexus:21147@New"]         -> site nexus, id 21147, channel New

The channel suffix is why a strict ``^Nexus(\\d+)$`` parse is wrong: it would
silently drop two real mods. It is kept separate rather than appended to the
id, because the id is what a page URL is built from and "21147@New" is not an
id.

Nothing here is specific to any game: the field name comes from the
descriptor, so a second game plugs in without touching this file. The site
ordering does prefer ``nexus``, because that is the one site this plugin can
turn an id into a page URL for -- a preference about sites, not about games.
"""
import re
from typing import Dict, List

MAX_KEYS = 40
MAX_SITE_CHARS = 24
MAX_ID_CHARS = 32
MAX_CHANNEL_CHARS = 24

# "<site>:<id>" with an optional "@<channel>". Site is letters only so that a
# URL or a path can never be mistaken for one.
_KEY_RE = re.compile(r"^\s*(?P<site>[A-Za-z][A-Za-z0-9_.-]{0,23})\s*:\s*"
                     r"(?P<id>[^@\s]{1,32})\s*(?:@\s*(?P<channel>[^@\s]{1,24}))?\s*$")

# A URL is not an update key. Without this, "https://example.com/x" parses as
# site="https" with the rest as an id -- a shape that looks valid and means
# nothing, which is worse than dropping it.
_NOT_A_SITE = frozenset({"http", "https", "file", "ftp"})


def _clean(value) -> List[str]:
    """Flatten the declared value into strings, ignoring junk shapes."""
    out: List[str] = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, str):
                out.append(item)
    return out[:MAX_KEYS]


def _already_parsed(value) -> List[Dict[str, str]]:
    """Accept output from :func:`parse` as input to :func:`id_for`.

    A caller holding the wire payload (a list of ``{site,id,channel}``) must be
    able to ask "which id for this site" without re-deriving the answer. Before
    this existed, ``id_for`` on a parsed list silently returned "" -- the one
    result that looks like "this mod declares nothing".
    """
    out: List[Dict[str, str]] = []
    if not isinstance(value, (list, tuple)):
        return out
    for item in value:
        if not isinstance(item, dict):
            return []
        site = item.get("site")
        ident = item.get("id")
        if not isinstance(site, str) or not isinstance(ident, str):
            return []
        out.append({"site": site.strip().lower(), "id": ident.strip(),
                    "channel": str(item.get("channel") or "").strip()})
    return out[:MAX_KEYS]


def parse(value) -> List[Dict[str, str]]:
    """Return ``[{"site","id","channel"}]`` for every key that parses.

    Unparsable entries are dropped rather than reported: this is a convenience
    index, not a validation, and a mod with one malformed key should not lose
    the key that does parse.

    Accepts a raw manifest value (a string or a list of strings) and also
    already-parsed entries, so the same call works before and after the value
    crosses into a payload.
    """
    given = _already_parsed(value)
    if given:
        return given
    sites: List[Dict[str, str]] = []
    seen = set()
    for raw in _clean(value):
        m = _KEY_RE.match(raw)
        if not m:
            continue
        site = m.group("site").strip().lower()
        ident = m.group("id").strip()
        if site in _NOT_A_SITE:
            continue
        if len(site) > MAX_SITE_CHARS or len(ident) > MAX_ID_CHARS:
            continue
        channel = (m.group("channel") or "").strip()
        if len(channel) > MAX_CHANNEL_CHARS:
            channel = ""
        key = (site, ident.lower(), channel.lower())
        if key in seen:
            continue
        seen.add(key)
        sites.append({"site": site, "id": ident, "channel": channel})
    sites.sort(key=lambda s: (s["site"] != "nexus", s["site"], s["id"]))
    return sites


def id_for(value, site: str) -> str:
    """The first id declared for one site, or "" when there is none."""
    want = (site or "").strip().lower()
    for entry in parse(value):
        if entry["site"] == want:
            return entry["id"]
    return ""
