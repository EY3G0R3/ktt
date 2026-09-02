"""Kitty-side navigation and sibling reordering in native tree order."""

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
    args: list[str], _answer: str, target_window_id: int, boss: Boss
) -> None:
    source = boss.window_id_map.get(target_window_id)
    tab = source.tabref() if source is not None else None
    tab_manager = tab.tab_manager_ref() if tab is not None else None
    if source is None or tab_manager is None or len(args) < 2:
        return

    package_root = Path(args[0]).resolve().parent.parent
    package_root_text = str(package_root)
    added = package_root_text not in sys.path
    if added:
        sys.path.insert(0, package_root_text)
    try:
        import ktt.tab_bar_geometry as tab_bar_geometry

        tab_bar_geometry = importlib.reload(tab_bar_geometry)
        import ktt.model as model
        import ktt.kitty_tabs as kitty_tabs

        model = importlib.reload(model)
        kitty_tabs = importlib.reload(kitty_tabs)
    finally:
        if added:
            try:
                sys.path.remove(package_root_text)
            except ValueError:
                pass

    action = args[1]
    direction = (
        1
        if action in ("next", "move-next")
        else -1
        if action in ("previous", "move-previous")
        else 0
    )
    if direction == 0 and action != "attention":
        return

    rows = model.tree_rows(kitty_tabs.live_tree_records(tab_manager))
    if action.startswith("move-"):
        active = tab_manager.active_tab
        if active is None:
            return
        desired_tab_ids = model.reordered_tree_tab_ids(
            rows, active.id, direction
        )
        if desired_tab_ids is not None:
            kitty_tabs.apply_tab_order(tab_manager, desired_tab_ids)
        return

    target_tab_id = (
        model.next_attention_tab_id(rows)
        if action == "attention"
        else model.adjacent_tree_tab_id(rows, direction)
    )
    target = next(
        (candidate for candidate in tab_manager if candidate.id == target_tab_id),
        None,
    )
    if target is not None:
        tab_manager.set_active_tab(target)
