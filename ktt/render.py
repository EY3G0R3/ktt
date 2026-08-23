from __future__ import annotations

import time
import unicodedata

from .model import TabRecord, TreeRow


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
STATUS_CELL_WIDTH = 2
CONTROL_ROWS = (
    ("↑/↓ · j/k · wheel", "switch tab"),
    ("Enter · click", "enter tab"),
    ("Space · right-click", "fold tree"),
    ("r", "refresh"),
    ("q", "quit"),
)
CONTROL_LEFT_WIDTH = max(len(shortcut) for shortcut, _ in CONTROL_ROWS)
CONTROL_RIGHT_WIDTH = max(len(action) for _, action in CONTROL_ROWS)
CONTROL_SEPARATOR = " │ "
CONTROL_LINES = tuple(
    f"{shortcut:>{CONTROL_LEFT_WIDTH}}{CONTROL_SEPARATOR}{action:<{CONTROL_RIGHT_WIDTH}}"
    for shortcut, action in CONTROL_ROWS
)


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
        f"{panel_style(ansi)}{padding}{_fg('8be9fd', ansi)}{shortcut}"
        f"{_fg('6272a4', ansi)}{CONTROL_SEPARATOR}"
        f"{_fg('f8f8f2', ansi)}{action}"
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
        return "💬", "f1fa8c"
    if status == "✅":
        return "✓", None
    return (status or " "), None


def render_row(
    row: TreeRow,
    *,
    selected: bool,
    width: int,
    now: float | None = None,
    ansi: bool = True,
) -> str:
    tab = row.tab
    disclosure = "▸" if row.is_collapsed else "▾" if row.has_children else " "
    indent = "  " * row.depth
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
    if verdict:
        background = verdict[1 if tab.is_active else 0]
    else:
        background = (
            ACTIVE_BACKGROUND
            if tab.is_active
            else ACTIVE_DESCENDANT_BACKGROUND
            if row.has_active_descendant
            else INACTIVE_BACKGROUND
        )
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
    left_cap = f"{cap_style}{LEFT_CAP}{base}" if show_caps else base
    if show_caps:
        if tab.status == "ready_to_merge":
            right_cap = f"{cap_style}{READY_RIGHT_CAP}"
        elif tab.status == "blocked":
            right_cap = f"{cap_style}{FLAME_RIGHT_CAP}"
        else:
            right_cap = f"{cap_style}{RIGHT_CAP}"
    else:
        right_cap = ""
    return (
        f"{panel_style(ansi)}{left}{left_cap}{disclosure}{orphan}{status}"
        f" {title}{' ' * max(0, body_width - card_content_width)}"
        f"{right_cap}{reset}"
    )


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
) -> str:
    available = content_height(height)
    start = visible_start(len(rows), selected_index, height)
    visible = rows[start:start + available]
    output = ["" for _ in range(vertical_padding(len(rows), height))]
    output.extend(
        render_row(
            row,
            selected=(start + offset == selected_index),
            width=width,
            now=now,
            ansi=ansi,
        )
        for offset, row in enumerate(visible)
    )
    while len(output) < available:
        output.append("")
    if error and output:
        output[-1] = f" error: {error}"[:width]
    output.extend(
        render_control_line(shortcut, action, width, ansi=ansi)
        for shortcut, action in CONTROL_ROWS
    )
    return "\n".join(output[:height])


def content_height(height: int) -> int:
    return max(0, height - len(CONTROL_LINES))


def visible_start(row_count: int, selected_index: int, height: int) -> int:
    available = content_height(height)
    if available and selected_index >= available:
        return min(selected_index - available + 1, max(0, row_count - available))
    return 0


def vertical_padding(row_count: int, height: int) -> int:
    available = content_height(height)
    if row_count >= available:
        return 0
    return (available - row_count) // 2
