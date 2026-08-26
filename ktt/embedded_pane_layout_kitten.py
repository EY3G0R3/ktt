"""No-UI Kitty bridge for placing a specific embedded KTT pane."""

from __future__ import annotations

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
    if len(args) < 4:
        return
    source_id = int(args[1]) if args[1].isdigit() else 0
    sidebar_id = int(args[2]) if args[2].isdigit() else 0
    bias = int(args[3]) if args[3].isdigit() else 20
    source = boss.window_id_map.get(source_id)
    sidebar = boss.window_id_map.get(sidebar_id)
    tab = source.tabref() if source is not None else None
    if source is None or sidebar is None or sidebar.tabref() is not tab:
        return

    # Kitty evaluates custom kittens without defining ``__file__``.
    package_root = Path(args[0]).resolve().parent.parent
    sys.path.insert(0, str(package_root))
    from ktt.kitty_layout import place_window_at_left_edge

    place_window_at_left_edge(
        tab, sidebar, bias, restore_window=source
    )
