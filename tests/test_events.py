import errno
import os
from collections import deque
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from ktt.events import (
    TabEventListener,
    event_socket_path,
    navigation_direction,
    navigation_event,
    parse_tab_state_event,
    send_navigation,
    tab_state_event,
)
from ktt.kitty_watcher import (
    NATIVE_MARKER_ATTRIBUTE,
    NORMALIZING_ATTRIBUTE,
    _normalize_native_tab_order,
    _notify,
    on_tab_bar_dirty,
)


class FakeTab:
    def __init__(self, tab_id: int) -> None:
        self.id = tab_id
        self.title = f"tab {tab_id}"
        self.windows = []
        self.active_window = None

    def __iter__(self):
        return iter(self.windows)


class FakeTabManager(list):
    def __init__(self, os_window_id: int, tab_ids: list[int], active: int) -> None:
        super().__init__(FakeTab(tab_id) for tab_id in tab_ids)
        self.os_window_id = os_window_id
        self.active_tab = next(tab for tab in self if tab.id == active)
        self.active_tab_history = deque()
        self.on_dirty = None
        self.dirty_count = 0

    @property
    def tabs(self):
        return self

    def _set_active_tab(self, index, store_in_history=True):
        self.active_tab = self[index]

    def mark_tab_bar_dirty(self):
        self.dirty_count += 1
        if self.on_dirty is not None:
            self.on_dirty()


class FakeWindow:
    def __init__(self, window_id: int, **user_vars: str) -> None:
        self.id = window_id
        self.user_vars = user_vars


class FakeBoss:
    pass


class FakeSocket:
    def __init__(self) -> None:
        self.reads = [b"tabs"]

    def recv(self, _size: int) -> bytes:
        if self.reads:
            return self.reads.pop()
        raise BlockingIOError


