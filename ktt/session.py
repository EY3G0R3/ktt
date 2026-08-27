from __future__ import annotations

import json
import os
import shlex
import sqlite3
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .kitty import RemoteControl
from .model import PARENT_VAR, SIDEBAR_VAR, records_for_os_window

MANIFEST_VERSION = 1
SESSION_MATCH_WINDOW_MS = 120_000


class SessionManifestError(ValueError):
    pass


@dataclass(frozen=True)
class AgentState:
    kind: str
    identity: str
    session_id: str | None = None
    restorable: bool = True
    reason: str | None = None

    def resume_command(self) -> tuple[str, ...]:
        if self.kind == "codex" and self.session_id:
            return ("codex", "resume", self.session_id)
        if self.kind == "claude" and self.session_id:
            return ("claude", "--resume", self.session_id)
        if self.kind == "tmux" and self.session_id:
            return ("tmux", "attach-session", "-t", self.session_id)
        return ()

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "kind": self.kind,
            "identity": self.identity,
            "restorable": self.restorable,
        }
        if self.session_id:
            result["session_id"] = self.session_id
        if self.reason:
            result["reason"] = self.reason
        return result

    @classmethod
    def from_dict(cls, value: object, location: str) -> AgentState:
        data = _object(value, location)
        kind = _string(data.get("kind"), f"{location}.kind")
        identity = _string(data.get("identity"), f"{location}.identity")
        session_id = _optional_string(data.get("session_id"), f"{location}.session_id")
        restorable = _boolean(data.get("restorable"), f"{location}.restorable")
        reason = _optional_string(data.get("reason"), f"{location}.reason")
        if kind not in {"shell", "codex", "claude", "tmux", "other"}:
            raise SessionManifestError(
                f"{location}.kind: unsupported agent kind {kind!r}"
            )
        if kind in {"codex", "claude", "tmux"} and restorable and not session_id:
            raise SessionManifestError(
                f"{location}: restorable {kind} agent requires a session_id"
            )
        return cls(kind, identity, session_id, restorable, reason)


@dataclass(frozen=True)
class SessionTab:
    logical_id: str
    title: str
    cwd: str | None
    parent: str | None
    active: bool
    focused: bool
    agent: AgentState

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.logical_id,
            "title": self.title,
            "parent": self.parent,
            "active": self.active,
            "focused": self.focused,
            "agent": self.agent.as_dict(),
        }
        if self.cwd:
            result["cwd"] = self.cwd
        return result

    @classmethod
    def from_dict(cls, value: object, location: str) -> SessionTab:
        data = _object(value, location)
        logical_id = _string(data.get("id"), f"{location}.id")
        title = _string(data.get("title"), f"{location}.title")
        cwd = _optional_string(data.get("cwd"), f"{location}.cwd")
        parent = _optional_string(data.get("parent"), f"{location}.parent")
        active = _boolean(data.get("active"), f"{location}.active")
        focused = _boolean(data.get("focused"), f"{location}.focused")
        agent = AgentState.from_dict(data.get("agent"), f"{location}.agent")
        return cls(logical_id, title, cwd, parent, active, focused, agent)


@dataclass(frozen=True)
class SessionOsWindow:
    logical_id: str
    title: str
    tabs: tuple[SessionTab, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.logical_id,
            "title": self.title,
            "tabs": [tab.as_dict() for tab in self.tabs],
        }

    @classmethod
    def from_dict(cls, value: object, location: str) -> SessionOsWindow:
        data = _object(value, location)
        logical_id = _string(data.get("id"), f"{location}.id")
        title = _string(data.get("title", ""), f"{location}.title")
        raw_tabs = _array(data.get("tabs"), f"{location}.tabs")
        tabs = tuple(
            SessionTab.from_dict(tab, f"{location}.tabs[{index}]")
            for index, tab in enumerate(raw_tabs)
        )
        if not tabs:
            raise SessionManifestError(f"{location}.tabs: expected at least one tab")
        return cls(logical_id, title, tabs)


