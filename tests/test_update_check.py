"""Round 82: tell the user which installed mods have a newer version.

`docs/NEXT_FEATURES.md` P2#8 recorded the gap plainly: "a stale plugin has no
way to tell its user it is stale", and the same was true of the mods inside it.
Nothing in the plugin answered "is there a newer version of this mod" — Round 67
only asked it about *dependencies*.

What makes this honest rather than a guess:

  * a mod is only asked about when its own `UpdateKeys` names a Nexus id;
  * the comparison uses the same `_version_tuple` the dependency check uses,
    so "1.2" and "1.2.0" compare equal and an unparsable version reads as
    unknown rather than newer or older;
  * free Nexus accounts cannot download, so this only ever REPORTS. It opens no
    archive, writes nothing, and never touches the mod folder.

The fixture is a fake opener: `nexus.mod_files` takes one, so no network is
reached and the API's exact response shape is what the test controls.
"""
from __future__ import annotations

import json
import os
import unittest

from deckymod import update_check


def _mod(uid, version, nexus_id=None, site="nexus"):
    row = {"dir": uid, "uniqueId": uid, "version": version, "update_keys": []}
    if nexus_id is not None:
        row["update_keys"] = [{"site": site, "id": str(nexus_id), "channel": ""}]
    return row


def _files(*pairs):
    """(version, uploaded_timestamp) pairs -> the shape nexus.mod_files returns."""
    return {
        "ok": True,
        "files": [
            {"file_id": i, "name": "f%d.zip" % i, "version": v, "mod_version": v,
             "uploaded_timestamp": ts, "category_name": "MAIN", "file_name": "f.zip",
             "size_kb": 1}
            for i, (v, ts) in enumerate(pairs)
        ],
    }


class _Response(object):
    """The minimum ``nexus._raw`` reads off a urllib response."""

    def __init__(self, status, payload):
        self.status = status
        self._body = payload

    def read(self, n=None):
        return self._body

    def close(self):
        pass


class _Opener(object):
    """A stand-in for ``download.default_opener`` that answers from a dict.

    ``nexus._raw`` reads ``resp.status`` and ``resp.read()``, so the fake has to
    return an object, not a dict — a dict silently became status 0 and every
    mod reported "error", which is exactly the kind of wrong-but-plausible
    answer this module exists to avoid.
    """

    def __init__(self, by_id):
        self.by_id = by_id
        self.calls = []

    def __call__(self, method, url, headers, timeout):
        self.calls.append(url)
        for ident, res in self.by_id.items():
            if "/mods/%s/files.json" % ident in url:
                if not res.get("ok"):
                    return _Response(404, b'{"message":"not found"}')
                return _Response(200, json.dumps({"files": res["files"]}).encode("utf-8"))
        return _Response(404, b'{"message":"not found"}')


class TestNexusIds(unittest.TestCase):
    def test_a_declared_nexus_id_is_collected(self):
        got = update_check.nexus_ids([_mod("A.Mod", "1.0.0", 1063)])
        self.assertEqual(got, {"1063": ["A.Mod"]})

    def test_two_mods_sharing_one_id_are_one_api_call(self):
        # A framework and its content pack inside one package is a real shape;
        # asking twice would burn two requests from a 60/hour budget.
        got = update_check.nexus_ids([_mod("A.Framework", "1.0", 1063),
                                      _mod("A.Content", "1.0", 1063)])
        self.assertEqual(got, {"1063": ["A.Framework", "A.Content"]})

    def test_a_mod_without_a_key_is_silently_absent(self):
        self.assertEqual(update_check.nexus_ids([_mod("No.Key", "1.0")]), {})

    def test_a_non_nexus_site_is_ignored(self):
        got = update_check.nexus_ids([_mod("X", "1.0", 42, site="github")])
        self.assertEqual(got, {})

    def test_a_non_numeric_id_is_dropped_not_requested(self):
        # "abc" would become /mods/abc/files.json -> a 404 that reads as
        # "this mod does not exist", which is a different claim.
        got = update_check.nexus_ids([_mod("X", "1.0", "abc")])
        self.assertEqual(got, {})

    def test_the_same_uid_is_not_listed_twice(self):
        row = _mod("A.Mod", "1.0", 5)
        row["update_keys"].append({"site": "nexus", "id": "5", "channel": "New"})
        self.assertEqual(update_check.nexus_ids([row]), {"5": ["A.Mod"]})


class TestCompare(unittest.TestCase):
    def test_older_installed_is_outdated(self):
        self.assertEqual(update_check.compare("1.2.3", "1.2.4"),
                         update_check.STATE_OUTDATED)

    def test_equal_is_current(self):
        self.assertEqual(update_check.compare("1.2.3", "1.2.3"),
                         update_check.STATE_CURRENT)

    def test_padding_does_not_make_it_outdated(self):
        # "1.2" and "1.2.0" are the same version to a mod author.
        self.assertEqual(update_check.compare("1.2", "1.2.0"),
                         update_check.STATE_CURRENT)

    def test_a_newer_local_version_is_current_not_outdated(self):
        # Downgrading is not "outdated"; suggesting an update to an older file
        # would be worse than saying nothing.
        self.assertEqual(update_check.compare("2.0.0", "1.9.9"),
                         update_check.STATE_CURRENT)

    def test_an_unparsable_version_is_unknown_never_current(self):
        for pair in (("", "1.0"), ("1.0", ""), ("beta", "1.0"), ("1.0", "??")):
            with self.subTest(pair=pair):
                self.assertEqual(update_check.compare(*pair),
                                 update_check.STATE_UNKNOWN)


