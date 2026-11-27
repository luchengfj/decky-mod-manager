/**
 * theme.ts — the one place the panel's sizes are written down.
 *
 * Why this file exists (Round 83)
 * -------------------------------
 * Before this, every size in the frontend was a raw pixel literal spelled out
 * at the point of use: `fontSize: "11px"` appeared 26 times across nine files,
 * `gap: "8px"` a dozen more. Two consequences, both real:
 *
 *  1. There was no single knob. Changing the caption size meant finding 26
 *     copies and hoping none was missed; the ones that were missed are exactly
 *     the kind of thing that makes a panel look uneven at one resolution and
 *     fine at another.
 *  2. Nothing tied the panel's text to the root font size. A raw `px` font size
 *     ignores the document's base size completely, so if the host ever scales
 *     the UI by setting that base, our text stays put while everything around
 *     it grows.
 *
 * `rem` is not magic. `1rem` is the root font size, and with no override that
 * is 16px — so `rem(11)` and `"11px"` render identically today. That equality
 * is the property this refactor is allowed to claim, and `tests/test_style_units.py`
 * proves it by arithmetic for every token. Whether the Deck's QAM ever sets a
 * non-16px root font size is *not* proven here and is not claimed; see
 * docs/PANEL_LAYOUT.md §5.
 *
 * Borders stay in px on purpose: a 2px focus underline is a hairline that should
 * stay one device-independent pixel-ish line, not scale with text.
 */
import type { CSSProperties } from "react";

/** The CSS initial value of the root font size. Every `rem()` call divides by it. */
export const REM_BASE = 16;

/**
 * Convert a design pixel value to rem, keeping it a plain number when possible
 * so the value stays readable in the devtools (`0.6875rem`, not `0.68750001rem`).
 */
export function rem(px: number): string {
  const v = px / REM_BASE;
  // 6 decimal places is far below any renderer's subpixel precision and keeps
  // the string free of float noise (11/16 = 0.6875 exactly, 13/16 = 0.8125).
  return `${parseFloat(v.toFixed(6))}rem`;
}

/**
 * Type scale. Names describe the ROLE, not the number, so a future resize
 * changes one table instead of 90 call sites.
 */
export const FONT = {
  /** The count badge inside a switcher tab. */
  badge: rem(10),
  /** Secondary detail: paths, subtitles, hints under a row. */
  caption: rem(11),
  /** Default body text and switcher tab labels. */
  body: rem(12),
  /** The status block and list-row labels: one step up from body. */
  bodyLg: rem(13),
  /** A confirm sentence the user must actually read before pressing A. */
  lead: rem(14),
  /** An error message headline. */
  strong: rem(15),
  /** A modal title that is not the standard 18px heading. */
  title: rem(17),
  /** Every dialog's title. */
  heading: rem(18),
} as const;

/**
 * Spacing scale. `gap` and `marginTop` were previously picked per call site
 * (2/4/6/8/10/16), which is why no two rows lined up.
 */
export const SPACE = {
  xs: rem(4),
  sm: rem(6),
  md: rem(8),
  lg: rem(10),
  xl: rem(16),
} as const;

/** Fixed box heights. The switcher badge slot must not vary by tab. */
export const HEIGHT = {
  /** One line of `FONT.badge` text, reserved even when the badge is empty. */
  badgeSlot: rem(12),
} as const;

/** Line boxes. Unitless multipliers stay unitless on purpose (they scale with
 *  whatever font size the element ends up with); the badge slot is a fixed box
 *  and so is expressed in rem like every other length. */
export const LINE_HEIGHT = {
  /** One line of `FONT.badge` text, reserved even when the badge is empty. */
  badgeSlot: rem(12),
  /** The status block's paragraphs. */
  body: 1.35,
  /** The switcher's two-line tab label. */
  tab: 1.15,
} as const;

/**
 * Borders stay in px: these are lines, not text, and a focus underline that
 * scales with the font would look heavier the larger the UI gets.
 */
export const BORDER = {
  /** The active-tab underline (the one thing Steam does not draw for us). */
  tabActive: "2px solid #1a9fff",
  tabIdle: "2px solid transparent",
} as const;

/**
 * `box-sizing: content-box` is the CSS default, so a box's declared `width` does
 * not include its padding: the rendered box comes out wider than the number
 * written, and the panel has no horizontal scrollbar to absorb it.
 *
 * Declaring border-box is a guard, not a repair. The one container proven to be
 * mis-sized is the modal body (`padding: SPACE.xl` on a stretched flex child).
 * The ten `width: "100%"` containers are Decky `Focusable`s whose padding comes
 * from Steam's runtime stylesheet rather than from this repo, so whether they
 * were overflowing could not be established offline -- border-box makes the
 * question moot either way. See docs/PANEL_LAYOUT.md §7.
 *
 * A global `*` rule would restyle Steam's own components, which is the class of
 * mistake Round 81 spent its time undoing.
 */
export const BOX_SIZING = "border-box" as const;

/**
 * The panel root. Applied to the single `Focusable autoFocus` that wraps the
 * whole QAM panel.
 */
export const PANEL_ROOT_STYLE: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  boxSizing: BOX_SIZING,
  // A flex column that is allowed to shrink is what lets a long section scroll
  // instead of stretching the panel; without this the children set the height.
  minHeight: 0,
};
