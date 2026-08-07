from __future__ import annotations

import asyncio
import json
import math
import os
import statistics
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse


ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT / "a_share_midreport_cloud" / "frontend"
FRONTEND_INDEX = FRONTEND_DIR / "index.html"
CALENDAR_INDEX = FRONTEND_DIR / "calendar.html"
SNAPSHOT_PATH = ROOT / "a_share_midreport_cloud" / "data" / "stock_snapshot.json"
FETCH_SCRIPT = ROOT / "fetch_2026_midreport_upcoming_sse.py"
CLOUD_BUILD_SCRIPT = ROOT / "build_cloud_frontend.py"
AKSHARE_SCRIPT = ROOT / "fetch_akshare_metrics.py"
TUSHARE_SCRIPT = ROOT / "fetch_tushare_metrics.py"

sys.path.insert(0, str(ROOT))
from update_report_server import (  # noqa: E402
    fetch_broker_forecast_html,
    fetch_business_analysis_html,
    fetch_dividend_history_html,
    fetch_financial_statements_html,
    resolve_dividend_source_url,
)


app = FastAPI(title="A股财报云 API")
update_lock = asyncio.Lock()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


_snapshot_cache: dict[str, Any] = {"mtime": None, "payload": None, "index": None}
SEARCH_ALIASES = {"mt": "600519", "gzmt": "600519"}


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _load_snapshot() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if not SNAPSHOT_PATH.exists():
        raise HTTPException(status_code=503, detail="股票数据快照尚未生成")
    mtime = SNAPSHOT_PATH.stat().st_mtime_ns
    if _snapshot_cache["mtime"] != mtime:
        payload = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        stocks = payload.get("stocks") or []
        stock_index = {str(item.get("code", "")): item for item in stocks}
        _snapshot_cache.update({"mtime": mtime, "payload": payload, "index": stock_index})
    return _snapshot_cache["payload"], _snapshot_cache["index"]


def _fetch_quote_snapshot() -> dict[str, dict[str, Any]]:
    payload, _ = _load_snapshot()
    return payload.get("quotes") or {}


def _fetch_fundamental_snapshot() -> dict[str, dict[str, Any]]:
    payload, _ = _load_snapshot()
    return payload.get("fundamentals") or {}


def _cashflow_status(fundamental: dict[str, Any]) -> str:
    operating_cashflow = _safe_float(fundamental.get("operating_cashflow"))
    if operating_cashflow is None:
        operating_cashflow = _safe_float(fundamental.get("ocf_per_share"))
    if operating_cashflow is None:
        return "暂无数据"
    if operating_cashflow > 0:
        return "经营现金流为正"
    if operating_cashflow < 0:
        return "经营现金流为负"
    return "经营现金流接近零"


def _risk_tags(stock: dict[str, Any], fundamental: dict[str, Any] | None = None) -> list[str]:
    fundamental = fundamental or {}
    tags: list[str] = []
    name = str(stock.get("name", ""))
    profit_growth = _safe_float(stock.get("profit_growth"))
    if "ST" in name.upper():
        tags.append("ST风险")
    if profit_growth is not None and profit_growth < 0:
        tags.append("利润下滑")
    debt_ratio = _safe_float(fundamental.get("debt_ratio"))
    if debt_ratio is not None and debt_ratio >= 70:
        tags.append("高负债")
    if _cashflow_status(fundamental) == "经营现金流为负":
        tags.append("现金流为负")
    roe = _safe_float(fundamental.get("roe"))
    if roe is not None and roe < 0:
        tags.append("ROE为负")
    if any(item in (stock.get("sectors") or []) for item in ("资源与材料", "农林牧渔", "交通运输")):
        tags.append("周期波动")
    if stock.get("source") == "待披露":
        tags.append("数据待披露")
    return tags[:3]


