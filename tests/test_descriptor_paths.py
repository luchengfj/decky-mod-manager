"""Round 43 / P1#5: descriptor path templates are real configuration.

Before this round every game resolved to ``<game_root>/Mods`` and the four
sibling folders were hard-coded in ``paths.resolve()``. A descriptor's
``paths`` block was documentation that happened to agree with the code. These
tests pin the helper contract directly, so a typo in a placeholder or a
misplaced ``${TXN_ID}`` fails before it can create a directory nobody reads.
"""
import os
import unittest

from deckymod import paths
from deckymod.errors import ModError


class TestDescriptorPathTemplates(unittest.TestCase):
    def setUp(self):
        self.game = os.path.join(os.sep, "home", "deck", ".steam", "steamapps", "common", "Factorio")
        self.home = os.path.join(os.sep, "home", "deck")
        self.xdg = os.path.join(self.home, ".config")

    def test_relative_value_is_anchored_at_game_root(self):
        self.assertEqual(
            paths._expand_layout("Mods", self.game, self.home, self.xdg),
            os.path.join(self.game, "Mods"),
        )

    def test_game_root_placeholder_matches_relative_value(self):
        self.assertEqual(
            paths._expand_layout("${GAME_ROOT}/Mods", self.game, self.home, self.xdg),
            os.path.join(self.game, "Mods"),
        )

    def test_home_and_xdg_placeholders_expand(self):
        self.assertEqual(
            paths._expand_layout("${HOME}/.factorio/mods", self.game, self.home, self.xdg),
            os.path.join(self.home, ".factorio", "mods"),
        )
        self.assertEqual(
            paths._expand_layout("${XDG_CONFIG}/MyGame/mods", self.game, self.home, self.xdg),
            os.path.join(self.xdg, "MyGame", "mods"),
        )

    def test_unknown_placeholder_is_an_error_not_an_empty_path(self):
        with self.assertRaises(ModError) as ctx:
            paths._expand_layout("${GME_ROOT}/Mods", self.game, self.home, self.xdg)
        self.assertEqual(ctx.exception.code, "E_PATH_INVALID")

    def test_missing_or_empty_block_uses_historical_names(self):
        for layout in (None, {}):
            with self.subTest(layout=layout):
                self.assertEqual(
                    paths._layout_value(layout, "mod_root", self.game, self.home, self.xdg),
                    os.path.join(self.game, "Mods"),
                )
                self.assertEqual(
                    paths._layout_value(layout, "staging", self.game, self.home, self.xdg),
                    os.path.join(self.game, ".decky-staging"),
                )
                self.assertEqual(
                    paths._layout_value(layout, "quarantine", self.game, self.home, self.xdg),
                    os.path.join(self.game, ".decky-quarantine"),
                )
                self.assertEqual(
                    paths._layout_value(layout, "disabled", self.game, self.home, self.xdg),
                    os.path.join(self.game, ".decky-disabled"),
                )

    def test_quarantine_transaction_suffix_is_dropped(self):
        layout = {"quarantine": "${GAME_ROOT}/.decky-quarantine/${TXN_ID}"}
        self.assertEqual(
            paths._layout_value(layout, "quarantine", self.game, self.home, self.xdg),
            os.path.join(self.game, ".decky-quarantine"),
        )

    def test_misplaced_transaction_suffix_is_an_error(self):
        for value in ("${TXN_ID}/.decky-quarantine", "${GAME_ROOT}/${TXN_ID}/Mods"):
            with self.subTest(value=value), self.assertRaises(ModError) as ctx:
                paths._layout_value({"quarantine": value}, "quarantine", self.game, self.home, self.xdg)
            self.assertEqual(ctx.exception.code, "E_PATH_INVALID")

    def test_descriptor_can_move_mod_root_outside_game_root(self):
        layout = {
            "mod_root": "${HOME}/.factorio/mods",
            "staging": "${HOME}/.factorio/.decky-staging",
            "quarantine": "${HOME}/.factorio/.decky-quarantine/${TXN_ID}",
            "disabled": "${HOME}/.factorio/.decky-disabled",
        }
        self.assertEqual(
            paths._layout_value(layout, "mod_root", self.game, self.home, self.xdg),
            os.path.join(self.home, ".factorio", "mods"),
        )
        self.assertEqual(
            paths._layout_value(layout, "quarantine", self.game, self.home, self.xdg),
            os.path.join(self.home, ".factorio", ".decky-quarantine"),
        )


if __name__ == "__main__":
    unittest.main()
