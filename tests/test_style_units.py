"""Round 83: the panel's sizes come from one table, and it is measured in rem.

Why these tests exist
---------------------
Before Round 83 every size in the frontend was a raw pixel literal written at
the point of use: ``fontSize: "11px"`` appeared 26 times across nine files, and
``gap``/``marginTop`` were picked per call site out of {2,4,6,8,10,16}. Two
things followed from that, and only the second one is a real defect:

  1. There was no single knob. A resize meant finding every copy, and the copy
     that was missed is exactly what makes a panel look uneven at one
     resolution and fine at another.
  2. A raw ``px`` font size ignores the document's root font size completely.
     If the host scales the UI by setting that base, our text stays put while
     everything around it grows.

``rem`` is not a cure-all and this file does not pretend it is. ``1rem`` is the
root font size, which with no override is 16px -- so ``rem(11)`` and ``"11px"``
render identically **today**. That equality is the only property claimed, and
``TestRemMatchesThePixelItReplaces`` proves it by simulating the function's
actual body for every token in the table. Whether the Deck's QAM ever sets a
non-16px root font size is not proven here; see docs/PANEL_LAYOUT.md §7.

Borders stay in px deliberately: a 2px focus underline is a line, not text, and
scaling it with the font would make the highlight heavier as the UI grows.

A note on what a source-text test can and cannot catch
-----------------------------------------------------
These assertions read the source, because there is no renderer here. Round 83's
first draft of this file was audited and found to be weaker than it looked: it
could catch "a px literal came back" and "a token's number changed", but NOT
"the wrong token was used" (``FONT.caption`` -> ``FONT.body``), "a new ``height``
or ``paddingTop`` px appeared", or "``boxSizing`` was set to the wrong value".
Those holes are closed below, and each rule names the mutation it is meant to
catch so the next person can re-prove it.
"""
import os
import re
import unittest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Every file that draws part of the panel or a dialog.
UI_FILES = (
    "src/index.tsx",
    "src/theme.ts",
    "src/components/Modal.tsx",
    "src/components/ConfirmModal.tsx",
    "src/components/ErrorView.tsx",
    "src/components/ModRow.tsx",
    "src/components/ImportBox.tsx",
    "src/rollbackFlow.tsx",
    "src/uninstallFlow.tsx",
    "src/autoImport.tsx",
)

#: Files that render React elements (theme.ts is plain data, no JSX).
JSX_FILES = tuple(f for f in UI_FILES if f != "src/theme.ts")

#: Every CSS length property this panel is allowed to size. A property NOT in
#: this list is not checked, so adding one here is how a new rule gets teeth.
LENGTH_PROPS = (
    "fontSize", "lineHeight", "gap",
    "padding", "paddingTop", "paddingBottom", "paddingLeft", "paddingRight",
    "margin", "marginTop", "marginBottom", "marginLeft", "marginRight",
    "height", "minHeight", "maxHeight", "width", "minWidth", "maxWidth",
)


def _read(rel):
    # utf-8 explicitly: the panel's own strings are Chinese, and the default
    # Windows codec turns them into mojibake that no assertion can match.
    with open(os.path.join(_HERE, rel), encoding="utf-8") as f:
        return f.read()


