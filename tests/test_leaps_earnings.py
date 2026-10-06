import unittest
from datetime import date, timedelta
from unittest.mock import Mock, patch

import pandas as pd

from stocktool.data import fetch_earnings_move_history, fetch_next_earnings_date


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


if __name__ == "__main__":
    unittest.main()
