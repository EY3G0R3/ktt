from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
from typing import Any, Sequence

from .model import PARENT_VAR
from .native_tabs import NativeVerticalTabsUnsupported


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
            raise KittyError(
                f"Kitty remote control timed out after {self.timeout:g}s"
            ) from error
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

        frame = (
            KITTY_COMMAND_PREFIX
            + json.dumps(
                {"cmd": "ls", "version": KITTY_PROTOCOL_VERSION},
                separators=(",", ":"),
            ).encode()
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

    def focus_window(self, window_id: int) -> None:
        self.run("focus-window", "--match", f"id:{window_id}")

    def close_window(self, window_id: int) -> None:
        self.run("close-window", "--match", f"id:{window_id}")

    def enable_native_vertical_tabs(self, source_window_id: int) -> None:
        """Show native vertical tabs in the source window's Kitty process."""
        kitten = Path(__file__).with_name("native_tabs_kitten.py")
        try:
            self.run(
                "action",
                "--match",
                f"id:{source_window_id}",
                "kitten",
                str(kitten),
                "vertical",
            )
        except KittyError as error:
            unsupported = NativeVerticalTabsUnsupported.from_message(str(error))
            if unsupported is not None:
                raise unsupported from error
            raise

    def set_parent(self, child_window_id: int, parent_window_id: int | None) -> None:
        value = "" if parent_window_id is None else str(parent_window_id)
        self.run(
            "set-user-vars",
            "--match",
            f"id:{child_window_id}",
            f"{PARENT_VAR}={value}",
        )

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
            raise KittyError(
                f"Kitty returned an invalid child window ID: {output!r}"
            ) from error


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
