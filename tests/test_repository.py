import subprocess
import unittest
from unittest.mock import patch

from ktt.repository import (
    FancylogIdentityCache,
    FancylogMonitor,
    RepositoryLocation,
    RepositoryLocationCache,
    active_window_cwd,
    repository_name_from_status,
    resolve_repository_location,
)


class RepositoryTests(unittest.TestCase):
    def test_active_cwd_ignores_focused_embedded_sidebar(self) -> None:
        os_window = {
            "tabs": [{
                "is_active": True,
                "active_window_history": [90, 10],
                "windows": [
                    {"id": 10, "cwd": "/work/project", "user_vars": {}},
                    {
                        "id": 90,
                        "cwd": "/work/ktt",
                        "is_focused": True,
                        "user_vars": {"ktt_sidebar": "1"},
                    },
                ],
            }],
        }

        self.assertEqual(active_window_cwd(os_window), "/work/project")

    def test_active_cwd_prefers_the_foreground_agent_process(self) -> None:
        os_window = {
            "tabs": [{
                "is_active": True,
                "active_window_history": [10],
                "windows": [{
                    "id": 10,
                    "cwd": "/home/igor",
                    "foreground_processes": [
                        {
                            "cmdline": ["claude", "--continue"],
                            "cwd": "/work/squawk__worktrees/push-hirayama",
                        },
                        {
                            "cmdline": ["xclip"],
                            "cwd": "/",
                        },
                    ],
                    "user_vars": {},
                }],
            }],
        }

        self.assertEqual(
            active_window_cwd(os_window),
            "/work/squawk__worktrees/push-hirayama",
        )

    def test_repository_name_comes_from_fancylog_identity(self) -> None:
        self.assertEqual(
            repository_name_from_status(
                [" (quiver) ~/work/quiver__worktrees/feature  ◈ 2 unstaged "]
            ),
            "quiver",
        )

    @patch("ktt.repository.subprocess.run")
    def test_location_compacts_a_main_checkout_subdirectory(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            [], 0, "/home/me/src/ktt\n/home/me/src/ktt/.git\n", ""
        )

        self.assertEqual(
            resolve_repository_location("/home/me/src/ktt/build"),
            RepositoryLocation(relative_path="build/"),
        )

    @patch("ktt.repository.subprocess.run")
    def test_location_identifies_a_linked_worktree_and_subdirectory(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            [],
            0,
            (
                "/home/me/work/quiver__worktrees/feature\n"
                "/home/me/work/quiver/.git\n"
            ),
            "",
        )

        self.assertEqual(
            resolve_repository_location(
                "/home/me/work/quiver__worktrees/feature/build"
            ),
            RepositoryLocation(worktree="feature", relative_path="build/"),
        )

    @patch("ktt.repository.resolve_repository_location")
    def test_location_cache_resolves_each_directory_once(self, resolve) -> None:
        resolve.return_value = RepositoryLocation(relative_path="build/")
        cache = RepositoryLocationCache()

        self.assertEqual(
            cache.update("/work/project/build"),
            RepositoryLocation(relative_path="build/"),
        )
        cache.update("/work/project/build")

        resolve.assert_called_once_with("/work/project/build", 0.25)
        self.assertEqual(
            repository_name_from_status([" (yadm) ~  ✓ working tree clean "]),
            "yadm",
        )

    def test_identity_cache_resolves_each_directory_only_once(self) -> None:
        cache = FancylogIdentityCache(workers=2)
        try:
            with patch.object(
                cache,
                "_resolve",
                side_effect=lambda path: path.rsplit("/", 1)[-1],
            ) as resolve:
                self.assertEqual(cache.update(["/work/quiver", "/home/yadm"]), {})
                for future in list(cache.pending.values()):
                    future.result(timeout=1.0)
                self.assertEqual(
                    cache.update(["/work/quiver", "/home/yadm"]),
                    {"/work/quiver": "quiver", "/home/yadm": "yadm"},
                )
                cache.update(["/work/quiver", "/home/yadm"])
                self.assertEqual(resolve.call_count, 2)
        finally:
            cache.close()

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
        self.assertEqual(command[command.index("--width") + 1], "256")
        self.assertEqual(command[command.index("--height") + 1], "2")
        self.assertEqual(
            command[command.index("--header-palette") + 1], "amber"
        )
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
