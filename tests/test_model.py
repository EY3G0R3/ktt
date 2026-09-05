import unittest

from ktt.model import (
    TabRecord,
    WaitingStatusDebouncer,
    adjacent_tree_tab_id,
    choose_os_window,
    clean_title,
    content_window_cwd,
    next_attention_tab_id,
    records_for_os_window,
    reordered_tree_tab_ids,
    tree_rows,
    with_active_tab,
    with_repository_names,
)


class ModelTests(unittest.TestCase):
    def test_waiting_attention_is_delayed_without_hiding_icon(self) -> None:
        debouncer = WaitingStatusDebouncer(delay=7.0)
        working = TabRecord(1, 1, "agent", (10,), status="🤖")
        waiting = TabRecord(1, 1, "agent", (10,), status="💬")

        self.assertEqual(debouncer.update([working], 0.0)[0].status, "🤖")
        pending = debouncer.update([waiting], 1.0)[0]
        self.assertEqual(pending.status, "💬")
        self.assertTrue(pending.attention_suppressed)
        self.assertEqual(debouncer.next_deadline, 8.0)
        self.assertTrue(
            debouncer.update([waiting], 7.9)[0].attention_suppressed
        )
        self.assertFalse(
            debouncer.update([waiting], 8.0)[0].attention_suppressed
        )
        self.assertIsNone(debouncer.next_deadline)

    def test_working_update_cancels_pending_waiting_edge(self) -> None:
        debouncer = WaitingStatusDebouncer(delay=7.0)
        working = TabRecord(1, 1, "agent", (10,), status="🤖")
        waiting = TabRecord(1, 1, "agent", (10,), status="💬")

        debouncer.update([working], 0.0)
        debouncer.update([waiting], 1.0)
        self.assertFalse(
            debouncer.update([working], 2.0)[0].attention_suppressed
        )
        self.assertIsNone(debouncer.next_deadline)
        self.assertTrue(
            debouncer.update([waiting], 10.0)[0].attention_suppressed
        )
        self.assertEqual(debouncer.next_deadline, 17.0)

    def test_working_title_starts_delay_when_spinner_disappears(self) -> None:
        debouncer = WaitingStatusDebouncer(delay=7.0)
        title_working = TabRecord(
            1,
            1,
            "agent",
            (10,),
            status="💬",
            attention_suppressed=True,
        )
        waiting = TabRecord(1, 1, "agent", (10,), status="💬")

        self.assertTrue(
            debouncer.update([title_working], 0.0)[0].attention_suppressed
        )
        self.assertIsNone(debouncer.next_deadline)
        self.assertTrue(
            debouncer.update([waiting], 1.0)[0].attention_suppressed
        )
        self.assertEqual(debouncer.next_deadline, 8.0)

    def test_debouncer_does_not_delay_other_attention_states(self) -> None:
        debouncer = WaitingStatusDebouncer(delay=7.0)
        working = TabRecord(1, 1, "agent", (10,), status="🤖")
        blocked = TabRecord(1, 1, "agent", (10,), status="blocked")

        debouncer.update([working], 0.0)

        self.assertEqual(debouncer.update([blocked], 1.0)[0].status, "blocked")

    def test_debouncer_forgets_closed_tabs(self) -> None:
        debouncer = WaitingStatusDebouncer(delay=7.0)
        working = TabRecord(1, 1, "agent", (10,), status="🤖")
        waiting = TabRecord(1, 1, "agent", (10,), status="💬")

        debouncer.update([working], 0.0)
        debouncer.update([], 1.0)

        self.assertEqual(debouncer.update([waiting], 2.0)[0].status, "💬")

    def test_records_read_active_window_metadata(self) -> None:
        os_window = {
            "id": 7,
            "tabs": [{
                "id": 10,
                "title": " child",
                "is_active": True,
                "windows": [
                    {"id": 101, "is_active": False, "user_vars": {}},
                    {
                        "id": 102,
                        "is_active": True,
                        "cwd": "/work/quiver__worktrees/feature",
                        "user_vars": {
                            "ktt_parent_window_id": "55",
                            "workmux_family": "ignored-legacy-value",
                            "workmux_status": "ready_to_merge",
                        },
                    },
                ],
            }],
        }
        record = records_for_os_window(os_window)[0]
        self.assertEqual(record.title, "child")
        self.assertEqual(record.window_ids, (102, 101))
        self.assertEqual(record.parent_window_id, 55)
        self.assertNotIn("family", record.__dict__)
        self.assertEqual(record.status, "ready_to_merge")
        self.assertEqual(record.cwd, "/work/quiver__worktrees/feature")

    def test_record_reads_worktree_phase_user_var(self) -> None:
        os_window = {
            "id": 7,
            "tabs": [{
                "id": 10,
                "title": "child",
                "windows": [
                    {
                        "id": 101,
                        "is_active": True,
                        "cwd": "/work/quiver__worktrees/feature",
                        "user_vars": {
                            "workmux_status": "working",
                            "workmux_phase": "in_review",
                        },
                    },
                ],
            }],
        }
        record = records_for_os_window(os_window)[0]
        self.assertEqual(record.phase, "in_review")

    def test_record_without_phase_user_var_has_no_phase(self) -> None:
        os_window = {
            "id": 7,
            "tabs": [{
                "id": 10,
                "title": "child",
                "windows": [
                    {"id": 101, "is_active": True, "user_vars": {}},
                ],
            }],
        }
        self.assertIsNone(records_for_os_window(os_window)[0].phase)

    def test_null_foreground_cmdline_falls_back_to_process_cwd(self) -> None:
        self.assertEqual(
            content_window_cwd(
                {
                    "cwd": "/stale-launch-directory",
                    "foreground_processes": [
                        {
                            "cmdline": None,
                            "cwd": "/worktree",
                        }
                    ],
                }
            ),
            "/worktree",
        )

    def test_agent_foreground_cwd_overrides_stale_launch_cwd(self) -> None:
        os_window = {
            "id": 7,
            "tabs": [{
                "id": 10,
                "title": "Hirayama git access and admin permissions",
                "is_active": True,
                "windows": [{
                    "id": 101,
                    "cwd": "/home/igor",
                    "foreground_processes": [
                        {
                            "cmdline": ["claude", "--continue"],
                            "cwd": "/home/igor/work/squawk__worktrees/push-hirayama",
                        },
                        {
                            "cmdline": ["xclip", "-selection", "primary"],
                            "cwd": "/",
                        },
                    ],
                    "user_vars": {},
                }],
            }],
        }

        record = records_for_os_window(os_window)[0]

        self.assertEqual(
            record.cwd,
            "/home/igor/work/squawk__worktrees/push-hirayama",
        )

    def test_repository_names_are_attached_by_cwd(self) -> None:
        records = [
            TabRecord(1, 1, "one", (10,), cwd="/work/quiver"),
            TabRecord(2, 1, "two", (20,), cwd="/home/igor"),
        ]
        named = with_repository_names(
            records,
            {"/work/quiver": "quiver", "/home/igor": "yadm"},
        )
        self.assertEqual([record.repository for record in named], ["quiver", "yadm"])

    def test_agent_role_owns_metadata_when_companion_is_active(self) -> None:
        os_window = {
            "id": 7,
            "tabs": [{
                "id": 10,
                "title": "agent tab",
                "is_active": True,
                "windows": [
                    {
                        "id": 101,
                        "is_active": False,
                        "user_vars": {
                            "ktt_cockpit_role": "agent",
                            "ktt_parent_window_id": "55",
                            "workmux_status": "blocked",
                        },
                    },
                    {
                        "id": 102,
                        "is_active": True,
                        "user_vars": {"ktt_cockpit_role": "shell"},
                    },
                ],
            }],
        }

        record = records_for_os_window(os_window)[0]

        self.assertEqual(record.window_ids, (101, 102))
        self.assertEqual(record.parent_window_id, 55)
        self.assertEqual(record.status, "blocked")

    def test_agent_role_refuses_stale_companion_metadata(self) -> None:
        os_window = {
            "id": 7,
            "tabs": [{
                "id": 10,
                "title": "editor",
                "is_active": True,
                "windows": [
                    {
                        "id": 101,
                        "title": "agent pane",
                        "cwd": "/work/agent",
                        "is_active": False,
                        "user_vars": {"ktt_cockpit_role": "agent"},
                    },
                    {
                        "id": 102,
                        "title": "editor",
                        "cwd": "/work/editor",
                        "is_active": True,
                        "user_vars": {
                            "ktt_parent_window_id": "999",
                            "workmux_status": "working",
                        },
                    },
                ],
            }],
        }

        record = records_for_os_window(os_window)[0]

        self.assertEqual(record.window_ids, (101, 102))
        self.assertEqual(record.title, "agent pane")
        self.assertEqual(record.cwd, "/work/agent")
        self.assertIsNone(record.parent_window_id)
        self.assertIsNone(record.status)

    def test_tree_supports_multiple_levels_and_reorders_children(self) -> None:
        records = [
            TabRecord(3, 1, "grandchild", (30,), parent_window_id=20, source_index=0),
            TabRecord(1, 1, "parent", (10,), source_index=1),
            TabRecord(2, 1, "child", (20,), parent_window_id=10, source_index=2),
            TabRecord(4, 1, "other", (40,), source_index=3),
        ]
        rows = tree_rows(records)
        self.assertEqual([row.tab.id for row in rows], [1, 2, 3, 4])
        self.assertEqual([row.depth for row in rows], [0, 1, 2, 0])

    def test_orphan_and_cycle_are_visible_as_roots(self) -> None:
        records = [
            TabRecord(1, 1, "one", (10,), parent_window_id=20),
            TabRecord(2, 1, "two", (20,), parent_window_id=10),
            TabRecord(3, 1, "orphan", (30,), parent_window_id=999),
        ]
        rows = tree_rows(records)
        self.assertEqual({row.tab.id for row in rows}, {1, 2, 3})
        self.assertTrue(all(row.depth == 0 for row in rows))
        self.assertTrue(all(row.orphaned for row in rows))

    def test_incoming_child_of_cycle_stays_attached_to_cycle_root(self) -> None:
        records = [
            TabRecord(1, 1, "one", (10,), parent_window_id=20),
            TabRecord(2, 1, "two", (20,), parent_window_id=10),
            TabRecord(3, 1, "incoming", (30,), parent_window_id=10),
        ]
        rows = tree_rows(records)
        by_id = {row.tab.id: row for row in rows}
        self.assertEqual(by_id[3].depth, 1)
        self.assertEqual(by_id[3].parent_tab_id, 1)
        self.assertFalse(by_id[3].orphaned)

    def test_collapsed_parent_hides_all_descendants(self) -> None:
        records = [
            TabRecord(1, 1, "parent", (10,)),
            TabRecord(2, 1, "child", (20,), parent_window_id=10),
            TabRecord(3, 1, "grandchild", (30,), parent_window_id=20),
            TabRecord(4, 1, "other", (40,)),
        ]
        rows = tree_rows(records, {1})
        self.assertEqual([row.tab.id for row in rows], [1, 4])
        self.assertTrue(rows[0].has_children)
        self.assertTrue(rows[0].is_collapsed)

    def test_collapsed_parent_reports_active_hidden_descendant(self) -> None:
        records = [
            TabRecord(1, 1, "parent", (10,)),
            TabRecord(2, 1, "child", (20,), is_active=True, parent_window_id=10),
        ]
        row = tree_rows(records, {1})[0]
        self.assertTrue(row.has_active_descendant)
        self.assertFalse(row.tab.is_active)

    def test_adjacent_navigation_uses_visible_tree_order(self) -> None:
        records = [
            TabRecord(3, 1, "child", (30,), is_active=True,
                      parent_window_id=10, source_index=0),
            TabRecord(1, 1, "parent", (10,), source_index=1),
            TabRecord(2, 1, "next root", (20,), source_index=2),
        ]
        rows = tree_rows(records)
        self.assertEqual([row.tab.id for row in rows], [1, 3, 2])
        self.assertEqual(adjacent_tree_tab_id(rows, 1), 2)
        self.assertEqual(adjacent_tree_tab_id(rows, -1), 1)

    def test_adjacent_navigation_respects_folded_tree_and_boundaries(self) -> None:
        records = [
            TabRecord(1, 1, "parent", (10,)),
            TabRecord(2, 1, "child", (20,), is_active=True,
                      parent_window_id=10),
            TabRecord(3, 1, "next root", (30,)),
        ]
        rows = tree_rows(records, {1})
        self.assertEqual([row.tab.id for row in rows], [1, 3])
        self.assertEqual(adjacent_tree_tab_id(rows, 1), 3)
        self.assertIsNone(adjacent_tree_tab_id(rows, -1))

    def test_attention_navigation_wraps_in_tree_order(self) -> None:
        records = [
            TabRecord(4, 1, "complete", (40,), status="✅", source_index=0),
            TabRecord(1, 1, "parent", (10,), source_index=1),
            TabRecord(
                2,
                1,
                "waiting child",
                (20,),
                is_active=True,
                parent_window_id=10,
                status="💬",
                source_index=2,
            ),
            TabRecord(
                3,
                1,
                "blocked child",
                (30,),
                parent_window_id=10,
                status="blocked",
                source_index=3,
            ),
        ]

        rows = tree_rows(records)

        self.assertEqual([row.tab.id for row in rows], [4, 1, 2, 3])
        self.assertEqual(next_attention_tab_id(rows), 3)
        self.assertEqual(
            next_attention_tab_id(tree_rows(with_active_tab(records, 3))),
            4,
        )

    def test_attention_navigation_accepts_semantic_lifecycle_statuses(self) -> None:
        for status in ("waiting", "done", "complete"):
            with self.subTest(status=status):
                rows = tree_rows([
                    TabRecord(1, 1, "active", (10,), is_active=True),
                    TabRecord(2, 1, status, (20,), status=status),
                ])
                self.assertEqual(next_attention_tab_id(rows), 2)

    def test_attention_navigation_ignores_working_and_current_tab(self) -> None:
        rows = tree_rows([
            TabRecord(
                1, 1, "active complete", (10,), is_active=True, status="✅"
            ),
            TabRecord(2, 1, "working", (20,), status="🤖"),
            TabRecord(3, 1, "idle", (30,)),
        ])

        self.assertIsNone(next_attention_tab_id(rows))

    def test_attention_navigation_accepts_debounced_eligible_tabs(self) -> None:
        rows = tree_rows([
            TabRecord(1, 1, "active", (10,), is_active=True),
            TabRecord(2, 1, "raw waiting", (20,), status="💬"),
            TabRecord(3, 1, "ready", (30,), status="ready_to_merge"),
        ])

        self.assertEqual(next_attention_tab_id(rows, {3}), 3)

    def test_attention_navigation_ignores_suppressed_waiting(self) -> None:
        rows = tree_rows([
            TabRecord(1, 1, "active", (10,), is_active=True),
            TabRecord(
                2,
                1,
                "transient waiting",
                (20,),
                status="💬",
                attention_suppressed=True,
            ),
        ])

        self.assertIsNone(next_attention_tab_id(rows))

    def test_attention_navigation_includes_folded_descendants(self) -> None:
        records = [
            TabRecord(1, 1, "parent", (10,), is_active=True),
            TabRecord(
                2,
                1,
                "ready child",
                (20,),
                parent_window_id=10,
                status="ready_to_merge",
            ),
        ]

        self.assertIsNone(next_attention_tab_id(tree_rows(records, {1})))
        self.assertEqual(next_attention_tab_id(tree_rows(records)), 2)

    def test_reorder_swaps_complete_root_subtrees(self) -> None:
        records = [
            TabRecord(1, 1, "first root", (10,), source_index=0),
            TabRecord(2, 1, "first child", (20,), parent_window_id=10, source_index=1),
            TabRecord(3, 1, "grandchild", (30,), parent_window_id=20, source_index=2),
            TabRecord(4, 1, "second root", (40,), source_index=3),
            TabRecord(5, 1, "second child", (50,), parent_window_id=40, source_index=4),
            TabRecord(6, 1, "last root", (60,), source_index=5),
        ]
        rows = tree_rows(records)

        self.assertEqual(
            reordered_tree_tab_ids(rows, 1, 1),
            (4, 5, 1, 2, 3, 6),
        )
        self.assertEqual(
            reordered_tree_tab_ids(rows, 4, -1),
            (4, 5, 1, 2, 3, 6),
        )

    def test_reorder_only_moves_among_siblings(self) -> None:
        records = [
            TabRecord(1, 1, "root", (10,), source_index=0),
            TabRecord(2, 1, "first child", (20,), parent_window_id=10, source_index=1),
            TabRecord(3, 1, "second child", (30,), parent_window_id=10, source_index=2),
            TabRecord(4, 1, "other root", (40,), source_index=3),
        ]
        rows = tree_rows(records)

        self.assertEqual(
            reordered_tree_tab_ids(rows, 2, 1),
            (1, 3, 2, 4),
        )
        self.assertIsNone(reordered_tree_tab_ids(rows, 3, 1))
        self.assertIsNone(reordered_tree_tab_ids(rows, 2, -1))

    def test_with_active_tab_moves_active_state(self) -> None:
        records = [
            TabRecord(1, 1, "one", (10,), is_active=True),
            TabRecord(2, 1, "two", (20,)),
        ]
        updated = with_active_tab(records, 2)
        self.assertEqual([record.is_active for record in updated], [False, True])

    def test_automatic_target_excludes_the_calling_os_window(self) -> None:
        snapshot = [
            {"id": 1, "tabs": [{"windows": [{"id": 10}]}]},
            {"id": 2, "tabs": [
                {"windows": [{"id": 20}]},
                {"windows": [{"id": 21}]},
            ]},
        ]
        self.assertEqual(choose_os_window(snapshot, self_window_id=10)["id"], 2)

    def test_clean_title_removes_existing_decorations(self) -> None:
        self.assertEqual(clean_title("⠋  feature-name"), "feature-name")

    def test_clean_title_uses_tilde_for_home_directory_name(self) -> None:
        self.assertEqual(
            clean_title(
                "igorg",
                cwd="/home/igorg",
                home="/home/igorg",
            ),
            "~",
        )
        self.assertEqual(
            clean_title(
                "igorg",
                cwd="/work/igorg",
                home="/home/igorg",
            ),
            "igorg",
        )

    def test_working_title_suppresses_attention_without_hiding_waiting(self) -> None:
        os_window = {
            "id": 7,
            "tabs": [{
                "id": 10,
                "title": "⠋ ktt",
                "windows": [{
                    "id": 101,
                    "is_active": True,
                    "user_vars": {"workmux_status": "💬"},
                }],
            }],
        }

        record = records_for_os_window(os_window)[0]

        self.assertEqual(record.title, "ktt")
        self.assertEqual(record.status, "💬")
        self.assertTrue(record.attention_suppressed)

    def test_waiting_remains_when_title_has_no_working_spinner(self) -> None:
        os_window = {
            "id": 7,
            "tabs": [{
                "id": 10,
                "title": "ktt",
                "windows": [{
                    "id": 101,
                    "is_active": True,
                    "user_vars": {"workmux_status": "💬"},
                }],
            }],
        }

        record = records_for_os_window(os_window)[0]
        self.assertEqual(record.status, "💬")
        self.assertFalse(record.attention_suppressed)


if __name__ == "__main__":
    unittest.main()
