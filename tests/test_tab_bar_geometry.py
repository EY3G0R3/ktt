import re
import unittest
import unicodedata

from ktt.render import adaptive_card_height, vertical_padding
from ktt.tab_bar_geometry import (
    bounded_cell_count,
    cached_tree_depth,
    fit_vertical_title,
    is_vertical_edge,
    select_content_windows,
    tree_indent,
    tree_leading_cells,
    valid_parent_tab_ids,
    vertical_cursor_plan,
    vertical_tab_layout,
)


def cell_width(text: str) -> int:
    plain = re.sub(r"\x1b\[[0-9;]*m", "", text)
    return sum(
        0 if unicodedata.combining(char)
        else 2 if unicodedata.east_asian_width(char) in {"W", "F"}
        else 1
        for char in plain
    )


def truncate(text: str, max_cells: int) -> str:
    rendered = ""
    for char in text:
        if cell_width(rendered + char) > max_cells:
            break
        rendered += char
    return rendered


class TabBarGeometryTests(unittest.TestCase):
    def test_content_window_selection_is_agent_first_without_active_bias(
        self,
    ) -> None:
        sidebar = {"id": 1, "sidebar": "1", "role": ""}
        active = {"id": 2, "sidebar": "", "role": ""}
        agent = {"id": 3, "sidebar": "", "role": "agent"}

        selected = select_content_windows(
            (sidebar, active, agent),
            user_var=lambda window, key: window[key],
            sidebar_var="sidebar",
            role_var="role",
            agent_role="agent",
            is_active=lambda window: window is active,
        )

        self.assertEqual([window["id"] for window in selected], [3, 2])

    def test_vertical_branch_uses_running_edge_constants(self) -> None:
        self.assertTrue(is_vertical_edge(1, 1, 2))
        self.assertTrue(is_vertical_edge(2, 1, 2))
        self.assertFalse(is_vertical_edge(3, 1, 2))
        self.assertFalse(is_vertical_edge(None, None, None))

    def test_vertical_cursor_plan_never_crosses_row_bound(self) -> None:
        before = 7
        rewind, remaining = vertical_cursor_plan(before, 30, 12)
        cursor = 30 - rewind + (1 if rewind else 0) + remaining

        self.assertEqual(cursor, before + 12)
        self.assertGreater(rewind, 0)

    def test_vertical_cursor_plan_fills_after_normal_short_title(self) -> None:
        rewind, remaining = vertical_cursor_plan(5, 10, 12)

        self.assertEqual(rewind, 0)
        self.assertEqual(remaining, 7)
        self.assertEqual(10 + remaining, 17)

    def test_vertical_cursor_plan_has_no_movement_for_tiny_limits(self) -> None:
        self.assertEqual(vertical_cursor_plan(5, 5, 0), (0, 0))
        self.assertEqual(vertical_cursor_plan(5, 6, 1), (0, 0))

    def test_vertical_layout_uses_three_row_cards_with_centered_gaps(self) -> None:
        layout = vertical_tab_layout(3, 15, active_index=1)

        self.assertEqual(
            [
                (placement.data_index, placement.start_row, placement.card_height)
                for placement in layout.placements
            ],
            [(0, 2, 3), (1, 6, 3), (2, 10, 3)],
        )
        self.assertEqual(
            [placement.content_row for placement in layout.placements],
            [3, 7, 11],
        )
        self.assertIsNone(layout.ellipsis_row)

    def test_vertical_layout_adapts_to_two_then_one_row_cards(self) -> None:
        two_rows = vertical_tab_layout(3, 10)
        one_row = vertical_tab_layout(3, 7)

        self.assertTrue(all(item.card_height == 2 for item in two_rows.placements))
        self.assertTrue(all(item.card_height == 1 for item in one_row.placements))

    def test_native_density_and_centering_match_legacy_geometry(self) -> None:
        for tab_count, height in ((3, 15), (3, 10), (3, 7), (4, 14)):
            with self.subTest(tab_count=tab_count, height=height):
                layout = vertical_tab_layout(tab_count, height)
                legacy_height = adaptive_card_height(tab_count, height)

                self.assertTrue(layout.placements)
                self.assertTrue(
                    all(
                        placement.card_height == legacy_height
                        for placement in layout.placements
                    )
                )
                self.assertEqual(
                    layout.placements[0].start_row,
                    vertical_padding(tab_count, height, legacy_height),
                )

    def test_overflow_keeps_active_tab_visible_and_draws_ellipsis(self) -> None:
        layout = vertical_tab_layout(10, 4, active_index=8)

        self.assertEqual(
            [placement.data_index for placement in layout.placements],
            [7, 8, 9],
        )
        self.assertEqual(layout.ellipsis_row, 3)

    def test_depth_indent_is_distinct_and_clamped_to_cell_budget(self) -> None:
        self.assertEqual(tree_indent(1, 24), "    └─ ")
        self.assertEqual(tree_indent(2, 24), "        └─ ")
        self.assertEqual(tree_indent(99, 13), "        └─ ")
        self.assertEqual(bounded_cell_count(0), 40)
        self.assertEqual(tree_leading_cells(4, 19), 12)
        self.assertEqual(tree_leading_cells(99, 9), 4)

    def test_title_fit_shortens_indent_before_semantic_labels(self) -> None:
        rendered = fit_vertical_title(
            tree_indent(5, 24),
            ("ready", "[repo]"),
            "界界\nunsafe",
            24,
            sanitize=lambda value: " ".join(value.split()),
            measure=cell_width,
            truncate=truncate,
        )

        self.assertIn("ready", rendered)
        self.assertIn("[repo]", rendered)
        self.assertNotIn("\n", rendered)
        self.assertLessEqual(cell_width(rendered), 24)

    def test_title_fit_drops_decorative_prefix_before_semantic_labels(self) -> None:
        rendered = fit_vertical_title(
            "",
            ("●", "ready", "[repo]"),
            "x",
            14,
            sanitize=str,
            measure=cell_width,
            truncate=truncate,
        )

        self.assertNotIn("●", rendered)
        self.assertIn("ready", rendered)
        self.assertIn("[repo]", rendered)

    def test_cycles_are_rejected_without_hiding_members(self) -> None:
        signature = (
            (10, (100,), 200),
            (20, (200,), 100),
            (30, (300,), 200),
        )

        self.assertEqual(valid_parent_tab_ids(signature), {30: 20})

    def test_depth_cache_invalidates_when_parent_membership_changes(self) -> None:
        cache = {}
        roots = ((10, (100,), None), (20, (200,), None))
        child = ((10, (100,), None), (20, (200,), 100))

        self.assertEqual(cached_tree_depth(cache, 7, roots, 20), 0)
        self.assertEqual(cached_tree_depth(cache, 7, child, 20), 1)
        self.assertEqual(cache[7][0], child)


if __name__ == "__main__":
    unittest.main()
