from collections import deque
import unittest

from ktt.kitty_layout import place_window_at_left_edge


class Window:
    def __init__(self, window_id: int) -> None:
        self.id = window_id


class Group:
    def __init__(self, group_id: int, window: Window) -> None:
        self.id = group_id
        self.window = window


class Windows:
    def __init__(self, source: Window, sidebar: Window) -> None:
        self.groups = [Group(10, source), Group(20, sidebar)]
        self.active_group_idx = 0
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
    def __init__(self, source: Window, sidebar: Window) -> None:
        self.windows = Windows(source, sidebar)
        self.current_layout = Layout()
        self.relayout_count = 0

    def relayout(self) -> None:
        self.relayout_count += 1


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


if __name__ == "__main__":
    unittest.main()
