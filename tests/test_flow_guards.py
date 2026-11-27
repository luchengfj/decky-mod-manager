"""Round 84: the three "silent write" guards in the self-contained flows.

Why these tests exist
---------------------
Three of the panel's flows could each reach a write (or a failure) without ever
telling the user:

  * ``src/rollbackFlow.tsx`` fired ``rollbackTxn()`` while the panel stayed
    un-busy, so the 32 buttons that the panel disables during every other write
    stayed live during a restore.
  * ``src/depsFlow.tsx`` installed every fetchable dependency straight from the
    "check dependencies" button, on the theory that "the button already is
    consent" -- but that button's label promises a check, not a write into
    Mods/.
  * ``src/autoImport.tsx`` swallowed a thrown scan whole (``.catch(() => ...)``),
    so a broken background import looked exactly like "nothing new to import".

There is no JS runtime in this harness (and the device is the only place a real
modal exists), so each guard is pinned against the source text, the same way
``test_panel_layout_rules.py`` and ``test_style_units.py`` pin their rules.

Each test names the mutation it is meant to catch, so the next person can
re-prove it. Comments are stripped first: a sentence that merely *describes*
the guard must not be able to satisfy it.
"""
import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _read(rel):
    # utf-8 explicitly: these files carry Chinese strings and em dashes, and the
    # default Windows codec turns them into mojibake.
    return (_ROOT / rel).read_text(encoding="utf-8")


def _strip_comments(text):
    """Drop // and /* */ comments so prose cannot satisfy a rule."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def _block_after(text, anchor):
    """The brace-matched ``{...}`` block that follows ``anchor``.

    ``anchor`` is a literal prefix (e.g. ``"if (fetchable >= total)"``); the
    returned text starts at its opening brace and ends at the matching close.
    Brace counting is naive but sufficient here: the regions scanned contain
    only balanced ``{n}`` placeholders inside strings, and comments are already
    gone by the time this runs.
    """
    start = text.index(anchor) + len(anchor)
    open_at = text.index("{", start)
    depth = 0
    for i in range(open_at, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_at:i + 1]
    raise AssertionError("unbalanced braces after %r" % anchor)


class TestRollbackRaisesBusy(unittest.TestCase):
    """A restore must disable the panel the way every other write does."""

    def setUp(self):
        self.src = _strip_comments(_read("src/rollbackFlow.tsx"))

    def test_set_busy_is_declared_called_and_cleared(self):
        """Catches: the parameter dropped, or the raise/clear call removed.

        Three occurrences are the floor -- the optional parameter declaration,
        the ``setBusy?.(true)`` on the confirm path, and at least one clear. A
        version that only *mentions* busy in a comment cannot pass, because
        comments are stripped.
        """
        self.assertGreaterEqual(
            self.src.count("setBusy"), 3,
            "src/rollbackFlow.tsx no longer declares, raises and clears setBusy "
            "(found %d occurrences)" % self.src.count("setBusy"))

    def test_busy_is_raised_only_on_the_confirm_path_before_the_rpc(self):
        """Catches: setBusy(true) moved to the cancel path, or after the RPC."""
        self.assertIn("setBusy?: (v: boolean) => void", self.src,
                      "the fifth parameter must stay optional and typed")
        raised = self.src.find("setBusy?.(true)")
        called = self.src.find("rollbackTxn(txn)")
        self.assertGreater(raised, 0, "the confirm path never raises busy")
        self.assertGreater(called, 0, "rollbackTxn(txn) is gone")
        self.assertLess(raised, called,
                        "setBusy?.(true) must run BEFORE rollbackTxn(txn), or the "
                        "panel is un-busy while the restore is in flight")
        # The cancel handler sits after the confirm button and must not touch
        # busy: cancelling performs no write.
        cancel_at = self.src.find("BTN_CANCEL")
        self.assertGreater(cancel_at, 0)
        between = self.src[raised:called]
        self.assertNotIn("setBusy", between.replace("setBusy?.(true)", ""),
                         "busy is toggled more than once before the RPC")

    def test_busy_is_cleared_before_on_done_on_every_path(self):
        """Catches: the clear dropped from the rejection path.

        ``onDone`` opens a fresh modal, so the clear has to happen first -- a
        panel still marked busy would render that modal's buttons disabled.
        The implementation does it with one ``.finally``; an equivalent
        two-branch clear is accepted, which is why the assertion is "the clear
        is downstream of both settle paths and upstream of the reporting call".
        """
        cleared = self.src.find("setBusy?.(false)")
        self.assertGreater(cleared, 0,
                           "nothing ever clears busy -- the panel stays locked "
                           "after a restore")
        finally_at = self.src.find(".finally(")
        self.assertGreater(finally_at, 0,
                           "the clear should be in a .finally so the catch path "
                           "cannot forget it")
        # The clear must be *inside* the .finally body, not merely somewhere
        # after it: a `.finally(() => {})` followed by a clear would run the
        # clear too late for a rejection that already opened a modal.
        self.assertIn("setBusy?.(false)", self.src[finally_at:finally_at + 200],
                      "setBusy?.(false) is not inside the .finally callback")
        # Both settle paths feed the finally, and the reporting call is last.
        catch_at = self.src.find(".catch(")
        self.assertLess(catch_at, finally_at,
                        "the .catch must be upstream of the .finally, or a "
                        "rejection skips the clear")
        reported = self.src.find("onDone(outcome)")
        self.assertGreater(reported, cleared,
                           "onDone runs before busy is cleared -- the modal it "
                           "opens would have its buttons disabled")


class TestDepsAllFetchableAsksFirst(unittest.TestCase):
    """The all-fetchable branch must confirm before it writes into Mods/."""

    def setUp(self):
        self.src = _strip_comments(_read("src/depsFlow.tsx"))
        self.branch = _block_after(self.src, "if (fetchable >= total)")

    def test_the_branch_confirms_with_a_modal_before_installing(self):
        """Catches: the branch reverting to ``await installFetchable(d)``."""
        self.assertIn("showInfo", self.branch,
                      "the all-fetchable branch must open a confirmation modal")
        self.assertIn("DEPS_CONFIRM_TITLE", self.branch,
                      "the confirmation must use the dedicated title key")
        self.assertNotIn("await installFetchable", self.branch,
                         "installFetchable is awaited directly again -- the "
                         "branch writes without a second confirmation")

    def test_install_only_happens_inside_the_confirm_action(self):
        """Catches: installFetchable moved above the action list.

        ``showInfo`` renders its actions as buttons, so the install belongs in
        one action's ``onClick``. Anything before the first ``onClick`` is code
        that runs as soon as the plan is read -- which is the bug.
        """
        head = self.branch.split("onClick:")[0]
        self.assertNotIn("installFetchable", head,
                         "installFetchable runs before the user presses "
                         "confirm")
        self.assertIn("installFetchable", self.branch,
                      "the confirm action never installs")
        self.assertRegex(
            self.branch,
            r"onClick:\s*\(close\)\s*=>\s*\{[^}]*installFetchable",
            "installFetchable must sit inside the confirm action's onClick")

    def test_the_confirmation_key_exists_in_the_flow(self):
        """Catches: the title key renamed/typo'd so the modal shows the key."""
        self.assertGreaterEqual(self.src.count("DEPS_CONFIRM_TITLE"), 1,
                                "src/depsFlow.tsx never references "
                                "DEPS_CONFIRM_TITLE")

    def test_the_mixed_branch_keeps_its_own_list(self):
        """The guard must not have swallowed the fetchable < total path."""
        self.assertIn("showListModal", self.src,
                      "the mixed branch's list disappeared")
        self.assertIn("DEP_INSTALL_ALL", self.src)


