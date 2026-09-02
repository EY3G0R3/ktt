from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Iterable

from .model import TabRecord


REPOSITORY_PALETTES = (
    "surf", "amber", "vivid", "quiet", "graphite", "terminal", "dracula",
)
DEFAULT_REPOSITORY_PALETTE = "amber"
MAX_REPOSITORY_LINES = 8
MAX_BOTTOM_REPOSITORY_LINES = 13
IDENTITY_WIDTH = 256
MINIMUM_STATUS_SOURCE_WIDTH = 256
REPOSITORY_IDENTITY = re.compile(
    r"^\s*(?:\((?P<parenthesized>[^)]+)\)|/(?P<slashed>[^/]+)/)"
)
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


@dataclass(frozen=True)
class RepositoryLocation:
    worktree: str | None = None
    relative_path: str | None = None


def repository_summary_parts(
    lines: Iterable[str],
) -> tuple[str, str, str]:
    values = list(lines)
    if not values:
        return "", "", ""
    header = ANSI_ESCAPE.sub(
        "", values[-2] if len(values) > 1 else values[-1]
    ).strip()
    branch = (
        ANSI_ESCAPE.sub("", values[-1]).strip()
        if len(values) > 1
        else ""
    )
    header_parts = re.split(r"\s{2,}", header, maxsplit=1)
    identity = header_parts[0]
    state = header_parts[1].strip() if len(header_parts) > 1 else ""
    if state == "✓ working tree clean":
        state = "✓ clean"
    return identity, branch, state


def resolve_repository_location(
    path: str, timeout: float = 0.25
) -> RepositoryLocation | None:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                path,
                "rev-parse",
                "--path-format=absolute",
                "--show-toplevel",
                "--git-common-dir",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    values = result.stdout.rstrip("\n").splitlines()
    if result.returncode != 0 or len(values) != 2:
        return None
    root = Path(values[0]).resolve()
    common_directory = Path(values[1]).resolve()
    try:
        relative = Path(path).resolve().relative_to(root)
    except ValueError:
        return None
    linked_worktree = common_directory != (root / ".git").resolve()
    return RepositoryLocation(
        worktree=root.name if linked_worktree else None,
        relative_path=None if str(relative) == "." else f"{relative}/",
    )


class RepositoryLocationCache:
    def __init__(self, timeout: float = 0.25) -> None:
        self.timeout = timeout
        self.locations: dict[str, RepositoryLocation | None] = {}

    def update(self, path: str | None) -> RepositoryLocation | None:
        if not path:
            return None
        if path not in self.locations:
            self.locations[path] = resolve_repository_location(
                path, self.timeout
            )
        return self.locations[path]


