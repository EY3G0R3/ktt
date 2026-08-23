from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import select
import shutil
import sys
import termios
import time
import tty

from .kitty import KittyError, RemoteControl
from .model import (
    TabRecord,
    TreeRow,
    choose_os_window,
    records_for_os_window,
    tree_rows,
    with_active_tab,
)
from .render import (
    DEFAULT_EDGE_STYLE,
    TREE_INDENT_WIDTH,
    adaptive_card_height,
    card_gap,
    card_content_line,
    content_height,
    panel_style,
    next_edge_style,
    render_screen,
    vertical_padding,
    visible_start,
)
from .repository import FancylogMonitor, active_window_cwd


MOUSE_PATTERN = re.compile(r"\x1b\[<(\d+);(\d+);(\d+)([Mm])")


@dataclass(frozen=True)
class MouseEvent:
    button: str
    column: int
    row: int
    pressed: bool


def parse_mouse_event(value: str) -> MouseEvent | None:
    # A PTY read can contain both the press and release reports. Acting on the
    # first complete report keeps an ordinary click reliable in that case.
    match = MOUSE_PATTERN.search(value)
    if match is None:
        return None
    code, column, row, terminator = match.groups()
    button_code = int(code)
    if button_code & 32:
        return None
    buttons = {
        0: "left",
        1: "middle",
        2: "right",
        64: "wheel_up",
        65: "wheel_down",
    }
    button = buttons.get(button_code & 67)
    if button is None:
        return None
    return MouseEvent(
        button=button,
        column=int(column),
        row=int(row),
        pressed=terminator == "M",
    )


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
    if mouse_row < first_row or mouse_row > content_height(height):
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


def active_row_index(rows: list[TreeRow]) -> int:
    active = next(
        (index for index, row in enumerate(rows) if row.tab.is_active),
        None,
    )
    if active is not None:
        return active
    return next(
        (index for index, row in enumerate(rows) if row.has_active_descendant),
        0,
    )


def restart_arguments(arguments: list[str], edge_style: str) -> list[str]:
    result: list[str] = []
    skip_value = False
    for argument in arguments:
        if skip_value:
            skip_value = False
            continue
        if argument == "--edge-style":
            skip_value = True
            continue
        if argument.startswith("--edge-style="):
            continue
        result.append(argument)
    return [*result, "--edge-style", edge_style]


def source_stamp() -> tuple[tuple[str, int, int], ...]:
    package = Path(__file__).resolve().parent
    return tuple(
        (path.name, path.stat().st_mtime_ns, path.stat().st_size)
        for path in sorted(package.glob("*.py"))
    )


