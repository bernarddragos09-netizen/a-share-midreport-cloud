#!/usr/bin/env python3
"""Local update server for the 2026 midreport HTML.

Run this once, then click the "抓取最新" button in the HTML report.
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import escape
from pathlib import Path
from typing import Any


HOST = "127.0.0.1"
PORT = 8765
ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "fetch_2026_midreport_upcoming_sse.py"
EASTMONEY_DATA_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def eastmoney_market_code(code: str) -> str:
    code = str(code or "").strip()
    return f"SH{code}" if code.startswith(("6", "9")) else f"SZ{code}"


def fmt_num(value: object, digits: int = 2) -> str:
    if value in (None, ""):
        return "-"
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def fmt_yi(value: object) -> str:
    if value in (None, ""):
        return "-"
    try:
        return f"{float(value) / 100000000:,.2f} 亿"
    except (TypeError, ValueError):
        return str(value)


def num(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def add_nums(*values: object) -> float | None:
    total = 0.0
    seen = False
    for value in values:
        number = num(value)
        if number is not None:
            total += number
            seen = True
    return total if seen else None


def sub_num(left: object, right: object) -> float | None:
    left_num = num(left)
    right_num = num(right)
    if left_num is None or right_num is None:
        return None
    return left_num - right_num


def pct_ratio(numerator: object, denominator: object) -> str:
    n = num(numerator)
    d = num(denominator)
    if n is None or d in (None, 0):
        return "-"
    return f"{n / d * 100:.2f}%"


def multiple_ratio(numerator: object, denominator: object) -> str:
    n = num(numerator)
    d = num(denominator)
    if n is None or d in (None, 0):
        return "-"
    return f"{n / d:.2f}x"


def fetch_eastmoney_report(report_name: str, code: str, page_size: int = 8) -> list[dict[str, Any]]:
    params = {
        "reportName": report_name,
        "columns": "ALL",
        "filter": f'(SECURITY_CODE="{code}")',
        "pageNumber": 1,
        "pageSize": page_size,
        "sortColumns": "REPORT_DATE",
        "sortTypes": "-1",
    }
    url = EASTMONEY_DATA_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    rows = (data.get("result") or {}).get("data") or []
    return list(reversed(rows))


def date_label(row: dict[str, Any]) -> str:
    return str(row.get("REPORT_DATE", "") or "")[:10]


def latest(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return rows[-1] if rows else {}


def metric_card(label: str, value: object, suffix: str = "") -> str:
    text = value if isinstance(value, str) else fmt_yi(value)
    return (
        '<div class="fs-card">'
        f'<div class="fs-label">{escape(label)}</div>'
        f'<div class="fs-value">{escape(str(text))}{escape(suffix)}</div>'
        "</div>"
    )


def mini_table(title: str, items: list[tuple[str, object]]) -> str:
    rows = "".join(
        f"<tr><th>{escape(label)}</th><td>{escape(value if isinstance(value, str) else fmt_yi(value))}</td></tr>"
        for label, value in items
    )
    return f'<section class="fs-panel"><h3>{escape(title)}</h3><table class="fs-mini"><tbody>{rows}</tbody></table></section>'


def svg_line_chart(title: str, series: list[tuple[str, list[tuple[str, float | None]], str]]) -> str:
    values = [value for _, points, _ in series for _, value in points if value is not None]
    if not values:
        return f'<div class="fs-chart empty">{escape(title)}：暂无数据</div>'
    min_v = min(values)
    max_v = max(values)
    if min_v == max_v:
        min_v -= 1
        max_v += 1
    padding = (max_v - min_v) * 0.08
    min_v -= padding
    max_v += padding
    width = 920
    height = 420
    left = 92
    right = 34
    top = 34
    bottom = 64
    labels = [label for label, _ in series[0][1]]
    count = max(1, len(labels) - 1)

    def xy(index: int, value: float) -> tuple[float, float]:
        x = left + index * ((width - left - right) / count)
        y = top + (max_v - value) / (max_v - min_v) * (height - top - bottom)
        return x, y

    def axis_text(value: float) -> str:
        if abs(value) >= 1000:
            return f"{value:,.0f}"
        if abs(value) >= 100:
            return f"{value:,.1f}"
        return f"{value:,.2f}"

    polylines = []
    dots = []
    legends = []
    for s_index, (name, points, color) in enumerate(series):
        parts = []
        for index, (_, value) in enumerate(points):
            if value is None:
                continue
            x, y = xy(index, value)
            parts.append(f"{x:.1f},{y:.1f}")
            dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{color}"><title>{escape(name)} {value:,.2f}</title></circle>')
        if parts:
            polylines.append(f'<polyline points="{" ".join(parts)}" fill="none" stroke="{color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>')
            legends.append(f'<span><i style="background:{color}"></i>{escape(name)}</span>')

    tick_count = 5
    y_ticks = []
    for tick in range(tick_count):
        value = min_v + (max_v - min_v) * tick / (tick_count - 1)
        y = top + (max_v - value) / (max_v - min_v) * (height - top - bottom)
        y_ticks.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#eaeef2"/>'
            f'<text x="{left-12}" y="{y+4:.1f}" text-anchor="end">{escape(axis_text(value))}</text>'
        )
    x_labels = "".join(
        f'<text x="{left + i * ((width - left - right) / count):.1f}" y="{height - 14}" text-anchor="middle">{escape(label[2:7])}</text>'
        for i, label in enumerate(labels)
    )
    return (
        '<div class="fs-chart">'
        f'<div class="fs-chart-title">{escape(title)}</div>'
        f'<svg viewBox="0 0 {width} {height}" role="img">'
        f'{"".join(y_ticks)}'
        f'<line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#d0d7de"/>'
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#d0d7de"/>'
        f'{"".join(polylines)}{"".join(dots)}{x_labels}'
        '</svg>'
        f'<div class="fs-legend">{"".join(legends)}</div>'
        "</div>"
    )


def balance_snapshot_chart(company_name: str, balance_rows: list[dict[str, Any]]) -> str:
    rows = list(reversed([row for row in balance_rows if row]))
    if not rows:
        return '<section class="fs-balance-snapshot empty">资产负债结构图：暂无数据</section>'

    width = 1120
    height = 500
    left = 76
    right = 36
    top = 98
    bottom = 94
    chart_w = width - left - right
    chart_h = height - top - bottom

    def axis_text(value: float) -> str:
        if value >= 1000:
            return f"{value:,.0f}"
        if value >= 100:
            return f"{value:,.1f}"
        return f"{value:,.2f}"

    def split_label(label: str) -> list[str]:
        if "&" in label:
            return label.split("&")
        if len(label) <= 4:
            return [label]
        return [label[:4], label[4:]]

    def row_bars(balance: dict[str, Any]) -> list[tuple[str, float, str, str]]:
        def value_yi(*fields: str) -> float | None:
            total = add_nums(*(balance.get(field) for field in fields))
            return total / 100000000 if total is not None else None

        assets = [
            ("现金", value_yi("MONETARYFUNDS")),
            ("应收账款", value_yi("ACCOUNTS_RECE")),
            ("预付款", value_yi("PREPAYMENT")),
            ("存货", value_yi("INVENTORY")),
            ("其他流动", value_yi("OTHER_CURRENT_ASSET")),
            ("长期投资", value_yi("LONG_EQUITY_INVEST")),
            ("固定资产", value_yi("FIXED_ASSET")),
            ("在建工程", value_yi("CIP")),
            ("无形资产", value_yi("INTANGIBLE_ASSET")),
            ("其他非流动", value_yi("OTHER_NONCURRENT_ASSET", "OTHER_NONCURRENT_FINASSET", "DEFER_TAX_ASSET")),
        ]
        liabilities = [
            ("短期借款", value_yi("SHORT_LOAN", "SHORT_BOND_PAYABLE", "NONCURRENT_LIAB_1YEAR")),
            ("应付款", value_yi("ACCOUNTS_PAYABLE")),
            ("预收款", value_yi("CONTRACT_LIAB", "PREDICT_LIAB")),
            ("薪酬&税", value_yi("STAFF_SALARY_PAYABLE", "TAX_PAYABLE")),
            ("其他流动", value_yi("OTHER_CURRENT_LIAB", "TOTAL_OTHER_PAYABLE")),
            ("长期借款", value_yi("LONG_LOAN", "BOND_PAYABLE", "LEASE_LIAB")),
            ("其他非流动", value_yi("OTHER_NONCURRENT_LIAB", "DEFER_TAX_LIAB")),
        ]
        bars = [(label, value, "#2f86d5", "asset") for label, value in assets if value is not None]
        bars += [(label, value, "#ff5b22", "liability") for label, value in liabilities if value is not None]
        return bars

    def render_panel(balance: dict[str, Any], panel_index: int) -> str:
        bars = row_bars(balance)
        if not bars:
            return f'<div class="fs-snapshot-panel fs-snapshot-panel-{panel_index} empty">本期资产负债结构暂无数据</div>'
        max_v = max(value for _, value, _, _ in bars)
        max_v = max_v * 1.18 if max_v > 0 else 1
        count = len(bars)
        gap = 12
        slot = chart_w / max(count, 1)
        bar_w = max(18, min(44, slot - gap))

        ticks = []
        for i in range(5):
            value = max_v * i / 4
            y = top + chart_h - (value / max_v) * chart_h
            ticks.append(
                f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#eaeef2"/>'
                f'<text x="{left-12}" y="{y+4:.1f}" text-anchor="end">{escape(axis_text(value))}</text>'
            )

        bar_nodes = []
        label_nodes = []
        asset_count = sum(1 for _, _, _, group in bars if group == "asset")
        for index, (label, value, color, group) in enumerate(bars):
            x = left + index * slot + (slot - bar_w) / 2
            bar_h = (value / max_v) * chart_h
            y = top + chart_h - bar_h
            bar_nodes.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" rx="4" fill="{color}">'
                f'<title>{escape(label)} {value:,.2f}亿元</title></rect>'
                f'<text x="{x + bar_w / 2:.1f}" y="{max(18, y - 8):.1f}" text-anchor="middle" class="fs-bar-value">{escape(axis_text(value))}</text>'
            )
            tspans = "".join(
                f'<tspan x="{x + bar_w / 2:.1f}" dy="{12 if part_index else 0}">{escape(part)}</tspan>'
                for part_index, part in enumerate(split_label(label))
            )
            label_nodes.append(f'<text x="{x + bar_w / 2:.1f}" y="{height - 64}" text-anchor="middle" class="fs-bar-label">{tspans}</text>')

        separator = ""
        if 0 < asset_count < count:
            sx = left + asset_count * slot - gap / 2
            separator = (
                f'<line x1="{sx:.1f}" y1="{top - 8}" x2="{sx:.1f}" y2="{height - bottom + 40}" stroke="#d8dee4" stroke-dasharray="5 5"/>'
                f'<text x="{left + asset_count * slot / 2:.1f}" y="{height - 18}" text-anchor="middle" class="fs-group-label">资产端</text>'
                f'<text x="{sx + (count - asset_count) * slot / 2:.1f}" y="{height - 18}" text-anchor="middle" class="fs-group-label">负债端</text>'
            )

        return (
            f'<div class="fs-snapshot-panel fs-snapshot-panel-{panel_index}">'
            '<div class="fs-snapshot-head">'
            '<div>'
            f'<div class="fs-snapshot-title">{escape(str(company_name))}资产负债结构图</div>'
            f'<div class="fs-snapshot-date">{escape(date_label(balance))}</div>'
            '</div>'
            '</div>'
            f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(str(company_name))}资产负债结构图">'
            f'{"".join(ticks)}'
            f'<line x1="{left}" y1="{top + chart_h}" x2="{width-right}" y2="{top + chart_h}" stroke="#d0d7de"/>'
            f'{"".join(bar_nodes)}{"".join(label_nodes)}{separator}'
            '<text x="24" y="42" class="fs-unit">单位：亿元</text>'
            '</svg>'
            '</div>'
        )

    panels = [
        render_panel(row, index).replace('class="fs-snapshot-panel ', 'class="fs-snapshot-panel is-active ' if index == 0 else 'class="fs-snapshot-panel ')
        for index, row in enumerate(rows[:6])
    ]
    return (
        '<section class="fs-balance-snapshot" data-current-index="0">'
        '<div class="fs-snapshot-nav">'
        '<button class="fs-snapshot-jump is-active" type="button" data-index="0">当期数据</button>'
        '<button class="fs-snapshot-step" type="button" data-dir="1">上一期</button>'
        '<button class="fs-snapshot-step is-disabled" type="button" data-dir="-1" disabled>下一期</button>'
        '</div>'
        f'{"".join(panels)}'
        '</section>'
    )


def chart_switcher(charts: list[str]) -> str:
    if not charts:
        return ""
    inputs = []
    panels = []
    labels = []
    for index, chart in enumerate(charts):
        checked = " checked" if index == 0 else ""
        input_id = f"fs-chart-tab-{index}"
        inputs.append(f'<input id="{input_id}" name="fs-chart-tab" type="radio"{checked}>')
        panels.append(f'<div class="fs-chart-panel fs-chart-panel-{index}">{chart}</div>')
        title_match = chart.split('<div class="fs-chart-title">', 1)
        label_text = f"图表{index + 1}"
        if len(title_match) > 1:
            label_text = title_match[1].split("</div>", 1)[0]
        labels.append(f'<label for="{input_id}">{label_text}</label>')
    selectors = []
    for index in range(len(charts)):
        selectors.append(
            f"#fs-chart-tab-{index}:checked ~ .fs-chart-stage .fs-chart-panel-{index}{{display:block}}"
            f"#fs-chart-tab-{index}:checked ~ .fs-chart-tabs label[for=fs-chart-tab-{index}]{{background:#0969da;color:#fff;border-color:#0969da}}"
        )
    return (
        '<style>'
        '.fs-chart-switcher>input{position:absolute;opacity:0;pointer-events:none}'
        '.fs-chart-panel{display:none}'
        f'{"".join(selectors)}'
        '</style>'
        '<section class="fs-chart-switcher">'
        f'{"".join(inputs)}'
        f'<div class="fs-chart-stage">{"".join(panels)}</div>'
        f'<div class="fs-chart-tabs">{"".join(labels)}</div>'
        '</section>'
    )


def points(rows: list[dict[str, Any]], field: str, scale: float = 100000000) -> list[tuple[str, float | None]]:
    return [(date_label(row), (num(row.get(field)) / scale if num(row.get(field)) is not None else None)) for row in rows]


def ratio_points(rows: list[dict[str, Any]], numerator_field: str, denominator_field: str) -> list[tuple[str, float | None]]:
    output = []
    for row in rows:
        n = num(row.get(numerator_field))
        d = num(row.get(denominator_field))
        output.append((date_label(row), (n / d * 100 if n is not None and d not in (None, 0) else None)))
    return output


def calc_series(rows: list[dict[str, Any]], fn) -> list[tuple[str, float | None]]:
    return [(date_label(row), fn(row)) for row in rows]


def fetch_financial_statements_html(code: str) -> str:
    code = "".join(ch for ch in code if ch.isdigit())[:6]
    if len(code) != 6:
        raise ValueError("股票代码必须是 6 位数字")

    income_rows = fetch_eastmoney_report("RPT_F10_FINANCE_GINCOME", code, 8)
    balance_rows = fetch_eastmoney_report("RPT_F10_FINANCE_GBALANCE", code, 8)
    cash_rows = fetch_eastmoney_report("RPT_F10_FINANCE_GCASHFLOW", code, 8)
    if not income_rows and not balance_rows and not cash_rows:
        return "暂无可抓取的三大财务报表数据。"

    income = latest(income_rows)
    balance = latest(balance_rows)
    cash = latest(cash_rows)
    name = income.get("SECURITY_NAME_ABBR") or balance.get("SECURITY_NAME_ABBR") or cash.get("SECURITY_NAME_ABBR") or code

    gross_profit = sub_num(income.get("TOTAL_OPERATE_INCOME"), income.get("OPERATE_COST"))
    interest_debt = add_nums(
        balance.get("SHORT_LOAN"),
        balance.get("LONG_LOAN"),
        balance.get("BOND_PAYABLE"),
        balance.get("SHORT_BOND_PAYABLE"),
        balance.get("NONCURRENT_LIAB_1YEAR"),
        balance.get("LEASE_LIAB"),
    )
    short_debt = add_nums(balance.get("SHORT_LOAN"), balance.get("SHORT_BOND_PAYABLE"), balance.get("NONCURRENT_LIAB_1YEAR"))
    net_debt = sub_num(interest_debt, balance.get("MONETARYFUNDS")) if interest_debt is not None else None
    fcf = sub_num(cash.get("NETCASH_OPERATE"), cash.get("CONSTRUCT_LONG_ASSET"))
    balance_snapshot = balance_snapshot_chart(str(name), balance_rows) if balance_rows else ""

    income_table = mini_table(
        "利润表",
        [
            ("营业收入", income.get("TOTAL_OPERATE_INCOME")),
            ("营业成本", income.get("OPERATE_COST")),
            ("毛利润", gross_profit),
            ("销售费用", income.get("SALE_EXPENSE")),
            ("管理费用", income.get("MANAGE_EXPENSE")),
            ("研发费用", income.get("RESEARCH_EXPENSE")),
            ("财务费用", income.get("FINANCE_EXPENSE")),
            ("营业利润", income.get("OPERATE_PROFIT")),
            ("利润总额", income.get("TOTAL_PROFIT")),
            ("净利润", income.get("NETPROFIT")),
            ("归母净利润", income.get("PARENT_NETPROFIT")),
            ("扣非净利润", income.get("DEDUCT_PARENT_NETPROFIT")),
        ],
    )
    balance_table = mini_table(
        "资产负债表",
        [
            ("货币资金", balance.get("MONETARYFUNDS")),
            ("应收账款", balance.get("ACCOUNTS_RECE")),
            ("存货", balance.get("INVENTORY")),
            ("固定资产", balance.get("FIXED_ASSET")),
            ("在建工程", balance.get("CIP")),
            ("总资产", balance.get("TOTAL_ASSETS")),
            ("短期借款", balance.get("SHORT_LOAN")),
            ("长期借款", balance.get("LONG_LOAN")),
            ("应付账款", balance.get("ACCOUNTS_PAYABLE")),
            ("合同负债", balance.get("CONTRACT_LIAB")),
            ("总负债", balance.get("TOTAL_LIABILITIES")),
            ("股东权益", balance.get("TOTAL_EQUITY")),
        ],
    )
    balance_metrics = mini_table(
        "重点指标",
        [
            ("资产负债率", pct_ratio(balance.get("TOTAL_LIABILITIES"), balance.get("TOTAL_ASSETS"))),
            ("有息负债", interest_debt),
            ("净负债", net_debt),
            ("流动比率", multiple_ratio(balance.get("TOTAL_CURRENT_ASSETS"), balance.get("TOTAL_CURRENT_LIAB"))),
            ("速动比率", multiple_ratio(sub_num(balance.get("TOTAL_CURRENT_ASSETS"), balance.get("INVENTORY")), balance.get("TOTAL_CURRENT_LIAB"))),
            ("现金短债比", multiple_ratio(balance.get("MONETARYFUNDS"), short_debt)),
            ("应收账款占营收比例", pct_ratio(balance.get("ACCOUNTS_RECE"), income.get("TOTAL_OPERATE_INCOME"))),
            ("存货占总资产比例", pct_ratio(balance.get("INVENTORY"), balance.get("TOTAL_ASSETS"))),
        ],
    )
    cash_table = mini_table(
        "现金流量表",
        [
            ("经营活动现金流", cash.get("NETCASH_OPERATE")),
            ("投资活动现金流", cash.get("NETCASH_INVEST")),
            ("筹资活动现金流", cash.get("NETCASH_FINANCE")),
            ("资本开支", cash.get("CONSTRUCT_LONG_ASSET")),
            ("自由现金流", fcf),
            ("现金及现金等价物变化", cash.get("CCE_ADD")),
        ],
    )
    cash_judgment = mini_table(
        "重点判断",
        [
            ("净利润是否有现金流支撑", "是" if num(cash.get("NETCASH_OPERATE")) is not None and num(income.get("NETPROFIT")) is not None and num(cash.get("NETCASH_OPERATE")) >= num(income.get("NETPROFIT")) else "需关注"),
            ("是否依赖借款维持经营", "需关注" if num(cash.get("NETCASH_FINANCE")) is not None and num(cash.get("NETCASH_FINANCE")) > 0 and num(cash.get("NETCASH_OPERATE") or 0) < 0 else "未见明显依赖"),
            ("是否持续大规模扩产", "需关注" if num(cash.get("CONSTRUCT_LONG_ASSET")) is not None and num(cash.get("NETCASH_OPERATE")) not in (None, 0) and abs(num(cash.get("CONSTRUCT_LONG_ASSET"))) / abs(num(cash.get("NETCASH_OPERATE"))) > 0.5 else "相对可控"),
            ("分红是否超出自由现金流", "需关注" if num(cash.get("ASSIGN_DIVIDEND_PORFIT")) is not None and fcf is not None and num(cash.get("ASSIGN_DIVIDEND_PORFIT")) > fcf else "未见明显超出"),
            ("经营现金流是否长期低于净利润", "看下方对比图"),
        ],
    )

    charts = [
        svg_line_chart("营收与净利润趋势（亿元）", [("营业收入", points(income_rows, "TOTAL_OPERATE_INCOME"), "#0969da"), ("净利润", points(income_rows, "NETPROFIT"), "#2da44e")]),
        svg_line_chart("营收同比增长率", [("营收同比", points(income_rows, "TOTAL_OPERATE_INCOME_YOY", 1), "#0969da")]),
        svg_line_chart("净利润同比增长率", [("净利润同比", points(income_rows, "NETPROFIT_YOY", 1), "#2da44e")]),
        svg_line_chart("毛利率与净利率趋势", [("毛利率", calc_series(income_rows, lambda row: (sub_num(row.get("TOTAL_OPERATE_INCOME"), row.get("OPERATE_COST")) / num(row.get("TOTAL_OPERATE_INCOME")) * 100) if sub_num(row.get("TOTAL_OPERATE_INCOME"), row.get("OPERATE_COST")) is not None and num(row.get("TOTAL_OPERATE_INCOME")) not in (None, 0) else None), "#0969da"), ("净利率", ratio_points(income_rows, "NETPROFIT", "TOTAL_OPERATE_INCOME"), "#2da44e")]),
        svg_line_chart("费用率变化", [("销售费用率", ratio_points(income_rows, "SALE_EXPENSE", "TOTAL_OPERATE_INCOME"), "#0969da"), ("管理费用率", ratio_points(income_rows, "MANAGE_EXPENSE", "TOTAL_OPERATE_INCOME"), "#8250df"), ("研发费用率", ratio_points(income_rows, "RESEARCH_EXPENSE", "TOTAL_OPERATE_INCOME"), "#bf8700"), ("财务费用率", ratio_points(income_rows, "FINANCE_EXPENSE", "TOTAL_OPERATE_INCOME"), "#cf222e")]),
        svg_line_chart("扣非净利润与归母净利润对比（亿元）", [("扣非净利润", points(income_rows, "DEDUCT_PARENT_NETPROFIT"), "#0969da"), ("归母净利润", points(income_rows, "PARENT_NETPROFIT"), "#2da44e")]),
        svg_line_chart("资产结构变化（亿元）", [("货币资金", points(balance_rows, "MONETARYFUNDS"), "#0969da"), ("应收账款", points(balance_rows, "ACCOUNTS_RECE"), "#8250df"), ("存货", points(balance_rows, "INVENTORY"), "#bf8700"), ("固定资产", points(balance_rows, "FIXED_ASSET"), "#2da44e")]),
        svg_line_chart("负债结构变化（亿元）", [("短期借款", points(balance_rows, "SHORT_LOAN"), "#cf222e"), ("长期借款", points(balance_rows, "LONG_LOAN"), "#8250df"), ("应付账款", points(balance_rows, "ACCOUNTS_PAYABLE"), "#0969da"), ("合同负债", points(balance_rows, "CONTRACT_LIAB"), "#2da44e")]),
        svg_line_chart("货币资金与有息负债对比（亿元）", [("货币资金", points(balance_rows, "MONETARYFUNDS"), "#0969da"), ("有息负债", calc_series(balance_rows, lambda row: (add_nums(row.get("SHORT_LOAN"), row.get("LONG_LOAN"), row.get("BOND_PAYABLE"), row.get("SHORT_BOND_PAYABLE"), row.get("NONCURRENT_LIAB_1YEAR"), row.get("LEASE_LIAB")) or 0) / 100000000), "#cf222e")]),
        svg_line_chart("应收账款和存货增长趋势（亿元）", [("应收账款", points(balance_rows, "ACCOUNTS_RECE"), "#0969da"), ("存货", points(balance_rows, "INVENTORY"), "#bf8700")]),
        svg_line_chart("净利润与经营现金流对比（亿元）", [("净利润", points(income_rows, "NETPROFIT"), "#2da44e"), ("经营活动现金流", points(cash_rows, "NETCASH_OPERATE"), "#0969da")]),
        svg_line_chart("三类现金流变化（亿元）", [("经营现金流", points(cash_rows, "NETCASH_OPERATE"), "#0969da"), ("投资现金流", points(cash_rows, "NETCASH_INVEST"), "#bf8700"), ("筹资现金流", points(cash_rows, "NETCASH_FINANCE"), "#8250df")]),
        svg_line_chart("资本开支与自由现金流（亿元）", [("资本开支", points(cash_rows, "CONSTRUCT_LONG_ASSET"), "#cf222e"), ("自由现金流", calc_series(cash_rows, lambda row: (sub_num(row.get("NETCASH_OPERATE"), row.get("CONSTRUCT_LONG_ASSET")) / 100000000 if sub_num(row.get("NETCASH_OPERATE"), row.get("CONSTRUCT_LONG_ASSET")) is not None else None)), "#2da44e")]),
    ]

    return (
        '<style>'
        '.fs-page{font-family:"Microsoft YaHei",Arial,sans-serif;color:#24292f}.fs-page h2{margin:0 0 8px;font-size:26px}.fs-sub{color:#57606a;margin-bottom:16px}.fs-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}.fs-panel{border:1px solid #d0d7de;border-radius:8px;background:#fff;padding:16px;overflow:auto}.fs-panel h3{margin:0 0 12px;font-size:18px}.fs-mini{width:100%;border-collapse:collapse}.fs-mini th,.fs-mini td{border-bottom:1px solid #d8dee4;padding:8px;text-align:left}.fs-mini th{color:#57606a;font-weight:600;width:46%}.fs-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin:12px 0}.fs-card{border:1px solid #d8dee4;border-radius:8px;background:#f6f8fa;padding:12px}.fs-label{color:#57606a;font-size:13px}.fs-value{margin-top:6px;font-weight:800;font-size:18px}.fs-balance-snapshot{position:relative;border:1px solid #d0d7de;border-radius:8px;background:#fff;margin:14px 0;padding:18px;box-shadow:0 1px 2px rgba(27,31,36,.06);overflow:hidden}.fs-snapshot-panel{display:none}.fs-snapshot-panel.is-active{display:block}.fs-snapshot-head{display:flex;align-items:flex-start;justify-content:center;gap:14px;margin-bottom:6px;padding-right:230px}.fs-snapshot-title{text-align:center;font-weight:900;font-size:20px;color:#24292f}.fs-snapshot-date{text-align:center;margin-top:4px;color:#57606a;font-size:13px}.fs-snapshot-nav{position:absolute;right:18px;top:18px;display:flex;gap:14px;color:#4f8ab8;font-weight:700;font-size:13px;white-space:nowrap;z-index:2}.fs-snapshot-nav button{appearance:none;border:0;background:transparent;padding:0;color:#4f8ab8;font:inherit;font-weight:700;cursor:pointer}.fs-snapshot-nav button:hover{color:#0969da}.fs-snapshot-nav button.is-active{color:#0969da;text-decoration:underline}.fs-snapshot-nav button:disabled,.fs-snapshot-nav button.is-disabled{color:#8c959f;cursor:not-allowed;text-decoration:none}.fs-balance-snapshot svg{display:block;width:100%;height:auto;overflow:visible}.fs-balance-snapshot text{fill:#57606a;font-size:13px}.fs-balance-snapshot .fs-bar-value{fill:#24292f;font-weight:800;font-size:14px}.fs-balance-snapshot .fs-bar-label{fill:#57606a;font-size:12px}.fs-balance-snapshot .fs-group-label{fill:#6b7280;font-size:13px;font-weight:800}.fs-balance-snapshot .fs-unit{fill:#6b7280;font-size:12px}.fs-chart-switcher{margin-top:14px}.fs-chart-stage{border:1px solid #d0d7de;border-radius:8px;background:#fff;padding:18px;overflow:hidden}.fs-chart{border:0;background:#fff;padding:0;overflow:hidden}.fs-chart-title{font-weight:900;font-size:22px;margin-bottom:10px}.fs-chart svg{display:block;width:100%;height:auto;max-width:100%;overflow:visible}.fs-chart text{font-size:13px;fill:#57606a}.fs-legend{display:flex;flex-wrap:wrap;gap:8px 14px;color:#57606a;font-size:14px;line-height:1.35;margin-top:6px}.fs-legend span{display:inline-flex;align-items:center;gap:6px;white-space:nowrap}.fs-legend i{display:inline-block;width:10px;height:10px;border-radius:999px;flex:0 0 auto}.fs-chart-tabs{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}.fs-chart-tabs label{border:1px solid #d0d7de;border-radius:999px;background:#fff;color:#24292f;padding:7px 12px;font-size:13px;font-weight:700;cursor:pointer}.fs-chart-tabs label:hover{background:#f6f8fa}.fs-note{margin:12px 0;color:#57606a;font-size:13px;line-height:1.6}.empty{color:#57606a}@media(max-width:720px){.fs-grid{grid-template-columns:1fr}.fs-balance-snapshot{padding:12px}.fs-snapshot-head{display:block;padding-right:0;padding-top:34px}.fs-snapshot-nav{left:12px;right:12px;top:12px;justify-content:center}.fs-balance-snapshot .fs-bar-value{font-size:13px}.fs-chart-stage{padding:12px}.fs-chart-title{font-size:18px}.fs-chart text{font-size:14px}.fs-legend{font-size:12px}.fs-chart-tabs label{font-size:12px;padding:6px 10px}}'
        '</style>'
        '<div class="fs-page">'
        f'<h2>{escape(str(name))} 三大财务报表</h2>'
        f'<div class="fs-sub">股票代码：{escape(code)}；最新报表期：{escape(date_label(income or balance or cash))}</div>'
        '<div class="fs-cards">'
        f'{metric_card("营业收入", income.get("TOTAL_OPERATE_INCOME"))}'
        f'{metric_card("净利润", income.get("NETPROFIT"))}'
        f'{metric_card("经营现金流", cash.get("NETCASH_OPERATE"))}'
        f'{metric_card("自由现金流", fcf)}'
        '</div>'
        f'{balance_snapshot}'
        '<div class="fs-grid">'
        f'{income_table}{balance_table}{balance_metrics}{cash_table}{cash_judgment}'
        '</div>'
        '<div class="fs-note">单位默认显示为亿元；比率类指标按最新一期报表计算。部分公司或行业字段可能为空，页面会保留项目但显示“-”。</div>'
        f'{chart_switcher(charts)}'
        '</div>'
    )


def fetch_business_analysis_html(code: str) -> str:
    code = "".join(ch for ch in code if ch.isdigit())[:6]
    if len(code) != 6:
        raise ValueError("股票代码必须是 6 位数字")

    market_code = eastmoney_market_code(code)
    url = (
        "https://emweb.securities.eastmoney.com/PC_HSF10/BusinessAnalysis/PageAjax?"
        + urllib.parse.urlencode({"code": market_code})
    )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": (
                "https://emweb.securities.eastmoney.com/PC_HSF10/BusinessAnalysis/Index?"
                + urllib.parse.urlencode({"code": market_code, "type": "web"})
            ),
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    scope_rows = data.get("zyfw") or []
    composition_rows = data.get("zygcfx") or []
    name = next(
        (
            row.get("SECURITY_NAME_ABBR")
            for row in composition_rows
            if row.get("SECURITY_NAME_ABBR")
        ),
        code,
    )
    scope = next(
        (
            str(row.get("BUSINESS_SCOPE") or "").strip()
            for row in scope_rows
            if row.get("BUSINESS_SCOPE")
        ),
        "",
    )
    if len(scope) > 520:
        scope = scope[:520].rstrip() + "..."

    latest_date = max((date_label(row) for row in composition_rows if date_label(row)), default="")
    latest_rows = [row for row in composition_rows if date_label(row) == latest_date]
    type_names = {"1": "按行业", "2": "按产品", "3": "按地区"}

    def ratio_text(value: object) -> str:
        value_num = num(value)
        return f"{value_num * 100:.2f}%" if value_num is not None else "-"

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in latest_rows:
        item_name = str(row.get("ITEM_NAME") or "").strip()
        if item_name:
            grouped.setdefault(str(row.get("MAINOP_TYPE") or "其他"), []).append(row)
    for rows in grouped.values():
        rows.sort(key=lambda row: (num(row.get("MBI_RATIO")) or 0, num(row.get("MAIN_BUSINESS_INCOME")) or 0), reverse=True)

    headline_rows = grouped.get("1") or grouped.get("2") or grouped.get("3") or []
    headline_income_values = [num(row.get("MAIN_BUSINESS_INCOME")) for row in headline_rows]
    headline_profit_values = [num(row.get("MAIN_BUSINESS_RPOFIT")) for row in headline_rows]
    headline_income = sum(value for value in headline_income_values if value is not None) if any(value is not None for value in headline_income_values) else None
    headline_profit = sum(value for value in headline_profit_values if value is not None) if any(value is not None for value in headline_profit_values) else None
    headline_margin = headline_profit / headline_income * 100 if headline_income not in (None, 0) and headline_profit is not None else None
    leading_item = headline_rows[0] if headline_rows else {}

    cards = "".join(
        (
            '<div class="ba-card">'
            f'<div class="ba-label">{escape(label)}</div>'
            f'<div class="ba-value">{escape(value)}</div>'
            "</div>"
        )
        for label, value in [
            ("主营收入", fmt_yi(headline_income)),
            ("主营利润", fmt_yi(headline_profit)),
            ("主营毛利率", f"{headline_margin:.2f}%" if headline_margin is not None else "-"),
            (
                "第一大主营",
                (
                    f"{leading_item.get('ITEM_NAME')} "
                    f"{ratio_text(leading_item.get('MBI_RATIO'))}"
                    if leading_item
                    else "-"
                ),
            ),
        ]
    )

    composition_sections: list[str] = []
    for type_code in ("1", "2", "3"):
        rows = grouped.get(type_code) or []
        if not rows:
            continue
        table_rows = "".join(
            "<tr>"
            f"<td><strong>{escape(str(row.get('ITEM_NAME') or '-'))}</strong>"
            f"<span class=\"ba-share\"><i style=\"width:{max(0, min(100, (num(row.get('MBI_RATIO')) or 0) * 100)):.2f}%\"></i></span></td>"
            f"<td>{fmt_yi(row.get('MAIN_BUSINESS_INCOME'))}</td>"
            f"<td>{ratio_text(row.get('MBI_RATIO'))}</td>"
            f"<td>{fmt_yi(row.get('MAIN_BUSINESS_COST'))}</td>"
            f"<td>{fmt_yi(row.get('MAIN_BUSINESS_RPOFIT'))}</td>"
            f"<td>{ratio_text(row.get('GROSS_RPOFIT_RATIO'))}</td>"
            "</tr>"
            for row in rows
        )
        composition_sections.append(
            '<section class="ba-section">'
            f"<h3>{escape(type_names.get(type_code, '其他构成'))}</h3>"
            '<div class="ba-table-wrap"><table class="ba-table"><thead><tr>'
            "<th>主营构成</th><th>主营收入</th><th>营收占比</th><th>主营成本</th><th>主营利润</th><th>毛利率</th>"
            f"</tr></thead><tbody>{table_rows}</tbody></table></div>"
            "</section>"
        )

    scope_html = escape(scope) if scope else "暂无公开主营范围介绍。"
    compositions_html = "".join(composition_sections) or '<div class="ba-empty">暂无主营构成明细。</div>'
    product_text = " ".join(str(row.get("ITEM_NAME") or "") for row in latest_rows).lower()
    business_text = f"{product_text} {scope}".lower()
    tracking_rules = [
        (
            ("集装箱", "航运", "海运", "船舶", "港口"),
            "航运与港口",
            ["SCFI、CCFI及欧美主要航线运价", "红海、苏伊士运河、港口拥堵与绕航情况", "新船交付、拆解量和闲置运力", "单箱收入、货运量、装载率和 EBIT 利润率"],
        ),
        (
            ("白酒", "啤酒", "酒类", "饮料", "食品", "乳业", "调味"),
            "消费品与渠道",
            ["核心单品批价与终端零售价", "经销商/门店数量及渠道库存", "合同负债、预收款与经营现金流", "销量、吨价和高端产品占比"],
        ),
        (
            ("半导体", "芯片", "集成电路", "软件", "人工智能", "云", "通信", "电子"),
            "科技与电子",
            ["下游客户资本开支与订单能见度", "产能利用率、产品价格与出货量", "存货、应收账款和周转天数", "研发投入、研发人员及新品进度"],
        ),
        (
            ("汽车", "电池", "新能源", "光伏", "风电", "充电", "储能"),
            "汽车、新能源与电力",
            ["终端销量、装机量和渗透率", "核心材料价格及单位成本", "在手订单、产能利用率和扩产进度", "补贴、出口和价格竞争变化"],
        ),
        (
            ("化工", "石化", "塑料", "树脂", "金属", "钢", "煤", "矿"),
            "资源、材料与化工",
            ["主要产品价格、价差和开工率", "原材料及能源成本变化", "库存、应收账款和下游需求", "新增产能、检修与项目投产节奏"],
        ),
        (
            ("银行", "证券", "基金", "保险", "信托", "金融"),
            "金融业务",
            ["资产管理规模和客户资产净流入", "利息净收入/手续费收入及费率", "信用减值、资产质量和资本充足率", "市场成交额、风险偏好与政策变化"],
        ),
        (
            ("医药", "医疗", "药品", "生物", "器械", "医院"),
            "医药健康",
            ["核心产品销量、终端价格和市场份额", "研发管线、临床进展和获批节奏", "集采、医保和监管政策影响", "销售费用率与应收账款回款"],
        ),
        (
            ("地产", "房地产", "建筑", "工程", "基建", "水泥"),
            "地产与基建",
            ["新签订单/合同销售和在手订单", "回款、应收账款和合同资产", "有息负债、到期债务和融资成本", "开工率、投资强度和政策支持"],
        ),
        (
            ("运输", "物流", "港口", "航空", "快递", "航运"),
            "交通运输",
            ["运量、客座率和货运量", "运价/票价与燃油成本", "运力投放、船舶/车辆利用率", "跨境贸易和宏观需求变化"],
        ),
        (
            ("电力", "燃气", "供水", "环保", "公用"),
            "公用事业",
            ["发电量、利用小时和上网电价", "燃料成本、来水量和供需格局", "装机投产与资本开支", "应收补贴、电费回款和现金流"],
        ),
        (
            ("农业", "种业", "养殖", "饲料", "渔业", "牧", "猪", "禽"),
            "农林牧渔",
            ["农产品/畜禽价格与供需周期", "出栏量、存栏量和单位养殖成本", "饲料原料价格和疫病风险", "库存、现金流和政策补贴"],
        ),
        (
            ("军工", "航空航天", "导弹", "船舶", "国防"),
            "国防军工",
            ["订单合同、交付节奏和预收款", "产能建设、供应链保障和存货", "军品定价与客户预算安排", "应收账款、回款周期和现金流"],
        ),
        (
            ("游戏", "影视", "传媒", "广告", "出版", "娱乐"),
            "传媒文娱",
            ["用户数、活跃度和付费率", "内容上线排期、票房/流水和爆款表现", "获客成本、广告景气和变现效率", "递延收入、合同负债和现金回款"],
        ),
    ]
    rule_scores = []
    for index, rule in enumerate(tracking_rules):
        keywords = rule[0]
        score = sum(3 for keyword in keywords if keyword in product_text) + sum(
            1 for keyword in keywords if keyword in scope.lower()
        )
        if score:
            rule_scores.append((score, index, rule))
    matched_rules = [rule for _, _, rule in sorted(rule_scores, key=lambda item: (-item[0], item[1]))[:1]]
    if not matched_rules:
        matched_rules = [
            (
                (),
                "主营经营效率",
                ["核心产品销量、单价和市场份额", "原材料、人工及制造成本变化", "订单、产能利用率和项目进度", "应收账款、存货和经营现金流"],
            )
        ]
    tracking_schedule = {
        "航运与港口": (
            ["SCFI、CCFI及欧美主要航线运价", "红海、苏伊士运河、港口拥堵与绕航情况", "新船交付、拆解量和闲置运力"],
            ["单箱收入", "货运量与运力增速、装载率", "EBIT 利润率、经营现金流、分红和资本开支"],
        ),
        "消费品与渠道": (
            ["核心单品批价、终端零售价和渠道库存", "经销商动销、门店数量和促销节奏", "竞品价格及消费景气变化"],
            ["销量、吨价和高端产品占比", "分产品毛利率、销售费用率和合同负债", "经营现金流、库存周转和渠道回款"],
        ),
        "科技与电子": (
            ["行业价格、下游资本开支和订单景气", "产能利用率、交期和核心产品出货", "关键零部件和存储/芯片价格"],
            ["收入增速、ASP、毛利率和客户集中度", "存货、应收账款和周转天数", "研发投入、新品进展和资本开支"],
        ),
        "汽车、新能源与电力": (
            ["终端销量、装机量和渗透率", "锂电材料/组件价格及价格战变化", "订单、排产和出口数据"],
            ["出货量、单价、单位成本和毛利率", "产能利用率、扩产进度和资本开支", "经营现金流、库存和应收账款"],
        ),
        "资源、材料与化工": (
            ["主要产品、原材料和能源价格", "产品价差、开工率和社会库存", "检修、投产与行业供给变化"],
            ["销量、售价、单位成本和毛利率", "库存、应收账款和经营现金流", "新增产能、资本开支和项目回报"],
        ),
        "金融业务": (
            ["市场成交额、两融余额和风险偏好", "基金申赎、客户资产流入和利率变化", "监管政策与资本市场制度变化"],
            ["资产管理规模、利息/手续费收入和费率", "信用减值、资产质量和资本充足率", "ROE、分红能力和资本补充安排"],
        ),
        "医药健康": (
            ["终端销售、招标挂网和集采价格", "临床试验、审批与新产品上市进度", "医保、集采和行业监管政策"],
            ["核心产品收入、毛利率和市场份额", "研发费用率、销售费用率和研发管线", "应收账款、库存和经营现金流"],
        ),
        "地产与基建": (
            ["合同销售/新签订单和开工数据", "土地、融资政策和信用利差", "回款、竣工与地方投资进度"],
            ["收入确认、在手订单和毛利率", "合同资产、应收账款和经营现金流", "有息负债、到期债务和资本开支"],
        ),
        "交通运输": (
            ["运量、票价/运价和燃油成本", "航线、运力投放与客座率", "跨境贸易和宏观需求变化"],
            ["货运量/客运量、单位收入和装载率", "毛利率、经营现金流和租赁负债", "运力扩张、资本开支和分红"],
        ),
        "公用事业": (
            ["电力负荷、燃料价格、来水量和天气", "上网电价、现货电价和供需变化", "装机投产与限电情况"],
            ["发电量、利用小时和单位成本", "电价、毛利率和经营现金流", "资本开支、负债率和分红覆盖"],
        ),
        "农林牧渔": (
            ["农产品、畜禽和饲料原料价格", "存栏、出栏和疫病信息", "天气、政策补贴和进口数据"],
            ["销量、单价、单位养殖成本和毛利率", "存货、生物资产和经营现金流", "产能扩张、资本开支和负债"],
        ),
        "国防军工": (
            ["行业订单、装备采购和预算信息", "供应链保障、原材料和交付节奏", "军工改革和政策催化"],
            ["在手订单、收入确认和毛利率", "存货、预收款、应收账款与回款", "产能建设、资本开支和经营现金流"],
        ),
        "传媒文娱": (
            ["用户活跃、流水/票房和内容上线排期", "广告景气、获客成本和竞品表现", "监管、版号和平台政策"],
            ["用户付费率、ARPU、收入和毛利率", "销售费用率、递延收入和现金回款", "内容投入、资本开支和经营现金流"],
        ),
        "主营经营效率": (
            ["核心产品价格、销量和行业景气", "订单、产能利用率和原材料成本", "主要政策、供需和竞争格局变化"],
            ["分业务收入、毛利率和市场份额", "存货、应收账款和经营现金流", "资本开支、负债和分红覆盖"],
        ),
    }
    watch_cards = [
        (
            "主营结构变化",
            ["核心产品价格、销量及渠道/订单高频变化", "行业供需、竞争格局和政策变化"],
            ["各业务收入占比与同比增速", "分业务毛利率和第一大业务集中度", "主营利润与归母净利润匹配度"],
        )
    ] + [
        (title, *tracking_schedule.get(title, (items[:2], items[2:])))
        for _, title, items in matched_rules
    ]
    watch_html = "".join(
        '<article class="ba-watch-card">'
        f"<h4>{escape(title)}</h4>"
        '<div class="ba-watch-frequency"><strong>每周看</strong>'
        f"<ul>{''.join(f'<li>{escape(item)}</li>' for item in weekly_items)}</ul></div>"
        '<div class="ba-watch-frequency"><strong>每季度看</strong>'
        f"<ul>{''.join(f'<li>{escape(item)}</li>' for item in quarterly_items)}</ul></div>"
        "</article>"
        for title, weekly_items, quarterly_items in watch_cards
    )
    return (
        '<style>'
        '.business-page{font-family:"Microsoft YaHei",Arial,sans-serif;color:#24292f}'
        '.business-page h2{margin:0 0 6px;font-size:26px}.ba-sub{color:#57606a;font-size:13px;margin-bottom:16px}'
        '.ba-intro{border-left:4px solid #0969da;background:#f6f8fa;padding:14px 16px;line-height:1.75;color:#334155}'
        '.ba-intro strong{display:block;color:#24292f;margin-bottom:5px}.ba-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin:14px 0}'
        '.ba-card{border:1px solid #d8dee4;border-radius:8px;background:#fff;padding:12px}.ba-label{font-size:13px;color:#57606a}.ba-value{margin-top:6px;font-size:18px;font-weight:800}'
        '.ba-section{margin-top:18px}.ba-section h3{margin:0 0 10px;font-size:18px}.ba-table-wrap{overflow-x:auto;border:1px solid #d8dee4;border-radius:8px}'
        '.ba-table{width:100%;min-width:760px;border-collapse:collapse;background:#fff}.ba-table th,.ba-table td{padding:10px 12px;border-bottom:1px solid #d8dee4;text-align:right;font-size:13px;white-space:nowrap}.ba-table th{background:#f6f8fa;color:#57606a;font-weight:700}.ba-table th:first-child,.ba-table td:first-child{text-align:left;white-space:normal;min-width:170px}.ba-table tr:last-child td{border-bottom:0}'
        '.ba-share{display:block;height:5px;margin-top:6px;border-radius:999px;background:#eaeef2;overflow:hidden}.ba-share i{display:block;height:100%;border-radius:inherit;background:#0969da}.ba-empty{color:#57606a;padding:12px 0}.ba-note{margin-top:14px;color:#57606a;font-size:12px;line-height:1.6}'
        '.ba-watch{margin-top:20px;border-top:1px solid #d8dee4;padding-top:18px}.ba-watch h3{margin:0 0 5px;font-size:18px}.ba-watch-sub{margin:0 0 12px;color:#57606a;font-size:13px;line-height:1.55}.ba-watch-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:10px}.ba-watch-card{border:1px solid #d8dee4;border-top:3px solid #0f766e;border-radius:8px;background:#f8fafc;padding:12px}.ba-watch-card h4{margin:0 0 10px;color:#0f766e;font-size:15px}.ba-watch-frequency{padding-top:10px;margin-top:10px;border-top:1px solid #d8dee4}.ba-watch-frequency:first-of-type{padding-top:0;margin-top:0;border-top:0}.ba-watch-frequency strong{color:#57606a;font-size:13px}.ba-watch-card ul{margin:4px 0 0;padding-left:18px;color:#334155;font-size:13px;line-height:1.7}'
        '@media(max-width:720px){.business-page h2{font-size:22px}.ba-table th,.ba-table td{padding:8px 9px}.ba-value{font-size:16px}}'
        '</style>'
        '<div class="business-page">'
        f'<h2>{escape(str(name))} 主营业务分析</h2>'
        f'<div class="ba-sub">股票代码：{escape(code)}；最新主营构成报告期：{escape(latest_date or "-")}</div>'
        f'<section class="ba-intro"><strong>公司主营介绍</strong>{scope_html}</section>'
        f'<div class="ba-cards">{cards}</div>'
        f'{compositions_html}'
        '<section class="ba-watch"><h3>最实用的跟踪顺序</h3><p class="ba-watch-sub">先用每周数据观察景气、价格与供需，再在季报期复核量、价、成本、利润和现金流。</p>'
        f'<div class="ba-watch-grid">{watch_html}</div></section>'
        '<div class="ba-note">数据来源：东方财富 F10 公司主营构成。金额按亿元展示；占比、毛利率按公司最新披露口径计算或展示，部分公司/报告期可能为空。</div>'
        '</div>'
    )


def fetch_broker_forecast_html(code: str) -> str:
    code = "".join(ch for ch in code if ch.isdigit())[:6]
    if len(code) != 6:
        raise ValueError("股票代码必须是 6 位数字")
    market_code = eastmoney_market_code(code)
    url = (
        "https://emweb.eastmoney.com/PC_HSF10/ProfitForecast/PageAjax?"
        + urllib.parse.urlencode({"code": market_code})
    )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": f"https://emweb.eastmoney.com/pc_hsf10/ProfitForecast/Index?code={market_code}&type=soft",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    ratings = data.get("pjtj") or []
    stats = data.get("yctj_chart") or data.get("yctj_list") or []
    details = data.get("ycmx") or []

    sections: list[str] = []
    if ratings:
        rating = next((item for item in ratings if item.get("DATE_TYPE") == "6月内"), ratings[-1])
        sections.append(
            '<div class="broker-summary">'
            f"评级区间：{escape(str(rating.get('DATE_TYPE', '-')))}；"
            f"综合评级：<strong>{escape(str(rating.get('COMPRE_RATING', '-')))}</strong>；"
            f"机构家数：{escape(str(rating.get('RATING_ORG_NUM', '-')))}"
            "</div>"
        )

    if stats:
        rows = []
        for item in stats[:4]:
            rows.append(
                "<tr>"
                f"<td>{escape(str(item.get('YEAR', '-')))}{escape(str(item.get('YEAR_MARK', '')))}</td>"
                f"<td>{fmt_yi(item.get('TOTAL_OPERATE_INCOME'))}</td>"
                f"<td>{fmt_yi(item.get('PARENT_NETPROFIT'))}</td>"
                f"<td>{fmt_num(item.get('EPS'))}</td>"
                f"<td>{fmt_num(item.get('ROE'))}%</td>"
                "</tr>"
            )
        sections.append(
            "<div><strong>预测统计/一致预期</strong></div>"
            "<table><thead><tr><th>年份</th><th>营业收入</th><th>归母净利润</th><th>EPS</th><th>ROE</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )

    if details:
        rows = []
        for item in details:
            rows.append(
                "<tr>"
                f"<td>{escape(str(item.get('PUBLISH_DATE', '-') or '-')[:10])}</td>"
                f"<td>{escape(str(item.get('ORG_NAME_ABBR', '-') or '-'))}</td>"
                f"<td>{escape(str(item.get('RESEARCHER', '-') or '-'))}</td>"
                f"<td>{escape(str(item.get('RATING', '-') or '-'))}</td>"
                f"<td>{escape(str(item.get('YEAR2', '-') or '-'))}E</td>"
                f"<td>{fmt_yi(item.get('PARENT_NETPROFIT2'))}</td>"
                f"<td>{fmt_num(item.get('EPS2'))}</td>"
                f"<td>{escape(str(item.get('YEAR3', '-') or '-'))}E</td>"
                f"<td>{fmt_yi(item.get('PARENT_NETPROFIT3'))}</td>"
                f"<td>{fmt_num(item.get('EPS3'))}</td>"
                "</tr>"
            )
        sections.append(
            f"<div><strong>机构预测明细（{len(details)} 条，已全部纳入）</strong></div>"
            "<table><thead><tr><th>日期</th><th>机构</th><th>研究员</th><th>评级</th><th>年份</th><th>净利润</th><th>EPS</th><th>年份</th><th>净利润</th><th>EPS</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )

    if not sections:
        return "该股暂无可收集到的券商盈利预测。"
    return "".join(sections) + "<div class=\"finance-note\">来源：东方财富 F10 盈利预测；预测数据来自各机构研究报告摘录。</div>"


class UpdateHandler(BaseHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path not in {"/broker", "/financials", "/business"}:
            self.send_json(404, {"ok": False, "error": "Unknown endpoint"})
            return
        query = urllib.parse.parse_qs(parsed.query)
        code = (query.get("code") or [""])[0]
        try:
            if parsed.path == "/broker":
                html = fetch_broker_forecast_html(code)
            elif parsed.path == "/business":
                html = fetch_business_analysis_html(code)
            else:
                html = fetch_financial_statements_html(code)
            self.send_json(200, {"ok": True, "html": html})
        except Exception as exc:
            self.send_json(500, {"ok": False, "error": str(exc)})

    def do_POST(self) -> None:
        if self.path != "/update":
            self.send_json(404, {"ok": False, "error": "Unknown endpoint"})
            return
        try:
            result = subprocess.run(
                [sys.executable, str(SCRIPT)],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=240,
            )
            if result.returncode != 0:
                self.send_json(
                    500,
                    {
                        "ok": False,
                        "error": result.stderr[-2000:] or result.stdout[-2000:] or "Script failed",
                    },
                )
                return
            self.send_json(200, {"ok": True, "output": result.stdout[-2000:]})
        except Exception as exc:
            self.send_json(500, {"ok": False, "error": str(exc)})

    def send_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> int:
    server = ThreadingHTTPServer((HOST, PORT), UpdateHandler)
    print(f"更新服务已启动：http://{HOST}:{PORT}")
    print("现在可以在 HTML 报告里点击“抓取最新”。按 Ctrl+C 关闭服务。")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
