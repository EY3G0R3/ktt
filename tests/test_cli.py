import unittest

from ktt.cli import _parser, _validate_link


def window(window_id, parent=None):
    user_vars = {}
    if parent is not None:
        user_vars["ktt_parent_window_id"] = str(parent)
    return {"id": window_id, "is_active": True, "user_vars": user_vars}


class LinkValidationTests(unittest.TestCase):
    def test_default_recovery_poll_is_one_second(self) -> None:
        self.assertEqual(_parser().parse_args([]).poll_interval, 1.0)

    def test_rejects_a_new_cycle(self) -> None:
        snapshot = [{
            "id": 1,
            "tabs": [
                {"id": 10, "title": "root", "windows": [window(100)]},
                {"id": 20, "title": "child", "windows": [window(200, 100)]},
                {"id": 30, "title": "grandchild", "windows": [window(300, 200)]},
            ],
        }]
        with self.assertRaisesRegex(ValueError, "cycle"):
            _validate_link(snapshot, 100, 300)

    def test_accepts_a_normal_link(self) -> None:
        snapshot = [{
            "id": 1,
            "tabs": [
                {"id": 10, "title": "root", "windows": [window(100)]},
                {"id": 20, "title": "child", "windows": [window(200)]},
            ],
        }]
        _validate_link(snapshot, 200, 100)


if __name__ == "__main__":
    unittest.main()
