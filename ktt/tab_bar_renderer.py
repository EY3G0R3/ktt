"""Kitty-independent execution helpers for the native vertical tab renderer."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .tab_bar_geometry import vertical_cursor_plan


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
    for_layout: bool,
) -> int:
    """Draw one vertical row, leaving layout measurement at its ideal width."""
    screen.cursor.bg = tab_background
    if max_tab_length <= 1:
        if not for_layout and max_tab_length == 1:
            screen.draw("…")
        return screen.cursor.x

    screen.draw(" ")
    draw_title(draw_data, screen, tab, index, max_tab_length - 1)
    if for_layout:
        return screen.cursor.x

    rewind, remaining = vertical_cursor_plan(
        before, screen.cursor.x, max_tab_length
    )
    if rewind:
        screen.cursor.x -= rewind
        screen.draw("…")
    if remaining:
        screen.cursor.bg = tab_background
        screen.draw(" " * remaining)
    return screen.cursor.x
