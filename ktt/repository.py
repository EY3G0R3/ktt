from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import os
import re
import subprocess
import time
from typing import Any, Iterable

from .model import SIDEBAR_VAR


REPOSITORY_PALETTES = (
    "surf", "amber", "vivid", "quiet", "graphite", "terminal", "dracula",
)
DEFAULT_REPOSITORY_PALETTE = "amber"
MAX_REPOSITORY_LINES = 8
IDENTITY_WIDTH = 256
REPOSITORY_IDENTITY = re.compile(r"^\s*\(([^)]+)\)")


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
    return match.group(1) if match else None


def active_window_cwd(os_window: dict[str, Any]) -> str | None:
    tabs = os_window.get("tabs") or []
    tab = next((item for item in tabs if item.get("is_active")), None)
    if tab is None:
        return None
    windows = [
        window
        for window in tab.get("windows") or []
        if str((window.get("user_vars") or {}).get(SIDEBAR_VAR) or "") != "1"
    ]
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
            width,
            max_lines,
            self.palette,
            self.timeout,
        )
        if lines is not None:
            self.lines = lines
        return self.lines

    def invalidate(self) -> None:
        self.next_refresh = 0.0


class FancylogIdentityCache:
    def __init__(
        self,
        timeout: float = 0.75,
        executable: str = "fancylog",
        palette: str = DEFAULT_REPOSITORY_PALETTE,
        workers: int = 2,
    ) -> None:
        self.timeout = timeout
        self.executable = executable
        self.palette = palette
        self.names: dict[str, str | None] = {}
        self.pending: dict[str, Future[str | None]] = {}
        self.executor = ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="ktt-repository",
        )

    def _resolve(self, path: str) -> str | None:
        lines = fancylog_status_lines(
            self.executable,
            path,
            IDENTITY_WIDTH,
            1,
            self.palette,
            self.timeout,
            color="never",
        )
        return repository_name_from_status(lines)

    def update(self, paths: Iterable[str | None]) -> dict[str, str]:
        for path, future in list(self.pending.items()):
            if not future.done():
                continue
            try:
                self.names[path] = future.result()
            except Exception:
                self.names[path] = None
            del self.pending[path]
        for path in dict.fromkeys(path for path in paths if path):
            if path not in self.names and path not in self.pending:
                self.pending[path] = self.executor.submit(self._resolve, path)
        return {path: name for path, name in self.names.items() if name is not None}

    def close(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)

    def __enter__(self) -> FancylogIdentityCache:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