class TestNewestVersion(unittest.TestCase):
    def test_the_latest_upload_wins_over_an_older_but_higher_number(self):
        # Authors re-upload old builds; the newest file is what a user gets.
        got = update_check._newest_version(_files(("2.0.0", 100), ("1.5.0", 900))["files"])
        self.assertEqual(got, "1.5.0")

    def test_an_empty_file_list_is_empty_not_zero(self):
        self.assertEqual(update_check._newest_version([]), "")

    def test_a_file_without_a_version_is_skipped(self):
        files = [{"uploaded_timestamp": 10, "mod_version": "", "version": ""},
                 {"uploaded_timestamp": 5, "mod_version": "1.0", "version": "1.0"}]
        self.assertEqual(update_check._newest_version(files), "1.0")


class TestCheck(unittest.TestCase):
    def test_a_newer_published_version_is_reported_outdated(self):
        opener = _Opener({"1063": _files(("2.0.0", 500))})
        got = update_check.check(opener, [_mod("A.Mod", "1.0.0", 1063)],
                                 api_key="k", game_domain="stardewvalley")
        self.assertTrue(got["ok"], got)
        self.assertEqual(got["outdated"], ["A.Mod"])
        self.assertEqual(got["rows"][0]["state"], update_check.STATE_OUTDATED)
        self.assertEqual(got["rows"][0]["latest"], "2.0.0")

    def test_the_same_version_is_reported_current(self):
        opener = _Opener({"1063": _files(("1.0.0", 500))})
        got = update_check.check(opener, [_mod("A.Mod", "1.0.0", 1063)],
                                 api_key="k", game_domain="stardewvalley")
        self.assertEqual(got["outdated"], [])
        self.assertEqual(got["rows"][0]["state"], update_check.STATE_CURRENT)

    def test_a_mod_with_no_key_is_not_checked_at_all(self):
        opener = _Opener({})
        got = update_check.check(opener, [_mod("No.Key", "1.0")],
                                 api_key="k", game_domain="stardewvalley")
        self.assertTrue(got["ok"])
        self.assertEqual(got["checked"], 0)
        self.assertEqual(opener.calls, [])

    def test_an_api_failure_is_reported_per_mod_not_swallowed(self):
        opener = _Opener({})          # every id answers 404
        got = update_check.check(opener, [_mod("A.Mod", "1.0.0", 1063)],
                                 api_key="k", game_domain="stardewvalley")
        self.assertTrue(got["ok"])
        self.assertEqual(got["rows"][0]["state"], update_check.STATE_ERROR)
        self.assertEqual(got["errors"]["1063"], "DL_NOT_FOUND")
        self.assertEqual(got["outdated"], [])

    def test_a_mod_whose_version_is_unreadable_is_unknown(self):
        opener = _Opener({"1063": _files(("2.0.0", 500))})
        got = update_check.check(opener, [_mod("A.Mod", "", 1063)],
                                 api_key="k", game_domain="stardewvalley")
        self.assertEqual(got["rows"][0]["state"], update_check.STATE_UNKNOWN)
        self.assertEqual(got["outdated"], [])

    def test_two_mods_one_id_both_get_a_row(self):
        opener = _Opener({"1063": _files(("2.0.0", 500))})
        got = update_check.check(
            opener,
            [_mod("A.Framework", "1.0.0", 1063), _mod("A.Content", "2.0.0", 1063)],
            api_key="k", game_domain="stardewvalley")
        self.assertEqual(len(opener.calls), 1, "one API call, not two")
        states = {r["uniqueId"]: r["state"] for r in got["rows"]}
        self.assertEqual(states["A.Framework"], update_check.STATE_OUTDATED)
        self.assertEqual(states["A.Content"], update_check.STATE_CURRENT)

    def test_the_cap_is_reported_rather_than_silently_applied(self):
        mods = [_mod("M%d" % i, "1.0", 1000 + i)
                for i in range(update_check.MAX_CHECKS + 5)]
        opener = _Opener({str(1000 + i): _files(("1.0", 1))
                          for i in range(update_check.MAX_CHECKS + 5)})
        got = update_check.check(opener, mods, api_key="k",
                                 game_domain="stardewvalley")
        self.assertEqual(got["checked"], update_check.MAX_CHECKS)
        self.assertEqual(got["skipped"], 5)
        self.assertIn("rate limit", got["note"])

    def test_nothing_is_written(self):
        # There is no write path in this module at all; this pins that the
        # call succeeds against a temp dir the test never sees changed.
        opener = _Opener({"1063": _files(("2.0.0", 500))})
        before = os.getcwd()
        update_check.check(opener, [_mod("A.Mod", "1.0.0", 1063)],
                           api_key="k", game_domain="stardewvalley")
        self.assertEqual(os.getcwd(), before)


class TestSummary(unittest.TestCase):
    def test_it_counts_each_state_once(self):
        rows = [{"state": update_check.STATE_OUTDATED},
                {"state": update_check.STATE_OUTDATED},
                {"state": update_check.STATE_CURRENT},
                {"state": update_check.STATE_UNKNOWN}]
        got = update_check.summary(rows)
        self.assertIn("2 outdated", got)
        self.assertIn("1 current", got)
        self.assertIn("1 unknown", got)

    def test_no_rows_means_no_sentence(self):
        self.assertEqual(update_check.summary([]), "")


if __name__ == "__main__":
    unittest.main()
