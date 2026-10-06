import unittest
from datetime import date, timedelta

from stocktool.analysis import build_leaps_gamma_curve, build_leaps_vega_impact
from stocktool.leaps import LeapsPosition


def make_position(entry_iv=None, current_iv=None) -> LeapsPosition:
    return LeapsPosition(
        id="vega001",
        ticker="TEST",
        option_type="CALL",
        strike=100.0,
        expiration=(date.today() + timedelta(days=365)).isoformat(),
        premium=10.0,
        contracts=2,
        entry_stock_price=100.0,
        entry_iv=entry_iv,
        current_iv=current_iv,
    )


def make_curve(position):
    return build_leaps_gamma_curve(
        position, stock_price=100.0, implied_volatility_pct=30.0,
        risk_free_rate_pct=4.0, dividend_yield_pct=1.0,
    )


class VegaImpactTests(unittest.TestCase):
    def test_none_curve_returns_none(self):
        self.assertIsNone(build_leaps_vega_impact(None, make_position()))

    def test_total_vega_scales_by_contracts(self):
        position = make_position(entry_iv=30.0, current_iv=30.0)
        curve = make_curve(position)
        impact = build_leaps_vega_impact(curve, position)

        self.assertAlmostEqual(impact.vega_total, impact.vega_per_contract * 2)
        self.assertAlmostEqual(impact.impact_plus_10, impact.vega_total * 10)
        self.assertAlmostEqual(impact.impact_minus_20, impact.vega_total * -20)

    def test_zero_iv_change_gives_real_zero_not_none(self):
        # Review Focus #1: entry == current must show a real $0.00, not "N/A".
        position = make_position(entry_iv=30.0, current_iv=30.0)
        curve = make_curve(position)
        impact = build_leaps_vega_impact(curve, position)

        self.assertEqual(impact.iv_change_pts, 0.0)
        self.assertEqual(impact.vega_pnl_since_entry, 0.0)
        self.assertIsNotNone(impact.vega_pnl_since_entry)

    def test_missing_both_entry_and_current_iv_gives_none_change(self):
        position = make_position(entry_iv=None, current_iv=None)
        curve = make_curve(position)
        impact = build_leaps_vega_impact(curve, position)

        self.assertIsNotNone(impact)  # vega itself is still computable
        self.assertIsNone(impact.iv_change_pts)
        self.assertIsNone(impact.vega_pnl_since_entry)

    def test_current_iv_falls_back_to_entry_iv_when_unset(self):
        position = make_position(entry_iv=30.0, current_iv=None)
        curve = make_curve(position)
        impact = build_leaps_vega_impact(curve, position)

        self.assertEqual(impact.current_iv, 30.0)
        self.assertEqual(impact.iv_change_pts, 0.0)


if __name__ == "__main__":
    unittest.main()
