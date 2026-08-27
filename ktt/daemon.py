from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys
import time
from typing import Any

from .events import TabEventListener, navigation_direction
from .folds import read_folded_tab_ids
from .kitty import (
    RemoteControl,
    embedded_sidebar_windows,
    os_window_by_id,
)
from .model import (
    TabRecord,
    adjacent_tree_tab_id,
    records_for_os_window,
    tree_rows,
    with_repository_names,
)
from .order import VisibleOrderPublisher
from .repository import (
    DEFAULT_REPOSITORY_PALETTE,
    FancylogIdentityCache,
    FancylogMonitor,
    MAX_REPOSITORY_LINES,
    RepositoryLocation,
    RepositoryLocationCache,
    active_window_cwd,
    with_repository_worktrees,
)


MAX_FRAME_BYTES = 16 * 1024 * 1024


def _kitty_pid(kitty_pid: int | None = None) -> int:
    if kitty_pid is not None:
        return kitty_pid
    value = os.environ.get("KITTY_PID", "")
    return int(value) if value.isdigit() else 0


def daemon_socket_path(
    os_window_id: int,
    *,
    runtime_dir: str | None = None,
    kitty_pid: int | None = None,
) -> Path:
    runtime = runtime_dir or os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    return (
        Path(runtime)
        / "ktt"
        / f"kitty-{_kitty_pid(kitty_pid)}-os-{os_window_id}.daemon.sock"
    )


def daemon_state_path(
    os_window_id: int,
    *,
    runtime_dir: str | None = None,
    kitty_pid: int | None = None,
) -> Path:
    return daemon_socket_path(
        os_window_id, runtime_dir=runtime_dir, kitty_pid=kitty_pid
    ).with_suffix(".json")


@dataclass(frozen=True)
class SharedSnapshot:
    sequence: int
    os_window_id: int
    records: tuple[TabRecord, ...]
    folded_tab_ids: tuple[int, ...]
    focused_window_ids: tuple[int, ...]
    sidebar_windows: dict[int, int]
    repository_path: str | None = None
    repository_lines: tuple[str, ...] = ()
    repository_location: RepositoryLocation | None = None
    error: str | None = None

    def to_bytes(self) -> bytes:
        value = {
            "sequence": self.sequence,
            "os_window_id": self.os_window_id,
            "records": [asdict(record) for record in self.records],
            "folded_tab_ids": self.folded_tab_ids,
            "focused_window_ids": self.focused_window_ids,
            "sidebar_windows": self.sidebar_windows,
            "repository_path": self.repository_path,
            "repository_lines": self.repository_lines,
            "repository_location": (
                asdict(self.repository_location)
                if self.repository_location is not None
                else None
            ),
            "error": self.error,
        }
        return json.dumps(value, separators=(",", ":")).encode()

    @classmethod
    def from_bytes(cls, payload: bytes) -> SharedSnapshot:
        value = json.loads(payload)
        records = tuple(
            TabRecord(
                **{
                    **record,
                    "window_ids": tuple(record.get("window_ids") or ()),
                }
            )
            for record in value.get("records") or ()
        )
        return cls(
            sequence=int(value["sequence"]),
            os_window_id=int(value["os_window_id"]),
            records=records,
            folded_tab_ids=tuple(
                int(tab_id) for tab_id in value.get("folded_tab_ids") or ()
            ),
            focused_window_ids=tuple(
                int(window_id)
                for window_id in value.get("focused_window_ids") or ()
            ),
            sidebar_windows={
                int(tab_id): int(window_id)
                for tab_id, window_id in (
                    value.get("sidebar_windows") or {}
                ).items()
            },
            repository_path=value.get("repository_path"),
            repository_lines=tuple(value.get("repository_lines") or ()),
            repository_location=(
                RepositoryLocation(**value["repository_location"])
                if value.get("repository_location") is not None
                else None
            ),
            error=value.get("error"),
        )


def _frame(snapshot: SharedSnapshot) -> bytes:
    payload = snapshot.to_bytes()
    return len(payload).to_bytes(4, "big") + payload


def _socket_is_live(path: Path) -> bool:
    if not path.exists():
        return False
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(0.05)
    try:
        client.connect(str(path))
    except OSError:
        return False
    finally:
        client.close()
    return True


class SnapshotServer:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.listener: socket.socket | None = None
        self.clients: list[socket.socket] = []
        self.cached_frame = b""
        self.inode: int | None = None

    def open(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if _socket_is_live(self.path):
            raise RuntimeError(f"ktt daemon socket is already active: {self.path}")
        self.path.unlink(missing_ok=True)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(self.path))
        self.path.chmod(0o600)
        self.inode = self.path.stat().st_ino
        listener.listen()
        listener.setblocking(False)
        self.listener = listener

    def accept_pending(self) -> None:
        if self.listener is None:
            return
        while True:
            try:
                client, _ = self.listener.accept()
            except BlockingIOError:
                return
            client.settimeout(0.1)
            if self.cached_frame:
                try:
                    client.sendall(self.cached_frame)
                except OSError:
                    client.close()
                    continue
            self.clients.append(client)

    def broadcast(self, snapshot: SharedSnapshot) -> None:
        frame = _frame(snapshot)
        self.cached_frame = frame
        survivors: list[socket.socket] = []
        for client in self.clients:
            try:
                client.sendall(frame)
            except OSError:
                client.close()
            else:
                survivors.append(client)
        self.clients = survivors

    def close(self) -> None:
        for client in self.clients:
            client.close()
        self.clients.clear()
        if self.listener is not None:
            self.listener.close()
            self.listener = None
        if self.inode is not None:
            try:
                if self.path.stat().st_ino == self.inode:
                    self.path.unlink()
            except FileNotFoundError:
                pass

    def __enter__(self) -> SnapshotServer:
        self.open()
        return self

    def __exit__(self, *_error: object) -> None:
        self.close()


