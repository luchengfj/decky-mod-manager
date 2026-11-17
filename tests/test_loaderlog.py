"""Tests for deckymod/loaderlog.py against a transcription of a REAL device log.

The fixture below is copied from /home/deck/.config/StardewValley/ErrorLogs/SMAPI-latest.txt
as read off the device on 2026-11-17 (SMAPI 4.5.2 / Stardew Valley 1.6.15). It is
not synthetic: every quirk exercised here was observed, including the
"Place Furniture Outside (Furniture Anywhere Redux) by glymr 1.0.5 by glymr" row
whose display name itself contains " by ", and the version-less
"LookupAnything/i18n" skip.

Run: python -m unittest tests.test_loaderlog -v
"""

import ast
import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deckymod import loaderlog  # noqa: E402

REAL_LOG = """\
[18:41:58 INFO  SMAPI] SMAPI 4.5.2 with Stardew Valley 1.6.15 build 24356 on Unix 7.2.7.2
[18:41:58 INFO  SMAPI] Mods go here: ~/.local/share/Steam/steamapps/common/Stardew Valley/Mods
[18:42:05 DEBUG SMAPI] Loading mods...
[18:42:05 TRACE SMAPI]    LookupAnything/i18n (from Mods/LookupAnything/i18n, ID: <unknown>)...
[18:42:05 TRACE SMAPI]       Failed: it contains files, but none of them are manifest.json.
[18:42:06 TRACE SMAPI]    Automate (from Mods/Automate/Automate.dll, ID: Pathoschild.Automate, assembly version: 2.6.1)...
[18:42:08 INFO  SMAPI] Loaded 22 mods:
[18:42:08 INFO  SMAPI]    Automate 2.6.1 by Pathoschild | Lets you automate crafting machines, fruit trees, and more by connecting them to chests.
[18:42:08 INFO  SMAPI]    AutomaticGates 2.5.5 by Rakiin aKa ScheKaa | Opens and closes gates automatically
[18:42:08 INFO  SMAPI]    Better Ranching 2.0.5 by Urbanyeti | Prevents failed milk/shear attempts.
[18:42:08 INFO  SMAPI]    SDV-HD2D 0.9.1 by ivory | Octopath-style HD-2D rendering.
[18:42:08 INFO  SMAPI]    Tractor Mod 4.24.4 by Pathoschild | Lets you buy a tractor.
[18:42:08 INFO  SMAPI] Loaded 3 content packs:
[18:42:08 INFO  SMAPI]    Immersive Spouses 0.8.0 by someguy363 | for Content Patcher | Updates schedules for spouses.
[18:42:08 INFO  SMAPI]    Place Furniture Outside (Furniture Anywhere Redux) by glymr 1.0.5 by glymr | for Content Patcher | Allows you to place furniture outside.
[18:42:08 INFO  SMAPI]    Xiddav's Little Red School House - Students and Teachers 2.3.1-SNT by Xiddav | for Content Patcher | Adds students.
[18:42:08 ERROR SMAPI]    Skipped mods
[18:42:08 ERROR SMAPI]    --------------------------------------------------
[18:42:08 ERROR SMAPI]       These mods could not be added to your game.
[18:42:08 ERROR SMAPI]       - (CP) Laundry Machines 1.1.0 because it requires mods which aren't installed (hxw.tilesheets, selph.ExtraMachineConfig, selph.FurnitureMachine).
[18:42:08 ERROR SMAPI]       - LookupAnything/i18n because it contains files, but none of them are manifest.json.
[18:42:08 ERROR SMAPI]       - SMAPI 4.5.2 installer because the SMAPI installer isn't a mod (you can delete this folder after running the installer file).
[18:42:08 ERROR SMAPI]       - Xiddav's Little Red School House 2.3.0 because it requires mods which aren't installed (Xiddav.tilesheet).
[18:42:08 INFO  SMAPI]    Patched game code
[18:42:08 INFO  SMAPI]    --------------------------------------------------
[18:42:08 INFO  SMAPI]       - Bigger Backpack
[18:42:08 INFO  SMAPI]       - SDV-HD2D
[18:42:08 DEBUG SMAPI] Launching mods...
"""


