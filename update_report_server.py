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
    width = 680
    height = 230
    left = 54
    right = 20
    top = 28
    bottom = 42
    labels = [label for label, _ in series[0][1]]
    count = max(1, len(labels) - 1)

    def xy(index: int, value: float) -> tuple[float, float]:
        x = left + index * ((width - left - right) / count)
        y = top + (max_v - value) / (max_v - min_v) * (height - top - bottom)
        return x, y

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

    x_labels = "".join(
        f'<text x="{left + i * ((width - left - right) / count):.1f}" y="{height - 14}" text-anchor="middle">{escape(label[2:7])}</text>'
        for i, label in enumerate(labels)
    )
    return (
        '<div class="fs-chart">'
        f'<div class="fs-chart-title">{escape(title)}</div>'
        f'<svg viewBox="0 0 {width} {height}" role="img">'
        f'<line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#d0d7de"/>'
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#d0d7de"/>'
        f'{"".join(polylines)}{"".join(dots)}{x_labels}'
        '</svg>'
        f'<div class="fs-legend">{"".join(legends)}</div>'
        "</div>"
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
        '.fs-page{font-family:"Microsoft YaHei",Arial,sans-serif;color:#24292f}.fs-page h2{margin:0 0 8px;font-size:26px}.fs-sub{color:#57606a;margin-bottom:16px}.fs-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}.fs-panel{border:1px solid #d0d7de;border-radius:8px;background:#fff;padding:16px;overflow:auto}.fs-panel h3{margin:0 0 12px;font-size:18px}.fs-mini{width:100%;border-collapse:collapse}.fs-mini th,.fs-mini td{border-bottom:1px solid #d8dee4;padding:8px;text-align:left}.fs-mini th{color:#57606a;font-weight:600;width:46%}.fs-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin:12px 0}.fs-card{border:1px solid #d8dee4;border-radius:8px;background:#f6f8fa;padding:12px}.fs-label{color:#57606a;font-size:13px}.fs-value{margin-top:6px;font-weight:800;font-size:18px}.fs-chart{border:1px solid #d0d7de;border-radius:8px;background:#fff;padding:12px;overflow:hidden}.fs-chart-title{font-weight:800;margin-bottom:8px}.fs-chart svg{display:block;width:100%;height:auto;max-width:100%;overflow:visible}.fs-chart text{font-size:12px;fill:#57606a}.fs-legend{display:flex;flex-wrap:wrap;gap:6px 10px;color:#57606a;font-size:12px;line-height:1.3}.fs-legend span{display:inline-flex;align-items:center;gap:5px;white-space:nowrap}.fs-legend i{display:inline-block;width:9px;height:9px;border-radius:999px;flex:0 0 auto}.fs-note{margin:12px 0;color:#57606a;font-size:13px;line-height:1.6}.empty{color:#57606a}@media(max-width:720px){.fs-grid{grid-template-columns:1fr}.fs-chart{padding:10px}.fs-chart text{font-size:13px}.fs-legend{font-size:12px}}'
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
        '<div class="fs-grid">'
        f'{income_table}{balance_table}{balance_metrics}{cash_table}{cash_judgment}'
        '</div>'
        '<div class="fs-note">单位默认显示为亿元；比率类指标按最新一期报表计算。部分公司或行业字段可能为空，页面会保留项目但显示“-”。</div>'
        '<div class="fs-grid">'
        f'{"".join(charts)}'
        '</div>'
        '</div>'
    )


def fetch_broker_forecast_html(code: str) -> str:
    code = "".join(ch for ch in code if ch.isdigit())[:6]
    if len(code) != 6:
        raise ValueError("股票代码必须是 6 位数字")
    market_code = f"SH{code}"
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
        if parsed.path not in {"/broker", "/financials"}:
            self.send_json(404, {"ok": False, "error": "Unknown endpoint"})
            return
        query = urllib.parse.parse_qs(parsed.query)
        code = (query.get("code") or [""])[0]
        try:
            if parsed.path == "/broker":
                html = fetch_broker_forecast_html(code)
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
