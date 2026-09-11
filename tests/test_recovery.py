from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from ktt.recovery import (
    RecoverySnapshotter,
    preserve_previous_snapshot,
    prune_autosave_history,
)
from ktt.session import (
    SessionManifestError,
    autosave_session_path,
    capture_session,
    previous_recovery_path,
    read_manifest,
    write_manifest,
)


def snapshot(*titles: str) -> list[dict[str, object]]:
    return [
        {
            "id": 91,
            "is_focused": True,
            "tabs": [
                {
                    "id": 100 + index,
                    "title": title,
                    "is_active": index == len(titles),
                    "is_focused": index == len(titles),
                    "windows": [
                        {
                            "id": 1000 + index,
                            "title": title,
                            "cwd": f"/work/{title}",
                            "is_active": True,
                            "is_focused": True,
                            "user_vars": {},
                            "foreground_processes": [
                                {
                                    "pid": 10_000 + index,
                                    "cwd": f"/work/{title}",
                                    "cmdline": ["codex"],
                                }
                            ],
                        }
                    ],
                }
                for index, title in enumerate(titles, start=1)
            ],
        }
    ]


class FakeRemote:
    def __init__(self, *snapshots: list[dict[str, object]]) -> None:
        self.snapshots = iter(snapshots)

    def snapshot(self) -> list[dict[str, object]]:
        return next(self.snapshots)


class RecoverySnapshotTests(unittest.TestCase):
    def test_new_process_preserves_the_pre_crash_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "recovery.json"
            path.write_text("pre-crash\n")

            preserve_previous_snapshot(path)

            self.assertFalse(path.exists())
            self.assertEqual(
                previous_recovery_path(path).read_text(),
                "pre-crash\n",
            )

    def test_new_snapshot_drops_a_tab_closed_since_the_previous_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "recovery.json"
            snapshotter = RecoverySnapshotter(
                FakeRemote(  # type: ignore[arg-type]
                    snapshot("kept", "closed"), snapshot("kept")
                ),
                path=path,
                session_resolver=lambda kind, pid, cwd, argv: f"{kind}-{pid}",
            )

            snapshotter.snapshot_once()
            self.assertEqual(read_manifest(path).tab_count, 2)
            snapshotter.snapshot_once()

            recovered = read_manifest(path)
            self.assertEqual(recovered.tab_count, 1)
            self.assertEqual(recovered.os_windows[0].tabs[0].title, "kept")

    def test_snapshotter_updates_one_owned_hourly_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "recovery.json"
            snapshotter = RecoverySnapshotter(
                FakeRemote(  # type: ignore[arg-type]
                    snapshot("kept", "closed"), snapshot("kept")
                ),
                path=path,
                session_resolver=lambda kind, pid, cwd, argv: f"{kind}-{pid}",
            )

            snapshotter.snapshot_once()
            archive = snapshotter._archive_path
            self.assertIsNotNone(archive)
            assert archive is not None
            snapshotter.snapshot_once()

            self.assertEqual(read_manifest(archive).tab_count, 1)

    def test_new_process_does_not_overwrite_an_existing_hour_bucket(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "recovery.json"
            first = RecoverySnapshotter(
                FakeRemote(snapshot("useful", "also-useful")),  # type: ignore[arg-type]
                path=path,
                session_resolver=lambda kind, pid, cwd, argv: f"{kind}-{pid}",
            )
            first.snapshot_once()
            archive = first._archive_path
            self.assertIsNotNone(archive)
            assert archive is not None

            after_reboot = RecoverySnapshotter(
                FakeRemote(snapshot("blank")),  # type: ignore[arg-type]
                path=path,
                session_resolver=lambda kind, pid, cwd, argv: f"{kind}-{pid}",
            )
            after_reboot.snapshot_once()

            self.assertEqual(read_manifest(archive).tab_count, 2)

    def test_pruning_keeps_eight_days_and_removes_older_archives(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "recovery.json"
            now = datetime.now().astimezone()

            def write_archive(saved_at: datetime) -> Path:
                created_at = saved_at.isoformat(timespec="seconds")
                manifest = capture_session(
                    snapshot("kept"),
                    hostname="host",
                    created_at=created_at,
                    session_resolver=lambda kind, pid, cwd, argv: f"{kind}-{pid}",
                )
                archive = autosave_session_path(created_at, path)
                write_manifest(archive, manifest)
                return archive

            expired = write_archive(now - timedelta(days=9))
            retained = write_archive(now - timedelta(days=7))

            prune_autosave_history(path, now=now)

            self.assertFalse(expired.exists())
            self.assertTrue(retained.exists())

    def test_failed_refresh_preserves_the_last_good_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "recovery.json"
            snapshotter = RecoverySnapshotter(
                FakeRemote(snapshot("kept"), []),  # type: ignore[arg-type]
                path=path,
                session_resolver=lambda kind, pid, cwd, argv: f"{kind}-{pid}",
            )
            snapshotter.snapshot_once()
            before = path.read_bytes()

            with self.assertRaises(SessionManifestError):
                snapshotter.snapshot_once()

            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
