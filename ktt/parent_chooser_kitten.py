"""Kitty-side rofi chooser for reparenting the active native tree tab."""

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
    child_tab = source.tabref() if source is not None else None
    tab_manager = (
        child_tab.tab_manager_ref() if child_tab is not None else None
    )
    if source is None or child_tab is None or tab_manager is None or not args:
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
        import ktt.chooser as chooser

        model = importlib.reload(model)
        kitty_tabs = importlib.reload(kitty_tabs)
        chooser = importlib.reload(chooser)
    finally:
        if added:
            try:
                sys.path.remove(package_root_text)
            except ValueError:
                pass

    from kitty.utils import log_error

    try:
        records = list(kitty_tabs.live_tree_records(tab_manager))
        selected = chooser.choose_parent_tab(records, child_tab.id)
        if selected is None:
            return

        # Rofi can stay open while tabs change. Revalidate the selection against
        # the live tree immediately before applying the parent relationship.
        live_records = list(kitty_tabs.live_tree_records(tab_manager))
        valid = {
            record.id: record
            for record in chooser.parent_candidates(live_records, child_tab.id)
        }
        parent = valid.get(selected.id)
        if parent is None or not parent.window_ids:
            raise RuntimeError("selected parent is no longer available")
        source.set_user_var(model.PARENT_VAR, str(parent.window_ids[0]))
    except Exception as error:
        message = f"ktt parent chooser: {error}"
        log_error(message)
        boss.show_error("KTT parent selection failed", str(error))
