"""Tests for deckymod/sevenzip.py — the .7z branch of mod import.

Goal item 3 asks for ".zip **and** .7z" import. The stdlib cannot read 7z and we
must not add a dependency, so the production path shells out to the 7z binary
SteamOS already ships. That makes the interesting logic *not* the archiver but
our validation of its output — which is exactly what these tests cover.

The runner is injectable, so every test here runs offline on Windows with a fake
runner. ``TestRealToolIntegration`` skips itself when no 7z is installed; on the
Deck it exercises a genuine archive end to end.
"""

import os
import shutil
import subprocess
import sys
import unittest
import uuid

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from deckymod import sevenzip  # noqa: E402
from deckymod.errors import ModError  # noqa: E402

# tempfile.mkdtemp() creates a 0o700 dir whose DACL the Windows sandbox refuses
# to write into (WinError 5 / PermissionError). Anchor a plain makedirs under the
# workspace instead — same approach as tests/test_mvp.py::workspace_tmpdir.
_TMP_ROOT = os.path.join(_ROOT, ".decky-test-tmp")

LIMITS = {
    "max_compressed_bytes": 268435456,
    "max_uncompressed_bytes": 268435456,
    "max_entries": 4096,
    "max_compression_ratio": 100,
    "max_path_depth": 16,
}

SLT_HEADER = "----------"


