from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from .events import event_socket_path


def fold_state_path(os_window_id: int, *, kitty_pid: int | None = None) -> Path:
    return event_socket_path(os_window_id, kitty_pid=kitty_pid).with_suffix(".folds")


def read_folded_tab_ids(
    os_window_id: int, *, kitty_pid: int | None = None
) -> set[int]:
    try:
        values = fold_state_path(os_window_id, kitty_pid=kitty_pid).read_text()
        return {
            parsed
            for value in values.split(",")
            if value.strip()
            if (parsed := int(value)) > 0
        }
    except (OSError, ValueError):
        return set()


def write_folded_tab_ids(
    os_window_id: int,
    tab_ids: Iterable[int],
    *,
    kitty_pid: int | None = None,
) -> bool:
    path = fold_state_path(os_window_id, kitty_pid=kitty_pid)
    values = tuple(sorted({tab_id for tab_id in tab_ids if tab_id > 0}))
    if path.exists() and read_folded_tab_ids(
        os_window_id, kitty_pid=kitty_pid
    ) == set(values):
        return True
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    try:
        temporary.write_text(",".join(map(str, values)) + "\n")
        temporary.chmod(0o600)
        temporary.replace(path)
    except OSError:
        temporary.unlink(missing_ok=True)
        return False
    return True
