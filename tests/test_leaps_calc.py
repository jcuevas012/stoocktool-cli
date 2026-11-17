from datetime import date, timedelta
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from vstock.analysis import black_scholes_price_theta
from vstock.cli import app
from vstock.leaps_calc import (
    CalcInputs, ExistingLeaps, evaluate_leaps, exit_trigger_price, iv_max_position_pct, iv_tier_label,
    project_premium, stop_loss_price, check_iv_crush,
    SEVERITY_BLOCKING, SEVERITY_SKIPPED, SEVERITY_WARNING,
    VERDICT_APPROVED, VERDICT_BLOCKED, VERDICT_CAUTION,
)
from vstock.leaps_eval_history import list_evaluations, save_evaluation

TODAY = date(2026, 11, 15)


def make_inputs(**overrides) -> CalcInputs:
    """GOOGL Jun 2028 $260C, mirroring the spec's worked example, with every rule passing."""
    base = dict(
        ticker="GOOGL",
        strike=260.0,
        expiration="2028-06-16",
        spot=294.73,
        premium=81.13,
        bid=80.5,
        ask=81.76,
        mid=81.13,
        spread_pct=1.5,
        iv_pct=36.8,
        iv_percentile=40.0,
        delta=0.77,
        theta=-0.058,
        days_to_earnings=75,
        nav=250_000.0,
        used_margin=0.0,
        today=TODAY.isoformat(),
    )
    base.update(overrides)
    return CalcInputs(**base)


def blocking_rules(ev) -> set[str]:
    return {r.rule for r in ev.rules if r.severity == SEVERITY_BLOCKING}


def rule(ev, name):
    return next(r for r in ev.rules if r.rule == name)


class SpecScenarioTests(unittest.TestCase):
    def test_1_current_state_blocks_on_size_margin_phase(self):
        ev = evaluate_leaps(make_inputs(
            nav=81_500.0, used_margin=8_308.0,
            existing_leaps=[ExistingLeaps("AMZN", 220.0, "2028-01-21", 67.5)],
        ))
        self.assertEqual(ev.verdict, VERDICT_BLOCKED)
        self.assertEqual(blocking_rules(ev), {"Position size", "Margin status", "Portfolio phase"})
        self.assertEqual(rule(ev, "Correlation").severity, SEVERITY_WARNING)

    def test_2_phase_3_nav_no_margin_is_approved(self):
        ev = evaluate_leaps(make_inputs(nav=250_000.0))
        self.assertEqual(ev.verdict, VERDICT_APPROVED, [r for r in ev.rules if r.severity != "ok"])

    def test_3_paper_skips_nav_rules_but_checks_contract_rules(self):
        ev = evaluate_leaps(make_inputs(ticker="NVDA", strike=220.0, expiration="2028-01-21",
                                        paper=True, nav=None, used_margin=50_000.0))
        for name in ("Position size", "Margin status", "Portfolio phase"):
            self.assertEqual(rule(ev, name).severity, SEVERITY_SKIPPED)
        for name in ("Delta range", "Days to expiry", "IV level / sizing", "IV crush trap"):
            self.assertNotEqual(rule(ev, name).severity, SEVERITY_SKIPPED)

    def test_4_unapproved_ticker_blocks(self):
        ev = evaluate_leaps(make_inputs(ticker="AMD", strike=200.0))
        self.assertIn("Approved ticker", blocking_rules(ev))
        self.assertEqual(ev.verdict, VERDICT_BLOCKED)

    def test_5_short_dte_blocks(self):
        ev = evaluate_leaps(make_inputs(strike=290.0, expiration="2027-01-15"))
        self.assertIn("Days to expiry", blocking_rules(ev))

    def test_6_low_delta_blocks(self):
        ev = evaluate_leaps(make_inputs(strike=320.0, delta=0.55))
        self.assertIn("Delta range", blocking_rules(ev))

    def test_delta_warning_band(self):
        ev = evaluate_leaps(make_inputs(delta=0.72, nav=250_000.0))
        self.assertEqual(rule(ev, "Delta range").severity, SEVERITY_WARNING)
        self.assertEqual(ev.verdict, VERDICT_CAUTION)

    def test_7_tsla_locked_until_phase_6(self):
        locked = evaluate_leaps(make_inputs(ticker="TSLA", strike=400.0, nav=100_000.0))
        self.assertIn("Approved ticker", blocking_rules(locked))
        unlocked = evaluate_leaps(make_inputs(ticker="TSLA", strike=400.0, nav=300_000.0))
        self.assertNotIn("Approved ticker", blocking_rules(unlocked))
        paper = evaluate_leaps(make_inputs(ticker="TSLA", strike=400.0, paper=True, nav=None))
        self.assertIn("Approved ticker", blocking_rules(paper))

    def test_8_compare_two_strikes(self):
        from vstock import display

        a = evaluate_leaps(make_inputs())
        b = evaluate_leaps(make_inputs(strike=270.0, premium=75.0, delta=0.74))
        self.assertNotEqual(a.metrics.breakeven, b.metrics.breakeven)
        self.assertNotEqual(a.metrics.exit_price, b.metrics.exit_price)
        self.assertNotEqual(a.metrics.contract_cost, b.metrics.contract_cost)
        display.render_leaps_calc_compare(a, b)  # must not raise


