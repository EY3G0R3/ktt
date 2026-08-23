import subprocess
import unittest
from unittest.mock import patch

from ktt.repository import FancylogMonitor


class RepositoryTests(unittest.TestCase):
    @patch("ktt.repository.subprocess.run")
    def test_monitor_requests_bounded_status_only_output(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            [], 0, "header row\nbranch row\n", ""
        )
        monitor = FancylogMonitor(executable="/usr/bin/fancylog")

        lines = monitor.update("/work/project", 48, 2, now=10.0)

        self.assertEqual(lines, ["header row", "branch row"])
        command = run.call_args.args[0]
        self.assertEqual(command[0], "/usr/bin/fancylog")
        self.assertIn("--status-only", command)
        self.assertEqual(command[command.index("--width") + 1], "48")
        self.assertEqual(command[command.index("--height") + 1], "2")
        self.assertEqual(command[-1], "/work/project")
        self.assertEqual(run.call_args.kwargs["timeout"], 0.75)

    @patch("ktt.repository.subprocess.run")
    def test_monitor_caches_output_until_refresh_deadline(self, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, "status\n", "")
        monitor = FancylogMonitor(interval=3.0)
        self.assertEqual(monitor.update("/work/project", 40, 1, now=10.0), ["status"])
        self.assertEqual(monitor.update("/work/project", 40, 1, now=12.9), ["status"])
        self.assertEqual(run.call_count, 1)

    @patch("ktt.repository.subprocess.run")
    def test_path_or_geometry_change_refreshes_immediately(self, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, "status\n", "")
        monitor = FancylogMonitor(interval=3.0)
        monitor.update("/work/one", 40, 1, now=10.0)
        monitor.update("/work/two", 40, 2, now=10.1)
        self.assertEqual(run.call_count, 2)

    @patch("ktt.repository.subprocess.run")
    def test_failed_refresh_keeps_the_last_good_panel(self, run) -> None:
        run.side_effect = [
            subprocess.CompletedProcess([], 0, "status\n", ""),
            subprocess.TimeoutExpired(["fancylog"], 0.75),
        ]
        monitor = FancylogMonitor(interval=3.0)
        monitor.update("/work/project", 40, 1, now=10.0)
        self.assertEqual(
            monitor.update("/work/project", 40, 1, now=13.0),
            ["status"],
        )


if __name__ == "__main__":
    unittest.main()
