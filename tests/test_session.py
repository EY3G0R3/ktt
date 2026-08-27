from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ktt.cli import _parser
from ktt.model import PARENT_VAR, SIDEBAR_VAR
from ktt.session import (
    AgentState,
    SessionManifest,
    SessionManifestError,
    SessionOsWindow,
    SessionTab,
    capture_session,
    execute_restore,
    plan_restore,
    read_manifest,
    write_manifest,
)
from ktt.session_cli import restore_saved_session


class FakeRemote:
    def __init__(self, ids: list[int]):
        self.ids = iter(ids)
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.focused: list[int] = []

    def run(self, subcommand: str, *arguments: str) -> str:
        self.calls.append((subcommand, arguments))
        return str(next(self.ids))

    def focus_window(self, window_id: int) -> None:
        self.focused.append(window_id)


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


def sidebar_window(window_id: int) -> dict[str, object]:
    return {
        "id": window_id,
        "title": "ktt",
        "cwd": "/tmp",
        "is_active": False,
        "is_focused": False,
        "user_vars": {SIDEBAR_VAR: "1"},
        "foreground_processes": [],
    }


class SessionTests(unittest.TestCase):
    def test_cli_exposes_save_and_dry_run_restore(self) -> None:
        save = _parser().parse_args(["save-session"])
        restore = _parser().parse_args(["restore-session", "--dry-run"])

        self.assertEqual(save.command, "save-session")
        self.assertEqual(restore.command, "restore-session")
        self.assertTrue(restore.dry_run)

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
                            sidebar_window(1901),
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
                            sidebar_window(1902),
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
        snapshot = [
            {
                "id": 91,
                "wm_name": "work",
                "is_focused": True,
                "tabs": [
                    {
                        "id": 101,
                        "title": "agent-with-fancylog",
                        "is_active": True,
                        "is_focused": True,
                        "windows": [
                            content_window(
                                1001,
                                "/work/project",
                                ["fancylog"],
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
        self.assertIn("id:7001", second)
        self.assertIn(f"{PARENT_VAR}=7001", second)
        self.assertEqual(second[-3:], ("claude", "--resume", "claude-id"))
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


if __name__ == "__main__":
    unittest.main()
