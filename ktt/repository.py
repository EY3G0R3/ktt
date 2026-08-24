from __future__ import annotations

import os
import subprocess
import time
from typing import Any


REPOSITORY_PALETTES = (
    "surf", "amber", "vivid", "quiet", "graphite", "terminal", "dracula",
)
DEFAULT_REPOSITORY_PALETTE = "amber"
MAX_REPOSITORY_LINES = 8


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
        environment = os.environ.copy()
        environment["GIT_OPTIONAL_LOCKS"] = "0"
        try:
            result = subprocess.run(
                [
                    self.executable,
                    "--status-only",
                    "--width",
                    str(width),
                    "--height",
                    str(max_lines),
                    "--color",
                    "always",
                    "--header-palette",
                    self.palette,
                    path,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired):
            return self.lines
        if result.returncode == 0:
            self.lines = result.stdout.rstrip("\n").splitlines()[:max_lines]
        return self.lines

    def invalidate(self) -> None:
        self.next_refresh = 0.0
