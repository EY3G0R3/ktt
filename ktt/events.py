from __future__ import annotations

from dataclasses import dataclass
import errno
import os
from pathlib import Path
import socket


EVENT_DIRECTORY = "ktt"
TAB_CHANGE_EVENT = b"tabs"
TAB_STATE_EVENT_PREFIX = TAB_CHANGE_EVENT + b":"
NAVIGATION_EVENT_PREFIX = b"navigate:"


@dataclass(frozen=True)
class TabStateEvent:
    active_tab_id: int | None
    tab_ids: tuple[int, ...]


def tab_state_event(
    active_tab_id: int | None, tab_ids: tuple[int, ...]
) -> bytes:
    active = b"" if active_tab_id is None else str(active_tab_id).encode()
    members = b",".join(str(tab_id).encode() for tab_id in tab_ids)
    return TAB_STATE_EVENT_PREFIX + active + b"|" + members


def parse_tab_state_event(event: bytes) -> TabStateEvent | None:
    if not event.startswith(TAB_STATE_EVENT_PREFIX):
        return None
    try:
        active_value, member_values = event[len(TAB_STATE_EVENT_PREFIX):].split(
            b"|", 1
        )
        active_tab_id = int(active_value) if active_value else None
        tab_ids = tuple(
            int(value) for value in member_values.split(b",") if value
        )
    except ValueError:
        return None
    if active_tab_id is not None and active_tab_id not in tab_ids:
        return None
    return TabStateEvent(active_tab_id, tab_ids)


def event_socket_path(
    os_window_id: int,
    *,
    runtime_dir: str | None = None,
    kitty_pid: int | None = None,
) -> Path:
    runtime = runtime_dir or os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    pid = kitty_pid
    if pid is None:
        raw_pid = os.environ.get("KITTY_PID", "")
        pid = int(raw_pid) if raw_pid.isdigit() else 0
    return Path(runtime) / EVENT_DIRECTORY / f"kitty-{pid}-os-{os_window_id}.sock"


def _remove_refused_socket(path: Path, error: OSError, inode: int | None) -> None:
    if error.errno != errno.ECONNREFUSED or inode is None:
        return
    try:
        if path.stat().st_ino == inode:
            path.unlink()
    except FileNotFoundError:
        pass


class TabEventListener:
    def __init__(self) -> None:
        self.socket: socket.socket | None = None
        self.path: Path | None = None
        self.inode: int | None = None
        self.os_window_id: int | None = None

    def bind(self, os_window_id: int) -> None:
        if self.os_window_id == os_window_id and self.socket is not None:
            return
        self.close()
        base_path = event_socket_path(os_window_id)
        base_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = (
            base_path.with_name(f"{base_path.name}.{os.getpid()}")
            if base_path.exists()
            else base_path
        )
        listener: socket.socket | None = None
        try:
            if path != base_path:
                path.unlink(missing_ok=True)
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            listener.setblocking(False)
            listener.bind(str(path))
            path.chmod(0o600)
        except OSError:
            if listener is not None:
                listener.close()
            return
        self.socket = listener
        self.path = path
        self.inode = path.stat().st_ino
        self.os_window_id = os_window_id

    def drain(self) -> tuple[bytes, ...]:
        if self.socket is None:
            return ()
        received: list[bytes] = []
        while True:
            try:
                received.append(self.socket.recv(256))
            except BlockingIOError:
                return tuple(received)
            except OSError:
                return tuple(received)

    def close(self) -> None:
        if self.socket is not None:
            self.socket.close()
        if self.path is not None and self.inode is not None:
            try:
                if self.path.stat().st_ino == self.inode:
                    self.path.unlink()
            except FileNotFoundError:
                pass
        self.socket = None
        self.path = None
        self.inode = None
        self.os_window_id = None

    def __enter__(self) -> "TabEventListener":
        return self

    def __exit__(self, *_error: object) -> None:
        self.close()


def navigation_event(direction: int) -> bytes:
    return NAVIGATION_EVENT_PREFIX + (b"1" if direction > 0 else b"-1")


def navigation_direction(event: bytes) -> int | None:
    if event == NAVIGATION_EVENT_PREFIX + b"1":
        return 1
    if event == NAVIGATION_EVENT_PREFIX + b"-1":
        return -1
    return None


def send_navigation(
    os_window_id: int,
    direction: int,
    *,
    kitty_pid: int | None = None,
) -> bool:
    sender = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sender.setblocking(False)
    base_path = event_socket_path(os_window_id, kitty_pid=kitty_pid)
    candidates = [
        base_path,
        *sorted(base_path.parent.glob(f"{base_path.name}.*")),
    ]
    try:
        for path in candidates:
            try:
                inode = path.stat().st_ino
            except OSError:
                inode = None
            try:
                sender.sendto(navigation_event(direction), str(path))
            except OSError as error:
                _remove_refused_socket(path, error, inode)
                continue
            return True
        return False
    finally:
        sender.close()