@dataclass(frozen=True)
class SessionManifest:
    created_at: str
    hostname: str
    os_windows: tuple[SessionOsWindow, ...]
    warnings: tuple[str, ...] = ()

    @property
    def tab_count(self) -> int:
        return sum(len(window.tabs) for window in self.os_windows)

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": MANIFEST_VERSION,
            "created_at": self.created_at,
            "hostname": self.hostname,
            "os_windows": [window.as_dict() for window in self.os_windows],
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: object) -> SessionManifest:
        data = _object(value, "manifest")
        version = data.get("version")
        if version != MANIFEST_VERSION:
            raise SessionManifestError(
                f"manifest.version: expected {MANIFEST_VERSION}, got {version!r}"
            )
        created_at = _string(data.get("created_at"), "manifest.created_at")
        hostname = _string(data.get("hostname"), "manifest.hostname")
        raw_windows = _array(data.get("os_windows"), "manifest.os_windows")
        windows = tuple(
            SessionOsWindow.from_dict(window, f"manifest.os_windows[{index}]")
            for index, window in enumerate(raw_windows)
        )
        warnings = tuple(
            _string(item, f"manifest.warnings[{index}]")
            for index, item in enumerate(
                _array(data.get("warnings", []), "manifest.warnings")
            )
        )
        manifest = cls(created_at, hostname, windows, warnings)
        _validate_relationships(manifest)
        return manifest


@dataclass(frozen=True)
class PlannedTab:
    os_window_id: str
    os_window_title: str
    logical_id: str
    source: str | None
    parent: str | None
    title: str
    cwd: str | None
    command: tuple[str, ...]
    active: bool
    focused: bool
    placeholder_reason: str | None

    def describe(self) -> str:
        relationship = f" child-of={self.parent}" if self.parent else " root"
        command = shlex.join(self.command) if self.command else "<shell>"
        suffix = (
            f"; placeholder: {self.placeholder_reason}"
            if self.placeholder_reason
            else ""
        )
        return (
            f"{self.os_window_id}/{self.logical_id}:{relationship}; "
            f"cwd={self.cwd or '<default>'}; command={command}{suffix}"
        )


SessionResolver = Callable[[str, int, str | None, Sequence[str]], str | None]
TmuxChecker = Callable[[str], bool]


def default_manifest_path() -> Path:
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    return state_home / "ktt" / "session.json"


def capture_session(
    snapshot: Sequence[Mapping[str, Any]],
    *,
    hostname: str,
    created_at: str,
    session_resolver: SessionResolver | None = None,
) -> SessionManifest:
    resolver = session_resolver or resolve_agent_session
    windows: list[SessionOsWindow] = []
    warnings: list[str] = []

    for os_index, raw_os_window in enumerate(snapshot, start=1):
        os_id = f"os-{os_index}"
        records = records_for_os_window(dict(raw_os_window))
        raw_tabs = {
            int(tab["id"]): tab
            for tab in raw_os_window.get("tabs", [])
            if isinstance(tab, Mapping) and isinstance(tab.get("id"), int)
        }
        record_tabs: list[tuple[Any, Mapping[str, Any], list[Mapping[str, Any]]]] = []
        runtime_to_logical: dict[int, str] = {}

        for record in records:
            raw_tab = raw_tabs.get(record.id)
            if raw_tab is None:
                continue
            content = _content_windows(raw_tab)
            if not content:
                continue
            tab_index = len(record_tabs) + 1
            logical_id = f"tab-{os_index}-{tab_index}"
            for window in content:
                runtime_id = window.get("id")
                if isinstance(runtime_id, int):
                    runtime_to_logical[runtime_id] = logical_id
            record_tabs.append((record, raw_tab, content))

        tabs: list[SessionTab] = []
        for tab_index, (record, raw_tab, content) in enumerate(record_tabs, start=1):
            logical_id = f"tab-{os_index}-{tab_index}"
            parent = runtime_to_logical.get(record.parent_window_id)
            if record.parent_window_id is not None and parent is None:
                warnings.append(
                    f"{logical_id}: parent window was outside the captured ktt tree"
                )
            agent_window, agent = detect_tab_agent(content, resolver)
            agent_cwd = _optional_text(agent_window.get("cwd")) or record.cwd
            if len(content) > 1:
                warnings.append(
                    f"{logical_id}: {len(content)} content panes collapsed to the active pane"
                )
            if not agent.restorable:
                warnings.append(f"{logical_id}: {agent.reason}")
            tabs.append(
                SessionTab(
                    logical_id=logical_id,
                    title=record.title,
                    cwd=agent_cwd,
                    parent=parent,
                    active=record.is_active,
                    focused=bool(raw_os_window.get("is_focused"))
                    and bool(raw_tab.get("is_focused")),
                    agent=agent,
                )
            )

        if tabs:
            windows.append(
                SessionOsWindow(
                    logical_id=os_id,
                    title=str(
                        raw_os_window.get("wm_name") or raw_os_window.get("title") or ""
                    ),
                    tabs=tuple(tabs),
                )
            )

    if not windows:
        raise SessionManifestError("Kitty snapshot contains no restorable content tabs")
    manifest = SessionManifest(created_at, hostname, tuple(windows), tuple(warnings))
    _validate_relationships(manifest)
    return manifest


