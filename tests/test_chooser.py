from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from ktt.chooser import choose_parent_tab, parent_candidates
from ktt.model import TabRecord


class ParentChooserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.records = [
            TabRecord(1, 10, "root", (101,)),
            TabRecord(2, 10, "child", (102,), parent_window_id=101),
            TabRecord(3, 10, "grandchild", (103,), parent_window_id=102),
            TabRecord(4, 10, "other", (104,)),
        ]

    def test_candidates_exclude_child_and_descendants(self) -> None:
        self.assertEqual(
            [record.id for record in parent_candidates(self.records, 2)],
            [1, 4],
        )

    def test_candidates_follow_tree_order(self) -> None:
        self.assertEqual(
            [record.id for record in parent_candidates(self.records, 3)],
            [1, 2, 4],
        )

    def test_candidates_exclude_tabs_without_windows(self) -> None:
        records = self.records + [TabRecord(5, 10, "empty", ())]
        self.assertNotIn(5, [record.id for record in parent_candidates(records, 2)])

    @patch("ktt.chooser.shutil.which", return_value="/usr/bin/rofi")
    @patch("ktt.chooser.subprocess.run")
    def test_selected_index_returns_candidate(self, run, _which) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, stdout="1\n", stderr="")

        selected = choose_parent_tab(self.records, 2)

        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, 4)
        self.assertEqual(run.call_args.kwargs["input"], "root  [tab 1]\nother  [tab 4]\n")

    @patch("ktt.chooser.shutil.which", return_value="/usr/bin/rofi")
    @patch("ktt.chooser.subprocess.run")
    def test_cancel_returns_none(self, run, _which) -> None:
        run.return_value = subprocess.CompletedProcess([], 1, stdout="", stderr="")
        self.assertIsNone(choose_parent_tab(self.records, 2))

    @patch("ktt.chooser.shutil.which", return_value=None)
    def test_missing_rofi_is_explicit(self, _which) -> None:
        with self.assertRaisesRegex(RuntimeError, "rofi is required"):
            choose_parent_tab(self.records, 2)

    @patch("ktt.chooser.shutil.which", return_value="/usr/bin/rofi")
    @patch("ktt.chooser.subprocess.run")
    def test_invalid_rofi_index_is_explicit(self, run, _which) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, stdout="9\n", stderr="")
        with self.assertRaisesRegex(RuntimeError, "invalid parent selection"):
            choose_parent_tab(self.records, 2)


if __name__ == "__main__":
    unittest.main()
