from __future__ import annotations

import argparse
import os
import socket
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .daemon import start_daemon
from .kitty import KittyError, RemoteControl, find_tab_for_window
from .render import (
    DEFAULT_CHANGED_FILES_PLACEMENT,
    DEFAULT_EDGE_STYLE,
    DEFAULT_ORIENTATION,
)
from .repository import DEFAULT_REPOSITORY_PALETTE
from .session import (
    SessionManifestError,
    capture_session,
    default_manifest_path,
    execute_restore,
    plan_restore,
    read_manifest,
    write_manifest,
)


def save_current_session(remote: RemoteControl, path: Path) -> int:
    manifest = capture_session(
        remote.snapshot(),
        hostname=socket.gethostname(),
        created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
    )
    write_manifest(path, manifest)
    print(
        f"saved {manifest.tab_count} tabs in {len(manifest.os_windows)} OS windows to {path}"
    )
    for warning in manifest.warnings:
        print(f"ktt: warning: {warning}", file=sys.stderr)
    return 0


def restore_saved_session(
    remote: RemoteControl,
    path: Path,
    *,
    dry_run: bool,
    poll_interval: float = 1.0,
    edge_style: str = DEFAULT_EDGE_STYLE,
    repository_palette: str = DEFAULT_REPOSITORY_PALETTE,
    changed_files_placement: str = DEFAULT_CHANGED_FILES_PLACEMENT,
    orientation: str = DEFAULT_ORIENTATION,
    pane_percent: int | None = None,
    current_window_id: int | None = None,
) -> int:
    manifest = read_manifest(path)
    for warning in manifest.warnings:
        print(f"ktt: saved warning: {warning}", file=sys.stderr)
    operations = plan_restore(manifest)
    for operation in operations:
        print(operation.describe())
    if dry_run:
        print(
            f"would restore {len(operations)} tabs from {path} and embed ktt in "
            f"{len(manifest.os_windows)} OS windows"
        )
        return 0
    runtime_ids = execute_restore(
        remote,
        operations,
        first_os_window_source_id=current_window_id,
    )
    snapshot = remote.snapshot()
    restored_os_window_ids: list[int] = []
    for operation in operations:
        if operation.source is not None:
            continue
        location = find_tab_for_window(snapshot, runtime_ids[operation.logical_id])
        if location is None:
            raise RuntimeError(
                f"restored Kitty window {runtime_ids[operation.logical_id]} disappeared"
            )
        restored_os_window_ids.append(location[0])

    resolved_pane_percent = pane_percent
    if resolved_pane_percent is None:
        resolved_pane_percent = 10 if orientation == "horizontal" else 20
    for os_window_id in restored_os_window_ids:
        start_daemon(
            os_window_id,
            to=remote.to,
            poll_interval=poll_interval,
            edge_style=edge_style,
            repository_palette=repository_palette,
            changed_files_placement=changed_files_placement,
            pane_percent=resolved_pane_percent,
            orientation=orientation,
        )
    print(
        f"restored {len(operations)} tabs from {path}; embedded ktt in "
        f"{len(restored_os_window_ids)} OS windows"
    )
    if current_window_id is not None:
        sys.stdout.flush()
        remote.close_window(current_window_id)
    return 0


def _current_window_id() -> int | None:
    value = os.environ.get("KITTY_WINDOW_ID", "")
    return int(value) if value.isdigit() else None


def save_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ktt-save")
    parser.add_argument("--to", help="Kitty remote-control socket address")
    parser.add_argument("path", nargs="?", type=Path, default=default_manifest_path())
    args = parser.parse_args(argv)
    return _run(lambda: save_current_session(RemoteControl(args.to), args.path))


def restore_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ktt-restore")
    parser.add_argument("--to", help="Kitty remote-control socket address")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--new-window",
        action="store_true",
        help="restore into newly created Kitty OS windows instead of replacing this tab",
    )
    parser.add_argument("path", nargs="?", type=Path, default=default_manifest_path())
    args = parser.parse_args(argv)
    return _run(
        lambda: restore_saved_session(
            RemoteControl(args.to),
            args.path,
            dry_run=args.dry_run,
            current_window_id=None if args.new_window else _current_window_id(),
        )
    )


def _run(operation: Callable[[], int]) -> int:
    try:
        return operation()
    except (KittyError, SessionManifestError, OSError, RuntimeError) as error:
        print(f"ktt: {error}", file=sys.stderr)
        return 1
