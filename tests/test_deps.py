"""Round 38 — dependency auto-download.

The user asked (m17400) whether a mod download can bring its required
dependencies along. The honest hard part is not fetching a zip: it is knowing
which zip is the right one. A real device probe showed a monorepo
(zombifier/My_Stardew_Mods) publishes a separate release per mod
(custom-builders/0.0.2, furniture-machine/0.0.2, ...), so "the first usable zip
in the repo" is frequently a DIFFERENT mod. Every test here exists to keep that
from becoming an installed surprise.

Nothing in this file touches the network or the real game folder.
"""

import io
import json
import os
import unittest

from deckymod import deps


class _Resp:
    """Minimal stand-in for download._Response: stateful read(), close()."""

    def __init__(self, status, headers=None, body=b""):
        self.status = status
        self.headers = dict(headers or {})
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


def _index_payload(rows):
    return json.dumps(rows).encode()


def _rec(uid, repo=None, nexus=None):
    return {"id": uid,
            "metadata": {"id": [uid], "gitHubRepo": repo, "nexusID": nexus}}


class _ListEngine:
    """Engine stand-in: a fixed inbox and a manifest per inbox filename."""

    def __init__(self, inbox, manifests=None):
        self._inbox = inbox
        self._manifests = dict(manifests or {})
        self.installed = []
        self.inspected = []

    def list_inbox(self):
        items = [{"name": n, "path": os.path.join(self._inbox, n), "size": 10}
                 for n in sorted(os.listdir(self._inbox))
                 if os.path.isfile(os.path.join(self._inbox, n))]
        return {"ok": True, "data": {"inbox": self._inbox, "items": items}}

    def inspect(self, path):
        name = os.path.basename(str(path))
        self.inspected.append(name)
        uid = self._manifests.get(name)
        if uid is None:
            return {"ok": False, "code": "E_MANIFEST_MISSING", "detail": name}
        return {"ok": True, "data": {"mod": {"uniqueId": uid, "dir_name": "x"}}}

    def install(self, path, *, after_confirm=False):
        self.installed.append(os.path.basename(str(path)))
        return {"ok": True, "data": {"txn": "t1"}}


class _TmpMixin:
    def _inbox(self):
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            ".decky-test-tmp",
                            "r38_" + os.urandom(4).hex())
        inbox = os.path.join(base, "inbox")
        os.makedirs(inbox, exist_ok=True)
        self.addCleanup(lambda: __import__("shutil").rmtree(base, True))
        return inbox

    def _touch(self, inbox, name, payload=b"PK\x03\x04"):
        path = os.path.join(inbox, name)
        with io.open(path, "wb") as f:
            f.write(payload)
        return path


class TestPlanIsPure(unittest.TestCase):
    """plan() must be reachable without any network, so its branches are
    covered directly instead of through a fake HTTPS server."""

    def _plan(self, ids, resolved, cands):
        return deps.plan(ids, lookup=lambda i: resolved, candidates_for=cands)

    def test_resolvable_when_the_index_names_a_repo_with_a_zip(self):
        got = self._plan(["a.one"], {"a.one": {"gitHubRepo": "o/r", "nexusID": 1}},
                         lambda repo, uid: [{"asset_id": 7, "name": "A.zip"}])
        row = got["deps"][0]
        self.assertTrue(got["ok"])
        self.assertEqual(got["fetchable"], 1)
        self.assertEqual(got["total"], 1)
        self.assertTrue(row["resolvable"])
        self.assertEqual(row["repo"], "o/r")
        self.assertEqual(row["reason"], "")

    def test_a_dependency_with_no_downloadable_repo_is_reported_not_faked(self):
        # The index may know a mod and still name no repo we can fetch from.
        # The honest answer is "why not", never a substitute file.
        got = self._plan(["b.two"], {"b.two": {"gitHubRepo": None}},
                         lambda repo, uid: [])
        row = got["deps"][0]
        self.assertFalse(row["resolvable"])
        self.assertEqual(row["reason"], "no_repo_in_index")
        self.assertEqual(got["fetchable"], 0)

    def test_unknown_id_is_reported_as_no_repo(self):
        got = self._plan(["c.three"], {}, lambda repo, uid: [])
        self.assertEqual(got["deps"][0]["reason"], "no_repo_in_index")

    def test_repo_without_any_zip_asset_is_reported(self):
        got = self._plan(["d.four"], {"d.four": {"gitHubRepo": "o/r"}},
                         lambda repo, uid: [])
        self.assertEqual(got["deps"][0]["reason"], "no_zip_asset")

    def test_ids_are_deduplicated_case_insensitively_and_ordered(self):
        seen = []

        def cands(repo, uid):
            seen.append(uid)
            return [{"asset_id": 1, "name": "x.zip"}]

        got = deps.plan(["A.One", "a.one", "b.two"],
                        lookup=lambda i: {"a.one": {"gitHubRepo": "o/r"},
                                          "b.two": {"gitHubRepo": "o/r2"}},
                        candidates_for=cands)
        self.assertEqual([d["uniqueId"] for d in got["deps"]], ["A.One", "b.two"])
        self.assertEqual(seen, ["A.One", "b.two"])

    def test_the_limit_bounds_the_work(self):
        ids = ["m.%d" % i for i in range(30)]
        got = deps.plan(ids, lookup=lambda i: {}, candidates_for=lambda r, u: [],
                        limit=3)
        self.assertEqual(got["total"], 3)
        self.assertEqual(len(got["deps"]), 3)

    def test_an_empty_list_is_not_an_error(self):
        got = deps.plan([], lookup=lambda i: {}, candidates_for=lambda r, u: [])
        self.assertTrue(got["ok"])
        self.assertEqual(got["total"], 0)


