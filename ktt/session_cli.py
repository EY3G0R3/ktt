from __future__ import annotations

import argparse
import os
import socket
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .kitty import KittyError, RemoteControl
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
            f"would restore {len(operations)} tabs from {path} and enable "
            "native vertical tabs"
        )
        return 0
    runtime_ids = execute_restore(
        remote,
        operations,
        first_os_window_source_id=current_window_id,
    )
    source_window_id = next(iter(runtime_ids.values()), None)
    if source_window_id is None:
        raise RuntimeError("the restored session contains no Kitty windows")
    remote.enable_native_vertical_tabs(source_window_id)
    print(
        f"restored {len(operations)} tabs from {path}; enabled native vertical tabs"
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
