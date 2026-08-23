"""Kitty-side navigation bridge for ktt's visible tree order."""

from __future__ import annotations

import os
from pathlib import Path
import sys

from kitty.boss import Boss
from kittens.tui.handler import result_handler


def main(_args: list[str]) -> None:
    pass


def _toggle_native_tabs(boss: Boss) -> None:
    from kitty.fast_data_types import get_options

    options = get_options()
    if options.tab_bar_style == "hidden":
        style = getattr(boss, "_ktt_native_tab_style", "custom")
    else:
        style = "hidden"
        setattr(boss, "_ktt_native_tab_style", options.tab_bar_style)
    boss.load_config_file(
        apply_overrides=False,
        overrides=(f"tab_bar_style {style}",),
    )


@result_handler(no_ui=True)
def handle_result(
    args: list[str], _answer: str, target_window_id: int, boss: Boss
) -> None:
    source = boss.window_id_map.get(target_window_id)
    tab = source.tabref() if source is not None else None
    tab_manager = tab.tab_manager_ref() if tab is not None else None
    if source is None or tab_manager is None or len(args) < 2:
        return

    # Kitty evaluates custom kittens without defining ``__file__``. The first
    # result-handler argument is the absolute kitten path from the mapping.
    package_root = Path(args[0]).resolve().parent.parent
    sys.path.insert(0, str(package_root))
    from ktt.events import send_navigation
    from ktt.model import adjacent_tree_tab_id, records_for_os_window, tree_rows

    action = args[1]
    if action == "toggle-tabs":
        _toggle_native_tabs(boss)
        return

    direction = 1 if action == "next" else -1 if action == "previous" else 0
    if direction == 0:
        return
    if send_navigation(
        tab_manager.os_window_id, direction, kitty_pid=os.getpid()
    ):
        return

    # If ktt is not running, preserve useful navigation by computing the full
    # tree in Kitty. There is no local fold state to honor in this fallback.
    os_window = next(
        (
            value
            for value in boss.list_os_windows(self_window=source)
            if int(value["id"]) == tab_manager.os_window_id
        ),
        None,
    )
    if os_window is None:
        return
    target_tab_id = adjacent_tree_tab_id(
        tree_rows(records_for_os_window(os_window)), direction
    )
    target = next(
        (candidate for candidate in tab_manager if candidate.id == target_tab_id),
        None,
    )
    if target is not None:
        tab_manager.set_active_tab(target)
