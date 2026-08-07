from __future__ import annotations

import unittest

from a_share_midreport_cloud.backend.app import _industry_summary, _median_metric


class PortalAggregationTests(unittest.TestCase):
    def test_median_metric_ignores_missing_values(self) -> None:
        items = [{"pe": 10}, {"pe": None}, {"pe": 30}, {}]
        self.assertEqual(_median_metric(items, "pe"), 20)

    def test_positive_only_excludes_non_positive_valuation(self) -> None:
        items = [{"pe": -5}, {"pe": 0}, {"pe": 18}, {"pe": 22}]
        self.assertEqual(_median_metric(items, "pe", positive_only=True), 20)

    def test_industry_summary_uses_metric_medians(self) -> None:
        items = [
            {"pe": 12, "roe": 8, "profit_growth": -10},
            {"pe": 18, "roe": 12, "profit_growth": 30},
        ]
        result = _industry_summary("example", items)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["median_pe"], 15)
        self.assertEqual(result["median_roe"], 10)
        self.assertEqual(result["median_profit_growth"], 10)


if __name__ == "__main__":
    unittest.main()
