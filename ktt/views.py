from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from .model import TreeRow
from .render import (
    DEFAULT_ORIENTATION,
    REPOSITORY_BOTTOM_MARGIN,
    REPOSITORY_TOP_GAP,
    TREE_INDENT_WIDTH,
    adaptive_card_height,
    card_content_line,
    card_gap,
    content_height,
    horizontal_disclosure_column,
    horizontal_index_at_mouse,
    horizontal_layout,
    render_horizontal_screen,
    render_screen,
    vertical_bottom_padding,
    vertical_padding,
    visible_start,
)


ScreenRenderer = Callable[..., str]


@dataclass(frozen=True)
class HitTarget:
    index: int | None
    disclosure: bool = False


class View(Protocol):
    name: str
    renderer: ScreenRenderer

    def card_height(self, row_count: int, height: int) -> int: ...

    def repository_capacity(
        self,
        rows: list[TreeRow],
        width: int,
        height: int,
        selected_index: int,
        card_height: int,
    ) -> int: ...

    def hit_target(
        self,
        rows: list[TreeRow],
        width: int,
        height: int,
        selected_index: int,
        card_height: int,
        mouse_column: int,
        mouse_row: int,
    ) -> HitTarget: ...


def row_index_at_mouse(
    mouse_row: int,
    *,
    start: int,
    row_count: int,
    height: int,
    top_padding: int = 0,
    card_height: int = 1,
) -> int | None:
    first_row = 1 + top_padding
    last_content_row = content_height(height)
    if mouse_row < first_row or mouse_row > last_content_row:
        return None
    offset = mouse_row - first_row
    stride = card_height + card_gap(card_height)
    line_in_stride = offset % stride
    if line_in_stride >= card_height:
        return None
    index = start + offset // stride
    return index if index < row_count else None


def disclosure_column(row: TreeRow) -> int:
    return 2 + TREE_INDENT_WIDTH * row.depth


@dataclass(frozen=True)
class VerticalView:
    name: str = "vertical"
    renderer: ScreenRenderer = render_screen

    def card_height(self, row_count: int, height: int) -> int:
        return adaptive_card_height(row_count, height)

    def repository_capacity(
        self,
        rows: list[TreeRow],
        width: int,
        height: int,
        selected_index: int,
        card_height: int,
    ) -> int:
        del width, selected_index
        return (
            vertical_bottom_padding(len(rows), height, card_height)
            - REPOSITORY_TOP_GAP
            - REPOSITORY_BOTTOM_MARGIN
        )

    def hit_target(
        self,
        rows: list[TreeRow],
        width: int,
        height: int,
        selected_index: int,
        card_height: int,
        mouse_column: int,
        mouse_row: int,
    ) -> HitTarget:
        del width
        start = visible_start(len(rows), selected_index, height, card_height)
        top_padding = vertical_padding(len(rows), height, card_height)
        index = row_index_at_mouse(
            mouse_row,
            start=start,
            row_count=len(rows),
            height=height,
            top_padding=top_padding,
            card_height=card_height,
        )
        if index is None:
            return HitTarget(None)
        content_line = (
            (mouse_row - 1 - top_padding)
            % (card_height + card_gap(card_height))
            == card_content_line(card_height)
        )
        return HitTarget(
            index,
            content_line and mouse_column == disclosure_column(rows[index]),
        )


@dataclass(frozen=True)
class HorizontalView:
    name: str = "horizontal"
    renderer: ScreenRenderer = render_horizontal_screen

    def card_height(self, row_count: int, height: int) -> int:
        del row_count, height
        return 1

    def repository_capacity(
        self,
        rows: list[TreeRow],
        width: int,
        height: int,
        selected_index: int,
        card_height: int,
    ) -> int:
        del rows, width, height, selected_index, card_height
        return 0

    def hit_target(
        self,
        rows: list[TreeRow],
        width: int,
        height: int,
        selected_index: int,
        card_height: int,
        mouse_column: int,
        mouse_row: int,
    ) -> HitTarget:
        del card_height
        placements = horizontal_layout(rows, width, height, selected_index)
        index = horizontal_index_at_mouse(
            mouse_column, mouse_row, placements
        )
        if index is None:
            return HitTarget(None)
        placement = next(item for item in placements if item.index == index)
        return HitTarget(
            index,
            mouse_column == horizontal_disclosure_column(
                rows[index], placement
            ),
        )


VIEWS: dict[str, View] = {
    "vertical": VerticalView(),
    "horizontal": HorizontalView(),
}


def view_for(orientation: str = DEFAULT_ORIENTATION) -> View:
    try:
        return VIEWS[orientation]
    except KeyError as error:
        raise ValueError(f"unknown orientation: {orientation}") from error
