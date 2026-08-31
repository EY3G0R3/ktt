from collections import deque
import unittest
from unittest.mock import patch

from ktt import model
from ktt.kitty_tabs import (
    apply_tab_order,
    live_tree_records,
    live_tree_tab_ids,
    tree_topology_signature,
)
from ktt.tab_bar_geometry import select_content_windows, tree_depths


class FakeTab:
    def __init__(self, tab_id: int) -> None:
        self.id = tab_id


class FakeWindow:
    def __init__(self, window_id: int, **user_vars: str) -> None:
        self.id = window_id
        self.user_vars = user_vars


class LiveTab:
    def __init__(
        self, tab_id: int, windows: list[FakeWindow], active: int = 0
    ) -> None:
        self.id = tab_id
        self.title = f"tab {tab_id}"
        self.windows = windows
        self.active_window = windows[active] if windows else None

    def __iter__(self):
        return iter(self.windows)


class LiveTabManager(list):
    def __init__(self, tabs: list[LiveTab]) -> None:
        super().__init__(tabs)
        self.os_window_id = 7
        self.active_tab = tabs[0] if tabs else None


class FakeTabManager:
    def __init__(self) -> None:
        self.os_window_id = 7
        self.tabs = [FakeTab(tab_id) for tab_id in (10, 99, 20, 30)]
        self.active_tab = self.tabs[2]
        self.active_tab_history = deque((30, 10))
        self.active_indexes: list[tuple[int, bool]] = []
        self.dirty = 0

    def _set_active_tab(self, index: int, store_in_history: bool = True) -> None:
        self.active_indexes.append((index, store_in_history))
        self.active_tab = self.tabs[index]

    def mark_tab_bar_dirty(self) -> None:
        self.dirty += 1


class FailOnceHistory(deque):
    def __init__(self, values) -> None:
        super().__init__(values)
        self.failed = False

    def clear(self) -> None:
        if not self.failed:
            self.failed = True
            raise RuntimeError("history failure")
        super().clear()


