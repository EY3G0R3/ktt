from collections import deque
import unittest

from ktt.kitty_layout import (
    capture_embedded_left_edge_placements,
    place_window_at_left_edge,
    restore_embedded_left_edge_placements,
)


class Window:
    def __init__(self, window_id: int, user_vars=None) -> None:
        self.id = window_id
        self.user_vars = user_vars or {}


class Group:
    def __init__(self, group_id: int, window: Window) -> None:
        self.id = group_id
        self.window = window


class Windows:
    def __init__(
        self, source: Window, sidebar: Window, active_group_idx: int = 0
    ) -> None:
        self.groups = [Group(10, source), Group(20, sidebar)]
        self.active_group_idx = active_group_idx
        self.active_group_history = deque([10], 64)

    @property
    def active_window(self) -> Window:
        return self.groups[self.active_group_idx].window

    def group_idx_for_window(self, window: Window) -> int | None:
        return next(
            (
                index
                for index, group in enumerate(self.groups)
                if group.window is window
            ),
            None,
        )

    def set_active_group_idx(self, index: int, notify: bool = True) -> None:
        self.active_group_idx = index
        self.active_group_history.append(self.groups[index].id)


class Layout:
    def __init__(self, supported: bool = True) -> None:
        self.calls: list[tuple[str, tuple[str, ...], int]] = []
        self.supported = supported

    def layout_action(
        self, action: str, arguments: tuple[str, ...], windows: Windows
    ) -> bool:
        self.calls.append((action, arguments, windows.active_window.id))
        return self.supported


class Tab:
    def __init__(
        self, source: Window, sidebar: Window, active_group_idx: int = 0
    ) -> None:
        self.windows = Windows(source, sidebar, active_group_idx)
        self.current_layout = Layout()
        self.relayout_count = 0

    def relayout(self) -> None:
        self.relayout_count += 1

    def __iter__(self):
        return (group.window for group in self.windows.groups)

    @property
    def active_window(self) -> Window:
        return self.windows.active_window


class KittyLayoutTests(unittest.TestCase):
    def test_places_exact_sidebar_at_root_edge_without_changing_active_window(
        self,
    ) -> None:
        source = Window(100)
        sidebar = Window(190)
        tab = Tab(source, sidebar)

        self.assertTrue(place_window_at_left_edge(tab, sidebar, 20))

        self.assertEqual(tab.current_layout.calls, [
            ("move_to_screen_edge", ("left",), 190),
            ("bias", ("20",), 190),
        ])
        self.assertIs(tab.windows.active_window, source)
        self.assertEqual(tuple(tab.windows.active_group_history), (10,))
        self.assertEqual(tab.relayout_count, 1)

    def test_unsupported_layout_leaves_focus_and_size_unchanged(self) -> None:
        source = Window(100)
        sidebar = Window(190)
        tab = Tab(source, sidebar)
        tab.current_layout = Layout(supported=False)

        self.assertFalse(place_window_at_left_edge(tab, sidebar, 20))

        self.assertEqual(tab.current_layout.calls, [
            ("move_to_screen_edge", ("left",), 190),
        ])
        self.assertIs(tab.windows.active_window, source)
        self.assertEqual(tab.relayout_count, 0)

    def test_restores_explicit_content_when_new_sidebar_became_active(self) -> None:
        source = Window(100)
        sidebar = Window(190)
        tab = Tab(source, sidebar, active_group_idx=1)

        self.assertTrue(
            place_window_at_left_edge(
                tab, sidebar, 20, restore_window=source
            )
        )

        self.assertIs(tab.windows.active_window, source)
        self.assertEqual(tab.relayout_count, 1)

    def test_captures_and_restores_all_vertical_embedded_panes(self) -> None:
        sidebar_vars = {
            "ktt_sidebar": "1",
            "ktt_orientation": "vertical",
            "ktt_cockpit_role": "ktt",
            "ktt_pane_percent": "23",
        }
        source = Window(100, {"ktt_cockpit_role": "agent"})
        sidebar = Window(190, sidebar_vars)
        tab = Tab(source, sidebar, active_group_idx=1)

        placements = capture_embedded_left_edge_placements(
            [[tab]],
            sidebar_var="ktt_sidebar",
            orientation_var="ktt_orientation",
            pane_percent_var="ktt_pane_percent",
            cockpit_role_var="ktt_cockpit_role",
        )

        self.assertEqual(len(placements), 1)
        self.assertEqual(placements[0].bias, 23)
        self.assertEqual(restore_embedded_left_edge_placements(placements), 1)
        self.assertEqual(tab.current_layout.calls, [
            ("move_to_screen_edge", ("left",), 190),
            ("bias", ("23",), 190),
        ])
        self.assertIs(tab.active_window, source)

    def test_capture_ignores_horizontal_and_standalone_sidebars(self) -> None:
        source = Window(100)
        sidebars = [
            Window(190, {
                "ktt_sidebar": "1",
                "ktt_orientation": "horizontal",
                "ktt_cockpit_role": "ktt",
            }),
            Window(191, {
                "ktt_sidebar": "1",
                "ktt_orientation": "vertical",
            }),
        ]
        tabs = [Tab(source, sidebar) for sidebar in sidebars]

        placements = capture_embedded_left_edge_placements(
            [tabs],
            sidebar_var="ktt_sidebar",
            orientation_var="ktt_orientation",
            pane_percent_var="ktt_pane_percent",
            cockpit_role_var="ktt_cockpit_role",
        )

        self.assertEqual(placements, [])


if __name__ == "__main__":
    unittest.main()