def detect_agent(window: Mapping[str, Any], resolver: SessionResolver) -> AgentState:
    processes = _processes(window)
    cwd = _optional_text(window.get("cwd"))

    for kind in ("tmux", "hirayama"):
        match = _find_process(processes, kind)
        if match:
            pid, argv, process_cwd = match
            session_id = _explicit_tmux_session(argv) or resolver(
                "tmux", pid, process_cwd or cwd, argv
            )
            if session_id:
                return AgentState("tmux", kind, session_id, True)
            return AgentState(
                kind="tmux",
                identity=kind,
                restorable=False,
                reason="tmux session name could not be verified; opening a shell placeholder",
            )

    for kind in ("codex", "claude"):
        match = _find_process(processes, kind)
        if not match:
            continue
        pid, argv, process_cwd = match
        session_id = _explicit_session_id(kind, argv) or resolver(
            kind, pid, process_cwd or cwd, argv
        )
        if session_id:
            return AgentState(kind, kind, session_id, True)
        return AgentState(
            kind=kind,
            identity=kind,
            restorable=False,
            reason=f"{kind} session ID could not be verified; opening a shell placeholder",
        )

    other = _foreground_identity(processes)
    if other and other not in {"bash", "dash", "fish", "sh", "zsh"}:
        return AgentState(
            kind="other",
            identity=other,
            restorable=False,
            reason=f"unsupported foreground process {other!r}; opening a shell placeholder",
        )
    return AgentState("shell", other or "shell")


def detect_tab_agent(
    windows: Sequence[Mapping[str, Any]],
    resolver: SessionResolver,
) -> tuple[Mapping[str, Any], AgentState]:
    primary = _primary_content_window(windows)
    ordered = [primary, *(window for window in windows if window is not primary)]
    candidates = [(window, detect_agent(window, resolver)) for window in ordered]

    def rank(candidate: tuple[Mapping[str, Any], AgentState]) -> int:
        agent = candidate[1]
        if agent.kind in {"codex", "claude", "tmux"}:
            return 0 if agent.restorable else 1
        if agent.kind == "shell":
            return 2
        return 3

    return min(candidates, key=rank)


def resolve_agent_session(
    kind: str,
    pid: int,
    cwd: str | None,
    argv: Sequence[str],
) -> str | None:
    if kind == "tmux":
        return _tmux_session_for_process(pid, cwd, argv)
    del argv
    from_open_file = _session_from_open_files(kind, pid)
    if from_open_file:
        return from_open_file
    started_at_ms = _process_started_at_ms(pid)
    if cwd is None or started_at_ms is None:
        return None
    if kind == "codex":
        return _codex_session_near(cwd, started_at_ms)
    if kind == "claude":
        return _claude_session_near(cwd, started_at_ms)
    return None


def plan_restore(
    manifest: SessionManifest,
    *,
    tmux_checker: TmuxChecker | None = None,
) -> tuple[PlannedTab, ...]:
    _validate_relationships(manifest)
    check_tmux = tmux_checker or tmux_session_exists
    operations: list[PlannedTab] = []
    for os_window in manifest.os_windows:
        ordered = _parent_first(os_window.tabs)
        previous: str | None = None
        for tab in ordered:
            command = tab.agent.resume_command()
            placeholder_reason = tab.agent.reason if not tab.agent.restorable else None
            if (
                tab.agent.kind == "tmux"
                and tab.agent.session_id
                and not check_tmux(tab.agent.session_id)
            ):
                command = ()
                placeholder_reason = (
                    f"tmux session {tab.agent.session_id!r} is not running; "
                    "opening a shell placeholder"
                )
            operations.append(
                PlannedTab(
                    os_window_id=os_window.logical_id,
                    os_window_title=os_window.title,
                    logical_id=tab.logical_id,
                    source=previous,
                    parent=tab.parent,
                    title=tab.title,
                    cwd=tab.cwd,
                    command=command,
                    active=tab.active,
                    focused=tab.focused,
                    placeholder_reason=placeholder_reason,
                )
            )
            previous = tab.logical_id
    return tuple(operations)


