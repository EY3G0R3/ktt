import os
import unittest
from unittest.mock import MagicMock, patch

from ktt.events import (
    TabEventListener,
    event_socket_path,
    navigation_direction,
    navigation_event,
    send_navigation,
)
from ktt.kitty_watcher import _notify, on_tab_bar_dirty


class FakeTab:
    def __init__(self, tab_id: int) -> None:
        self.id = tab_id


class FakeTabManager(list):
    def __init__(self, os_window_id: int, tab_ids: list[int], active: int) -> None:
        super().__init__(FakeTab(tab_id) for tab_id in tab_ids)
        self.os_window_id = os_window_id
        self.active_tab = next(tab for tab in self if tab.id == active)


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
            _notify(3)
        self.assertEqual(
            [call.args for call in sender.sendto.call_args_list],
            [(b"tabs", str(base)), (b"tabs", str(sibling))],
        )

    def test_navigation_stops_after_the_primary_listener(self) -> None:
        sender = MagicMock()
        with patch("ktt.events.socket.socket", return_value=sender):
            self.assertTrue(send_navigation(3, 1))
        sender.sendto.assert_called_once()

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
        self.assertEqual([call.args for call in notify.call_args_list], [(3,), (3,)])


if __name__ == "__main__":
    unittest.main()
