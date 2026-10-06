import unittest
from datetime import date, timedelta
from unittest.mock import Mock, patch

import pandas as pd

from stocktool.analysis import build_leaps_earnings_context, leaps_earnings_move_stats
from stocktool.data import fetch_earnings_move_history, fetch_next_earnings_date
from stocktool.leaps import LeapsPosition


class FetchEarningsMoveHistoryTests(unittest.TestCase):
    def test_computes_pct_move_around_each_earnings_date(self):
        today = date.today()
        earnings_date = today - timedelta(days=100)
        earnings_df = pd.DataFrame(
            {"EPS Estimate": [1.0]}, index=pd.DatetimeIndex([pd.Timestamp(earnings_date)])
        )
        trading_days = pd.bdate_range(end=pd.Timestamp(today), periods=400)
        closes = pd.Series(100.0, index=trading_days)
        before_idx = trading_days.searchsorted(pd.Timestamp(earnings_date)) - 1
        closes.iloc[before_idx] = 100.0
        closes.iloc[before_idx + 1] = 110.0
        hist_df = pd.DataFrame({"Close": closes})

        ticker = Mock()
        ticker.get_earnings_dates.return_value = earnings_df
        ticker.history.return_value = hist_df

        with patch("stocktool.data.yf.Ticker", return_value=ticker):
            moves = fetch_earnings_move_history("TEST", quarters=8)

        self.assertEqual(len(moves), 1)
        self.assertAlmostEqual(moves[0]["pct_move"], 10.0, places=4)
        self.assertAlmostEqual(moves[0]["abs_pct_move"], 10.0, places=4)

    def test_never_raises_on_fetch_failure(self):
        # Review Focus #5.
        with patch("stocktool.data.yf.Ticker", side_effect=RuntimeError("network down")):
            moves = fetch_earnings_move_history("TEST")

        self.assertEqual(moves, [])

    def test_empty_earnings_dates_returns_empty_list(self):
        # Review Focus #5.
        ticker = Mock()
        ticker.get_earnings_dates.return_value = pd.DataFrame()
        with patch("stocktool.data.yf.Ticker", return_value=ticker):
            moves = fetch_earnings_move_history("TEST")

        self.assertEqual(moves, [])

    def test_too_short_price_history_returns_empty_list(self):
        # Review Focus #5.
        today = date.today()
        earnings_df = pd.DataFrame(
            {"EPS Estimate": [1.0]},
            index=pd.DatetimeIndex([pd.Timestamp(today - timedelta(days=5))]),
        )
        ticker = Mock()
        ticker.get_earnings_dates.return_value = earnings_df
        ticker.history.return_value = pd.DataFrame({"Close": []})
        with patch("stocktool.data.yf.Ticker", return_value=ticker):
            moves = fetch_earnings_move_history("TEST")

        self.assertEqual(moves, [])


class FetchNextEarningsDateTests(unittest.TestCase):
    def test_future_earnings_date_from_get_earnings_dates(self):
        future_date = date.today() + timedelta(days=15)
        edf = pd.DataFrame({"EPS Estimate": [1.0]}, index=pd.DatetimeIndex([pd.Timestamp(future_date)]))
        ticker = Mock()
        ticker.calendar = {}
        ticker.get_earnings_dates.return_value = edf

        with patch("stocktool.data.yf.Ticker", return_value=ticker):
            result = fetch_next_earnings_date("TEST")

        self.assertEqual(result["earnings_date"], future_date.isoformat())
        self.assertEqual(result["days_to_earnings"], 15)

    def test_never_raises_on_fetch_failure(self):
        with patch("stocktool.data.yf.Ticker", side_effect=RuntimeError("network down")):
            result = fetch_next_earnings_date("TEST")

        self.assertEqual(result, {})


class LeapsEarningsMoveStatsTests(unittest.TestCase):
    def test_computes_avg_and_max_abs_move(self):
        moves = [
            {"date": "2026-01-01", "pct_move": 5.0, "abs_pct_move": 5.0},
            {"date": "2026-04-01", "pct_move": -9.0, "abs_pct_move": 9.0},
        ]
        stats = leaps_earnings_move_stats(moves)

        self.assertAlmostEqual(stats.avg_abs_move_pct, 7.0)
        self.assertAlmostEqual(stats.max_abs_move_pct, 9.0)
        self.assertEqual(stats.quarters_used, 2)

    def test_empty_moves_returns_none(self):
        self.assertIsNone(leaps_earnings_move_stats([]))


class BuildLeapsEarningsContextTests(unittest.TestCase):
    def make_position(self) -> LeapsPosition:
        return LeapsPosition(
            id="earn001", ticker="TEST", option_type="CALL", strike=100.0,
            expiration="2028-01-01", premium=10.0, contracts=2,
        )

    def test_none_when_no_date_and_no_moves(self):
        context = build_leaps_earnings_context(self.make_position(), 100.0, 0.8, None, None, [])

        self.assertIsNone(context)

    def test_computes_delta_only_impact_with_moves_and_delta(self):
        moves = [{"date": "2026-01-01", "pct_move": 10.0, "abs_pct_move": 10.0}]
        context = build_leaps_earnings_context(
            self.make_position(), current_price=100.0, effective_delta=0.8,
            next_earnings_date="2026-12-01", days_to_earnings=20, moves=moves,
        )

        self.assertEqual(context.avg_abs_move_pct, 10.0)
        # delta_impact = 0.8 * 100 * 2 contracts * (100 * 10 / 100) = 1600.0
        self.assertAlmostEqual(context.delta_impact_avg, 1600.0)

    def test_date_only_with_no_moves_still_returns_context(self):
        context = build_leaps_earnings_context(self.make_position(), 100.0, 0.8, "2026-12-01", 20, [])

        self.assertIsNotNone(context)
        self.assertIsNone(context.avg_abs_move_pct)
        self.assertEqual(context.quarters_used, 0)


if __name__ == "__main__":
    unittest.main()
