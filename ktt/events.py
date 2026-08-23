from __future__ import annotations

import os
from pathlib import Path
import socket


EVENT_DIRECTORY = "ktt"
TAB_CHANGE_EVENT = b"tabs"
NAVIGATION_EVENT_PREFIX = b"navigate:"


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
        path = event_socket_path(os_window_id)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        listener: socket.socket | None = None
        try:
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
    try:
        sender.sendto(
            navigation_event(direction),
            str(event_socket_path(os_window_id, kitty_pid=kitty_pid)),
        )
    except OSError:
        return False
    finally:
        sender.close()
    return True