class TestCandidateOrdering(unittest.TestCase):
    def test_a_name_resembling_the_id_is_tried_first(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "deckymod", "deps.py")
        with io.open(path, encoding="utf-8") as f:
            src = f.read()
        # The ordering helper exists and the acceptance step is separate; if
        # someone ever merged them, this test should fail loudly.
        self.assertIn("def _segments(", src)
        self.assertIn("def verify_candidate(", src)


class TestVerifyCandidate(unittest.TestCase):
    """A filename is not evidence — only the manifest's UniqueID is."""

    def setUp(self):
        self.inbox = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".decky-test-tmp", "r38v_" + os.urandom(4).hex())
        os.makedirs(self.inbox, exist_ok=True)
        self.addCleanup(lambda: __import__("shutil").rmtree(
            os.path.dirname(self.inbox), True))
        self.zip = os.path.join(self.inbox, "FurnitureMachine.0.0.2.zip")
        with io.open(self.zip, "wb") as f:
            f.write(b"PK\x03\x04")

    def test_matching_manifest_uid_is_accepted(self):
        eng = _ListEngine(self.inbox, {"FurnitureMachine.0.0.2.zip": "selph.FurnitureMachine"})
        got = deps.verify_candidate(eng, self.zip, "selph.FurnitureMachine")
        self.assertTrue(got["ok"])
        self.assertEqual(got["mod"]["uniqueId"], "selph.FurnitureMachine")

    def test_case_differences_do_not_reject_a_match(self):
        eng = _ListEngine(self.inbox, {"FurnitureMachine.0.0.2.zip": "Selph.FurnitureMachine"})
        self.assertTrue(deps.verify_candidate(
            eng, self.zip, "selph.furnituremachine")["ok"])

    def test_a_different_mod_in_the_same_repo_is_refused(self):
        # The exact trap the device probe found: same repo, different mod.
        eng = _ListEngine(self.inbox, {"FurnitureMachine.0.0.2.zip": "zombifier.CustomBuilders"})
        got = deps.verify_candidate(eng, self.zip, "selph.FurnitureMachine")
        self.assertFalse(got["ok"])
        self.assertEqual(got["code"], "DL_BAD_ARCHIVE")
        self.assertIn("zombifier.CustomBuilders", got["detail"])
        self.assertIn("selph.FurnitureMachine", got["detail"])

    def test_an_unreadable_manifest_is_refused(self):
        eng = _ListEngine(self.inbox, {})
        got = deps.verify_candidate(eng, self.zip, "x.y")
        self.assertFalse(got["ok"])
        self.assertEqual(got["code"], "E_MANIFEST_MISSING")


