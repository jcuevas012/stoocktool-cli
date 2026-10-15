import unittest
from unittest.mock import Mock, patch

import pandas as pd

from stocktool.analysis import _institutional_flow_signal, build_valuation_snapshot
from stocktool.data import fetch_institutional_ownership


def holder(pct_change: float, value: float, holder_name: str = "H") -> dict:
    return {"holder": holder_name, "pct_held": 1.0, "value": value, "pct_change": pct_change}


class InstitutionalFlowSignalTests(unittest.TestCase):
    def test_dollar_weighted_average_favors_the_larger_holder(self):
        holders = [
            holder(pct_change=10.0, value=900.0, holder_name="Big"),
            holder(pct_change=-10.0, value=100.0, holder_name="Small"),
        ]
        # weighted = (10*900 + -10*100) / 1000 = 8.0
        signal = _institutional_flow_signal(holders)

        self.assertAlmostEqual(signal.net_flow_pct, 8.0)
        self.assertEqual(signal.label, "NET BUYING")
        self.assertEqual(signal.color, "green")

    def test_counts_increasing_decreasing_and_unchanged(self):
        holders = [
            holder(1.0, 100.0), holder(2.0, 100.0), holder(-1.0, 100.0), holder(0.0, 100.0),
        ]
        signal = _institutional_flow_signal(holders)

        self.assertEqual(signal.holders_increasing, 2)
        self.assertEqual(signal.holders_decreasing, 1)
        self.assertEqual(signal.holders_unchanged, 1)

    def test_label_boundaries(self):
        cases = [
            (1.01, "NET BUYING", "green"),
            (1.0, "MIXED/FLAT", "yellow"),
            (-1.0, "MIXED/FLAT", "yellow"),
            (-1.01, "NET SELLING", "red"),
            (0.0, "MIXED/FLAT", "yellow"),
        ]
        for net_flow, expected_label, expected_color in cases:
            with self.subTest(net_flow=net_flow):
                holders = [holder(net_flow, 100.0)]
                signal = _institutional_flow_signal(holders)
                self.assertEqual(signal.label, expected_label)
                self.assertEqual(signal.color, expected_color)

    def test_empty_holders_returns_none(self):
        self.assertIsNone(_institutional_flow_signal([]))

    def test_zero_total_value_returns_none(self):
        # Can't dollar-weight when every holder reports zero value.
        self.assertIsNone(_institutional_flow_signal([holder(5.0, 0.0), holder(-5.0, 0.0)]))


class FetchInstitutionalOwnershipTests(unittest.TestCase):
    def test_extracts_ownership_breakdown_and_top_holders(self):
        major_holders = pd.DataFrame(
            {"Value": [0.0165, 0.6632, 0.6743, 7684.0]},
            index=["insidersPercentHeld", "institutionsPercentHeld",
                   "institutionsFloatPercentHeld", "institutionsCount"],
        )
        institutional_holders = pd.DataFrame({
            "Date Reported": [pd.Timestamp("2026-06-30")] * 2,
            "Holder": ["Blackrock Inc.", "Vanguard Capital Management LLC"],
            "pctHeld": [0.0797, 0.0657],
            "Shares": [1162996939, 959107911],
            "Value": [392092805050, 323353655163],
            "pctChange": [0.0160, 0.0055],
        })

        ticker = Mock()
        ticker.major_holders = major_holders
        ticker.institutional_holders = institutional_holders

        with patch("stocktool.data.yf.Ticker", return_value=ticker):
            result = fetch_institutional_ownership(["AAPL"])

        data = result["AAPL"]
        self.assertAlmostEqual(data["institutions_pct"], 66.32, places=2)
        self.assertAlmostEqual(data["insiders_pct"], 1.65, places=2)
        self.assertEqual(data["institutions_count"], 7684)
        self.assertEqual(data["report_date"], "2026-06-30")
        self.assertEqual(len(data["top_holders"]), 2)
        self.assertEqual(data["top_holders"][0]["holder"], "Blackrock Inc.")
        self.assertAlmostEqual(data["top_holders"][0]["pct_held"], 7.97, places=2)
        self.assertAlmostEqual(data["top_holders"][0]["pct_change"], 1.60, places=2)

    def test_never_raises_on_fetch_failure(self):
        with patch("stocktool.data.yf.Ticker", side_effect=RuntimeError("network down")):
            result = fetch_institutional_ownership(["AAPL"])

        self.assertEqual(result, {"AAPL": {}})

    def test_empty_major_holders_returns_empty_dict_for_ticker(self):
        ticker = Mock()
        ticker.major_holders = pd.DataFrame()
        ticker.institutional_holders = pd.DataFrame()

        with patch("stocktool.data.yf.Ticker", return_value=ticker):
            result = fetch_institutional_ownership(["AAPL"])

        self.assertEqual(result, {"AAPL": {}})


class BuildValuationSnapshotInstitutionalWiringTests(unittest.TestCase):
    def test_institutional_fields_land_on_the_snapshot(self):
        institutional_data = {
            "institutions_pct": 66.32,
            "insiders_pct": 1.65,
            "institutions_count": 7684,
            "report_date": "2026-06-30",
            "top_holders": [
                holder(pct_change=1.60, value=392092805050.0, holder_name="Blackrock Inc."),
                holder(pct_change=-1.23, value=76754226410.0, holder_name="JPMORGAN CHASE & CO"),
            ],
        }

        snapshot = build_valuation_snapshot(
            "AAPL", {}, pd.DataFrame(), None, institutional_data=institutional_data,
        )

        self.assertEqual(snapshot.institutions_pct, 66.32)
        self.assertEqual(snapshot.insiders_pct, 1.65)
        self.assertEqual(snapshot.institutions_count, 7684)
        self.assertEqual(snapshot.institutional_report_date, "2026-06-30")
        self.assertEqual(len(snapshot.top_institutional_holders), 2)
        self.assertIsNotNone(snapshot.institutional_flow)
        self.assertEqual(snapshot.institutional_flow.holders_increasing, 1)
        self.assertEqual(snapshot.institutional_flow.holders_decreasing, 1)

    def test_no_institutional_data_leaves_fields_none(self):
        snapshot = build_valuation_snapshot("AAPL", {}, pd.DataFrame(), None)

        self.assertIsNone(snapshot.institutions_pct)
        self.assertIsNone(snapshot.institutional_flow)
        self.assertEqual(snapshot.top_institutional_holders, [])


if __name__ == "__main__":
    unittest.main()