class TestAutoImportSilentReportsItsError(unittest.TestCase):
    """A thrown scan must travel back in the result, not vanish."""

    def setUp(self):
        self.src = _strip_comments(_read("src/autoImport.tsx"))

    def test_the_outcome_type_carries_an_error(self):
        """Catches: the optional field dropped from the interface.

        Matched by brace-balancing rather than a regex: the interface already
        contains ``Array<{ name: string; why: string }>``, so ``[^}]*`` would
        stop at that inner brace and miss the field below it.
        """
        body = _block_after(self.src, "export interface AutoImportOutcome")
        self.assertIn("error?: string", body,
                      "AutoImportOutcome must keep the optional error field the "
                      "silent pass fills in")

    def test_the_silent_pass_keeps_the_reason(self):
        """Catches: ``.catch(() => ({...}))`` -- the original bug, verbatim."""
        body = _block_after(self.src, "export function autoImportSilent(): Promise<AutoImportOutcome>")
        catch_at = body.find(".catch(")
        self.assertGreater(catch_at, 0, "the silent pass no longer guards itself")
        tail = body[catch_at:]
        self.assertIn("error:", tail,
                      "autoImportSilent's .catch drops the failure reason again "
                      "-- a broken scan looks like 'nothing new to import'")
        self.assertIn("ok: false", tail,
                      "the failure result must still be marked not-ok")

    def test_the_silent_pass_does_not_open_a_modal(self):
        """Catches: the fix moved the UI into the module.

        A background pass runs on panel mount; raising a modal there would
        stack a dialog on every mount. ``showSummary`` belongs to the manual
        flow only, so the silent function must not reference it.
        """
        body = _block_after(self.src, "export function autoImportSilent(): Promise<AutoImportOutcome>")
        self.assertNotIn("showSummary", body,
                         "autoImportSilent must not open UI; the caller shows it")


if __name__ == "__main__":
    unittest.main()
