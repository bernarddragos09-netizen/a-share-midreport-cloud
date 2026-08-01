#!/usr/bin/env python3
"""Refresh cached A-share screening metrics through AKShare bulk interfaces."""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import akshare as ak
import pandas as pd
import requests


ROOT = Path(__file__).resolve().parent
SNAPSHOT_PATH = ROOT / "a_share_midreport_cloud" / "data" / "stock_snapshot.json"
CHINA_TZ = ZoneInfo("Asia/Shanghai")


def _disable_broken_local_proxy() -> None:
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        value = os.environ.get(name, "")
        if value.startswith(("http://127.0.0.1:", "https://127.0.0.1:")):
            os.environ.pop(name, None)


def _install_default_timeout(seconds: int = 45) -> None:
    original = requests.sessions.Session.request

    def request_with_timeout(self, method, url, **kwargs):
        kwargs.setdefault("timeout", seconds)
        return original(self, method, url, **kwargs)

    requests.sessions.Session.request = request_with_timeout


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _date_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, (int, float)) and value > 10_000_000_000:
        return datetime.fromtimestamp(value / 1000, CHINA_TZ).strftime("%Y-%m-%d")
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    return text[:10] if text and text.lower() not in {"nat", "nan", "none"} else ""


def _fetch(label: str, function: Callable[[], pd.DataFrame], retries: int = 2) -> pd.DataFrame:
    for attempt in range(1, retries + 1):
        started = time.monotonic()
        try:
            frame = function()
            if not isinstance(frame, pd.DataFrame):
                raise TypeError(f"{label} did not return a DataFrame")
            print(f"{label}: {len(frame)} rows in {time.monotonic() - started:.1f}s")
            return frame
        except Exception as exc:
            print(f"{label} failed ({attempt}/{retries}): {type(exc).__name__}: {exc}")
            if attempt < retries:
                time.sleep(attempt * 2)
    return pd.DataFrame()


def _rows_by_code(frame: pd.DataFrame, code_column: str) -> dict[str, dict[str, Any]]:
    if frame.empty or code_column not in frame.columns:
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for raw in frame.to_dict("records"):
        code = str(raw.get(code_column, "")).strip().split(".")[0].zfill(6)
        if len(code) == 6:
            rows[code] = raw
    return rows


def _set_number(target: dict[str, Any], key: str, row: dict[str, Any], column: str) -> None:
    value = _number(row.get(column))
    if value is not None:
        target[key] = value


def _merge_earnings(
    metrics: dict[str, dict[str, Any]], frame: pd.DataFrame, period: str
) -> None:
    for code, row in _rows_by_code(frame, "股票代码").items():
        item = metrics.setdefault(code, {})
        item.update(
            {
                "financial_period": f"{period[:4]}-{period[4:6]}-{period[6:]}",
                "financial_source": "AKShare/东方财富业绩报告",
                "ak_industry": str(row.get("所处行业") or "").strip(),
                "financial_announcement_date": _date_text(row.get("最新公告日期")),
            }
        )
        for key, column in (
            ("eps", "每股收益"),
            ("revenue", "营业总收入-营业总收入"),
            ("financial_revenue_growth", "营业总收入-同比增长"),
            ("net_profit", "净利润-净利润"),
            ("financial_profit_growth", "净利润-同比增长"),
            ("roe", "净资产收益率"),
            ("gross_margin", "销售毛利率"),
            ("ocf_per_share", "每股经营现金流量"),
        ):
            _set_number(item, key, row, column)


def _merge_balance_sheet(
    metrics: dict[str, dict[str, Any]], frame: pd.DataFrame, period: str
) -> None:
    for code, row in _rows_by_code(frame, "股票代码").items():
        item = metrics.setdefault(code, {})
        item["balance_period"] = f"{period[:4]}-{period[4:6]}-{period[6:]}"
        for key, column in (
            ("debt_ratio", "资产负债率"),
            ("total_assets", "资产-总资产"),
            ("total_liabilities", "负债-总负债"),
            ("shareholder_equity", "股东权益合计"),
        ):
            _set_number(item, key, row, column)