class CalcMathTests(unittest.TestCase):
    def test_breakeven_exit_stop(self):
        ev = evaluate_leaps(make_inputs())
        self.assertAlmostEqual(ev.metrics.breakeven, 341.13)
        self.assertAlmostEqual(ev.metrics.exit_price, 294.73 + 0.5 * 81.13 / 0.77)
        self.assertAlmostEqual(ev.metrics.stop_price, 294.73 - 0.5 * 81.13 / 0.77)
        self.assertEqual(ev.metrics.critical_exit_date, "2028-03-18")
        self.assertAlmostEqual(exit_trigger_price(100, 10, 0.5), 110)
        self.assertAlmostEqual(stop_loss_price(100, 10, 0.5), 90)

    def test_projection_subtracts_theta_once_and_floors_at_intrinsic(self):
        value = project_premium("CALL", 260, 81.13, 0.77, -0.058, 294.73, 294.73, 30)
        self.assertAlmostEqual(value, 81.13 - 0.058 * 30)
        deep = project_premium("CALL", 100, 10, 0.5, -0.1, 100, 200, 0)
        self.assertEqual(deep, 100)  # intrinsic floor beats 10 + 0.5*100

    def test_theta_projection_is_negative_dollars(self):
        ev = evaluate_leaps(make_inputs())
        self.assertAlmostEqual(ev.metrics.theta_projection[30], -0.058 * 30 * 100)
        self.assertLess(ev.metrics.theta_projection_pct[365], 0)

    def test_scenarios_mark_key_levels(self):
        ev = evaluate_leaps(make_inputs(), scenario_prices=[260, 300, 340])
        markers = {m for row in ev.scenarios for m in row.markers}
        self.assertTrue({"🎯", "BE", "K", "🛑", "NOW"} <= markers)
        be_row = next(r for r in ev.scenarios if "BE" in r.markers)
        self.assertAlmostEqual(be_row.pnl_at_expiry, 0.0, places=6)
        now_row = next(r for r in ev.scenarios if "NOW" in r.markers)
        self.assertAlmostEqual(now_row.pnl_by_horizon[0], 0.0, places=6)

    def test_black_scholes_call_theta_negative_and_price_positive(self):
        price, theta = black_scholes_price_theta("CALL", 100, 90, 1.5, 0.3, 0.04, 0.01)
        self.assertGreater(price, 10)
        self.assertLess(theta, 0)

    def test_iv_sizing_tiers(self):
        self.assertEqual(iv_max_position_pct(30), 4.0)
        self.assertEqual(iv_max_position_pct(50), 3.0)
        self.assertEqual(iv_max_position_pct(70), 1.0)
        self.assertEqual(iv_max_position_pct(None), 1.0)

    def test_iv_tier_labels_follow_config(self):
        self.assertEqual(iv_tier_label(30), "<40%")
        self.assertEqual(iv_tier_label(47.6), "40–60%")
        self.assertEqual(iv_tier_label(75), "≥60%")

    def test_iv_sizing_message_explains_tier_and_overage(self):
        ev = evaluate_leaps(make_inputs(iv_pct=47.6, nav=100_000.0))
        r = rule(ev, "IV level / sizing")
        self.assertEqual(r.severity, SEVERITY_WARNING)
        self.assertIn("40–60% tier", r.actual)
        self.assertIn("over the cap", r.actual)
        self.assertIn("max 3% of NAV", r.required)
        self.assertTrue(r.why)


