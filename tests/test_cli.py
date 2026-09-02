from contextlib import redirect_stderr
from io import StringIO
import unittest
from unittest.mock import patch

from ktt.cli import _parser, _validate_link, main
from ktt.native_tabs import NativeVerticalTabsUnsupported


def window(window_id, parent=None):
    user_vars = {}
    if parent is not None:
        user_vars["ktt_parent_window_id"] = str(parent)
    return {"id": window_id, "is_active": True, "user_vars": user_vars}


class CliTests(unittest.TestCase):
    def test_legacy_launch_command_is_removed(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            _parser().parse_args(["launch"])

    @patch("ktt.cli.RemoteControl")
    def test_bare_command_enables_native_tabs(self, remote_class) -> None:
        with patch.dict("os.environ", {"KITTY_WINDOW_ID": "100"}, clear=True):
            self.assertEqual(main([]), 0)
        remote_class.return_value.enable_native_vertical_tabs.assert_called_once_with(100)

    @patch("ktt.cli.RemoteControl")
    def test_bare_command_requires_kitty(self, remote_class) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            redirect_stderr(StringIO()) as stderr,
        ):
            self.assertEqual(main([]), 1)
        self.assertIn("must run inside Kitty", stderr.getvalue())
        remote_class.return_value.enable_native_vertical_tabs.assert_not_called()

    @patch("ktt.cli.RemoteControl")
    def test_old_kitty_reports_native_requirement(self, remote_class) -> None:
        remote_class.return_value.enable_native_vertical_tabs.side_effect = (
            NativeVerticalTabsUnsupported((0, 47, 4))
        )
        with (
            patch.dict("os.environ", {"KITTY_WINDOW_ID": "100"}, clear=True),
            redirect_stderr(StringIO()) as stderr,
        ):
            self.assertEqual(main([]), 1)
        self.assertIn("require Kitty 0.48.0", stderr.getvalue())

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