class SharedSnapshotClient:
    def __init__(
        self,
        os_window_id: int,
        *,
        socket_path: str | Path | None = None,
        runtime_dir: str | None = None,
        kitty_pid: int | None = None,
    ) -> None:
        self.path = (
            Path(socket_path)
            if socket_path is not None
            else daemon_socket_path(
                os_window_id,
                runtime_dir=runtime_dir,
                kitty_pid=kitty_pid,
            )
        )
        self.socket: socket.socket | None = None
        self.buffer = bytearray()
        self.next_connect = 0.0

    def _disconnect(self) -> None:
        if self.socket is not None:
            self.socket.close()
        self.socket = None
        self.buffer.clear()

    def _connect(self, now: float) -> None:
        if self.socket is not None or now < self.next_connect:
            return
        self.next_connect = now + 0.25
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(0.1)
        try:
            client.connect(str(self.path))
        except OSError:
            client.close()
            return
        client.setblocking(False)
        self.socket = client

    def take_latest(self, now: float | None = None) -> SharedSnapshot | None:
        current = time.monotonic() if now is None else now
        self._connect(current)
        if self.socket is None:
            return None
        while True:
            try:
                chunk = self.socket.recv(65536)
            except BlockingIOError:
                break
            except OSError:
                self._disconnect()
                return None
            if not chunk:
                self._disconnect()
                return None
            self.buffer.extend(chunk)
        latest: SharedSnapshot | None = None
        while len(self.buffer) >= 4:
            length = int.from_bytes(self.buffer[:4], "big")
            if length > MAX_FRAME_BYTES:
                self._disconnect()
                return None
            if len(self.buffer) < 4 + length:
                break
            payload = bytes(self.buffer[4:4 + length])
            del self.buffer[:4 + length]
            try:
                latest = SharedSnapshot.from_bytes(payload)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return latest

    def close(self) -> None:
        self._disconnect()

    def __enter__(self) -> SharedSnapshotClient:
        return self

    def __exit__(self, *_error: object) -> None:
        self.close()


def daemon_arguments(
    target_os_window_id: int,
    *,
    to: str | None,
    poll_interval: float,
    edge_style: str,
    repository_palette: str,
    pane_percent: int,
    orientation: str,
) -> list[str]:
    arguments = [sys.executable, "-m", "ktt"]
    if to:
        arguments.extend(("--to", to))
    arguments.extend((
        "--target-os-window",
        str(target_os_window_id),
        "--poll-interval",
        str(poll_interval),
        "--edge-style",
        edge_style,
        "--repository-palette",
        repository_palette,
        "--orientation",
        orientation,
        "daemon",
        "--pane-percent",
        str(pane_percent),
    ))
    return arguments


