"""Kitty-independent execution helpers for the native vertical tab renderer."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .tab_bar_geometry import vertical_cursor_plan, vertical_tab_layout


LEFT_CAP = ""
RIGHT_CAP = ""


def draw_vertical_tab(
    *,
    screen: Any,
    draw_title: Callable[..., None],
    draw_data: Any,
    tab: Any,
    before: int,
    max_tab_length: int,
    index: int,
    tab_background: Any,
    panel_background: Any | None = None,
    leading_cells: int = 0,
    line_index: int = 0,
    card_height: int = 1,
    for_layout: bool,
) -> int:
    """Draw one line of a tapered native card at an exact bounded width."""
    panel_background = (
        tab_background if panel_background is None else panel_background
    )
    title_foreground = screen.cursor.fg
    screen.cursor.bg = tab_background
    if max_tab_length <= 1:
        if not for_layout and max_tab_length == 1:
            screen.draw("…")
        return screen.cursor.x

    leading_cells = min(max(0, int(leading_cells)), max_tab_length - 1)
    if leading_cells:
        screen.cursor.bg = panel_background
        screen.draw(" " * leading_cells)
    available = max_tab_length - leading_cells
    content_line = max(0, (max(1, int(card_height)) - 1) // 2)
    if line_index != content_line:
        if available <= 2:
            screen.cursor.bg = tab_background
            screen.draw(" " * available)
        else:
            screen.cursor.bg = panel_background
            screen.draw(" ")
            screen.cursor.bg = tab_background
            screen.draw(" " * (available - 2))
            screen.cursor.bg = panel_background
            screen.draw(" ")
        return screen.cursor.x

    if available <= 2:
        screen.cursor.bg = tab_background
        draw_title(draw_data, screen, tab, index, available)
        if not for_layout and screen.cursor.x < before + max_tab_length:
            screen.draw(" " * (before + max_tab_length - screen.cursor.x))
        return screen.cursor.x

    screen.cursor.bg = panel_background
    screen.cursor.fg = tab_background
    screen.draw(LEFT_CAP)
    screen.cursor.bg = tab_background
    screen.cursor.fg = title_foreground
    draw_title(draw_data, screen, tab, index, available - 2)
    if for_layout:
        screen.cursor.bg = panel_background
        screen.cursor.fg = tab_background
        screen.draw(RIGHT_CAP)
        return screen.cursor.x

    rewind, remaining = vertical_cursor_plan(
        before, screen.cursor.x, max_tab_length - 1
    )
    if rewind:
        screen.cursor.x -= rewind
        screen.draw("…")
    if remaining:
        screen.cursor.bg = tab_background
        screen.draw(" " * remaining)
    screen.cursor.bg = panel_background
    screen.cursor.fg = tab_background
    screen.draw(RIGHT_CAP)
    return screen.cursor.x


def update_vertical_tab_bar(
    owner: Any,
    data: Any,
    *,
    as_rgb: Callable[[int], Any],
    color_as_int: Callable[[Any], int],
    cell_range_type: Callable[[int, int], Any],
    tab_extent_type: Callable[..., Any],
    extra_data_type: Callable[[], Any],
) -> bool:
    """Render KTT cards into Kitty 0.48's native vertical tab surface."""
    screen = owner.screen
    owner.last_laid_out_tabs = data
    owner.tab_extents = ()
    screen.cursor.x = screen.cursor.y = 0
    screen.erase_in_display(2, False)
    if not data:
        return owner._update_edge_defaults(True)

    active_index = next(
        (index for index, tab in enumerate(data) if tab.is_active),
        0,
    )
    layout = vertical_tab_layout(
        len(data),
        screen.lines,
        active_index=active_index,
        alignment=owner.tab_bar_align,
    )
    max_tab_length = max(1, screen.columns - 1)
    panel_background = as_rgb(color_as_int(owner.draw_data.default_bg))
    extents = []
    for placement in layout.placements:
        tab = data[placement.data_index]
        for line_index in range(placement.card_height):
            screen.cursor.x = 0
            screen.cursor.y = placement.start_row + line_index
            screen.cursor.bg = as_rgb(owner.draw_data.tab_bg(tab))
            screen.cursor.fg = as_rgb(owner.draw_data.tab_fg(tab))
            screen.cursor.bold, screen.cursor.italic = (
                owner.active_font_style
                if tab.is_active
                else owner.inactive_font_style
            )
            extra_data = extra_data_type()
            extra_data.ktt_line_index = line_index
            extra_data.ktt_card_height = placement.card_height
            extra_data.ktt_panel_background = panel_background
            owner.draw_func(
                owner.draw_data,
                screen,
                tab,
                0,
                max_tab_length,
                placement.data_index + 1,
                placement is layout.placements[-1],
                extra_data,
            )
            screen.cursor.bg = screen.cursor.fg = 0
        extents.append(tab_extent_type(
            tab_id=tab.tab_id,
            x=cell_range_type(0, screen.columns - 1),
            y=cell_range_type(
                placement.start_row,
                placement.start_row + placement.card_height - 1,
            ),
        ))
    if layout.ellipsis_row is not None:
        screen.cursor.x = 0
        screen.cursor.y = layout.ellipsis_row
        screen.cursor.bg = panel_background
        screen.cursor.fg = as_rgb(0xff0000)
        screen.draw("…")
    owner.tab_extents = tuple(extents)
    return owner._update_edge_defaults(True)


def install_vertical_tab_layout(
    tab_bar_type: type,
    *,
    is_enabled: Callable[[], bool],
    **dependencies: Any,
) -> None:
    """Install a reversible, process-local native-card layout wrapper."""
    current = tab_bar_type.update_vertical
    original = getattr(current, "_ktt_original_update_vertical", current)

    def update_vertical(owner: Any, data: Any) -> bool:
        if not is_enabled() or not getattr(
            owner.draw_func, "_ktt_vertical_cards", False
        ):
            return original(owner, data)
        return update_vertical_tab_bar(owner, data, **dependencies)

    update_vertical._ktt_vertical_layout = True  # type: ignore[attr-defined]
    update_vertical._ktt_original_update_vertical = original  # type: ignore[attr-defined]
    tab_bar_type.update_vertical = update_vertical
