from io import StringIO
import unittest
from unittest.mock import MagicMock, patch

from ktt.cli import (
    _configure_current_sidebar,
    _parser,
    _validate_link,
    main,
)
from ktt.kitty import KittyError
from ktt.native_tabs import NativeVerticalTabsUnsupported


def window(window_id, parent=None):
    user_vars = {}
    if parent is not None:
        user_vars["ktt_parent_window_id"] = str(parent)
    return {"id": window_id, "is_active": True, "user_vars": user_vars}


class LinkValidationTests(unittest.TestCase):
    def test_default_recovery_poll_is_one_second(self) -> None:
        self.assertEqual(_parser().parse_args([]).poll_interval, 1.0)

    def test_default_orientation_remains_vertical(self) -> None:
        self.assertEqual(_parser().parse_args([]).orientation, "vertical")

    def test_horizontal_orientation_is_opt_in(self) -> None:
        self.assertEqual(
            _parser().parse_args(["--orientation", "horizontal"]).orientation,
            "horizontal",
        )

    def test_embedded_pane_defaults_to_ten_percent(self) -> None:
        args = _parser().parse_args([
            "--orientation", "horizontal", "launch-pane",
        ])
        self.assertEqual(args.pane_percent, 10)

    def test_shared_embed_defers_default_to_selected_orientation(self) -> None:
        args = _parser().parse_args([
            "--orientation", "horizontal", "embed",
        ])
        self.assertIsNone(args.pane_percent)

    def test_changed_files_default_to_bottom_free_space(self) -> None:
        args = _parser().parse_args(["embed"])
        self.assertEqual(args.changed_files_placement, "bottom")

    def test_tui_start_reapplies_sidebar_configuration(self) -> None:
        remote = MagicMock()
        with patch.dict("os.environ", {"KITTY_WINDOW_ID": "91"}):
            _configure_current_sidebar(remote, 3, "vertical", False)
        remote.configure_sidebar.assert_called_once_with(
            91, 3, "vertical", False
        )

    def test_tui_start_without_kitty_window_skips_configuration(self) -> None:
        remote = MagicMock()
        with patch.dict("os.environ", {}, clear=True):
            _configure_current_sidebar(remote, 3, "vertical", False)
        remote.configure_sidebar.assert_not_called()

    @patch("ktt.cli.run_tui")
    @patch("ktt.cli.RemoteControl")
    def test_bare_command_launches_sidebar_for_current_os_window(
        self, remote_class, run_tui
    ) -> None:
        remote = remote_class.return_value
        remote.enable_native_vertical_tabs.side_effect = (
            NativeVerticalTabsUnsupported((0, 47, 4))
        )
        remote.snapshot.return_value = [{
            "id": 7,
            "tabs": [
                {"id": 10, "windows": [window(100)]},
                {"id": 20, "windows": [window(200)]},
            ],
        }]
        remote.launch_sidebar.return_value = 900
        error_output = StringIO()
        with (
            patch.dict("os.environ", {"KITTY_WINDOW_ID": "100"}),
            patch("sys.stderr", error_output),
        ):
            self.assertEqual(main([]), 0)
        remote.launch_sidebar.assert_called_once_with(
            7, "tapered", "amber", "vertical", "bottom"
        )
        self.assertIn("running 0.47.4", error_output.getvalue())
        self.assertIn("opening the legacy sidebar", error_output.getvalue())
        run_tui.assert_not_called()

    @patch("ktt.cli.run_tui")
    @patch("ktt.cli.RemoteControl")
    def test_bare_command_uses_native_vertical_tabs_when_supported(
        self, remote_class, run_tui
    ) -> None:
        remote = remote_class.return_value
        remote.snapshot.return_value = [{
            "id": 7,
            "tabs": [{"id": 10, "windows": [window(100)]}],
        }]
        with patch.dict("os.environ", {"KITTY_WINDOW_ID": "100"}):
            self.assertEqual(main([]), 0)
        remote.enable_native_vertical_tabs.assert_called_once_with(
            100, strict=False
        )
        remote.launch_sidebar.assert_not_called()
        run_tui.assert_not_called()

    @patch("ktt.cli.RemoteControl")
    def test_native_command_directs_old_kitty_to_legacy_sidebar(
        self, remote_class
    ) -> None:
        remote = remote_class.return_value
        remote.enable_native_vertical_tabs.side_effect = (
            NativeVerticalTabsUnsupported((0, 47, 4))
        )
        error_output = StringIO()
        with (
            patch.dict("os.environ", {"KITTY_WINDOW_ID": "100"}),
            patch("sys.stderr", error_output),
        ):
            self.assertEqual(main(["native"]), 1)
        remote.enable_native_vertical_tabs.assert_called_once_with(
            100, strict=True
        )
        self.assertIn("running 0.47.4", error_output.getvalue())
        self.assertIn("ktt launch", error_output.getvalue())

    @patch("ktt.cli.RemoteControl")
    def test_bare_command_falls_back_after_other_native_failures(
        self, remote_class
    ) -> None:
        remote = remote_class.return_value
        remote.snapshot.return_value = [{
            "id": 7,
            "tabs": [{"id": 10, "windows": [window(100)]}],
        }]
        remote.enable_native_vertical_tabs.side_effect = KittyError("denied")
        remote.launch_sidebar.return_value = 900

        error_output = StringIO()
        with (
            patch.dict("os.environ", {"KITTY_WINDOW_ID": "100"}),
            patch("sys.stderr", error_output),
        ):
            self.assertEqual(main([]), 0)

        remote.launch_sidebar.assert_called_once_with(
            7, "tapered", "amber", "vertical", "bottom"
        )
        self.assertIn("denied", error_output.getvalue())
        self.assertIn("opening the legacy sidebar", error_output.getvalue())

    @patch("ktt.cli.RemoteControl")
    def test_explicit_native_does_not_mask_other_failures(
        self, remote_class
    ) -> None:
        remote = remote_class.return_value
        remote.enable_native_vertical_tabs.side_effect = KittyError("denied")

        output = StringIO()
        with (
            patch.dict("os.environ", {"KITTY_WINDOW_ID": "100"}),
            patch("sys.stdout", output),
        ):
            self.assertEqual(main(["native"]), 1)

        remote.launch_sidebar.assert_not_called()
        self.assertNotIn("enabled Kitty", output.getvalue())

    @patch("ktt.cli.run_tui")
    @patch("ktt.cli.RemoteControl")
    def test_bare_horizontal_command_uses_legacy_sidebar_on_new_kitty(
        self, remote_class, run_tui
    ) -> None:
        remote = remote_class.return_value
        remote.snapshot.return_value = [{
            "id": 7,
            "tabs": [{"id": 10, "windows": [window(100)]}],
        }]
        remote.launch_sidebar.return_value = 900

        with patch.dict("os.environ", {"KITTY_WINDOW_ID": "100"}):
            self.assertEqual(main(["--orientation", "horizontal"]), 0)

        remote.enable_native_vertical_tabs.assert_not_called()
        remote.launch_sidebar.assert_called_once_with(
            7, "tapered", "amber", "horizontal", "bottom"
        )
        run_tui.assert_not_called()

    @patch("ktt.cli.start_daemon", return_value=456)
    @patch("ktt.cli.stop_daemon")
    @patch("ktt.cli.RemoteControl")
    def test_embed_replaces_existing_panes_and_starts_shared_daemon(
        self, remote_class, stop_daemon, start_daemon
    ) -> None:
        remote = remote_class.return_value
        snapshot = [{
            "id": 7,
            "tabs": [{"id": 10, "windows": [window(100)]}],
        }]
        remote.snapshot.return_value = snapshot
        remote.to = "unix:/tmp/kitty"
        with patch.dict("os.environ", {"KITTY_WINDOW_ID": "100"}):
            self.assertEqual(main([
                "--orientation", "horizontal", "embed", "--pane-percent", "12",
            ]), 0)

        stop_daemon.assert_called_once_with(7)
        self.assertEqual(remote.snapshot.call_count, 2)
        remote.close_embedded_panes.assert_called_once_with(snapshot, 7)
        start_daemon.assert_called_once_with(
            7,
            to="unix:/tmp/kitty",
            poll_interval=1.0,
            edge_style="tapered",
            repository_palette="amber",
            changed_files_placement="bottom",
            pane_percent=12,
            orientation="horizontal",
        )

    @patch("ktt.cli.start_daemon", return_value=456)
    @patch("ktt.cli.stop_daemon")
    @patch("ktt.cli.RemoteControl")
    def test_vertical_embed_defaults_to_twenty_percent(
        self, remote_class, _stop_daemon, start_daemon
    ) -> None:
        remote = remote_class.return_value
        remote.snapshot.return_value = [{
            "id": 7,
            "tabs": [{"id": 10, "windows": [window(100)]}],
        }]
        with patch.dict("os.environ", {"KITTY_WINDOW_ID": "100"}):
            self.assertEqual(main(["--orientation", "vertical", "embed"]), 0)

        self.assertEqual(start_daemon.call_args.kwargs["pane_percent"], 20)
        self.assertEqual(start_daemon.call_args.kwargs["orientation"], "vertical")

    def test_rejects_a_new_cycle(self) -> None:
        snapshot = [{
            "id": 1,
            "tabs": [
                {"id": 10, "title": "root", "windows": [window(100)]},
                {"id": 20, "title": "child", "windows": [window(200, 100)]},
                {"id": 30, "title": "grandchild", "windows": [window(300, 200)]},
            ],
        }]
        with self.assertRaisesRegex(ValueError, "cycle"):
            _validate_link(snapshot, 100, 300)

    def test_accepts_a_normal_link(self) -> None:
        snapshot = [{
            "id": 1,
            "tabs": [
                {"id": 10, "title": "root", "windows": [window(100)]},
                {"id": 20, "title": "child", "windows": [window(200)]},
            ],
        }]
        _validate_link(snapshot, 200, 100)


if __name__ == "__main__":
    unittest.main()
