import os
import unittest
from unittest.mock import patch

from ktt.events import (
    TabEventListener,
    event_socket_path,
    navigation_direction,
    navigation_event,
)
from ktt.kitty_watcher import on_tab_bar_dirty


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