class TestTriState(_TmpMixin, unittest.TestCase):
    def _run(self, **kw):
        inbox = self._inbox()
        eng = _ListEngine(inbox)
        base = dict(missing_ids=["a.one"],
                    lookup=lambda ids: {"a.one": {"gitHubRepo": "o/r"}},
                    candidates_for=lambda repo, uid: [{"asset_id": 7, "name": "A.zip"}])
        base.update(kw)
        return deps.run(None, eng, **base), eng

    def test_default_is_plan_only_and_writes_nothing(self):
        got, eng = self._run()
        self.assertTrue(got["ok"])
        self.assertEqual(got["phase"], "inspect")
        self.assertFalse(got["install_allowed"])
        self.assertEqual(got["fetchable"], 1)
        self.assertEqual(eng.installed, [])
        self.assertIn("nothing was downloaded", got["note"])

    def test_confirm_phase_still_writes_nothing(self):
        got, eng = self._run(allow_install=True)
        self.assertEqual(got["phase"], "confirm")
        self.assertIn("1 of 1", got["confirm_text"])
        self.assertTrue(got["warnings"])
        self.assertEqual(eng.installed, [])
        self.assertEqual(eng.inspected, [])

    def test_unresolvable_dependency_is_reported_when_installing(self):
        got, eng = self._run(allow_install=True, after_confirm=True,
                             lookup=lambda ids: {},
                             candidates_for=lambda repo, uid: [])
        self.assertEqual(got["phase"], "installed")
        self.assertEqual(got["installed"], 0)
        self.assertEqual(got["deps"][0]["reason"], "no_repo_in_index")
        self.assertEqual(eng.installed, [])


class TestInstallPath(_TmpMixin, unittest.TestCase):
    def test_a_verified_download_is_installed(self):
        inbox = self._inbox()
        # The manifest inside the downloaded zip is what authorises the install,
        # so the fixture has to declare one.
        eng = _ListEngine(inbox, {"A.zip": "a.one"})

        def fetch(repo, asset_id, filename):
            self._touch(inbox, filename)
            return {"ok": True, "path": os.path.join(inbox, filename)}

        got = deps.run(None, eng, missing_ids=["a.one"], allow_install=True,
                       after_confirm=True,
                       lookup=lambda ids: {"a.one": {"gitHubRepo": "o/r"}},
                       candidates_for=lambda repo, uid: [{"asset_id": 7, "name": "A.zip"}],
                       fetch=fetch)
        self.assertTrue(got["ok"])
        self.assertEqual(got["installed"], 1)
        self.assertEqual(got["attempted"], 1)
        self.assertTrue(got["deps"][0]["installed"])
        self.assertEqual(got["deps"][0]["asset"], "A.zip")
        self.assertEqual(len(eng.installed), 1)

    def test_a_wrong_mod_is_deleted_and_the_next_candidate_is_tried(self):
        inbox = self._inbox()
        eng = _ListEngine(inbox, {"Wrong.1.zip": "someone.else",
                                  "Right.1.zip": "a.one"})

        def fetch(repo, asset_id, filename):
            self._touch(inbox, filename)
            return {"ok": True, "path": os.path.join(inbox, filename)}

        got = deps.run(None, eng, missing_ids=["a.one"], allow_install=True,
                       after_confirm=True,
                       lookup=lambda ids: {"a.one": {"gitHubRepo": "o/r"}},
                       candidates_for=lambda repo, uid: [{"asset_id": 1, "name": "Wrong.1.zip"},
                                                         {"asset_id": 2, "name": "Right.1.zip"}],
                       fetch=fetch)
        self.assertEqual(got["installed"], 1)
        self.assertEqual(got["deps"][0]["asset"], "Right.1.zip")
        self.assertEqual(eng.installed, ["Right.1.zip"])
        # The rejected file must not be left in the inbox for a human to
        # mistake for something they asked for.
        self.assertFalse(os.path.exists(os.path.join(inbox, "Wrong.1.zip")))

    def test_no_candidate_matching_leaves_nothing_installed(self):
        inbox = self._inbox()
        eng = _ListEngine(inbox, {"Wrong.1.zip": "someone.else"})

        def fetch(repo, asset_id, filename):
            self._touch(inbox, filename)
            return {"ok": True, "path": os.path.join(inbox, filename)}

        got = deps.run(None, eng, missing_ids=["a.one"], allow_install=True,
                       after_confirm=True,
                       lookup=lambda ids: {"a.one": {"gitHubRepo": "o/r"}},
                       candidates_for=lambda repo, uid: [{"asset_id": 1, "name": "Wrong.1.zip"}],
                       fetch=fetch)
        self.assertEqual(got["installed"], 0)
        self.assertEqual(got["deps"][0]["reason"], "candidate_failed")
        self.assertEqual(eng.installed, [])
        self.assertFalse(os.path.exists(os.path.join(inbox, "Wrong.1.zip")))

    def test_a_refused_install_does_not_block_the_other_dependencies(self):
        inbox = self._inbox()
        eng = _ListEngine(inbox, {"A.zip": "a.one", "B.zip": "b.two"})
        # Refuse only the first dependency's install.
        calls = {"n": 0}

        def install(path, *, after_confirm=False):
            calls["n"] += 1
            if os.path.basename(str(path)) == "A.zip":
                return {"ok": False, "code": "E_EXTERNAL_MANAGER",
                        "detail": "another manager owns the folder"}
            eng.installed.append(os.path.basename(str(path)))
            return {"ok": True, "data": {"txn": "t2"}}

        eng.install = install

        def fetch(repo, asset_id, filename):
            self._touch(inbox, filename)
            return {"ok": True, "path": os.path.join(inbox, filename)}

        got = deps.run(None, eng, missing_ids=["a.one", "b.two"], allow_install=True,
                       after_confirm=True,
                       lookup=lambda ids: {"a.one": {"gitHubRepo": "o/r"},
                                           "b.two": {"gitHubRepo": "o/r"}},
                       candidates_for=lambda repo, uid: [{"asset_id": 1,
                                                          "name": "A.zip" if uid == "a.one" else "B.zip"}],
                       fetch=fetch)
        # Both were attempted: the dependencies are independent, so a failure on
        # one must not stop the other. This is exactly the bug a device run
        # found (ExtraMachineConfig blocked FurnitureMachine).
        self.assertEqual(got["attempted"], 2)
        self.assertEqual(got["installed"], 1)
        self.assertEqual(got["deps"][0]["reason"], "install_refused")
        self.assertTrue(got["deps"][1]["installed"])
        self.assertEqual(eng.installed, ["B.zip"])

    def test_an_engine_exception_while_installing_is_reported_not_raised(self):
        inbox = self._inbox()
        eng = _ListEngine(inbox, {"A.zip": "a.one"})

        def boom(path, *, after_confirm=False):
            raise RuntimeError("engine exploded")

        eng.install = boom

        def fetch(repo, asset_id, filename):
            self._touch(inbox, filename)
            return {"ok": True, "path": os.path.join(inbox, filename)}

        got = deps.run(None, eng, missing_ids=["a.one"], allow_install=True,
                       after_confirm=True,
                       lookup=lambda ids: {"a.one": {"gitHubRepo": "o/r"}},
                       candidates_for=lambda repo, uid: [{"asset_id": 1, "name": "A.zip"}],
                       fetch=fetch)
        self.assertEqual(got["installed"], 0)
        self.assertEqual(got["deps"][0]["reason"], "install_raised")
        self.assertIn("engine exploded", got["deps"][0]["detail"])


