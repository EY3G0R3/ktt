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

from .events import TabEventListener, navigation_direction
from .folds import read_folded_tab_ids, write_folded_tab_ids
from .kitty import KittyError, RemoteControl
from .model import (
    TabRecord,
    TreeRow,
    WORKING_STATUS,
    active_tree_row_index,
    adjacent_tree_tab_id,
    choose_os_window,
    records_for_os_window,
    tree_rows,
    with_active_tab,
)
from .order import VisibleOrderPublisher
from .render import (
    DEFAULT_EDGE_STYLE,
    DEFAULT_ORIENTATION,
    SPINNER_INTERVAL,
    panel_style,
    next_edge_style,
)
from .repository import (
    DEFAULT_REPOSITORY_PALETTE,
    FancylogMonitor,
    MAX_REPOSITORY_LINES,
    active_window_cwd,
)
from .views import view_for


MOUSE_PATTERN = re.compile(r"\x1b\[<(\d+);(\d+);(\d+)([Mm])")
SOURCE_CHECK_INTERVAL = 1.0
NAVIGATION_STEP_INTERVAL = 0.05


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


active_row_index = active_tree_row_index


def take_navigation_step(pending: list[int]) -> int | None:
    """Consume at most one keypress so every tab transition can repaint."""
    return pending.pop(0) if pending else None


def navigation_poll_deadline(
    now: float,
    poll_interval: float,
    pending: list[int],
) -> float:
    return now + (
        NAVIGATION_STEP_INTERVAL if pending else poll_interval
    )


def enqueue_tab_events(pending: list[int], messages: tuple[bytes, ...]) -> bool:
    """Queue navigation and report whether an idle loop should wake now."""
    was_idle = not pending
    pending.extend(
        direction
        for message in messages
        if (direction := navigation_direction(message)) is not None
    )
    return was_idle


def animation_frame(rows: list[TreeRow], now: float) -> int | None:
    if not any(row.tab.status == WORKING_STATUS for row in rows):
        return None
    return int(now / SPINNER_INTERVAL)


def next_wake_timeout(
    now: float,
    *,
    next_poll: float,
    next_source_check: float,
    animated: bool,
    auto_reload: bool,
) -> float:
    deadlines = [next_poll]
    if auto_reload:
        deadlines.append(next_source_check)
    if animated:
        deadlines.append((int(now / SPINNER_INTERVAL) + 1) * SPINNER_INTERVAL)
    return max(0.0, min(deadlines) - now)


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


SourceStamp = tuple[tuple[str, int, int], ...]


def source_stamp() -> SourceStamp:
    package = Path(__file__).resolve().parent
    return tuple(
        (path.name, path.stat().st_mtime_ns, path.stat().st_size)
        for path in sorted(package.glob("*.py"))
    )


def reload_candidate(
    initial: SourceStamp,
    candidate: SourceStamp | None,
    current: SourceStamp,
) -> tuple[SourceStamp | None, bool]:
    if current == initial:
        return None, False
    if current != candidate:
        return current, False
    return candidate, True