class EventTests(unittest.TestCase):
    def test_listener_and_watcher_share_the_runtime_socket_contract(self) -> None:
        environment = {
            "XDG_RUNTIME_DIR": "/run/user/example",
            "KITTY_PID": str(os.getpid()),
        }
        with patch.dict(os.environ, environment, clear=False):
            from ktt.kitty_watcher import event_socket_path as watcher_path

            self.assertEqual(event_socket_path(3), watcher_path(3))

    def test_listener_drains_all_queued_wakeups(self) -> None:
        listener = TabEventListener()
        listener.socket = FakeSocket()
        self.assertEqual(listener.drain(), (b"tabs",))
        self.assertEqual(listener.drain(), ())

    def test_second_listener_uses_a_process_specific_socket(self) -> None:
        listener_socket = MagicMock()
        fake_stat = MagicMock(st_ino=7)
        with (
            patch("ktt.events.Path.exists", return_value=True),
            patch("ktt.events.Path.mkdir"),
            patch("ktt.events.Path.unlink"),
            patch("ktt.events.Path.chmod"),
            patch("ktt.events.Path.stat", return_value=fake_stat),
            patch("ktt.events.socket.socket", return_value=listener_socket),
            patch("ktt.events.os.getpid", return_value=456),
        ):
            listener = TabEventListener()
            listener.bind(3)
        self.assertTrue(str(listener.path).endswith(".456"))
        listener_socket.bind.assert_called_once_with(str(listener.path))

    def test_watcher_broadcasts_tab_events_to_every_listener(self) -> None:
        base = event_socket_path(3)
        sibling = base.with_name(f"{base.name}.456")
        sender = MagicMock()
        with (
            patch("ktt.kitty_watcher.event_socket_path", return_value=base),
            patch("ktt.kitty_watcher.Path.glob", return_value=[sibling]),
            patch("ktt.kitty_watcher.socket.socket", return_value=sender),
        ):
            _notify(3, 20, (10, 20))
        event = tab_state_event(20, (10, 20))
        self.assertEqual(
            [call.args for call in sender.sendto.call_args_list],
            [(event, str(base)), (event, str(sibling))],
        )

    def test_tab_state_event_round_trips_active_tab_and_membership(self) -> None:
        event = tab_state_event(20, (10, 20, 30))
        state = parse_tab_state_event(event)
        self.assertIsNotNone(state)
        self.assertEqual(state.active_tab_id, 20)
        self.assertEqual(state.tab_ids, (10, 20, 30))
        self.assertIsNone(parse_tab_state_event(b"tabs"))
        self.assertIsNone(parse_tab_state_event(b"tabs:99|10,20"))

    def test_navigation_stops_after_the_primary_listener(self) -> None:
        sender = MagicMock()
        with patch("ktt.events.socket.socket", return_value=sender):
            self.assertTrue(send_navigation(3, 1))
        sender.sendto.assert_called_once()

    def test_navigation_removes_refused_stale_socket(self) -> None:
        path = Path("/tmp/stale.sock")
        sender = MagicMock()
        sender.sendto.side_effect = ConnectionRefusedError(
            errno.ECONNREFUSED, "refused"
        )
        fake_stat = MagicMock(st_ino=7)
        with (
            patch("ktt.events.event_socket_path", return_value=path),
            patch("ktt.events.Path.glob", return_value=[]),
            patch("ktt.events.Path.stat", return_value=fake_stat),
            patch("ktt.events.Path.unlink") as unlink,
            patch("ktt.events.socket.socket", return_value=sender),
        ):
            self.assertFalse(send_navigation(3, 1))
        unlink.assert_called_once_with()

    def test_watcher_removes_refused_stale_socket(self) -> None:
        path = Path("/tmp/stale.sock")
        sender = MagicMock()
        sender.sendto.side_effect = ConnectionRefusedError(
            errno.ECONNREFUSED, "refused"
        )
        fake_stat = MagicMock(st_ino=7)
        with (
            patch("ktt.kitty_watcher.event_socket_path", return_value=path),
            patch("ktt.kitty_watcher.Path.glob", return_value=[]),
            patch("ktt.kitty_watcher.Path.stat", return_value=fake_stat),
            patch("ktt.kitty_watcher.Path.unlink") as unlink,
            patch("ktt.kitty_watcher.socket.socket", return_value=sender),
        ):
            _notify(3, 10, (10,))
        unlink.assert_called_once_with()

    def test_refused_send_keeps_a_concurrently_replaced_socket(self) -> None:
        path = Path("/tmp/replaced.sock")
        sender = MagicMock()
        sender.sendto.side_effect = ConnectionRefusedError(
            errno.ECONNREFUSED, "refused"
        )
        with (
            patch("ktt.events.event_socket_path", return_value=path),
            patch("ktt.events.Path.glob", return_value=[]),
            patch(
                "ktt.events.Path.stat",
                side_effect=[MagicMock(st_ino=7), MagicMock(st_ino=8)],
            ),
            patch("ktt.events.Path.unlink") as unlink,
            patch("ktt.events.socket.socket", return_value=sender),
        ):
            self.assertFalse(send_navigation(3, 1))
        unlink.assert_not_called()

    def test_navigation_event_round_trips_direction(self) -> None:
        self.assertEqual(navigation_direction(navigation_event(1)), 1)
        self.assertEqual(navigation_direction(navigation_event(-1)), -1)
        self.assertIsNone(navigation_direction(b"tabs"))

    def test_watcher_ignores_title_only_tab_bar_churn(self) -> None:
        boss = FakeBoss()
        manager = FakeTabManager(3, [10, 20], 10)
        data = {"tab_manager": manager}
        with patch("ktt.kitty_watcher._notify") as notify:
            on_tab_bar_dirty(boss, None, data)
            on_tab_bar_dirty(boss, None, data)
            manager.active_tab = manager[1]
            on_tab_bar_dirty(boss, None, data)
        self.assertEqual(
            [call.args for call in notify.call_args_list],
            [(3, 10, (10, 20)), (3, 20, (10, 20))],
        )

    def test_normalization_failure_does_not_suppress_notification(self) -> None:
        boss = FakeBoss()
        manager = FakeTabManager(3, [10, 20], 10)

        with (
            patch(
                "ktt.kitty_watcher._normalize_native_tab_order",
                side_effect=RuntimeError("private Kitty API changed"),
            ),
            patch("ktt.kitty_watcher._log_error") as log_error,
            patch("ktt.kitty_watcher._notify") as notify,
        ):
            on_tab_bar_dirty(boss, None, {"tab_manager": manager})

        notify.assert_called_once_with(3, 10, (10, 20))
        self.assertIn("private Kitty API changed", log_error.call_args.args[0])

    def test_vertical_watcher_normalizes_new_or_reparented_tabs(self) -> None:
        boss = FakeBoss()
        setattr(boss, NATIVE_MARKER_ATTRIBUTE, True)
        manager = FakeTabManager(3, [20, 10], 20)

        with (
            patch("ktt.kitty_watcher._is_vertical_tab_bar", return_value=True),
            patch("ktt.kitty_watcher._load_kitty_tabs") as load_tabs,
            patch("ktt.kitty_watcher._notify"),
        ):
            load_tabs.return_value.tree_topology_signature.return_value = (
                (10, 20),
            )
            load_tabs.return_value.live_tree_tab_ids.return_value = (10, 20)
            apply = load_tabs.return_value.apply_tab_order
            apply.return_value = True
            on_tab_bar_dirty(boss, object(), {"tab_manager": manager})

        apply.assert_called_once_with(manager, (10, 20))

    def test_vertical_watcher_skips_title_only_churn_before_modeling(self) -> None:
        boss = FakeBoss()
        setattr(boss, NATIVE_MARKER_ATTRIBUTE, True)
        manager = FakeTabManager(3, [10, 20], 10)

        with (
            patch("ktt.kitty_watcher._is_vertical_tab_bar", return_value=True),
            patch("ktt.kitty_watcher._load_kitty_tabs") as load_tabs,
            patch("ktt.kitty_watcher._notify"),
        ):
            load_tabs.return_value.tree_topology_signature.return_value = (
                (10, 20),
            )
            live_order = load_tabs.return_value.live_tree_tab_ids
            live_order.return_value = (10, 20)
            load_tabs.return_value.apply_tab_order.return_value = False
            on_tab_bar_dirty(boss, object(), {"tab_manager": manager})
            on_tab_bar_dirty(boss, object(), {"tab_manager": manager})

        live_order.assert_called_once_with(manager)

    def test_ordering_import_failure_does_not_suppress_notification(self) -> None:
        boss = FakeBoss()
        setattr(boss, NATIVE_MARKER_ATTRIBUTE, True)
        manager = FakeTabManager(3, [10, 20], 10)

        with (
            patch("ktt.kitty_watcher._is_vertical_tab_bar", return_value=True),
            patch(
                "ktt.kitty_watcher._load_kitty_tabs",
                side_effect=ImportError("checkout unavailable"),
            ),
            patch("ktt.kitty_watcher._log_error") as log_error,
            patch("ktt.kitty_watcher._notify") as notify,
        ):
            on_tab_bar_dirty(boss, None, {"tab_manager": manager})

        notify.assert_called_once_with(3, 10, (10, 20))
        self.assertIn("checkout unavailable", log_error.call_args.args[0])

    def test_persistent_order_failure_logs_once_per_topology(self) -> None:
        boss = FakeBoss()
        setattr(boss, NATIVE_MARKER_ATTRIBUTE, True)
        manager = FakeTabManager(3, [20, 10], 20)

        with (
            patch("ktt.kitty_watcher._is_vertical_tab_bar", return_value=True),
            patch("ktt.kitty_watcher._load_kitty_tabs") as load_tabs,
            patch("ktt.kitty_watcher._log_error") as log_error,
            patch("ktt.kitty_watcher._notify"),
        ):
            load_tabs.return_value.tree_topology_signature.return_value = (
                (20, 10),
            )
            load_tabs.return_value.live_tree_tab_ids.return_value = (10, 20)
            load_tabs.return_value.apply_tab_order.side_effect = RuntimeError(
                "persistent failure"
            )
            on_tab_bar_dirty(boss, None, {"tab_manager": manager})
            on_tab_bar_dirty(boss, None, {"tab_manager": manager})

        load_tabs.return_value.apply_tab_order.assert_called_once()
        log_error.assert_called_once()

    def test_normalization_guard_stops_synchronous_dirty_recursion(self) -> None:
        boss = FakeBoss()
        setattr(boss, NATIVE_MARKER_ATTRIBUTE, True)
        manager = FakeTabManager(3, [20, 10], 20)
        child, root = manager
        child.windows = [FakeWindow(200, ktt_parent_window_id="100")]
        child.active_window = child.windows[0]
        root.windows = [FakeWindow(100)]
        root.active_window = root.windows[0]
        manager.on_dirty = lambda: on_tab_bar_dirty(
            boss, None, {"tab_manager": manager}
        )

        with (
            patch("ktt.kitty_watcher._is_vertical_tab_bar", return_value=True),
            patch("ktt.kitty_tabs._swap_tabs"),
            patch("ktt.kitty_watcher._notify") as notify,
        ):
            on_tab_bar_dirty(boss, None, {"tab_manager": manager})

        self.assertEqual([tab.id for tab in manager], [10, 20])
        self.assertEqual(manager.dirty_count, 1)
        notify.assert_called_once_with(3, 20, (10, 20))

    def test_normalization_guard_returns_before_ordering_import(self) -> None:
        boss = FakeBoss()
        setattr(boss, NATIVE_MARKER_ATTRIBUTE, True)
        setattr(boss, NORMALIZING_ATTRIBUTE, {3})
        manager = FakeTabManager(3, [20, 10], 20)

        with (
            patch("ktt.kitty_watcher._is_vertical_tab_bar", return_value=True),
            patch("ktt.kitty_watcher._load_kitty_tabs") as load_tabs,
        ):
            _normalize_native_tab_order(boss, None, manager)

        load_tabs.assert_not_called()

    def test_unmarked_vertical_bar_notifies_without_reordering(self) -> None:
        boss = FakeBoss()
        manager = FakeTabManager(3, [20, 10], 20)

        with (
            patch("ktt.kitty_watcher._is_vertical_tab_bar", return_value=True),
            patch("ktt.kitty_watcher._load_kitty_tabs") as load_tabs,
            patch("ktt.kitty_watcher._notify") as notify,
        ):
            on_tab_bar_dirty(boss, None, {"tab_manager": manager})

        load_tabs.assert_not_called()
        notify.assert_called_once_with(3, 20, (20, 10))

    def test_horizontal_watcher_leaves_native_order_alone(self) -> None:
        boss = FakeBoss()
        manager = FakeTabManager(3, [20, 10], 20)

        with (
            patch("ktt.kitty_watcher._is_vertical_tab_bar", return_value=False),
            patch("ktt.kitty_watcher._load_kitty_tabs") as load_tabs,
            patch("ktt.kitty_watcher._notify"),
        ):
            on_tab_bar_dirty(boss, None, {"tab_manager": manager})

        load_tabs.assert_not_called()


if __name__ == "__main__":
    unittest.main()
