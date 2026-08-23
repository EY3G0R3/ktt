from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import time
from typing import Any


@dataclass(frozen=True)
class RepositoryStatus:
    name: str
    directory: str
    branch: str
    changed: int = 0
    staged: int = 0
    unstaged: int = 0
    untracked: int = 0
    conflicted: int = 0
    ahead: int = 0
    behind: int = 0

    @property
    def clean(self) -> bool:
        return self.changed == 0


def active_window_cwd(os_window: dict[str, Any]) -> str | None:
    tabs = os_window.get("tabs") or []
    tab = next((item for item in tabs if item.get("is_active")), None)
    if tab is None:
        return None
    windows = tab.get("windows") or []
    history = tab.get("active_window_history") or []
    active_id = int(history[0]) if history else None
    window = next(
        (
            item
            for item in windows
            if active_id is not None and int(item["id"]) == active_id
        ),
        None,
    )
    window = window or next(
        (item for item in windows if item.get("is_focused") or item.get("is_active")),
        None,
    )
    window = window or (windows[0] if windows else None)
    if window is None:
        return None
    cwd = window.get("cwd")
    if cwd:
        return str(cwd)
    processes = window.get("foreground_processes") or []
    for process in reversed(processes):
        if process.get("cwd"):
            return str(process["cwd"])
    return None


def find_repository_root(path: Path) -> Path | None:
    try:
        path = path.resolve()
    except OSError:
        return None
    for directory in (path, *path.parents):
        control = directory / ".git"
        if control.is_dir() or control.is_file():
            return directory
    return None


def _linked_worktree_parent(root: Path) -> Path | None:
    control = root / ".git"
    try:
        contents = control.read_text().strip()
    except OSError:
        return None
    if not contents.startswith("gitdir:"):
        return None
    git_dir = Path(contents.removeprefix("gitdir:").strip())
    if not git_dir.is_absolute():
        git_dir = root / git_dir
    worktrees = git_dir.parent
    if worktrees.name != "worktrees":
        return None
    parent_control = worktrees.parent
    if parent_control.name == ".git":
        return parent_control.parent
    if parent_control.suffix == ".git":
        return parent_control.with_suffix("")
    return None


def repository_name(root: Path) -> str:
    parent = _linked_worktree_parent(root)
    return (parent or root).name or str(parent or root)


def display_path(path: Path) -> str:
    home = Path.home()
    try:
        relative = path.resolve().relative_to(home)
    except (OSError, ValueError):
        return str(path)
    return "~" if not relative.parts else f"~/{relative}"


def parse_porcelain(
    output: str,
    *,
    root: Path,
    directory: Path,
) -> RepositoryStatus:
    branch = "detached"
    oid = ""
    ahead = behind = changed = staged = unstaged = untracked = conflicted = 0
    for line in output.splitlines():
        if line.startswith("# branch.oid "):
            oid = line.removeprefix("# branch.oid ").strip()
        elif line.startswith("# branch.head "):
            value = line.removeprefix("# branch.head ").strip()
            branch = value if value != "(detached)" else f"detached@{oid[:7]}"
        elif line.startswith("# branch.ab "):
            fields = line.removeprefix("# branch.ab ").split()
            for field in fields:
                if field.startswith("+"):
                    ahead = int(field[1:])
                elif field.startswith("-"):
                    behind = int(field[1:])
        elif line.startswith(("1 ", "2 ")):
            fields = line.split(maxsplit=2)
            if len(fields) < 2:
                continue
            changed += 1
            staged += fields[1][0] != "."
            unstaged += fields[1][1] != "."
        elif line.startswith("u "):
            changed += 1
            conflicted += 1
        elif line.startswith("? "):
            changed += 1
            untracked += 1
    return RepositoryStatus(
        name=repository_name(root),
        directory=display_path(directory),
        branch=branch,
        changed=changed,
        staged=staged,
        unstaged=unstaged,
        untracked=untracked,
        conflicted=conflicted,
        ahead=ahead,
        behind=behind,
    )


def probe_repository(path: str, timeout: float = 0.75) -> RepositoryStatus | None:
    directory = Path(path)
    root = find_repository_root(directory)
    if root is None:
        return None
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    result = subprocess.run(
        [
            "git",
            "-C",
            str(directory),
            "status",
            "--porcelain=v2",
            "--branch",
            "--untracked-files=normal",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=environment,
    )
    if result.returncode:
        return None
    return parse_porcelain(result.stdout, root=root, directory=directory)


class RepositoryMonitor:
    def __init__(self, interval: float = 3.0, timeout: float = 0.75) -> None:
        self.interval = interval
        self.timeout = timeout
        self.path: str | None = None
        self.status: RepositoryStatus | None = None
        self.next_refresh = 0.0

    def update(
        self, path: str | None, now: float | None = None
    ) -> RepositoryStatus | None:
        current = time.monotonic() if now is None else now
        if path != self.path:
            self.path = path
            self.status = None
            self.next_refresh = 0.0
        if not path or current < self.next_refresh:
            return self.status
        self.next_refresh = current + self.interval
        try:
            self.status = probe_repository(path, self.timeout)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return self.status

    def invalidate(self) -> None:
        self.next_refresh = 0.0
