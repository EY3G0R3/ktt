from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ktt.model import TabRecord, TreeRow
from ktt.order import VisibleOrderPublisher, read_visible_order


class VisibleOrderTests(unittest.TestCase):
    def test_publishes_tree_order_with_folded_active_ancestor_as_anchor(self) -> None:
        rows = [
            TreeRow(
                TabRecord(10, 1, "parent", (100,)),
                0,
                None,
                has_children=True,
                is_collapsed=True,
                has_active_descendant=True,
            ),
            TreeRow(TabRecord(30, 1, "next", (300,)), 0, None),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "visible.order"
            with patch("ktt.order.order_path", return_value=path):
                publisher = VisibleOrderPublisher()
                publisher.publish(1, rows)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(read_visible_order(1).anchor_tab_id, 10)
                self.assertEqual(read_visible_order(1).tab_ids, (10, 30))
                publisher.close()
                self.assertFalse(path.exists())

    def test_old_publisher_does_not_remove_newer_snapshot(self) -> None:
        first_rows = [TreeRow(
            TabRecord(10, 1, "first", (100,), is_active=True), 0, None
        )]
        second_rows = [TreeRow(
            TabRecord(20, 1, "second", (200,), is_active=True), 0, None
        )]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "visible.order"
            with patch("ktt.order.order_path", return_value=path):
                first = VisibleOrderPublisher()
                second = VisibleOrderPublisher()
                first.publish(1, first_rows)
                second.publish(1, second_rows)
                first.close()
                self.assertEqual(read_visible_order(1).tab_ids, (20,))
                second.close()


if __name__ == "__main__":
    unittest.main()