def _strip_comments(text):
    """Drop // and /* */ comments so a comment cannot satisfy or trip a rule."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def _rem_calls(text):
    """Every literal ``rem(<number>)`` argument in a file, as floats."""
    return [float(m) for m in re.findall(r"rem\(\s*([0-9.]+)\s*\)", _strip_comments(text))]


def _block(theme, name):
    """The body of one ``export const NAME = { ... } as const;`` table."""
    marker = "export const %s" % name
    assert marker in theme, "theme.ts has no %s table" % name
    return theme.split(marker, 1)[1].split("}", 1)[0]


def _simulate_rem(px, base):
    """Re-implement ``rem()`` the way theme.ts writes it, to check the real body.

    theme.ts does:
        const v = px / REM_BASE;
        return `${parseFloat(v.toFixed(6))}rem`;
    so the rendered number is the float with 6dp applied, then parsed back.
    This is the arithmetic the browser performs, not a restatement of the input.
    """
    v = px / base
    return float(repr(round(v, 6)))


class TestNoRawPixelSizesRemain(unittest.TestCase):
    """A px literal outside a border is a size that skipped the theme table."""

    def test_no_px_font_size_survives_anywhere(self):
        # Catches: `fontSize: FONT.caption` reverted to `fontSize: "11px"`.
        for rel in UI_FILES:
            text = _strip_comments(_read(rel))
            hits = re.findall(r'fontSize:\s*"[0-9.]+px"', text)
            self.assertEqual(
                hits, [],
                "%s still hard-codes a pixel font size: %s -- every font size "
                "must come from FONT in src/theme.ts, or it will not follow the "
                "root font size" % (rel, hits))

    def test_no_px_font_size_written_as_a_bare_number(self):
        # `fontSize: 11` is the same defect as `fontSize: "11px"` -- React
        # appends px to a unitless number -- and it is easy to write by accident.
        for rel in UI_FILES:
            text = _strip_comments(_read(rel))
            hits = re.findall(r"fontSize:\s*[0-9]+(?=[,\s}])", text)
            self.assertEqual(
                hits, [],
                "%s passes a unitless number to fontSize (%s); use a FONT "
                "token instead" % (rel, hits))

    def test_no_px_length_on_any_sizing_property(self):
        """Covers every property in LENGTH_PROPS, including the longhands.

        Catches: a new `height: "20px"`, `paddingTop: "4px"`, `margin: "8px"`,
        `minHeight: "40px"` or `lineHeight: "18px"` slipping in beside the
        converted ones. The first draft only looked at `padding`/`margin`/`gap`,
        so a `paddingTop` px was invisible to it.
        """
        prop_alt = "|".join(LENGTH_PROPS)
        pattern = re.compile(r'\b(?:%s):\s*"[0-9.]+px"' % prop_alt)
        for rel in UI_FILES:
            hits = pattern.findall(_strip_comments(_read(rel)))
            self.assertEqual(
                hits, [],
                "%s still hard-codes a px length on %s -- use FONT/SPACE/HEIGHT/"
                "LINE_HEIGHT from src/theme.ts" % (rel, hits))

    def test_the_only_px_left_is_the_border(self):
        # Guards the rules above from being satisfied by deleting the border
        # instead of converting the sizes: exactly one style draws a line.
        theme = _strip_comments(_read("src/theme.ts"))
        self.assertIn('tabActive: "2px solid #1a9fff"', theme)
        self.assertIn('tabIdle: "2px solid transparent"', theme)
        # And the border must still be the ONLY px anywhere in the panel.
        for rel in JSX_FILES:
            for i, line in enumerate(_read(rel).splitlines(), 1):
                for m in re.finditer(r"[0-9.]+px", line):
                    self.assertIn(
                        "solid", line,
                        "%s:%d has a px value that is not a border: %s"
                        % (rel, i, line.strip()[:90]))


class TestRemMatchesThePixelItReplaces(unittest.TestCase):
    """The refactor is only allowed to be invisible if 1rem is still 16px."""

    def test_rem_base_is_the_css_initial_value(self):
        theme = _read("src/theme.ts")
        self.assertIn("export const REM_BASE = 16;", theme,
                      "REM_BASE must stay 16: it is the CSS initial value of the "
                      "root font size, and every equality below is against it")

    def test_rem_divides_by_the_base(self):
        theme = _strip_comments(_read("src/theme.ts"))
        self.assertRegex(theme, r"const v = px / REM_BASE;",
                         "rem() must divide by REM_BASE, not a hard-coded 16")

    def test_the_function_body_actually_renders_pixels(self):
        """Executes the arithmetic theme.ts writes, for the values it uses.

        The first draft of this file "checked" rem() by taking each number from
        the table and multiplying it back by 16 -- which is true of any input and
        never touches the implementation. Rewriting ``rem`` to return
        ``(v * 2) + "rem"``, or a plain ``"px"`` string, left it green. This one
        reads the implementation's own rounding rule and applies it.
        """
        theme = _strip_comments(_read("src/theme.ts"))
        self.assertIn("parseFloat(v.toFixed(6))", theme,
                      "rem() must round to 6dp before rendering; without it the "
                      "string carries float noise and this test is not checking "
                      "what the browser will parse")
        self.assertIn('return `${parseFloat(v.toFixed(6))}rem`;', theme)
        for n in _rem_calls(theme):
            rendered = _simulate_rem(n, 16)
            self.assertAlmostEqual(
                rendered * 16, n, places=4,
                msg="rem(%g) renders as %gpx, not %gpx" % (n, rendered * 16, n))

    def test_every_token_reproduces_the_number_it_replaced(self):
        """The table below is the pre-refactor px value for each token.

        If a token's number changes, this test fails -- which is the point: a
        size change should be a deliberate edit here, not a silent drift.
        """
        expected = {
            # font scale
            "badge": 10,
            "caption": 11,
            "body": 12,
            "bodyLg": 13,
            "lead": 14,
            "strong": 15,
            "title": 17,
            "heading": 18,
            # spacing scale
            "xs": 4,
            "sm": 6,
            "md": 8,
            "lg": 10,
            "xl": 16,
        }
        theme = _strip_comments(_read("src/theme.ts"))
        for name, px in expected.items():
            with self.subTest(token=name):
                self.assertRegex(
                    theme,
                    r"\b%s:\s*rem\(%d\)" % (re.escape(name), px),
                    "token %r must still be rem(%d) -- that is the pixel value "
                    "it replaced, so the refactor stays invisible at 16px root"
                    % (name, px))

    def test_both_badge_slot_tokens_are_pinned_in_their_own_block(self):
        """HEIGHT and LINE_HEIGHT both define `badgeSlot`; anchor each one.

        The first draft's regex was unanchored, so either block satisfied it and
        the other could drift to any value unnoticed. The two must also agree:
        a fixed height with a different line box still lets the tab grow.
        """
        theme = _strip_comments(_read("src/theme.ts"))
        self.assertRegex(_block(theme, "HEIGHT"), r"badgeSlot:\s*rem\(12\)",
                         "HEIGHT.badgeSlot must be rem(12) -- one line of the "
                         "badge font, reserved whether or not a count exists")
        self.assertRegex(_block(theme, "LINE_HEIGHT"), r"badgeSlot:\s*rem\(12\)",
                         "LINE_HEIGHT.badgeSlot must match HEIGHT.badgeSlot; a "
                         "mismatch lets the tab grow again")

    def test_the_scale_has_no_duplicate_values(self):
        """Two tokens for one number means one of them is redundant.

        Scoped per block: FONT and SPACE are separate scales, so a font size of
        10 and a gap of 10 sharing a number is not a collision -- they answer
        different questions.
        """
        theme = _strip_comments(_read("src/theme.ts"))
        for block_name in ("FONT", "SPACE"):
            seen = {}
            for m in re.finditer(r"\b([a-zA-Z]+):\s*rem\(([0-9.]+)\)",
                                 _block(theme, block_name)):
                seen.setdefault(float(m.group(2)), []).append(m.group(1))
            dupes = {v: names for v, names in seen.items() if len(names) > 1}
            self.assertEqual(dupes, {},
                             "%s gives the same rem value two names: %r -- keep one"
                             % (block_name, dupes))


def _uses_token(text, table, name):
    """True when `table.name` is referenced as a whole identifier.

    A plain substring test is wrong here: `FONT.body` is a prefix of
    `FONT.bodyLg`, so a file that only ever renders `FONT.bodyLg` would still
    satisfy an "is FONT.body used?" check -- and FONT.body could then go stale
    unnoticed. The trailing \\b is what makes `body` not match `bodyLg`.
    """
    return re.search(r"\b%s\.%s\b" % (table, re.escape(name)), text) is not None


class TestConsumersUseTheTable(unittest.TestCase):
    """A token nothing imports is a table that drifted away from the code."""

    def test_every_jsx_file_imports_the_tokens_it_names(self):
        """Checks the NAMES, not just that some theme import exists.

        The first draft only asked "is there a theme import?", so deleting
        ``BOX_SIZING`` from an import list while still using it passed. This
        compares the set of tokens the file names against the set it imports.
        """
        token_re = re.compile(r"\b(FONT|SPACE|HEIGHT|LINE_HEIGHT|BORDER|"
                              r"PANEL_ROOT_STYLE|BOX_SIZING)\b")
        for rel in JSX_FILES:
            text = _strip_comments(_read(rel))
            used = set(token_re.findall(text))
            if not used:
                continue
            m = re.search(r'import \{([^}]*)\}\s*from\s*"[./]*\.?/?theme";', text)
            self.assertIsNotNone(m, "%s names theme tokens but has no theme import" % rel)
            imported = {p.strip() for p in m.group(1).split(",") if p.strip()}
            missing = used - imported
            self.assertEqual(
                missing, set(),
                "%s uses %s but does not import them from theme"
                % (rel, sorted(missing)))
            unused = imported - used
            self.assertEqual(
                unused, set(),
                "%s imports %s but never names them -- dead import"
                % (rel, sorted(unused)))

    def test_every_font_token_is_used_somewhere(self):
        """Substring match is safe here because the token list has no prefix
        collisions after ``body``/``bodyLg`` are both in the table."""
        theme = _strip_comments(_read("src/theme.ts"))
        names = re.findall(r"([a-zA-Z]+):\s*rem\(", _block(theme, "FONT"))
        self.assertGreater(len(names), 6)
        consumers = "\n".join(_strip_comments(_read(f)) for f in JSX_FILES)
        unused = [n for n in names if not _uses_token(consumers, "FONT", n)]
        self.assertEqual(unused, [],
                         "FONT tokens nothing renders: %r -- an unused token is "
                         "a number that will silently go stale" % unused)

    def test_every_space_token_is_used_somewhere(self):
        theme = _strip_comments(_read("src/theme.ts"))
        names = re.findall(r"([a-zA-Z]+):\s*rem\(", _block(theme, "SPACE"))
        self.assertGreater(len(names), 4)
        consumers = "\n".join(_strip_comments(_read(f)) for f in JSX_FILES)
        unused = [n for n in names if not _uses_token(consumers, "SPACE", n)]
        self.assertEqual(unused, [],
                         "SPACE tokens nothing renders: %r" % unused)

    def test_the_role_bound_sizes_use_the_role_bound_token(self):
        """Pins a few call sites where picking the neighbouring token would be a
        visible regression.

        Catches: ``FONT.caption`` -> ``FONT.body`` at the status block's detail
        lines, or ``FONT.heading`` -> ``FONT.title`` in a dialog title. A swap
        like that passes every other test in this file, because the value is
        still a token -- it is just the wrong one.
        """
        index = _strip_comments(_read("src/index.tsx"))
        modal = _strip_comments(_read("src/components/Modal.tsx"))

        # The switcher's tab label is body, its badge is badge.
        self.assertIn("fontSize: FONT.body,", index)
        self.assertIn("fontSize: FONT.badge,", index)
        # The status block's headline is one step above body.
        self.assertIn("fontSize: FONT.bodyLg, lineHeight: LINE_HEIGHT.body", index)
        # Every dialog title is the heading size, never the title size.
        for rel in ("src/components/Modal.tsx", "src/components/ConfirmModal.tsx",
                    "src/rollbackFlow.tsx", "src/uninstallFlow.tsx"):
            text = _strip_comments(_read(rel))
            self.assertIn("fontWeight: 700, fontSize: FONT.heading", text,
                          "%s must title its dialog with FONT.heading" % rel)
        # The confirm sentence the user must read before pressing A.
        for rel in ("src/components/ConfirmModal.tsx", "src/rollbackFlow.tsx",
                    "src/uninstallFlow.tsx"):
            text = _strip_comments(_read(rel))
            self.assertIn("fontSize: FONT.lead", text,
                          "%s must render its confirm sentence at FONT.lead" % rel)
        # The modal body gap/padding pair.
        self.assertIn("gap: SPACE.lg,", modal)
        self.assertIn("padding: SPACE.xl,", modal)

    def test_the_token_usage_census_matches(self):
        """Every (file, token) pair must still be used exactly as many times.

        This is the assertion that actually closes the "wrong token" hole the
        auditor demonstrated: swapping one ``FONT.caption`` for ``FONT.body``
        keeps every value a token and changes no token's number, so every other
        rule here stays green -- but it moves the census, and this test names
        both the pair and the delta.

        The census is a *snapshot*, not a target: adding a new row legitimately
        changes it. When that happens, update the number here deliberately, in
        the same commit as the row that changed it.
        """
        census = {
            "src/index.tsx": {
                "BORDER.tabActive": 1, "BORDER.tabIdle": 1,
                "FONT.badge": 1, "FONT.body": 7, "FONT.bodyLg": 2,
                "FONT.caption": 27,
                "HEIGHT.badgeSlot": 1,
                "LINE_HEIGHT.badgeSlot": 1, "LINE_HEIGHT.body": 5,
                "LINE_HEIGHT.tab": 1,
                "SPACE.lg": 2, "SPACE.md": 4, "SPACE.sm": 2, "SPACE.xs": 2,
            },
            "src/components/Modal.tsx": {
                "FONT.body": 3, "FONT.bodyLg": 3, "FONT.caption": 1,
                "FONT.heading": 3,
                "SPACE.lg": 1, "SPACE.md": 3, "SPACE.sm": 3, "SPACE.xl": 1,
            },
            "src/components/ConfirmModal.tsx": {
                "FONT.body": 1, "FONT.heading": 1, "FONT.lead": 1,
                "SPACE.lg": 1, "SPACE.md": 1,
            },
            "src/components/ErrorView.tsx": {
                "FONT.body": 1, "FONT.caption": 1, "FONT.strong": 1,
                "SPACE.md": 2,
            },
            "src/components/ModRow.tsx": {
                "FONT.caption": 1, "FONT.lead": 1, "SPACE.md": 2,
            },
            "src/components/ImportBox.tsx": {
                "FONT.body": 1, "SPACE.md": 2,
            },
            "src/rollbackFlow.tsx": {
                "FONT.body": 1, "FONT.heading": 1, "FONT.lead": 1,
                "SPACE.lg": 1, "SPACE.md": 1,
            },
            "src/uninstallFlow.tsx": {
                "FONT.body": 1, "FONT.heading": 1, "FONT.lead": 1,
                "SPACE.lg": 1, "SPACE.md": 1,
            },
            "src/autoImport.tsx": {
                "FONT.bodyLg": 1, "FONT.title": 1, "SPACE.sm": 1,
            },
        }
        token_re = re.compile(r"\b(FONT|SPACE|HEIGHT|LINE_HEIGHT|BORDER)\.([A-Za-z]+)\b")
        for rel in JSX_FILES:
            text = _strip_comments(_read(rel))
            actual = {}
            for m in token_re.finditer(text):
                key = "%s.%s" % (m.group(1), m.group(2))
                actual[key] = actual.get(key, 0) + 1
            expected = census.get(rel, {})
            self.assertEqual(
                actual, expected,
                "%s token census changed.\n  missing: %r\n  extra:   %r\n"
                "A difference here means a call site switched to a different "
                "token (a wrong-token swap looks exactly like this), a row was "
                "added, or one was deleted. If the change is intended, update "
                "the census in this test in the same commit."
                % (rel,
                   {k: v for k, v in expected.items() if actual.get(k) != v},
                   {k: v for k, v in actual.items() if expected.get(k) != v}))


class TestFullWidthBoxesAreBorderBox(unittest.TestCase):
    """`width: "100%"` plus padding, under content-box, is wider than the parent.

    A QAM panel does not scroll horizontally, so what that actually does is push
    content past the right edge where the D-pad cannot reach it. This is the
    mechanical half of the "elements drift off the panel" report.
    """

    def test_every_hundred_percent_width_declares_border_box(self):
        for rel in JSX_FILES:
            for i, line in enumerate(_read(rel).splitlines(), 1):
                if 'width: "100%"' not in line:
                    continue
                self.assertIn(
                    "boxSizing", line,
                    "%s:%d sets width 100%% without boxSizing -- its padding and "
                    "border will add to that 100%%: %s" % (rel, i, line.strip()[:90]))

    def test_the_declared_value_is_border_box_not_merely_present(self):
        """Catches ``boxSizing: "content-box"`` and ``boxSizing: undefined``.

        The first draft asserted the substring "boxSizing" was on the line, which
        any of those satisfy while doing nothing.
        """
        for rel in JSX_FILES:
            for i, line in enumerate(_read(rel).splitlines(), 1):
                if "boxSizing" not in line:
                    continue
                self.assertIn(
                    "boxSizing: BOX_SIZING", line,
                    "%s:%d must set boxSizing to the BOX_SIZING token, not to "
                    "some other value: %s" % (rel, i, line.strip()[:90]))

    def test_the_panel_root_uses_the_shared_style(self):
        text = _strip_comments(_read("src/index.tsx"))
        self.assertIn("style={PANEL_ROOT_STYLE}", text,
                      "the panel root must use PANEL_ROOT_STYLE so the border-box "
                      "declaration has exactly one home")
        theme = _strip_comments(_read("src/theme.ts"))
        self.assertRegex(
            theme, r"PANEL_ROOT_STYLE: CSSProperties = \{[^}]*boxSizing: BOX_SIZING",
            "PANEL_ROOT_STYLE must itself declare border-box")
        self.assertIn('export const BOX_SIZING = "border-box" as const;', theme)

    def test_the_modal_body_is_border_box(self):
        # The modal body carries `padding: SPACE.xl` and is the direct child of
        # the modal frame, so it is the one container where the difference shows.
        modal = _strip_comments(_read("src/components/Modal.tsx"))
        self.assertIn("boxSizing: BOX_SIZING", modal,
                      "MODAL_BODY_STYLE must declare border-box; it carries "
                      "padding inside a frame that already gives it a width")

    def test_no_global_star_rule_was_added(self):
        """A `* { box-sizing }` rule would restyle Steam's own components."""
        for rel in JSX_FILES + ("src/theme.ts",):
            text = _strip_comments(_read(rel))
            self.assertNotIn("* {", text,
                             "%s adds a global CSS rule; this plugin styles only "
                             "its own elements" % rel)
            self.assertNotIn("insertRule", text)


