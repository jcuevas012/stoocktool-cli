import unittest
from datetime import date, timedelta

from stocktool.analysis import build_leaps_scenario, leaps_iv_rank
from stocktool.leaps import IvReading, LeapsPosition


def readings(*values: float) -> list[IvReading]:
    return [IvReading(date=f"2026-01-{i+1:02d}", iv=v, source="yahoo") for i, v in enumerate(values)]


class LeapsIvRankTests(unittest.TestCase):
    def test_below_minimum_readings_returns_none(self):
        # Review Focus #2: 4 readings must be None, 5 must compute — exact boundary.
        self.assertIsNone(leaps_iv_rank(40.0, readings(30, 32, 34, 36)))

    def test_exactly_minimum_readings_computes_a_rank(self):
        result = leaps_iv_rank(40.0, readings(20, 25, 30, 35, 40))

        self.assertIsNotNone(result)
        self.assertEqual(result.reading_count, 5)
        self.assertEqual(result.range_low, 20.0)
        self.assertEqual(result.range_high, 40.0)
        self.assertAlmostEqual(result.rank_pct, 100.0)

    def test_flat_history_ranks_at_fifty(self):
        result = leaps_iv_rank(30.0, readings(30, 30, 30, 30, 30))

        self.assertAlmostEqual(result.rank_pct, 50.0)

    def test_label_and_color_boundaries(self):
        cases = [
            (29.9, "CHEAP", "green"),
            (30.0, "CHEAP", "green"),
            (30.1, "NORMAL", "yellow"),
            (60.0, "NORMAL", "yellow"),
            (60.1, "ELEVATED", "orange3"),
            (80.0, "ELEVATED", "orange3"),
            (80.1, "EXPENSIVE", "red"),
        ]
        history = readings(0, 100, 50, 10, 90)  # range 0-100 so current_iv == rank_pct directly
        for current_iv, expected_label, expected_color in cases:
            with self.subTest(current_iv=current_iv):
                result = leaps_iv_rank(current_iv, history)
                self.assertEqual(result.label, expected_label)
                self.assertEqual(result.color, expected_color)

    def test_none_current_iv_returns_none(self):
        self.assertIsNone(leaps_iv_rank(None, readings(20, 25, 30, 35, 40)))


class ScenarioIvWarningTests(unittest.TestCase):
    """build_leaps_scenario's warning text must not claim IV history isn't tracked — it is,
    via LeapsPosition.record_iv_reading and analysis.leaps_iv_rank."""

    def test_entry_iv_warning_does_not_claim_no_iv_history_tracking(self):
        position = LeapsPosition(
            id="scn001", ticker="TEST", option_type="CALL", strike=100.0,
            expiration=(date.today() + timedelta(days=365)).isoformat(), premium=10.0,
            entry_stock_price=100.0, entry_iv=30.0,
        )
        scenario = build_leaps_scenario(position, current_price=100.0)

        joined = " ".join(scenario.warnings)
        self.assertNotIn("doesn't track IV history", joined)
        self.assertIn("leaps show", joined)


if __name__ == "__main__":
    unittest.main()
