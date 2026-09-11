import subprocess
import unittest
from unittest.mock import patch

from ktt.model import TabRecord
from ktt.repository import (
    repository_summary_parts,
    AsyncFancylogMonitor,
    FancylogIdentityCache,
    FancylogMonitor,
    RepositoryLocation,
    RepositoryLocationCache,
    RepositoryContext,
    infer_repository_context,
    repository_name_from_status,
    resolve_repository_location,
    resolve_repository_context,
    with_repository_worktrees,
)


class RepositoryTests(unittest.TestCase):
    def test_context_is_inferred_from_a_workmux_worktree_path(self) -> None:
        self.assertEqual(
            infer_repository_context(
                "/home/me/work/quiver__worktrees/fixie-on-outpost/packages/app"
            ),
            RepositoryContext(
                "quiver",
                RepositoryLocation(
                    worktree="fixie-on-outpost",
                    relative_path="packages/app/",
                ),
                inferred=True,
            ),
        )

    def test_context_is_inferred_from_a_main_source_checkout(self) -> None:
        self.assertEqual(
            infer_repository_context("/home/me/src/ktt/tests"),
            RepositoryContext(
                "ktt",
                RepositoryLocation(relative_path="tests/"),
                inferred=True,
            ),
        )

    def test_context_is_not_inferred_from_an_arbitrary_directory(self) -> None:
        self.assertIsNone(infer_repository_context("/home/me/Documents/notes"))

    def test_repository_name_comes_from_fancylog_identity(self) -> None:
        self.assertEqual(
            repository_name_from_status(
                [" (quiver) ~/work/quiver__worktrees/feature  ◈ 2 unstaged "]
            ),
            "quiver",
        )
        self.assertEqual(
            repository_name_from_status(
                [" /quiver/ ~/work/quiver__worktrees/feature  ◈ 2 unstaged "]
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

    @patch("ktt.repository.subprocess.run")
    def test_context_identifies_repository_and_worktree(self, run) -> None:
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
            resolve_repository_context(
                "/home/me/work/quiver__worktrees/feature/build"
            ),
            RepositoryContext(
                "quiver",
                RepositoryLocation(worktree="feature", relative_path="build/"),
            ),
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
                side_effect=lambda path: (
                    path.rsplit("/", 1)[-1],
                    RepositoryLocation(
                        worktree=path.rsplit("/", 1)[-1]
                    ),
                ),
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
                self.assertEqual(cache.worktrees(), {
                    "/work/quiver": "quiver",
                    "/home/yadm": "yadm",
                })
        finally:
            cache.close()

    def test_identity_cache_retries_failed_lookup_after_backoff(self) -> None:
        cache = FancylogIdentityCache(workers=1, retry_interval=3.0)
        try:
            with patch.object(
                cache,
                "_resolve",
                side_effect=[
                    (None, None),
                    (
                        "convex-backend",
                        RepositoryLocation(worktree="push-context"),
                    ),
                ],
            ) as resolve:
                self.assertEqual(cache.update(["/work/convex"], now=10.0), {})
                cache.pending["/work/convex"].result(timeout=1.0)
                self.assertEqual(cache.update(["/work/convex"], now=10.1), {})
                self.assertEqual(cache.update(["/work/convex"], now=13.0), {})
                self.assertEqual(resolve.call_count, 1)

                self.assertEqual(cache.update(["/work/convex"], now=13.1), {})
                cache.pending["/work/convex"].result(timeout=1.0)
                self.assertEqual(
                    cache.update(["/work/convex"], now=13.2),
                    {"/work/convex": "convex-backend"},
                )
                self.assertEqual(resolve.call_count, 2)
                self.assertEqual(
                    cache.worktrees(), {"/work/convex": "push-context"}
                )
        finally:
            cache.close()

    def test_cached_worktrees_enrich_every_record(self) -> None:
        records = [
            TabRecord(1, 1, "one", (10,), cwd="/work/one"),
            TabRecord(2, 1, "two", (20,), cwd="/work/two"),
        ]
        enriched = with_repository_worktrees(
            records, {"/work/one": "feature"}
        )

        self.assertEqual(enriched[0].repository_worktree, "feature")
        self.assertIsNone(enriched[1].repository_worktree)

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

    def test_async_monitor_refreshes_without_blocking_the_caller(self) -> None:
        monitor = AsyncFancylogMonitor(interval=3.0)
        try:
            with patch(
                "ktt.repository.fancylog_status_lines",
                return_value=["header", "branch"],
            ) as status:
                self.assertEqual(
                    monitor.update("/work/project", 40, 2, now=10.0), []
                )
                self.assertTrue(monitor.needs_refresh(now=10.1))
                assert monitor.pending is not None
                monitor.pending.result(timeout=1.0)
                self.assertEqual(
                    monitor.update("/work/project", 40, 2, now=10.1),
                    ["header", "branch"],
                )
                self.assertFalse(monitor.needs_refresh(now=12.9))
                status.assert_called_once()
        finally:
            monitor.close()


if __name__ == "__main__":
    unittest.main()


class SummaryPartsTests(unittest.TestCase):
    def test_worktree_header_drops_the_padded_path_from_the_state(self) -> None:
        identity, branch, state = repository_summary_parts(
            ["/ktt/    ~/src/ktt" + " " * 120 + "◈ 1 unstaged", " main"]
        )
        self.assertEqual(identity, "/ktt/")
        self.assertEqual(branch, "main")
        self.assertEqual(state, "◈ 1 unstaged")

    def test_two_space_separators_inside_the_state_survive(self) -> None:
        _, _, state = repository_summary_parts(
            [" (quiver) /path  ◈ 1 unstaged  ·  2 untracked ", "  topic "]
        )
        self.assertEqual(state, "◈ 1 unstaged  ·  2 untracked")