class TestDepth(_TmpMixin, unittest.TestCase):
    """Round 45: a dependency can itself require something.

    The scan only reports what the INSTALLED mods declare, so a gap created by
    the very mod we just installed is invisible until the scan is re-run. These
    cases pin that re-scan, and pin that it cannot run forever.
    """

    def test_a_dependency_of_a_dependency_is_resolved(self):
        inbox = self._inbox()
        eng = _ListEngine(inbox, {"A.zip": "a.one", "B.zip": "b.two"})
        # Scan order matters: the re-scan happens AFTER a round's installs land,
        # so the first answer must already include what a.one needed. The final
        # call is the "what is left" question asked once more before reporting.
        scans = [["b.two"], [], []]
        calls = {"n": 0}

        def rescan():
            i = min(calls["n"], len(scans) - 1)
            calls["n"] += 1
            return scans[i]

        def fetch(repo, asset_id, filename):
            self._touch(inbox, filename)
            return {"ok": True, "path": os.path.join(inbox, filename)}

        got = deps.run(None, eng, missing_ids=["a.one"], allow_install=True,
                       after_confirm=True,
                       lookup=lambda ids: {i: {"gitHubRepo": "o/r"} for i in ids},
                       candidates_for=lambda repo, uid: [
                           {"asset_id": hash(uid) % 1000,
                            "name": "A.zip" if uid == "a.one" else "B.zip"}],
                       fetch=fetch, rescan=rescan)
        self.assertTrue(got["ok"])
        self.assertEqual(got["installed"], 2)
        self.assertEqual(eng.installed, ["A.zip", "B.zip"])
        rounds = {r["uniqueId"]: r["round"] for r in got["deps"]}
        self.assertEqual(rounds["a.one"], 1)
        self.assertEqual(rounds["b.two"], 2, "second level must be attempted")
        self.assertEqual(got["rounds"], 2)
        self.assertEqual(got["still_missing"], [])

    def test_the_loop_is_bounded_and_says_so(self):
        inbox = self._inbox()
        eng = _ListEngine(inbox, {"A.zip": "a.one"})
        # A cycle in the index: every scan still reports the same id.
        def rescan():
            return ["a.one"]

        def fetch(repo, asset_id, filename):
            self._touch(inbox, filename)
            return {"ok": True, "path": os.path.join(inbox, filename)}

        got = deps.run(None, eng, missing_ids=["a.one"], allow_install=True,
                       after_confirm=True,
                       lookup=lambda ids: {"a.one": {"gitHubRepo": "o/r"}},
                       candidates_for=lambda repo, uid: [{"asset_id": 1, "name": "A.zip"}],
                       fetch=fetch, rescan=rescan, max_rounds=3)
        # One install: the id joins `seen`, so the second round has nothing new
        # to do and the loop exits instead of downloading the same thing again.
        self.assertEqual(got["installed"], 1)
        self.assertEqual(eng.installed, ["A.zip"])
        self.assertEqual(got["rounds"], 1)
        self.assertEqual(got["still_missing"], ["a.one"])
        self.assertIn("still", got.get("note") or "")

    def test_an_already_seen_id_is_never_installed_twice(self):
        inbox = self._inbox()
        eng = _ListEngine(inbox, {"A.zip": "a.one"})

        def fetch(repo, asset_id, filename):
            self._touch(inbox, filename)
            return {"ok": True, "path": os.path.join(inbox, filename)}

        got = deps.run(None, eng, missing_ids=["a.one", "a.one"], allow_install=True,
                       after_confirm=True,
                       lookup=lambda ids: {"a.one": {"gitHubRepo": "o/r"}},
                       candidates_for=lambda repo, uid: [{"asset_id": 1, "name": "A.zip"}],
                       fetch=fetch, rescan=lambda: [])
        self.assertEqual(got["attempted"], 1)
        self.assertEqual(len(eng.installed), 1)

    def test_the_confirm_phase_promises_the_bounded_depth(self):
        inbox = self._inbox()
        eng = _ListEngine(inbox, {"A.zip": "a.one"})
        got = deps.run(None, eng, missing_ids=["a.one"], allow_install=True,
                       after_confirm=False,
                       lookup=lambda ids: {"a.one": {"gitHubRepo": "o/r"}},
                       candidates_for=lambda repo, uid: [{"asset_id": 1, "name": "A.zip"}])
        self.assertEqual(got["phase"], "confirm")
        self.assertEqual(eng.installed, [], "confirming must not write")
        joined = " ".join(got.get("warnings") or [])
        self.assertIn("re-run", joined)
        self.assertIn(str(deps.MAX_ROUNDS), joined)

    def test_a_rescan_that_raises_does_not_lose_the_installs(self):
        inbox = self._inbox()
        eng = _ListEngine(inbox, {"A.zip": "a.one"})

        def rescan():
            raise RuntimeError("status exploded")

        def fetch(repo, asset_id, filename):
            self._touch(inbox, filename)
            return {"ok": True, "path": os.path.join(inbox, filename)}

        got = deps.run(None, eng, missing_ids=["a.one"], allow_install=True,
                       after_confirm=True,
                       lookup=lambda ids: {"a.one": {"gitHubRepo": "o/r"}},
                       candidates_for=lambda repo, uid: [{"asset_id": 1, "name": "A.zip"}],
                       fetch=fetch, rescan=rescan)
        self.assertTrue(got["ok"])
        self.assertEqual(got["installed"], 1)
        self.assertEqual(got["still_missing"], [])


class TestJsonSafe(unittest.TestCase):
    def test_a_result_survives_json_round_trip(self):
        got = deps.run(None, _ListEngine(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".decky-test-tmp")), missing_ids=["a.one"],
            lookup=lambda ids: {"a.one": {"gitHubRepo": "o/r"}},
            candidates_for=lambda repo, uid: [{"asset_id": 1, "name": "A.zip"}])
        text = json.dumps(got, allow_nan=False)
        self.assertIn("inspect", text)


class TestModuleReusesTheSharedLayer(unittest.TestCase):
    """No second https stack: the dependency resolver must go through the same
    allow-list / error-code layer as every other download."""

    def setUp(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "deckymod", "deps.py")
        with io.open(path, encoding="utf-8") as f:
            self.src = f.read()

    def test_it_imports_the_shared_download_layer(self):
        self.assertIn("from . import download", self.src)

    def test_it_does_not_open_its_own_sockets(self):
        self.assertNotIn("import urllib", self.src)
        self.assertNotIn("import socket", self.src)

    def test_the_index_host_is_pinned(self):
        self.assertIn('INDEX_HOST = "smapi.io"', self.src)


if __name__ == "__main__":
    unittest.main()