def _cfg():
    """The descriptor's real block, read from disk rather than duplicated here.

    Duplicating the patterns in the test would let the descriptor rot while the
    tests stayed green -- the exact class of bug this suite exists to prevent.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "registry", "games", "stardew.json")
    with io.open(path, encoding="utf-8") as f:
        doc = json.load(f)
    return doc["loader_detection"]["loader_log"]


class TestParseRealLog(unittest.TestCase):
    def test_loaded_rows(self):
        r = loaderlog.parse(REAL_LOG, _cfg())
        self.assertTrue(r["ok"])
        names = [x["name"] for x in r["loaded"]]
        self.assertEqual(names, ["Automate", "AutomaticGates", "Better Ranching",
                                 "SDV-HD2D", "Tractor Mod"])
        self.assertEqual(r["loaded"][0]["version"], "2.6.1")
        self.assertEqual(r["loaded"][0]["author"], "Pathoschild")
        self.assertTrue(r["loaded"][0]["summary"].startswith("Lets you automate"))
        # header count is preserved even though the fixture is a subset
        self.assertEqual(r["counts"]["loaded"], 22)

    def test_content_packs(self):
        r = loaderlog.parse(REAL_LOG, _cfg())
        self.assertEqual(len(r["content_packs"]), 3)
        self.assertEqual(r["counts"]["content_packs"], 3)

    def test_name_containing_by_is_not_mis_split(self):
        """The row whose display name itself contains ' by ' must survive.

        A greedy name pattern would swallow "glymr 1.0.5" and report version
        "1.0.5" as part of the name with no author. This is the regression guard.
        """
        r = loaderlog.parse(REAL_LOG, _cfg())
        row = [x for x in r["content_packs"] if "Furniture" in x["name"]][0]
        self.assertIn("glymr", row["name"])
        self.assertEqual(row["version"], "1.0.5")
        self.assertEqual(row["author"], "glymr")

    def test_prerelease_version_suffix(self):
        r = loaderlog.parse(REAL_LOG, _cfg())
        row = [x for x in r["content_packs"] if "School House" in x["name"]][0]
        self.assertEqual(row["version"], "2.3.1-SNT")

    def test_skipped_rows_with_and_without_version(self):
        r = loaderlog.parse(REAL_LOG, _cfg())
        self.assertEqual(len(r["skipped"]), 4)
        with_ver = [x for x in r["skipped"] if x["name"].startswith("(CP) Laundry")]
        self.assertEqual(with_ver[0]["version"], "1.1.0")
        self.assertEqual(with_ver[0]["missing_ids"],
                         ["hxw.tilesheets", "selph.ExtraMachineConfig",
                          "selph.FurnitureMachine"])
        no_ver = [x for x in r["skipped"] if x["name"] == "LookupAnything/i18n"][0]
        self.assertEqual(no_ver["version"], "")
        self.assertEqual(no_ver["missing_ids"], [])
        self.assertIn("none of them are manifest.json", no_ver["reason"])

    def test_patched_rows(self):
        r = loaderlog.parse(REAL_LOG, _cfg())
        self.assertEqual([x["name"] for x in r["patched"]],
                         ["Bigger Backpack", "SDV-HD2D"])

    def test_trace_lines_before_headers_are_ignored(self):
        """'Automate (from Mods/...)' appears BEFORE 'Loaded 22 mods:'.

        If the state machine started in the loaded section it would emit a bogus
        row with name 'Automate (from ...)' and no version.
        """
        r = loaderlog.parse(REAL_LOG, _cfg())
        self.assertFalse([x for x in r["loaded"] if "from Mods/" in x["name"]])


class TestParseRobustness(unittest.TestCase):
    def test_empty_log(self):
        r = loaderlog.parse("", _cfg())
        self.assertTrue(r["ok"])
        self.assertEqual(r["loaded"], [])
        self.assertEqual(r["skipped"], [])

    def test_garbage_log_yields_no_rows(self):
        r = loaderlog.parse("hello world\n" * 50, _cfg())
        self.assertTrue(r["ok"])
        self.assertEqual(r["loaded"], [])

    def test_bad_regex_in_descriptor_is_a_value(self):
        cfg = dict(_cfg(), loaded_header="([unclosed")
        r = loaderlog.parse(REAL_LOG, cfg)
        # header fails to compile -> section never opens -> zero rows, still ok
        self.assertTrue(r["ok"])
        self.assertEqual(r["loaded"], [])

    def test_missing_row_pattern_is_reported(self):
        cfg = dict(_cfg())
        cfg.pop("loaded_row")
        r = loaderlog.parse(REAL_LOG, cfg)
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "log_unparsed")

    def test_report_is_capped(self):
        many = "\n".join(["[x INFO  SMAPI] Loaded 1 mods:"]
                         + ["[x INFO  SMAPI]    M%d 1.0 by A | s" % i
                            for i in range(loaderlog.MAX_REPORTED + 25)])
        r = loaderlog.parse(many, _cfg())
        self.assertEqual(len(r["loaded"]), loaderlog.MAX_REPORTED)


class TestCorrelation(unittest.TestCase):
    def test_loaded_by_display_name(self):
        r = loaderlog.parse(REAL_LOG, _cfg())
        mods = [{"dir_name": "Automate", "name": "Automate"}]
        out = loaderlog.annotate(mods, r)
        self.assertEqual(out[0]["load_status"], "loaded")
        self.assertEqual(out[0]["load_version"], "2.6.1")

    def test_folder_name_without_spaces_still_matches(self):
        """Folder 'BetterRanching' vs log name 'Better Ranching'."""
        r = loaderlog.parse(REAL_LOG, _cfg())
        out = loaderlog.annotate([{"dir_name": "BetterRanching", "name": ""}], r)
        self.assertEqual(out[0]["load_status"], "loaded")

    def test_skipped_mod_reports_reason_and_missing_ids(self):
        r = loaderlog.parse(REAL_LOG, _cfg())
        out = loaderlog.annotate([{"dir_name": "LaundryMachines",
                                   "name": "(CP) Laundry Machines"}], r)
        self.assertEqual(out[0]["load_status"], "skipped")
        self.assertIn("selph.ExtraMachineConfig", out[0]["load_missing_ids"])

    def test_unlisted_mod_is_unknown_not_loaded(self):
        """The whole point: absence from the log must never read as success."""
        r = loaderlog.parse(REAL_LOG, _cfg())
        out = loaderlog.annotate([{"dir_name": "BrandNewMod", "name": "Brand New"}], r)
        self.assertEqual(out[0]["load_status"], "unknown")
        self.assertIn("not listed", out[0]["load_note"])

    def test_no_report_marks_everything_unknown(self):
        out = loaderlog.annotate([{"dir_name": "A", "name": "A"},
                                  {"dir_name": "B", "name": "B"}], None)
        self.assertEqual([x["load_status"] for x in out], ["unknown", "unknown"])

    def test_failed_report_marks_everything_unknown(self):
        bad = {"ok": False, "reason": "log_missing", "detail": ""}
        out = loaderlog.annotate([{"dir_name": "A", "name": "A"}], bad)
        self.assertEqual(out[0]["load_status"], "unknown")

    def test_directory_key_from_the_real_scan_is_honoured(self):
        """manifest.scan_installed_mods returns 'dir', NOT 'dir_name'.

        A device run found this: the folder fallback read a key that never
        exists, so every mod whose manifest name differs from its folder (or
        whose manifest failed to parse, leaving name empty) fell through to
        'unknown'. The parser was right and the correlation was silently blind.
        """
        r = loaderlog.parse(REAL_LOG, _cfg())
        out = loaderlog.annotate([{"dir": "Automate", "name": "Automate"}], r)
        self.assertEqual(out[0]["load_status"], "loaded")

    def test_manifest_less_folder_matches_by_directory(self):
        """A folder whose manifest could not be read has name=None."""
        r = loaderlog.parse(REAL_LOG, _cfg())
        out = loaderlog.annotate([{"dir": "SMAPI 4.5.2 installer", "name": None}], r)
        self.assertEqual(out[0]["load_status"], "skipped")

    def test_skipped_subfolder_matches_its_parent_directory(self):
        """SMAPI names a skipped SUBSECTION as 'LookupAnything/i18n'.

        Normalized that is a different string from the folder 'LookupAnything',
        so without splitting on '/' the row matched nothing and the folder was
        reported 'unknown' while the log had in fact told us why it was skipped.
        """
        r = loaderlog.parse(REAL_LOG, _cfg())
        out = loaderlog.annotate([{"dir": "LookupAnything", "name": "Lookup Anything"}], r)
        self.assertEqual(out[0]["load_status"], "skipped")
        self.assertIn("none of them are manifest.json", out[0]["load_reason"])


class TestPathsAndSummary(unittest.TestCase):
    def test_candidate_templates_expand(self):
        cfg = _cfg()
        got = loaderlog.candidate_paths("/g", "/h", "/x", cfg)
        self.assertTrue(got[0].startswith("/h/.config/StardewValley/ErrorLogs/"))
        self.assertIn("/g/SMAPI-latest.txt", got)

    def test_unknown_token_is_left_literal_not_dropped(self):
        got = loaderlog.candidate_paths("/g", "/h", "/x",
                                        {"candidates": ["${NOPE}/a.txt"]})
        self.assertEqual(got, ["${NOPE}/a.txt"])

    def test_missing_log_is_a_reason_not_a_code(self):
        got = loaderlog.find_log(["/nonexistent/one.txt", "/nonexistent/two.txt"])
        self.assertFalse(got["ok"])
        self.assertEqual(got["reason"], "log_missing")
        self.assertNotIn("E_", json.dumps(got))

    def test_summary_counts(self):
        r = loaderlog.parse(REAL_LOG, _cfg())
        annotated = loaderlog.annotate(
            [{"dir_name": "Automate", "name": "Automate"},
             {"dir_name": "LaundryMachines", "name": "(CP) Laundry Machines"},
             {"dir_name": "Zzz", "name": "Zzz"}], r)
        s = loaderlog.summarize(r, annotated)
        self.assertTrue(s["available"])
        self.assertEqual(s["skipped"], 4)
        self.assertEqual(s["unknown"], 1)

    def test_inspect_disabled_descriptor(self):
        got = loaderlog.inspect("/g", "/h", "/x", {"enabled": False}, [])
        self.assertFalse(got["ok"])
        self.assertEqual(got["reason"], "not_configured")

    def test_inspect_never_raises_on_a_directory(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cfg = dict(_cfg(), candidates=[root])
        got = loaderlog.inspect(root, "/h", "/x", cfg, [])
        self.assertFalse(got["ok"])       # a directory is not a log


class TestNoGameLiteralsInModule(unittest.TestCase):
    def test_module_has_no_game_specific_strings(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with io.open(os.path.join(root, "deckymod", "loaderlog.py"),
                     encoding="utf-8") as f:
            src = f.read()
        for literal in ("413150", "Stardew", "SMAPI-latest", "stardewvalley"):
            self.assertNotIn(literal, src,
                             "%r must live in the descriptor, not the parser" % literal)

    def test_module_does_not_write(self):
        """No write-mode open, and no filesystem mutation, checked via the AST.

        Two false starts shaped this test. A version that searched for quote-
        heavy string literals did not compile at all. A version that forbade
        any call named 'replace' also rejected str.replace, which the module
        legitimately uses to expand ${...} templates. So the check resolves
        each attribute chain to its root name and only objects rooted at os/
        shutil can be file operations.
        """
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with io.open(os.path.join(root, "deckymod", "loaderlog.py"),
                     encoding="utf-8") as f:
            tree = ast.parse(f.read())

        def chain(node):
            parts = []
            while isinstance(node, ast.Attribute):
                parts.append(node.attr)
                node = node.value
            if isinstance(node, ast.Name):
                parts.append(node.id)
                return list(reversed(parts))
            return []

        writes = {"rename", "remove", "replace", "chmod", "mkdir",
                  "makedirs", "unlink", "rmtree", "copy", "copyfile",
                  "copy2", "move", "dump", "dump_all", "write",
                  "writelines", "truncate", "write_text", "write_bytes"}
        opened = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id == "open":
                opened += 1
                mode = None
                if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                    mode = node.args[1].value
                if mode is not None:
                    for bad in ("w", "a", "+", "x"):
                        self.assertNotIn(bad, str(mode),
                                         "write mode %r in loaderlog" % mode)
                continue
            if not isinstance(fn, ast.Attribute):
                continue
            parts = chain(fn)
            if parts and parts[0] in ("os", "shutil"):
                self.assertNotIn(parts[-1], writes,
                                 "loaderlog must not call %s" % ".".join(parts))
        self.assertEqual(opened, 1, "expected exactly one open(), the log read")


if __name__ == "__main__":
    unittest.main()
