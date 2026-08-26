from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EmbeddedLeftEdgePlacement:
    tab: Any
    sidebar: Any
    restore_window: Any
    bias: int


def capture_embedded_left_edge_placements(
    tab_managers: Any,
    *,
    sidebar_var: str,
    orientation_var: str,
    pane_percent_var: str,
    cockpit_role_var: str,
) -> list[EmbeddedLeftEdgePlacement]:
    """Remember vertical embedded panes before Kitty rebuilds their layouts."""
    placements: list[EmbeddedLeftEdgePlacement] = []
    for tab_manager in tab_managers:
        for tab in tab_manager:
            tab_windows = tuple(tab)
            sidebar = next(
                (
                    window
                    for window in tab_windows
                    if str(window.user_vars.get(sidebar_var) or "") == "1"
                    and str(window.user_vars.get(orientation_var) or "")
                    == "vertical"
                    and str(window.user_vars.get(cockpit_role_var) or "")
                    == "ktt"
                ),
                None,
            )
            if sidebar is None:
                continue
            content = [window for window in tab_windows if window is not sidebar]
            if not content:
                continue
            active = tab.active_window
            restore_window = active if active in content else next(
                (
                    window
                    for window in content
                    if str(window.user_vars.get(cockpit_role_var) or "")
                    == "agent"
                ),
                content[0],
            )
            try:
                bias = int(sidebar.user_vars.get(pane_percent_var) or 20)
            except (TypeError, ValueError):
                bias = 20
            placements.append(
                EmbeddedLeftEdgePlacement(
                    tab, sidebar, restore_window, max(1, min(bias, 99))
                )
            )
    return placements


def restore_embedded_left_edge_placements(
    placements: list[EmbeddedLeftEdgePlacement],
) -> int:
    """Reapply captured left-edge placements after a Kitty config reload."""
    return sum(
        place_window_at_left_edge(
            placement.tab,
            placement.sidebar,
            placement.bias,
            restore_window=placement.restore_window,
        )
        for placement in placements
    )


def place_window_at_left_edge(
    tab: Any,
    window: Any,
    bias: int,
    *,
    restore_window: Any | None = None,
) -> bool:
    """Promote one window to the splits-layout left edge without changing focus."""
    windows = tab.windows
    target_index = windows.group_idx_for_window(window)
    original_window = restore_window or windows.active_window
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
