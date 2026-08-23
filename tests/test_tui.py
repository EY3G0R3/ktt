import unittest

from ktt.model import TabRecord, TreeRow
from ktt.tui import (
    active_row_index,
    disclosure_column,
    parse_mouse_event,
    reload_candidate,
    restart_arguments,
    row_index_at_mouse,
    window_is_focused,
)
from ktt.repository import active_window_cwd


class MouseTests(unittest.TestCase):
    def test_repository_cwd_follows_the_active_tab_window(self) -> None:
        os_window = {"tabs": [
            {"is_active": False, "windows": [{"id": 1, "cwd": "/old"}]},
            {
                "is_active": True,
                "active_window_history": [3, 2],
                "windows": [
                    {"id": 2, "cwd": "/inactive"},
                    {"id": 3, "cwd": "/active"},
                ],
            },
        ]}
        self.assertEqual(active_window_cwd(os_window), "/active")

    def test_sidebar_focus_comes_from_its_own_kitty_window(self) -> None:
        snapshot = [{"tabs": [{"windows": [
            {"id": 10, "is_focused": False},
            {"id": 20, "is_focused": True},
        ]}]}]
        self.assertTrue(window_is_focused(snapshot, 20))
        self.assertFalse(window_is_focused(snapshot, 10))

    def test_parses_left_click_and_wheel(self) -> None:
        click = parse_mouse_event("\x1b[<0;12;4M")
        self.assertEqual((click.button, click.column, click.row, click.pressed), (
            "left", 12, 4, True
        ))
        self.assertEqual(parse_mouse_event("\x1b[<65;2;3M").button, "wheel_down")

    def test_ignores_release_and_motion_at_action_layer(self) -> None:
        self.assertFalse(parse_mouse_event("\x1b[<0;12;4m").pressed)
        self.assertIsNone(parse_mouse_event("\x1b[<32;12;4M"))

    def test_uses_press_when_press_and_release_share_a_read(self) -> None:
        event = parse_mouse_event("\x1b[<0;12;4M\x1b[<0;12;4m")
        self.assertTrue(event.pressed)
        self.assertEqual(event.button, "left")

    def test_maps_screen_row_after_scroll(self) -> None:
        self.assertEqual(
            row_index_at_mouse(1, start=5, row_count=20, height=12), 5
        )
        self.assertEqual(
            row_index_at_mouse(4, start=5, row_count=20, height=12), 8
        )
        self.assertIsNone(
            row_index_at_mouse(13, start=5, row_count=20, height=12)
        )

    def test_maps_centered_screen_row(self) -> None:
        self.assertIsNone(row_index_at_mouse(
            1, start=0, row_count=2, height=11, top_padding=1
        ))
        self.assertEqual(row_index_at_mouse(
            2, start=0, row_count=2, height=11, top_padding=1
        ), 0)
        self.assertEqual(row_index_at_mouse(
            3, start=0, row_count=2, height=11, top_padding=1
        ), 1)

    def test_every_physical_line_of_tall_card_maps_to_same_tab(self) -> None:
        arguments = {
            "start": 0,
            "row_count": 3,
            "height": 20,
            "top_padding": 1,
            "card_height": 3,
        }
        self.assertIsNone(row_index_at_mouse(1, **arguments))
        self.assertEqual(row_index_at_mouse(2, **arguments), 0)
        self.assertEqual(row_index_at_mouse(3, **arguments), 0)
        self.assertEqual(row_index_at_mouse(4, **arguments), 0)
        self.assertIsNone(row_index_at_mouse(5, **arguments))
        self.assertEqual(row_index_at_mouse(6, **arguments), 1)
        self.assertEqual(row_index_at_mouse(10, **arguments), 2)
        self.assertEqual(row_index_at_mouse(12, **arguments), 2)
        self.assertIsNone(row_index_at_mouse(21, **arguments))

    def test_disclosure_column_tracks_depth(self) -> None:
        tab = TabRecord(1, 1, "parent", (10,))
        self.assertEqual(disclosure_column(TreeRow(tab, 0, None)), 2)
        self.assertEqual(disclosure_column(TreeRow(tab, 2, None)), 10)

    def test_active_row_uses_visible_folded_ancestor(self) -> None:
        inactive = TreeRow(TabRecord(1, 1, "one", (10,)), 0, None)
        folded = TreeRow(
            TabRecord(2, 1, "parent", (20,)), 0, None,
            has_children=True, is_collapsed=True, has_active_descendant=True,
        )
        self.assertEqual(active_row_index([inactive, folded]), 1)

    def test_active_row_prefers_visible_child_over_its_ancestor(self) -> None:
        parent = TreeRow(
            TabRecord(1, 1, "parent", (10,)),
            0,
            None,
            has_children=True,
            has_active_descendant=True,
        )
        child = TreeRow(
            TabRecord(2, 1, "child", (20,), is_active=True),
            1,
            1,
        )
        next_root = TreeRow(TabRecord(3, 1, "next", (30,)), 0, None)
        self.assertEqual(active_row_index([parent, child, next_root]), 1)

    def test_auto_reload_preserves_the_live_edge_style(self) -> None:
        self.assertEqual(
            restart_arguments(
                ["--to", "unix:/tmp/kitty", "--edge-style", "tapered"],
                "rounded",
            ),
            ["--to", "unix:/tmp/kitty", "--edge-style", "rounded"],
        )
        self.assertEqual(
            restart_arguments(["--edge-style=wedge"], "straight"),
            ["--edge-style", "straight"],
        )

    def test_auto_reload_waits_for_a_stable_source_snapshot(self) -> None:
        initial = (("tui.py", 1, 100),)
        first_edit = (("tui.py", 2, 101),)
        complete_edit = (("tui.py", 3, 102),)

        candidate, ready = reload_candidate(initial, None, first_edit)
        self.assertFalse(ready)
        candidate, ready = reload_candidate(initial, candidate, complete_edit)
        self.assertFalse(ready)
        candidate, ready = reload_candidate(initial, candidate, complete_edit)
        self.assertTrue(ready)


if __name__ == "__main__":
    unittest.main()
