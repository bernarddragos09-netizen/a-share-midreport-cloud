#!/usr/bin/env python3
"""Fetch upcoming 2026 interim-report appointment dates from SSE.

This script focuses on the upcoming 2026 half-year/interim report schedule.
Source: Shanghai Stock Exchange periodic report appointment page.
"""

from __future__ import annotations

import csv
import calendar
import html
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib import parse, request


SSE_URL = "https://query.sse.com.cn/commonSoaQuery.do"
EASTMONEY_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EASTMONEY_QUOTE_URL = "https://push2.eastmoney.com/api/qt/clist/get"
EASTMONEY_QUOTE_BATCH_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
REFERER = "https://www.sse.com.cn/disclosure/listedinfo/periodic/"
OUTPUT_DIR = Path("a_share_midreport_2026_upcoming_sse")
CHINA_TZ = timezone(timedelta(hours=8))

SECTOR_RULES = [
    ("金融", ["银行", "保险", "证券", "多元金融", "期货", "信托", "金融"]),
    ("科技", ["半导体", "软件", "互联网", "通信", "电子", "芯片", "人工智能", "大数据", "云计算", "信息安全", "算力", "光通信"]),
    ("先进制造", ["机械", "设备", "工业母机", "自动化", "机器人", "仪器", "专用设备", "通用设备", "电机", "激光", "工业"]),
    ("汽车", ["汽车", "零部件", "新能源车", "无人驾驶", "摩托车", "交运设备"]),
    ("新能源与电力", ["电力", "新能源", "光伏", "风电", "储能", "电池", "锂电", "氢能源", "充电桩", "智能电网"]),
    ("资源与材料", ["煤炭", "有色", "钢铁", "化工", "材料", "稀土", "矿", "石油", "金属", "玻璃", "水泥", "塑料"]),
    ("地产与基建", ["房地产", "建筑", "建材", "工程", "基建", "装修", "园林", "物业"]),
    ("交通运输", ["交通", "运输", "物流", "港口", "航运", "机场", "铁路", "公路", "航空"]),
    ("公用事业", ["环保", "水务", "燃气", "供水", "供热", "公用事业"]),
    ("医药健康", ["医药", "医疗", "生物", "制药", "疫苗", "器械", "中药", "CXO", "健康"]),
    ("消费", ["食品", "饮料", "白酒", "家电", "服装", "零售", "旅游", "酒店", "餐饮", "美容", "化妆品", "家居"]),
    ("农林牧渔", ["农业", "种植", "养殖", "农牧", "渔", "林业", "饲料", "种业"]),
    ("传媒文娱", ["传媒", "游戏", "影视", "出版", "广告", "文化", "教育", "文娱"]),
    ("国防军工", ["军工", "航天", "航空", "船舶", "卫星", "北斗", "兵装", "国防"]),
]

FALLBACK_SECTORS = ["综合"]

PINYIN_INITIAL_RANGES = [
    (-20319, -20284, "a"),
    (-20283, -19776, "b"),
    (-19775, -19219, "c"),
    (-19218, -18711, "d"),
    (-18710, -18527, "e"),
    (-18526, -18240, "f"),
    (-18239, -17923, "g"),
    (-17922, -17418, "h"),
    (-17417, -16475, "j"),
    (-16474, -16213, "k"),
    (-16212, -15641, "l"),
    (-15640, -15166, "m"),
    (-15165, -14923, "n"),
    (-14922, -14915, "o"),
    (-14914, -14631, "p"),
    (-14630, -14150, "q"),
    (-14149, -14091, "r"),
    (-14090, -13319, "s"),
    (-13318, -12839, "t"),
    (-12838, -12557, "w"),
    (-12556, -11848, "x"),
    (-11847, -11056, "y"),
    (-11055, -10247, "z"),
]


def fetch_json(params: dict[str, Any], timeout: int = 25, retries: int = 3) -> dict[str, Any]:
    url = SSE_URL + "?" + parse.urlencode(params)
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        req = request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": REFERER,
                "Accept": "application/json,text/javascript,*/*;q=0.01",
            },
        )
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            print(f"Request failed ({attempt}/{retries}): {exc}", file=sys.stderr)
            if attempt < retries:
                time.sleep(1.5 * attempt)
    raise RuntimeError("SSE request failed after retries") from last_error


def fetch_eastmoney_pages(
    report_name: str,
    filter_expr: str,
    sort_columns: str,
    sort_types: str,
    page_size: int = 500,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page_no = 1
    pages = 1

    while page_no <= pages:
        params = {
            "reportName": report_name,
            "columns": "ALL",
            "filter": filter_expr,
            "pageNumber": page_no,
            "pageSize": page_size,
            "sortColumns": sort_columns,
            "sortTypes": sort_types,
        }
        url = EASTMONEY_URL + "?" + parse.urlencode(params)
        req = request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://data.eastmoney.com/bbsj/202606/yjbb.html",
            },
        )
        with request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        result = data.get("result") or {}
        page_rows = result.get("data") or []
        pages = int(result.get("pages") or 0)
        if not page_rows:
            break
        rows.extend(page_rows)
        print(f"Fetched Eastmoney {report_name} page {page_no}/{pages}: {len(page_rows)} rows")
        page_no += 1

    return rows


def classify_sectors(industry: str, concepts: str, stock_name: str) -> list[str]:
    text = "|".join([industry or "", concepts or "", stock_name or ""])
    sectors: list[str] = []
    for sector, keywords in SECTOR_RULES:
        if any(keyword in text for keyword in keywords):
            sectors.append(sector)
        if len(sectors) >= 3:
            break
    if not sectors:
        sectors.extend(FALLBACK_SECTORS)
    while len(sectors) < 2:
        if "综合" not in sectors:
            sectors.append("综合")
        else:
            break
    return sectors[:3]


def chinese_initials(text: str) -> str:
    initials = []
    for char in text:
        if char.isascii():
            if char.isalnum():
                initials.append(char.lower())
            continue
        try:
            gbk = char.encode("gbk")
        except UnicodeEncodeError:
            continue
        if len(gbk) < 2:
            continue
        code = gbk[0] * 256 + gbk[1] - 65536
        for start, end, initial in PINYIN_INITIAL_RANGES:
            if start <= code <= end:
                initials.append(initial)
                break
    return "".join(initials)


def fetch_sector_lookup(stock_codes: list[str]) -> dict[str, list[str]]:
    lookup: dict[str, list[str]] = {}
    unique_codes = sorted({code for code in stock_codes if code})
    batch_size = 80

    for start in range(0, len(unique_codes), batch_size):
        batch = unique_codes[start : start + batch_size]
        secids = ",".join(f"1.{code}" for code in batch)
        params = {
            "fltt": 2,
            "invt": 2,
            "fields": "f12,f14,f100,f103",
            "secids": secids,
        }
        url = EASTMONEY_QUOTE_BATCH_URL + "?" + parse.urlencode(params)
        req = request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
        )
        data = None
        for attempt in range(1, 4):
            try:
                with request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                break
            except Exception as exc:
                print(f"Sector request failed ({attempt}/3): {exc}", file=sys.stderr)
                if attempt < 3:
                    time.sleep(1.5 * attempt)
        if not data:
            continue
        payload = data.get("data") or {}
        rows = payload.get("diff") or []
        for row in rows:
            code = str(row.get("f12", "") or "").strip()
            if not code:
                continue
            lookup[code] = classify_sectors(
                str(row.get("f100", "") or ""),
                str(row.get("f103", "") or ""),
                str(row.get("f14", "") or ""),
            )
        print(f"Fetched Eastmoney sector batch {start // batch_size + 1}: {len(rows)} rows")
    return lookup


def final_appointment_date(row: dict[str, Any]) -> str:
    for key in ("actualDate", "publishDate3", "publishDate2", "publishDate1", "publishDate0"):
        value = str(row.get(key, "") or "").strip()
        if value:
            return value
    return ""


