from pathlib import Path
import json
import unittest
from unittest.mock import patch

import ktt.kitty as kitty_module
from ktt.kitty import RemoteControl, find_sidebar_window


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
        sent = connection.sendall.call_args.args[0]
        self.assertTrue(sent.startswith(b"\x1bP@kitty-cmd"))
        self.assertIn(b'"cmd":"ls"', sent)

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
        self.assertIn("--type=tab", arguments)
        self.assertIn("ktt_parent_window_id=123", arguments)
        self.assertEqual(arguments[-3:], ("codex", "--", "prompt"))

    def test_finds_tagged_sidebar_and_recorded_target(self) -> None:
        snapshot = [{
            "id": 9,
            "wm_class": "ktt",
            "tabs": [{"windows": [{
                "id": 91,
                "cmdline": ["python3", "-m", "ktt"],
                "user_vars": {
                    "ktt_sidebar": "1",
                    "ktt_target_os_window_id": "3",
                },
            }]}],
        }]
        self.assertEqual(find_sidebar_window(snapshot), (9, 91, 3))

    def test_finds_sidebar_by_orientation(self) -> None:
        snapshot = [{
            "id": 9,
            "tabs": [{"windows": [
                {
                    "id": 91,
                    "user_vars": {
                        "ktt_sidebar": "1",
                        "ktt_target_os_window_id": "3",
                    },
                },
                {
                    "id": 92,
                    "user_vars": {
                        "ktt_sidebar": "1",
                        "ktt_target_os_window_id": "3",
                        "ktt_orientation": "horizontal",
                    },
                },
            ]}],
        }]
        self.assertEqual(find_sidebar_window(snapshot, "vertical"), (9, 91, 3))
        self.assertEqual(find_sidebar_window(snapshot, "horizontal"), (9, 92, 3))

    def test_preview_switches_tab_then_restores_sidebar_focus(self) -> None:
        remote = RecordingRemote()
        remote.preview_tab(12, 91)
        self.assertEqual(remote.calls, [
            ("focus-tab", ("--match", "id:12")),
            ("focus-window", ("--match", "id:91")),
        ])

    def test_embedded_preview_focuses_destination_renderer(self) -> None:
        remote = RecordingRemote()
        remote.preview_embedded_tab(12, 192)
        self.assertEqual(remote.calls, [
            ("focus-tab", ("--match", "id:12")),
            ("focus-window", ("--match", "id:192")),
        ])

    def test_native_tab_toggle_targets_the_main_window(self) -> None:
        remote = RecordingRemote()
        remote.toggle_native_tabs(12)
        subcommand, arguments = remote.call
        self.assertEqual(subcommand, "action")
        self.assertEqual(arguments[:2], ("--match", "id:12"))
        self.assertEqual(arguments[-2:], (
            str(Path(kitty_module.__file__).with_name(
                "tree_navigation_kitten.py"
            )),
            "toggle-tabs",
        ))

    def test_running_sidebar_reapplies_launch_appearance_and_identity(self) -> None:
        remote = RecordingRemote()
        remote.configure_sidebar(91, 3, "vertical")
        self.assertEqual(remote.calls, [
            (
                "set-colors",
                ("--match", "id:91", "background=#000000"),
            ),
            (
                "set-user-vars",
                (
                    "--match",
                    "id:91",
                    "ktt_sidebar=1",
                    "ktt_orientation=vertical",
                    "ktt_target_os_window_id=3",
                ),
            ),
        ])

    def test_running_embedded_sidebar_restores_cockpit_role(self) -> None:
        remote = RecordingRemote()
        remote.configure_sidebar(91, 3, "horizontal", embedded=True)
        self.assertIn("ktt_cockpit_role=ktt", remote.calls[1][1])

    def test_sidebar_launch_passes_configured_edge_style(self) -> None:
        remote = RecordingRemote()
        remote.launch_sidebar(3, "rounded", "graphite")
        subcommand, arguments = remote.calls[0]
        self.assertEqual(subcommand, "launch")
        self.assertIn("--edge-style", arguments)
        self.assertEqual(arguments[arguments.index("--edge-style") + 1], "rounded")
        self.assertEqual(
            arguments[arguments.index("--repository-palette") + 1], "graphite"
        )
        self.assertIn("--color", arguments)
        self.assertEqual(arguments[arguments.index("--color") + 1], "background=#000000")

    def test_horizontal_launch_uses_distinct_window_identity(self) -> None:
        remote = RecordingRemote()
        remote.launch_sidebar(3, "tapered", "terminal", "horizontal")
        subcommand, arguments = remote.calls[0]
        self.assertEqual(subcommand, "launch")
        self.assertIn("--os-window-class=ktt-horizontal", arguments)
        self.assertIn("ktt_orientation=horizontal", arguments)
        self.assertIn("--orientation", arguments)
        self.assertEqual(
            arguments[arguments.index("--orientation") + 1], "horizontal"
        )

    def test_embedded_launch_splits_below_source_and_keeps_focus(self) -> None:
        remote = RecordingRemote()
        pane = remote.launch_pane(123, 3, "tapered", "terminal", 10)
        self.assertEqual(pane, 456)
        subcommand, arguments = remote.calls[0]
        self.assertEqual(subcommand, "launch")
        self.assertIn("window_id:123", arguments)
        self.assertIn("--location=hsplit", arguments)
        self.assertIn("--bias=10", arguments)
        self.assertIn("--keep-focus", arguments)
        self.assertIn("--embedded", arguments)
        self.assertIn("ktt_orientation=horizontal", arguments)
        self.assertIn("ktt_cockpit_role=ktt", arguments)
        self.assertNotIn("--shared-socket", arguments)

    def test_vertical_embedded_launch_creates_side_pane(self) -> None:
        remote = RecordingRemote()
        pane = remote.launch_pane(
            123, 3, "tapered", "terminal", 20,
            "/tmp/ktt-shared.sock", "vertical",
        )

        self.assertEqual(pane, 456)
        _, arguments = remote.calls[0]
        self.assertIn("--location=vsplit", arguments)
        self.assertIn("--bias=20", arguments)
        self.assertIn("ktt_orientation=vertical", arguments)
        self.assertEqual(
            arguments[arguments.index("--orientation") + 1], "vertical"
        )
        self.assertEqual(remote.calls[1], (
            "action",
            (
                "--match",
                "id:123",
                "kitten",
                str(Path(kitty_module.__file__).with_name(
                    "tree_navigation_kitten.py"
                )),
                "place-sidebar-left",
                "456",
                "20",
            ),
        ))

    def test_embedded_sync_only_creates_missing_tab_panes(self) -> None:
        remote = RecordingRemote()
        snapshot = [{
            "id": 3,
            "tabs": [
                {"id": 10, "windows": [{"id": 100, "user_vars": {}}]},
                {"id": 20, "windows": [
                    {"id": 200, "user_vars": {}},
                    {"id": 290, "user_vars": {
                        "ktt_sidebar": "1",
                        "ktt_orientation": "horizontal",
                    }},
                ]},
            ],
        }]

        created = remote.sync_embedded_panes(
            snapshot, 3, "tapered", "terminal", 12,
            "/tmp/ktt-shared.sock",
        )

        self.assertEqual(created, [456])
        launch_calls = [call for call in remote.calls if call[0] == "launch"]
        self.assertEqual(len(launch_calls), 1)
        self.assertIn("window_id:100", launch_calls[0][1])
        self.assertIn("--bias=12", launch_calls[0][1])
        self.assertIn("--shared-socket", launch_calls[0][1])
        self.assertIn("/tmp/ktt-shared.sock", launch_calls[0][1])

    def test_unembed_closes_embedded_panes_in_both_orientations(self) -> None:
        remote = RecordingRemote()
        snapshot = [{
            "id": 3,
            "tabs": [{"id": 10, "windows": [
                {"id": 100, "user_vars": {}},
                {"id": 190, "user_vars": {"ktt_sidebar": "1"}},
                {"id": 191, "user_vars": {
                    "ktt_sidebar": "1",
                    "ktt_orientation": "horizontal",
                }},
            ]}],
        }]

        self.assertEqual(remote.close_embedded_panes(snapshot, 3), [190, 191])
        self.assertEqual(remote.calls, [
            ("close-window", ("--match", "id:190")),
            ("close-window", ("--match", "id:191")),
        ])

    def test_vertical_sync_reuses_existing_vertical_pane(self) -> None:
        remote = RecordingRemote()
        snapshot = [{
            "id": 3,
            "tabs": [{"id": 10, "windows": [
                {"id": 100, "user_vars": {}},
                {"id": 190, "user_vars": {
                    "ktt_sidebar": "1",
                    "ktt_orientation": "vertical",
                }},
            ]}],
        }]

        created = remote.sync_embedded_panes(
            snapshot, 3, pane_percent=20, orientation="vertical"
        )

        self.assertEqual(created, [])
        self.assertEqual(remote.calls, [])

    def test_vertical_sync_splits_the_active_content_window(self) -> None:
        remote = RecordingRemote()
        snapshot = [{
            "id": 3,
            "tabs": [{"id": 10, "windows": [
                {"id": 100, "is_active": False, "user_vars": {
                    "ktt_cockpit_role": "agent",
                }},
                {"id": 101, "is_active": True, "user_vars": {}},
            ]}],
        }]

        remote.sync_embedded_panes(
            snapshot, 3, pane_percent=20, orientation="vertical"
        )

        self.assertIn("window_id:101", remote.calls[0][1])
        self.assertEqual(remote.calls[1], (
            "action",
            (
                "--match",
                "id:101",
                "kitten",
                str(Path(kitty_module.__file__).with_name(
                    "tree_navigation_kitten.py"
                )),
                "place-sidebar-left",
                "456",
                "20",
            ),
        ))

    def test_sync_closes_sidebar_when_it_is_the_tabs_only_survivor(self) -> None:
        remote = RecordingRemote()
        snapshot = [{
            "id": 3,
            "tabs": [{"id": 10, "windows": [{
                "id": 190,
                "is_active": True,
                "user_vars": {
                    "ktt_sidebar": "1",
                    "ktt_orientation": "vertical",
                },
            }]}],
        }]

        created = remote.sync_embedded_panes(
            snapshot, 3, pane_percent=20, orientation="vertical"
        )

        self.assertEqual(created, [])
        self.assertEqual(remote.calls, [
            ("close-window", ("--match", "id:190")),
        ])

    def test_sidebar_refresh_launches_with_background_before_close(self) -> None:
        remote = RecordingRemote()
        replacement = remote.replace_sidebar(123, 3)
        self.assertEqual(replacement, 456)
        subcommand, arguments = remote.calls[0]
        self.assertEqual(subcommand, "launch")
        self.assertIn("--color", arguments)
        self.assertEqual(arguments[arguments.index("--color") + 1], "background=#000000")
        self.assertEqual(remote.calls[1], (
            "close-window",
            ("--match", "id:123"),
        ))


if __name__ == "__main__":
    unittest.main()