def fancylog_status_lines(
    executable: str,
    path: str,
    width: int,
    max_lines: int,
    palette: str,
    timeout: float,
    *,
    color: str = "always",
) -> list[str] | None:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        result = subprocess.run(
            [
                executable,
                "--status-only",
                "--width",
                str(width),
                "--height",
                str(max_lines),
                "--color",
                color,
                "--header-palette",
                palette,
                path,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.rstrip("\n").splitlines()[:max_lines]


def repository_name_from_status(lines: list[str] | None) -> str | None:
    if not lines:
        return None
    match = REPOSITORY_IDENTITY.match(lines[-1])
    if match is None:
        return None
    return match.group("parenthesized") or match.group("slashed")


class FancylogMonitor:
    def __init__(
        self,
        interval: float = 3.0,
        timeout: float = 0.75,
        executable: str = "fancylog",
        palette: str = DEFAULT_REPOSITORY_PALETTE,
    ) -> None:
        self.interval = interval
        self.timeout = timeout
        self.executable = executable
        self.palette = palette
        self.key: tuple[str, int, int] | None = None
        self.lines: list[str] = []
        self.next_refresh = 0.0

    def update(
        self,
        path: str | None,
        width: int,
        max_lines: int,
        now: float | None = None,
    ) -> list[str]:
        if not path or width <= 0 or max_lines <= 0:
            return []
        current = time.monotonic() if now is None else now
        key = (path, width, max_lines)
        if key != self.key:
            self.key = key
            self.lines = []
            self.next_refresh = 0.0
        if current < self.next_refresh:
            return self.lines
        self.next_refresh = current + self.interval
        lines = fancylog_status_lines(
            self.executable,
            path,
            max(MINIMUM_STATUS_SOURCE_WIDTH, width * 3),
            max_lines,
            self.palette,
            self.timeout,
        )
        if lines is not None:
            self.lines = lines
        return self.lines

    def invalidate(self) -> None:
        self.next_refresh = 0.0


class AsyncFancylogMonitor:
    """Refresh one Fancylog summary without blocking a UI renderer."""

    def __init__(
        self,
        interval: float = 3.0,
        timeout: float = 0.75,
        executable: str = "fancylog",
        palette: str = DEFAULT_REPOSITORY_PALETTE,
    ) -> None:
        self.interval = interval
        self.timeout = timeout
        self.executable = executable
        self.palette = palette
        self.key: tuple[str, int, int] | None = None
        self.lines: list[str] = []
        self.next_refresh = 0.0
        self.pending: Future[list[str] | None] | None = None
        self.pending_key: tuple[str, int, int] | None = None
        self.executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="ktt-repository-summary",
        )

    def update(
        self,
        path: str | None,
        width: int,
        max_lines: int,
        now: float | None = None,
    ) -> list[str]:
        current = time.monotonic() if now is None else now
        key = (
            (path, width, max_lines)
            if path and width > 0 and max_lines > 0
            else None
        )
        if key != self.key:
            self.key = key
            self.lines = []
            self.next_refresh = 0.0

        if self.pending is not None and self.pending.done():
            try:
                lines = self.pending.result()
            except Exception:
                lines = None
            if self.pending_key == self.key and lines is not None:
                self.lines = lines
            self.pending = None
            self.pending_key = None

        if (
            self.key is not None
            and self.pending is None
            and current >= self.next_refresh
        ):
            path_value, width_value, max_lines_value = self.key
            self.pending_key = self.key
            self.next_refresh = current + self.interval
            self.pending = self.executor.submit(
                fancylog_status_lines,
                self.executable,
                path_value,
                max(MINIMUM_STATUS_SOURCE_WIDTH, width_value * 3),
                max_lines_value,
                self.palette,
                self.timeout,
            )
        return self.lines

    def needs_refresh(self, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        return (
            self.pending is not None
            or (self.key is not None and current >= self.next_refresh)
        )

    def close(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)


class FancylogIdentityCache:
    def __init__(
        self,
        timeout: float = 0.75,
        executable: str = "fancylog",
        palette: str = DEFAULT_REPOSITORY_PALETTE,
        workers: int = 2,
        retry_interval: float = 3.0,
    ) -> None:
        self.timeout = timeout
        self.executable = executable
        self.palette = palette
        self.retry_interval = retry_interval
        self.names: dict[str, str | None] = {}
        self.locations: dict[str, RepositoryLocation | None] = {}
        self.retry_after: dict[str, float] = {}
        self.pending: dict[
            str, Future[tuple[str | None, RepositoryLocation | None]]
        ] = {}
        self.executor = ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="ktt-repository",
        )

    def _resolve(
        self, path: str
    ) -> tuple[str | None, RepositoryLocation | None]:
        lines = fancylog_status_lines(
            self.executable,
            path,
            IDENTITY_WIDTH,
            1,
            self.palette,
            self.timeout,
            color="never",
        )
        return (
            repository_name_from_status(lines),
            resolve_repository_location(path, min(0.25, self.timeout)),
        )

    def update(
        self,
        paths: Iterable[str | None],
        now: float | None = None,
    ) -> dict[str, str]:
        current = time.monotonic() if now is None else now
        for path, future in list(self.pending.items()):
            if not future.done():
                continue
            try:
                name, location = future.result()
            except Exception:
                name, location = None, None
            self.names[path] = name
            self.locations[path] = location
            if self.names[path] is None:
                self.retry_after[path] = current + self.retry_interval
            else:
                self.retry_after.pop(path, None)
            del self.pending[path]
        for path in dict.fromkeys(path for path in paths if path):
            if path in self.pending or self.names.get(path) is not None:
                continue
            if current >= self.retry_after.get(path, 0.0):
                self.pending[path] = self.executor.submit(self._resolve, path)
        return {path: name for path, name in self.names.items() if name is not None}

    def worktrees(self) -> dict[str, str]:
        return {
            path: location.worktree
            for path, location in self.locations.items()
            if location is not None and location.worktree
        }

    def close(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)

    def __enter__(self) -> FancylogIdentityCache:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def with_repository_worktrees(
    records: Iterable[TabRecord],
    worktrees_by_cwd: dict[str, str],
) -> list[TabRecord]:
    return [
        replace(
            record,
            repository_worktree=worktrees_by_cwd.get(record.cwd or ""),
        )
        for record in records
    ]
