#!/usr/bin/env python3
"""Build a GitHub Pages friendly static version of the midreport dashboard."""

from __future__ import annotations

import csv
import html as htmlmod
import json
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from fetch_2026_midreport_upcoming_sse import fetch_financial_lookup, write_html_report
from update_report_server import fetch_broker_forecast_html


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "a_share_midreport_2026_upcoming_sse"
STATIC_DIR = ROOT / "a_share_midreport_2026_static_site"
CACHE_PATH = DATA_DIR / "broker_forecast_cache.json"


def clean_html_text(value: str) -> str:
    return htmlmod.unescape(re.sub(r"<[^>]+>", "", value or "")).strip()


def load_sector_lookup() -> dict[str, list[str]]:
    """Reuse sectors from the latest generated HTML to avoid another quote crawl."""
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


def load_report_rows() -> tuple[list[dict[str, str]], dict[str, list[dict[str, str]]], int, list[str]]:
    detail_path = DATA_DIR / "detail_sse_2026_midreport.csv"
    with detail_path.open(encoding="utf-8-sig", newline="") as file:
        detail_rows = list(csv.DictReader(file))

    counts: dict[str, int] = defaultdict(int)
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    codes: list[str] = []
    for row in detail_rows:
        code = row.get("stock_code", "")
        date = row.get("stat_date", "")
        if code:
            codes.append(code)
        if date:
            counts[date] += 1
            groups[date].append({"stock_code": code, "stock_name": row.get("stock_name", "")})
    for companies in groups.values():
        companies.sort(key=lambda item: item["stock_code"])
    daily_rows = [{"date": date, "company_count": str(counts[date])} for date in sorted(counts)]
    return daily_rows, dict(groups), len(detail_rows), sorted(set(codes))


def load_cache() -> dict[str, str]:
    if not CACHE_PATH.exists():
        return {}
    return json.loads(CACHE_PATH.read_text(encoding="utf-8"))


def save_cache(cache: dict[str, str]) -> None:
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_one_broker(code: str) -> tuple[str, str]:
    try:
        return code, fetch_broker_forecast_html(code)
    except Exception as exc:
        return code, f"券商预测抓取失败：{htmlmod.escape(str(exc))}"


def build_broker_lookup(codes: list[str]) -> dict[str, str]:
    cache = load_cache()
    missing = [code for code in codes if code not in cache]
    if not missing:
        print(f"Broker forecast cache complete: {len(cache)} codes")
        return cache

    print(f"Fetching broker forecasts: {len(missing)} missing / {len(codes)} total")
    completed = 0
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(fetch_one_broker, code): code for code in missing}
        for future in as_completed(futures):
            code, forecast_html = future.result()
            cache[code] = forecast_html
            completed += 1
            if completed % 50 == 0 or completed == len(missing):
                save_cache(cache)
                print(f"  cached {completed}/{len(missing)}")
            time.sleep(0.02)
    save_cache(cache)
    return cache


def write_readme() -> None:
    readme = """# A Share 2026 Midreport Static Site

这个目录是可直接发布的静态网站。

## GitHub Pages 发布方法

1. 新建一个 GitHub 仓库。
2. 把本目录里的 `index.html` 上传到仓库根目录。
3. 打开仓库 `Settings` -> `Pages`。
4. `Build and deployment` 选择 `Deploy from a branch`。
5. Branch 选择 `main`，目录选择 `/root`，保存。
6. 等几十秒，GitHub 会给你一个可分享的网址。

这个静态版不依赖你电脑上的 Python 服务；券商预测数据已预先写入页面。
如果以后要更新数据，在本地重新运行：

```bash
python build_static_site.py
```
"""
    (STATIC_DIR / "README.md").write_text(readme, encoding="utf-8")


def main() -> int:
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    daily_rows, groups, total_rows, codes = load_report_rows()
    sector_lookup = load_sector_lookup()
    print(f"Loaded report rows: {total_rows}; sectors: {len(sector_lookup)}")
    financial_lookup = fetch_financial_lookup()
    print(f"Loaded financial forecasts: {len(financial_lookup)}")
    broker_lookup = build_broker_lookup(codes)
    write_html_report(
        STATIC_DIR / "index.html",
        daily_rows,
        groups,
        total_rows,
        financial_lookup,
        sector_lookup,
        broker_lookup=broker_lookup,
        static_site=True,
    )
    write_readme()
    print(f"Done: {STATIC_DIR / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