def execute_restore(
    remote: RemoteControl,
    operations: Sequence[PlannedTab],
) -> dict[str, int]:
    runtime_ids: dict[str, int] = {}
    active_tabs: list[int] = []
    focused: int | None = None
    for operation in operations:
        arguments: list[str] = [
            "--type=os-window" if operation.source is None else "--type=tab",
            "--dont-take-focus",
        ]
        if operation.source is not None:
            source_id = runtime_ids[operation.source]
            arguments.extend(("--source-window", f"id:{source_id}", "--location=after"))
        elif operation.os_window_title:
            arguments.extend(("--os-window-title", operation.os_window_title))
        if operation.cwd:
            arguments.append(f"--cwd={operation.cwd}")
        if operation.title:
            arguments.extend(("--tab-title", operation.title))
        if operation.parent:
            parent_id = runtime_ids[operation.parent]
            arguments.extend(("--var", f"{PARENT_VAR}={parent_id}"))
        arguments.extend(operation.command)
        raw_id = remote.run("launch", *arguments)
        try:
            runtime_id = int(raw_id)
        except ValueError as error:
            raise SessionManifestError(
                f"Kitty returned an invalid window ID for {operation.logical_id}: {raw_id!r}"
            ) from error
        runtime_ids[operation.logical_id] = runtime_id
        if operation.active:
            active_tabs.append(runtime_id)
        if operation.focused:
            focused = runtime_id
    for runtime_id in active_tabs:
        remote.focus_window(runtime_id)
    if focused is not None and (not active_tabs or active_tabs[-1] != focused):
        remote.focus_window(focused)
    return runtime_ids