def fetch_sse_2026_midreport(page_size: int = 1000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page_no = 1
    page_count = None
    total = None

    while True:
        params = {
            "sqlId": "SSE_SZSGG_DQBGYYQK_CAST_NEW",
            "isPagination": "true",
            "pageHelp.pageSize": str(page_size),
            "pageHelp.pageNo": str(page_no),
            "pageHelp.beginPage": str(page_no),
            "pageHelp.cacheSize": "1",
            "pageHelp.endPage": str(page_no),
            "bulletintype": "L012",
            "publishYear": "2026",
            "companyCode": "",
            "startTime": "",
            "order": "publishDate0|asc",
        }
        data = fetch_json(params)
        page_help = data.get("pageHelp") or {}
        page_rows = data.get("result") or page_help.get("data") or []
        rows.extend(page_rows)
        page_count = int(page_help.get("pageCount") or page_count or 1)
        total = int(page_help.get("total") or total or len(rows))
        print(f"Fetched SSE page {page_no}/{page_count}: {len(page_rows)} rows, total {len(rows)}")

        if page_no >= page_count or len(rows) >= total:
            return rows[:total]
        page_no += 1


def normalized_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    detail_rows = []
    for row in rows:
        detail_rows.append(
            {
                "stock_code": str(row.get("companyCode", "") or "").strip(),
                "stock_name": str(row.get("companyAbbr", "") or "").strip(),
                "report_type": "半年报（中报）",
                "report_year": str(row.get("publishYear", "") or "").strip(),
                "first_appointment_date": str(row.get("publishDate0", "") or "").strip(),
                "first_change_date": str(row.get("publishDate1", "") or "").strip(),
                "second_change_date": str(row.get("publishDate2", "") or "").strip(),
                "third_change_date": str(row.get("publishDate3", "") or "").strip(),
                "actual_disclosure_date": str(row.get("actualDate", "") or "").strip(),
                "stat_date": final_appointment_date(row),
            }
        )
    return detail_rows


def amount_to_yi(value: Any) -> str:
    if value in (None, ""):
        return "待披露"
    try:
        return f"{float(value) / 100000000:.2f} 亿"
    except (TypeError, ValueError):
        return str(value)


def amount_range_to_yi(lower: Any, upper: Any) -> str:
    if lower in (None, "") and upper in (None, ""):
        return "待披露"
    if lower not in (None, "") and upper not in (None, "") and lower != upper:
        return f"{float(lower) / 100000000:.2f} 亿 - {float(upper) / 100000000:.2f} 亿"
    value = lower if lower not in (None, "") else upper
    return amount_to_yi(value)


def pct_text(value: Any) -> str:
    if value in (None, ""):
        return "待披露"
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return str(value)


def pct_range_text(lower: Any, upper: Any, middle: Any = None) -> str:
    if lower not in (None, "") and upper not in (None, "") and lower != upper:
        return f"{float(lower):.2f}% - {float(upper):.2f}%"
    if middle not in (None, ""):
        return pct_text(middle)
    value = lower if lower not in (None, "") else upper
    return pct_text(value)


def growth_class(*values: Any) -> str:
    nums = []
    for value in values:
        if value in (None, ""):
            continue
        try:
            nums.append(float(value))
        except (TypeError, ValueError):
            pass
    if not nums:
        return "tier-unknown"
    avg = sum(nums) / len(nums)
    if avg >= 50:
        return "tier-boom"
    if avg >= 30:
        return "tier-strong-up"
    if avg >= 15:
        return "tier-mid-up"
    if avg >= -5:
        return "tier-flat"
    if avg >= -15:
        return "tier-small-down"
    if avg >= -30:
        return "tier-big-down"
    return "tier-crash"


def fetch_financial_lookup() -> dict[str, dict[str, Any]]:
    formal_rows = fetch_eastmoney_pages(
        "RPT_LICO_FN_CPD",
        "(REPORTDATE='2026-06-30')",
        "UPDATE_DATE",
        "-1",
    )
    predict_rows = fetch_eastmoney_pages(
        "RPT_PUBLIC_OP_NEWPREDICT",
        "(REPORT_DATE='2026-06-30')",
        "NOTICE_DATE,SECURITY_CODE",
        "-1,-1",
    )

    lookup: dict[str, dict[str, Any]] = {}
    for row in formal_rows:
        code = str(row.get("SECURITY_CODE", "") or "").strip()
        if not code:
            continue
        lookup.setdefault(code, {})["formal"] = row

    for row in predict_rows:
        code = str(row.get("SECURITY_CODE", "") or "").strip()
        finance_code = str(row.get("PREDICT_FINANCE_CODE", "") or "").strip()
        if not code or finance_code not in {"004", "005", "006"}:
            continue
        lookup.setdefault(code, {}).setdefault("predict", {})[finance_code] = row

    return lookup


def fetch_q1_deduct_profit_lookup() -> dict[str, dict[str, Any]]:
    rows = fetch_eastmoney_pages(
        "RPT_DMSK_FN_INCOME",
        "(REPORT_DATE='2026-03-31')",
        "NOTICE_DATE,SECURITY_CODE",
        "-1,1",
    )
    lookup: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = str(row.get("SECURITY_CODE", "") or "").strip()
        if not code:
            continue
        lookup[code] = row
    return lookup


def forecast_notice_date(row: dict[str, Any]) -> str:
    value = str(row.get("NOTICE_DATE", "") or "").strip()
    return value[:10]


def forecast_growth_value(row: dict[str, Any]) -> float | None:
    return numeric_average(row.get("ADD_AMP_LOWER"), row.get("ADD_AMP_UPPER"), row.get("INCREASE_JZ"))


def is_key_performance_forecast(row: dict[str, Any]) -> bool:
    predict_type = str(row.get("PREDICT_TYPE", "") or "").strip()
    if predict_type in {"扭亏", "首亏", "续亏"}:
        return True
    growth = forecast_growth_value(row)
    return growth is not None and abs(growth) >= 50


def fetch_key_performance_forecasts(cutoff_date: str = "2026-07-15") -> list[dict[str, str]]:
    rows = fetch_eastmoney_pages(
        "RPT_PUBLIC_OP_NEWPREDICT",
        "(REPORT_DATE='2026-06-30')",
        "NOTICE_DATE,SECURITY_CODE",
        "-1,-1",
    )
    q1_lookup = fetch_q1_deduct_profit_lookup()
    by_code: dict[str, dict[str, Any]] = {}
    priority = {"005": 0, "004": 1, "002": 2, "006": 3}

    for row in rows:
        code = str(row.get("SECURITY_CODE", "") or "").strip()
        notice_date = forecast_notice_date(row)
        finance_code = str(row.get("PREDICT_FINANCE_CODE", "") or "").strip()
        if not code or not notice_date or notice_date > cutoff_date:
            continue
        if not is_key_performance_forecast(row):
            continue
        current = by_code.get(code)
        if current is None or priority.get(finance_code, 99) < priority.get(str(current.get("PREDICT_FINANCE_CODE", "")), 99):
            by_code[code] = row

    forecasts: list[dict[str, str]] = []
    for row in by_code.values():
        code = str(row.get("SECURITY_CODE", "") or "").strip()
        finance_code = str(row.get("PREDICT_FINANCE_CODE", "") or "").strip()
        q1_row = q1_lookup.get(code, {})
        growth = forecast_growth_value(row)
        forecasts.append(
            {
                "stock_code": code,
                "stock_name": str(row.get("SECURITY_NAME_ABBR", "") or "").strip(),
                "notice_date": forecast_notice_date(row),
                "predict_type": str(row.get("PREDICT_TYPE", "") or "").strip() or "业绩预告",
                "forecast_basis": "扣非归母净利润" if finance_code == "005" else "归母净利润口径",
                "finance": str(row.get("PREDICT_FINANCE", "") or "").strip(),
                "amount": amount_range_to_yi(row.get("PREDICT_AMT_LOWER"), row.get("PREDICT_AMT_UPPER")),
                "growth": arrow_pct_text(growth),
                "growth_class": growth_class(row.get("ADD_AMP_LOWER"), row.get("ADD_AMP_UPPER"), row.get("INCREASE_JZ")),
                "q1_deduct_profit": amount_to_yi(q1_row.get("DEDUCT_PARENT_NETPROFIT")),
                "q1_deduct_yoy": pct_text(q1_row.get("DPN_RATIO")),
                "q1_deduct_class": growth_class(q1_row.get("DPN_RATIO")),
                "content": str(row.get("PREDICT_CONTENT", "") or "").strip(),
            }
        )
    forecasts.sort(key=lambda item: (item["notice_date"], item["stock_code"]))
    return forecasts


def metric_html(label: str, amount: str, growth: str, klass: str, source: str) -> str:
    return (
        '<div class="metric">'
        f'<div class="metric-label">{html.escape(label)}</div>'
        f'<div class="metric-value">{html.escape(amount)}</div>'
        f'<div class="metric-growth {klass}">{html.escape(growth)}</div>'
        f'<div class="metric-source">{html.escape(source)}</div>'
        "</div>"
    )


def finance_panel_html(code: str, financial_lookup: dict[str, dict[str, Any]]) -> str:
    info = financial_lookup.get(code, {})
    formal = info.get("formal")
    predicts = info.get("predict", {})

    if formal:
        revenue = metric_html(
            "营业总收入",
            amount_to_yi(formal.get("TOTAL_OPERATE_INCOME")),
            pct_text(formal.get("YSTZ")),
            growth_class(formal.get("YSTZ")),
            "正式中报",
        )
        parent_profit = metric_html(
            "归母净利润",
            amount_to_yi(formal.get("PARENT_NETPROFIT")),
            pct_text(formal.get("SJLTZ")),
            growth_class(formal.get("SJLTZ")),
            "正式中报",
        )
        deduct_profit = metric_html(
            "扣非归母净利润",
            amount_to_yi(formal.get("DEDUCT_PARENT_NETPROFIT")),
            pct_text(formal.get("DEDUCT_PARENT_NETPROFIT_YOY")),
            growth_class(formal.get("DEDUCT_PARENT_NETPROFIT_YOY")),
            "正式中报",
        )
    else:
        pred_revenue = predicts.get("006", {})
        pred_parent = predicts.get("004", {})
        pred_deduct = predicts.get("005", {})
        revenue = metric_html(
            "营业总收入",
            amount_range_to_yi(pred_revenue.get("PREDICT_AMT_LOWER"), pred_revenue.get("PREDICT_AMT_UPPER")),
            pct_range_text(pred_revenue.get("ADD_AMP_LOWER"), pred_revenue.get("ADD_AMP_UPPER"), pred_revenue.get("INCREASE_JZ")),
            growth_class(pred_revenue.get("ADD_AMP_LOWER"), pred_revenue.get("ADD_AMP_UPPER"), pred_revenue.get("INCREASE_JZ")),
            "业绩预告" if pred_revenue else "待披露",
        )
        parent_profit = metric_html(
            "归母净利润",
            amount_range_to_yi(pred_parent.get("PREDICT_AMT_LOWER"), pred_parent.get("PREDICT_AMT_UPPER")),
            pct_range_text(pred_parent.get("ADD_AMP_LOWER"), pred_parent.get("ADD_AMP_UPPER"), pred_parent.get("INCREASE_JZ")),
            growth_class(pred_parent.get("ADD_AMP_LOWER"), pred_parent.get("ADD_AMP_UPPER"), pred_parent.get("INCREASE_JZ")),
            "业绩预告" if pred_parent else "待披露",
        )
        deduct_profit = metric_html(
            "扣非归母净利润",
            amount_range_to_yi(pred_deduct.get("PREDICT_AMT_LOWER"), pred_deduct.get("PREDICT_AMT_UPPER")),
            pct_range_text(pred_deduct.get("ADD_AMP_LOWER"), pred_deduct.get("ADD_AMP_UPPER"), pred_deduct.get("INCREASE_JZ")),
            growth_class(pred_deduct.get("ADD_AMP_LOWER"), pred_deduct.get("ADD_AMP_UPPER"), pred_deduct.get("INCREASE_JZ")),
            "业绩预告" if pred_deduct else "待披露",
        )

    return (
        '<div class="finance-panel">'
        '<div class="finance-note">同比增长率：正数红色，负数绿色。正式中报未披露前，归母/扣非若有业绩预告则显示预告区间。</div>'
        '<div class="metrics">'
        f"{revenue}{parent_profit}{deduct_profit}"
        "</div>"
        f'<div class="broker-forecast" data-code="{html.escape(code)}">'
        '<button class="broker-button" type="button">加载券商预测</button>'
        '<div class="broker-content">点击按钮后抓取该股票的券商盈利预测。</div>'
        "</div>"
        "</div>"
    )


def numeric_average(*values: Any) -> float | None:
    nums = []
    for value in values:
        if value in (None, ""):
            continue
        try:
            nums.append(float(value))
        except (TypeError, ValueError):
            pass
    if not nums:
        return None
    return sum(nums) / len(nums)


def arrow_pct_text(value: float | None) -> str:
    if value is None:
        return "待披露"
    arrow = "↑" if value >= 0 else "↓"
    return f"{arrow} {value:+.2f}%"


def star_rating(growth: float | None) -> str:
    if growth is None:
        return "★★★☆☆"
    if growth >= 50:
        return "★★★★★"
    if growth >= 30:
        return "★★★★☆"
    if growth >= 15:
        return "★★★★☆"
    if growth >= -5:
        return "★★★☆☆"
    if growth >= -15:
        return "★★☆☆☆"
    return "★☆☆☆☆"


def metric_summary(code: str, financial_lookup: dict[str, dict[str, Any]]) -> dict[str, Any]:
    info = financial_lookup.get(code, {})
    if "summary" in info:
        return info["summary"]
    formal = info.get("formal")
    predicts = info.get("predict", {})

    if formal:
        revenue_growth = numeric_average(formal.get("YSTZ"))
        profit_growth = numeric_average(formal.get("SJLTZ"))
        deduct_growth = numeric_average(formal.get("DEDUCT_PARENT_NETPROFIT_YOY"))
        return {
            "source": "正式中报",
            "revenue_amount": amount_to_yi(formal.get("TOTAL_OPERATE_INCOME")),
            "revenue_growth": revenue_growth,
            "revenue_text": arrow_pct_text(revenue_growth),
            "revenue_class": growth_class(formal.get("YSTZ")),
            "profit_amount": amount_to_yi(formal.get("PARENT_NETPROFIT")),
            "profit_growth": profit_growth,
            "profit_text": arrow_pct_text(profit_growth),
            "profit_class": growth_class(formal.get("SJLTZ")),
            "deduct_amount": amount_to_yi(formal.get("DEDUCT_PARENT_NETPROFIT")),
            "deduct_growth": deduct_growth,
            "deduct_text": arrow_pct_text(deduct_growth),
            "deduct_class": growth_class(formal.get("DEDUCT_PARENT_NETPROFIT_YOY")),
        }

    pred_revenue = predicts.get("006", {})
    pred_parent = predicts.get("004", {})
    pred_deduct = predicts.get("005", {})
    revenue_growth = numeric_average(
        pred_revenue.get("ADD_AMP_LOWER"),
        pred_revenue.get("ADD_AMP_UPPER"),
        pred_revenue.get("INCREASE_JZ"),
    )
    profit_growth = numeric_average(
        pred_parent.get("ADD_AMP_LOWER"),
        pred_parent.get("ADD_AMP_UPPER"),
        pred_parent.get("INCREASE_JZ"),
    )
    deduct_growth = numeric_average(
        pred_deduct.get("ADD_AMP_LOWER"),
        pred_deduct.get("ADD_AMP_UPPER"),
        pred_deduct.get("INCREASE_JZ"),
    )
    return {
        "source": "业绩预告" if predicts else "待披露",
        "revenue_amount": amount_range_to_yi(pred_revenue.get("PREDICT_AMT_LOWER"), pred_revenue.get("PREDICT_AMT_UPPER")),
        "revenue_growth": revenue_growth,
        "revenue_text": arrow_pct_text(revenue_growth),
        "revenue_class": growth_class(pred_revenue.get("ADD_AMP_LOWER"), pred_revenue.get("ADD_AMP_UPPER"), pred_revenue.get("INCREASE_JZ")),
        "profit_amount": amount_range_to_yi(pred_parent.get("PREDICT_AMT_LOWER"), pred_parent.get("PREDICT_AMT_UPPER")),
        "profit_growth": profit_growth,
        "profit_text": arrow_pct_text(profit_growth),
        "profit_class": growth_class(pred_parent.get("ADD_AMP_LOWER"), pred_parent.get("ADD_AMP_UPPER"), pred_parent.get("INCREASE_JZ")),
        "deduct_amount": amount_range_to_yi(pred_deduct.get("PREDICT_AMT_LOWER"), pred_deduct.get("PREDICT_AMT_UPPER")),
        "deduct_growth": deduct_growth,
        "deduct_text": arrow_pct_text(deduct_growth),
        "deduct_class": growth_class(pred_deduct.get("ADD_AMP_LOWER"), pred_deduct.get("ADD_AMP_UPPER"), pred_deduct.get("INCREASE_JZ")),
    }


def ai_summary_for(item: dict[str, Any]) -> str:
    profit_growth = item.get("profit_growth")
    revenue_growth = item.get("revenue_growth")
    if profit_growth is None and revenue_growth is None:
        return f"{item['name']}的2026年中报预约在{item['date']}，核心财务数据仍需等待披露或券商预测补充。"
    parts = [f"{item['name']}预约在{item['date']}披露中报"]
    if revenue_growth is not None:
        parts.append(f"营收同比预计{revenue_growth:+.2f}%")
    if profit_growth is not None:
        parts.append(f"利润同比预计{profit_growth:+.2f}%")
    return "，".join(parts) + "，建议重点看披露当天是否兑现预期。"


def disclosure_status(company: dict[str, str], date: str) -> dict[str, str]:
    first_date = company.get("first_appointment_date", "") or date
    actual_date = company.get("actual_disclosure_date", "")
    is_early = bool(first_date and date and date < first_date)
    if actual_date:
        if first_date and actual_date < first_date:
            label = "提前披露"
        elif first_date and actual_date > first_date:
            label = "延期披露"
        else:
            label = "已披露"
    elif is_early:
        label = "提前安排"
    else:
        label = "预约披露"
    return {
        "label": label,
        "class_name": "status-early" if is_early or label == "提前披露" else "status-normal",
        "first_date": first_date,
        "actual_date": actual_date,
        "is_early": "1" if is_early or label == "提前披露" else "",
    }


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_html_report(
    path: Path,
    daily_rows: list[dict[str, str]],
    groups: dict[str, list[dict[str, str]]],
    total_rows: int,
    financial_lookup: dict[str, dict[str, Any]],
    sector_lookup: dict[str, list[str]],
    performance_forecasts: list[dict[str, str]] | None = None,
    broker_lookup: dict[str, str] | None = None,
    static_site: bool = False,
    api_base: str = "http://127.0.0.1:8765",
) -> None:
    now = datetime.now(CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S")
    broker_lookup = broker_lookup or {}
    performance_forecasts = performance_forecasts or []
    table_rows = []
    search_index = []
    detail_index: dict[str, dict[str, Any]] = {}
    count_by_date = {row["date"]: row["company_count"] for row in daily_rows}
    forecast_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for item in performance_forecasts:
        if item.get("notice_date"):
            forecast_groups[item["notice_date"]].append(item)
    early_by_date: dict[str, int] = {}
    for date, companies in groups.items():
        early_by_date[date] = sum(
            1 for company in companies if disclosure_status(company, date)["is_early"]
        )
    all_dates = sorted(set(count_by_date) | set(forecast_groups))
    parsed_dates = [datetime.strptime(date, "%Y-%m-%d") for date in all_dates]
    months = []
    if parsed_dates:
        month_cursor = datetime(parsed_dates[0].year, parsed_dates[0].month, 1)
        end_month = datetime(parsed_dates[-1].year, parsed_dates[-1].month, 1)
        while month_cursor <= end_month:
            months.append((month_cursor.year, month_cursor.month))
            next_month = month_cursor.month + 1
            next_year = month_cursor.year + (1 if next_month == 13 else 0)
            month_cursor = datetime(next_year, 1 if next_month == 13 else next_month, 1)

    calendar_months = []
    for year, month in months:
        weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
        day_cells = []
        for week in weeks:
            for day in week:
                date_text = day.strftime("%Y-%m-%d")
                count = count_by_date.get(date_text)
                forecast_count = len(forecast_groups.get(date_text, []))
                outside_class = " is-outside" if day.month != month else ""
                if count or forecast_count:
                    early_count = early_by_date.get(date_text, 0)
                    early_badge = (
                        f'<span class="calendar-early">提前{html.escape(str(early_count))}家</span>'
                        if early_count
                        else ""
                    )
                    forecast_badge = (
                        f'<span class="calendar-forecast">预告{html.escape(str(forecast_count))}家</span>'
                        if forecast_count
                        else ""
                    )
                    day_cells.append(
                        '<button class="calendar-day has-count{}" type="button" data-date="{}">'
                        '<span class="calendar-date">{}</span>{}{}{}</button>'.format(
                            outside_class,
                            html.escape(date_text),
                            day.day,
                            f'<span class="calendar-count">{html.escape(str(count))}家</span>' if count else "",
                            early_badge,
                            forecast_badge,
                        )
                    )
                else:
                    day_cells.append(
                        '<div class="calendar-day is-empty{}"><span class="calendar-date">{}</span></div>'.format(
                            outside_class,
                            day.day,
                        )
                    )
        calendar_months.append(
            '<section class="calendar-month"><h2>{}年{}月</h2>'
            '<div class="calendar-weekdays"><span>一</span><span>二</span><span>三</span><span>四</span><span>五</span><span>六</span><span>日</span></div>'
            '<div class="calendar-grid">{}</div></section>'.format(
                year,
                month,
                "".join(day_cells),
            )
        )
    for date in all_dates:
        companies = groups.get(date, [])
        for company in companies:
            metrics = metric_summary(company["stock_code"], financial_lookup)
            sectors = sector_lookup.get(company["stock_code"], ["综合"])
            status = disclosure_status(company, date)
            detail_item = {
                "code": company["stock_code"],
                "name": company["stock_name"],
                "initials": chinese_initials(company["stock_name"]),
                "date": date,
                "first_date": status["first_date"],
                "actual_date": status["actual_date"],
                "schedule_status": status["label"],
                "schedule_class": status["class_name"],
                "sectors": sectors,
                "stars": star_rating(metrics.get("profit_growth")),
                **metrics,
            }
            detail_item["ai_summary"] = ai_summary_for(detail_item)
            detail_index[company["stock_code"]] = detail_item
            search_index.append(
                {
                    "code": company["stock_code"],
                    "name": company["stock_name"],
                    "initials": detail_item["initials"],
                    "date": date,
                }
            )
        company_items = "\n".join(
            '<tr class="company-row" id="company-{}" data-code="{}" data-date="{}">'
            '<td><span class="code">{}</span><strong>{}</strong></td>'
            '<td><span class="sector-tags">{}</span></td>'
            '<td class="stars">{}</td>'
            '<td><span class="table-metric {}">{}</span><small>{}</small></td>'
            '<td><span class="table-metric {}">{}</span><small>{}</small></td>'
            '<td class="date-cell">{}</td>'
            '<td><span class="status-badge {}">{}</span><small>{}</small></td>'
            '<td><button class="detail-button" type="button" data-code="{}">查看详情 →</button></td>'
            '</tr>'.format(
                html.escape(detail_index[company["stock_code"]]["code"]),
                html.escape(detail_index[company["stock_code"]]["code"]),
                html.escape(date),
                html.escape(detail_index[company["stock_code"]]["code"]),
                html.escape(detail_index[company["stock_code"]]["name"]),
                "".join(
                    f'<span class="sector-tag">{html.escape(sector)}</span>'
                    for sector in detail_index[company["stock_code"]]["sectors"]
                ),
                html.escape(detail_index[company["stock_code"]]["stars"]),
                html.escape(detail_index[company["stock_code"]]["revenue_class"]),
                html.escape(detail_index[company["stock_code"]]["revenue_text"]),
                html.escape(detail_index[company["stock_code"]]["revenue_amount"]),
                html.escape(detail_index[company["stock_code"]]["profit_class"]),
                html.escape(detail_index[company["stock_code"]]["profit_text"]),
                html.escape(detail_index[company["stock_code"]]["profit_amount"]),
                html.escape(date),
                html.escape(detail_index[company["stock_code"]]["schedule_class"]),
                html.escape(detail_index[company["stock_code"]]["schedule_status"]),
                (
                    "原预约 " + html.escape(detail_index[company["stock_code"]]["first_date"])
                    if detail_index[company["stock_code"]]["first_date"] != date
                    else "按预约"
                ),
                html.escape(detail_index[company["stock_code"]]["code"]),
            )
            for company in companies
        )
        forecast_items = "\n".join(
            '<tr class="forecast-row" id="forecast-{}" data-code="{}" data-date="{}">'
            '<td><span class="code">{}</span><strong>{}</strong></td>'
            '<td><span class="forecast-type">{}</span></td>'
            '<td><span class="table-metric {}">{}</span><small>{}</small><small>{}</small></td>'
            '<td><span class="table-metric">{}</span><small class="{}">{}</small></td>'
            '<td>{}</td>'
            '<td class="forecast-content">{}</td>'
            '</tr>'.format(
                html.escape(item["stock_code"]),
                html.escape(item["stock_code"]),
                html.escape(date),
                html.escape(item["stock_code"]),
                html.escape(item["stock_name"]),
                html.escape(item["predict_type"]),
                html.escape(item["growth_class"]),
                html.escape(item["growth"]),
                html.escape(item["amount"]),
                html.escape(item["forecast_basis"]),
                html.escape(item["q1_deduct_profit"]),
                html.escape(item["q1_deduct_class"]),
                html.escape(item["q1_deduct_yoy"]),
                html.escape(item["finance"] or "归母/净利润"),
                html.escape(item["content"]),
            )
            for item in forecast_groups.get(date, [])
        )
        schedule_block = (
            '<div class="company-table-wrap">'
            '<table class="company-table">'
            '<thead><tr><th>股票</th><th>板块</th><th>评级</th><th>营收预测</th><th>利润预测</th><th>发布日期</th><th>状态</th><th>操作</th></tr></thead>'
            f"<tbody>{company_items}</tbody>"
            "</table>"
            "</div>"
            if company_items
            else '<div class="empty-note">这一天暂无中报预约披露公司。</div>'
        )
        forecast_block = (
            '<details class="forecast-details" open>'
            '<summary>展开业绩预告列表</summary>'
            '<div class="company-table-wrap">'
            '<table class="company-table forecast-table">'
            '<thead><tr><th>股票</th><th>预告类型</th><th>中报预告利润</th><th>一季度扣非归母净利润</th><th>预告指标</th><th>公告摘要</th></tr></thead>'
            f"<tbody>{forecast_items}</tbody>"
            "</table>"
            "</div>"
            "</details>"
            if forecast_items
            else ""
        )
        table_rows.append(
            f"""
            <tr>
              <td class="date" id="date-{html.escape(date)}">{html.escape(date)}</td>
              <td class="count">
                <strong>{html.escape(str(count_by_date.get(date, 0)))}</strong>
                {f'<span class="forecast-inline">业绩预告 {len(forecast_groups.get(date, []))} 家</span>' if forecast_groups.get(date) else ''}
                <details>
                  <summary>展开企业列表</summary>
                  {schedule_block}
                </details>
                {forecast_block}
              </td>
            </tr>
            """
        )

    document = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>沪市2026年中报预约披露日期统计</title>
  <style>
    body {{ margin: 0; padding: 28px; background: #f6f7fb; color: #1f2937; font-family: "Microsoft YaHei", Arial, sans-serif; }}
    main {{ max-width: 980px; margin: 0 auto; }}
    h1 {{ margin: 0 0 14px; font-size: 28px; letter-spacing: 0; }}
    .notice {{ margin: 0 0 16px; padding: 12px 14px; border: 1px solid #bfdbfe; border-radius: 8px; background: #eff6ff; color: #1e3a8a; }}
    .meta {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; margin: 16px 0 22px; }}
    .meta div {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px 12px; }}
    .refresh-card {{ display: flex; align-items: center; justify-content: space-between; gap: 10px; }}
    .refresh-button {{ border: 1px solid #2563eb; border-radius: 6px; background: #2563eb; color: #fff; padding: 6px 10px; cursor: pointer; font-size: 14px; white-space: nowrap; }}
    .refresh-button:hover {{ background: #1d4ed8; }}
    .refresh-button:disabled {{ cursor: wait; opacity: .65; }}
    .refresh-status {{ margin-left: 8px; color: #64748b; font-size: 12px; }}
    .search-box {{ display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 0 0 18px; padding: 12px; background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; }}
    .search-input {{ flex: 1 1 260px; min-width: 0; border: 1px solid #cbd5e1; border-radius: 6px; padding: 8px 10px; font-size: 14px; }}
    .search-button {{ border: 1px solid #0f766e; border-radius: 6px; background: #0f766e; color: #fff; padding: 8px 12px; cursor: pointer; font-size: 14px; }}
    .search-button:hover {{ background: #0d665f; }}
    .search-result {{ flex: 1 0 100%; color: #334155; font-size: 14px; line-height: 1.5; }}
    .search-result button {{ margin-left: 8px; border: 1px solid #2563eb; border-radius: 6px; background: #eff6ff; color: #1d4ed8; padding: 4px 8px; cursor: pointer; }}
    .highlight-row {{ outline: 3px solid #f59e0b; outline-offset: -3px; }}
    .highlight-company {{ outline: 4px solid #f59e0b; outline-offset: 2px; box-shadow: 0 0 0 6px rgba(245, 158, 11, .18); background: #fffbeb; }}
    .highlight-company > .company-button {{ background: #fef3c7; }}
    .calendar-wrap {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px; margin: 0 0 22px; }}
    .calendar-month {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; }}
    .calendar-month h2 {{ margin: 0; padding: 12px 14px; font-size: 18px; background: #eef2f7; }}
    .calendar-weekdays, .calendar-grid {{ display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); }}
    .calendar-weekdays span {{ padding: 8px 4px; text-align: center; color: #64748b; font-size: 13px; border-bottom: 1px solid #e5e7eb; }}
    .calendar-day {{ min-height: 70px; border: 0; border-right: 1px solid #e5e7eb; border-bottom: 1px solid #e5e7eb; background: #fff; padding: 8px; text-align: left; box-sizing: border-box; }}
    .calendar-day:nth-child(7n) {{ border-right: 0; }}
    .calendar-date {{ display: block; color: #334155; font-weight: 700; }}
    .calendar-count {{ display: inline-block; margin-top: 8px; border-radius: 999px; background: #dcfce7; color: #166534; padding: 3px 8px; font-weight: 700; font-size: 13px; }}
    .calendar-early {{ display: inline-block; margin-top: 6px; border-radius: 999px; background: #fee2e2; color: #b91c1c; padding: 3px 8px; font-weight: 800; font-size: 12px; }}
    .calendar-forecast {{ display: inline-block; margin-top: 6px; border-radius: 999px; background: #fef3c7; color: #92400e; padding: 3px 8px; font-weight: 800; font-size: 12px; }}
    .calendar-day.has-count {{ cursor: pointer; }}
    .calendar-day.has-count:hover {{ background: #f0fdf4; }}
    .calendar-day.is-empty {{ background: #f8fafc; }}
    .calendar-day.is-outside {{ opacity: .38; }}
    .calendar-day.calendar-selected {{ outline: 3px solid #f59e0b; outline-offset: -3px; background: #fffbeb; }}
    .detail-title {{ margin: 0 0 10px; font-size: 18px; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; }}
    th, td {{ border-bottom: 1px solid #e5e7eb; padding: 12px 14px; vertical-align: top; text-align: left; }}
    th {{ background: #eef2f7; }}
    tr:last-child td {{ border-bottom: 0; }}
    .date {{ width: 180px; white-space: nowrap; font-variant-numeric: tabular-nums; }}
    .count strong {{ display: inline-block; min-width: 64px; font-size: 18px; color: #0f766e; }}
    details {{ margin-top: 8px; }}
    summary {{ display: inline-flex; cursor: pointer; user-select: none; border: 1px solid #2563eb; color: #1d4ed8; background: #eff6ff; border-radius: 6px; padding: 6px 10px; font-size: 14px; }}
    summary:hover {{ background: #dbeafe; }}
    .company-table-wrap {{ margin-top: 12px; overflow-x: auto; border: 1px solid #d8dee4; border-radius: 6px; background: #fff; }}
    .company-table {{ min-width: 860px; border: 0; border-radius: 0; }}
    .company-table th {{ background: #f6f8fa; color: #57606a; font-size: 13px; font-weight: 700; }}
    .company-table th, .company-table td {{ padding: 10px 12px; border-bottom: 1px solid #d8dee4; vertical-align: middle; }}
    .company-table tr:last-child td {{ border-bottom: 0; }}
    .company-row:hover {{ background: #f6f8fa; }}
    .stars {{ color: #b45309; white-space: nowrap; letter-spacing: 0; }}
    .table-metric {{ display: block; font-weight: 800; white-space: nowrap; }}
    .company-table small {{ display: block; margin-top: 2px; color: #6b7280; font-size: 12px; }}
    .date-cell {{ white-space: nowrap; font-variant-numeric: tabular-nums; color: #374151; }}
    .status-badge {{ display: inline-flex; border-radius: 999px; padding: 3px 8px; font-size: 12px; font-weight: 800; white-space: nowrap; }}
    .status-normal {{ background: #eef2f7; color: #475569; }}
    .status-early {{ background: #fee2e2; color: #b91c1c; }}
    .forecast-inline {{ display: inline-flex; margin-left: 10px; border-radius: 999px; padding: 3px 8px; background: #fef3c7; color: #92400e; font-size: 12px; font-weight: 800; }}
    .forecast-details {{ margin-top: 12px; }}
    .forecast-type {{ display: inline-flex; border-radius: 999px; padding: 3px 8px; background: #fff7ed; color: #c2410c; font-weight: 800; white-space: nowrap; }}
    .forecast-content {{ min-width: 280px; color: #334155; font-size: 13px; line-height: 1.55; }}
    .empty-note {{ margin-top: 10px; color: #64748b; font-size: 13px; }}
    .detail-button {{ border: 1px solid #0969da; border-radius: 6px; background: #0969da; color: #fff; padding: 6px 10px; cursor: pointer; font-size: 13px; white-space: nowrap; }}
    .detail-button:hover {{ background: #0550ae; }}
    .sector-tags {{ display: inline-flex; flex-wrap: wrap; justify-content: flex-end; gap: 4px; }}
    .sector-tag {{ border: 1px solid #cbd5e1; border-radius: 999px; background: #f8fafc; color: #475569; padding: 2px 6px; font-size: 12px; line-height: 1.2; }}
    .code {{ display: inline-block; width: 70px; color: #475569; font-family: Consolas, monospace; font-variant-numeric: tabular-nums; }}
    .finance-panel {{ border-top: 1px solid #e5e7eb; background: #ffffff; padding: 10px; }}
    .finance-note {{ color: #64748b; font-size: 12px; line-height: 1.5; margin-bottom: 8px; }}
    .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); gap: 8px; }}
    .metric {{ border: 1px solid #e5e7eb; border-radius: 6px; padding: 8px; background: #fcfcfc; }}
    .metric-label {{ font-size: 12px; color: #64748b; }}
    .metric-value {{ margin-top: 4px; font-weight: 700; }}
    .metric-growth {{ margin-top: 3px; font-weight: 700; }}
    .metric-source {{ margin-top: 3px; font-size: 12px; color: #94a3b8; }}
    .broker-forecast {{ margin-top: 10px; border-top: 1px dashed #cbd5e1; padding-top: 10px; }}
    .broker-button {{ border: 1px solid #7c3aed; border-radius: 6px; background: #f5f3ff; color: #6d28d9; padding: 6px 10px; cursor: pointer; font-size: 14px; }}
    .broker-button:hover {{ background: #ede9fe; }}
    .broker-button:disabled {{ opacity: .65; cursor: wait; }}
    .broker-content {{ margin-top: 8px; color: #334155; font-size: 13px; line-height: 1.55; overflow-x: auto; }}
    .broker-content table {{ min-width: 720px; border-radius: 6px; }}
    .broker-content th, .broker-content td {{ padding: 7px 8px; font-size: 13px; }}
    .tier-legend {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(112px, 1fr)); gap: 8px; margin: 0 0 20px; }}
    .tier-item {{ border-radius: 6px; padding: 8px 10px; color: #111827; background: #fff; border: 1px solid #e5e7eb; }}
    .tier-item strong {{ display: block; margin-bottom: 2px; }}
    .tier-boom {{ color: #C00000; }}
    .tier-strong-up {{ color: #E53935; }}
    .tier-mid-up {{ color: #FF6B6B; }}
    .tier-flat {{ color: #6b7280; }}
    .tier-small-down {{ color: #7BC96F; }}
    .tier-big-down {{ color: #2E8B57; }}
    .tier-crash {{ color: #006400; }}
    .tier-unknown {{ color: #64748b; }}
    .detail-overlay {{ position: fixed; inset: 0; z-index: 30; overflow: auto; background: linear-gradient(180deg, #f8fafc 0%, #eef4ff 48%, #f8fafc 100%); padding: 24px; box-sizing: border-box; }}
    .detail-shell {{ max-width: 1080px; margin: 0 auto; }}
    .back-button {{ border: 1px solid #d0d7de; border-radius: 6px; background: #fff; color: #24292f; padding: 8px 12px; cursor: pointer; }}
    .back-button:hover {{ background: #f6f8fa; }}
    .detail-hero {{ margin-top: 16px; border: 1px solid #d0d7de; border-radius: 8px; background: #fff; overflow: hidden; box-shadow: 0 24px 60px rgba(15, 23, 42, .10); }}
    .detail-header {{ display: grid; grid-template-columns: 1fr auto; gap: 18px; padding: 26px; border-bottom: 1px solid #d8dee4; background: radial-gradient(circle at right top, rgba(9, 105, 218, .14), transparent 38%), #fff; }}
    .detail-header h2 {{ margin: 0 0 8px; font-size: 34px; letter-spacing: 0; }}
    .detail-code {{ color: #57606a; font-family: Consolas, monospace; }}
    .detail-score {{ text-align: right; }}
    .detail-score .stars {{ display: block; font-size: 24px; }}
    .detail-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 0; border-bottom: 1px solid #d8dee4; }}
    .detail-block {{ padding: 22px 24px; border-right: 1px solid #d8dee4; }}
    .detail-block:last-child {{ border-right: 0; }}
    .detail-label {{ color: #57606a; font-size: 13px; margin-bottom: 8px; }}
    .detail-value {{ font-size: 24px; font-weight: 800; }}
    .bar {{ height: 12px; margin: 14px 0 8px; border-radius: 999px; background: #eaeef2; overflow: hidden; }}
    .bar span {{ display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, #0969da, #2da44e); }}
    .detail-section {{ padding: 24px; border-bottom: 1px solid #d8dee4; background: #fff; }}
    .detail-section h3 {{ margin: 0 0 14px; font-size: 18px; }}
    .trend-svg {{ width: 100%; height: 160px; display: block; border: 1px solid #d8dee4; border-radius: 8px; background: #f6f8fa; }}
    .detail-kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }}
    .detail-kpi {{ border: 1px solid #d8dee4; border-radius: 8px; padding: 14px; background: #f6f8fa; }}
    .detail-ai {{ font-size: 18px; line-height: 1.7; color: #24292f; }}
    @media (max-width: 720px) {{
      body {{ padding: 16px; }}
      .detail-overlay {{ padding: 14px; }}
      .detail-header {{ grid-template-columns: 1fr; }}
      .detail-score {{ text-align: left; }}
      .detail-header h2 {{ font-size: 28px; }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>沪市2026年中报预约披露日期统计</h1>
    <p class="notice">当前文件统计的是上交所已发布的沪市 2026 年半年报（中报）预约披露时间。深市/北交所若尚未发布完整预约表，需要待官方数据放出后再合并。</p>
    <section class="meta">
      <div>数据源：上海证券交易所定期报告预约情况</div>
      <div>报告类型：2026 年半年报（中报）</div>
      <div>统计日期：首次预约日优先，若有变更/实际披露则取最新可用日期</div>
      <div class="refresh-card"><span>{'静态生成时间' if static_site else '抓取时间'}：{html.escape(now)}<span id="refreshStatus" class="refresh-status">{'；公开版不依赖本地服务' if static_site else ''}</span></span><button id="refreshButton" class="refresh-button" type="button"{' disabled' if static_site else ''}>{'静态版' if static_site else '抓取最新'}</button></div>
      <div>公司记录数：{total_rows}</div>
      <div>7月15日前关键业绩预告：{len(performance_forecasts)} 家</div>
    </section>
    <section class="search-box">
      <input id="stockSearchInput" class="search-input" type="search" placeholder="输入股票代码、公司简称或名称，例如 600519 / 贵州茅台 / 茅台">
      <button id="stockSearchButton" class="search-button" type="button">查询发布时间</button>
      <div id="stockSearchResult" class="search-result">输入股票代码或简称后点击查询。</div>
    </section>
    <section class="tier-legend">
      <div class="tier-item"><strong style="color:#C00000">① 暴涨</strong>≥ +50%</div>
      <div class="tier-item"><strong style="color:#E53935">② 大涨</strong>+30% ～ +50%</div>
      <div class="tier-item"><strong style="color:#FF6B6B">③ 中涨</strong>+15% ～ +30%</div>
      <div class="tier-item"><strong style="color:#6b7280">④ 平稳</strong>-5% ～ +15%</div>
      <div class="tier-item"><strong style="color:#7BC96F">⑤ 小跌</strong>-15% ～ -5%</div>
      <div class="tier-item"><strong style="color:#2E8B57">⑥ 大跌</strong>-30% ～ -15%</div>
      <div class="tier-item"><strong style="color:#006400">⑦ 暴跌</strong>≤ -30%</div>
    </section>
    <section class="calendar-wrap" aria-label="中报预约日历">
      {"".join(calendar_months)}
    </section>
    <h2 id="detailTitle" class="detail-title">日期详情</h2>
    <table>
      <thead><tr><th>日期</th><th>公布家数 / 企业列表</th></tr></thead>
      <tbody>{"".join(table_rows)}</tbody>
    </table>
  </main>
  <section id="detailOverlay" class="detail-overlay" hidden>
    <div class="detail-shell">
      <button id="detailBackButton" class="back-button" type="button">← 返回日历</button>
      <div id="detailContent"></div>
    </div>
  </section>
  <script>
    const searchIndex = {json.dumps(search_index, ensure_ascii=False)};
    const detailIndex = {json.dumps(detail_index, ensure_ascii=False)};
    const brokerIndex = {json.dumps(broker_lookup, ensure_ascii=False)};
    const isStaticSite = {str(static_site).lower()};
    const apiBase = {json.dumps(api_base, ensure_ascii=False)};
    const stockSearchInput = document.getElementById('stockSearchInput');
    const stockSearchButton = document.getElementById('stockSearchButton');
    const stockSearchResult = document.getElementById('stockSearchResult');
    const detailOverlay = document.getElementById('detailOverlay');
    const detailContent = document.getElementById('detailContent');
    const detailBackButton = document.getElementById('detailBackButton');
    function normalizeQuery(value) {{
      return String(value || '').trim().toLowerCase().replace(/\\s+/g, '');
    }}
    function clearHighlights() {{
      document.querySelectorAll('.highlight-row').forEach(el => el.classList.remove('highlight-row'));
      document.querySelectorAll('.highlight-company').forEach(el => el.classList.remove('highlight-company'));
      document.querySelectorAll('.calendar-selected').forEach(el => el.classList.remove('calendar-selected'));
    }}
    function selectCalendarDay(date) {{
      document.querySelectorAll(`.calendar-day[data-date="${{date}}"]`).forEach(el => el.classList.add('calendar-selected'));
    }}
    function jumpToCompany(item) {{
      const cell = document.getElementById('date-' + item.date);
      const companyRow = document.getElementById('company-' + item.code);
      clearHighlights();
      selectCalendarDay(item.date);
      if (cell) {{
        const row = cell.closest('tr');
        if (row) {{
          row.classList.add('highlight-row');
          const dateDetails = row.querySelector('td.count > details');
          if (dateDetails) dateDetails.open = true;
        }}
      }}
      if (companyRow) {{
        companyRow.classList.add('highlight-company');
        companyRow.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
      }} else if (cell) {{
        const row = cell.closest('tr');
        if (row) row.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
      }}
    }}
    function jumpToDate(date) {{
      const cell = document.getElementById('date-' + date);
      if (!cell) return;
      const row = cell.closest('tr');
      clearHighlights();
      selectCalendarDay(date);
      if (row) {{
        row.classList.add('highlight-row');
        const dateDetails = row.querySelector('td.count > details');
        if (dateDetails) dateDetails.open = true;
        const scrollTarget = dateDetails || row;
        scrollTarget.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
      }}
    }}
    document.querySelectorAll('.calendar-day.has-count').forEach(button => {{
      button.addEventListener('click', () => jumpToDate(button.dataset.date));
    }});
    function runStockSearch() {{
      const q = normalizeQuery(stockSearchInput.value);
      if (!q) {{
        stockSearchResult.textContent = '请输入股票代码、公司简称或名称。';
        return;
      }}
        const matches = searchIndex.filter(item => {{
        const code = normalizeQuery(item.code);
        const name = normalizeQuery(item.name);
        const initials = normalizeQuery(item.initials);
        return code.includes(q) || name.includes(q) || initials.includes(q);
      }}).slice(0, 20);
      if (!matches.length) {{
        stockSearchResult.textContent = '没有找到匹配公司。可以试试 6 位股票代码或股票简称。';
        return;
      }}
      stockSearchResult.innerHTML = matches.map(item =>
        `<span><strong>${{item.code}} ${{item.name}}</strong>：${{item.date}} 发布中报</span><button type="button" data-code="${{item.code}}">跳转</button>`
      ).join('<br>');
      if (matches.length === 1) jumpToCompany(matches[0]);
    }}
    stockSearchButton.addEventListener('click', runStockSearch);
    stockSearchInput.addEventListener('keydown', event => {{
      if (event.key === 'Enter') runStockSearch();
    }});
    stockSearchResult.addEventListener('click', event => {{
      const target = event.target;
      if (target && target.dataset && target.dataset.code) {{
        const item = searchIndex.find(item => item.code === target.dataset.code);
        if (item) jumpToCompany(item);
      }}
    }});
    function escapeHtml(value) {{
      return String(value ?? '').replace(/[&<>"']/g, char => ({{
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
      }}[char]));
    }}
    function barWidth(value) {{
      if (value === null || value === undefined || Number.isNaN(Number(value))) return 18;
      return Math.min(100, Math.max(12, Math.abs(Number(value)) + 18));
    }}
    function sectorsHtml(item) {{
      return (item.sectors || ['综合']).map(sector => `<span class="sector-tag">${{escapeHtml(sector)}}</span>`).join('');
    }}
    function trendSvg(item) {{
      const revenue = Number(item.revenue_growth);
      const profit = Number(item.profit_growth);
      const hasRevenue = !Number.isNaN(revenue);
      const hasProfit = !Number.isNaN(profit);
      if (!hasRevenue && !hasProfit) {{
        return '<div class="detail-kpi">暂无足够公开数据绘制趋势，加载券商预测后可查看预测明细。</div>';
      }}
      const base = hasRevenue ? revenue : profit;
      const next = hasProfit ? profit : revenue;
      const points = [
        28, 118 - Math.max(-30, Math.min(60, base - 8)),
        190, 100 - Math.max(-30, Math.min(60, base)),
        352, 112 - Math.max(-30, Math.min(60, next)),
        514, 92 - Math.max(-30, Math.min(60, next + 6))
      ].join(' ');
      return `<svg class="trend-svg" viewBox="0 0 560 160" role="img" aria-label="趋势图">
        <line x1="24" y1="130" x2="536" y2="130" stroke="#d0d7de"/>
        <line x1="24" y1="80" x2="536" y2="80" stroke="#d0d7de" stroke-dasharray="4 6"/>
        <polyline points="${{points}}" fill="none" stroke="#0969da" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
        <circle cx="28" cy="${{118 - Math.max(-30, Math.min(60, base - 8))}}" r="5" fill="#0969da"/>
        <circle cx="514" cy="${{92 - Math.max(-30, Math.min(60, next + 6))}}" r="5" fill="#2da44e"/>
        <text x="28" y="148" fill="#57606a" font-size="13">历史</text>
        <text x="472" y="148" fill="#57606a" font-size="13">预测</text>
      </svg>`;
    }}
    function openDetail(code) {{
      const item = detailIndex[code];
      if (!item) return;
      const revenueWidth = barWidth(item.revenue_growth);
      const profitWidth = barWidth(item.profit_growth);
      const deductWidth = barWidth(item.deduct_growth);
      detailContent.innerHTML = `
        <article class="detail-hero">
          <header class="detail-header">
            <div>
              <div class="detail-code">${{escapeHtml(item.code)}}</div>
              <h2>${{escapeHtml(item.name)}}</h2>
              <div class="sector-tags">${{sectorsHtml(item)}}</div>
            </div>
            <div class="detail-score">
              <span class="stars">${{escapeHtml(item.stars)}}</span>
              <div class="detail-label">综合预测评分</div>
            </div>
          </header>
          <section class="detail-grid">
            <div class="detail-block">
              <div class="detail-label">发布日期</div>
              <div class="detail-value">${{escapeHtml(item.date)}}</div>
              <strong class="${{escapeHtml(item.schedule_class)}} status-badge">${{escapeHtml(item.schedule_status)}}</strong>
              <div class="detail-label">原预约：${{escapeHtml(item.first_date || item.date)}}</div>
            </div>
            <div class="detail-block">
              <div class="detail-label">营收</div>
              <div class="detail-value">${{escapeHtml(item.revenue_amount)}}</div>
              <div class="bar"><span style="width:${{revenueWidth}}%"></span></div>
              <strong class="${{escapeHtml(item.revenue_class)}}">同比 ${{escapeHtml(item.revenue_text)}}</strong>
            </div>
            <div class="detail-block">
              <div class="detail-label">净利润</div>
              <div class="detail-value">${{escapeHtml(item.profit_amount)}}</div>
              <div class="bar"><span style="width:${{profitWidth}}%"></span></div>
              <strong class="${{escapeHtml(item.profit_class)}}">同比 ${{escapeHtml(item.profit_text)}}</strong>
            </div>
            <div class="detail-block">
              <div class="detail-label">扣非归母净利润</div>
              <div class="detail-value">${{escapeHtml(item.deduct_amount)}}</div>
              <div class="bar"><span style="width:${{deductWidth}}%"></span></div>
              <strong class="${{escapeHtml(item.deduct_class)}}">同比 ${{escapeHtml(item.deduct_text)}}</strong>
            </div>
          </section>
          <section class="detail-section">
            <h3>历史趋势（折线图）</h3>
            ${{trendSvg(item)}}
          </section>
          <section class="detail-section">
            <h3>行业排名 / 券商一致预测</h3>
            <div class="detail-kpis">
              <div class="detail-kpi"><div class="detail-label">行业排名</div><div class="detail-value">待计算</div></div>
              <div class="detail-kpi"><div class="detail-label">预测来源</div><div class="detail-value">${{escapeHtml(item.source)}}</div></div>
            </div>
            <div class="broker-forecast" data-code="${{escapeHtml(item.code)}}">
              <button class="broker-button" type="button">加载券商预测</button>
              <div class="broker-content">点击按钮后抓取该股票能收集到的券商预测。</div>
            </div>
          </section>
          <section class="detail-section">
            <h3>AI总结</h3>
            <div class="detail-ai">${{escapeHtml(item.ai_summary)}}</div>
          </section>
        </article>
      `;
      detailOverlay.hidden = false;
      document.body.style.overflow = 'hidden';
      detailOverlay.scrollTo({{ top: 0, behavior: 'instant' }});
    }}
    function closeDetail() {{
      detailOverlay.hidden = true;
      document.body.style.overflow = '';
    }}
    detailBackButton.addEventListener('click', closeDetail);
    detailOverlay.addEventListener('click', event => {{
      if (event.target === detailOverlay) closeDetail();
    }});
    document.addEventListener('keydown', event => {{
      if (event.key === 'Escape' && !detailOverlay.hidden) closeDetail();
    }});
    document.addEventListener('click', event => {{
      const target = event.target;
      if (target && target.classList && target.classList.contains('detail-button')) {{
        openDetail(target.dataset.code);
      }}
    }});
    async function loadBrokerForecast(container) {{
      const code = container.dataset.code;
      const button = container.querySelector('.broker-button');
      const content = container.querySelector('.broker-content');
      if (!code || !button || !content) return;
      if (Object.prototype.hasOwnProperty.call(brokerIndex, code)) {{
        content.innerHTML = brokerIndex[code] || '该股暂无可收集到的券商盈利预测。';
        button.textContent = '已加载静态预测';
        return;
      }}
      if (isStaticSite) {{
        content.textContent = '该静态版未收集到这只股票的券商预测。';
        button.textContent = '暂无券商预测';
        return;
      }}
      button.disabled = true;
      button.textContent = '抓取中...';
      content.textContent = '正在抓取券商预测...';
      try {{
        const response = await fetch(apiBase + '/broker?code=' + encodeURIComponent(code));
        const data = await response.json();
        if (!response.ok || !data.ok) {{
          throw new Error(data.error || data.detail || '抓取失败');
        }}
        content.innerHTML = data.html || '暂无券商预测';
        button.textContent = '刷新券商预测';
      }} catch (error) {{
        const helpText = apiBase.startsWith('http://127.0.0.1')
          ? '需要先运行：<code>python update_report_server.py</code>'
          : '云端 API 暂时不可用，请稍后重试。';
        content.innerHTML = '无法抓取券商预测。' + helpText + '<br>错误：' + String(error.message || error);
        button.textContent = '加载券商预测';
      }} finally {{
        button.disabled = false;
      }}
    }}
    document.addEventListener('click', event => {{
      const target = event.target;
      if (target && target.classList && target.classList.contains('broker-button')) {{
        const container = target.closest('.broker-forecast');
        if (container) loadBrokerForecast(container);
      }}
    }});

    const refreshButton = document.getElementById('refreshButton');
    const refreshStatus = document.getElementById('refreshStatus');
    refreshButton.addEventListener('click', async () => {{
      if (isStaticSite) return;
      refreshButton.disabled = true;
      refreshButton.textContent = '抓取中...';
      refreshStatus.textContent = '正在更新，请稍等';
      try {{
        const response = await fetch(apiBase + '/update', {{ method: 'POST' }});
        const data = await response.json();
        if (!response.ok || !data.ok) {{
          throw new Error(data.error || data.detail || '更新失败');
        }}
        refreshStatus.textContent = '更新完成，正在刷新';
        window.location.reload();
      }} catch (error) {{
        refreshStatus.textContent = '更新服务未启动';
        const helpText = apiBase.startsWith('http://127.0.0.1')
          ? '需要先在 PowerShell 运行：python update_report_server.py'
          : '云端更新接口暂时不可用，请稍后重试';
        alert(helpText + '\\n\\n详细错误：' + error.message);
        refreshButton.disabled = false;
        refreshButton.textContent = '抓取最新';
      }}
    }});
  </script>
</body>
</html>
"""
    path.write_text(document, encoding="utf-8")


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    raw_rows = fetch_sse_2026_midreport()
    financial_lookup = fetch_financial_lookup()
    performance_forecasts = fetch_key_performance_forecasts()
    detail_rows = normalized_rows(raw_rows)
    sector_lookup = fetch_sector_lookup([row["stock_code"] for row in detail_rows])

    counts: Counter[str] = Counter(row["stat_date"] for row in detail_rows if row["stat_date"])
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in detail_rows:
        if row["stat_date"]:
            groups[row["stat_date"]].append(row)
    for companies in groups.values():
        companies.sort(key=lambda item: item["stock_code"])

    daily_rows = [
        {"date": date, "company_count": str(count)}
        for date, count in sorted(counts.items())
    ]

    detail_path = OUTPUT_DIR / "detail_sse_2026_midreport.csv"
    daily_path = OUTPUT_DIR / "daily_count_sse_2026_midreport.csv"
    html_path = OUTPUT_DIR / "report_sse_2026_midreport.html"
    md_path = OUTPUT_DIR / "report_sse_2026_midreport.md"

    write_csv(detail_path, detail_rows, list(detail_rows[0].keys()) if detail_rows else [])
    write_csv(daily_path, daily_rows, ["date", "company_count"])
    write_html_report(
        html_path,
        daily_rows,
        dict(groups),
        len(detail_rows),
        financial_lookup,
        sector_lookup,
        performance_forecasts=performance_forecasts,
    )

    md_lines = [
        "# 沪市2026年中报预约披露日期统计",
        "",
        f"- 数据源：上海证券交易所定期报告预约情况",
        f"- 公司记录数：{len(detail_rows)}",
        f"- 7月15日前关键业绩预告：{len(performance_forecasts)}",
        f"- 抓取时间：{datetime.now(CHINA_TZ).strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "| 日期 | 家数 |",
        "| --- | ---: |",
    ]
    md_lines.extend(f"| {row['date']} | {row['company_count']} |" for row in daily_rows)
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(f"Done. Detail CSV: {detail_path}")
    print(f"Done. Daily count CSV: {daily_path}")
    print(f"Done. Expandable HTML report: {html_path}")
    print(f"Done. Markdown report: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
