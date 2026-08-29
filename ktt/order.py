from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from .events import event_socket_path
from .model import TreeRow, active_tree_row_index


@dataclass(frozen=True)
class VisibleOrder:
    anchor_tab_id: int
    tab_ids: tuple[int, ...]
    attention_tab_ids: tuple[int, ...] | None = None


def order_path(os_window_id: int, *, kitty_pid: int | None = None) -> Path:
    return event_socket_path(os_window_id, kitty_pid=kitty_pid).with_suffix(".order")


def read_visible_order(
    os_window_id: int, *, kitty_pid: int | None = None
) -> VisibleOrder | None:
    try:
        lines = order_path(os_window_id, kitty_pid=kitty_pid).read_text().splitlines()
        anchor, values = lines[:2]
        tab_ids = tuple(int(value) for value in values.split(",") if value)
        anchor_tab_id = int(anchor)
        attention_tab_ids = (
            tuple(int(value) for value in lines[2].split(",") if value)
            if len(lines) >= 3
            else None
        )
    except (OSError, ValueError, IndexError):
        return None
    if anchor_tab_id not in tab_ids:
        return None
    return VisibleOrder(anchor_tab_id, tab_ids, attention_tab_ids)


class VisibleOrderPublisher:
    def __init__(self) -> None:
        self.path: Path | None = None
        self.inode: int | None = None
        self.value: VisibleOrder | None = None

    def publish(
        self,
        os_window_id: int,
        rows: list[TreeRow],
        attention_tab_ids: tuple[int, ...] = (),
    ) -> None:
        if not rows:
            return
        value = VisibleOrder(
            rows[active_tree_row_index(rows)].tab.id,
            tuple(row.tab.id for row in rows),
            attention_tab_ids,
        )
        path = order_path(os_window_id)
        if self.path == path and self.value == value:
            return
        if self.path is not None and self.path != path:
            self.close()
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        try:
            temporary.write_text(
                f"{value.anchor_tab_id}\n"
                f"{','.join(map(str, value.tab_ids))}\n"
                f"{','.join(map(str, value.attention_tab_ids or ()))}\n"
            )
            temporary.chmod(0o600)
            inode = temporary.stat().st_ino
            temporary.replace(path)
        except OSError:
            temporary.unlink(missing_ok=True)
            return
        self.path = path
        self.inode = inode
        self.value = value

    def close(self) -> None:
        if self.path is not None and self.inode is not None:
            try:
                if self.path.stat().st_ino == self.inode:
                    self.path.unlink()
            except FileNotFoundError:
                pass
        self.path = None
        self.inode = None
        self.value = None

    def __enter__(self) -> "VisibleOrderPublisher":
        return self

    def __exit__(self, *_error: object) -> None:
        self.close()