def _public_stock(
    stock: dict[str, Any],
    quote: dict[str, Any] | None = None,
    fundamental: dict[str, Any] | None = None,
) -> dict[str, Any]:
    quote = quote or {}
    fundamental = fundamental or {}
    result = dict(stock)
    revenue_growth = _safe_float(stock.get("revenue_growth"))
    if revenue_growth is None:
        revenue_growth = _safe_float(fundamental.get("financial_revenue_growth"))
    profit_growth = _safe_float(stock.get("profit_growth"))
    if profit_growth is None:
        profit_growth = _safe_float(fundamental.get("financial_profit_growth"))
    result.update(
        {
            "price": quote.get("price"),
            "change_pct": quote.get("change_pct"),
            "pe": quote.get("pe"),
            "pb": quote.get("pb"),
            "market_cap": quote.get("market_cap"),
            "market_cap_yi": (
                round(float(quote["market_cap"]) / 100_000_000, 2)
                if quote.get("market_cap") is not None
                else None
            ),
            "revenue_growth": revenue_growth,
            "profit_growth": profit_growth,
            "roe": _safe_float(fundamental.get("roe")),
            "gross_margin": _safe_float(fundamental.get("gross_margin")),
            "dividend_yield": _safe_float(fundamental.get("dividend_yield")),
            "debt_ratio": _safe_float(fundamental.get("debt_ratio")),
            "operating_cashflow": _safe_float(fundamental.get("operating_cashflow")),
            "ocf_per_share": _safe_float(fundamental.get("ocf_per_share")),
            "cashflow_status": _cashflow_status(fundamental),
            "financial_period": fundamental.get("financial_period") or "",
            "balance_period": fundamental.get("balance_period") or "",
            "cashflow_period": fundamental.get("cashflow_period") or "",
            "financial_source": fundamental.get("financial_source") or "",
            "balance_source": fundamental.get("balance_source") or "",
            "cashflow_source": fundamental.get("cashflow_source") or "",
            "dividend_source": fundamental.get("dividend_source") or "",
            "ak_industry": fundamental.get("ak_industry") or "",
            "financial_revenue_growth": _safe_float(fundamental.get("financial_revenue_growth")),
            "financial_profit_growth": _safe_float(fundamental.get("financial_profit_growth")),
            "financial_revenue": _safe_float(fundamental.get("revenue")),
            "financial_net_profit": _safe_float(fundamental.get("net_profit")),
            "dividend_period": fundamental.get("dividend_period") or "",
            "risk_tags": _risk_tags(stock, fundamental),
        }
    )
    return result


def _matches_query(stock: dict[str, Any], query: str) -> bool:
    normalized = query.strip().lower().replace(" ", "")
    if not normalized:
        return True
    return any(
        normalized in str(value or "").lower().replace(" ", "")
        for value in (stock.get("code"), stock.get("name"), stock.get("initials"))
    )


def _public_stocks_for_codes(codes: list[str]) -> list[dict[str, Any]]:
    _, stock_index = _load_snapshot()
    quotes = _fetch_quote_snapshot()
    fundamentals = _fetch_fundamental_snapshot()
    return [
        _public_stock(stock_index[code], quotes.get(code), fundamentals.get(code))
        for code in codes
        if code in stock_index
    ]


def _median_metric(
    items: list[dict[str, Any]], key: str, *, positive_only: bool = False
) -> float | None:
    values = [
        value
        for item in items
        if (value := _safe_float(item.get(key))) is not None
        and (not positive_only or value > 0)
    ]
    return round(statistics.median(values), 2) if values else None


def _industry_summary(name: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "name": name,
        "count": len(items),
        "median_pe": _median_metric(items, "pe", positive_only=True),
        "median_pb": _median_metric(items, "pb", positive_only=True),
        "median_roe": _median_metric(items, "roe"),
        "median_revenue_growth": _median_metric(items, "revenue_growth"),
        "median_profit_growth": _median_metric(items, "profit_growth"),
        "median_dividend_yield": _median_metric(items, "dividend_yield"),
        "median_debt_ratio": _median_metric(items, "debt_ratio"),
    }


def _frontend() -> FileResponse:
    if not FRONTEND_INDEX.exists():
        raise HTTPException(status_code=500, detail="frontend/index.html has not been built")
    return FileResponse(FRONTEND_INDEX, media_type="text/html; charset=utf-8")


@app.get("/")
def index() -> FileResponse:
    return _frontend()


@app.get("/screener")
def screener_page() -> FileResponse:
    return _frontend()


@app.get("/stock/{code}")
def stock_page(code: str) -> FileResponse:
    return _frontend()


@app.get("/industry/{name}")
def industry_page(name: str) -> FileResponse:
    return _frontend()


@app.get("/watchlist")
def watchlist_page() -> FileResponse:
    return _frontend()


@app.get("/compare")
def compare_page() -> FileResponse:
    return _frontend()


@app.get("/data-guide")
def data_guide_page() -> FileResponse:
    return _frontend()


@app.get("/calendar")
def calendar_page() -> FileResponse:
    if not CALENDAR_INDEX.exists():
        raise HTTPException(status_code=404, detail="中报日历尚未生成")
    return FileResponse(CALENDAR_INDEX, media_type="text/html; charset=utf-8")


