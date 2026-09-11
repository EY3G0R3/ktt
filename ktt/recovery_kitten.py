"""Kitty-side entry point for hot-starting automatic recovery snapshots."""

from __future__ import annotations

import importlib
from pathlib import Path
import sys

from kitty.boss import Boss
from kittens.tui.handler import result_handler


def main(_args: list[str]) -> None:
    pass


@result_handler(no_ui=True)
def handle_result(
    args: list[str], _answer: str, _target_window_id: int, boss: Boss
) -> None:
    if not args:
        return
    package_root = str(Path(args[0]).resolve().parent.parent)
    added = package_root not in sys.path
    if added:
        sys.path.insert(0, package_root)
    try:
        import ktt.kitty_watcher as kitty_watcher

        kitty_watcher = importlib.reload(kitty_watcher)
        kitty_watcher._start_recovery_snapshotter(boss, replace=True)
    finally:
        if added:
            try:
                sys.path.remove(package_root)
            except ValueError:
                pass
