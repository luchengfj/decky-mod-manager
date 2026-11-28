"""Round 86 — an engine must be asked what it can do, not probed.

Two defects, one cause.

  A. ``registry/games/cyberpunk.json`` declared ``"parser": "path_map"`` and no
     such parser was ever written. ``manifest.parser_for`` raised
     ``E_MANIFEST_UNSAFE`` with the internal string
     ``no manifest parser named 'path_map'``, and on a Cyberpunk 2077 device
     that string reached the panel through ``archive_mods``.

  B. Worse: ``install()`` was broken on EVERY root_merge game, including the
     games a user configures themselves. Round 84 added ``member_root`` to
     ``FileDropEngine.install`` and made it forward four positional arguments
     to ``_install_inner``. ``RootMergeEngine`` overrides ``_install_inner``
     with three. So the call raised
     ``TypeError: _install_inner() takes from 3 to 4 positional arguments but
     5 were given``, which ``install()`` turned into ``E_UNKNOWN``. Installing
     anything on Cyberpunk 2077 could not work, and no test noticed because
     none of the four root_merge fixtures ever called ``.install()``.

Both survived because ``main.py`` decided "can this engine do X?" by probing
for a method that every engine inherits: ``hasattr(engine, "_set_enabled_inner")``
is True for all three, so ``member_root`` was forwarded to an engine that had
no parameter for it, and ``archive_mods`` was called on an engine whose
inherited implementation cannot work.

This module pins the FIX, not the two incidents:

  * ``_x_inner`` overrides keep the base signature (the root cause of B);
  * a refused argument/operation comes back as ``E_CAPABILITY_DISABLED`` with a
    ``reason`` word the UI can translate -- never ``E_UNKNOWN`` and never an
    internal parser name;
  * a descriptor that declares an unregistered parser fails at REGISTRY LOAD,
    where the message names the file, instead of at the first archive the user
    opens.

The engine fixtures are the repositories' own: ``MultiRootTree`` from
test_handover_multiroot. Nothing in deckymod/ is mocked.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import json
import os
import shutil
import sys
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402
from deckymod import manifest  # noqa: E402
from deckymod.engine import Engine  # noqa: E402
from deckymod.errors import ModError  # noqa: E402
from deckymod.registry import Registry  # noqa: E402
from deckymod.root_merge import RootMergeEngine  # noqa: E402
from deckymod.smapi import FileDropEngine  # noqa: E402
from test_handover_multiroot import MultiRootTree  # noqa: E402
from test_second_game import SecondTree  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Every engine class the factory can dispatch to. A new engine must be added
#: here, otherwise the signature test below silently stops covering it.
ENGINES = (Engine, FileDropEngine, RootMergeEngine)

#: The hooks ``install``/``uninstall``/``set_enabled`` route to. A subclass that
#: overrides one of these MUST keep its parent's parameter list.
HOOKS = ("_install_inner", "_uninstall_inner", "_set_enabled_inner",
         "_rollback_inner", "_reclaim_inner", "_handover_inner")

_PREV = None


def setUpModule():
    global _PREV
    _PREV = os.environ.pop("DECKYMOD_GAME_ID", None)


def tearDownModule():
    if _PREV is not None:
        os.environ["DECKYMOD_GAME_ID"] = _PREV
    else:
        os.environ.pop("DECKYMOD_GAME_ID", None)


def _params(func):
    """Parameter names of a bound/unbound function, ``self`` excluded."""
    return [p.name for p in inspect.signature(func).parameters.values()
            if p.name != "self"]


def _mod_zip(path, members=None):
    members = members or {
        "mods/ProbeMod/info.json": json.dumps(
            {"name": "probe.mod", "version": "1.0.0"}).encode(),
        "mods/ProbeMod/ProbeMod.archive": b"archive bytes",
    }
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return path


class TestHookSignaturesMatchTheBase(unittest.TestCase):
    """Defect B's root cause: a subclass hook with a shorter parameter list.

    ``FileDropEngine.install`` forwards its arguments POSITIONALLY to
    ``_install_inner``. So the moment one side gains a parameter the other does
    not, every call to the shorter one raises TypeError -- and ``install()``
    catches Exception and reports ``E_UNKNOWN``, which reads like a plugin bug
    rather than "this engine does not take that argument".
    """

    def test_every_override_keeps_its_parents_parameter_list(self):
        offenders = []
        for cls in ENGINES:
            for name in HOOKS:
                own = cls.__dict__.get(name)
                if own is None:
                    continue  # inherited: nothing to compare
                base = getattr(cls.__mro__[1], name, None) if len(cls.__mro__) > 1 else None
                if base is None:
                    continue
                if _params(own) != _params(base):
                    offenders.append(
                        "%s.%s%s != %s.%s%s" % (
                            cls.__name__, name, tuple(_params(own)),
                            cls.__mro__[1].__name__, name, tuple(_params(base))))
        self.assertEqual(offenders, [], "\n" + "\n".join(offenders))

    def test_the_install_hook_accepts_everything_install_forwards(self):
        # The exact regression: FileDropEngine.install sends four positional
        # arguments, and RootMergeEngine inherits that wrapper.
        #
        # This deliberately does NOT sweep all of ENGINES. Engine (RimWorld's
        # xml_list) sits on a SEPARATE inheritance chain: it has its own install
        # wrapper that forwards two arguments, and its own two-argument
        # _install_inner. Demanding four of it asserted a relationship that does
        # not exist -- the first version of this test did exactly that, and the
        # failure it reported was the test's own mistake, not a defect.
        forwarded = _params(FileDropEngine.install)
        self.assertEqual(forwarded, ["zip_path", "after_confirm",
                                     "fomod_choices", "member_root"])
        for cls in ENGINES:
            if not issubclass(cls, FileDropEngine):
                continue  # a different chain, with a different contract
            own = cls.__dict__.get("_install_inner")
            if own is None:
                continue
            self.assertEqual(_params(own), forwarded, cls.__name__)

    def test_every_engine_hook_matches_the_wrapper_that_calls_it(self):
        # The general form of the same rule, per inheritance chain: whichever
        # install wrapper a class actually resolves to must forward exactly the
        # parameter list its own _install_inner accepts.
        for cls in ENGINES:
            wrapper = _params(cls.install)
            hook = _params(cls._install_inner)
            self.assertEqual(hook, wrapper, cls.__name__)

    def test_no_engine_probes_another_engine_by_hasattr_in_main(self):
        # main.py used hasattr(engine, "_set_enabled_inner") as "is this
        # file_drop?". Every engine inherits that method, so the probe answered
        # yes for root_merge and forwarded arguments it could not accept.
        #
        # Read as AST, not as text: the fix left explanatory comments that quote
        # the old probe, and a substring search cannot tell a comment from code.
        with open(os.path.join(REPO, "main.py"), "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        probed = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "hasattr"):
                continue
            names = [a.value for a in node.args
                     if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            if names and names[0] in self.INHERITED_EVERYWHERE:
                probed.append((names[0], node.lineno))
        self.assertEqual(
            probed, [],
            "main.py still decides capability by probing a method every engine "
            "inherits: %r" % (probed,))

    #: Methods every engine has, so their PRESENCE says nothing about which
    #: engine this is. Probing them is the Round 86 bug.
    INHERITED_EVERYWHERE = ("_set_enabled_inner", "_install_inner",
                            "_uninstall_inner", "_rollback_inner",
                            "_reclaim_inner", "_handover_inner",
                            "archive_mods")

    def test_the_source_actually_asks_the_declared_flags(self):
        # The other half: the guards must read the flags, or deleting the probe
        # would be enough to pass and the arguments would be dropped silently.
        #
        # Counted per flag, not "at least one somewhere": THREE flags guard
        # three different RPCs, and a census notices if one guard loses its
        # flag. SUPPORTS_MEMBER_ROOT guards both inspect() and install().
        expected = {"SUPPORTS_FOMOD": 1, "SUPPORTS_MEMBER_ROOT": 2,
                    "SUPPORTS_ARCHIVE_MODS": 1}
        with open(os.path.join(REPO, "main.py"), "r", encoding="utf-8") as f:
            src = f.read()
        found = {flag: src.count('getattr(engine, "%s"' % flag)
                 for flag in expected}
        self.assertEqual(found, expected)


class TestDeclaredCapabilities(unittest.TestCase):
    """The flags main.py now asks are declarative, not inherited-by-accident."""

    def test_every_engine_declares_all_three_flags_as_booleans(self):
        for cls in ENGINES:
            for flag in ("SUPPORTS_FOMOD", "SUPPORTS_MEMBER_ROOT",
                         "SUPPORTS_ARCHIVE_MODS"):
                self.assertIsInstance(getattr(cls, flag, None), bool,
                                      "%s.%s" % (cls.__name__, flag))

    def test_the_three_engines_disagree_where_they_must(self):
        # FileDropEngine is the one that can do all three; the other two cannot
        # do any of them. If this ever becomes uniform, the flags have stopped
        # carrying information and main.py's guards are dead code.
        self.assertEqual(
            (FileDropEngine.SUPPORTS_FOMOD, FileDropEngine.SUPPORTS_MEMBER_ROOT,
             FileDropEngine.SUPPORTS_ARCHIVE_MODS), (True, True, True))
        for cls in (Engine, RootMergeEngine):
            self.assertEqual(
                (cls.SUPPORTS_FOMOD, cls.SUPPORTS_MEMBER_ROOT,
                 cls.SUPPORTS_ARCHIVE_MODS), (False, False, False), cls.__name__)


class _RootMergeCase(unittest.TestCase):
    """A synthetic root_merge game (its own Steam tree + private registry)."""

    def setUp(self):
        self.t = MultiRootTree()
        self.t.env()
        self.eng = self.t.engine()
        self.addCleanup(self.t.cleanup)
        self.zip = _mod_zip(os.path.join(self.t.inbox, "Probe.zip"))


class TestRootMergeInstallWorks(_RootMergeCase):
    """Defect B, end to end: a plain import must install, not E_UNKNOWN."""

    def test_a_plain_import_succeeds(self):
        r = self.eng.install(self.zip, after_confirm=True)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["data"]["packageId"], "probe.mod")

    def test_the_files_really_land_and_the_journal_records_them(self):
        r = self.eng.install(self.zip, after_confirm=True)
        self.assertEqual(r["data"]["files"], 2, r)
        self.assertTrue(os.path.isfile(self.t.root("mods/ProbeMod/ProbeMod.archive")))
        self.assertTrue(os.path.isfile(self.t.root("mods/ProbeMod/info.json")))
        placed = [e for e in self.eng.journal.events(r["data"]["txn"])
                  if e.get("event") == "FILE_PLACED"]
        self.assertEqual(len(placed), 2, placed)

    def test_the_confirm_phase_writes_nothing(self):
        r = self.eng.install(self.zip, after_confirm=False)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["data"]["phase"], "confirm")
        self.assertFalse(os.path.exists(self.t.root("mods/ProbeMod")))

    def test_it_is_never_e_unknown(self):
        # The assertion the old suite lacked: any code, but not the catch-all.
        for root, fomod in ((None, None), ("", None), (None, {})):
            r = self.eng.install(self.zip, after_confirm=False,
                                 member_root=root, fomod_choices=fomod)
            self.assertNotEqual(r.get("code"), "E_UNKNOWN", r)


class TestRootMergeRefusesWhatItCannotDo(_RootMergeCase):
    """An unsupported argument is an ANSWER, with a word the UI can translate."""

    def test_member_root_is_refused_not_ignored(self):
        r = self.eng.install(self.zip, after_confirm=False, member_root="mods/ProbeMod")
        self.assertFalse(r["ok"], r)
        self.assertEqual(r["code"], "E_CAPABILITY_DISABLED")
        self.assertEqual((r.get("data") or {}).get("reason"), "no_member_root")

    def test_fomod_choices_are_refused_not_ignored(self):
        r = self.eng.install(self.zip, after_confirm=False,
                             fomod_choices={"Step:One": ["A"]})
        self.assertFalse(r["ok"], r)
        self.assertEqual(r["code"], "E_CAPABILITY_DISABLED")
        self.assertEqual((r.get("data") or {}).get("reason"), "no_fomod")

    def test_an_empty_fomod_choice_dict_is_treated_as_no_choice(self):
        # main.py normalises {} to None, so the engine must not refuse it: an
        # empty selection is "the user picked nothing", not "FOMOD requested".
        r = self.eng.install(self.zip, after_confirm=False, fomod_choices={})
        self.assertTrue(r["ok"], r)

    def test_archive_mods_is_refused_with_its_own_envelope(self):
        # The bug the user reported: this used to raise ModError out of a
        # method whose callers all treat it as envelope-returning.
        r = self.eng.archive_mods(self.zip)
        self.assertFalse(r["ok"], r)
        self.assertEqual(r["code"], "E_CAPABILITY_DISABLED")
        self.assertEqual((r.get("data") or {}).get("reason"), "no_archive_mods")

    def test_archive_mods_never_mentions_a_parser_name(self):
        r = self.eng.archive_mods(self.zip)
        text = json.dumps(r)
        self.assertNotIn("path_map", text)
        self.assertNotIn("manifest parser", text)


class TestArchiveModsStillWorksWhereItShould(unittest.TestCase):
    """The fix must not disable the archive picker for the engine that has it.

    This half is the one that could regress quietly: Round 86 made root_merge
    answer ``no_archive_mods``, and the easy way to "fix" the reported bug is to
    make ``archive_mods`` refuse everywhere. So a real file_drop engine is asked
    for real roots of a real two-mod archive.
    """

    def test_file_drop_still_declares_support_and_answers_real_roots(self):
        self.assertTrue(FileDropEngine.SUPPORTS_ARCHIVE_MODS)
        self.assertEqual(RootMergeEngine.SUPPORTS_ARCHIVE_MODS, False)
        self.assertTrue(callable(getattr(FileDropEngine, "archive_mods", None)))
        self.assertIn("json_map", manifest.PARSERS)

        t = SecondTree()
        t.env()
        self.addCleanup(t.cleanup)
        eng = t.engine()
        self.assertIsInstance(eng, FileDropEngine)
        self.assertNotIsInstance(eng, RootMergeEngine)

        path = os.path.join(t.inbox, "TwoMods.zip")
        # SecondTree's descriptor maps id/name/version onto modId/title/semver
        # and looks for mod.json at the root or one level down.
        with zipfile.ZipFile(path, "w") as z:
            for root in ("Pack/ModA", "Pack/ModB"):
                z.writestr(root + "/mod.json", json.dumps({
                    "modId": root.split("/")[-1].lower(),
                    "title": root.split("/")[-1],
                    "semver": "1.0.0",
                }))
                z.writestr(root + "/" + root.split("/")[-1] + ".dat", "x")

        r = eng.archive_mods(path)
        self.assertTrue(r["ok"], r)
        roots = sorted(rec["root"] for rec in r["data"]["roots"])
        self.assertEqual(roots, ["Pack/ModA", "Pack/ModB"], r)
        self.assertEqual(r["data"]["count"], 2, r)


class TestRegistryRejectsAnUnknownParser(unittest.TestCase):
    """A descriptor naming a parser nobody wrote must fail at LOAD time."""

    def setUp(self):
        self.base = os.path.join(REPO, ".decky-test-tmp",
                                 "r86parser-" + os.urandom(5).hex())
        os.makedirs(os.path.join(self.base, "registry", "games"), exist_ok=True)
        self.addCleanup(shutil.rmtree, self.base, True)

    def _write(self, descriptor):
        with open(os.path.join(self.base, "registry", "games", "g.json"),
                  "w", encoding="utf-8") as f:
            json.dump(descriptor, f)
        with open(os.path.join(self.base, "registry", "registry.json"),
                  "w", encoding="utf-8") as f:
            json.dump({
                "schema": 1,
                "capability_gate": {"enabled_game_status": "enabled",
                                    "max_enabled_games_in_mvp": 1},
                "descriptors": {"g": {"file": "registry/games/g.json"}},
                "loader_catalog": {},
            }, f)

    def test_an_unregistered_parser_name_fails_the_load(self):
        self._write({"id": "g", "status": "enabled",
                     "mod_package": {"parser": "path_map"}})
        with self.assertRaises(ModError) as ctx:
            Registry(base_dir=self.base)
        self.assertIn("path_map", ctx.exception.detail)
        self.assertIn("g.json", ctx.exception.detail)
        self.assertIn("not registered", ctx.exception.detail)

    def test_the_message_lists_what_is_actually_available(self):
        self._write({"id": "g", "status": "enabled",
                     "mod_package": {"parser": "nonesuch"}})
        with self.assertRaises(ModError) as ctx:
            Registry(base_dir=self.base)
        for known in sorted(manifest.PARSERS):
            self.assertIn(known, ctx.exception.detail)

    def test_a_registered_parser_loads(self):
        self._write({"id": "g", "status": "enabled",
                     "mod_package": {"parser": "json_map"}})
        reg = Registry(base_dir=self.base)
        self.assertIn("g", reg.descriptors)

    def test_an_omitted_parser_loads_because_json_map_is_the_documented_default(self):
        self._write({"id": "g", "status": "enabled",
                     "mod_package": {"manifest_globs": ["mod.json"]}})
        reg = Registry(base_dir=self.base)
        self.assertIn("g", reg.descriptors)

    def test_every_shipped_descriptor_passes_the_check(self):
        # The real registry, unmodified: proves the two path_map declarations
        # this round removed were the only ones.
        reg = Registry()
        self.assertTrue(reg.descriptors)


class TestTheRpcBoundaryAnswersInWords(_RootMergeCase):
    """main.py is where the user actually meets these engines."""

    def setUp(self):
        super().setUp()
        self._real = main.Registry
        main.Registry = lambda: Registry(base_dir=self.t.reg_root)
        self.addCleanup(self._restore)
        self.plugin = main.Plugin()
        # Patching main.Registry alone is not enough: FileDropEngine imports
        # Registry into ITS OWN module namespace and builds one when nobody
        # passes a registry in. So main._make_engine() asks our lambda which game
        # is active, then constructs an engine that asks the REAL registry -- the
        # engine then reports game_id="stardew" and every path resolves against
        # a game that is not in this synthetic Steam tree (E_GAME_NOT_FOUND).
        # Handing the fixture's own engine to the plugin is the honest seam.
        self.plugin.engine = self.eng

    def _restore(self):
        main.Registry = self._real

    def test_install_forwards_nothing_root_merge_cannot_take(self):
        r = asyncio.run(self.plugin.install(self.zip, False))
        self.assertTrue(r["ok"], r)          # was E_UNKNOWN before Round 86
        self.assertEqual(r["data"]["phase"], "confirm")

    def test_member_root_at_the_rpc_boundary_is_refused_with_a_reason(self):
        r = asyncio.run(self.plugin.install(self.zip, False, None, "mods/ProbeMod"))
        self.assertFalse(r["ok"], r)
        self.assertEqual(r["code"], "E_CAPABILITY_DISABLED")
        self.assertEqual((r.get("data") or {}).get("reason"), "no_member_root")

    def test_fomod_at_the_rpc_boundary_is_refused_with_a_reason(self):
        r = asyncio.run(self.plugin.install(self.zip, False, {"S:G": ["A"]}, None))
        self.assertFalse(r["ok"], r)
        self.assertEqual((r.get("data") or {}).get("reason"), "no_fomod")

    def test_archive_mods_at_the_rpc_boundary_is_refused_with_a_reason(self):
        r = asyncio.run(self.plugin.archive_mods(self.zip))
        self.assertFalse(r["ok"], r)
        self.assertEqual(r["code"], "E_CAPABILITY_DISABLED")
        self.assertEqual((r.get("data") or {}).get("reason"), "no_archive_mods")

    def test_inspect_with_member_root_is_refused_with_a_reason(self):
        r = asyncio.run(self.plugin.inspect(self.zip, "mods/ProbeMod"))
        self.assertFalse(r["ok"], r)
        self.assertEqual(r["code"], "E_CAPABILITY_DISABLED")
        self.assertEqual((r.get("data") or {}).get("reason"), "no_member_root")

    def test_inspect_without_member_root_still_works(self):
        r = asyncio.run(self.plugin.inspect(self.zip))
        self.assertTrue(r["ok"], r)


if __name__ == "__main__":
    unittest.main()
