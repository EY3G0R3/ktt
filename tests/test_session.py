from __future__ import annotations

import json
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest import mock

from ktt.cli import _parser, main
from ktt.model import PARENT_VAR
from ktt.session import (
    AgentState,
    SessionManifest,
    SessionManifestError,
    SessionOsWindow,
    SessionTab,
    capture_session,
    execute_restore,
    generated_session_path,
    named_autosave_path,
    plan_restore,
    recovery_restore_path,
    named_session_path,
    read_manifest,
    write_manifest,
)
from ktt.session_cli import (
    latest_saved_session_path,
    list_saved_sessions,
    restore_saved_session,
    show_saved_session,
)


class FakeRemote:
    def __init__(self, ids: list[int]):
        self.ids = iter(ids)
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.focused: list[int] = []
        self.closed: list[int] = []
        self.native_enabled: list[int] = []

    def run(self, subcommand: str, *arguments: str) -> str:
        self.calls.append((subcommand, arguments))
        return str(next(self.ids))

    def focus_window(self, window_id: int) -> None:
        self.focused.append(window_id)

    def close_window(self, window_id: int) -> None:
        self.closed.append(window_id)

    def enable_native_vertical_tabs(self, window_id: int) -> None:
        self.native_enabled.append(window_id)


def content_window(
    window_id: int,
    cwd: str,
    command: list[str],
    *,
    parent: int | None = None,
    focused: bool = False,
) -> dict[str, object]:
    user_vars = {} if parent is None else {PARENT_VAR: str(parent)}
    return {
        "id": window_id,
        "title": command[0],
        "cwd": cwd,
        "is_active": focused,
        "is_focused": focused,
        "user_vars": user_vars,
        "foreground_processes": [
            {"pid": window_id + 10_000, "cwd": cwd, "cmdline": command}
        ],
    }


