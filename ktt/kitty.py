from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from typing import Any, Sequence

from .model import COCKPIT_ROLE_VAR, PARENT_VAR, SIDEBAR_VAR


TARGET_OS_WINDOW_VAR = "ktt_target_os_window_id"
ORIENTATION_VAR = "ktt_orientation"
SIDEBAR_BACKGROUND = "#000000"
KITTY_COMMAND_PREFIX = b"\x1bP@kitty-cmd"
KITTY_COMMAND_SUFFIX = b"\x1b\\"
KITTY_PROTOCOL_VERSION = [0, 14, 2]
MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024


class KittyError(RuntimeError):
    pass


class RemoteControl:
    def __init__(self, to: str | None = None, timeout: float = 3.0) -> None:
        self.to = to or os.environ.get("KITTY_LISTEN_ON")
        self.timeout = timeout
        self._direct_snapshot_enabled = bool(
            self.to and self.to.startswith("unix:")
        )

    def _command(self, subcommand: str, *arguments: str) -> list[str]:
        command = ["kitten", "@"]
        if self.to:
            command.extend(("--to", self.to))
        command.append(subcommand)
        command.extend(arguments)
        return command

    def run(self, subcommand: str, *arguments: str) -> str:
        try:
            result = subprocess.run(
                self._command(subcommand, *arguments),
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except FileNotFoundError as error:
            raise KittyError("`kitten` is not installed or is not on PATH") from error
        except subprocess.TimeoutExpired as error:
            raise KittyError(f"Kitty remote control timed out after {self.timeout:g}s") from error
        if result.returncode:
            detail = (result.stderr or result.stdout).strip().splitlines()
            message = detail[-1] if detail else f"exit status {result.returncode}"
            raise KittyError(f"Kitty {subcommand} failed: {message}")
        return result.stdout.strip()

    def snapshot(self) -> list[dict[str, Any]]:
        if self._direct_snapshot_enabled:
            try:
                value = self._direct_snapshot()
            except (OSError, TimeoutError, KittyError):
                # Addresses such as inherited socket-pair descriptors and
                # password-protected listeners need kitten's full client.
                # Disable the probe after its first failure so recovery polls
                # do not repeatedly pay for two requests.
                self._direct_snapshot_enabled = False
            else:
                return self._validate_snapshot(value, "Kitty socket")

        output = self.run("ls")
        try:
            value = json.loads(output)
        except json.JSONDecodeError as error:
            raise KittyError("Kitty returned invalid JSON from `kitten @ ls`") from error
        return self._validate_snapshot(value, "`kitten @ ls`")

    def _validate_snapshot(
        self, value: Any, source: str
    ) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            raise KittyError(f"Kitty returned an unexpected value from {source}")
        return value

    def _direct_snapshot(self) -> Any:
        assert self.to is not None
        address = self.to.removeprefix("unix:")
        if not address:
            raise KittyError("Kitty Unix socket address is empty")
        if address.startswith("@"):
            address = "\0" + address[1:]

        request = {
            "cmd": "ls",
            # A standalone client must advertise a protocol version no newer
            # than the Kitty it contacts. This is Kitty's documented baseline
            # for the stable `ls` request used here.
            "version": KITTY_PROTOCOL_VERSION,
        }
        frame = (
            KITTY_COMMAND_PREFIX
            + json.dumps(request, separators=(",", ":")).encode()
            + KITTY_COMMAND_SUFFIX
        )
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(self.timeout)
            connection.connect(address)
            connection.sendall(frame)
            response = bytearray()
            while KITTY_COMMAND_SUFFIX not in response:
                chunk = connection.recv(65536)
                if not chunk:
                    raise KittyError("Kitty closed its socket before replying")
                response.extend(chunk)
                if len(response) > MAX_SNAPSHOT_BYTES:
                    raise KittyError("Kitty snapshot exceeded the safety limit")

        prefix_at = response.find(KITTY_COMMAND_PREFIX)
        if prefix_at < 0:
            raise KittyError("Kitty socket reply had no command frame")
        body_at = prefix_at + len(KITTY_COMMAND_PREFIX)
        suffix_at = response.find(KITTY_COMMAND_SUFFIX, body_at)
        try:
            reply = json.loads(response[body_at:suffix_at])
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise KittyError("Kitty socket returned invalid JSON") from error
        if not isinstance(reply, dict):
            raise KittyError("Kitty socket returned an unexpected reply")
        if not reply.get("ok"):
            raise KittyError(str(reply.get("error") or "Kitty socket request failed"))
        data = reply.get("data")
        if isinstance(data, str):
            try:
                return json.loads(data)
            except json.JSONDecodeError as error:
                raise KittyError("Kitty socket returned invalid snapshot JSON") from error
        return data

    def focus_tab(self, tab_id: int) -> None:
        self.run("focus-tab", "--match", f"id:{tab_id}")

    def focus_window(self, window_id: int) -> None:
        self.run("focus-window", "--match", f"id:{window_id}")

    def preview_tab(self, tab_id: int, sidebar_window_id: int) -> None:
        # focus-tab necessarily switches OS focus. Restore it only after Kitty
        # acknowledges the tab change, allowing repeated navigation in ktt.
        self.focus_tab(tab_id)
        self.focus_window(sidebar_window_id)

    def preview_embedded_tab(
        self, tab_id: int, sidebar_window_id: int | None
    ) -> None:
        self.focus_tab(tab_id)
        if sidebar_window_id is not None:
            self.focus_window(sidebar_window_id)

    def toggle_native_tabs(self, source_window_id: int) -> None:
        kitten = Path(__file__).with_name("tree_navigation_kitten.py")
        self.run(
            "action",
            "--match",
            f"id:{source_window_id}",
            "kitten",
            str(kitten),
            "toggle-tabs",
        )

    def set_parent(self, child_window_id: int, parent_window_id: int | None) -> None:
        value = "" if parent_window_id is None else str(parent_window_id)
        self.run(
            "set-user-vars",
            "--match",
            f"id:{child_window_id}",
            f"{PARENT_VAR}={value}",
        )

    def configure_sidebar(
        self,
        sidebar_window_id: int,
        target_os_window_id: int | None,
        orientation: str,
        embedded: bool = False,
    ) -> None:
        """Reapply the launch-time appearance and identity to a running sidebar."""
        self.run(
            "set-colors",
            "--match",
            f"id:{sidebar_window_id}",
            f"background={SIDEBAR_BACKGROUND}",
        )
        assignments = [
            f"{SIDEBAR_VAR}=1",
            f"{ORIENTATION_VAR}={orientation}",
        ]
        if target_os_window_id is not None:
            assignments.append(
                f"{TARGET_OS_WINDOW_VAR}={target_os_window_id}"
            )
        if embedded:
            assignments.append(f"{COCKPIT_ROLE_VAR}=ktt")
        self.run(
            "set-user-vars",
            "--match",
            f"id:{sidebar_window_id}",
            *assignments,
        )

    def _sidebar_process(
        self,
        target_os_window_id: int,
        edge_style: str | None = None,
        repository_palette: str | None = None,
        orientation: str = "vertical",
        embedded: bool = False,
        shared_socket: str | None = None,
    ) -> tuple[str, list[str]]:
        package_root = str(Path(__file__).resolve().parent.parent)
        process = [
            sys.executable,
            "-m",
            "ktt",
        ]
        if self.to:
            process.extend(("--to", self.to))
        process.extend(("--target-os-window", str(target_os_window_id)))
        process.extend(("--orientation", orientation))
        if embedded:
            process.append("--embedded")
        if shared_socket:
            process.extend(("--shared-socket", shared_socket))
        if edge_style:
            process.extend(("--edge-style", edge_style))
        if repository_palette:
            process.extend(("--repository-palette", repository_palette))
        return package_root, process

    def launch_pane(
        self,
        source_window_id: int,
        target_os_window_id: int,
        edge_style: str | None = None,
        repository_palette: str | None = None,
        pane_percent: int = 10,
        shared_socket: str | None = None,
        orientation: str = "horizontal",
    ) -> int:
        package_root, process = self._sidebar_process(
            target_os_window_id,
            edge_style,
            repository_palette,
            orientation,
            embedded=True,
            shared_socket=shared_socket,
        )
        location = "hsplit" if orientation == "horizontal" else "vsplit"
        output = self.run(
            "launch",
            "--match",
            f"window_id:{source_window_id}",
            "--source-window",
            f"id:{source_window_id}",
            "--next-to",
            f"id:{source_window_id}",
            "--type=window",
            f"--location={location}",
            f"--bias={pane_percent}",
            "--keep-focus",
            "--title=ktt",
            "--color",
            f"background={SIDEBAR_BACKGROUND}",
            f"--cwd={package_root}",
            "--var",
            f"{SIDEBAR_VAR}=1",
            "--var",
            f"{TARGET_OS_WINDOW_VAR}={target_os_window_id}",
            "--var",
            f"{ORIENTATION_VAR}={orientation}",
            "--var",
            f"{COCKPIT_ROLE_VAR}=ktt",
            *process,
        )
        try:
            pane_window_id = int(output)
        except ValueError as error:
            raise KittyError(
                f"Kitty returned an invalid embedded window ID: {output!r}"
            ) from error
        if orientation == "vertical":
            self.run(
                "action",
                "--match",
                f"id:{source_window_id}",
                "move_window",
                "right",
            )
        return pane_window_id

    def sync_embedded_panes(
        self,
        snapshot: Sequence[dict[str, Any]],
        target_os_window_id: int,
        edge_style: str | None = None,
        repository_palette: str | None = None,
        pane_percent: int = 10,
        shared_socket: str | None = None,
        orientation: str = "horizontal",
    ) -> list[int]:
        os_window = os_window_by_id(snapshot, target_os_window_id)
        existing = embedded_sidebar_windows(os_window, orientation)
        created: list[int] = []
        for tab in os_window.get("tabs") or []:
            tab_id = int(tab["id"])
            source = content_window_for_tab(
                tab, prefer_active=orientation == "vertical"
            )
            if source is None:
                for window in tab.get("windows") or []:
                    variables = window.get("user_vars") or {}
                    if str(variables.get(SIDEBAR_VAR) or "") == "1":
                        self.run(
                            "close-window",
                            "--match",
                            f"id:{int(window['id'])}",
                        )
                continue
            if tab_id in existing:
                continue
            created.append(
                self.launch_pane(
                    source,
                    target_os_window_id,
                    edge_style,
                    repository_palette,
                    pane_percent,
                    shared_socket,
                    orientation,
                )
            )
        return created

    def close_embedded_panes(
        self,
        snapshot: Sequence[dict[str, Any]],
        target_os_window_id: int,
    ) -> list[int]:
        os_window = os_window_by_id(snapshot, target_os_window_id)
        window_ids = embedded_sidebar_window_ids(os_window)
        for window_id in window_ids:
            self.run("close-window", "--match", f"id:{window_id}")
        return window_ids

    def launch_sidebar(
        self,
        target_os_window_id: int,
        edge_style: str | None = None,
        repository_palette: str | None = None,
        orientation: str = "vertical",
    ) -> int:
        package_root, process = self._sidebar_process(
            target_os_window_id, edge_style, repository_palette, orientation
        )
        window_class = "ktt" if orientation == "vertical" else "ktt-horizontal"
        window_title = (
            "Kitty Tab Tree"
            if orientation == "vertical"
            else "Kitty Tab Tree — horizontal"
        )
        output = self.run(
            "launch",
            "--type=os-window",
            f"--os-window-class={window_class}",
            f"--os-window-name={window_class}",
            f"--os-window-title={window_title}",
            "--title=ktt",
            "--color",
            f"background={SIDEBAR_BACKGROUND}",
            f"--cwd={package_root}",
            "--var",
            f"{SIDEBAR_VAR}=1",
            "--var",
            f"{TARGET_OS_WINDOW_VAR}={target_os_window_id}",
            "--var",
            f"{ORIENTATION_VAR}={orientation}",
            *process,
        )
        try:
            return int(output)
        except ValueError as error:
            raise KittyError(f"Kitty returned an invalid new window ID: {output!r}") from error

    def replace_sidebar(
        self,
        sidebar_window_id: int,
        target_os_window_id: int,
        edge_style: str | None = None,
        repository_palette: str | None = None,
        orientation: str = "vertical",
    ) -> int:
        package_root, process = self._sidebar_process(
            target_os_window_id, edge_style, repository_palette, orientation
        )
        output = self.run(
            "launch",
            "--match",
            f"window_id:{sidebar_window_id}",
            "--source-window",
            f"id:{sidebar_window_id}",
            "--type=window",
            "--location=after",
            "--title=ktt",
            "--color",
            f"background={SIDEBAR_BACKGROUND}",
            f"--cwd={package_root}",
            "--var",
            f"{SIDEBAR_VAR}=1",
            "--var",
            f"{TARGET_OS_WINDOW_VAR}={target_os_window_id}",
            "--var",
            f"{ORIENTATION_VAR}={orientation}",
            *process,
        )
        try:
            new_window_id = int(output)
        except ValueError as error:
            raise KittyError(f"Kitty returned an invalid replacement window ID: {output!r}") from error
        self.run("close-window", "--match", f"id:{sidebar_window_id}")
        return new_window_id

    def launch_child(
        self,
        parent_window_id: int,
        child_command: Sequence[str],
        title: str | None = None,
    ) -> int:
        arguments = [
            "--type=tab",
            "--source-window",
            f"id:{parent_window_id}",
            "--location=after",
            "--cwd=current",
            "--var",
            f"{PARENT_VAR}={parent_window_id}",
        ]
        if title:
            arguments.extend(("--tab-title", title))
        arguments.extend(child_command)
        output = self.run("launch", *arguments)
        try:
            return int(output)
        except ValueError as error:
            raise KittyError(f"Kitty returned an invalid child window ID: {output!r}") from error


def find_tab_for_window(
    snapshot: Sequence[dict[str, Any]], window_id: int
) -> tuple[int, int] | None:
    for os_window in snapshot:
        for tab in os_window.get("tabs") or []:
            if any(
                int(window["id"]) == window_id
                for window in tab.get("windows") or []
            ):
                return int(os_window["id"]), int(tab["id"])
    return None


def os_window_by_id(
    snapshot: Sequence[dict[str, Any]], os_window_id: int
) -> dict[str, Any]:
    for os_window in snapshot:
        if int(os_window["id"]) == os_window_id:
            return os_window
    raise ValueError(f"Kitty OS window {os_window_id} does not exist")


def embedded_sidebar_windows(
    os_window: dict[str, Any], orientation: str | None = None
) -> dict[int, int]:
    result: dict[int, int] = {}
    for tab in os_window.get("tabs") or []:
        for window in tab.get("windows") or []:
            variables = window.get("user_vars") or {}
            recorded_orientation = str(
                variables.get(ORIENTATION_VAR) or "vertical"
            )
            if (
                str(variables.get(SIDEBAR_VAR) or "") == "1"
                and (
                    orientation is None
                    or recorded_orientation == orientation
                )
            ):
                result[int(tab["id"])] = int(window["id"])
                break
    return result


def embedded_sidebar_window_ids(
    os_window: dict[str, Any], orientation: str | None = None
) -> list[int]:
    result: list[int] = []
    for tab in os_window.get("tabs") or []:
        for window in tab.get("windows") or []:
            variables = window.get("user_vars") or {}
            recorded_orientation = str(
                variables.get(ORIENTATION_VAR) or "vertical"
            )
            if (
                str(variables.get(SIDEBAR_VAR) or "") == "1"
                and (
                    orientation is None
                    or recorded_orientation == orientation
                )
            ):
                result.append(int(window["id"]))
    return result


def content_window_for_tab(
    tab: dict[str, Any], *, prefer_active: bool = False
) -> int | None:
    windows = [
        window
        for window in tab.get("windows") or []
        if str((window.get("user_vars") or {}).get(SIDEBAR_VAR) or "") != "1"
    ]
    if not windows:
        return None
    windows.sort(
        key=lambda window: (
            prefer_active and not bool(window.get("is_active")),
            str(
                (window.get("user_vars") or {}).get(COCKPIT_ROLE_VAR) or ""
            )
            != "agent",
            not bool(window.get("is_active")),
        )
    )
    return int(windows[0]["id"])


def find_sidebar_window(
    snapshot: Sequence[dict[str, Any]],
    orientation: str | None = None,
) -> tuple[int, int, int | None] | None:
    fallback = None
    for os_window in snapshot:
        class_match = (
            str(os_window.get("wm_class") or "").lower() == "ktt"
            or str(os_window.get("wm_name") or "").lower() == "ktt"
        )
        for tab in os_window.get("tabs") or []:
            for window in tab.get("windows") or []:
                variables = window.get("user_vars") or {}
                recorded_orientation = str(
                    variables.get(ORIENTATION_VAR) or "vertical"
                )
                if orientation is not None and recorded_orientation != orientation:
                    continue
                target_value = str(variables.get(TARGET_OS_WINDOW_VAR) or "")
                target = int(target_value) if target_value.isdigit() else None
                result = (int(os_window["id"]), int(window["id"]), target)
                if str(variables.get(SIDEBAR_VAR) or "") == "1":
                    return result
                command = [str(part) for part in window.get("cmdline") or []]
                looks_like_ktt = "-m" in command and "ktt" in command
                if fallback is None and (class_match or looks_like_ktt):
                    fallback = result
    return fallback
