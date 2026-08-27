from __future__ import annotations

import argparse
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


def restore_saved_session(remote: RemoteControl, path: Path, *, dry_run: bool) -> int:
    manifest = read_manifest(path)
    for warning in manifest.warnings:
        print(f"ktt: saved warning: {warning}", file=sys.stderr)
    operations = plan_restore(manifest)
    for operation in operations:
        print(operation.describe())
    if dry_run:
        print(f"would restore {len(operations)} tabs from {path}")
        return 0
    execute_restore(remote, operations)
    print(f"restored {len(operations)} tabs from {path}")
    return 0


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
    parser.add_argument("path", nargs="?", type=Path, default=default_manifest_path())
    args = parser.parse_args(argv)
    return _run(
        lambda: restore_saved_session(
            RemoteControl(args.to), args.path, dry_run=args.dry_run
        )
    )


def _run(operation: Callable[[], int]) -> int:
    try:
        return operation()
    except (KittyError, SessionManifestError, OSError, RuntimeError) as error:
        print(f"ktt: {error}", file=sys.stderr)
        return 1