def window_is_focused(snapshot: list[dict], window_id: int | None) -> bool:
    if window_id is None:
        return False
    return any(
        int(window.get("id", -1)) == window_id and bool(window.get("is_focused"))
        for os_window in snapshot
        for tab in os_window.get("tabs") or []
        for window in tab.get("windows") or []
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

    def read_key(
        self,
        timeout: float,
        tab_events: TabEventListener | None = None,
    ) -> tuple[str | None, tuple[bytes, ...]]:
        readers: list[object] = [self.fd]
        event_socket = tab_events.socket if tab_events is not None else None
        if event_socket is not None:
            readers.append(event_socket)
        readable, _, _ = select.select(readers, [], [], timeout)
        events = (
            tab_events.drain()
            if event_socket is not None
            and event_socket in readable
            and tab_events is not None
            else ()
        )
        key = (
            os.read(self.fd, 64).decode(errors="ignore")
            if self.fd in readable
            else None
        )
        return key, events


def run_tui(
    remote: RemoteControl,
    target_os_window_id: int | None,
    poll_interval: float,
    auto_reload: bool = True,
    edge_style: str = DEFAULT_EDGE_STYLE,
    repository_palette: str = DEFAULT_REPOSITORY_PALETTE,
    orientation: str = DEFAULT_ORIENTATION,
    embedded: bool = False,
) -> int:
    view = view_for(orientation)
    selected_index = 0
    records: list[TabRecord] = []
    rows: list[TreeRow] = []
    collapsed_tab_ids: set[int] = set()
    fold_state_os_window_id: int | None = None
    os_window_id = target_os_window_id or 0
    error: str | None = None
    repository_path: str | None = None
    sidebar_focused = False
    help_pinned = False
    pending_navigation: list[int] = []
    repository_monitor = FancylogMonitor(palette=repository_palette)
    next_poll = 0.0
    next_source_check = 0.0
    initial_source_stamp = source_stamp() if auto_reload else ()
    pending_source_stamp: SourceStamp | None = None
    last_render_signature: tuple[object, ...] | None = None
    restart = False
    self_window_id = int(os.environ["KITTY_WINDOW_ID"]) if os.environ.get("KITTY_WINDOW_ID", "").isdigit() else None

    def preview_selected() -> None:
        nonlocal error, next_poll, records, rows, selected_index
        if not rows or self_window_id is None:
            return
        target_tab_id = rows[selected_index].tab.id
        try:
            if embedded:
                remote.focus_tab(target_tab_id)
            else:
                remote.preview_tab(target_tab_id, self_window_id)
            records = with_active_tab(records, target_tab_id)
            rows = tree_rows(records, collapsed_tab_ids)
            selected_index = active_row_index(rows)
            error = None
            next_poll = 0.0
        except KittyError as caught:
            error = str(caught)

    with (
        TerminalMode() as terminal,
        TabEventListener() as tab_events,
        VisibleOrderPublisher() as order_publisher,
    ):
        while True:
            now = time.monotonic()
            if auto_reload and now >= next_source_check:
                pending_source_stamp, stable = reload_candidate(
                    initial_source_stamp,
                    pending_source_stamp,
                    source_stamp(),
                )
                if stable:
                    restart = True
                    break
                next_source_check = now + SOURCE_CHECK_INTERVAL
            if now >= next_poll:
                try:
                    snapshot = remote.snapshot()
                    sidebar_focused = window_is_focused(snapshot, self_window_id)
                    os_window = choose_os_window(
                        snapshot, target_os_window_id, self_window_id
                    )
                    os_window_id = int(os_window["id"])
                    if fold_state_os_window_id != os_window_id:
                        collapsed_tab_ids = read_folded_tab_ids(os_window_id)
                        fold_state_os_window_id = os_window_id
                    tab_events.bind(os_window_id)
                    records = records_for_os_window(os_window)
                    previous_collapsed_tab_ids = collapsed_tab_ids.copy()
                    collapsed_tab_ids.intersection_update(
                        record.id for record in records
                    )
                    if collapsed_tab_ids != previous_collapsed_tab_ids:
                        write_folded_tab_ids(os_window_id, collapsed_tab_ids)
                    rows = tree_rows(records, collapsed_tab_ids)
                    selected_index = active_row_index(rows)
                    repository_path = active_window_cwd(os_window)
                    error = None

                    direction = take_navigation_step(pending_navigation)
                    if direction is not None:
                        target_tab_id = adjacent_tree_tab_id(rows, direction)
                        if target_tab_id is not None:
                            remote.focus_tab(target_tab_id)
                            records = with_active_tab(records, target_tab_id)
                            rows = tree_rows(records, collapsed_tab_ids)
                            selected_index = active_row_index(rows)
                except (KittyError, ValueError) as caught:
                    error = str(caught)
                next_poll = navigation_poll_deadline(
                    now, poll_interval, pending_navigation
                )

            order_publisher.publish(os_window_id, rows)
            width, height = shutil.get_terminal_size((40, 24))
            card_height = view.card_height(len(rows), height)
            repository_capacity = min(
                MAX_REPOSITORY_LINES,
                view.repository_capacity(
                    rows, width, height, selected_index, card_height
                ),
            )
            repository_lines = repository_monitor.update(
                repository_path,
                width,
                repository_capacity,
                now,
            )
            render_now = time.monotonic()
            current_animation_frame = animation_frame(rows, render_now)
            render_signature: tuple[object, ...] = (
                tuple(rows),
                selected_index,
                os_window_id,
                width,
                height,
                error,
                edge_style,
                orientation,
                tuple(repository_lines),
                sidebar_focused,
                help_pinned,
                current_animation_frame,
            )
            if render_signature != last_render_signature:
                screen = view.renderer(
                    rows, selected_index, os_window_id, width, height,
                    total_tabs=len(records), error=error, now=render_now,
                    edge_style=edge_style,
                    repository_lines=repository_lines,
                    show_controls=sidebar_focused or help_pinned,
                    help_pinned=help_pinned,
                )
                # Erase with ktt's own black background. Kitty's configured
                # default can change when the OS window gains focus, which
                # otherwise makes inactive cards disappear into the panel.
                sys.stdout.write(panel_style() + "\x1b[H\x1b[2J" + screen)
                sys.stdout.flush()
                last_render_signature = render_signature
            key, tab_event_messages = terminal.read_key(
                next_wake_timeout(
                    time.monotonic(),
                    next_poll=next_poll,
                    next_source_check=next_source_check,
                    animated=current_animation_frame is not None,
                    auto_reload=auto_reload,
                ),
                tab_events,
            )
            if tab_event_messages:
                if enqueue_tab_events(
                    pending_navigation, tab_event_messages
                ):
                    next_poll = 0.0
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
                    hit_target = view.hit_target(
                        rows, width, height, selected_index, card_height,
                        mouse.column, mouse.row,
                    )
                    clicked_index = hit_target.index
                    if clicked_index is not None:
                        clicked = rows[clicked_index]
                        toggle = clicked.has_children and (
                            mouse.button == "right"
                            or hit_target.disclosure
                        )
                        if toggle:
                            if clicked.tab.id in collapsed_tab_ids:
                                collapsed_tab_ids.remove(clicked.tab.id)
                            else:
                                collapsed_tab_ids.add(clicked.tab.id)
                            write_folded_tab_ids(
                                os_window_id, collapsed_tab_ids
                            )
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
                write_folded_tab_ids(os_window_id, collapsed_tab_ids)
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
            elif key == "t":
                active = next(
                    (record for record in records if record.is_active), None
                )
                if active is not None and active.window_ids:
                    try:
                        remote.toggle_native_tabs(active.window_ids[0])
                        error = None
                    except KittyError as caught:
                        error = str(caught)
            elif key == "?":
                help_pinned = not help_pinned
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
