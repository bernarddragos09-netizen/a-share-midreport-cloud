#!/usr/bin/env python3
"""Build server-side stock data and the standalone disclosure calendar."""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib import request
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "a_share_midreport_2026_upcoming_sse"
CLOUD_DIR = ROOT / "a_share_midreport_cloud"
CLOUD_FRONTEND_DIR = CLOUD_DIR / "frontend"
CLOUD_DATA_DIR = CLOUD_DIR / "data"
SNAPSHOT_PATH = CLOUD_DATA_DIR / "stock_snapshot.json"
CALENDAR_PATH = CLOUD_FRONTEND_DIR / "calendar.html"
CHINA_TZ = ZoneInfo("Asia/Shanghai")
TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="


def extract_json_assignment(document: str, variable: str):
    marker = f"const {variable} = "
    start = document.find(marker)
    if start < 0:
        return None
    start += len(marker)
    value, _ = json.JSONDecoder().raw_decode(document[start:])
    return value


def source_candidates() -> list[Path]:
    return [
        CLOUD_FRONTEND_DIR / "index.html",
        DATA_DIR / "report_sse_2026_midreport.html",
        ROOT / "a_share_midreport_2026_static_site" / "index.html",
    ]


def find_source_report() -> tuple[Path, str, list[dict], dict[str, dict]]:
    for path in source_candidates():
        if not path.exists():
            continue
        document = path.read_text(encoding="utf-8")
        search_index = extract_json_assignment(document, "searchIndex")
        detail_index = extract_json_assignment(document, "detailIndex")
        if isinstance(search_index, list) and isinstance(detail_index, dict):
            return path, document, search_index, detail_index
    raise RuntimeError("No generated report containing searchIndex/detailIndex was found")


def _quote_number(values: list[str], index: int, scale: float = 1.0) -> float | None:
    try:
        value = float(values[index]) * scale
    except (IndexError, TypeError, ValueError):
        return None
    return value if value > 0 else None


def fetch_quote_metrics(stock_codes: list[str]) -> dict[str, dict[str, float | None]]:
    quotes: dict[str, dict[str, float | None]] = {}
    unique_codes = sorted({str(code) for code in stock_codes if str(code)})
    batch_size = 60
    for start in range(0, len(unique_codes), batch_size):
        batch = unique_codes[start : start + batch_size]
        symbols = ",".join(
            ("sh" if code.startswith(("6", "9")) else "sz") + code for code in batch
        )
        req = request.Request(
            TENCENT_QUOTE_URL + symbols,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"},
        )
        payload = ""
        for attempt in range(1, 4):
            try:
                with request.urlopen(req, timeout=30) as response:
                    payload = response.read().decode("gbk", errors="replace")
                break
            except Exception as exc:
                print(f"Quote batch {start // batch_size + 1} failed ({attempt}/3): {exc}")
                if attempt < 3:
                    time.sleep(attempt)
        for code, raw_fields in re.findall(r'v_(?:sh|sz)(\d{6})="([^"]*)"', payload):
            values = raw_fields.split("~")
            quotes[code] = {
                "price": _quote_number(values, 3),
                "change_pct": float(values[32]) if len(values) > 32 and values[32] not in {"", "-"} else None,
                "pe": _quote_number(values, 39),
                "market_cap": _quote_number(values, 45, 100_000_000),
                "pb": _quote_number(values, 46),
            }
        print(f"Fetched Tencent quote batch {start // batch_size + 1}: {len(batch)} stocks")
    return quotes


def build_snapshot(force: bool = False, quotes_only: bool = False) -> Path:
    if quotes_only:
        if not SNAPSHOT_PATH.exists():
            raise RuntimeError("Cannot refresh quotes before the stock snapshot exists")
        payload = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        payload["quotes"] = fetch_quote_metrics(
            [str(item.get("code", "")) for item in payload.get("stocks") or []]
        )
        payload["quote_generated_at"] = datetime.now(CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S")
        SNAPSHOT_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        print(f"Quote snapshot refreshed: {len(payload['quotes'])} stocks")
        return SNAPSHOT_PATH
    if SNAPSHOT_PATH.exists() and not force:
        print(f"Keeping existing stock snapshot: {SNAPSHOT_PATH}")
        return SNAPSHOT_PATH

    previous_payload = {}
    if SNAPSHOT_PATH.exists():
        previous_payload = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))

    source_path, document, search_index, detail_index = find_source_report()
    ordered_codes = [str(item.get("code", "")) for item in search_index]
    stocks = [detail_index[code] for code in ordered_codes if code in detail_index]
    seen = {str(item.get("code", "")) for item in stocks}
    stocks.extend(item for code, item in detail_index.items() if str(code) not in seen)

    payload = {
        "generated_at": datetime.now(CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "report_period": "2026中报",
        "source_report": source_path.name,
        "count": len(stocks),
        "stocks": stocks,
    }
    if previous_payload.get("fundamentals"):
        payload["fundamentals"] = previous_payload["fundamentals"]
        for key in (
            "data_provider",
            "akshare_generated_at",
            "akshare_sources",
            "tushare_generated_at",
            "tushare_sources",
            "tushare_quote_count",
            "tushare_disclosure_count",
            "tushare_financial_count",
        ):
            if key in previous_payload:
                payload[key] = previous_payload[key]
    payload["quotes"] = fetch_quote_metrics([str(item.get("code", "")) for item in stocks])
    payload["quote_generated_at"] = datetime.now(CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S")
    CLOUD_DATA_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    CLOUD_FRONTEND_DIR.mkdir(parents=True, exist_ok=True)
    if source_path.resolve() != CALENDAR_PATH.resolve():
        CALENDAR_PATH.write_text(document, encoding="utf-8")

    print(f"Stock snapshot written: {SNAPSHOT_PATH} ({len(stocks)} stocks)")
    print(f"Disclosure calendar written: {CALENDAR_PATH}")
    return SNAPSHOT_PATH


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild the snapshot from the newest generated report.",
    )
    parser.add_argument(
        "--quotes-only",
        action="store_true",
        help="Keep the stock data and only refresh Tencent quote metrics.",
    )
    args = parser.parse_args()
    build_snapshot(force=args.force, quotes_only=args.quotes_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
