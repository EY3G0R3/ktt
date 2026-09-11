from __future__ import annotations

import argparse
import os
import shlex
import socket
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .kitty import KittyError, RemoteControl
from .repository import infer_repository_context, resolve_repository_context
from .render import (
    CARD_TITLE_FOREGROUND,
    PANEL_BACKGROUND,
    REPOSITORY_BRANCH_FOREGROUND,
    REPOSITORY_CLEAN_FOREGROUND,
    REPOSITORY_DIRTY_FOREGROUND,
    REPOSITORY_META_FOREGROUND,
    WORKTREE_GLYPH,
    repository_label_foreground,
    worktree_foreground,
    worktree_glyph_foreground,
)
from .session import (
    SessionManifest,
    SessionManifestError,
    autosave_sessions_dir,
    capture_session,
    default_manifest_path,
    execute_restore,
    named_autosave_path,
    named_session_path,
    plan_restore,
    read_manifest,
    recovery_restore_path,
    named_sessions_dir,
    write_manifest,
)


def _session_candidates() -> list[tuple[str, str, Path, SessionManifest]]:
    candidates: list[tuple[str, str, Path, SessionManifest]] = []
    autosave_directory = autosave_sessions_dir()
    if autosave_directory.exists():
        for path in autosave_directory.glob("autosave-*.json"):
            candidates.append((path.stem, "automatic", path, read_manifest(path)))
    if not candidates:
        autosave = recovery_restore_path()
        if autosave.exists():
            candidates.append(("autosave", "automatic", autosave, read_manifest(autosave)))
    directory = named_sessions_dir()
    if directory.exists():
        for path in directory.glob("*.json"):
            candidates.append((path.stem, "manual", path, read_manifest(path)))
    return candidates


def latest_autosave_path() -> Path:
    candidates = [
        candidate for candidate in _session_candidates() if candidate[1] == "automatic"
    ]
    if not candidates:
        return recovery_restore_path()
    return max(
        candidates,
        key=lambda candidate: datetime.fromisoformat(candidate[3].created_at),
    )[2]


def latest_saved_session_path() -> Path:
    candidates = _session_candidates()
    if not candidates:
        return recovery_restore_path()
    return max(
        candidates,
        key=lambda candidate: datetime.fromisoformat(candidate[3].created_at),
    )[2]


def resolve_saved_session_path(name: str | None) -> Path:
    if name == "autosave":
        return latest_autosave_path()
    if name and name.startswith("autosave-"):
        return named_autosave_path(name)
    if name and name != "latest":
        return named_session_path(name)
    return latest_saved_session_path()


def _display_saved_at(created_at: str) -> str:
    return (
        datetime.fromisoformat(created_at)
        .astimezone()
        .strftime("%Y-%m-%d %-I:%M:%S %p %Z")
    )


def _color_enabled() -> bool:
    return (
        sys.stdout.isatty()
        and "NO_COLOR" not in os.environ
        and os.environ.get("TERM") != "dumb"
    )


def _paint(text: str, color: str, *, enabled: bool, bold: bool = False) -> str:
    if not enabled:
        return text
    red, green, blue = (int(color[offset : offset + 2], 16) for offset in (0, 2, 4))
    weight = "\x1b[1m" if bold else ""
    return f"{weight}\x1b[38;2;{red};{green};{blue}m{text}\x1b[0m"


def _tab_depth(logical_id: str, parents: dict[str, str | None]) -> int:
    depth = 0
    current = parents.get(logical_id)
    while current is not None:
        depth += 1
        current = parents.get(current)
    return depth


def save_current_session(
    remote: RemoteControl, path: Path, *, name: str | None = None
) -> int:
    manifest = capture_session(
        remote.snapshot(),
        hostname=socket.gethostname(),
        created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
    )
    write_manifest(path, manifest)
    destination = name or str(path)
    print(
        f"saved {manifest.tab_count} tabs in {len(manifest.os_windows)} OS windows "
        f"as {destination}"
    )
    for warning in manifest.warnings:
        print(f"ktt: warning: {warning}", file=sys.stderr)
    return 0


