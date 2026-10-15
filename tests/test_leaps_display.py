import unittest

from stocktool.analysis import LeapsSnapshot
from stocktool.display import _leaps_iv_rank_line


def make_snapshot(status="ACTIVE", iv_rank_label=None, iv_rank_reading_count=0, **overrides) -> LeapsSnapshot:
    fields = dict(
        id="x", ticker="T", option_type="CALL", strike=100.0, expiration="2028-01-01",
        premium=10.0, contracts=1, entry_stock_price=100.0, entry_delta=0.8,
        entry_theta=-1.0, entry_iv=30.0, status=status,
        iv_rank_label=iv_rank_label, iv_rank_reading_count=iv_rank_reading_count,
    )
    fields.update(overrides)
    return LeapsSnapshot(**fields)


class LeapsIvRankLineTests(unittest.TestCase):
    """Review finding (Important #2): the None-label branch must distinguish closed
    positions, zero readings, below-minimum readings, and sufficient-readings-but-no-IV —
    not collapse them all into one self-contradictory 'not enough history' message."""

    def test_closed_position_says_not_computed_even_with_plenty_of_history(self):
        snapshot = make_snapshot(status="CLOSED", iv_rank_label=None, iv_rank_reading_count=6)

        line = _leaps_iv_rank_line(snapshot)

        self.assertIn("closed", line.lower())
        self.assertNotIn("not enough history", line)

    def test_zero_readings_says_none_tracked_yet(self):
        snapshot = make_snapshot(status="ACTIVE", iv_rank_label=None, iv_rank_reading_count=0)

        line = _leaps_iv_rank_line(snapshot)

        self.assertIn("no iv readings tracked yet", line.lower())

    def test_below_minimum_readings_says_not_enough_history_with_count(self):
        snapshot = make_snapshot(status="ACTIVE", iv_rank_label=None, iv_rank_reading_count=3)

        line = _leaps_iv_rank_line(snapshot)

        self.assertIn("not enough history", line.lower())
        self.assertIn("3", line)

    def test_sufficient_readings_but_no_iv_value_says_unavailable_not_not_enough(self):
        # Reproduces the self-contradictory case: 6 >= minimum(5) readings exist, but
        # leaps_iv_rank returned None because there was no current_iv to rank at all.
        snapshot = make_snapshot(status="ACTIVE", iv_rank_label=None, iv_rank_reading_count=6)

        line = _leaps_iv_rank_line(snapshot)

        self.assertNotIn("not enough history", line.lower())

    def test_computed_rank_still_renders_normally(self):
        snapshot = make_snapshot(
            status="ACTIVE", iv_rank_label="EXPENSIVE", iv_rank_reading_count=6,
            iv_rank_pct=100.0, iv_rank_color="red", iv_range_low=40.0, iv_range_high=47.0,
        )

        line = _leaps_iv_rank_line(snapshot)

        self.assertIn("EXPENSIVE", line)
        self.assertIn("100", line)


if __name__ == "__main__":
    unittest.main()
