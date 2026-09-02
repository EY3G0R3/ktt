from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .kitty import KittyError, RemoteControl, find_tab_for_window
from .model import choose_os_window, records_for_os_window, tree_rows
from .native_tabs import NativeVerticalTabsUnsupported, format_version
from .session import default_manifest_path
from .session_cli import restore_saved_session, save_current_session


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ktt", description="A tree-shaped native tab bar for Kitty"
    )
    parser.add_argument("--to", help="Kitty remote-control socket address")
    subparsers = parser.add_subparsers(dest="command")
    save_session = subparsers.add_parser(
        "save-session", help="save Kitty tabs, ktt relationships, and resumable agents"
    )
    save_session.add_argument(
        "path", nargs="?", type=Path, default=default_manifest_path()
    )
    restore_session = subparsers.add_parser(
        "restore-session", help="restore a saved Kitty and ktt session"
    )
    restore_session.add_argument("--dry-run", action="store_true")
    restore_session.add_argument(
        "--new-window",
        action="store_true",
        help="restore into newly created Kitty OS windows instead of replacing this tab",
    )
    restore_session.add_argument(
        "path", nargs="?", type=Path, default=default_manifest_path()
    )
    list_tree = subparsers.add_parser("list", help="print the current tree once")
    list_tree.add_argument(
        "--target-os-window", type=int, help="Kitty OS window ID to inspect"
    )
    subparsers.add_parser("native", help="enable Kitty's native vertical tab bar")
    subparsers.add_parser(
        "watcher-path", help="print the native tree-order watcher path"
    )
    subparsers.add_parser(
        "navigation-kitten-path", help="print the tree-navigation kitten path"
    )
    subparsers.add_parser(
        "parent-chooser-kitten-path", help="print the parent chooser kitten path"
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


def _list(remote: RemoteControl, target: int | None) -> int:
    snapshot = remote.snapshot()
    os_window = choose_os_window(snapshot, target, _self_window_id())
    for row in tree_rows(records_for_os_window(os_window)):
        active = "*" if row.tab.is_active else " "
        status = f"{row.tab.status} " if row.tab.status else ""
        print(f"{active} {'    ' * row.depth}{status}{row.tab.title}")
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


def _enable_native(remote: RemoteControl) -> int:
    source = _self_window_id()
    if source is None:
        raise ValueError("ktt must run inside Kitty")
    remote.enable_native_vertical_tabs(source)
    print("enabled Kitty's native vertical tab bar for this Kitty process")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    remote = RemoteControl(args.to)
    try:
        if args.command == "save-session":
            return save_current_session(remote, args.path)
        if args.command == "restore-session":
            return restore_saved_session(
                remote,
                args.path,
                dry_run=args.dry_run,
                current_window_id=None if args.new_window else _self_window_id(),
            )
        if args.command == "watcher-path":
            print(Path(__file__).with_name("kitty_watcher.py"))
            return 0
        if args.command == "navigation-kitten-path":
            print(Path(__file__).with_name("tree_navigation_kitten.py"))
            return 0
        if args.command == "parent-chooser-kitten-path":
            print(Path(__file__).with_name("parent_chooser_kitten.py"))
            return 0
        if args.command == "list":
            return _list(remote, args.target_os_window)
        if args.command in (None, "native"):
            return _enable_native(remote)
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
            print(f"linked Kitty window {args.child_window} under {args.parent_window}")
            return 0
        if args.command == "unlink":
            snapshot = remote.snapshot()
            if find_tab_for_window(snapshot, args.child_window) is None:
                raise ValueError(f"child Kitty window {args.child_window} does not exist")
            remote.set_parent(args.child_window, None)
            print(f"unlinked Kitty window {args.child_window}")
            return 0
        raise ValueError(f"unknown command: {args.command}")
    except NativeVerticalTabsUnsupported as error:
        print(
            "ktt: native vertical tabs require Kitty 0.48.0 or newer "
            f"(running {format_version(error.version)})",
            file=sys.stderr,
        )
        return 1
    except (KittyError, ValueError, RuntimeError) as error:
        print(f"ktt: {error}", file=sys.stderr)
        return 1