class TabOrderingTests(unittest.TestCase):
    def assert_original_state(
        self, manager: FakeTabManager, active: FakeTab
    ) -> None:
        self.assertEqual(
            [tab.id for tab in manager.tabs], [10, 99, 20, 30]
        )
        self.assertIs(manager.active_tab, active)
        self.assertEqual(tuple(manager.active_tab_history), (30, 10))

    def test_live_tree_uses_agent_metadata_and_excludes_sidebar_tabs(self) -> None:
        child = LiveTab(20, [
            FakeWindow(201, ktt_parent_window_id="999"),
            FakeWindow(
                200,
                ktt_cockpit_role="agent",
                ktt_parent_window_id="100",
            ),
        ])
        sidebar = LiveTab(99, [FakeWindow(990, ktt_sidebar="1")])
        root = LiveTab(10, [FakeWindow(100)])
        manager = LiveTabManager([child, sidebar, root])

        self.assertEqual(live_tree_tab_ids(manager), (10, 20))

    def test_live_order_and_renderer_depth_share_parent_window_selection(
        self,
    ) -> None:
        root = LiveTab(10, [FakeWindow(100)])
        child = LiveTab(20, [
            FakeWindow(201, ktt_parent_window_id="300"),
            FakeWindow(
                200,
                ktt_cockpit_role="agent",
                ktt_parent_window_id="100",
            ),
            FakeWindow(
                202,
                ktt_sidebar="1",
                ktt_parent_window_id="300",
            ),
        ])
        other = LiveTab(30, [FakeWindow(300)])
        manager = LiveTabManager([root, child, other])

        records = live_tree_records(manager)
        selected = select_content_windows(
            tuple(child),
            user_var=lambda window, key: str(window.user_vars.get(key) or ""),
            sidebar_var=model.SIDEBAR_VAR,
            role_var=model.COCKPIT_ROLE_VAR,
            agent_role=model.AGENT_ROLE,
            is_active=lambda window: window is child.active_window,
        )
        signature = (
            (10, (100,), None),
            (
                20,
                tuple(window.id for window in selected),
                int(selected[0].user_vars[model.PARENT_VAR]),
            ),
            (30, (300,), None),
        )

        self.assertEqual(records[1].parent_window_id, 100)
        self.assertEqual(live_tree_tab_ids(manager), (10, 20, 30))
        self.assertEqual(tree_depths(signature)[20], 1)

    def test_live_tree_keeps_cycle_members_visible(self) -> None:
        first = LiveTab(10, [FakeWindow(100, ktt_parent_window_id="200")])
        second = LiveTab(20, [FakeWindow(200, ktt_parent_window_id="100")])

        self.assertEqual(live_tree_tab_ids(LiveTabManager([first, second])), (
            10, 20,
        ))

    def test_live_tree_attention_uses_agent_status_without_order_file(
        self,
    ) -> None:
        active = LiveTab(10, [FakeWindow(100)])
        ready = LiveTab(20, [
            FakeWindow(201, workmux_status="working"),
            FakeWindow(
                200,
                ktt_cockpit_role="agent",
                workmux_status="ready_to_merge",
            ),
        ])
        manager = LiveTabManager([active, ready])

        target = model.next_attention_tab_id(
            model.tree_rows(live_tree_records(manager))
        )

        self.assertEqual(target, 20)

    def test_live_tree_suppresses_fresh_waiting_spinner_attention(self) -> None:
        active = LiveTab(10, [FakeWindow(100)])
        waiting = LiveTab(20, [FakeWindow(200, workmux_status="waiting")])
        waiting.title = "✳ still working"
        manager = LiveTabManager([active, waiting])

        records = live_tree_records(manager)

        self.assertEqual(records[1].status, "waiting")
        self.assertTrue(records[1].attention_suppressed)
        self.assertIsNone(model.next_attention_tab_id(model.tree_rows(records)))

    def test_topology_signature_ignores_paint_but_tracks_membership(self) -> None:
        window = FakeWindow(100, workmux_status="working")
        tab = LiveTab(10, [window])
        manager = LiveTabManager([tab])
        original = tree_topology_signature(manager)

        tab.title = "repainted"
        window.user_vars["workmux_status"] = "ready_to_merge"
        self.assertEqual(tree_topology_signature(manager), original)

        tab.windows.append(FakeWindow(101))
        self.assertNotEqual(tree_topology_signature(manager), original)

    @patch("ktt.kitty_tabs._swap_tabs")
    def test_partial_order_preserves_unknown_slots_and_focus_state(
        self, swap_tabs
    ) -> None:
        manager = FakeTabManager()
        active = manager.active_tab

        self.assertTrue(apply_tab_order(manager, (30, 10, 20)))

        self.assertEqual([tab.id for tab in manager.tabs], [30, 99, 10, 20])
        self.assertIs(manager.active_tab, active)
        self.assertEqual(tuple(manager.active_tab_history), (30, 10))
        self.assertEqual(manager.active_indexes, [(3, False)])
        self.assertGreater(swap_tabs.call_count, 0)
        self.assertEqual(manager.dirty, 1)

    @patch("ktt.kitty_tabs._swap_tabs")
    def test_noop_order_does_not_dirty_the_tab_bar(self, swap_tabs) -> None:
        manager = FakeTabManager()

        self.assertFalse(apply_tab_order(manager, (10, 20, 30)))

        swap_tabs.assert_not_called()
        self.assertEqual(manager.active_indexes, [])
        self.assertEqual(manager.dirty, 0)

    @patch("ktt.kitty_tabs._swap_tabs")
    def test_c_side_swap_failure_rolls_back_completed_swaps(
        self, swap_tabs
    ) -> None:
        manager = FakeTabManager()
        active = manager.active_tab
        calls = []

        def fail_second(os_window_id, left, right):
            calls.append((os_window_id, left, right))
            if len(calls) == 2:
                raise RuntimeError("swap failure")

        swap_tabs.side_effect = fail_second

        with self.assertRaisesRegex(RuntimeError, "swap failure"):
            apply_tab_order(manager, (30, 10, 20))

        self.assert_original_state(manager, active)
        self.assertEqual(calls[0], calls[-1])

    @patch("ktt.kitty_tabs._swap_tabs")
    def test_focus_failure_rolls_back_order_focus_and_history(
        self, _swap_tabs
    ) -> None:
        manager = FakeTabManager()
        active = manager.active_tab
        attempts = 0

        def fail_once(index, store_in_history=True):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("focus failure")
            manager.active_tab = manager.tabs[index]

        manager._set_active_tab = fail_once

        with self.assertRaisesRegex(RuntimeError, "focus failure"):
            apply_tab_order(manager, (30, 10, 20))

        self.assert_original_state(manager, active)

    @patch("ktt.kitty_tabs._swap_tabs")
    def test_history_failure_rolls_back_all_state(self, _swap_tabs) -> None:
        manager = FakeTabManager()
        active = manager.active_tab
        manager.active_tab_history = FailOnceHistory((30, 10))

        with self.assertRaisesRegex(RuntimeError, "history failure"):
            apply_tab_order(manager, (30, 10, 20))

        self.assert_original_state(manager, active)

    @patch("ktt.kitty_tabs._swap_tabs")
    def test_dirty_failure_rolls_back_and_marks_restored_state(
        self, _swap_tabs
    ) -> None:
        manager = FakeTabManager()
        active = manager.active_tab
        attempts = 0

        def fail_once():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("dirty failure")
            manager.dirty += 1

        manager.mark_tab_bar_dirty = fail_once

        with self.assertRaisesRegex(RuntimeError, "dirty failure"):
            apply_tab_order(manager, (30, 10, 20))

        self.assert_original_state(manager, active)
        self.assertEqual(manager.dirty, 1)

    @patch("ktt.kitty_tabs._swap_tabs")
    def test_public_active_tab_api_is_preferred(self, _swap_tabs) -> None:
        manager = FakeTabManager()
        selected = []

        def set_active_tab(tab):
            selected.append(tab)
            manager.active_tab = tab

        manager.set_active_tab = set_active_tab
        manager._set_active_tab = None

        self.assertTrue(apply_tab_order(manager, (30, 10, 20)))

        self.assertEqual(selected, [manager.active_tab])

    @patch("ktt.kitty_tabs._swap_tabs")
    def test_missing_focus_api_fails_before_swaps(self, swap_tabs) -> None:
        manager = FakeTabManager()
        manager._set_active_tab = None

        with self.assertRaisesRegex(TypeError, "active-tab setter"):
            apply_tab_order(manager, (30, 10, 20))

        swap_tabs.assert_not_called()


if __name__ == "__main__":
    unittest.main()