class TestNoDeadThemeExports(unittest.TestCase):
    """An exported style nothing imports is a second source of truth waiting."""

    def test_every_exported_style_is_used(self):
        theme = _strip_comments(_read("src/theme.ts"))
        # Only the `: CSSProperties` exports are style objects; BOX_SIZING and
        # REM_BASE are values, and the token tables are checked separately.
        exported = re.findall(r"export const ([A-Z_]+):\s*CSSProperties", theme)
        self.assertIn("PANEL_ROOT_STYLE", exported)
        consumers = "\n".join(_strip_comments(_read(f)) for f in JSX_FILES)
        dead = [n for n in exported if n not in consumers]
        self.assertEqual(dead, [],
                         "theme.ts exports %r but no component uses it -- delete "
                         "it or use it, do not leave a second place to edit"
                         % dead)


class TestLineEndingsStayNormalised(unittest.TestCase):
    """The refactor is unreviewable if every line shows as changed.

    Round 83 was nearly lost this way: an editor wrote CRLF into 18 files, and
    `git diff` reported 9017 added / 8582 deleted around 767 real lines. Nothing
    in the test suite noticed, because line endings do not change program
    behaviour -- only the ability to review the change.
    """

    def test_gitattributes_pins_lf(self):
        path = os.path.join(_HERE, ".gitattributes")
        self.assertTrue(os.path.isfile(path),
                        ".gitattributes is missing -- without it an editor that "
                        "writes CRLF turns every future diff into line noise")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("* text=auto eol=lf", text,
                      ".gitattributes must normalise the tree to LF")

    def test_no_ui_file_is_stored_with_crlf(self):
        # HEAD is LF for every one of these; a CRLF worktree copy means the file
        # was rewritten by something other than a deliberate edit.
        for rel in UI_FILES + ("tests/test_style_units.py",):
            path = os.path.join(_HERE, rel)
            with open(path, "rb") as f:
                data = f.read()
            self.assertNotIn(
                b"\r\n", data,
                "%s has CRLF line endings but is stored as LF -- run "
                "`.decky-probe/r83_eol.py` (or `git add --renormalize .`) before "
                "committing, or the diff becomes unreadable" % rel)


if __name__ == "__main__":
    unittest.main()
