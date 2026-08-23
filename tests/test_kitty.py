from pathlib import Path
import unittest

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

    def test_preview_switches_tab_then_restores_sidebar_focus(self) -> None:
        remote = RecordingRemote()
        remote.preview_tab(12, 91)
        self.assertEqual(remote.calls, [
            ("focus-tab", ("--match", "id:12")),
            ("focus-window", ("--match", "id:91")),
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
