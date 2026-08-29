"""Kitty-side navigation bridge for ktt's visible tree order."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys

from kitty.boss import Boss
from kittens.tui.handler import result_handler


def main(_args: list[str]) -> None:
    pass


def _apply_tab_order(tab_manager: object, desired_tab_ids: tuple[int, ...]) -> None:
    from kitty.fast_data_types import swap_tabs

    tabs = tab_manager.tabs
    active_tab = tab_manager.active_tab
    by_id = {tab.id: tab for tab in tabs}
    desired = [by_id[tab_id] for tab_id in desired_tab_ids if tab_id in by_id]
    desired_ids = {tab.id for tab in desired}
    known_slots = [
        index for index, tab in enumerate(tabs) if tab.id in desired_ids
    ]
    final_order = list(tabs)
    for index, tab in zip(known_slots, desired):
        final_order[index] = tab
    if final_order == tabs:
        return

    for target_index, target in enumerate(final_order):
        current_index = tabs.index(target)
        while current_index > target_index:
            previous_index = current_index - 1
            tabs[previous_index], tabs[current_index] = (
                tabs[current_index],
                tabs[previous_index],
            )
            swap_tabs(tab_manager.os_window_id, previous_index, current_index)
            current_index = previous_index
    if active_tab is not None:
        tab_manager._set_active_tab(
            tabs.index(active_tab), store_in_history=False
        )
    tab_manager.mark_tab_bar_dirty()


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
    import ktt.events as events
    import ktt.model as model
    import ktt.order as order
    from ktt.kitty import SIDEBAR_VAR, TARGET_OS_WINDOW_VAR

    # Kitty caches imported package modules between kitten invocations. Reload
    # the pure tree model and runtime snapshot reader so source updates work
    # without restarting Kitty.
    model = importlib.reload(model)
    order = importlib.reload(order)

    action = args[1]
    direction = (
        1
        if action in ("next", "move-next")
        else -1
        if action in ("previous", "move-previous")
        else 0
    )
    attention = action == "attention"
    if direction == 0 and not attention:
        return
    reorder = action.startswith("move-")

    target_value = str(source.user_vars.get(TARGET_OS_WINDOW_VAR) or "")
    from_sidebar = (
        str(source.user_vars.get(SIDEBAR_VAR) or "") == "1"
        and target_value.isdigit()
    )
    target_os_window_id = (
        int(target_value) if from_sidebar else tab_manager.os_window_id
    )
    target_manager = boss.os_window_map.get(target_os_window_id)
    if target_manager is None:
        return
    if attention:
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
        visible = order.read_visible_order(
            target_os_window_id, kitty_pid=os.getpid()
        )
        attention_tab_ids = getattr(visible, "attention_tab_ids", None)
        eligible_tab_ids = (
            set(attention_tab_ids)
            if attention_tab_ids is not None
            else None
        )
        target_tab_id = model.next_attention_tab_id(
            model.tree_rows(model.records_for_os_window(os_window)),
            eligible_tab_ids,
        )
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
    if reorder:
        visible = order.read_visible_order(
            target_os_window_id, kitty_pid=os.getpid()
        )
        anchor_tab_id = (
            visible.anchor_tab_id
            if visible is not None
            else target_manager.active_tab.id
            if target_manager.active_tab is not None
            else None
        )
        os_window = next(
            (
                value
                for value in boss.list_os_windows(self_window=source)
                if int(value["id"]) == target_os_window_id
            ),
            None,
        )
        if anchor_tab_id is None or os_window is None:
            return
        desired_tab_ids = model.reordered_tree_tab_ids(
            model.tree_rows(model.records_for_os_window(os_window)),
            anchor_tab_id,
            direction,
        )
        if desired_tab_ids is not None:
            _apply_tab_order(target_manager, desired_tab_ids)
        return
    if from_sidebar:
        visible = order.read_visible_order(
            target_os_window_id, kitty_pid=os.getpid()
        )
        if visible is not None:
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
    target_tab_id = model.adjacent_tree_tab_id(
        model.tree_rows(model.records_for_os_window(os_window)), direction
    )
    target = next(
        (candidate for candidate in target_manager if candidate.id == target_tab_id),
        None,
    )
    if target is not None:
        target_manager.set_active_tab(target)