def _merge_cashflow(
    metrics: dict[str, dict[str, Any]], frame: pd.DataFrame, period: str
) -> None:
    for code, row in _rows_by_code(frame, "股票代码").items():
        item = metrics.setdefault(code, {})
        item["cashflow_period"] = f"{period[:4]}-{period[4:6]}-{period[6:]}"
        for key, column in (
            ("operating_cashflow", "经营性现金流-现金流量净额"),
            ("investing_cashflow", "投资性现金流-现金流量净额"),
            ("financing_cashflow", "融资性现金流-现金流量净额"),
        ):
            _set_number(item, key, row, column)


def _merge_dividends(
    metrics: dict[str, dict[str, Any]], frame: pd.DataFrame, period: str
) -> None:
    for code, row in _rows_by_code(frame, "代码").items():
        dividend_yield = _number(row.get("现金分红-股息率"))
        if dividend_yield is None:
            continue
        item = metrics.setdefault(code, {})
        item.update(
            {
                "dividend_yield": dividend_yield * 100,
                "dividend_period": f"{period[:4]}-{period[4:6]}-{period[6:]}",
                "dividend_status": str(row.get("方案进度") or "").strip(),
            }
        )


def refresh(periods: list[str], dividend_periods: list[str]) -> dict[str, Any]:
    if not SNAPSHOT_PATH.exists():
        raise RuntimeError(f"Stock snapshot does not exist: {SNAPSHOT_PATH}")
    _disable_broken_local_proxy()
    _install_default_timeout()

    payload = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    allowed_codes = {str(item.get("code", "")) for item in payload.get("stocks") or []}
    metrics: dict[str, dict[str, Any]] = {
        str(code): dict(item)
        for code, item in (payload.get("fundamentals") or {}).items()
        if str(code) in allowed_codes and isinstance(item, dict)
    }

    successful_sources: list[str] = []
    for period in periods:
        earnings = _fetch(f"stock_yjbb_em({period})", lambda p=period: ak.stock_yjbb_em(date=p))
        if not earnings.empty:
            _merge_earnings(metrics, earnings, period)
            successful_sources.append(f"业绩报告{period}")

        balance = _fetch(f"stock_zcfz_em({period})", lambda p=period: ak.stock_zcfz_em(date=p))
        if not balance.empty:
            _merge_balance_sheet(metrics, balance, period)
            successful_sources.append(f"资产负债表{period}")

        cashflow = _fetch(f"stock_xjll_em({period})", lambda p=period: ak.stock_xjll_em(date=p))
        if not cashflow.empty:
            _merge_cashflow(metrics, cashflow, period)
            successful_sources.append(f"现金流量表{period}")

    for period in dividend_periods:
        dividends = _fetch(f"stock_fhps_em({period})", lambda p=period: ak.stock_fhps_em(date=p))
        if not dividends.empty:
            _merge_dividends(metrics, dividends, period)
            successful_sources.append(f"分红配送{period}")

    if not successful_sources:
        raise RuntimeError("Every AKShare bulk interface failed; the existing cache was left unchanged")

    metrics = {code: item for code, item in metrics.items() if code in allowed_codes}
    payload["fundamentals"] = metrics
    payload["akshare_generated_at"] = datetime.now(CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S")
    payload["akshare_sources"] = successful_sources
    temporary = SNAPSHOT_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    temporary.replace(SNAPSHOT_PATH)
    print(f"AKShare metrics cached: {len(metrics)} stocks")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--periods", nargs="+", default=["20260331", "20260630"])
    parser.add_argument("--dividend-periods", nargs="+", default=["20251231", "20260630"])
    args = parser.parse_args()
    refresh(args.periods, args.dividend_periods)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
