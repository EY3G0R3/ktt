import unittest

from ktt.model import (
    TabRecord,
    adjacent_tree_tab_id,
    choose_os_window,
    clean_title,
    records_for_os_window,
    tree_rows,
    with_active_tab,
    with_repository_names,
)


class ModelTests(unittest.TestCase):
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

    def test_with_active_tab_moves_active_state(self) -> None:
        records = [
            TabRecord(1, 1, "one", (10,), is_active=True),
            TabRecord(2, 1, "two", (20,)),
        ]
        updated = with_active_tab(records, 2)
        self.assertEqual([record.is_active for record in updated], [False, True])

    def test_automatic_target_excludes_sidebar_os_window(self) -> None:
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

    def test_working_title_overrides_transient_waiting_user_var(self) -> None:
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
        self.assertEqual(record.status, "🤖")

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

        self.assertEqual(records_for_os_window(os_window)[0].status, "💬")


if __name__ == "__main__":
    unittest.main()