class TerminalMode:
    def __enter__(self) -> "TerminalMode":
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise RuntimeError("interactive mode requires a terminal; use `ktt list`")
        self.fd = sys.stdin.fileno()
        self.previous = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h")
        sys.stdout.flush()
        return self

    def __exit__(self, *_error: object) -> None:
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.previous)
        sys.stdout.write("\x1b[0m\x1b[?1000l\x1b[?1006l\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()

    def read_key(self, timeout: float) -> str | None:
        readable, _, _ = select.select([self.fd], [], [], timeout)
        if not readable:
            return None
        return os.read(self.fd, 64).decode(errors="ignore")


def run_tui(
    remote: RemoteControl,
    target_os_window_id: int | None,
    poll_interval: float,
    auto_reload: bool = True,
    edge_style: str = DEFAULT_EDGE_STYLE,
) -> int:
    selected_index = 0
    records: list[TabRecord] = []
    rows: list[TreeRow] = []
    collapsed_tab_ids: set[int] = set()
    os_window_id = target_os_window_id or 0
    error: str | None = None
    repository_path: str | None = None
    repository_monitor = FancylogMonitor()
    next_poll = 0.0
    next_source_check = 0.0
    initial_source_stamp = source_stamp() if auto_reload else ()
    restart = False
    self_window_id = int(os.environ["KITTY_WINDOW_ID"]) if os.environ.get("KITTY_WINDOW_ID", "").isdigit() else None

    def preview_selected() -> None:
        nonlocal error, next_poll, records, rows, selected_index
        if not rows or self_window_id is None:
            return
        target_tab_id = rows[selected_index].tab.id
        try:
            remote.preview_tab(target_tab_id, self_window_id)
            records = with_active_tab(records, target_tab_id)
            rows = tree_rows(records, collapsed_tab_ids)
            selected_index = active_row_index(rows)
            error = None
            next_poll = 0.0
        except KittyError as caught:
            error = str(caught)

    with TerminalMode() as terminal:
        while True:
            now = time.monotonic()
            if auto_reload and now >= next_source_check:
                if source_stamp() != initial_source_stamp:
                    restart = True
                    break
                next_source_check = now + 0.5
            if now >= next_poll:
                try:
                    snapshot = remote.snapshot()
                    os_window = choose_os_window(
                        snapshot, target_os_window_id, self_window_id
                    )
                    os_window_id = int(os_window["id"])
                    records = records_for_os_window(os_window)
                    collapsed_tab_ids.intersection_update(
                        record.id for record in records
                    )
                    rows = tree_rows(records, collapsed_tab_ids)
                    selected_index = active_row_index(rows)
                    repository_path = active_window_cwd(os_window)
                    error = None
                except (KittyError, ValueError) as caught:
                    error = str(caught)
                next_poll = now + poll_interval

            width, height = shutil.get_terminal_size((40, 24))
            card_height = adaptive_card_height(len(rows), height)
            repository_lines = repository_monitor.update(
                repository_path,
                width,
                min(3, vertical_padding(len(rows), height, card_height)),
                now,
            )
            screen = render_screen(
                rows, selected_index, os_window_id, width, height,
                total_tabs=len(records), error=error, now=now,
                edge_style=edge_style,
                repository_lines=repository_lines,
            )
            # Erase with ktt's own black background. Kitty's configured default
            # can change when the OS window gains focus, which otherwise makes
            # inactive gray cards disappear into the panel.
            sys.stdout.write(panel_style() + "\x1b[H\x1b[2J" + screen)
            sys.stdout.flush()
            key = terminal.read_key(min(0.05, max(0.0, next_poll - time.monotonic())))
            if key is None:
                continue
            mouse = parse_mouse_event(key)
            if mouse is not None and mouse.pressed and rows:
                if mouse.button in {"wheel_up", "wheel_down"}:
                    previous_index = selected_index
                    direction = -1 if mouse.button == "wheel_up" else 1
                    selected_index = min(
                        len(rows) - 1, max(0, selected_index + direction)
                    )
                    if selected_index != previous_index:
                        preview_selected()
                else:
                    card_height = adaptive_card_height(len(rows), height)
                    start = visible_start(
                        len(rows), selected_index, height, card_height
                    )
                    top_padding = vertical_padding(
                        len(rows), height, card_height
                    )
                    clicked_index = row_index_at_mouse(
                        mouse.row,
                        start=start,
                        row_count=len(rows),
                        height=height,
                        top_padding=top_padding,
                        card_height=card_height,
                    )
                    if clicked_index is not None:
                        clicked = rows[clicked_index]
                        line_in_card = (
                            mouse.row - 1 - top_padding
                        ) % (card_height + card_gap(card_height))
                        toggle = clicked.has_children and (
                            mouse.button == "right"
                            or (
                                line_in_card == card_content_line(card_height)
                                and mouse.column == disclosure_column(clicked)
                            )
                        )
                        if toggle:
                            if clicked.tab.id in collapsed_tab_ids:
                                collapsed_tab_ids.remove(clicked.tab.id)
                            else:
                                collapsed_tab_ids.add(clicked.tab.id)
                            rows = tree_rows(records, collapsed_tab_ids)
                            selected_index = active_row_index(rows)
                        elif mouse.button == "left":
                            try:
                                remote.focus_tab(clicked.tab.id)
                                error = None
                                next_poll = 0.0
                            except KittyError as caught:
                                error = str(caught)
                continue
            if key in {"q", "\x03"}:
                return 0
            previous_index = selected_index
            preview_after_move = False
            if key in {"k", "\x1b[A"} and rows:
                selected_index = (selected_index - 1) % len(rows)
                preview_after_move = True
            elif key in {"j", "\x1b[B"} and rows:
                selected_index = (selected_index + 1) % len(rows)
                preview_after_move = True
            elif key == "g" and rows:
                selected_index = 0
                preview_after_move = True
            elif key == "G" and rows:
                selected_index = len(rows) - 1
                preview_after_move = True
            elif key in {" ", "h", "l"} and rows and rows[selected_index].has_children:
                selected = rows[selected_index]
                should_collapse = (
                    key == "h" or (key == " " and not selected.is_collapsed)
                )
                should_expand = (
                    key == "l" or (key == " " and selected.is_collapsed)
                )
                if should_collapse:
                    collapsed_tab_ids.add(selected.tab.id)
                elif should_expand:
                    collapsed_tab_ids.discard(selected.tab.id)
                rows = tree_rows(records, collapsed_tab_ids)
                selected_index = active_row_index(rows)
            elif key in {"\r", "\n"} and rows:
                try:
                    active_tab = next(
                        (record for record in records if record.is_active),
                        rows[selected_index].tab,
                    )
                    remote.focus_tab(active_tab.id)
                    error = None
                    next_poll = 0.0
                except KittyError as caught:
                    error = str(caught)
            elif key == "r":
                repository_monitor.invalidate()
                next_poll = 0.0
            elif key == "e":
                edge_style = next_edge_style(edge_style)
            if preview_after_move and selected_index != previous_index:
                preview_selected()

    if restart:
        os.environ["KTT_EDGE_STYLE"] = edge_style
        os.execv(
            sys.executable,
            [
                sys.executable,
                "-m",
                "ktt",
                *restart_arguments(sys.argv[1:], edge_style),
            ],
        )
    return 0
