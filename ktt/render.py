from __future__ import annotations

import time
import unicodedata

from .model import TabRecord, TreeRow
from .repository import RepositoryStatus


SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
SPINNER_INTERVAL = 0.12
VERDICT_BACKGROUNDS = {
    "ready_to_merge": ("1b5e36", "2f9c5c"),
    "blocked": ("7a2029", "c0394a"),
}
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
EDGE_STYLES = ("tapered", "stacked", "straight", "rounded", "wedge")
DEFAULT_EDGE_STYLE = EDGE_STYLES[0]
TREE_INDENT_WIDTH = 4
STATUS_CELL_WIDTH = 2
CONTROL_ROWS = (
    ("↑/↓ · j/k · wheel", "switch tab"),
    ("Enter · click", "enter tab"),
    ("Space · right-click", "fold tree"),
    ("e", "edge style"),
    ("r", "refresh"),
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
REPOSITORY_FOREGROUND = "8a93a3"
REPOSITORY_BRANCH_FOREGROUND = "5f7a82"
REPOSITORY_CLEAN_FOREGROUND = "698a72"
REPOSITORY_DIRTY_FOREGROUND = "9a7650"
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


def repository_state_text(status: RepositoryStatus, detailed: bool = True) -> str:
    if status.clean:
        return "✓ clean"
    if not detailed:
        return f"● {status.changed} changed"
    parts = []
    if status.conflicted:
        parts.append(f"{status.conflicted} conflict")
    if status.staged:
        parts.append(f"{status.staged} staged")
    if status.unstaged:
        parts.append(f"{status.unstaged} modified")
    if status.untracked:
        parts.append(f"{status.untracked} untracked")
    return "● " + " · ".join(parts or [f"{status.changed} changed"])


def repository_branch_text(status: RepositoryStatus) -> str:
    tracking = ""
    if status.ahead:
        tracking += f" ↑{status.ahead}"
    if status.behind:
        tracking += f" ↓{status.behind}"
    return f" {status.branch}{tracking}"


def _render_repository_line(
    text: str,
    width: int,
    color: str,
    *,
    ansi: bool,
    bold: bool = False,
) -> str:
    text = truncate_cells(text, width)
    padding = " " * max(0, (width - display_width(text)) // 2)
    weight = "\x1b[1m" if ansi and bold else ""
    return f"{panel_style(ansi)}{padding}{_fg(color, ansi)}{weight}{text}"


def render_repository_status(
    status: RepositoryStatus,
    width: int,
    max_lines: int,
    *,
    ansi: bool = True,
) -> list[str]:
    if max_lines <= 0 or width <= 0:
        return []
    branch = repository_branch_text(status)
    state = repository_state_text(status)
    state_color = (
        REPOSITORY_CLEAN_FOREGROUND
        if status.clean
        else REPOSITORY_DIRTY_FOREGROUND
    )
    if max_lines >= 3:
        return [
            _render_repository_line(
                f"{status.name}  {status.directory}", width,
                REPOSITORY_FOREGROUND, ansi=ansi, bold=True,
            ),
            _render_repository_line(
                branch, width, REPOSITORY_BRANCH_FOREGROUND, ansi=ansi,
            ),
            _render_repository_line(state, width, state_color, ansi=ansi),
        ]
    if max_lines == 2:
        return [
            _render_repository_line(
                f"{status.name}  {status.directory}", width,
                REPOSITORY_FOREGROUND, ansi=ansi, bold=True,
            ),
            _render_repository_line(
                f"{branch} · {state}", width, state_color, ansi=ansi,
            ),
        ]
    return [
        _render_repository_line(
            f"{status.name} · {branch} · {repository_state_text(status, False)}",
            width,
            state_color,
            ansi=ansi,
        )
    ]


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
        return "💬", "f1fa8c"
    if status == "✅":
        return "✓", None
    return (status or " "), None


def card_background(row: TreeRow) -> str:
    tab = row.tab
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
        base = _bg(background, True) + _fg(
            "f8f8f2" if verdict or tab.is_active else "d8dee9", True
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
    if show_caps and effective_style in {"tapered", "stacked"}:
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
    if edge_style == "stacked":
        return (
            f"{panel_style(ansi)}{left}{cap_style}{LEFT_CAP}{base}"
            f"{' ' * body_width}{cap_style}{verdict_cap or RIGHT_CAP}{reset}"
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
    repository_status: RepositoryStatus | None = None,
) -> str:
    available = content_height(height)
    card_height = adaptive_card_height(len(rows), height)
    capacity = card_capacity(available, card_height)
    start = visible_start(len(rows), selected_index, height, card_height)
    visible = rows[start:start + capacity]
    top_padding = vertical_padding(len(rows), height, card_height)
    repository_lines = (
        render_repository_status(
            repository_status, width, min(3, top_padding), ansi=ansi
        )
        if repository_status is not None
        else []
    )
    output = [*repository_lines]
    output.extend("" for _ in range(top_padding - len(repository_lines)))
    for offset, row in enumerate(visible):
        if offset:
            output.extend("" for _ in range(card_gap(card_height)))
        output.extend(
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
    while len(output) < available:
        output.append("")
    if error and output:
        output[-1] = f" error: {error}"[:width]
    output.extend(
        render_control_line(
            shortcut,
            f"edge: {edge_style}" if shortcut == "e" else action,
            width,
            ansi=ansi,
        )
        for shortcut, action in CONTROL_ROWS
    )
    return "\n".join(output[:height])


def content_height(height: int) -> int:
    return max(0, height - len(CONTROL_LINES))


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
    card_height = card_height or adaptive_card_height(row_count, height)
    used = cards_height(row_count, card_height)
    if used >= available:
        return 0
    return (available - used) // 2
