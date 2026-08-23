from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import sys

from .kitty import (
    KittyError,
    RemoteControl,
    find_sidebar_window,
    find_tab_for_window,
)
from .model import choose_os_window, records_for_os_window, tree_rows
from .render import (
    DEFAULT_EDGE_STYLE,
    DEFAULT_ORIENTATION,
    EDGE_STYLES,
    ORIENTATIONS,
    render_horizontal_screen,
    render_screen,
)
from .repository import DEFAULT_REPOSITORY_PALETTE, REPOSITORY_PALETTES
from .tui import run_tui


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ktt", description="A tree-shaped tab bar for Kitty"
    )
    parser.add_argument("--to", help="Kitty remote-control socket address")
    parser.add_argument(
        "--orientation",
        choices=ORIENTATIONS,
        default=os.environ.get("KTT_ORIENTATION", DEFAULT_ORIENTATION),
        help="tree direction (default: vertical)",
    )
    parser.add_argument(
        "--target-os-window", type=int, help="Kitty OS window ID to display"
    )
    parser.add_argument(
        "--poll-interval", type=float, default=1.0,
        help="seconds between Kitty state polls (default: 1.0)",
    )
    parser.add_argument(
        "--no-auto-reload", action="store_false", dest="auto_reload",
        help="do not restart the TUI when its Python sources change",
    )
    parser.add_argument(
        "--edge-style",
        choices=EDGE_STYLES,
        default=os.environ.get("KTT_EDGE_STYLE", DEFAULT_EDGE_STYLE),
        help="tab-card edge treatment (default: tapered)",
    )
    parser.add_argument(
        "--repository-palette",
        choices=REPOSITORY_PALETTES,
        default=os.environ.get(
            "KTT_REPOSITORY_PALETTE", DEFAULT_REPOSITORY_PALETTE
        ),
        help="fancylog status-bar palette (default: terminal)",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("list", help="print the current tree once")
    subparsers.add_parser("launch", help="open ktt in a separate Kitty OS window")
    subparsers.add_parser(
        "refresh", help="replace the running sidebar inside its current OS window"
    )
    subparsers.add_parser(
        "watcher-path", help="print the global Kitty watcher path"
    )
    subparsers.add_parser(
        "navigation-kitten-path", help="print the tree-navigation kitten path"
    )
    launch_child = subparsers.add_parser(
        "launch-child", help="launch a child tab linked to the current Kitty window"
    )
    launch_child.add_argument("--parent-window", type=int)
    launch_child.add_argument("--title")
    launch_child.add_argument("child_command", nargs=argparse.REMAINDER)
    link = subparsers.add_parser("link", help="make one Kitty window a child of another")
    link.add_argument("--child-window", type=int, required=True)
    link.add_argument("--parent-window", type=int, required=True)
    unlink = subparsers.add_parser("unlink", help="remove a Kitty window's parent")
    unlink.add_argument("--child-window", type=int, required=True)
    return parser


def _self_window_id() -> int | None:
    value = os.environ.get("KITTY_WINDOW_ID", "")
    return int(value) if value.isdigit() else None


def _list(remote: RemoteControl, target: int | None, orientation: str) -> int:
    snapshot = remote.snapshot()
    os_window = choose_os_window(snapshot, target, _self_window_id())
    rows = tree_rows(records_for_os_window(os_window))
    width = shutil.get_terminal_size((80, 24)).columns
    renderer = render_screen if orientation == "vertical" else render_horizontal_screen
    print(
        renderer(
            rows, -1, int(os_window["id"]), width, len(rows) + 2, ansi=False
        )
    )
    return 0


def _validate_link(snapshot: list[dict], child: int, parent: int) -> None:
    child_location = find_tab_for_window(snapshot, child)
    parent_location = find_tab_for_window(snapshot, parent)
    if child_location is None:
        raise ValueError(f"child Kitty window {child} does not exist")
    if parent_location is None:
        raise ValueError(f"parent Kitty window {parent} does not exist")
    if child == parent or child_location[1] == parent_location[1]:
        raise ValueError("parent and child must belong to different Kitty tabs")
    if child_location[0] != parent_location[0]:
        raise ValueError("parent and child must belong to the same Kitty OS window")

    os_window = next(
        item for item in snapshot if int(item["id"]) == child_location[0]
    )
    records = records_for_os_window(os_window)
    tab_for_window = {
        window_id: record.id
        for record in records
        for window_id in record.window_ids
    }
    parent_for = {
        record.id: tab_for_window[record.parent_window_id]
        for record in records
        if record.parent_window_id in tab_for_window
        and tab_for_window[record.parent_window_id] != record.id
    }
    child_tab_id = child_location[1]
    current = parent_location[1]
    visited: set[int] = set()
    while current in parent_for and current not in visited:
        if current == child_tab_id:
            raise ValueError("link would create a cycle in the tab tree")
        visited.add(current)
        current = parent_for[current]
    if current == child_tab_id:
        raise ValueError("link would create a cycle in the tab tree")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.poll_interval < 0.1:
        print("ktt: --poll-interval must be at least 0.1 seconds", file=sys.stderr)
        return 2
    remote = RemoteControl(args.to)
    try:
        if args.command == "watcher-path":
            print(Path(__file__).with_name("kitty_watcher.py"))
            return 0
        if args.command == "navigation-kitten-path":
            print(Path(__file__).with_name("tree_navigation_kitten.py"))
            return 0
        if args.command == "list":
            return _list(remote, args.target_os_window, args.orientation)
        if args.command == "launch":
            snapshot = remote.snapshot()
            self_id = _self_window_id()
            target = args.target_os_window
            if target is None:
                if self_id is None:
                    raise ValueError(
                        "launch must run inside Kitty or receive --target-os-window"
                    )
                location = find_tab_for_window(snapshot, self_id)
                if location is None:
                    raise ValueError("the current Kitty window was not found")
                target = location[0]
            new_window_id = remote.launch_sidebar(
                target, args.edge_style, args.repository_palette,
                args.orientation,
            )
            print(f"opened ktt in Kitty window {new_window_id}, targeting OS window {target}")
            return 0
        if args.command == "refresh":
            snapshot = remote.snapshot()
            sidebar = find_sidebar_window(snapshot, args.orientation)
            if sidebar is None:
                raise ValueError("no running ktt sidebar window was found")
            sidebar_os_window_id, sidebar_window_id, recorded_target = sidebar
            target = args.target_os_window or recorded_target
            if target is None:
                candidates = [
                    os_window for os_window in snapshot
                    if int(os_window["id"]) != sidebar_os_window_id
                ]
                target = int(choose_os_window(candidates)["id"])
            new_window_id = remote.replace_sidebar(
                sidebar_window_id, target, args.edge_style,
                args.repository_palette,
                args.orientation,
            )
            print(
                f"refreshed ktt as Kitty window {new_window_id}, "
                f"still targeting OS window {target}"
            )
            return 0
        if args.command == "launch-child":
            parent = args.parent_window or _self_window_id()
            if parent is None:
                raise ValueError(
                    "launch-child must run inside Kitty or receive --parent-window"
                )
            snapshot = remote.snapshot()
            if find_tab_for_window(snapshot, parent) is None:
                raise ValueError(f"parent Kitty window {parent} does not exist")
            child_command = list(args.child_command)
            if child_command[:1] == ["--"]:
                child_command = child_command[1:]
            child = remote.launch_child(parent, child_command, args.title)
            print(f"launched child Kitty window {child} under {parent}")
            return 0
        if args.command == "link":
            snapshot = remote.snapshot()
            _validate_link(snapshot, args.child_window, args.parent_window)
            remote.set_parent(args.child_window, args.parent_window)
            print(
                f"linked Kitty window {args.child_window} under {args.parent_window}"
            )
            return 0
        if args.command == "unlink":
            snapshot = remote.snapshot()
            if find_tab_for_window(snapshot, args.child_window) is None:
                raise ValueError(f"child Kitty window {args.child_window} does not exist")
            remote.set_parent(args.child_window, None)
            print(f"unlinked Kitty window {args.child_window}")
            return 0
        return run_tui(
            remote,
            args.target_os_window,
            args.poll_interval,
            args.auto_reload,
            args.edge_style,
            args.repository_palette,
            args.orientation,
        )
    except (KittyError, ValueError, RuntimeError) as error:
        print(f"ktt: {error}", file=sys.stderr)
        return 1
