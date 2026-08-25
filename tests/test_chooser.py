import subprocess
import unittest
from unittest.mock import patch

from ktt.chooser import choose_parent_tab, parent_candidates
from ktt.model import TabRecord


class ParentCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.records = [
            TabRecord(1, 1, "root", (10,)),
            TabRecord(2, 1, "child", (20,), parent_window_id=10),
            TabRecord(3, 1, "grandchild", (30,), parent_window_id=20),
            TabRecord(4, 1, "other", (40,)),
        ]

    def test_excludes_selected_tab_and_its_descendants(self) -> None:
        self.assertEqual(
            [record.id for record in parent_candidates(self.records, 2)],
            [1, 4],
        )

    @patch("ktt.chooser.subprocess.run")
    @patch("ktt.chooser.shutil.which", return_value="/usr/bin/rofi")
    def test_rofi_index_selects_matching_tab(self, _which, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, "1\n", "")

        selected = choose_parent_tab(self.records, 2)

        self.assertEqual(selected.id, 4)
        self.assertIn("root  [tab 1]", run.call_args.kwargs["input"])
        self.assertIn("other  [tab 4]", run.call_args.kwargs["input"])

    @patch("ktt.chooser.subprocess.run")
    @patch("ktt.chooser.shutil.which", return_value="/usr/bin/rofi")
    def test_cancelling_rofi_keeps_parent_unchanged(self, _which, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 1, "", "")
        self.assertIsNone(choose_parent_tab(self.records, 2))

    @patch("ktt.chooser.shutil.which", return_value=None)
    def test_missing_rofi_has_actionable_error(self, _which) -> None:
        with self.assertRaisesRegex(RuntimeError, "rofi is required"):
            choose_parent_tab(self.records, 2)


if __name__ == "__main__":
    unittest.main()
