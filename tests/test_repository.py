import tempfile
import unittest
from pathlib import Path

from ktt.repository import (
    RepositoryMonitor,
    find_repository_root,
    parse_porcelain,
    repository_name,
)


class RepositoryTests(unittest.TestCase):
    def test_parses_branch_tracking_and_worktree_categories(self) -> None:
        status = parse_porcelain(
            "\n".join((
                "# branch.oid 0123456789abcdef",
                "# branch.head feature/status-panel",
                "# branch.ab +2 -1",
                "1 M. N... 100644 100644 100644 a b staged.py",
                "1 .M N... 100644 100644 100644 a b modified.py",
                "1 MM N... 100644 100644 100644 a b both.py",
                "u UU N... 100644 100644 100644 100644 a b c conflict.py",
                "? new.py",
            )),
            root=Path("/tmp/project"),
            directory=Path("/tmp/project/src"),
        )
        self.assertEqual(status.branch, "feature/status-panel")
        self.assertEqual((status.ahead, status.behind), (2, 1))
        self.assertEqual(status.changed, 5)
        self.assertEqual((status.staged, status.unstaged), (2, 2))
        self.assertEqual((status.untracked, status.conflicted), (1, 1))

    def test_discovers_a_repository_from_a_nested_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            nested = root / "src" / "feature"
            (root / ".git").mkdir(parents=True)
            nested.mkdir(parents=True)
            self.assertEqual(find_repository_root(nested), root)

    def test_linked_worktree_uses_the_parent_repository_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            parent = base / "project"
            child = base / "worktrees" / "feature"
            control = parent / ".git" / "worktrees" / "feature"
            control.mkdir(parents=True)
            (child / ".git").parent.mkdir(parents=True)
            (child / ".git").write_text(f"gitdir: {control}\n")
            self.assertEqual(repository_name(child), "project")

    def test_monitor_caches_until_its_refresh_deadline(self) -> None:
        monitor = RepositoryMonitor(interval=2.0)
        monitor.path = "/tmp/project"
        monitor.next_refresh = 12.0
        self.assertIsNone(monitor.update("/tmp/project", now=11.0))
        self.assertEqual(monitor.next_refresh, 12.0)


if __name__ == "__main__":
    unittest.main()