@app.get("/api/health")
def health() -> dict[str, object]:
    payload, _ = _load_snapshot()
    return {
        "ok": True,
        "frontend_built": FRONTEND_INDEX.exists(),
        "stock_count": payload.get("count", 0),
        "generated_at": payload.get("generated_at", ""),
        "fundamental_count": len(payload.get("fundamentals") or {}),
        "data_provider": payload.get("data_provider", "AKShare"),
        "akshare_generated_at": payload.get("akshare_generated_at", ""),
        "tushare_configured": bool(
            os.environ.get("TUSHARE_TOKEN") or os.environ.get("TS_TOKEN")
        ),
        "tushare_generated_at": payload.get("tushare_generated_at", ""),
        "tushare_quote_count": payload.get("tushare_quote_count", 0),
        "tushare_disclosure_count": payload.get("tushare_disclosure_count", 0),
        "tushare_financial_count": payload.get("tushare_financial_count", 0),
    }


@app.get("/api/home")
def home(response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "public, max-age=120"
    payload, _ = _load_snapshot()
    stocks = payload.get("stocks") or []
    quotes = _fetch_quote_snapshot()
    fundamentals = _fetch_fundamental_snapshot()
    reported = [
        item
        for item in stocks
        if item.get("actual_date") or item.get("source") == "正式中报"
    ]
    latest_candidates = reported or [item for item in stocks if item.get("source") != "待披露"]
    latest = sorted(
        latest_candidates,
        key=lambda item: (
            str(item.get("actual_date") or item.get("date") or ""),
            item.get("source") != "待披露",
        ),
        reverse=True,
    )[:8]
    sectors = Counter(
        sector
        for item in stocks
        for sector in (item.get("sectors") or [])
        if sector and sector != "综合"
    )
    return {
        "ok": True,
        "report_period": payload.get("report_period", "2026中报"),
        "generated_at": payload.get("generated_at", ""),
        "data_provider": payload.get("data_provider", "AKShare"),
        "tushare_generated_at": payload.get("tushare_generated_at", ""),
        "stock_count": len(stocks),
        "latest": [
            _public_stock(
                item,
                quotes.get(str(item.get("code"))),
                fundamentals.get(str(item.get("code"))),
            )
            for item in latest
        ],
        "industries": [{"name": name, "count": count} for name, count in sectors.most_common(12)],
    }


@app.get("/api/search")
def search_stocks(
    q: str = Query(min_length=1, max_length=40),
    limit: int = Query(default=10, ge=1, le=30),
) -> dict[str, Any]:
    _, stock_index = _load_snapshot()
    normalized = q.strip().lower()
    alias_code = SEARCH_ALIASES.get(normalized)
    matches = [item for item in stock_index.values() if _matches_query(item, q)]
    matches.sort(
        key=lambda item: (
            str(item.get("code")) != alias_code,
            str(item.get("code")) != normalized,
            str(item.get("name")) != q.strip(),
            str(item.get("initials", "")) != normalized,
            not str(item.get("initials", "")).endswith(normalized),
            not str(item.get("initials", "")).startswith(normalized),
            str(item.get("code")),
        )
    )
    return {
        "ok": True,
        "items": [
            {
                "code": item.get("code"),
                "name": item.get("name"),
                "market": item.get("market"),
                "date": item.get("date"),
                "sectors": item.get("sectors") or [],
            }
            for item in matches[:limit]
        ],
    }


@app.get("/api/screener")
def screen_stocks(
    response: Response,
    q: str = "",
    sector: str = "",
    market: str = "",
    pe_min: float | None = None,
    pe_max: float | None = None,
    pb_max: float | None = None,
    market_cap_min: float | None = None,
    market_cap_max: float | None = None,
    revenue_growth_min: float | None = None,
    profit_growth_min: float | None = None,
    deduct_growth_min: float | None = None,
    roe_min: float | None = None,
    dividend_yield_min: float | None = None,
    debt_ratio_max: float | None = None,
    cashflow: str = "",
    source: str = "",
    exclude_st: bool = True,
    sort: str = "profit_growth",
    order: str = "desc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=10, le=100),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    _, stock_index = _load_snapshot()
    quotes = _fetch_quote_snapshot()
    fundamentals = _fetch_fundamental_snapshot()
    results: list[dict[str, Any]] = []

    for stock in stock_index.values():
        if q and not _matches_query(stock, q):
            continue
        if sector and sector not in (stock.get("sectors") or []):
            continue
        if market and stock.get("market") != market:
            continue
        if source and stock.get("source") != source:
            continue
        if exclude_st and "ST" in str(stock.get("name", "")).upper():
            continue

        quote = quotes.get(str(stock.get("code")), {})
        fundamental = fundamentals.get(str(stock.get("code")), {})
        item = _public_stock(stock, quote, fundamental)
        pe = _safe_float(quote.get("pe"))
        pb = _safe_float(quote.get("pb"))
        market_cap_yi = (
            _safe_float(quote.get("market_cap")) / 100_000_000
            if _safe_float(quote.get("market_cap")) is not None
            else None
        )
        revenue_growth = _safe_float(item.get("revenue_growth"))
        profit_growth = _safe_float(item.get("profit_growth"))
        deduct_growth = _safe_float(stock.get("deduct_growth"))
        roe = _safe_float(item.get("roe"))
        dividend_yield = _safe_float(item.get("dividend_yield"))
        debt_ratio = _safe_float(item.get("debt_ratio"))

        if pe_min is not None and (pe is None or pe < pe_min):
            continue
        if pe_max is not None and (pe is None or pe <= 0 or pe > pe_max):
            continue
        if pb_max is not None and (pb is None or pb <= 0 or pb > pb_max):
            continue
        if market_cap_min is not None and (market_cap_yi is None or market_cap_yi < market_cap_min):
            continue
        if market_cap_max is not None and (market_cap_yi is None or market_cap_yi > market_cap_max):
            continue
        if revenue_growth_min is not None and (revenue_growth is None or revenue_growth < revenue_growth_min):
            continue
        if profit_growth_min is not None and (profit_growth is None or profit_growth < profit_growth_min):
            continue
        if deduct_growth_min is not None and (deduct_growth is None or deduct_growth < deduct_growth_min):
            continue
        if roe_min is not None and (roe is None or roe < roe_min):
            continue
        if dividend_yield_min is not None and (
            dividend_yield is None or dividend_yield < dividend_yield_min
        ):
            continue
        if debt_ratio_max is not None and (debt_ratio is None or debt_ratio > debt_ratio_max):
            continue
        if cashflow == "positive" and item.get("cashflow_status") != "经营现金流为正":
            continue
        if cashflow == "negative" and item.get("cashflow_status") != "经营现金流为负":
            continue
        results.append(item)

    sort_fields = {
        "code": "code",
        "name": "name",
        "date": "date",
        "market_cap": "market_cap_yi",
        "pe": "pe",
        "pb": "pb",
        "revenue_growth": "revenue_growth",
        "profit_growth": "profit_growth",
        "deduct_growth": "deduct_growth",
        "roe": "roe",
        "dividend_yield": "dividend_yield",
        "debt_ratio": "debt_ratio",
    }
    sort_field = sort_fields.get(sort, "profit_growth")
    reverse = order != "asc"
    available = [item for item in results if item.get(sort_field) is not None]
    unavailable = [item for item in results if item.get(sort_field) is None]
    available.sort(key=lambda item: item.get(sort_field), reverse=reverse)
    results = available + unavailable

    total = len(results)
    pages = max(1, math.ceil(total / page_size))
    page = min(page, pages)
    start = (page - 1) * page_size
    return {
        "ok": True,
        "items": results[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "sort": sort,
        "order": order,
    }


@app.get("/api/compare")
def compare_stocks(
    response: Response,
    codes: str = Query(min_length=1, max_length=800),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    requested: list[str] = []
    for value in codes.split(","):
        code = value.strip()
        if code and code not in requested:
            requested.append(code)
    if len(requested) > 100:
        raise HTTPException(status_code=400, detail="一次最多读取100只股票")
    items = _public_stocks_for_codes(requested)
    return {"ok": True, "items": items, "requested": requested}


@app.get("/api/industries")
def industry_summaries(response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "public, max-age=300"
    _, stock_index = _load_snapshot()
    quotes = _fetch_quote_snapshot()
    fundamentals = _fetch_fundamental_snapshot()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for stock in stock_index.values():
        code = str(stock.get("code", ""))
        item = _public_stock(stock, quotes.get(code), fundamentals.get(code))
        for sector in stock.get("sectors") or []:
            if sector and sector != "综合":
                grouped.setdefault(str(sector), []).append(item)
    summaries = [_industry_summary(name, items) for name, items in grouped.items()]
    summaries.sort(key=lambda item: (-int(item["count"]), str(item["name"])))
    return {"ok": True, "items": summaries}


@app.get("/api/industry")
def industry_detail(
    response: Response,
    name: str = Query(min_length=1, max_length=30),
    limit: int = Query(default=50, ge=10, le=100),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "public, max-age=180"
    _, stock_index = _load_snapshot()
    quotes = _fetch_quote_snapshot()
    fundamentals = _fetch_fundamental_snapshot()
    items = []
    for stock in stock_index.values():
        if name not in (stock.get("sectors") or []):
            continue
        code = str(stock.get("code", ""))
        items.append(_public_stock(stock, quotes.get(code), fundamentals.get(code)))
    if not items:
        raise HTTPException(status_code=404, detail="未找到该行业")
    summary = _industry_summary(name, items)
    available = [item for item in items if item.get("profit_growth") is not None]
    unavailable = [item for item in items if item.get("profit_growth") is None]
    available.sort(key=lambda item: item.get("profit_growth"), reverse=True)
    unavailable.sort(key=lambda item: str(item.get("code", "")))
    return {
        "ok": True,
        "summary": summary,
        "items": (available + unavailable)[:limit],
        "total": len(items),
    }


@app.get("/api/stock/{code}")
def stock_summary(code: str, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    _, stock_index = _load_snapshot()
    stock = stock_index.get(code)
    if not stock:
        raise HTTPException(status_code=404, detail="未找到该股票")
    quotes = _fetch_quote_snapshot()
    fundamentals = _fetch_fundamental_snapshot()
    item = _public_stock(stock, quotes.get(code), fundamentals.get(code))
    primary_sector = (stock.get("sectors") or ["综合"])[0]
    peers = [
        other
        for other in stock_index.values()
        if other.get("code") != code and primary_sector in (other.get("sectors") or [])
    ]
    peers.sort(
        key=lambda other: _safe_float(other.get("profit_growth")) or float("-inf"),
        reverse=True,
    )
    return {
        "ok": True,
        "stock": item,
        "peers": [
            _public_stock(
                peer,
                quotes.get(str(peer.get("code", ""))),
                fundamentals.get(str(peer.get("code", ""))),
            )
            for peer in peers[:6]
        ],
    }


@app.get("/api/broker")
def broker(code: str, response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    try:
        return {"ok": True, "html": fetch_broker_forecast_html(code)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/financials")
def financials(code: str, response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    try:
        return {"ok": True, "html": fetch_financial_statements_html(code)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/business")
def business(code: str, response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    try:
        return {"ok": True, "html": fetch_business_analysis_html(code)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/dividends")
def dividends(code: str, response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    try:
        return {"ok": True, "html": fetch_dividend_history_html(code)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/dividend-source")
def dividend_source(code: str, date: str, kind: str) -> RedirectResponse:
    try:
        return RedirectResponse(resolve_dividend_source_url(code, date, kind), status_code=302)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/update")
async def update() -> dict[str, object]:
    if update_lock.locked():
        raise HTTPException(status_code=409, detail="已有一次更新正在运行，请稍后再试")

    async with update_lock:
        fetch_result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, str(FETCH_SCRIPT)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=900,
        )
        if fetch_result.returncode != 0:
            error = fetch_result.stderr[-3000:] or fetch_result.stdout[-3000:] or "fetch script failed"
            raise HTTPException(status_code=500, detail=error)

        build_result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, str(CLOUD_BUILD_SCRIPT), "--force"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=240,
        )
        if build_result.returncode != 0:
            error = build_result.stderr[-3000:] or build_result.stdout[-3000:] or "cloud build failed"
            raise HTTPException(status_code=500, detail=error)

        akshare_result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, str(AKSHARE_SCRIPT)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=900,
        )
        akshare_warning = ""
        if akshare_result.returncode != 0:
            akshare_warning = (
                akshare_result.stderr[-2000:]
                or akshare_result.stdout[-2000:]
                or "AKShare update failed; previous fundamentals were retained"
            )

        tushare_output = ""
        tushare_warning = ""
        if os.environ.get("TUSHARE_TOKEN") or os.environ.get("TS_TOKEN"):
            tushare_result = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, str(TUSHARE_SCRIPT)],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=900,
            )
            tushare_output = tushare_result.stdout[-2000:]
            if tushare_result.returncode != 0:
                tushare_warning = (
                    tushare_result.stderr[-2000:]
                    or tushare_output
                    or "Tushare Pro update failed; the AKShare fallback was retained"
                )
        else:
            tushare_warning = "TUSHARE_TOKEN 未配置，本次继续使用 AKShare 数据"

        _snapshot_cache.update({"mtime": None, "payload": None, "index": None})
        warnings = [warning for warning in (akshare_warning, tushare_warning) if warning]
        return {
            "ok": True,
            "message": "更新完成",
            "fetch_output": fetch_result.stdout[-2000:],
            "build_output": build_result.stdout[-2000:],
            "akshare_output": akshare_result.stdout[-2000:],
            "tushare_output": tushare_output,
            "warning": "\n".join(warnings),
        }
