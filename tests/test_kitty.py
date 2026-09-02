from pathlib import Path
import json
import unittest
from unittest.mock import patch

import ktt.kitty as kitty_module
from ktt.kitty import KittyError, RemoteControl, find_tab_for_window
from ktt.native_tabs import NativeVerticalTabsUnsupported, UNSUPPORTED_MARKER


class RecordingRemote(RemoteControl):
    def __init__(self):
        super().__init__("unix:/tmp/example")
        self.call = None
        self.calls = []

    def run(self, subcommand, *arguments):
        self.call = (subcommand, arguments)
        self.calls.append(self.call)
        return "456"


class RemoteControlTests(unittest.TestCase):
    @staticmethod
    def _socket_reply(data):
        reply = json.dumps({"ok": True, "data": json.dumps(data)}).encode()
        return b"\x1bP@kitty-cmd" + reply + b"\x1b\\"

    def test_snapshot_uses_direct_unix_socket(self) -> None:
        snapshot = [{"id": 3, "tabs": []}]
        connection = unittest.mock.MagicMock()
        connection.recv.return_value = self._socket_reply(snapshot)
        context = unittest.mock.MagicMock()
        context.__enter__.return_value = connection
        with patch("ktt.kitty.socket.socket", return_value=context):
            remote = RemoteControl("unix:/tmp/kitty-test")
            self.assertEqual(remote.snapshot(), snapshot)
        connection.connect.assert_called_once_with("/tmp/kitty-test")
        self.assertIn(b'"cmd":"ls"', connection.sendall.call_args.args[0])

    def test_snapshot_falls_back_once_after_socket_failure(self) -> None:
        remote = RemoteControl("unix:/tmp/kitty-test")
        with (
            patch("ktt.kitty.socket.socket", side_effect=OSError("unavailable"))
            as socket_factory,
            patch.object(remote, "run", return_value='[{"id": 3}]') as run,
        ):
            self.assertEqual(remote.snapshot(), [{"id": 3}])
            self.assertEqual(remote.snapshot(), [{"id": 3}])
        socket_factory.assert_called_once()
        self.assertEqual(run.call_count, 2)

    def test_snapshot_supports_linux_abstract_socket(self) -> None:
        connection = unittest.mock.MagicMock()
        connection.recv.return_value = self._socket_reply([])
        context = unittest.mock.MagicMock()
        context.__enter__.return_value = connection
        with patch("ktt.kitty.socket.socket", return_value=context):
            RemoteControl("unix:@kitty-test").snapshot()
        connection.connect.assert_called_once_with("\0kitty-test")

    def test_launch_child_sets_parent_during_tab_creation(self) -> None:
        remote = RecordingRemote()
        child = remote.launch_child(123, ["codex", "--", "prompt"], "agent")
        self.assertEqual(child, 456)
        subcommand, arguments = remote.call
        self.assertEqual(subcommand, "launch")
        self.assertIn("ktt_parent_window_id=123", arguments)
        self.assertEqual(arguments[-3:], ("codex", "--", "prompt"))

    def test_native_vertical_tabs_target_the_source_process(self) -> None:
        remote = RecordingRemote()
        remote.enable_native_vertical_tabs(12)
        subcommand, arguments = remote.call
        self.assertEqual(subcommand, "action")
        self.assertEqual(arguments[:2], ("--match", "id:12"))
        self.assertEqual(arguments[-2:], (
            str(Path(kitty_module.__file__).with_name("native_tabs_kitten.py")),
            "vertical",
        ))

    def test_native_vertical_tabs_translate_running_version_error(self) -> None:
        remote = RecordingRemote()
        with (
            patch.object(
                remote,
                "run",
                side_effect=KittyError(
                    f"Kitty action failed: {UNSUPPORTED_MARKER}0.47.4"
                ),
            ),
            self.assertRaises(NativeVerticalTabsUnsupported) as raised,
        ):
            remote.enable_native_vertical_tabs(12)
        self.assertEqual(raised.exception.version, (0, 47, 4))

    def test_set_parent_updates_the_canonical_edge(self) -> None:
        remote = RecordingRemote()
        remote.set_parent(20, 10)
        self.assertEqual(remote.call, (
            "set-user-vars",
            ("--match", "id:20", "ktt_parent_window_id=10"),
        ))

    def test_find_tab_for_window_returns_os_window_and_tab(self) -> None:
        snapshot = [{"id": 1, "tabs": [{"id": 2, "windows": [{"id": 3}]}]}]
        self.assertEqual(find_tab_for_window(snapshot, 3), (1, 2))


if __name__ == "__main__":
    unittest.main()