def _slt(entries):
    """Build `7z l -slt -ba` output that looks like the real thing.

    ``-ba`` suppresses the archive header and footer, so the output is just the
    repeating ``key = value`` blocks. entries: (name, size, attrs) tuples or dicts.
    """
    out = []
    for e in entries:
        if isinstance(e, tuple):
            name, size, attrs = e
        else:
            name = e["name"]
            size = e.get("size", 0)
            attrs = e.get("attrs", "....A")
        out.append("Path = %s" % name)
        out.append("Size = %d" % size)
        out.append("Packed Size = %d" % max(1, size // 2))
        out.append("Modified = 2026-11-15 10:00:00")
        out.append("Attributes = %s" % attrs)
        out.append("")
    return "\n".join(out)


class _FakeRunner:
    """Records argv and replays queued results (or one fixed result)."""

    def __init__(self, out="", code=0, stderr="", queue=None):
        self.out = out
        self.code = code
        self.stderr = stderr
        self.queue = list(queue) if queue else None
        self.calls = []

    def __call__(self, argv, cwd=None):
        self.calls.append(list(argv))
        if self.queue:
            return self.queue.pop(0)
        return {"code": self.code, "stdout": self.out, "stderr": self.stderr}


class _Base(unittest.TestCase):
    def setUp(self):
        os.makedirs(_TMP_ROOT, exist_ok=True)
        self.tmp = os.path.join(_TMP_ROOT, "dz7-" + uuid.uuid4().hex[:8])
        os.makedirs(self.tmp, exist_ok=True)
        self.arc = os.path.join(self.tmp, "probe.7z")
        with open(self.arc, "wb") as f:
            f.write(sevenzip_MAGIC + b"\x00" * 100)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_inspect(self, entries, **kw):
        runner = kw.pop("runner", None) or _FakeRunner(out=_slt(entries))
        return sevenzip.inspect_7z(self.arc, LIMITS, runner=runner, tool="/usr/bin/7z", **kw)

    def assert_code(self, code, fn, *a, **kw):
        with self.assertRaises(ModError) as ctx:
            fn(*a, **kw)
        self.assertEqual(ctx.exception.code, code, str(ctx.exception))


sevenzip_MAGIC = b"7z\xbc\xaf'\x1c"


class TestParseSlt(_Base):
    def test_parses_key_value_blocks(self):
        blocks = sevenzip._parse_slt(_slt([("a/manifest.json", 10, "....A"),
                                          ("a/x.dll", 20, "....A")]))
        self.assertEqual([b["Path"] for b in blocks], ["a/manifest.json", "a/x.dll"])
        self.assertEqual(blocks[0]["Size"], "10")

    def test_empty_output_yields_no_blocks(self):
        self.assertEqual(sevenzip._parse_slt(""), [])

    def test_blocks_without_path_are_dropped(self):
        text = "Path = inner\nSize = 1\n\nSize = 2\n\n"
        blocks = sevenzip._parse_slt(text)
        self.assertEqual([b["Path"] for b in blocks], ["inner"])

    def test_verbose_header_before_the_separator_is_not_an_entry(self):
        # The non-`-ba` verbose form starts with an archive stanza whose Path is
        # the archive itself; treating it as an entry made every listing look
        # like a duplicate. Everything before ---------- must be discarded.
        verbose = "\n".join([
            "Path = probe.7z",
            "Type = 7z",
            "Physical Size = 1234",
            "----------",
            "Path = Automate/manifest.json",
            "Size = 200",
            "",
        ])
        blocks = sevenzip._parse_slt(verbose)
        self.assertEqual([b["Path"] for b in blocks], ["Automate/manifest.json"])


class TestToolDiscovery(_Base):
    def test_find_tool_returns_none_when_nothing_is_installed(self):
        real_which = shutil.which
        sevenzip.shutil.which = lambda name: None
        try:
            self.assertIsNone(sevenzip.find_tool())
        finally:
            sevenzip.shutil.which = real_which

    def test_find_tool_returns_the_first_candidate(self):
        real_which = shutil.which
        seen = []

        def fake(name):
            seen.append(name)
            return "/opt/7z" if name == "7za" else None

        sevenzip.shutil.which = fake
        try:
            self.assertEqual(sevenzip.find_tool(), "/opt/7z")
        finally:
            sevenzip.shutil.which = real_which
        self.assertEqual(seen, ["7z", "7za"])

    def test_missing_tool_produces_a_readable_error_not_an_oserror(self):
        self.assert_code("E_BAD_ARCHIVE", sevenzip.inspect_7z, self.arc, LIMITS,
                         runner=_FakeRunner(), tool=None)
        # the detail must name what we looked for so the log is actionable
        try:
            sevenzip.inspect_7z(self.arc, LIMITS, runner=_FakeRunner(), tool=None)
        except ModError as e:
            self.assertIn("7z", e.detail)


class TestEntryValidation(_Base):
    def test_accepts_a_normal_mod_layout(self):
        info = self.run_inspect([
            ("Automate/manifest.json", 300, "....A"),
            ("Automate/Automate.dll", 9000, "....A"),
            ("Automate/i18n/default.json", 40, "....A"),
        ])
        self.assertEqual(len(info["entries"]), 3)
        self.assertEqual(info["total_uncompressed"], 9340)
        self.assertFalse(any(e["is_dir"] for e in info["entries"]))

    def test_directory_entries_are_flagged_not_rejected(self):
        info = self.run_inspect([("Automate/", 0, "D...."), ("Automate/manifest.json", 5, "....A")])
        self.assertTrue(info["entries"][0]["is_dir"])
        self.assertFalse(info["entries"][1]["is_dir"])

    def test_absolute_path_is_refused(self):
        self.assert_code("E_UNSAFE_ENTRY", self.run_inspect, [("/etc/passwd", 10, "....A")])

    def test_windows_drive_path_is_refused(self):
        self.assert_code("E_UNSAFE_ENTRY", self.run_inspect, [("C:/Windows/x.dll", 10, "....A")])

    def test_backslash_separator_is_refused(self):
        self.assert_code("E_UNSAFE_ENTRY", self.run_inspect, [("Automate\\manifest.json", 10, "....A")])

    def test_parent_traversal_is_refused(self):
        self.assert_code("E_PATH_ESCAPE", self.run_inspect, [("Automate/../../evil.dll", 10, "....A")])

    def test_dot_segment_is_refused(self):
        self.assert_code("E_UNSAFE_ENTRY", self.run_inspect, [("Automate/./manifest.json", 10, "....A")])

    def test_symlink_is_refused(self):
        self.assert_code("E_UNSAFE_ENTRY", self.run_inspect, [("Automate/link", 10, "lrwxrwxrwx")])

    def test_device_entry_is_refused(self):
        self.assert_code("E_UNSAFE_ENTRY", self.run_inspect, [("Automate/null", 10, "crw-rw-rw-")])

    def test_depth_limit_is_enforced(self):
        deep = "/".join(["d"] * 20) + "/manifest.json"
        self.assert_code("E_UNSAFE_ENTRY", self.run_inspect, [(deep, 10, "....A")])

    def test_empty_path_is_refused(self):
        # a block that parsed but whose Path is whitespace only
        runner = _FakeRunner(out="----------\nPath = \nSize = 1\n\n")
        self.assert_code("E_UNSAFE_ENTRY", sevenzip.inspect_7z, self.arc, LIMITS,
                         runner=runner, tool="/usr/bin/7z")

    def test_forbidden_extension_is_refused(self):
        self.assert_code("E_UNSAFE_ENTRY", self.run_inspect,
                         [("Automate/setup.exe", 10, "....A")],
                         forbidden_ext={".exe"})

    def test_forbidden_extension_check_is_case_insensitive(self):
        self.assert_code("E_UNSAFE_ENTRY", self.run_inspect,
                         [("Automate/SETUP.EXE", 10, "....A")],
                         forbidden_ext={".exe"})

    def test_allowed_extension_passes_when_forbidden_set_excludes_it(self):
        info = self.run_inspect([("Automate/Automate.dll", 10, "....A")],
                                forbidden_ext={".exe", ".msi"})
        self.assertEqual(len(info["entries"]), 1)

    def test_duplicate_entry_is_refused(self):
        self.assert_code("E_DUPLICATE_ENTRY", self.run_inspect,
                         [("Automate/manifest.json", 1, "....A"),
                          ("Automate/manifest.json", 2, "....A")])

    def test_single_entry_over_the_cap_is_refused(self):
        small = dict(LIMITS, max_uncompressed_bytes=100)
        runner = _FakeRunner(out=_slt([("Automate/big.dll", 101, "....A")]))
        self.assert_code("E_ZIP_BOMB", sevenzip.inspect_7z, self.arc, small,
                         runner=runner, tool="/usr/bin/7z")

    def test_total_over_the_cap_is_refused(self):
        small = dict(LIMITS, max_uncompressed_bytes=100)
        runner = _FakeRunner(out=_slt([("a/x.dll", 60, "....A"), ("a/y.dll", 60, "....A")]))
        self.assert_code("E_ZIP_BOMB", sevenzip.inspect_7z, self.arc, small,
                         runner=runner, tool="/usr/bin/7z")

    def test_compressed_size_over_the_cap_is_refused_before_running_the_tool(self):
        tiny = dict(LIMITS, max_compressed_bytes=1)
        runner = _FakeRunner(out=_slt([("a/manifest.json", 1, "....A")]))
        self.assert_code("E_ZIP_BOMB", sevenzip.inspect_7z, self.arc, tiny,
                         runner=runner, tool="/usr/bin/7z")
        self.assertEqual(runner.calls, [], "must not spawn 7z when the file is too big")

    def test_too_many_entries_is_refused(self):
        few = dict(LIMITS, max_entries=2)
        runner = _FakeRunner(out=_slt([("a/%d.dll" % i, 1, "....A") for i in range(3)]))
        self.assert_code("E_ZIP_BOMB", sevenzip.inspect_7z, self.arc, few,
                         runner=runner, tool="/usr/bin/7z")


class TestToolFailures(_Base):
    def test_fatal_exit_is_reported_as_bad_archive(self):
        runner = _FakeRunner(out="", code=2, stderr="Cannot open the file as archive")
        self.assert_code("E_BAD_ARCHIVE", sevenzip.inspect_7z, self.arc, LIMITS,
                         runner=runner, tool="/usr/bin/7z")

    def test_warning_exit_1_is_still_accepted(self):
        runner = _FakeRunner(out=_slt([("a/manifest.json", 4, "....A")]), code=1)
        info = sevenzip.inspect_7z(self.arc, LIMITS, runner=runner, tool="/usr/bin/7z")
        self.assertEqual(len(info["entries"]), 1)

    def test_output_without_any_entry_is_bad_archive(self):
        runner = _FakeRunner(out=SLT_HEADER, code=0)
        self.assert_code("E_BAD_ARCHIVE", sevenzip.inspect_7z, self.arc, LIMITS,
                         runner=runner, tool="/usr/bin/7z")

    def test_listing_invocation_uses_slt_and_ba_and_never_extracts(self):
        runner = _FakeRunner(out=_slt([("a/manifest.json", 1, "....A")]))
        sevenzip.inspect_7z(self.arc, LIMITS, runner=runner, tool="/usr/bin/7z")
        argv = runner.calls[0]
        self.assertEqual(argv[1], "l")
        self.assertIn("-slt", argv)
        self.assertIn("-ba", argv)
        self.assertNotIn("x", [a for a in argv if a in ("x", "e")],
                         "inspection must not extract")

    def test_default_runner_wraps_oserror_as_mod_error(self):
        real = sevenzip.subprocess.run

        def boom(*a, **kw):
            raise OSError(2, "No such file or directory")

        sevenzip.subprocess.run = boom
        try:
            self.assert_code("E_BAD_ARCHIVE", sevenzip.default_runner, ["/nope/7z", "l"])
        finally:
            sevenzip.subprocess.run = real


class TestExtract(_Base):
    def test_extract_builds_an_x_command_with_overwrite_and_no_progress(self):
        runner = _FakeRunner(code=0)
        out = os.path.join(self.tmp, "out")
        sevenzip.extract_7z(self.arc, out, runner=runner, tool="/usr/bin/7z")
        argv = runner.calls[0]
        self.assertEqual(argv[1], "x")
        self.assertIn("-y", argv)
        self.assertIn("-bd", argv)
        self.assertIn("-o" + out, argv)
        self.assertIn(self.arc, argv)

    def test_extract_failure_is_op_failed_not_silent(self):
        self.assert_code("E_OP_FAILED", sevenzip.extract_7z, self.arc, self.tmp,
                         runner=_FakeRunner(code=2, stderr="Data Error"), tool="/usr/bin/7z")

    def test_extract_refuses_without_a_tool(self):
        # tool=None means "auto-detect". On a machine that really has 7z (the
        # Steam Deck does) there is no missing tool to simulate, so the premise
        # only exists where discovery fails. Assert the refusal there and skip
        # otherwise instead of asserting something the platform cannot produce.
        if sevenzip.find_tool() is not None:
            self.skipTest("7z is installed here; the no-tool premise needs a tool-less host")
        self.assert_code("E_BAD_ARCHIVE", sevenzip.extract_7z, self.arc, self.tmp,
                         runner=_FakeRunner(), tool=None)


class TestIs7z(_Base):
    def test_true_for_real_magic_and_extension(self):
        self.assertTrue(sevenzip.is_7z(self.arc))

    def test_false_when_the_magic_is_wrong(self):
        # a ZIP renamed to .7z must not be routed to the 7z code path
        fake = os.path.join(self.tmp, "renamed.7z")
        with open(fake, "wb") as f:
            f.write(b"PK\x03\x04" + b"\x00" * 50)
        self.assertFalse(sevenzip.is_7z(fake))

    def test_false_for_a_zip_extension(self):
        self.assertFalse(sevenzip.is_7z(os.path.join(self.tmp, "x.zip")))

    def test_false_for_a_missing_file(self):
        self.assertFalse(sevenzip.is_7z(os.path.join(self.tmp, "absent.7z")))


def _have_7z():
    return sevenzip.find_tool() is not None


@unittest.skipUnless(_have_7z(), "no 7z binary on this machine")
class TestRealToolIntegration(_Base):
    """Only runs where 7z exists (the Deck). Builds a real archive with it."""

    def test_real_archive_roundtrip(self):
        tool = sevenzip.find_tool()
        src = os.path.join(self.tmp, "src")
        os.makedirs(os.path.join(src, "Automate"))
        with open(os.path.join(src, "Automate", "manifest.json"), "w", encoding="utf-8") as f:
            f.write('{"UniqueID": "Pathoschild.Automate", "Name": "Automate", "Version": "1.28.1"}')
        with open(os.path.join(src, "Automate", "Automate.dll"), "wb") as f:
            f.write(b"MZ" + b"\x00" * 200)
        real = os.path.join(self.tmp, "real.7z")
        proc = subprocess.run([tool, "a", "-bd", real, "Automate"], cwd=src,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))

        info = sevenzip.inspect_7z(real, LIMITS, forbidden_ext={".exe"})
        names = sorted(e["name"] for e in info["entries"] if not e["is_dir"])
        self.assertIn("Automate/manifest.json", names)
        self.assertIn("Automate/Automate.dll", names)

        out = os.path.join(self.tmp, "out")
        os.makedirs(out)
        sevenzip.extract_7z(real, out)
        self.assertTrue(os.path.isfile(os.path.join(out, "Automate", "manifest.json")))


if __name__ == "__main__":
    unittest.main()
