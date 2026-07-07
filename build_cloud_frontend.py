#!/usr/bin/env python3
"""Build the frontend HTML used by the cloud FastAPI app."""

from __future__ import annotations

import csv
import html as htmlmod
import re
from collections import defaultdict
from pathlib import Path

from fetch_2026_midreport_upcoming_sse import fetch_financial_lookup, write_html_report


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "a_share_midreport_2026_upcoming_sse"
CLOUD_FRONTEND_DIR = ROOT / "a_share_midreport_cloud" / "frontend"


def clean_html_text(value: str) -> str:
    return htmlmod.unescape(re.sub(r"<[^>]+>", "", value or "")).strip()


def load_sector_lookup() -> dict[str, list[str]]:
    report_path = DATA_DIR / "report_sse_2026_midreport.html"
    if not report_path.exists():
        return {}
    document = report_path.read_text(encoding="utf-8")
    lookup: dict[str, list[str]] = {}
    for match in re.finditer(r'<tr class="company-row" id="company-([0-9]{6})".*?</tr>', document, re.S):
        code = match.group(1)
        sectors = [
            clean_html_text(item)
            for item in re.findall(r'<span class="sector-tag">(.*?)</span>', match.group(0), re.S)
        ]
        if sectors:
            lookup[code] = sectors
    return lookup


def load_report_rows() -> tuple[list[dict[str, str]], dict[str, list[dict[str, str]]], int]:
    detail_path = DATA_DIR / "detail_sse_2026_midreport.csv"
    with detail_path.open(encoding="utf-8-sig", newline="") as file:
        detail_rows = list(csv.DictReader(file))

    counts: dict[str, int] = defaultdict(int)
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in detail_rows:
        date = row.get("stat_date", "")
        if date:
            counts[date] += 1
            groups[date].append(
                {"stock_code": row.get("stock_code", ""), "stock_name": row.get("stock_name", "")}
            )
    for companies in groups.values():
        companies.sort(key=lambda item: item["stock_code"])
    daily_rows = [{"date": date, "company_count": str(counts[date])} for date in sorted(counts)]
    return daily_rows, dict(groups), len(detail_rows)


def main() -> int:
    CLOUD_FRONTEND_DIR.mkdir(parents=True, exist_ok=True)
    daily_rows, groups, total_rows = load_report_rows()
    sector_lookup = load_sector_lookup()
    financial_lookup = fetch_financial_lookup()
    write_html_report(
        CLOUD_FRONTEND_DIR / "index.html",
        daily_rows,
        groups,
        total_rows,
        financial_lookup,
        sector_lookup,
        broker_lookup={},
        static_site=False,
        api_base="/api",
    )
    print(f"Cloud frontend written: {CLOUD_FRONTEND_DIR / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
