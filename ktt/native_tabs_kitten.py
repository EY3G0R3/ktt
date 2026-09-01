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
    package_root_text = str(package_root)
    added = package_root_text not in sys.path
    if added:
        sys.path.insert(0, package_root_text)
    try:
        import ktt.tab_bar_geometry as tab_bar_geometry
        tab_bar_geometry = importlib.reload(tab_bar_geometry)
        import ktt.kitty_layout as kitty_layout
        import ktt.model as model
        import ktt.kitty_tabs as kitty_tabs
        import ktt.native_tabs as native_tabs
        native_tabs = importlib.reload(native_tabs)
        import ktt.native_tabs_runtime as native_tabs_runtime
        import ktt.tab_bar_renderer as tab_bar_renderer

        tab_bar_renderer = importlib.reload(tab_bar_renderer)
        model = importlib.reload(model)
        kitty_tabs = importlib.reload(kitty_tabs)
        kitty_layout = importlib.reload(kitty_layout)
        native_tabs_runtime = importlib.reload(native_tabs_runtime)
    finally:
        if added:
            try:
                sys.path.remove(package_root_text)
            except ValueError:
                pass

    action, strict = native_tabs_runtime.parse_action_args(args[1:])
    from kitty.constants import version as kitty_version
    from kitty.fast_data_types import get_options
    from kitty.utils import log_error

    running_version = native_tabs.version_tuple(kitty_version)
    left_edge = right_edge = None
    if running_version >= native_tabs.NATIVE_VERTICAL_TABS_VERSION:
        from kitty.fast_data_types import LEFT_EDGE, RIGHT_EDGE

        left_edge, right_edge = LEFT_EDGE, RIGHT_EDGE
    # load_config_file reloads the configured tab_bar.py. Keep ktt importable
    # for that bounded operation so the renderer binds the tested geometry
    # helpers on the very first native enable, then restore Kitty's path.
    with native_tabs_runtime.temporary_sys_path(package_root_text):
        native_tabs_runtime.run_native_tabs_action(
            boss=boss,
            action=action,
            strict=strict,
            running_version=running_version,
            options=get_options(),
            read_options=get_options,
            left_edge=left_edge,
            right_edge=right_edge,
            kitty_layout=kitty_layout,
            kitty_tabs=kitty_tabs,
            log_error=log_error,
        )