def list_saved_sessions() -> int:
    candidates = _session_candidates()
    if not candidates:
        print("No saved terminal sessions.")
        return 0
    rows = [
        (
            name,
            kind,
            _display_saved_at(manifest.created_at),
            str(manifest.tab_count),
        )
        for name, kind, _path, manifest in sorted(
            candidates,
            key=lambda candidate: datetime.fromisoformat(candidate[3].created_at),
            reverse=True,
        )
    ]
    headers = ("NAME", "TYPE", "SAVED", "TABS")
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]
    print("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    for row in rows:
        cells = [row[index].ljust(widths[index]) for index in range(len(row) - 1)]
        cells.append(row[-1].rjust(widths[-1]))
        print("  ".join(cells))
    return 0


def show_saved_session(path: Path) -> int:
    manifest = read_manifest(path)
    color = _color_enabled()
    automatic = path.parent == autosave_sessions_dir() or path in {
        recovery_restore_path(),
    }
    name = path.stem
    if path.name in {"recovery.json", "recovery.previous.json"}:
        name = "autosave"
    tab_label = "tab" if manifest.tab_count == 1 else "tabs"
    window_count = len(manifest.os_windows)
    window_label = "window" if window_count == 1 else "windows"
    print(_paint(name, CARD_TITLE_FOREGROUND, enabled=color, bold=True))
    print(
        f"{_display_saved_at(manifest.created_at)}  ·  "
        f"{'automatic' if automatic else 'manual'}  ·  "
        f"{manifest.tab_count} {tab_label} in {window_count} {window_label}  ·  "
        f"{manifest.hostname}"
    )
    print(_paint(str(path), REPOSITORY_META_FOREGROUND, enabled=color))
    print(
        _paint(
            "Repository context below is derived now from saved working directories.",
            REPOSITORY_META_FOREGROUND,
            enabled=color,
        )
    )
    for window_index, os_window in enumerate(manifest.os_windows, start=1):
        window_title = f": {os_window.title}" if os_window.title else ""
        print(f"\n{_paint(f'Window {window_index}{window_title}', CARD_TITLE_FOREGROUND, enabled=color, bold=True)}")
        parents = {tab.logical_id: tab.parent for tab in os_window.tabs}
        for tab_index, tab in enumerate(os_window.tabs, start=1):
            command = tab.agent.resume_command()
            launch = shlex.join(command) if command else "<default shell>"
            relationship = f"child of {tab.parent}" if tab.parent else "root"
            state = ", ".join(
                label
                for enabled, label in (
                    (tab.active, "active"),
                    (tab.focused, "focused"),
                )
                if enabled
            ) or "background"
            repository = (
                resolve_repository_context(tab.cwd)
                or infer_repository_context(tab.cwd)
                if tab.cwd
                else None
            )
            header = [
                _paint(f"Tab {tab_index}", REPOSITORY_META_FOREGROUND, enabled=color),
                _paint(tab.title, CARD_TITLE_FOREGROUND, enabled=color, bold=True),
            ]
            if repository is not None:
                repository_label = f"/{repository.name}/"
                header.append(
                    _paint(
                        repository_label,
                        repository_label_foreground(
                            repository.name, PANEL_BACKGROUND
                        ),
                        enabled=color,
                    )
                )
                if repository.location.worktree:
                    header.append(
                        _paint(
                            WORKTREE_GLYPH,
                            worktree_glyph_foreground(PANEL_BACKGROUND),
                            enabled=color,
                        )
                        + _paint(
                            repository.location.worktree,
                            worktree_foreground(PANEL_BACKGROUND),
                            enabled=color,
                        )
                    )
                if repository.location.relative_path:
                    header.append(
                        _paint(
                            repository.location.relative_path,
                            REPOSITORY_META_FOREGROUND,
                            enabled=color,
                        )
                    )
            indent = "    " * _tab_depth(tab.logical_id, parents)
            print(f"{indent}  ╭─ {'  '.join(header)}")
            print(
                f"{indent}  │  {_paint('Launch', REPOSITORY_BRANCH_FOREGROUND, enabled=color)}  "
                f"{launch}"
            )
            print(
                f"{indent}  │  {_paint('Cwd', REPOSITORY_META_FOREGROUND, enabled=color)}     "
                f"{tab.cwd or '<default>'}"
            )
            agent = f"{tab.agent.identity} ({tab.agent.kind})"
            if tab.agent.session_id:
                agent += f"  ·  session {tab.agent.session_id}"
            print(
                f"{indent}  │  {_paint('Agent', REPOSITORY_META_FOREGROUND, enabled=color)}   "
                f"{agent}"
            )
            if tab.agent.reason:
                print(
                    f"{indent}  │  {_paint('Reason', REPOSITORY_DIRTY_FOREGROUND, enabled=color)}  "
                    f"{tab.agent.reason}"
                )
            warning_prefix = f"{tab.logical_id}: "
            for warning in manifest.warnings:
                if warning.startswith(warning_prefix):
                    print(
                        f"{indent}  │  {_paint('Warning', REPOSITORY_DIRTY_FOREGROUND, enabled=color)} "
                        f"{warning.removeprefix(warning_prefix)}"
                    )
            restorable = _paint(
                "restorable" if tab.agent.restorable else "not restorable",
                REPOSITORY_CLEAN_FOREGROUND
                if tab.agent.restorable
                else REPOSITORY_DIRTY_FOREGROUND,
                enabled=color,
            )
            print(
                f"{indent}  ╰─ {relationship}  ·  {state}  ·  {restorable}  ·  "
                f"{tab.logical_id}"
            )
    tab_warning_prefixes = tuple(
        f"{tab.logical_id}: "
        for os_window in manifest.os_windows
        for tab in os_window.tabs
    )
    for warning in manifest.warnings:
        if not warning.startswith(tab_warning_prefixes):
            print(
                f"\n{_paint('Warning', REPOSITORY_DIRTY_FOREGROUND, enabled=color)}: "
                f"{warning}"
            )
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
        "--recovery",
        action="store_true",
        help="restore the latest automatic crash-recovery snapshot",
    )
    parser.add_argument(
        "--new-window",
        action="store_true",
        help="restore into newly created Kitty OS windows instead of replacing this tab",
    )
    parser.add_argument("path", nargs="?", type=Path)
    args = parser.parse_args(argv)
    return _run(
        lambda: restore_saved_session(
            RemoteControl(args.to),
            args.path
            or (
                recovery_restore_path()
                if args.recovery
                else default_manifest_path()
            ),
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
