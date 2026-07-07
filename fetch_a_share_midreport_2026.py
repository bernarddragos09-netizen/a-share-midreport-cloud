#!/usr/bin/env python3
"""
Fetch A-share interim report disclosure schedule from CNINFO and summarize it by day.

The script uses only Python standard library modules so it can run immediately
after installing Python.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import parse, request


BASE_URL = "https://www.cninfo.com.cn/new"
REFERER = "https://www.cninfo.com.cn/new/commonUrl?url=data/yypl"

FIELD_NAMES = {
    "seccode": "stock_code",
    "secname": "stock_name",
    "f001d_0102": "report_period",
    "f002d_0102": "first_appointment_date",
    "f003d_0102": "first_change_date",
    "f004d_0102": "second_change_date",
    "f005d_0102": "third_change_date",
    "f006d_0102": "actual_disclosure_date",
}

DATE_FIELD_MAP = {
    "actual": "f006d_0102",
    "first": "f002d_0102",
    "change1": "f003d_0102",
    "change2": "f004d_0102",
    "change3": "f005d_0102",
}


def post_json(path: str, data: dict[str, Any], timeout: int = 20, retries: int = 3) -> Any:
    payload = parse.urlencode(data).encode("utf-8")
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        req = request.Request(
            BASE_URL + path,
            data=payload,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": REFERER,
                "Origin": "https://www.cninfo.com.cn",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            print(
                f"Request failed ({attempt}/{retries}) for {path}: {exc}",
                file=sys.stderr,
            )
            if attempt < retries:
                time.sleep(1.5 * attempt)

    raise RuntimeError(f"Request failed after {retries} retries: {path}") from last_error


def get_sections() -> list[dict[str, str]]:
    sections = post_json("/information/getSelectData", {"rows": 20})
    if not isinstance(sections, list):
        raise RuntimeError(f"Unexpected section response: {sections!r}")
    return sections


def pick_latest_midreport_section(sections: list[dict[str, str]]) -> str:
    for item in sections:
        label = item.get("value1", "")
        if "半年" in label or "中报" in label:
            return item["value0"]
    raise RuntimeError("No interim/half-year report period was found.")


def final_appointment_date(row: dict[str, str]) -> str:
    for key in ("f006d_0102", "f005d_0102", "f004d_0102", "f003d_0102", "f002d_0102"):
        value = row.get(key, "")
        if value:
            return value
    return ""


def normalize_row(row: dict[str, Any]) -> dict[str, str]:
    return {output: str(row.get(source, "") or "").strip() for source, output in FIELD_NAMES.items()}


def fetch_rows(section: str, market: str, page_size: int, sleep_seconds: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page_num = 1
    total_pages = None
    total_rows = None

    print(f"Fetching CNINFO rows: section={section}, market={market}", file=sys.stderr)
    while True:
        data = post_json(
            "/information/getPrbookInfo",
            {
                "sectionTime": section,
                "firstTime": "",
                "lastTime": "",
                "market": market,
                "stockCode": "",
                "orderClos": "",
                "isDesc": "",
                "pagesize": page_size,
                "pagenum": page_num,
            },
        )
        page_rows = data.get("prbookinfos") or []
        rows.extend(page_rows)
        total_pages = data.get("totalPages", total_pages)
        total_rows = data.get("totalRows", total_rows)

        print(
            f"Fetched page {page_num}/{total_pages or '?'}: "
            f"{len(page_rows)} rows, total {len(rows)}",
            file=sys.stderr,
        )

        if total_pages is not None and page_num >= int(total_pages):
            break
        if total_rows is not None and len(rows) >= int(total_rows):
            rows = rows[: int(total_rows)]
            break
        if not data.get("hasNextPage"):
            break
        page_num += 1
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    return rows


def choose_stat_date(row: dict[str, Any], mode: str) -> str:
    if mode == "final":
        return final_appointment_date(row)
    return str(row.get(DATE_FIELD_MAP[mode], "") or "").strip()


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_markdown_report(
    path: Path,
    section: str,
    market: str,
    date_mode: str,
    total_rows: int,
    skipped_rows: int,
    daily_rows: list[dict[str, str]],
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# A股中期财报公布日期统计",
        "",
        f"- 数据源：巨潮资讯网预约披露页面（CNINFO）",
        f"- 报告期：{section}",
        f"- 市场范围：{market}",
        f"- 统计口径：{date_mode}",
        f"- 抓取时间：{now}",
        f"- 公司记录数：{total_rows}",
        f"- 未纳入每日统计的空日期记录数：{skipped_rows}",
        "",
        "## 每日公布家数",
        "",
        "| 日期 | 家数 |",
        "| --- | ---: |",
    ]
    lines.extend(f"| {row['date']} | {row['company_count']} |" for row in daily_rows)
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def build_company_groups(
    raw_rows: list[dict[str, Any]], date_mode: str
) -> dict[str, list[dict[str, str]]]:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in raw_rows:
        date = choose_stat_date(row, date_mode)
        if not date:
            continue
        groups[date].append(
            {
                "stock_code": str(row.get("seccode", "") or "").strip(),
                "stock_name": str(row.get("secname", "") or "").strip(),
            }
        )

    for companies in groups.values():
        companies.sort(key=lambda item: item["stock_code"])
    return dict(groups)


def write_html_report(
    path: Path,
    section: str,
    market: str,
    date_mode: str,
    total_rows: int,
    skipped_rows: int,
    daily_rows: list[dict[str, str]],
    company_groups: dict[str, list[dict[str, str]]],
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows_html = []
    for row in daily_rows:
        date = row["date"]
        count = row["company_count"]
        companies = company_groups.get(date, [])
        company_items = "\n".join(
            "<li><span class=\"code\">{code}</span><span>{name}</span></li>".format(
                code=html.escape(company["stock_code"]),
                name=html.escape(company["stock_name"]),
            )
            for company in companies
        )
        rows_html.append(
            """
            <tr>
              <td class="date">{date}</td>
              <td class="count">
                <strong>{count}</strong>
                <details>
                  <summary>展开企业列表</summary>
                  <ul class="company-list">
                    {company_items}
                  </ul>
                </details>
              </td>
            </tr>
            """.format(
                date=html.escape(date),
                count=html.escape(count),
                company_items=company_items,
            )
        )

    document = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>A股中期财报公布日期统计</title>
  <style>
    :root {{
      color-scheme: light;
      font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
      background: #f6f7fb;
      color: #1f2937;
    }}
    body {{
      margin: 0;
      padding: 28px;
    }}
    main {{
      max-width: 980px;
      margin: 0 auto;
    }}
    h1 {{
      margin: 0 0 14px;
      font-size: 28px;
      letter-spacing: 0;
    }}
    .meta {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 10px;
      margin: 16px 0 22px;
    }}
    .meta div {{
      background: #ffffff;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      padding: 10px 12px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: #ffffff;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      overflow: hidden;
    }}
    th, td {{
      border-bottom: 1px solid #e5e7eb;
      padding: 12px 14px;
      vertical-align: top;
      text-align: left;
    }}
    th {{
      background: #eef2f7;
      font-weight: 700;
    }}
    tr:last-child td {{
      border-bottom: 0;
    }}
    .date {{
      width: 180px;
      white-space: nowrap;
      font-variant-numeric: tabular-nums;
    }}
    .count strong {{
      display: inline-block;
      min-width: 64px;
      font-size: 18px;
      color: #0f766e;
    }}
    details {{
      margin-top: 8px;
    }}
    summary {{
      display: inline-flex;
      align-items: center;
      cursor: pointer;
      user-select: none;
      border: 1px solid #2563eb;
      color: #1d4ed8;
      background: #eff6ff;
      border-radius: 6px;
      padding: 6px 10px;
      font-size: 14px;
      line-height: 1.2;
    }}
    summary:hover {{
      background: #dbeafe;
    }}
    .company-list {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 6px 14px;
      margin: 12px 0 2px;
      padding: 0;
      list-style: none;
    }}
    .company-list li {{
      border: 1px solid #e5e7eb;
      border-radius: 6px;
      padding: 7px 9px;
      background: #fafafa;
    }}
    .code {{
      display: inline-block;
      width: 70px;
      color: #475569;
      font-family: Consolas, "Courier New", monospace;
      font-variant-numeric: tabular-nums;
    }}
  </style>
</head>
<body>
  <main>
    <h1>A股中期财报公布日期统计</h1>
    <section class="meta">
      <div>数据源：巨潮资讯网预约披露页面（CNINFO）</div>
      <div>报告期：{section}</div>
      <div>市场范围：{market}</div>
      <div>统计口径：{date_mode}</div>
      <div>抓取时间：{now}</div>
      <div>公司记录数：{total_rows}</div>
      <div>空日期记录数：{skipped_rows}</div>
    </section>
    <table>
      <thead>
        <tr>
          <th>日期</th>
          <th>公布家数 / 企业列表</th>
        </tr>
      </thead>
      <tbody>
        {rows}
      </tbody>
    </table>
  </main>
</body>
</html>
""".format(
        section=html.escape(section),
        market=html.escape(market),
        date_mode=html.escape(date_mode),
        now=html.escape(now),
        total_rows=total_rows,
        skipped_rows=skipped_rows,
        rows="\n".join(rows_html),
    )
    path.write_text(document, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="统计 A 股中期/半年报公布日期：哪些天公布多少家公司。"
    )
    parser.add_argument(
        "--section",
        default="auto",
        help="报告期，例如 2025-06-30；默认 auto，自动选择最新可用半年报。",
    )
    parser.add_argument(
        "--market",
        default="szsh",
        choices=["szsh", "sz", "szmb", "cyb", "sh", "shmb", "kcb", "bj"],
        help="市场范围：szsh=深沪京，sz=深市，sh=沪市，bj=北交所等。",
    )
    parser.add_argument(
        "--date-field",
        default="actual",
        choices=["actual", "first", "change1", "change2", "change3", "final"],
        help="统计日期字段：actual=实际披露，first=首次预约，final=实际披露优先否则最后一次预约。",
    )
    parser.add_argument("--page-size", type=int, default=500, help="每页抓取条数。")
    parser.add_argument("--sleep", type=float, default=0.2, help="翻页请求间隔秒数。")
    parser.add_argument("--out-dir", default="a_share_midreport_output", help="输出目录。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.section == "auto":
        print("Fetching available report periods from CNINFO...", file=sys.stderr)
        sections = get_sections()
        section = pick_latest_midreport_section(sections)
    else:
        section = args.section

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_rows = fetch_rows(section, args.market, args.page_size, args.sleep)
    detail_rows = [normalize_row(row) for row in raw_rows]

    counts: Counter[str] = Counter()
    skipped_rows = 0
    for row in raw_rows:
        date = choose_stat_date(row, args.date_field)
        if date:
            counts[date] += 1
        else:
            skipped_rows += 1

    daily_rows = [
        {"date": date, "company_count": str(count)}
        for date, count in sorted(counts.items())
    ]

    suffix = f"{section}_{args.market}_{args.date_field}".replace("-", "")
    detail_path = out_dir / f"detail_{suffix}.csv"
    daily_path = out_dir / f"daily_count_{suffix}.csv"
    report_path = out_dir / f"report_{suffix}.md"
    html_report_path = out_dir / f"report_{suffix}.html"
    company_groups = build_company_groups(raw_rows, args.date_field)

    write_csv(detail_path, detail_rows, list(FIELD_NAMES.values()))
    write_csv(daily_path, daily_rows, ["date", "company_count"])
    write_markdown_report(
        report_path,
        section,
        args.market,
        args.date_field,
        len(raw_rows),
        skipped_rows,
        daily_rows,
    )
    write_html_report(
        html_report_path,
        section,
        args.market,
        args.date_field,
        len(raw_rows),
        skipped_rows,
        daily_rows,
        company_groups,
    )

    print(f"Done. Detail CSV: {detail_path}")
    print(f"Done. Daily count CSV: {daily_path}")
    print(f"Done. Markdown report: {report_path}")
    print(f"Done. Expandable HTML report: {html_report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
