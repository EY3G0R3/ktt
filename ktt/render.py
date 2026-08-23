from __future__ import annotations

from dataclasses import dataclass
import time
import unicodedata

from .model import TabRecord, TreeRow


SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
SPINNER_INTERVAL = 0.12
VERDICT_BACKGROUNDS = {
    "ready_to_merge": ("1b5e36", "2f9c5c"),
    "blocked": ("7a2029", "c0394a"),
}
WAITING_BACKGROUNDS = ("d8dee9", "f8f8f2")
PANEL_BACKGROUND = "000000"
ACTIVE_BACKGROUND = "4c566a"
ACTIVE_DESCENDANT_BACKGROUND = "343b49"
INACTIVE_BACKGROUND = "20232a"
LEFT_CAP = ""
RIGHT_CAP = ""
FLAME_RIGHT_CAP = ""
READY_RIGHT_CAP = ""
WEDGE_TOP_LEFT = ""
WEDGE_TOP_RIGHT = ""
WEDGE_BOTTOM_LEFT = ""
WEDGE_BOTTOM_RIGHT = ""
EDGE_STYLES = ("tapered", "straight", "rounded", "wedge")
DEFAULT_EDGE_STYLE = EDGE_STYLES[0]
ORIENTATIONS = ("vertical", "horizontal")
DEFAULT_ORIENTATION = ORIENTATIONS[0]
TREE_INDENT_WIDTH = 4
STATUS_CELL_WIDTH = 2
HORIZONTAL_MIN_CARD_WIDTH = 14
HORIZONTAL_CONTROL_TEXT = (
    "j/k switch · Enter/click enter · Space fold · e edges · t tabs · ? help · q quit"
)
CONTROL_ROWS = (
    ("↑/↓ · j/k · wheel", "switch tab"),
    ("Enter · click", "enter tab"),
    ("Space · right-click", "fold tree"),
    ("e", "edge style"),
    ("r", "refresh"),
    ("t", "native tab bar"),
    ("?", "pin help"),
    ("q", "quit"),
)
CONTROL_LEFT_WIDTH = max(len(shortcut) for shortcut, _ in CONTROL_ROWS)
CONTROL_RIGHT_WIDTH = max(
    max(len(action) for _, action in CONTROL_ROWS),
    max(len(f"edge: {style}") for style in EDGE_STYLES),
)
CONTROL_SEPARATOR = " │ "
CONTROL_SHORTCUT_FOREGROUND = "5f7a82"
CONTROL_SEPARATOR_FOREGROUND = "3f4552"
CONTROL_ACTION_FOREGROUND = "777d89"
REPOSITORY_TOP_GAP = 1
REPOSITORY_BOTTOM_MARGIN = 1
CONTROL_LINES = tuple(
    f"{shortcut:>{CONTROL_LEFT_WIDTH}}{CONTROL_SEPARATOR}"
    f"{(f'edge: {DEFAULT_EDGE_STYLE}' if shortcut == 'e' else action):<{CONTROL_RIGHT_WIDTH}}"
    for shortcut, action in CONTROL_ROWS
)


def next_edge_style(edge_style: str) -> str:
    try:
        index = EDGE_STYLES.index(edge_style)
    except ValueError:
        return DEFAULT_EDGE_STYLE
    return EDGE_STYLES[(index + 1) % len(EDGE_STYLES)]


def _fg(hex_color: str, enabled: bool) -> str:
    if not enabled:
        return ""
    red, green, blue = (int(hex_color[offset:offset + 2], 16) for offset in (0, 2, 4))
    return f"\x1b[38;2;{red};{green};{blue}m"


def _bg(hex_color: str, enabled: bool) -> str:
    if not enabled:
        return ""
    red, green, blue = (int(hex_color[offset:offset + 2], 16) for offset in (0, 2, 4))
    return f"\x1b[48;2;{red};{green};{blue}m"


def panel_style(ansi: bool = True) -> str:
    return _bg(PANEL_BACKGROUND, ansi) + _fg("f8f8f2", ansi)


def display_width(text: str) -> int:
    return sum(
        0 if unicodedata.combining(character)
        else 2 if unicodedata.east_asian_width(character) in {"W", "F"}
        else 1
        for character in text
    )


