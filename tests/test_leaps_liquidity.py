import unittest
from unittest.mock import Mock, patch

import pandas as pd

from stocktool.analysis import leaps_liquidity_rating
from stocktool.data import fetch_leaps_option_quote


class LeapsLiquidityRatingTests(unittest.TestCase):
    def test_tight_when_narrow_spread_and_high_oi(self):
        self.assertEqual(leaps_liquidity_rating(0.5, 600), ("TIGHT", "green"))

    def test_moderate_boundary(self):
        self.assertEqual(leaps_liquidity_rating(2.0, 200), ("MODERATE", "yellow"))

    def test_wide_boundary(self):
        self.assertEqual(leaps_liquidity_rating(4.0, 60), ("WIDE", "orange3"))

    def test_illiquid_when_spread_too_wide(self):
        self.assertEqual(leaps_liquidity_rating(8.0, 1000), ("ILLIQUID", "red"))

    def test_illiquid_when_open_interest_too_low(self):
        self.assertEqual(leaps_liquidity_rating(0.5, 10), ("ILLIQUID", "red"))

    def test_missing_spread_returns_na(self):
        # Review Focus #4.
        self.assertEqual(leaps_liquidity_rating(None, 600), ("N/A", "dim"))

    def test_missing_open_interest_returns_na(self):
        # Review Focus #4.
        self.assertEqual(leaps_liquidity_rating(0.5, None), ("N/A", "dim"))


class FetchLeapsOptionQuoteLiquidityTests(unittest.TestCase):
    def test_extracts_volume_and_open_interest(self):
        row = pd.DataFrame([{
            "strike": 100.0, "bid": 9.5, "ask": 10.0,
            "impliedVolatility": 0.30, "lastTradeDate": pd.Timestamp("2026-01-01"),
            "volume": 89, "openInterest": 1245,
        }])
        chain = Mock()
        chain.calls, chain.puts = row, row
        ticker = Mock()
        ticker.option_chain.return_value = chain

        with patch("stocktool.data.yf.Ticker", return_value=ticker):
            result = fetch_leaps_option_quote("TEST", "CALL", 100.0, "2028-01-01")

        self.assertEqual(result["volume"], 89)
        self.assertEqual(result["open_interest"], 1245)


if __name__ == "__main__":
    unittest.main()
