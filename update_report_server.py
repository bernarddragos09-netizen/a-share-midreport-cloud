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


HOST = "127.0.0.1"
PORT = 8765
ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "fetch_2026_midreport_upcoming_sse.py"


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
        if parsed.path != "/broker":
            self.send_json(404, {"ok": False, "error": "Unknown endpoint"})
            return
        query = urllib.parse.parse_qs(parsed.query)
        code = (query.get("code") or [""])[0]
        try:
            html = fetch_broker_forecast_html(code)
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
