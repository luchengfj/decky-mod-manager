"""Round 81: the layout rules that keep the panel from drifting.

The user's report was "分辨率问题，就是贴图位移" -- elements and their artwork
sliding apart at some resolutions. The investigation found no image assets and no
hard-coded pixel geometry at all; what it found was *styling that overrides the
size Steam computes for its own controls*:

  * ``DialogButton`` was given ``height: "auto"`` and a custom ``padding``. Steam
    draws that button's focus ring and backing plate at the box size it
    calculates internally, so overriding either decouples the visible box from
    the drawn artwork -- which is exactly what "the highlight is off the button"
    looks like.
  * The tab switcher's badge was conditionally rendered, so the three tabs had
    two different heights.
  * ``PanelSectionRow`` -- the QAM panel's own row container -- was used inside
    modals, which are narrower, so those rows laid out against the wrong width.
  * Four of the five dialogs lacked ``maxHeight``/``overflowY``, so a long
    message pushed the buttons past the screen edge where the D-pad cannot
    reach them.
  * The longest paragraph in the panel had no ``wordBreak``, so Chinese text
    with no spaces to wrap at widened its row.

None of that can be asserted by rendering here (the device is the only place a
real layout exists), so these tests pin the *structure*: the overrides must not
come back. Each one is written against the source text, the same way
``test_outdated_dependencies.py`` pins its honesty rule.
"""
import os
import re
import unittest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    # utf-8 explicitly: the panel's own strings are Chinese, and the default
    # Windows codec turns them into mojibake that no assertion can match.
    with open(os.path.join(_HERE, rel), encoding="utf-8") as f:
        return f.read()


def _strip_comments(text):
    """Drop // and /* */ comments so a comment cannot satisfy or trip a rule."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def _style_blocks(text):
    """Every ``style={{ ... }}`` object literal in a file, comments removed."""
    text = _strip_comments(text)
    out = []
    i = 0
    while True:
        start = text.find("style={{", i)
        if start < 0:
            break
        depth = 0
        j = start + len("style={{") - 2
        while j < len(text):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        out.append(text[start:j + 1])
        i = j + 1
    return out


class TestNoDialogButtonSizeOverride(unittest.TestCase):
    """A DialogButton's box must stay the size Steam computed for its artwork."""

    def test_no_dialog_button_forces_its_own_height(self):
        for rel in ("src/index.tsx", "src/components/Modal.tsx",
                    "src/components/ConfirmModal.tsx",
                    "src/components/ErrorView.tsx",
                    "src/components/ModRow.tsx",
                    "src/components/ImportBox.tsx",
                    "src/rollbackFlow.tsx", "src/uninstallFlow.tsx",
                    "src/autoImport.tsx", "src/depsFlow.tsx"):
            text = _read(rel)
            for block in _style_blocks(text):
                # Only blocks that sit on a DialogButton are in scope; a plain
                # div may legitimately size itself.
                self.assertNotIn(
                    'height: "auto"', block,
                    "%s: a style block still forces height auto -- if this is on "
                    "a DialogButton it decouples the box from Steam's artwork: %s"
                    % (rel, block[:120]))

    def test_the_reason_is_recorded_next_to_the_switcher(self):
        text = _read("src/index.tsx")
        self.assertIn("focus ring", text,
                      "the switcher must keep the comment that says why the "
                      "height/padding overrides were removed")


class TestSwitcherTabsAreEqualHeight(unittest.TestCase):
    def test_the_badge_slot_is_always_rendered(self):
        text = _read("src/index.tsx")
        # The badge must occupy its line even when absent, or the three tabs
        # differ in height. Round 83 moved the number into src/theme.ts, so the
        # assertion is on the token pair -- a fixed height AND a matching line
        # box, because one without the other still lets the tab grow.
        self.assertRegex(
            text,
            r"height: HEIGHT\.badgeSlot,\s*lineHeight: LINE_HEIGHT\.badgeSlot",
            "the badge slot must have a fixed height so every tab is the same "
            "height whether or not it carries a count")
        # ...and the token itself must still be one line of the badge font.
        theme = _read("src/theme.ts")
        self.assertIn("badgeSlot: rem(12)", theme)
        self.assertIn("badge: rem(10)", theme)
        self.assertNotRegex(
            text,
            r"\{badge \? \(\s*\n\s*<div",
            "a conditionally rendered badge row makes the tabs unequal again")


class TestModalsDoNotUsePanelContainers(unittest.TestCase):
    """PanelSectionRow carries the QAM panel's width; a modal is narrower."""

    def test_no_modal_body_imports_panel_section_row(self):
        for rel in ("src/components/Modal.tsx", "src/components/ErrorView.tsx"):
            # Comments explain why the container was dropped; only real usage
            # counts, so strip them first.
            text = _strip_comments(_read(rel))
            self.assertNotIn("PanelSectionRow", text,
                             "%s is rendered inside a modal and must not use the "
                             "panel's row container" % rel)

    def test_every_dialog_body_scrolls(self):
        # The four dialogs that used to overflow now share one style object.
        for rel in ("src/components/ConfirmModal.tsx", "src/rollbackFlow.tsx",
                    "src/uninstallFlow.tsx", "src/autoImport.tsx"):
            text = _read(rel)
            self.assertIn("MODAL_BODY_STYLE", text,
                          "%s must use the shared modal body style" % rel)

    def test_the_shared_style_actually_scrolls(self):
        text = _read("src/components/Modal.tsx")
        self.assertIn("MODAL_BODY_STYLE", text)
        self.assertIn("maxHeight", text)
        self.assertIn("overflowY", text)
        # Without minHeight:0 a flex child stretches its parent instead of
        # scrolling, which is the failure this style exists to prevent.
        self.assertIn("minHeight: 0", text)


class TestLongTextWraps(unittest.TestCase):
    def test_the_constraints_paragraph_wraps(self):
        text = _read("src/index.tsx")
        idx = text.find('t("CONSTRAINTS")')
        self.assertGreater(idx, 0)
        # Look at the style that immediately precedes it.
        window = text[max(0, idx - 400):idx]
        self.assertIn("wordBreak", window,
                      "the constraints paragraph is the longest text in the "
                      "panel and has no spaces to wrap at")

    def test_game_row_name_and_subtitle_wrap(self):
        text = _read("src/index.tsx")
        idx = text.find("GAME_ROW_SUB")
        self.assertGreater(idx, 0)
        window = text[max(0, idx - 700):idx]
        self.assertIn("wordBreak", window,
                      "a long game name must wrap rather than widen the row")


class TestDocsMatchTheCode(unittest.TestCase):
    """The layout doc described a panel that no longer exists."""

    def test_panel_layout_doc_describes_three_tabs_not_four(self):
        text = _read("docs/PANEL_LAYOUT.md")
        # The doc keeps Round 30's wrong claim as a quoted history note, so the
        # assertion has to be about the CURRENT sentence, not the word "four".
        self.assertIn("three `DialogButton`", text)
        self.assertNotIn("**The switcher is four", text)

    def test_panel_layout_doc_states_the_real_default_section(self):
        text = _read("docs/PANEL_LAYOUT.md")
        # The code says useState<string>("games"); the doc used to say "mods".
        self.assertIn('defaults to `"games"`', text)


if __name__ == "__main__":
    unittest.main()
