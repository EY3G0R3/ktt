import unittest
import re

from ktt.model import TabRecord, TreeRow
from ktt.render import (
    CONTROL_LINES,
    FLAME_RIGHT_CAP,
    LEFT_CAP,
    READY_RIGHT_CAP,
    RIGHT_CAP,
    display_width,
    panel_style,
    render_control_line,
    render_row,
    render_screen,
    status_icon,
    vertical_padding,
)


class RenderTests(unittest.TestCase):
    def test_panel_uses_explicit_black_background(self) -> None:
        self.assertEqual(panel_style(), "\x1b[48;2;0;0;0m\x1b[38;2;248;248;242m")

    def test_statuses_match_existing_workmux_conventions(self) -> None:
        self.assertEqual(status_icon("ready_to_merge"), ("✓", "50fa7b"))
        self.assertEqual(status_icon("blocked"), ("✗", "ff5555"))
        self.assertEqual(status_icon("🤖", now=0.0)[0], "⠋")

    def test_child_row_is_indented(self) -> None:
        tab = TabRecord(2, 1, "child", (20,), status="blocked")
        rendered = render_row(
            TreeRow(tab, depth=2, parent_tab_id=1),
            selected=False,
            width=80,
            ansi=False,
            now=0.0,
        )
        self.assertIn(f"    {LEFT_CAP}", rendered)
        self.assertIn("✗", rendered)
        self.assertIn("child", rendered)

    def test_ready_and_blocked_rows_have_verdict_backgrounds(self) -> None:
        ready = TabRecord(2, 1, "ready", (20,), status="ready_to_merge")
        blocked = TabRecord(3, 1, "blocked", (30,), status="blocked")
        self.assertIn("\x1b[48;2;27;94;54m", render_row(
            TreeRow(ready, 0, None), selected=False, width=80
        ))
        self.assertIn("\x1b[48;2;122;32;41m", render_row(
            TreeRow(blocked, 0, None), selected=False, width=80
        ))

    def test_short_tab_list_is_centered_above_multiline_controls(self) -> None:
        rows = [
            TreeRow(TabRecord(1, 1, "one", (10,)), 0, None),
            TreeRow(TabRecord(2, 1, "two", (20,)), 0, None),
        ]
        screen = render_screen(rows, 0, 1, 80, 10, ansi=False)
        lines = screen.splitlines()
        self.assertEqual(vertical_padding(2, 10), 1)
        self.assertIn("one", lines[1])
        self.assertIn("two", lines[2])
        controls = lines[-len(CONTROL_LINES):]
        self.assertEqual(
            [line.strip() for line in controls],
            [line.strip() for line in CONTROL_LINES],
        )
        self.assertTrue(all(line.startswith(" " * 24) for line in controls))

    def test_screen_has_no_normal_header(self) -> None:
        screen = render_screen([], 0, 17, 40, 8, total_tabs=9, ansi=False)
        self.assertNotIn("Kitty OS window", screen)
        self.assertNotIn("9 tabs", screen)

    def test_control_lines_fit_a_narrow_sidebar(self) -> None:
        width = 32
        screen = render_screen([], 0, 1, width, 8, ansi=False)
        self.assertTrue(all(len(line) <= width for line in screen.splitlines()))
        self.assertEqual(screen.splitlines()[-5:], list(CONTROL_LINES))

    def test_control_legend_visually_separates_shortcuts_and_actions(self) -> None:
        line = render_control_line("Enter · click", "enter tab", 40, ansi=False)
        self.assertEqual(line.strip(), "Enter · click │ enter tab")

    def test_long_tab_list_uses_all_available_rows(self) -> None:
        self.assertEqual(vertical_padding(20, 10), 0)

    def test_active_tab_has_persistent_background(self) -> None:
        active = TabRecord(1, 1, "active", (10,), is_active=True)
        rendered = render_row(
            TreeRow(active, 0, None), selected=False, width=80
        )
        self.assertIn("\x1b[48;2;76;86;106m", rendered)

    def test_folded_active_descendant_uses_dimmer_active_background(self) -> None:
        parent = TabRecord(1, 1, "parent", (10,))
        rendered = render_row(
            TreeRow(parent, 0, None, has_children=True,
                    is_collapsed=True, has_active_descendant=True),
            selected=False,
            width=80,
        )
        self.assertIn("\x1b[48;2;52;59;73m", rendered)

    def test_rows_have_no_active_marker_gutter(self) -> None:
        active = render_row(
            TreeRow(TabRecord(1, 1, "active", (10,), is_active=True), 0, None),
            selected=False, width=30, ansi=False,
        )
        self.assertTrue(active.startswith(LEFT_CAP))
        self.assertNotIn("●", active)
        self.assertNotIn("◉", active)

    def test_inactive_row_has_full_width_inset_background_card(self) -> None:
        parent = render_row(
            TreeRow(TabRecord(1, 1, "parent", (10,)), 0, None),
            selected=False, width=30,
        )
        child = render_row(
            TreeRow(TabRecord(2, 1, "child", (20,)), 2, 1),
            selected=False, width=30,
        )
        background = "\x1b[48;2;32;35;42m"
        self.assertIn(background, parent)
        self.assertIn(background, child)
        self.assertLess(parent.index(background), child.index(background))
        ansi = re.compile(r"\x1b\[[0-9;]*m")
        self.assertEqual(len(ansi.sub("", parent)), 29)
        self.assertEqual(len(ansi.sub("", child)), 29)

    def test_inactive_row_restores_readable_foreground_after_left_cap(self) -> None:
        rendered = render_row(
            TreeRow(TabRecord(1, 1, "visible", (10,)), 0, None),
            selected=False, width=30,
        )
        self.assertIn("\x1b[38;2;216;222;233m", rendered)
        self.assertTrue(rendered.startswith(panel_style()))

    def test_selection_does_not_create_a_second_highlight(self) -> None:
        row = TreeRow(TabRecord(1, 1, "one", (10,)), 0, None)
        self.assertEqual(
            render_row(row, selected=False, width=30),
            render_row(row, selected=True, width=30),
        )

    def test_status_glyph_width_does_not_move_title(self) -> None:
        statuses = [None, "🤖", "💬", "ready_to_merge", "blocked"]
        positions = []
        for status in statuses:
            rendered = render_row(
                TreeRow(TabRecord(1, 1, "fixed-title", (10,), status=status), 0, None),
                selected=False, width=40, ansi=False, now=0.0,
            )
            positions.append(display_width(rendered.split("fixed-title", 1)[0]))
        self.assertEqual(positions, [positions[0]] * len(positions))

    def test_only_tree_depth_moves_title_column(self) -> None:
        root = render_row(
            TreeRow(TabRecord(1, 1, "fixed-title", (10,), status="💬"), 0, None),
            selected=False, width=40, ansi=False,
        )
        child = render_row(
            TreeRow(TabRecord(2, 1, "fixed-title", (20,), status=None), 2, 1),
            selected=False, width=40, ansi=False,
        )
        root_column = display_width(root.split("fixed-title", 1)[0])
        child_column = display_width(child.split("fixed-title", 1)[0])
        self.assertEqual(child_column - root_column, 4)

    def test_leaf_row_has_no_tree_dash(self) -> None:
        leaf = render_row(
            TreeRow(TabRecord(1, 1, "leaf", (10,)), 0, None),
            selected=False, width=30, ansi=False,
        )
        self.assertNotIn("─", leaf)
        self.assertIn(LEFT_CAP, leaf)
        self.assertIn(RIGHT_CAP, leaf)

    def test_working_row_uses_rounded_right_cap(self) -> None:
        working = render_row(
            TreeRow(TabRecord(1, 1, "working", (10,), status="🤖"), 0, None),
            selected=False, width=30, ansi=False, now=0.0,
        )
        self.assertIn(LEFT_CAP, working)
        self.assertIn(RIGHT_CAP, working)
        self.assertNotIn(FLAME_RIGHT_CAP, working)

    def test_verdicts_replace_only_the_right_cap(self) -> None:
        ready = render_row(
            TreeRow(TabRecord(1, 1, "ready", (10,), status="ready_to_merge"), 0, None),
            selected=False, width=30, ansi=False,
        )
        blocked = render_row(
            TreeRow(TabRecord(2, 1, "blocked", (20,), status="blocked"), 0, None),
            selected=False, width=30, ansi=False,
        )
        self.assertIn(READY_RIGHT_CAP, ready)
        self.assertEqual(READY_RIGHT_CAP, "\ue0c8")
        self.assertIn(FLAME_RIGHT_CAP, blocked)
        self.assertNotIn(RIGHT_CAP, ready)
        self.assertNotIn(RIGHT_CAP, blocked)


if __name__ == "__main__":
    unittest.main()
