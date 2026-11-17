"""Round 41: deckymod/openurl.py -- put a mod page on screen.

The device measurement (2026-11-17) is the whole design brief:
  xdg-open  -> exits 0, opens nothing (DISPLAY/WAYLAND_DISPLAY unset; and even
               with DISPLAY=:0 forced it breaks on a malformed desktop command)
  steam://openurl/<url> -> the Steam client navigates: a real tab appears at the
               URL and the main window lands on routes/externalweb
So the runner must be argv-based (no shell), the URL must be built from a numeric
id rather than accepted from the caller, and the exit code must never be treated
as proof that anything was displayed.
"""
import unittest

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deckymod import openurl  # noqa: E402

GOOD = "https://www.nexusmods.com/stardewvalley/mods/2400"


class _Recorder:
    def __init__(self, code=0, stderr=""):
        self.argv = None
        self.code = code
        self.stderr = stderr
        self.calls = 0

    def __call__(self, argv):
        self.calls += 1
        self.argv = argv
        return {"code": self.code, "stdout": "", "stderr": self.stderr}


class TestValidation(unittest.TestCase):
    def test_https_nexus_page_is_accepted(self):
        self.assertIsNone(openurl.validate_url(GOOD))

    def test_bare_nexusmods_host_is_accepted(self):
        self.assertIsNone(openurl.validate_url("https://nexusmods.com/stardewvalley/mods/1"))

    def test_http_is_refused(self):
        """Plain http would be a downgrade the client cannot warn about here."""
        reason = openurl.validate_url("http://www.nexusmods.com/stardewvalley/mods/1")
        self.assertIn("https", reason)

    def test_other_hosts_are_refused(self):
        """This is not a general 'open any URL' primitive."""
        for bad in ("https://example.com/x",
                    "https://nexusmods.com.evil.test/mods/1",
                    "https://www.nexusmods.com@evil.test/mods/1"):
            self.assertIsNotNone(openurl.validate_url(bad), bad)

    def test_userinfo_is_refused(self):
        self.assertIn("userinfo", openurl.validate_url(
            "https://user:pw@www.nexusmods.com/stardewvalley/mods/1"))

    def test_whitespace_and_control_characters_are_refused(self):
        """A newline or quote would change which URI the client receives."""
        for bad in ("https://www.nexusmods.com/a b",
                    "https://www.nexusmods.com/a\nb",
                    "https://www.nexusmods.com/a\rb",
                    "https://www.nexusmods.com/a\x00b",
                    "https://www.nexusmods.com/a\x7fb"):
            self.assertIsNotNone(openurl.validate_url(bad), repr(bad))

    def test_overlong_url_is_refused(self):
        self.assertIn("longer", openurl.validate_url(
            "https://www.nexusmods.com/" + "a" * openurl.MAX_URL_LEN))

    def test_relative_url_is_refused(self):
        self.assertIn("absolute", openurl.validate_url("/mods/1"))

    def test_empty_is_refused(self):
        self.assertIsNotNone(openurl.validate_url(""))


class TestCommandShape(unittest.TestCase):
    def test_argv_is_a_list_not_a_shell_string(self):
        """No shell means no quoting bug can exist."""
        argv = openurl.command_for(GOOD)
        self.assertIsInstance(argv, list)
        self.assertEqual(argv[0], openurl.STEAM_BIN)
        self.assertEqual(argv[1], "steam://openurl/" + GOOD)

    def test_no_shell_true_anywhere_in_the_module(self):
        import io
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "deckymod", "openurl.py")
        with io.open(path, encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("shell=True", src)


class TestOpenUrl(unittest.TestCase):
    def setUp(self):
        self.rec = _Recorder()
        openurl.set_runner(self.rec)
        # STEAM_BIN is a POSIX device path; on the Windows dev box it does not
        # exist, and the module (correctly) refuses to launch a missing binary.
        # Point it at something real so these tests exercise the runner path,
        # not the host's filesystem layout.
        self._real_bin = openurl.STEAM_BIN
        openurl.STEAM_BIN = sys.executable

    def tearDown(self):
        openurl.set_runner(None)
        openurl.STEAM_BIN = self._real_bin

    def test_success_reports_ok_and_the_runner_saw_the_argv(self):
        got = openurl.open_url(GOOD)
        self.assertTrue(got["ok"], got)
        self.assertEqual(self.rec.argv, [openurl.STEAM_BIN, "steam://openurl/" + GOOD])

    def test_a_refused_url_never_reaches_the_runner(self):
        got = openurl.open_url("https://example.com/x")
        self.assertFalse(got["ok"])
        self.assertEqual(got["reason"], "url_refused")
        self.assertEqual(self.rec.calls, 0, "must not launch anything for a bad URL")

    def test_nonzero_exit_is_reported_not_hidden(self):
        openurl.set_runner(_Recorder(code=3, stderr="boom"))
        got = openurl.open_url(GOOD)
        self.assertFalse(got["ok"])
        self.assertEqual(got["reason"], "steam_failed")
        self.assertIn("3", got["detail"])

    def test_missing_steam_binary_is_a_reason_not_a_crash(self):
        real = openurl.STEAM_BIN
        openurl.STEAM_BIN = "/nonexistent/steam"
        try:
            got = openurl.open_url(GOOD)
        finally:
            openurl.STEAM_BIN = real
        self.assertFalse(got["ok"])
        self.assertEqual(got["reason"], "steam_missing")
        self.assertEqual(self.rec.calls, 0)

    def test_default_runner_converts_a_spawn_error_into_data(self):
        """A missing binary must be a dict, never an exception in the RPC path."""
        got = openurl.default_runner(["/nonexistent/binary", "x"])
        self.assertEqual(got["code"], -1)
        self.assertIn("Error", got["stderr"])


if __name__ == "__main__":
    unittest.main()
