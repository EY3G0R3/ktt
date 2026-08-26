"""Kitty-side native tab-bar toggle that preserves embedded ktt panes."""

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

    # Kitty evaluates custom kittens without defining ``__file__``. The first
    # result-handler argument is the absolute kitten path from the action.
    package_root = Path(args[0]).resolve().parent.parent
    sys.path.insert(0, str(package_root))

    from kitty.fast_data_types import get_options
    import ktt.kitty_layout as kitty_layout

    # Other ktt kittens can leave package modules cached inside Kitty. Reload
    # this pure helper so a source update works without restarting Kitty.
    kitty_layout = importlib.reload(kitty_layout)

    placements = kitty_layout.capture_embedded_left_edge_placements(
        boss.all_tab_managers,
        sidebar_var="ktt_sidebar",
        orientation_var="ktt_orientation",
        pane_percent_var="ktt_pane_percent",
        cockpit_role_var="ktt_cockpit_role",
    )

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
    # Kitty resizes before TabManager.apply_options() updates tab_bar_hidden.
    # Resize once more, then restore layouts invalidated by the config reload.
    for tab_manager in boss.all_tab_managers:
        tab_manager.resize()
    kitty_layout.restore_embedded_left_edge_placements(placements)