def write_manifest(path: Path, manifest: SessionManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="session.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            json.dump(manifest.as_dict(), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_manifest(path: Path) -> SessionManifest:
    try:
        with path.open() as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise SessionManifestError(
            f"cannot read session manifest {path}: {error}"
        ) from error
    return SessionManifest.from_dict(value)


def _content_windows(tab: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    result: list[Mapping[str, Any]] = []
    for value in tab.get("windows", []):
        if not isinstance(value, Mapping):
            continue
        user_vars = value.get("user_vars")
        if (
            isinstance(user_vars, Mapping)
            and str(user_vars.get(SIDEBAR_VAR) or "") == "1"
        ):
            continue
        result.append(value)
    return result


def _primary_content_window(windows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    return next(
        (
            window
            for window in windows
            if window.get("is_focused") or window.get("is_active")
        ),
        windows[0],
    )


def _processes(
    window: Mapping[str, Any],
) -> list[tuple[int, tuple[str, ...], str | None]]:
    result: list[tuple[int, tuple[str, ...], str | None]] = []
    for value in window.get("foreground_processes", []):
        if not isinstance(value, Mapping):
            continue
        raw_argv = value.get("cmdline")
        if not isinstance(raw_argv, Sequence) or isinstance(raw_argv, (str, bytes)):
            continue
        argv = tuple(str(item) for item in raw_argv if str(item))
        pid = value.get("pid")
        if argv and isinstance(pid, int):
            result.append((pid, argv, _optional_text(value.get("cwd"))))
    if not result:
        raw_argv = window.get("cmdline")
        pid = window.get("pid")
        if (
            isinstance(raw_argv, Sequence)
            and not isinstance(raw_argv, (str, bytes))
            and isinstance(pid, int)
        ):
            argv = tuple(str(item) for item in raw_argv if str(item))
            if argv:
                result.append((pid, argv, _optional_text(window.get("cwd"))))
    return result


def _find_process(
    processes: Sequence[tuple[int, tuple[str, ...], str | None]],
    program: str,
) -> tuple[int, tuple[str, ...], str | None] | None:
    for process in reversed(processes):
        if any(Path(argument).name == program for argument in process[1]):
            return process
    return None


def _foreground_identity(
    processes: Sequence[tuple[int, tuple[str, ...], str | None]],
) -> str | None:
    for _, argv, _ in reversed(processes):
        if argv:
            return Path(argv[0]).name
    return None


def _explicit_session_id(kind: str, argv: Sequence[str]) -> str | None:
    if kind == "codex":
        try:
            index = argv.index("resume")
        except ValueError:
            return None
        if index + 1 < len(argv) and not argv[index + 1].startswith("-"):
            return argv[index + 1]
        return None
    for option in ("--resume", "--session-id"):
        for index, argument in enumerate(argv):
            if argument == option and index + 1 < len(argv):
                return argv[index + 1]
            if argument.startswith(option + "="):
                return argument.split("=", 1)[1]
    return None


def _explicit_tmux_session(argv: Sequence[str]) -> str | None:
    for index, argument in enumerate(argv):
        if argument in {"-t", "--target-session"} and index + 1 < len(argv):
            return argv[index + 1]
        if argument.startswith("--target-session="):
            return argument.split("=", 1)[1]
    return None


def _tmux_session_for_process(
    pid: int,
    cwd: str | None,
    argv: Sequence[str],
) -> str | None:
    explicit = _explicit_tmux_session(argv)
    if explicit:
        return explicit
    clients = _tmux_rows(
        "list-clients",
        "#{client_pid}\t#{session_name}",
    )
    for fields in clients:
        if len(fields) >= 2 and fields[0] == str(pid):
            return fields[1]
    panes = _tmux_rows(
        "list-panes",
        "-a",
        "-F",
        "#{pane_pid}\t#{pane_current_path}\t#{pane_current_command}\t#{session_name}",
    )
    matches = [
        fields[3]
        for fields in panes
        if len(fields) >= 4
        and (
            fields[0] == str(pid)
            or (
                cwd is not None
                and fields[1] == cwd
                and fields[2] in {"hirayama", "tmux"}
            )
        )
    ]
    return matches[0] if len(set(matches)) == 1 else None


def tmux_session_exists(name: str) -> bool:
    try:
        result = subprocess.run(
            ("tmux", "has-session", "-t", name),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


def _tmux_rows(*arguments: str) -> list[list[str]]:
    command = ["tmux", *arguments]
    if "-F" not in command:
        command.insert(2, "-F")
    try:
        result = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return []
    if result.returncode:
        return []
    return [line.split("\t") for line in result.stdout.splitlines() if line]


def _session_from_open_files(kind: str, pid: int) -> str | None:
    root = Path.home() / (".codex/sessions" if kind == "codex" else ".claude/projects")
    fd_root = Path(f"/proc/{pid}/fd")
    try:
        descriptors = tuple(fd_root.iterdir())
    except OSError:
        return None
    for descriptor in descriptors:
        try:
            target = Path(os.readlink(descriptor))
            target.relative_to(root)
        except (OSError, ValueError):
            continue
        if target.suffix != ".jsonl":
            continue
        metadata = _jsonl_metadata(target)
        session_id = metadata.get("session_id")
        if session_id:
            return session_id
    return None


def _process_started_at_ms(pid: int) -> int | None:
    try:
        return int(Path(f"/proc/{pid}").stat().st_ctime * 1000)
    except OSError:
        return None


def _codex_session_near(cwd: str, started_at_ms: int) -> str | None:
    database = Path.home() / ".codex/state_5.sqlite"
    if not database.exists():
        return None
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            rows = connection.execute(
                "select id, created_at_ms from threads where cwd = ? and archived = 0",
                (cwd,),
            ).fetchall()
        finally:
            connection.close()
    except (OSError, sqlite3.Error):
        return None
    matches = [
        (str(session_id), abs(int(created_at_ms) - started_at_ms))
        for session_id, created_at_ms in rows
        if created_at_ms is not None
        and abs(int(created_at_ms) - started_at_ms) <= SESSION_MATCH_WINDOW_MS
    ]
    return matches[0][0] if len(matches) == 1 else None


def _claude_session_near(cwd: str, started_at_ms: int) -> str | None:
    root = Path.home() / ".claude/projects"
    if not root.is_dir():
        return None
    matches: list[str] = []
    candidates_with_mtime: list[tuple[float, Path]] = []
    for path in root.glob("*/*.jsonl"):
        try:
            candidates_with_mtime.append((path.stat().st_mtime, path))
        except OSError:
            continue
    candidates = [path for _, path in sorted(candidates_with_mtime, reverse=True)[:500]]
    for path in candidates:
        metadata = _jsonl_metadata(path)
        if metadata.get("cwd") != cwd or metadata.get("created_at_ms") is None:
            continue
        if (
            abs(int(metadata["created_at_ms"]) - started_at_ms)
            <= SESSION_MATCH_WINDOW_MS
        ):
            session_id = metadata.get("session_id")
            if session_id:
                matches.append(session_id)
    return matches[0] if len(matches) == 1 else None


def _jsonl_metadata(path: Path) -> dict[str, Any]:
    try:
        with path.open(errors="replace") as handle:
            for _ in range(20):
                line = handle.readline()
                if not line:
                    break
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(value, Mapping):
                    continue
                payload = value.get("payload")
                sources = [value]
                if isinstance(payload, Mapping):
                    sources.insert(0, payload)
                session_id = next(
                    (
                        str(source[key])
                        for source in sources
                        for key in ("sessionId", "id")
                        if source.get(key)
                    ),
                    None,
                )
                cwd = next(
                    (str(source["cwd"]) for source in sources if source.get("cwd")),
                    None,
                )
                timestamp = next(
                    (
                        str(source["timestamp"])
                        for source in sources
                        if source.get("timestamp")
                    ),
                    None,
                )
                if session_id:
                    return {
                        "session_id": session_id,
                        "cwd": cwd,
                        "created_at_ms": _timestamp_ms(timestamp),
                    }
    except OSError:
        pass
    return {}


def _timestamp_ms(value: str | None) -> int | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return int(parsed.timestamp() * 1000)


def _parent_first(tabs: Sequence[SessionTab]) -> list[SessionTab]:
    remaining = list(tabs)
    ordered: list[SessionTab] = []
    emitted: set[str] = set()
    while remaining:
        index = next(
            (
                index
                for index, tab in enumerate(remaining)
                if tab.parent is None or tab.parent in emitted
            ),
            None,
        )
        if index is None:
            raise SessionManifestError("session tab relationships contain a cycle")
        tab = remaining.pop(index)
        ordered.append(tab)
        emitted.add(tab.logical_id)
    return ordered


def _validate_relationships(manifest: SessionManifest) -> None:
    if not manifest.os_windows:
        raise SessionManifestError(
            "manifest.os_windows: expected at least one OS window"
        )
    window_ids: set[str] = set()
    tab_ids: set[str] = set()
    focused_tabs = 0
    for window in manifest.os_windows:
        if window.logical_id in window_ids:
            raise SessionManifestError(f"duplicate OS-window ID {window.logical_id!r}")
        window_ids.add(window.logical_id)
        local_ids = {tab.logical_id for tab in window.tabs}
        if len(local_ids) != len(window.tabs):
            raise SessionManifestError(f"{window.logical_id}: duplicate tab IDs")
        overlap = tab_ids.intersection(local_ids)
        if overlap:
            raise SessionManifestError(f"duplicate tab ID {min(overlap)!r}")
        tab_ids.update(local_ids)
        active_tabs = sum(tab.active for tab in window.tabs)
        if active_tabs > 1:
            raise SessionManifestError(
                f"{window.logical_id}: expected at most one active tab"
            )
        for tab in window.tabs:
            if tab.focused and not tab.active:
                raise SessionManifestError(
                    f"{tab.logical_id}: a focused tab must also be active"
                )
            focused_tabs += tab.focused
            if tab.parent and tab.parent not in local_ids:
                raise SessionManifestError(
                    f"{tab.logical_id}: parent {tab.parent!r} is not in the same OS window"
                )
        _parent_first(window.tabs)
    if focused_tabs > 1:
        raise SessionManifestError("manifest: expected at most one focused tab")


def _object(value: object, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SessionManifestError(f"{location}: expected an object")
    return value


def _array(value: object, location: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise SessionManifestError(f"{location}: expected an array")
    return value


def _string(value: object, location: str) -> str:
    if not isinstance(value, str):
        raise SessionManifestError(f"{location}: expected a string")
    return value


def _optional_string(value: object, location: str) -> str | None:
    if value is None:
        return None
    return _string(value, location)


def _boolean(value: object, location: str) -> bool:
    if not isinstance(value, bool):
        raise SessionManifestError(f"{location}: expected a boolean")
    return value


def _optional_text(value: object) -> str | None:
    return str(value) if value else None
