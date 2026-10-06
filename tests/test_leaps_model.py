import unittest
from datetime import date

from stocktool.leaps import LeapsPosition


def make_position() -> LeapsPosition:
    return LeapsPosition(
        id="model001", ticker="TEST", option_type="CALL", strike=100.0,
        expiration="2028-01-01", premium=10.0,
    )


class RecordIvReadingTests(unittest.TestCase):
    def test_first_reading_appends_and_returns_true(self):
        position = make_position()
        appended = position.record_iv_reading(30.0, date(2026, 1, 1), "yahoo")

        self.assertTrue(appended)
        self.assertEqual(len(position.iv_history), 1)
        self.assertEqual(position.iv_history[0].iv, 30.0)
        self.assertEqual(position.iv_history[0].date, "2026-01-01")

    def test_same_day_second_call_is_deduped(self):
        # Review Focus #3 support: repeated same-day calls must not flood the history.
        position = make_position()
        position.record_iv_reading(30.0, date(2026, 1, 1), "yahoo")
        appended_again = position.record_iv_reading(31.0, date(2026, 1, 1), "yahoo")

        self.assertFalse(appended_again)
        self.assertEqual(len(position.iv_history), 1)
        self.assertEqual(position.iv_history[0].iv, 30.0)  # first reading wins, not overwritten

    def test_next_day_appends_a_second_reading(self):
        position = make_position()
        position.record_iv_reading(30.0, date(2026, 1, 1), "yahoo")
        appended = position.record_iv_reading(31.0, date(2026, 1, 2), "manual")

        self.assertTrue(appended)
        self.assertEqual(len(position.iv_history), 2)
        self.assertEqual(position.iv_history[1].source, "manual")


class ShouldCaptureIvReadingTests(unittest.TestCase):
    """Review Focus #3: the leaps_show capture guard must not fire for CLOSED positions or
    when no market IV was fetched this run."""

    def test_active_with_market_iv_captures(self):
        from stocktool.cli import _should_capture_iv_reading

        self.assertTrue(_should_capture_iv_reading("ACTIVE", 30.0))

    def test_closed_position_never_captures(self):
        from stocktool.cli import _should_capture_iv_reading

        self.assertFalse(_should_capture_iv_reading("CLOSED", 30.0))

    def test_no_market_iv_never_captures(self):
        from stocktool.cli import _should_capture_iv_reading

        self.assertFalse(_should_capture_iv_reading("ACTIVE", None))


if __name__ == "__main__":
    unittest.main()
