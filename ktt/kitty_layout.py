from __future__ import annotations

from typing import Any


def place_window_at_left_edge(tab: Any, window: Any, bias: int) -> bool:
    """Promote one window to the splits-layout left edge without changing focus."""
    windows = tab.windows
    target_index = windows.group_idx_for_window(window)
    original_window = windows.active_window
    if target_index is None or original_window is None:
        return False
    original_history = tuple(windows.active_group_history)
    windows.set_active_group_idx(target_index, notify=False)
    moved = False
    try:
        result = tab.current_layout.layout_action(
            "move_to_screen_edge", ("left",), windows
        )
        moved = result is True
        if moved:
            tab.current_layout.layout_action(
                "bias", (str(max(1, min(bias, 99))),), windows
            )
    finally:
        original_index = windows.group_idx_for_window(original_window)
        if original_index is not None:
            windows.set_active_group_idx(original_index, notify=False)
        windows.active_group_history.clear()
        windows.active_group_history.extend(original_history)
    if moved:
        tab.relayout()
    return moved
