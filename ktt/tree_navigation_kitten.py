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
    hidden = (
        options.tab_bar_style == "hidden"
        or options.tab_bar_min_tabs >= 1000000
    )
    if hidden:
        overrides = ["tab_bar_min_tabs 1"]
        if options.tab_bar_style == "hidden":
            # Compatibility with the first ktt experiment, which hid the bar
            # by replacing its style and therefore forgot the configured one.
            overrides.append("tab_bar_style fade")
    else:
        overrides = ["tab_bar_min_tabs 1000000"]
    boss.load_config_file(
        apply_overrides=False,
        overrides=tuple(overrides),
    )
    # Kitty's option reload resizes managers before TabManager.apply_options()
    # changes tab_bar_hidden. Resize once more with the new visibility so the
    # terminal grid yields/reclaims the bar row instead of painting over it.
    for tab_manager in boss.all_tab_managers:
        tab_manager.resize()


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
    action = args[1]
    if action == "place-sidebar-left":
        if len(args) < 4:
            return
        sidebar_id = int(args[2]) if args[2].isdigit() else 0
        bias = int(args[3]) if args[3].isdigit() else 20
        sidebar = boss.window_id_map.get(sidebar_id)
        if sidebar is None or sidebar.tabref() is not tab:
            return
        from ktt.kitty_layout import place_window_at_left_edge

        place_window_at_left_edge(tab, sidebar, bias)
        return

    import ktt.events as events
    from ktt.kitty import SIDEBAR_VAR, TARGET_OS_WINDOW_VAR
    from ktt.model import adjacent_tree_tab_id, records_for_os_window, tree_rows

    if action == "toggle-tabs":
        _toggle_native_tabs(boss)
        return
    direction = 1 if action == "next" else -1 if action == "previous" else 0
    if direction == 0:
        return

    target_value = str(source.user_vars.get(TARGET_OS_WINDOW_VAR) or "")
    from_sidebar = (
        str(source.user_vars.get(SIDEBAR_VAR) or "") == "1"
        and target_value.isdigit()
    )
    target_os_window_id = (
        int(target_value) if from_sidebar else tab_manager.os_window_id
    )
    if from_sidebar:
        from ktt.order import read_visible_order

        visible = read_visible_order(
            target_os_window_id, kitty_pid=os.getpid()
        )
        target_manager = boss.os_window_map.get(target_os_window_id)
        if visible is not None and target_manager is not None:
            index = visible.tab_ids.index(visible.anchor_tab_id)
            target_index = index + direction
            if not 0 <= target_index < len(visible.tab_ids):
                return
            target_tab_id = visible.tab_ids[target_index]
            target = next(
                (
                    candidate
                    for candidate in target_manager
                    if candidate.id == target_tab_id
                ),
                None,
            )
            if target is not None:
                target_manager.set_active_tab(target)
                return
    sent = events.send_navigation(
        target_os_window_id,
        direction,
        kitty_pid=os.getpid(),
    )
    if sent:
        return

    # If ktt is not running, preserve useful navigation by computing the full
    # tree in Kitty. There is no local fold state to honor in this fallback.
    os_window = next(
        (
            value
            for value in boss.list_os_windows(self_window=source)
            if int(value["id"]) == target_os_window_id
        ),
        None,
    )
    if os_window is None:
        return
    target_tab_id = adjacent_tree_tab_id(
        tree_rows(records_for_os_window(os_window)), direction
    )
    target_manager = boss.os_window_map.get(target_os_window_id)
    if target_manager is None:
        return
    target = next(
        (candidate for candidate in target_manager if candidate.id == target_tab_id),
        None,
    )
    if target is not None:
        target_manager.set_active_tab(target)
