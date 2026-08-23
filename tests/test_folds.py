from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ktt.folds import read_folded_tab_ids, write_folded_tab_ids


class FoldStateTests(unittest.TestCase):
    def test_round_trips_sorted_owner_only_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "visible.folds"
            with patch("ktt.folds.fold_state_path", return_value=path):
                self.assertTrue(write_folded_tab_ids(1, {30, 10, 30}))
                self.assertEqual(path.read_text(), "10,30\n")
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(read_folded_tab_ids(1), {10, 30})

    def test_empty_state_clears_previous_folds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "visible.folds"
            with patch("ktt.folds.fold_state_path", return_value=path):
                write_folded_tab_ids(1, {10})
                write_folded_tab_ids(1, set())
                self.assertEqual(read_folded_tab_ids(1), set())
                self.assertEqual(path.read_text(), "\n")

    def test_malformed_state_fails_open_as_unfolded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "visible.folds"
            path.write_text("10,broken,30\n")
            with patch("ktt.folds.fold_state_path", return_value=path):
                self.assertEqual(read_folded_tab_ids(1), set())


if __name__ == "__main__":
    unittest.main()
