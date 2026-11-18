"""Round 41 -- a dependency published only as .7z must be fetchable.

The engine has installed .7z end-to-end since round 63 (41/41 device checks),
and goal item 3 asks for ".zip and .7z". But ``deps.candidate_assets`` used to
filter on ``.zip`` only, so a dependency whose repo publishes a single ``.7z``
was reported ``no_zip_asset`` and never fetched -- a capability gap dressed up
as a content policy. Content type is only a first-pass filter; the manifest
read in ``verify_candidate`` remains the authority that decides whether the
asset really is the requested mod.

Nothing here touches the network or the real game folder.
"""

import json
import os
import unittest

from deckymod import deps


class _Resp:
    def __init__(self, status, body=b""):
        self.status = status
        self.headers = {}
        self._body = body
        self._pos = 0

    def read(self, amt=None):
        if amt is None:
            amt = len(self._body)
        part = self._body[self._pos:self._pos + amt]
        self._pos += len(part)
        return part

    def close(self):
        pass


def _opener_with(releases):
    body = json.dumps(releases).encode("utf-8")
    calls = []

    def opener(method, url, headers, timeout):
        calls.append((method, url))
        return _Resp(200, body)

    return opener, calls


def _release(tag, assets):
    return {"tag_name": tag, "assets": [
        {"name": name, "content_type": ct, "id": aid, "size": 1000}
        for aid, (name, ct) in enumerate(assets, start=1)
    ]}


class TestSevenZIsAFetchableArchive(unittest.TestCase):
    def test_a_repo_publishing_only_7z_yields_a_candidate(self):
        opener, _ = _opener_with([
            _release("1.0.0", [("a.one.7z", "application/x-7z-compressed")]),
        ])
        got = deps.candidate_assets(opener, "o/r", "a.one")
        self.assertTrue(got["ok"])
        names = [a["name"] for a in got["assets"]]
        self.assertIn("a.one.7z", names)

    def test_zip_and_7z_are_both_usable(self):
        opener, _ = _opener_with([
            _release("1.0.0", [("a.one.zip", "application/zip"),
                               ("a.two.7z", "application/x-7z-compressed")]),
        ])
        got = deps.candidate_assets(opener, "o/r", "a.one")
        self.assertEqual(sorted(a["name"] for a in got["assets"]),
                         ["a.one.zip", "a.two.7z"])

    def test_a_7z_labelled_only_octet_stream_is_still_usable(self):
        # GitHub frequently under-reports the content type; the suffix plus
        # the manifest check are what matter, not the label.
        opener, _ = _opener_with([
            _release("1.0.0", [("a.one.7z", "application/octet-stream")]),
        ])
        got = deps.candidate_assets(opener, "o/r", "a.one")
        self.assertTrue(got["ok"])
        self.assertIn("a.one.7z", [a["name"] for a in got["assets"]])

    def test_other_archive_formats_are_still_refused(self):
        # Adding .7z must not turn this into "accept anything": .rar is not
        # readable by the engine, so offering it would only waste a fetch.
        opener, _ = _opener_with([
            _release("1.0.0", [("a.one.rar", "application/octet-stream"),
                               ("a.one.exe", "application/octet-stream")]),
        ])
        got = deps.candidate_assets(opener, "o/r", "a.one")
        self.assertTrue(got["ok"])
        self.assertEqual(got["assets"], [])

    def test_ordering_by_id_hint_still_applies_to_7z(self):
        opener, _ = _opener_with([
            _release("1.0.0", [("unrelated.7z", "application/x-7z-compressed"),
                               ("a.one.7z", "application/x-7z-compressed")]),
        ])
        got = deps.candidate_assets(opener, "o/r", "a.one")
        self.assertEqual(got["assets"][0]["name"], "a.one.7z")
        self.assertEqual(got["matched"], 1)


class TestReasonWordingMatchesCapability(unittest.TestCase):
    def test_the_no_archive_reason_and_i18n_mention_both_formats(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "src", "i18n", "en.json"), encoding="utf-8") as f:
            en = f.read()
        with open(os.path.join(root, "src", "i18n", "zh-CN.json"), encoding="utf-8") as f:
            zh = f.read()
        self.assertIn('"DEPS_R_NO_ZIP": "the repository publishes no zip or 7z"', en)
        self.assertIn('"DEPS_R_NO_ZIP": "该仓库没有发布 zip 或 7z"', zh)
        # The wire key stays stable: only the wording changed.
        with open(os.path.join(root, "src", "index.tsx"), encoding="utf-8") as f:
            index = f.read()
        self.assertIn('"no_zip_asset"', index)


if __name__ == "__main__":
    unittest.main()
