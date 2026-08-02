from __future__ import annotations

import unittest

import pandas as pd

from fetch_tushare_metrics import (
    _financial_candidates,
    _merge_daily_basic,
    _merge_disclosures,
    _merge_financial_indicator,
    _ts_code,
)


class TushareMetricTests(unittest.TestCase):
    def test_ts_code_uses_expected_exchange_suffix(self) -> None:
        self.assertEqual(_ts_code("600519"), "600519.SH")
        self.assertEqual(_ts_code("002714"), "002714.SZ")
        self.assertEqual(_ts_code("430047"), "430047.BJ")

    def test_daily_basic_overlays_quotes_and_dividend(self) -> None:
        payload = {
            "stocks": [{"code": "600519"}],
            "quotes": {"600519": {"change_pct": 1.2}},
            "fundamentals": {},
        }
        frame = pd.DataFrame(
            [
                {
                    "ts_code": "600519.SH",
                    "trade_date": "20260731",
                    "close": 1500.0,
                    "pe": 22.0,
                    "pe_ttm": 21.5,
                    "pb": 7.2,
                    "dv_ttm": 3.1,
                    "total_mv": 18_800_000.0,
                }
            ]
        )

        self.assertEqual(_merge_daily_basic(payload, frame), 1)
        quote = payload["quotes"]["600519"]
        self.assertEqual(quote["pe"], 21.5)
        self.assertEqual(quote["market_cap"], 188_000_000_000.0)
        self.assertEqual(quote["change_pct"], 1.2)
        fundamental = payload["fundamentals"]["600519"]
        self.assertEqual(fundamental["dividend_yield"], 3.1)
        self.assertEqual(fundamental["dividend_source"], "Tushare Pro/daily_basic")

    def test_disclosure_overlay_prefers_actual_date(self) -> None:
        payload = {"stocks": [{"code": "600519", "date": "2026-08-30"}]}
        frame = pd.DataFrame(
            [
                {
                    "ts_code": "600519.SH",
                    "ann_date": "20260720",
                    "pre_date": "20260815",
                    "actual_date": "20260814",
                    "modify_date": "20260718",
                }
            ]
        )

        self.assertEqual(_merge_disclosures(payload, frame), 1)
        stock = payload["stocks"][0]
        self.assertEqual(stock["date"], "2026-08-14")
        self.assertEqual(stock["actual_date"], "2026-08-14")
        self.assertEqual(stock["schedule_status"], "已披露")

    def test_financial_indicator_uses_latest_period_and_maps_metrics(self) -> None:
        metrics = {"600519": {"financial_period": "2026-03-31"}}
        frame = pd.DataFrame(
            [
                {
                    "ts_code": "600519.SH",
                    "ann_date": "20260420",
                    "end_date": "20260331",
                    "roe_waa": 8.0,
                },
                {
                    "ts_code": "600519.SH",
                    "ann_date": "20260814",
                    "end_date": "20260630",
                    "eps": 31.2,
                    "profit_dedt": 41_000_000_000.0,
                    "dt_netprofit_yoy": 12.3,
                    "roe_waa": 18.2,
                    "grossprofit_margin": 91.1,
                    "ocfps": 32.5,
                    "debt_to_assets": 22.4,
                    "tr_yoy": 14.6,
                    "netprofit_yoy": 15.8,
                },
            ]
        )

        self.assertTrue(_merge_financial_indicator(metrics, "600519", frame))
        result = metrics["600519"]
        self.assertEqual(result["financial_period"], "2026-06-30")
        self.assertEqual(result["roe"], 18.2)
        self.assertEqual(result["deducted_profit_growth"], 12.3)
        self.assertEqual(result["financial_source"], "Tushare Pro/fina_indicator")

    def test_financial_indicator_does_not_downgrade_period(self) -> None:
        metrics = {"600519": {"financial_period": "2026-06-30", "roe": 18.0}}
        frame = pd.DataFrame(
            [{"ts_code": "600519.SH", "ann_date": "20260420", "end_date": "20260331", "roe": 8.0}]
        )

        self.assertFalse(_merge_financial_indicator(metrics, "600519", frame))
        self.assertEqual(metrics["600519"]["roe"], 18.0)

    def test_candidates_only_include_reported_companies(self) -> None:
        payload = {
            "stocks": [
                {"code": "1", "source": "正式中报", "date": "2026-07-20"},
                {"code": "2", "actual_date": "2026-07-25", "source": "待披露"},
                {"code": "3", "source": "业绩预告", "date": "2026-08-01"},
            ]
        }

        self.assertEqual(
            [stock["code"] for stock in _financial_candidates(payload, 10)],
            ["2", "1"],
        )


if __name__ == "__main__":
    unittest.main()