class ConservativeDefaultTests(unittest.TestCase):
    def test_iv_crush_unknown_percentile_and_earnings_blocks(self):
        self.assertFalse(check_iv_crush(make_inputs(iv_percentile=None, days_to_earnings=None)).passed)

    def test_iv_crush_unknown_percentile_far_earnings_passes(self):
        self.assertTrue(check_iv_crush(make_inputs(iv_percentile=None, days_to_earnings=75)).passed)

    def test_iv_crush_high_percentile_near_earnings_blocks(self):
        self.assertFalse(check_iv_crush(make_inputs(iv_percentile=85, days_to_earnings=10)).passed)

    def test_paying_the_ask_warns(self):
        ev = evaluate_leaps(make_inputs(premium=81.76, nav=250_000.0))
        self.assertEqual(rule(ev, "Fill price").severity, SEVERITY_WARNING)

    def test_duplicate_contract_warns(self):
        ev = evaluate_leaps(make_inputs(existing_leaps=[ExistingLeaps("GOOGL", 260.0, "2028-06-16", 80.0)]))
        self.assertEqual(rule(ev, "Duplicate contract").severity, SEVERITY_WARNING)

    def test_missing_delta_blocks(self):
        ev = evaluate_leaps(make_inputs(delta=None, iv_pct=None))
        self.assertIn("Delta range", blocking_rules(ev))
        self.assertIsNone(ev.metrics.exit_price)


class HistoryTests(unittest.TestCase):
    def test_save_and_list_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "evals.db"
            ev = evaluate_leaps(make_inputs(nav=81_500.0, used_margin=8_308.0))
            row_id = save_evaluation(ev, db_path=db)
            rows = list_evaluations(db_path=db)
            self.assertEqual(rows[0]["id"], row_id)
            self.assertEqual(rows[0]["verdict"], VERDICT_BLOCKED)
            self.assertEqual(len(json.loads(rows[0]["blocking_failures_json"])), 3)
            self.assertEqual(list_evaluations(ticker="AMZN", db_path=db), [])


def fake_market(ticker, strike, expiration, option_type="CALL"):
    return {
        "expiration": "2028-06-16",
        "strike_found": True,
        "quote": {"bid": 80.5, "ask": 81.76, "mid": 81.13, "spread_pct": 1.5, "implied_volatility": 36.8},
        "gamma_inputs": {"stock_price": 294.73, "risk_free_rate_pct": 4.0, "dividend_yield_pct": 0.3},
        "earnings": {"earnings_date": (date.today() + timedelta(days=75)).isoformat(), "days_to_earnings": 75},
        "realized_volatility": 30.0,
    }


@patch("vstock.leaps.load_leaps")
@patch("vstock.data.get_used_margin", return_value=0.0)
@patch("vstock.data.fetch_leaps_calc_inputs", side_effect=fake_market)
class CliTests(unittest.TestCase):
    args = ["calc", "leaps", "GOOGL", "--strike", "260", "--expiration", "2028-06-16"]

    def setUp(self):
        self.runner = CliRunner()

    def test_json_output_is_valid(self, _fetch, _margin, load_leaps):
        load_leaps.return_value.active_positions.return_value = []
        result = self.runner.invoke(app, self.args + ["--nav", "250000", "-o", "json"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["inputs"]["ticker"], "GOOGL")
        self.assertIn(payload["verdict"], {VERDICT_APPROVED, VERDICT_CAUTION, VERDICT_BLOCKED})

    def test_compact_output_is_one_line(self, _fetch, _margin, load_leaps):
        load_leaps.return_value.active_positions.return_value = []
        result = self.runner.invoke(app, self.args + ["--paper", "-o", "compact"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(len(result.stdout.strip().splitlines()), 1)
        self.assertIn("VERDICT", result.stdout)

    def test_missing_nav_errors_cleanly(self, _fetch, _margin, load_leaps):
        load_leaps.return_value.active_positions.return_value = []
        with patch("vstock.cli._leaps_portfolio_value", return_value=None):
            result = self.runner.invoke(app, self.args)
        self.assertEqual(result.exit_code, 1)
        self.assertIsNone(result.exception if not isinstance(result.exception, SystemExit) else None)


if __name__ == "__main__":
    unittest.main()
