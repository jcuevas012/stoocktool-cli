from datetime import date, timedelta
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from stocktool.analysis import _black_scholes_delta_gamma, build_leaps_gamma_curve, build_leaps_snapshot
from stocktool.data import fetch_leaps_gamma_inputs
from stocktool.leaps import LeapsPosition


def make_position(option_type: str, days_to_expiry: int = 365) -> LeapsPosition:
    return LeapsPosition(
        id="gamma001",
        ticker="TEST",
        option_type=option_type,
        strike=100.0,
        expiration=(date.today() + timedelta(days=days_to_expiry)).isoformat(),
        premium=10.0,
        entry_stock_price=100.0,
        entry_delta=0.6 if option_type == "CALL" else -0.4,
    )


class LeapsGammaCurveTests(unittest.TestCase):
    def build(self, option_type: str, days_to_expiry: int = 365):
        return build_leaps_gamma_curve(
            make_position(option_type, days_to_expiry),
            stock_price=100.0,
            implied_volatility_pct=30.0,
            risk_free_rate_pct=4.0,
            dividend_yield_pct=1.0,
        )

    def test_call_delta_rises_with_stock_price_and_gamma_is_positive(self):
        curve = self.build("CALL")

        self.assertIsNotNone(curve)
        self.assertGreater(curve.gamma, 0.0)
        self.assertGreater(curve.points[-1].delta, curve.points[0].delta)
        self.assertGreater(curve.model_delta, 0.0)

    def test_put_delta_moves_toward_zero_as_stock_price_rises(self):
        curve = self.build("PUT")

        self.assertIsNotNone(curve)
        self.assertGreater(curve.gamma, 0.0)
        self.assertLess(curve.model_delta, 0.0)
        self.assertGreater(curve.points[-1].delta, curve.points[0].delta)

    def test_gamma_matches_local_delta_change_per_dollar(self):
        years = 1.0
        args = ("CALL", 100.0, 100.0, years, 0.30, 0.04, 0.01)
        _, gamma = _black_scholes_delta_gamma(*args)
        delta_up, _ = _black_scholes_delta_gamma("CALL", 101.0, *args[2:])
        delta_down, _ = _black_scholes_delta_gamma("CALL", 99.0, *args[2:])

        self.assertAlmostEqual(gamma, (delta_up - delta_down) / 2.0, delta=0.00001)

    def test_gamma_decreases_with_more_time_at_the_money(self):
        one_year = self.build("CALL", 365)
        two_years = self.build("CALL", 730)

        self.assertIsNotNone(one_year)
        self.assertIsNotNone(two_years)
        self.assertGreater(one_year.gamma, two_years.gamma)

    def test_missing_required_market_input_disables_curve(self):
        good_inputs = {
            "stock_price": 100.0,
            "implied_volatility_pct": 30.0,
            "risk_free_rate_pct": 4.0,
            "dividend_yield_pct": 0.0,
        }
        for missing_input in good_inputs:
            with self.subTest(missing_input=missing_input):
                inputs = {**good_inputs, missing_input: None}
                self.assertIsNone(build_leaps_gamma_curve(make_position("CALL"), **inputs))

    def test_modeled_delta_never_replaces_broker_delta_for_exposure(self):
        position = make_position("PUT")
        position.current_delta = -0.65
        snapshot = build_leaps_snapshot(position, 100.0, 10000.0, {"mid": 10.0})
        curve = self.build("PUT")

        self.assertEqual(snapshot.effective_shares, -65.0)
        self.assertEqual(snapshot.current_delta, -0.65)
        self.assertNotEqual(curve.model_delta, snapshot.current_delta)
        self.assertEqual(position.current_delta, -0.65)

    def test_curve_centers_on_spot_and_covers_plus_minus_twenty_percent(self):
        curve = self.build("CALL")

        self.assertEqual(len(curve.points), 9)
        self.assertAlmostEqual(curve.points[0].stock_price, 80.0)
        self.assertAlmostEqual(curve.points[4].stock_price, curve.spot)
        self.assertAlmostEqual(curve.points[-1].stock_price, 120.0)
        self.assertAlmostEqual(curve.points[4].delta, curve.model_delta)

    def test_expired_or_zero_volatility_contract_has_no_curve(self):
        expired_position = make_position("CALL", days_to_expiry=-1)
        expired = build_leaps_gamma_curve(expired_position, 100.0, 30.0, 4.0, 1.0)
        zero_volatility = build_leaps_gamma_curve(make_position("CALL"), 100.0, 0.0, 4.0, 1.0)

        self.assertIsNone(expired)
        self.assertIsNone(zero_volatility)

    def test_market_inputs_keep_documented_yahoo_yield_units_and_dates(self):
        as_of = pd.Timestamp(date.today())
        stock = Mock()
        stock.info = {"dividendYield": 0.39}
        stock.history.return_value = pd.DataFrame({"Close": [250.0]}, index=[as_of])
        treasury = Mock()
        treasury.history.return_value = pd.DataFrame({"Close": [4.25]}, index=[as_of])

        with patch("stocktool.data.yf.Ticker", side_effect=[stock, treasury]):
            inputs = fetch_leaps_gamma_inputs("TEST")

        self.assertEqual(inputs["stock_price"], 250.0)
        self.assertEqual(inputs["stock_price_as_of"], date.today().isoformat())
        self.assertEqual(inputs["dividend_yield_pct"], 0.39)
        self.assertEqual(inputs["risk_free_rate_pct"], 4.25)
        self.assertEqual(inputs["risk_free_as_of"], date.today().isoformat())


if __name__ == "__main__":
    unittest.main()