class SessionTests(unittest.TestCase):
    def test_session_group_parses_save_restore_list_and_show(self) -> None:
        save = _parser().parse_args(["session", "save", "before-upgrade"])
        restore = _parser().parse_args(["session", "restore", "before-upgrade"])
        listing = _parser().parse_args(["session", "list"])
        show_latest = _parser().parse_args(["session", "show"])
        show_named = _parser().parse_args(["session", "show", "before-upgrade"])

        self.assertEqual((save.session_command, save.name), ("save", "before-upgrade"))
        self.assertEqual(
            (restore.session_command, restore.name), ("restore", "before-upgrade")
        )
        self.assertEqual(listing.session_command, "list")
        self.assertEqual((show_latest.session_command, show_latest.name), ("show", None))
        self.assertEqual(
            (show_named.session_command, show_named.name),
            ("show", "before-upgrade"),
        )

    def test_named_session_paths_reject_traversal_and_reserved_latest(self) -> None:
        with self.assertRaises(ValueError):
            named_session_path("../outside")
        with self.assertRaises(ValueError):
            named_session_path("latest")
        with self.assertRaises(ValueError):
            named_session_path("autosave")
        with self.assertRaises(ValueError):
            named_autosave_path("autosave-../../outside")

    def test_generated_session_path_uses_timestamp_and_collision_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.dict(os.environ, {"XDG_STATE_HOME": temporary}):
                now = datetime(2026, 9, 10, 19, 23, 53)
                first = generated_session_path(now)
                self.assertEqual(first.name, "2026-09-10-192353.json")
                first.parent.mkdir(parents=True)
                first.touch()
                self.assertEqual(
                    generated_session_path(now).name,
                    "2026-09-10-192353-2.json",
                )

    def test_unnamed_save_creates_a_generated_session(self) -> None:
        generated = Path("/tmp/2026-09-10-192353.json")
        with (
            mock.patch("ktt.cli.RemoteControl"),
            mock.patch("ktt.cli.generated_session_path", return_value=generated),
            mock.patch("ktt.cli.save_current_session", return_value=0) as save,
        ):
            self.assertEqual(main(["session", "save"]), 0)

        save.assert_called_once()
        self.assertEqual(save.call_args.args[1], generated)
        self.assertEqual(save.call_args.kwargs["name"], "2026-09-10-192353")

    def test_list_aligns_sessions_and_latest_selects_newest(self) -> None:
        def manifest(created_at: str) -> SessionManifest:
            return SessionManifest(
                created_at=created_at,
                hostname="host",
                os_windows=(
                    SessionOsWindow(
                        "os-1",
                        "main",
                        (
                            SessionTab(
                                "tab-1",
                                "shell",
                                "/tmp",
                                None,
                                True,
                                True,
                                AgentState("shell", "zsh"),
                            ),
                        ),
                    ),
                ),
            )

        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.dict(os.environ, {"XDG_STATE_HOME": temporary}):
                autosave = Path(temporary) / "ktt" / "recovery.json"
                manual = named_session_path("newer")
                write_manifest(autosave, manifest("2026-09-10T12:00:00-07:00"))
                write_manifest(manual, manifest("2026-09-10T13:00:00-07:00"))
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(list_saved_sessions(), 0)

                self.assertEqual(latest_saved_session_path(), manual)
                lines = output.getvalue().splitlines()
                self.assertNotIn("\t", output.getvalue())
                self.assertEqual(lines[0].split(), ["NAME", "TYPE", "SAVED", "TABS"])
                self.assertEqual(lines[1].split()[:2], ["newer", "manual"])
                self.assertEqual(lines[2].split()[:2], ["autosave", "automatic"])

                detail = io.StringIO()
                with redirect_stdout(detail):
                    self.assertEqual(show_saved_session(manual), 0)
                shown = detail.getvalue()
                self.assertTrue(shown.startswith("newer\n"))
                self.assertIn("1 tab in 1 window", shown)
                self.assertIn("Window 1: main", shown)
                self.assertIn("╭─ Tab 1  shell", shown)
                self.assertIn("│  Cwd     /tmp", shown)
                self.assertIn("│  Agent   zsh (shell)", shown)
                self.assertIn("│  Launch  <default shell>", shown)
                self.assertIn("·  restorable  ·  tab-1", shown)
                self.assertNotIn("\x1b[", shown)

                colored = io.StringIO()
                with (
                    redirect_stdout(colored),
                    mock.patch("ktt.session_cli._color_enabled", return_value=True),
                ):
                    self.assertEqual(show_saved_session(manual), 0)
                self.assertIn("\x1b[", colored.getvalue())

    def test_recovery_restore_prefers_the_previous_process_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state_home = Path(temporary)
            current = state_home / "ktt" / "recovery.json"
            previous = state_home / "ktt" / "recovery.previous.json"
            current.parent.mkdir()
            current.touch()
            with mock.patch.dict(os.environ, {"XDG_STATE_HOME": temporary}):
                self.assertEqual(recovery_restore_path(), current)
                previous.touch()
                self.assertEqual(recovery_restore_path(), previous)

    def test_capture_replaces_runtime_ids_with_logical_relationships(self) -> None:
        snapshot = [
            {
                "id": 91,
                "wm_name": "work",
                "tabs": [
                    {
                        "id": 101,
                        "title": "root",
                        "is_active": True,
                        "windows": [
                            content_window(1001, "/work/root", ["codex"], focused=True),
                        ],
                    },
                    {
                        "id": 102,
                        "title": "child",
                        "is_active": False,
                        "windows": [
                            content_window(
                                1002,
                                "/work/child",
                                ["claude"],
                                parent=1001,
                            ),
                        ],
                    },
                ],
            }
        ]

        def resolve(kind: str, pid: int, cwd: str | None, argv: object) -> str:
            del pid, cwd, argv
            return f"{kind}-session"

        manifest = capture_session(
            snapshot,
            hostname="host",
            created_at="2026-08-27T12:00:00-07:00",
            session_resolver=resolve,
        )

        self.assertEqual(manifest.tab_count, 2)
        root, child = manifest.os_windows[0].tabs
        self.assertEqual(root.logical_id, "tab-1-1")
        self.assertIsNone(root.parent)
        self.assertEqual(root.agent.session_id, "codex-session")
        self.assertEqual(child.parent, root.logical_id)
        self.assertEqual(child.agent.session_id, "claude-session")
        serialized = json.dumps(manifest.as_dict())
        self.assertNotIn("1001", serialized)
        self.assertNotIn("1002", serialized)
        self.assertNotIn("1901", serialized)

    def test_capture_uses_tab_focus_instead_of_each_tabs_focused_pane(self) -> None:
        snapshot = [
            {
                "id": 91,
                "wm_name": "work",
                "is_focused": True,
                "tabs": [
                    {
                        "id": 101,
                        "title": "inactive",
                        "is_active": False,
                        "is_focused": False,
                        "windows": [
                            content_window(
                                1001,
                                "/work/one",
                                ["zsh"],
                                focused=True,
                            )
                        ],
                    },
                    {
                        "id": 102,
                        "title": "focused",
                        "is_active": True,
                        "is_focused": True,
                        "windows": [
                            content_window(
                                1002,
                                "/work/two",
                                ["zsh"],
                                focused=True,
                            )
                        ],
                    },
                ],
            }
        ]

        manifest = capture_session(
            snapshot,
            hostname="host",
            created_at="2026-08-27T12:00:00-07:00",
        )

        inactive, focused = manifest.os_windows[0].tabs
        self.assertFalse(inactive.active)
        self.assertFalse(inactive.focused)
        self.assertTrue(focused.active)
        self.assertTrue(focused.focused)

    def test_capture_prefers_a_resumable_agent_over_the_focused_utility_pane(
        self,
    ) -> None:
        for utility in ("fancylog", "zsh"):
            with self.subTest(utility=utility):
                snapshot = [
                    {
                        "id": 91,
                        "wm_name": "work",
                        "is_focused": True,
                        "tabs": [
                            {
                                "id": 101,
                                "title": f"agent-with-{utility}",
                                "is_active": True,
                                "is_focused": True,
                                "windows": [
                                    content_window(
                                        1001,
                                        "/work/project",
                                        [utility],
                                        focused=True,
                                    ),
                                    content_window(
                                        1002,
                                        "/work/project",
                                        ["codex"],
                                    ),
                                ],
                            }
                        ],
                    }
                ]

                manifest = capture_session(
                    snapshot,
                    hostname="host",
                    created_at="2026-08-27T12:00:00-07:00",
                    session_resolver=lambda kind, pid, cwd, argv: "codex-session",
                )

                tab = manifest.os_windows[0].tabs[0]
                self.assertEqual(tab.agent.kind, "codex")
                self.assertEqual(tab.agent.session_id, "codex-session")
                self.assertEqual(tab.cwd, "/work/project")
                self.assertEqual(
                    manifest.warnings,
                    (
                        "tab-1-1: 2 content panes; restore will use "
                        "the resumable codex pane",
                    ),
                )

    def test_restore_remaps_relationships_to_new_kitty_ids(self) -> None:
        manifest = SessionManifest(
            created_at="2026-08-27T12:00:00-07:00",
            hostname="host",
            os_windows=(
                SessionOsWindow(
                    logical_id="os-1",
                    title="work",
                    tabs=(
                        SessionTab(
                            "root",
                            "Codex",
                            "/work/root",
                            None,
                            False,
                            False,
                            AgentState("codex", "codex", "codex-id"),
                        ),
                        SessionTab(
                            "child",
                            "Claude",
                            "/work/child",
                            "root",
                            True,
                            True,
                            AgentState("claude", "claude", "claude-id"),
                        ),
                    ),
                ),
            ),
        )
        operations = plan_restore(manifest)
        remote = FakeRemote([7001, 7002])

        mapping = execute_restore(remote, operations)  # type: ignore[arg-type]

        self.assertEqual(mapping, {"root": 7001, "child": 7002})
        first = remote.calls[0][1]
        second = remote.calls[1][1]
        self.assertIn("--type=os-window", first)
        self.assertIn("--os-window-title", first)
        self.assertEqual(first[-3:], ("codex", "resume", "codex-id"))
        self.assertIn("--type=tab", second)
        self.assertIn("--match", second)
        self.assertIn("window_id:7001", second)
        self.assertIn("id:7001", second)
        self.assertIn(f"{PARENT_VAR}=7001", second)
        self.assertEqual(second[-3:], ("claude", "--resume", "claude-id"))
        self.assertIn("--hold", second)
        self.assertEqual(remote.focused, [7002])

    def test_tmux_reattaches_only_while_the_session_survives(self) -> None:
        manifest = SessionManifest(
            created_at="2026-08-27T12:00:00-07:00",
            hostname="host",
            os_windows=(
                SessionOsWindow(
                    "os-1",
                    "work",
                    (
                        SessionTab(
                            "tmux",
                            "Hirayama",
                            "/work",
                            None,
                            True,
                            True,
                            AgentState("tmux", "hirayama", "hirayama"),
                        ),
                    ),
                ),
            ),
        )

        alive = plan_restore(manifest, tmux_checker=lambda name: name == "hirayama")
        missing = plan_restore(manifest, tmux_checker=lambda name: False)

        self.assertEqual(
            alive[0].command,
            ("tmux", "attach-session", "-t", "hirayama"),
        )
        self.assertEqual(missing[0].command, ())
        self.assertIn("not running", missing[0].placeholder_reason or "")

    def test_parent_is_created_before_a_child_even_if_manifest_order_is_reversed(
        self,
    ) -> None:
        root = SessionTab(
            "root", "root", "/root", None, False, False, AgentState("shell", "zsh")
        )
        child = SessionTab(
            "child", "child", "/child", "root", True, True, AgentState("shell", "zsh")
        )
        manifest = SessionManifest(
            "2026-08-27T12:00:00-07:00",
            "host",
            (SessionOsWindow("os-1", "", (child, root)),),
        )

        operations = plan_restore(manifest)

        self.assertEqual(
            [operation.logical_id for operation in operations], ["root", "child"]
        )

    def test_manifest_rejects_cycles_and_cross_window_parents(self) -> None:
        value = {
            "version": 1,
            "created_at": "2026-08-27T12:00:00-07:00",
            "hostname": "host",
            "warnings": [],
            "os_windows": [
                {
                    "id": "os-1",
                    "title": "",
                    "tabs": [
                        {
                            "id": "a",
                            "title": "a",
                            "parent": "b",
                            "active": True,
                            "focused": True,
                            "agent": {
                                "kind": "shell",
                                "identity": "zsh",
                                "restorable": True,
                            },
                        },
                        {
                            "id": "b",
                            "title": "b",
                            "parent": "a",
                            "active": False,
                            "focused": False,
                            "agent": {
                                "kind": "shell",
                                "identity": "zsh",
                                "restorable": True,
                            },
                        },
                    ],
                }
            ],
        }

        with self.assertRaisesRegex(SessionManifestError, "cycle"):
            SessionManifest.from_dict(value)

    def test_manifest_write_is_private_and_round_trips(self) -> None:
        manifest = SessionManifest(
            "2026-08-27T12:00:00-07:00",
            "host",
            (
                SessionOsWindow(
                    "os-1",
                    "",
                    (
                        SessionTab(
                            "tab-1",
                            "shell",
                            "/work",
                            None,
                            True,
                            True,
                            AgentState("shell", "zsh"),
                        ),
                    ),
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "session.json"

            write_manifest(path, manifest)

            self.assertEqual(read_manifest(path), manifest)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_dry_run_restore_never_calls_kitty(self) -> None:
        manifest = SessionManifest(
            "2026-08-27T12:00:00-07:00",
            "host",
            (
                SessionOsWindow(
                    "os-1",
                    "",
                    (
                        SessionTab(
                            "tab-1",
                            "shell",
                            "/work",
                            None,
                            True,
                            True,
                            AgentState("shell", "zsh"),
                        ),
                    ),
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "session.json"
            write_manifest(path, manifest)
            remote = mock.Mock()

            result = restore_saved_session(remote, path, dry_run=True)

            self.assertEqual(result, 0)
            remote.run.assert_not_called()
            remote.focus_window.assert_not_called()

    def test_restore_enables_native_tabs(self) -> None:
        manifest = SessionManifest(
            "2026-08-27T12:00:00-07:00",
            "host",
            (
                SessionOsWindow(
                    "os-1",
                    "work",
                    (
                        SessionTab(
                            "tab-1",
                            "shell",
                            "/work",
                            None,
                            True,
                            True,
                            AgentState("shell", "zsh"),
                        ),
                    ),
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "session.json"
            write_manifest(path, manifest)
            remote = FakeRemote([7001])
            result = restore_saved_session(remote, path, dry_run=False)

        self.assertEqual(result, 0)
        self.assertEqual(remote.native_enabled, [7001])

    def test_restore_replaces_invoking_tab_instead_of_creating_an_os_window(
        self,
    ) -> None:
        manifest = SessionManifest(
            "2026-08-27T12:00:00-07:00",
            "host",
            (
                SessionOsWindow(
                    "os-1",
                    "work",
                    (
                        SessionTab(
                            "tab-1",
                            "shell",
                            "/work",
                            None,
                            True,
                            True,
                            AgentState("shell", "zsh"),
                        ),
                    ),
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "session.json"
            write_manifest(path, manifest)
            remote = FakeRemote([7001])
            result = restore_saved_session(
                remote,
                path,
                dry_run=False,
                current_window_id=55,
            )

        self.assertEqual(result, 0)
        launch = remote.calls[0]
        self.assertEqual(launch[0], "launch")
        self.assertIn("--type=tab", launch[1])
        self.assertIn("window_id:55", launch[1])
        self.assertIn("id:55", launch[1])
        self.assertNotIn("--type=os-window", launch[1])
        self.assertEqual(remote.closed, [55])
        self.assertEqual(remote.native_enabled, [7001])


if __name__ == "__main__":
    unittest.main()