def start_daemon(
    target_os_window_id: int,
    *,
    to: str | None,
    poll_interval: float,
    edge_style: str,
    repository_palette: str,
    pane_percent: int,
    orientation: str,
    timeout: float = 3.0,
) -> int:
    path = daemon_socket_path(target_os_window_id)
    state_path = daemon_state_path(target_os_window_id)
    process = subprocess.Popen(
        daemon_arguments(
            target_os_window_id,
            to=to,
            poll_interval=poll_interval,
            edge_style=edge_style,
            repository_palette=repository_palette,
            pane_percent=pane_percent,
            orientation=orientation,
        ),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("ktt daemon exited before opening its socket")
        if path.exists() and state_path.exists():
            return process.pid
        time.sleep(0.025)
    process.terminate()
    raise RuntimeError("ktt daemon did not open its socket in time")


def stop_daemon(target_os_window_id: int, timeout: float = 2.0) -> bool:
    state_path = daemon_state_path(target_os_window_id)
    socket_path = daemon_socket_path(target_os_window_id)
    try:
        state = json.loads(state_path.read_text())
        pid = int(state["pid"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        if not _socket_is_live(socket_path):
            socket_path.unlink(missing_ok=True)
        return False
    if pid <= 1:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        if not _socket_is_live(socket_path):
            socket_path.unlink(missing_ok=True)
            state_path.unlink(missing_ok=True)
            return True
        return False
    except PermissionError:
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and socket_path.exists():
        time.sleep(0.025)
    return not socket_path.exists()


def _focused_window_ids(os_window: dict[str, Any]) -> tuple[int, ...]:
    return tuple(
        int(window["id"])
        for tab in os_window.get("tabs") or []
        for window in tab.get("windows") or []
        if window.get("is_focused")
    )


def _embedded_sidebar_width(
    os_window: dict[str, Any], sidebar_windows: dict[int, int]
) -> int:
    window_ids = set(sidebar_windows.values())
    return max(
        (
            int(window.get("columns") or 0)
            for tab in os_window.get("tabs") or []
            for window in tab.get("windows") or []
            if int(window.get("id") or 0) in window_ids
        ),
        default=0,
    )


def run_daemon(
    remote: RemoteControl,
    target_os_window_id: int,
    *,
    poll_interval: float,
    edge_style: str,
    repository_palette: str = DEFAULT_REPOSITORY_PALETTE,
    pane_percent: int = 10,
    orientation: str = "horizontal",
) -> int:
    socket_path = daemon_socket_path(target_os_window_id)
    state_path = daemon_state_path(target_os_window_id)
    stopping = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    previous_term = signal.signal(signal.SIGTERM, request_stop)
    previous_int = signal.signal(signal.SIGINT, request_stop)
    sequence = 0
    records: list[TabRecord] = []
    rows = []
    next_refresh = 0.0
    state_inode: int | None = None
    repository_monitor = FancylogMonitor(palette=repository_palette)
    repository_locations = RepositoryLocationCache()
    try:
        with (
            SnapshotServer(socket_path) as server,
            TabEventListener() as tab_events,
            VisibleOrderPublisher() as order_publisher,
            FancylogIdentityCache(palette=repository_palette) as identities,
        ):
            state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            temporary = state_path.with_suffix(f".{os.getpid()}.tmp")
            temporary.write_text(json.dumps({
                "pid": os.getpid(),
                "target_os_window_id": target_os_window_id,
                "pane_percent": pane_percent,
                "orientation": orientation,
            }))
            temporary.chmod(0o600)
            state_inode = temporary.stat().st_ino
            temporary.replace(state_path)
            tab_events.bind(target_os_window_id)

            while not stopping:
                now = time.monotonic()
                timeout = max(0.0, next_refresh - now)
                readers: list[object] = []
                if server.listener is not None:
                    readers.append(server.listener)
                if tab_events.socket is not None:
                    readers.append(tab_events.socket)
                readable, _, _ = select.select(readers, [], [], timeout)
                if server.listener in readable:
                    server.accept_pending()

                messages = tab_events.drain() if tab_events.socket in readable else ()
                navigation = [
                    direction
                    for message in messages
                    if (direction := navigation_direction(message)) is not None
                ]
                if navigation and rows:
                    target = adjacent_tree_tab_id(rows, navigation[0])
                    if target is not None:
                        remote.focus_tab(target)

                now = time.monotonic()
                if now < next_refresh and not messages:
                    continue
                next_refresh = now + poll_interval
                try:
                    snapshot = remote.snapshot()
                    if not any(
                        int(item["id"]) == target_os_window_id
                        for item in snapshot
                    ):
                        break
                    os_window = os_window_by_id(snapshot, target_os_window_id)
                    created = remote.sync_embedded_panes(
                        snapshot,
                        target_os_window_id,
                        edge_style,
                        repository_palette,
                        pane_percent,
                        str(socket_path),
                        orientation,
                    )
                    if created:
                        snapshot = remote.snapshot()
                        os_window = os_window_by_id(snapshot, target_os_window_id)
                    records = records_for_os_window(os_window)
                    names = identities.update(record.cwd for record in records)
                    records = with_repository_names(records, names)
                    records = with_repository_worktrees(
                        records, identities.worktrees()
                    )
                    folded = read_folded_tab_ids(target_os_window_id)
                    rows = tree_rows(records, folded)
                    order_publisher.publish(target_os_window_id, rows)
                    sidebar_windows = embedded_sidebar_windows(os_window)
                    repository_path = active_window_cwd(os_window)
                    repository_lines = repository_monitor.update(
                        repository_path,
                        _embedded_sidebar_width(os_window, sidebar_windows),
                        MAX_REPOSITORY_LINES,
                        now,
                    )
                    repository_location = repository_locations.update(
                        repository_path
                    )
                    error = None
                except (OSError, RuntimeError, ValueError) as caught:
                    folded = read_folded_tab_ids(target_os_window_id)
                    os_window = {"tabs": []}
                    sidebar_windows = {}
                    repository_path = None
                    repository_lines = []
                    repository_location = None
                    error = str(caught)

                sequence += 1
                server.broadcast(SharedSnapshot(
                    sequence=sequence,
                    os_window_id=target_os_window_id,
                    records=tuple(records),
                    folded_tab_ids=tuple(sorted(folded)),
                    focused_window_ids=_focused_window_ids(os_window),
                    sidebar_windows=sidebar_windows,
                    repository_path=repository_path,
                    repository_lines=tuple(repository_lines),
                    repository_location=repository_location,
                    error=error,
                ))
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)
        if state_inode is not None:
            try:
                if state_path.stat().st_ino == state_inode:
                    state_path.unlink()
            except FileNotFoundError:
                pass
    return 0
