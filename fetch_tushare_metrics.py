#!/usr/bin/env python3
"""Overlay the cloud stock snapshot with Tushare Pro data."""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import pandas as pd
import tushare as ts


ROOT = Path(__file__).resolve().parent
SNAPSHOT_PATH = ROOT / "a_share_midreport_cloud" / "data" / "stock_snapshot.json"
CHINA_TZ = ZoneInfo("Asia/Shanghai")
DAILY_BASIC_FIELDS = "ts_code,trade_date,close,pe,pe_ttm,pb,dv_ttm,total_mv"
DISCLOSURE_FIELDS = "ts_code,ann_date,end_date,pre_date,actual_date,modify_date"
FINANCIAL_FIELDS = ",".join(
    (
        "ts_code",
        "ann_date",
        "end_date",
        "update_flag",
        "eps",
        "profit_dedt",
        "dt_netprofit_yoy",
        "roe",
        "roe_waa",
        "grossprofit_margin",
        "netprofit_margin",
        "ocfps",
        "debt_to_assets",
        "current_ratio",
        "quick_ratio",
        "interestdebt",
        "netdebt",
        "fcff",
        "fcfe",
        "rd_exp",
        "tr_yoy",
        "or_yoy",
        "netprofit_yoy",
    )
)


def _disable_broken_local_proxy() -> None:
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        value = os.environ.get(name, "")
        if value.startswith(("http://127.0.0.1:", "https://127.0.0.1:")):
            os.environ.pop(name, None)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _first_number(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _number(row.get(key))
        if value is not None:
            return value
    return None


def _date_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = "".join(character for character in str(value) if character.isdigit())[:8]
    if len(text) != 8:
        return ""
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


def _period_key(value: Any) -> str:
    return "".join(character for character in str(value or "") if character.isdigit())[:8]


def _plain_code(ts_code: Any) -> str:
    return str(ts_code or "").split(".")[0].zfill(6)


def _ts_code(code: Any) -> str:
    plain = str(code or "").zfill(6)
    if plain.startswith(("4", "8", "92")):
        suffix = "BJ"
    elif plain.startswith(("5", "6", "9")):
        suffix = "SH"
    else:
        suffix = "SZ"
    return f"{plain}.{suffix}"


def _fetch(
    label: str,
    function: Callable[[], pd.DataFrame],
    retries: int = 2,
) -> pd.DataFrame:
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


def _recent_weekdays(today: date, lookback: int = 15) -> list[str]:
    days: list[str] = []
    for offset in range(lookback):
        candidate = today - timedelta(days=offset)
        if candidate.weekday() < 5:
            days.append(candidate.strftime("%Y%m%d"))
    return days


def _fetch_latest_daily_basic(pro: Any, today: date) -> tuple[pd.DataFrame, str]:
    for trade_date in _recent_weekdays(today):
        frame = _fetch(
            f"daily_basic({trade_date})",
            lambda d=trade_date: pro.daily_basic(
                trade_date=d,
                fields=DAILY_BASIC_FIELDS,
            ),
            retries=1,
        )
        if not frame.empty:
            return frame, trade_date
    return pd.DataFrame(), ""


def _merge_daily_basic(payload: dict[str, Any], frame: pd.DataFrame) -> int:
    quotes = payload.setdefault("quotes", {})
    fundamentals = payload.setdefault("fundamentals", {})
    allowed_codes = {str(item.get("code", "")) for item in payload.get("stocks") or []}
    merged = 0
    for row in frame.to_dict("records"):
        code = _plain_code(row.get("ts_code"))
        if code not in allowed_codes:
            continue
        quote = quotes.setdefault(code, {})
        price = _number(row.get("close"))
        pe = _first_number(row, "pe_ttm", "pe")
        pb = _number(row.get("pb"))
        total_mv = _number(row.get("total_mv"))
        if price is not None:
            quote["price"] = price
        if pe is not None:
            quote["pe"] = pe
        if pb is not None:
            quote["pb"] = pb
        if total_mv is not None:
            quote["market_cap"] = total_mv * 10_000
        quote.update(
            {
                "quote_source": "Tushare Pro/daily_basic",
                "trade_date": _date_text(row.get("trade_date")),
            }
        )

        dividend_yield = _number(row.get("dv_ttm"))
        if dividend_yield is not None:
            fundamental = fundamentals.setdefault(code, {})
            fundamental.update(
                {
                    "dividend_yield": dividend_yield,
                    "dividend_period": _date_text(row.get("trade_date")),
                    "dividend_source": "Tushare Pro/daily_basic",
                }
            )
        merged += 1
    return merged


def _merge_disclosures(payload: dict[str, Any], frame: pd.DataFrame) -> int:
    stock_index = {str(item.get("code", "")): item for item in payload.get("stocks") or []}
    merged = 0
    for row in frame.to_dict("records"):
        stock = stock_index.get(_plain_code(row.get("ts_code")))
        if not stock:
            continue
        pre_date = _date_text(row.get("pre_date"))
        actual_date = _date_text(row.get("actual_date"))
        if pre_date:
            stock["date"] = pre_date
        if actual_date:
            stock["actual_date"] = actual_date
            stock["date"] = actual_date
            stock["schedule_status"] = "已披露"
        stock.update(
            {
                "disclosure_source": "Tushare Pro/disclosure_date",
                "tushare_announcement_date": _date_text(row.get("ann_date")),
                "tushare_modify_date": _date_text(row.get("modify_date")),
            }
        )
        merged += 1
    return merged


def _financial_candidates(payload: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    reported = [
        stock
        for stock in payload.get("stocks") or []
        if stock.get("actual_date") or stock.get("source") == "正式中报"
    ]
    reported.sort(
        key=lambda stock: str(stock.get("actual_date") or stock.get("date") or ""),
        reverse=True,
    )
    return reported[: max(0, limit)]


def _select_latest_financial(frame: pd.DataFrame) -> dict[str, Any] | None:
    if frame.empty:
        return None
    rows = frame.to_dict("records")
    rows.sort(
        key=lambda row: (
            _period_key(row.get("end_date")),
            _period_key(row.get("ann_date")),
            str(row.get("update_flag") or ""),
        ),
        reverse=True,
    )
    return rows[0] if rows else None


def _merge_financial_indicator(
    metrics: dict[str, dict[str, Any]],
    code: str,
    frame: pd.DataFrame,
) -> bool:
    row = _select_latest_financial(frame)
    if not row:
        return False
    period = _period_key(row.get("end_date"))
    if not period:
        return False
    current = metrics.setdefault(code, {})
    if period < _period_key(current.get("financial_period")):
        return False

    values = {
        "eps": _number(row.get("eps")),
        "deducted_profit": _number(row.get("profit_dedt")),
        "deducted_profit_growth": _number(row.get("dt_netprofit_yoy")),
        "roe": _first_number(row, "roe_waa", "roe"),
        "gross_margin": _number(row.get("grossprofit_margin")),
        "net_profit_margin": _number(row.get("netprofit_margin")),
        "ocf_per_share": _number(row.get("ocfps")),
        "debt_ratio": _number(row.get("debt_to_assets")),
        "current_ratio": _number(row.get("current_ratio")),
        "quick_ratio": _number(row.get("quick_ratio")),
        "interest_bearing_debt": _number(row.get("interestdebt")),
        "net_debt": _number(row.get("netdebt")),
        "free_cashflow_firm": _number(row.get("fcff")),
        "free_cashflow_equity": _number(row.get("fcfe")),
        "research_expense": _number(row.get("rd_exp")),
        "financial_revenue_growth": _first_number(row, "tr_yoy", "or_yoy"),
        "financial_profit_growth": _number(row.get("netprofit_yoy")),
    }
    current.update({key: value for key, value in values.items() if value is not None})
    current.update(
        {
            "financial_period": _date_text(row.get("end_date")),
            "balance_period": _date_text(row.get("end_date")),
            "financial_announcement_date": _date_text(row.get("ann_date")),
            "financial_source": "Tushare Pro/fina_indicator",
        }
    )
    if values["ocf_per_share"] is not None:
        current["cashflow_period"] = _date_text(row.get("end_date"))
        current["cashflow_source"] = "Tushare Pro/fina_indicator"
    return True


def refresh(
    report_period: str = "20260630",
    financial_limit: int = 80,
    token: str | None = None,
    pro: Any | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    if not SNAPSHOT_PATH.exists():
        raise RuntimeError(f"Stock snapshot does not exist: {SNAPSHOT_PATH}")
    token = (token or os.environ.get("TUSHARE_TOKEN") or os.environ.get("TS_TOKEN") or "").strip()
    if not token and pro is None:
        raise RuntimeError("TUSHARE_TOKEN is not configured")

    _disable_broken_local_proxy()
    pro = pro or ts.pro_api(token)
    today = today or datetime.now(CHINA_TZ).date()
    payload = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    successful_sources: list[str] = []

    daily_basic, trade_date = _fetch_latest_daily_basic(pro, today)
    quote_count = _merge_daily_basic(payload, daily_basic) if not daily_basic.empty else 0
    if quote_count:
        successful_sources.append(f"daily_basic:{trade_date}")

    disclosures = _fetch(
        f"disclosure_date({report_period})",
        lambda: pro.disclosure_date(end_date=report_period, fields=DISCLOSURE_FIELDS),
    )
    disclosure_count = _merge_disclosures(payload, disclosures) if not disclosures.empty else 0
    if disclosure_count:
        successful_sources.append(f"disclosure_date:{report_period}")

    metrics = payload.setdefault("fundamentals", {})
    financial_count = 0
    candidates = _financial_candidates(payload, financial_limit)
    for index, stock in enumerate(candidates, start=1):
        code = str(stock.get("code", ""))
        ts_code = _ts_code(code)
        frame = _fetch(
            f"fina_indicator({ts_code})",
            lambda value=ts_code: pro.fina_indicator(
                ts_code=value,
                start_date="20250101",
                end_date="20261231",
                fields=FINANCIAL_FIELDS,
            ),
            retries=1,
        )
        if _merge_financial_indicator(metrics, code, frame):
            financial_count += 1
        if index < len(candidates):
            time.sleep(0.35)
    if financial_count:
        successful_sources.append(f"fina_indicator:{financial_count}")

    if not successful_sources:
        raise RuntimeError("Every Tushare Pro interface failed; the AKShare cache was retained")

    payload.update(
        {
            "data_provider": "Tushare Pro + AKShare兜底",
            "tushare_generated_at": datetime.now(CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "tushare_sources": successful_sources,
            "tushare_quote_count": quote_count,
            "tushare_disclosure_count": disclosure_count,
            "tushare_financial_count": sum(
                1
                for item in metrics.values()
                if str(item.get("financial_source", "")).startswith("Tushare Pro")
            ),
        }
    )
    temporary = SNAPSHOT_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary.replace(SNAPSHOT_PATH)
    print(
        "Tushare Pro cached: "
        f"{quote_count} quotes, {disclosure_count} disclosures, {financial_count} financial records"
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-period", default="20260630")
    parser.add_argument(
        "--optional",
        action="store_true",
        help="Keep deployment successful when Tushare is unavailable.",
    )
    parser.add_argument(
        "--financial-limit",
        type=int,
        default=int(os.environ.get("TUSHARE_FINANCIAL_LIMIT", "80")),
    )
    args = parser.parse_args()
    try:
        refresh(report_period=args.report_period, financial_limit=args.financial_limit)
    except Exception as exc:
        if not args.optional:
            raise
        print(f"Optional Tushare update skipped: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