def fit_cells(text: str, width: int) -> str:
    fitted: list[str] = []
    used = 0
    for character in text:
        character_width = display_width(character)
        if used + character_width > width:
            break
        fitted.append(character)
        used += character_width
    return "".join(fitted) + (" " * (width - used))


def truncate_cells(text: str, width: int) -> str:
    if display_width(text) <= width:
        return text
    if width <= 1:
        return fit_cells("…", width).rstrip()
    return fit_cells(text, width - 1).rstrip() + "…"


def render_control_line(
    shortcut: str,
    action: str,
    width: int,
    *,
    ansi: bool = True,
) -> str:
    shortcut = f"{shortcut:>{CONTROL_LEFT_WIDTH}}"
    action = f"{action:<{CONTROL_RIGHT_WIDTH}}"
    plain = f"{shortcut}{CONTROL_SEPARATOR}{action}"
    if display_width(plain) > width:
        return f"{panel_style(ansi)}{truncate_cells(plain, width)}"
    padding = " " * ((width - display_width(plain)) // 2)
    return (
        f"{panel_style(ansi)}{padding}"
        f"{_fg(CONTROL_SHORTCUT_FOREGROUND, ansi)}{shortcut}"
        f"{_fg(CONTROL_SEPARATOR_FOREGROUND, ansi)}{CONTROL_SEPARATOR}"
        f"{_fg(CONTROL_ACTION_FOREGROUND, ansi)}{action}"
    )


def status_icon(status: str | None, now: float | None = None) -> tuple[str, str | None]:
    if status == "🤖":
        current = time.monotonic() if now is None else now
        frame = int(current / SPINNER_INTERVAL) % len(SPINNER_FRAMES)
        return SPINNER_FRAMES[frame], "8be9fd"
    if status == "ready_to_merge":
        return "✓", "50fa7b"
    if status == "blocked":
        return "✗", "ff5555"
    if status == "💬":
        return "💬", "20232a"
    if status == "✅":
        return "✓", None
    return (status or " "), None


def card_background(row: TreeRow) -> str:
    tab = row.tab
    if tab.status == "💬":
        return WAITING_BACKGROUNDS[1 if tab.is_active else 0]
    verdict = VERDICT_BACKGROUNDS.get(tab.status or "")
    if verdict:
        return verdict[1 if tab.is_active else 0]
    return (
        ACTIVE_BACKGROUND
        if tab.is_active
        else ACTIVE_DESCENDANT_BACKGROUND
        if row.has_active_descendant
        else INACTIVE_BACKGROUND
    )


@dataclass(frozen=True)
class HorizontalPlacement:
    index: int
    left: int
    width: int
    screen_row: int


def _horizontal_children(rows: list[TreeRow]) -> tuple[list[int], dict[int, list[int]]]:
    index_for_tab = {row.tab.id: index for index, row in enumerate(rows)}
    children = {index: [] for index in range(len(rows))}
    roots: list[int] = []
    for index, row in enumerate(rows):
        parent = index_for_tab.get(row.parent_tab_id)
        if parent is None:
            roots.append(index)
        else:
            children[parent].append(index)
    return roots, children


def _compact_horizontal_layout(
    rows: list[TreeRow], width: int, selected_index: int
) -> list[HorizontalPlacement]:
    usable = max(0, width - 1)
    if not rows or usable < 3:
        return []
    capacity = max(1, usable // HORIZONTAL_MIN_CARD_WIDTH)
    capacity = min(capacity, len(rows))
    start = min(
        max(0, selected_index - capacity // 2),
        max(0, len(rows) - capacity),
    )
    slot_width = usable // capacity
    return [
        HorizontalPlacement(
            index=index,
            left=offset * slot_width,
            width=(
                usable - offset * slot_width
                if offset == capacity - 1
                else slot_width
            ) - 1,
            screen_row=0,
        )
        for offset, index in enumerate(range(start, start + capacity))
    ]


def horizontal_layout(
    rows: list[TreeRow],
    width: int,
    height: int,
    selected_index: int,
) -> list[HorizontalPlacement]:
    """Lay out visible subtrees as proportional spans growing downward."""
    usable = max(0, width - 1)
    if not rows or usable < 3 or height <= 0:
        return []
    roots, children = _horizontal_children(rows)
    leaves: dict[int, int] = {}

    def leaf_count(index: int) -> int:
        if index not in leaves:
            leaves[index] = max(
                1, sum(leaf_count(child) for child in children[index])
            )
        return leaves[index]

    total_leaves = sum(leaf_count(root) for root in roots)
    if total_leaves <= 0 or usable // total_leaves < HORIZONTAL_MIN_CARD_WIDTH:
        return _compact_horizontal_layout(rows, width, selected_index)

    placements: list[HorizontalPlacement] = []

    def place(index: int, unit_start: int, unit_end: int) -> None:
        row = rows[index]
        screen_row = row.depth * 2
        left = unit_start * usable // total_leaves
        right = unit_end * usable // total_leaves
        card_width = max(1, right - left - 1)
        if screen_row < height:
            placements.append(
                HorizontalPlacement(index, left, card_width, screen_row)
            )
        child_start = unit_start
        for child in children[index]:
            child_end = child_start + leaf_count(child)
            place(child, child_start, child_end)
            child_start = child_end

    unit_start = 0
    for root in roots:
        unit_end = unit_start + leaf_count(root)
        place(root, unit_start, unit_end)
        unit_start = unit_end
    return placements


def horizontal_index_at_mouse(
    mouse_column: int,
    mouse_row: int,
    placements: list[HorizontalPlacement],
) -> int | None:
    column = mouse_column - 1
    row = mouse_row - 1
    return next(
        (
            placement.index
            for placement in placements
            if placement.screen_row == row
            and placement.left <= column < placement.left + placement.width
        ),
        None,
    )


def adaptive_card_height(row_count: int, height: int) -> int:
    available = content_height(height)
    if row_count > 0 and cards_height(row_count, 3) <= available:
        return 3
    if row_count > 0 and cards_height(row_count, 2) <= available:
        return 2
    return 1


def card_content_line(card_height: int) -> int:
    return max(0, (card_height - 1) // 2)


def card_gap(card_height: int) -> int:
    return 1 if card_height > 1 else 0


def cards_height(row_count: int, card_height: int) -> int:
    if row_count <= 0:
        return 0
    return row_count * card_height + (row_count - 1) * card_gap(card_height)


def card_capacity(available: int, card_height: int) -> int:
    gap = card_gap(card_height)
    return max(0, (available + gap) // (card_height + gap))


def render_row(
    row: TreeRow,
    *,
    selected: bool,
    width: int,
    now: float | None = None,
    ansi: bool = True,
    edge_style: str = DEFAULT_EDGE_STYLE,
    line_index: int = 0,
    card_height: int = 1,
) -> str:
    tab = row.tab
    disclosure = "▸" if row.is_collapsed else "▾" if row.has_children else " "
    indent = " " * (TREE_INDENT_WIDTH * row.depth)
    orphan = "?" if row.orphaned else " "
    icon, status_color = status_icon(tab.status, now)
    status_text = fit_cells(icon, STATUS_CELL_WIDTH)
    left = indent
    card_prefix_width = (
        display_width(disclosure)
        + display_width(orphan)
        + STATUS_CELL_WIDTH
        + 1
    )
    # Keep the final terminal column untouched. Drawing a cap there sets the
    # terminal's pending-wrap flag, so the following newline can create a blank
    # row and visually split the tree.
    card_width = max(1, width - len(left) - 1)
    show_caps = card_width >= 3
    body_width = card_width - 2 if show_caps else card_width
    remaining = max(1, body_width - card_prefix_width)
    title = truncate_cells(tab.title, remaining)
    card_content_width = min(body_width, card_prefix_width + display_width(title))

    base = ""
    verdict = VERDICT_BACKGROUNDS.get(tab.status or "")
    background = card_background(row)
    if ansi:
        foreground = (
            "20232a"
            if tab.status == "💬"
            else "f8f8f2"
            if verdict or tab.is_active
            else "d8dee9"
        )
        base = _bg(background, True) + _fg(
            foreground, True
        )
        if tab.is_active:
            base += "\x1b[1m"
    reset = "\x1b[0m" if ansi else ""
    restore = reset + base if ansi else ""
    status = (
        f"{_fg(status_color, ansi) if status_color else ''}{status_text}"
        f"{restore if status_color else ''}"
    )
    cap_style = f"{_bg('000000', ansi)}{_fg(background, ansi)}"
    verdict_cap = (
        READY_RIGHT_CAP
        if tab.status == "ready_to_merge"
        else FLAME_RIGHT_CAP
        if tab.status == "blocked"
        else None
    )
    effective_style = (
        DEFAULT_EDGE_STYLE
        if card_height == 1 and edge_style in {"rounded", "wedge"}
        else edge_style
    )
    if show_caps and effective_style == "tapered":
        left_cap = f"{cap_style}{LEFT_CAP}{base}"
        right_cap = f"{cap_style}{verdict_cap or RIGHT_CAP}"
    elif show_caps and effective_style == "straight":
        left_cap = f"{base} "
        right_cap = f"{cap_style}{verdict_cap}" if verdict_cap else f"{base} "
    elif show_caps and effective_style == "rounded":
        left_edge = "╭" if card_height == 2 and line_index == 0 else "│"
        right_edge = "╮" if card_height == 2 and line_index == 0 else "│"
        left_cap = f"{cap_style}{left_edge}{base}"
        right_cap = f"{cap_style}{verdict_cap or right_edge}"
    elif show_caps and effective_style == "wedge":
        left_edge = WEDGE_TOP_LEFT if line_index == 0 else " "
        right_edge = WEDGE_TOP_RIGHT if line_index == 0 else " "
        left_cap = (
            f"{cap_style}{left_edge}{base}"
            if line_index == 0
            else f"{base} "
        )
        right_cap = (
            f"{cap_style}{verdict_cap or right_edge}"
            if line_index == 0 or verdict_cap
            else f"{base} "
        )
    else:
        left_cap = base
        right_cap = ""
    return (
        f"{panel_style(ansi)}{left}{left_cap}{disclosure}{orphan}{status}"
        f" {title}{' ' * max(0, body_width - card_content_width)}"
        f"{right_cap}{reset}"
    )


def render_card_blank(
    row: TreeRow,
    *,
    width: int,
    ansi: bool = True,
    edge_style: str = DEFAULT_EDGE_STYLE,
    line_index: int = 0,
    card_height: int = 3,
) -> str:
    left = " " * (TREE_INDENT_WIDTH * row.depth)
    card_width = max(1, width - len(left) - 1)
    show_caps = card_width >= 3
    body_width = card_width - 2 if show_caps else card_width
    background = card_background(row)
    base = _bg(background, ansi)
    reset = "\x1b[0m" if ansi else ""
    if not show_caps:
        return f"{panel_style(ansi)}{left}{base}{' ' * body_width}{reset}"
    verdict_cap = (
        READY_RIGHT_CAP
        if row.tab.status == "ready_to_merge"
        else FLAME_RIGHT_CAP
        if row.tab.status == "blocked"
        else None
    )
    cap_style = f"{_bg(PANEL_BACKGROUND, ansi)}{_fg(background, ansi)}"
    if edge_style == "tapered":
        right_edge = (
            f"{cap_style}{verdict_cap}" if verdict_cap else f"{panel_style(ansi)} "
        )
        return (
            f"{panel_style(ansi)}{left} {base}{' ' * body_width}{reset}"
            f"{right_edge}{reset}"
        )
    if edge_style == "straight":
        right_edge = f"{cap_style}{verdict_cap}" if verdict_cap else f"{base} "
        return (
            f"{panel_style(ansi)}{left}{base}{' ' * (body_width + 1)}"
            f"{right_edge}{reset}"
        )
    if edge_style == "rounded":
        bottom = line_index == card_height - 1
        left_edge, right_edge = ("╰", "╯") if bottom else ("╭", "╮")
        return (
            f"{panel_style(ansi)}{left}{cap_style}{left_edge}"
            f"{'─' * body_width}{right_edge}{reset}"
        )
    if edge_style == "wedge":
        bottom = line_index == card_height - 1
        left_edge = WEDGE_BOTTOM_LEFT if bottom else WEDGE_TOP_LEFT
        right_edge = WEDGE_BOTTOM_RIGHT if bottom else WEDGE_TOP_RIGHT
        return (
            f"{panel_style(ansi)}{left}{cap_style}{left_edge}{base}"
            f"{' ' * body_width}{cap_style}{verdict_cap or right_edge}{reset}"
        )
    raise ValueError(f"unknown edge style: {edge_style}")


def render_card(
    row: TreeRow,
    *,
    selected: bool,
    width: int,
    card_height: int,
    now: float | None = None,
    ansi: bool = True,
    edge_style: str = DEFAULT_EDGE_STYLE,
) -> list[str]:
    content_line = card_content_line(card_height)
    return [
        render_row(
            row,
            selected=selected,
            width=width,
            now=now,
            ansi=ansi,
            edge_style=edge_style,
            line_index=line,
            card_height=card_height,
        )
        if line == content_line
        else render_card_blank(
            row,
            width=width,
            ansi=ansi,
            edge_style=edge_style,
            line_index=line,
            card_height=card_height,
        )
        for line in range(card_height)
    ]


def render_horizontal_card(
    row: TreeRow,
    *,
    width: int,
    now: float | None = None,
    ansi: bool = True,
    edge_style: str = DEFAULT_EDGE_STYLE,
) -> str:
    if width <= 0:
        return ""
    tab = row.tab
    disclosure = "▸" if row.is_collapsed else "▾" if row.has_children else " "
    orphan = "?" if row.orphaned else " "
    icon, status_color = status_icon(tab.status, now)
    status_text = fit_cells(icon, STATUS_CELL_WIDTH)
    show_caps = width >= 3
    body_width = width - 2 if show_caps else width
    prefix_width = 2 + STATUS_CELL_WIDTH + 1
    title = truncate_cells(tab.title, max(0, body_width - prefix_width))
    content_width = min(
        body_width, prefix_width + display_width(title)
    )
    left_padding = max(0, (body_width - content_width) // 2)
    right_padding = max(0, body_width - content_width - left_padding)

    background = card_background(row)
    verdict = VERDICT_BACKGROUNDS.get(tab.status or "")
    foreground = (
        "20232a"
        if tab.status == "💬"
        else "f8f8f2"
        if verdict or tab.is_active
        else "d8dee9"
    )
    base = _bg(background, ansi) + _fg(foreground, ansi)
    if ansi and tab.is_active:
        base += "\x1b[1m"
    reset = "\x1b[0m" if ansi else ""
    restore = reset + base if ansi else ""
    status = (
        f"{_fg(status_color, ansi) if status_color else ''}{status_text}"
        f"{restore if status_color else ''}"
    )
    content = (
        f"{' ' * left_padding}{disclosure}{orphan}{status} {title}"
        f"{' ' * right_padding}"
    )
    if not show_caps:
        return f"{base}{fit_cells(content, body_width)}{reset}"

    cap_style = f"{_bg(PANEL_BACKGROUND, ansi)}{_fg(background, ansi)}"
    verdict_cap = (
        READY_RIGHT_CAP
        if tab.status == "ready_to_merge"
        else FLAME_RIGHT_CAP
        if tab.status == "blocked"
        else None
    )
    effective_style = (
        DEFAULT_EDGE_STYLE if edge_style in {"rounded", "wedge"} else edge_style
    )
    if effective_style == "straight":
        left_cap = f"{base} "
        right_cap = f"{cap_style}{verdict_cap}" if verdict_cap else f"{base} "
    else:
        left_cap = f"{cap_style}{LEFT_CAP}{base}"
        right_cap = f"{cap_style}{verdict_cap or RIGHT_CAP}"
    return f"{left_cap}{content}{right_cap}{reset}"


def horizontal_disclosure_column(
    row: TreeRow, placement: HorizontalPlacement
) -> int:
    body_width = placement.width - 2 if placement.width >= 3 else placement.width
    prefix_width = 2 + STATUS_CELL_WIDTH + 1
    title = truncate_cells(row.tab.title, max(0, body_width - prefix_width))
    content_width = min(body_width, prefix_width + display_width(title))
    left_padding = max(0, (body_width - content_width) // 2)
    cap_width = 1 if placement.width >= 3 else 0
    return placement.left + cap_width + left_padding + 1


def _connector_lines(
    rows: list[TreeRow],
    placements: list[HorizontalPlacement],
    width: int,
) -> dict[int, str]:
    if not placements or len({item.screen_row for item in placements}) == 1:
        return {}
    placement_for_index = {item.index: item for item in placements}
    index_for_tab = {row.tab.id: index for index, row in enumerate(rows)}
    masks: dict[int, list[int]] = {}
    left_bit, right_bit, up_bit, down_bit = 1, 2, 4, 8
    for child_index, child in placement_for_index.items():
        parent_index = index_for_tab.get(rows[child_index].parent_tab_id)
        parent = placement_for_index.get(parent_index) if parent_index is not None else None
        if parent is None or child.screen_row != parent.screen_row + 2:
            continue
        connector_row = parent.screen_row + 1
        cells = masks.setdefault(connector_row, [0] * max(0, width - 1))
        parent_center = parent.left + max(0, parent.width - 1) // 2
        child_center = child.left + max(0, child.width - 1) // 2
        low, high = sorted((parent_center, child_center))
        for column in range(low, min(high + 1, len(cells))):
            if column > low:
                cells[column] |= left_bit
            if column < high:
                cells[column] |= right_bit
        if parent_center < len(cells):
            cells[parent_center] |= up_bit
        if child_center < len(cells):
            cells[child_center] |= down_bit

    glyph = {
        0: " ",
        left_bit: "─",
        right_bit: "─",
        left_bit | right_bit: "─",
        up_bit: "│",
        down_bit: "│",
        up_bit | down_bit: "│",
        right_bit | up_bit: "└",
        left_bit | up_bit: "┘",
        right_bit | down_bit: "┌",
        left_bit | down_bit: "┐",
        left_bit | right_bit | up_bit: "┴",
        left_bit | right_bit | down_bit: "┬",
        right_bit | up_bit | down_bit: "├",
        left_bit | up_bit | down_bit: "┤",
        left_bit | right_bit | up_bit | down_bit: "┼",
    }
    return {
        screen_row: "".join(glyph.get(mask, "┼") for mask in cells).rstrip()
        for screen_row, cells in masks.items()
    }


def horizontal_repository_capacity(
    rows: list[TreeRow],
    width: int,
    height: int,
    selected_index: int,
) -> int:
    placements = horizontal_layout(rows, width, height, selected_index)
    tree_height = max(
        (placement.screen_row + 1 for placement in placements), default=0
    )
    return max(0, height - tree_height - REPOSITORY_TOP_GAP - REPOSITORY_BOTTOM_MARGIN)


def render_horizontal_screen(
    rows: list[TreeRow],
    selected_index: int,
    os_window_id: int,
    width: int,
    height: int,
    *,
    total_tabs: int | None = None,
    error: str | None = None,
    now: float | None = None,
    ansi: bool = True,
    edge_style: str = DEFAULT_EDGE_STYLE,
    repository_lines: list[str] | None = None,
    show_controls: bool = True,
    help_pinned: bool = False,
) -> str:
    del os_window_id, total_tabs, help_pinned
    placements = horizontal_layout(rows, width, height, selected_index)
    output = ["" for _ in range(height)]
    by_screen_row: dict[int, list[HorizontalPlacement]] = {}
    for placement in placements:
        by_screen_row.setdefault(placement.screen_row, []).append(placement)
    for screen_row, items in by_screen_row.items():
        if screen_row >= height:
            continue
        cursor = 0
        line = panel_style(ansi)
        for placement in sorted(items, key=lambda item: item.left):
            line += " " * max(0, placement.left - cursor)
            line += render_horizontal_card(
                rows[placement.index],
                width=placement.width,
                now=now,
                ansi=ansi,
                edge_style=edge_style,
            )
            cursor = placement.left + placement.width
        output[screen_row] = line

    connectors = _connector_lines(rows, placements, width)
    for screen_row, line in connectors.items():
        if screen_row < height:
            output[screen_row] = (
                f"{panel_style(ansi)}{_fg(CONTROL_SEPARATOR_FOREGROUND, ansi)}{line}"
            )

    tree_height = max(
        (placement.screen_row + 1 for placement in placements), default=0
    )
    context_capacity = horizontal_repository_capacity(
        rows, width, height, selected_index
    )
    context = (repository_lines or [])[:context_capacity]
    context_start = height - REPOSITORY_BOTTOM_MARGIN - len(context)
    if context:
        output[context_start:context_start + len(context)] = context

    free_start = tree_height
    free_end = context_start if context else height - REPOSITORY_BOTTOM_MARGIN
    if show_controls and free_end > free_start:
        text = truncate_cells(HORIZONTAL_CONTROL_TEXT, width)
        padding = " " * max(0, (width - display_width(text)) // 2)
        control_row = free_start + (free_end - free_start - 1) // 2
        output[control_row] = (
            f"{panel_style(ansi)}{_fg(CONTROL_ACTION_FOREGROUND, ansi)}"
            f"{padding}{text}"
        )
    if error:
        blank = next(
            (index for index in range(height - 1, -1, -1) if not output[index]),
            None,
        )
        if blank is not None:
            output[blank] = f" error: {error}"[:width]
    return "\n".join(output)


def render_screen(
    rows: list[TreeRow],
    selected_index: int,
    os_window_id: int,
    width: int,
    height: int,
    *,
    total_tabs: int | None = None,
    error: str | None = None,
    now: float | None = None,
    ansi: bool = True,
    edge_style: str = DEFAULT_EDGE_STYLE,
    repository_lines: list[str] | None = None,
    show_controls: bool = True,
    help_pinned: bool = False,
) -> str:
    available = content_height(height)
    card_height = adaptive_card_height(len(rows), height)
    capacity = card_capacity(available, card_height)
    start = visible_start(len(rows), selected_index, height, card_height)
    visible = rows[start:start + capacity]
    top_padding = vertical_padding(len(rows), height, card_height)
    bottom_padding = vertical_bottom_padding(len(rows), height, card_height)
    context_spacing = REPOSITORY_TOP_GAP + REPOSITORY_BOTTOM_MARGIN
    context = (repository_lines or [])[:max(0, bottom_padding - context_spacing)]
    cards: list[str] = []
    for offset, row in enumerate(visible):
        if offset:
            cards.extend("" for _ in range(card_gap(card_height)))
        cards.extend(
            render_card(
                row,
                selected=(start + offset == selected_index),
                width=width,
                card_height=card_height,
                now=now,
                ansi=ansi,
                edge_style=edge_style,
            )
        )
    output = ["" for _ in range(height)]
    for index, line in enumerate(cards, start=top_padding):
        if index >= height:
            break
        output[index] = line
    if show_controls and top_padding >= len(CONTROL_ROWS):
        controls = list(
            render_control_line(
                shortcut,
                f"edge: {edge_style}"
                if shortcut == "e"
                else "unpin help"
                if shortcut == "?" and help_pinned
                else action,
                width,
                ansi=ansi,
            )
            for shortcut, action in CONTROL_ROWS
        )
        control_start = (top_padding - len(controls)) // 2
        output[control_start:control_start + len(controls)] = controls
    if context:
        context_start = height - REPOSITORY_BOTTOM_MARGIN - len(context)
        output[context_start:context_start + len(context)] = context
    if error:
        blank = next(
            (index for index in range(height - 1, -1, -1) if not output[index]),
            None,
        )
        if blank is not None:
            output[blank] = f" error: {error}"[:width]
    return "\n".join(output)


def content_height(height: int) -> int:
    # Help and repository context live in the free space around the vertically
    # centered cards. They never reserve rows or shift the tab stack.
    return max(0, height)


def visible_start(
    row_count: int,
    selected_index: int,
    height: int,
    card_height: int | None = None,
) -> int:
    available = content_height(height)
    card_height = card_height or adaptive_card_height(row_count, height)
    capacity = card_capacity(available, card_height)
    if capacity and selected_index >= capacity:
        return min(selected_index - capacity + 1, max(0, row_count - capacity))
    return 0


def vertical_padding(
    row_count: int,
    height: int,
    card_height: int | None = None,
) -> int:
    available = content_height(height)
    if row_count == 0:
        return available
    card_height = card_height or adaptive_card_height(row_count, height)
    used = cards_height(row_count, card_height)
    if used >= available:
        return 0
    return (available - used) // 2


def vertical_bottom_padding(
    row_count: int,
    height: int,
    card_height: int | None = None,
) -> int:
    available = content_height(height)
    if row_count == 0:
        return 0
    card_height = card_height or adaptive_card_height(row_count, height)
    used = cards_height(row_count, card_height)
    return max(0, available - used - vertical_padding(
        row_count, height, card_height
    ))
