from pathlib import Path
import tempfile
import time
import unittest

from ktt.daemon import (
    SharedSnapshot,
    SharedSnapshotClient,
    SnapshotServer,
    daemon_arguments,
    daemon_socket_path,
)
from ktt.model import TabRecord
from ktt.repository import RepositoryLocation


class SharedSnapshotTests(unittest.TestCase):
    def test_socket_path_is_scoped_to_kitty_and_os_window(self) -> None:
        self.assertEqual(
            daemon_socket_path(7, runtime_dir="/run/user/test", kitty_pid=42),
            Path("/run/user/test/ktt/kitty-42-os-7.daemon.sock"),
        )

    def test_snapshot_round_trip_preserves_records_and_sidebar_map(self) -> None:
        snapshot = SharedSnapshot(
            sequence=3,
            os_window_id=7,
            records=(TabRecord(1, 7, "main", (10,), repository="repo"),),
            folded_tab_ids=(1,),
            focused_window_ids=(90,),
            sidebar_windows={1: 90},
            repository_path="/repo",
            repository_lines=("header", "branch"),
            repository_location=RepositoryLocation(
                worktree="feature", relative_path="src"
            ),
        )
        self.assertEqual(SharedSnapshot.from_bytes(snapshot.to_bytes()), snapshot)

    def test_client_receives_latest_daemon_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as runtime:
            path = daemon_socket_path(7, runtime_dir=runtime, kitty_pid=42)
            server = SnapshotServer(path)
            server.open()
            client = SharedSnapshotClient(
                7, runtime_dir=runtime, kitty_pid=42
            )
            try:
                self.assertIsNone(client.take_latest())
                server.accept_pending()
                expected = SharedSnapshot(
                    sequence=1,
                    os_window_id=7,
                    records=(),
                    folded_tab_ids=(),
                    focused_window_ids=(),
                    sidebar_windows={},
                )
                server.broadcast(expected)
                actual = None
                deadline = time.monotonic() + 0.5
                while actual is None and time.monotonic() < deadline:
                    actual = client.take_latest()
                    time.sleep(0.005)
                self.assertEqual(actual, expected)
            finally:
                client.close()
                server.close()

    def test_second_server_cannot_replace_a_live_daemon_socket(self) -> None:
        with tempfile.TemporaryDirectory() as runtime:
            path = daemon_socket_path(7, runtime_dir=runtime, kitty_pid=42)
            server = SnapshotServer(path)
            server.open()
            try:
                with self.assertRaisesRegex(RuntimeError, "already active"):
                    SnapshotServer(path).open()
            finally:
                server.close()

    def test_daemon_command_keeps_global_options_before_subcommand(self) -> None:
        arguments = daemon_arguments(
            7,
            to="unix:/tmp/kitty",
            poll_interval=0.5,
            edge_style="rounded",
            repository_palette="quiet",
            pane_percent=12,
            orientation="vertical",
        )
        daemon_at = arguments.index("daemon")
        self.assertLess(arguments.index("--target-os-window"), daemon_at)
        self.assertLess(arguments.index("--orientation"), daemon_at)
        self.assertEqual(
            arguments[arguments.index("--orientation") + 1], "vertical"
        )
        self.assertEqual(arguments[-2:], ["--pane-percent", "12"])


if __name__ == "__main__":
    unittest.main()
