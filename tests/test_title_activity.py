import unittest

from ktt.model import TabRecord, WORKING_STATUS
from ktt.title_activity import TitleActivity


def record(tab_id=10, window_ids=(101,), **fields):
    return TabRecord(
        id=tab_id,
        os_window_id=7,
        title="ktt",
        window_ids=window_ids,
        **fields,
    )


class TitleActivityTests(unittest.TestCase):
    def test_reported_spinner_title_supplies_missing_status(self) -> None:
        activity = TitleActivity()
        activity.record(101, "⠋ ktt cards", 0.0)

        card = activity.apply([record()], 0.05)[0]

        self.assertEqual(card.status, WORKING_STATUS)

    def test_frozen_title_stops_counting_as_work(self) -> None:
        activity = TitleActivity(grace=1.5)
        activity.record(101, "⠋ ktt cards", 0.0)

        working = activity.apply([record()], 1.0)[0]
        stopped = activity.apply([record()], 1.6)[0]

        self.assertEqual(working.status, WORKING_STATUS)
        self.assertIsNone(stopped.status)
        self.assertIsNone(activity.next_deadline)

    def test_title_without_a_spinner_ends_activity_immediately(self) -> None:
        activity = TitleActivity()
        activity.record(101, "⠋ ktt cards", 0.0)
        activity.record(101, "ktt cards", 0.1)

        card = activity.apply([record()], 0.2)[0]

        self.assertIsNone(card.status)

    def test_titles_from_other_panes_do_not_claim_work(self) -> None:
        activity = TitleActivity()
        activity.record(999, "⠋ unrelated pane", 0.0)

        card = activity.apply([record()], 0.05)[0]

        self.assertIsNone(card.status)

    def test_published_status_survives_title_activity(self) -> None:
        activity = TitleActivity()
        activity.record(101, "✳ review", 0.0)

        card = activity.apply([record(status="💬")], 0.05)[0]

        self.assertEqual(card.status, "💬")
        self.assertTrue(card.attention_suppressed)

    def test_waiting_attention_returns_once_the_title_settles(self) -> None:
        activity = TitleActivity(grace=1.5)
        activity.record(101, "✳ review", 0.0)

        settled = activity.apply([record(status="💬")], 2.0)[0]

        self.assertFalse(settled.attention_suppressed)

    def test_animated_cards_request_their_next_frame(self) -> None:
        activity = TitleActivity(grace=1.5, frame_interval=0.12)
        activity.record(101, "⠋ ktt cards", 0.0)

        activity.apply([record()], 0.0)

        self.assertEqual(activity.next_deadline, 0.12)

    def test_closed_windows_are_forgotten(self) -> None:
        activity = TitleActivity()
        activity.record(101, "⠋ ktt cards", 0.0)
        activity.forget(101)

        card = activity.apply([record()], 0.05)[0]

        self.assertIsNone(card.status)


if __name__ == "__main__":
    unittest.main()
