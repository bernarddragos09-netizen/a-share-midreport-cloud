from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse


ROOT = Path(__file__).resolve().parents[2]
FRONTEND_INDEX = ROOT / "a_share_midreport_cloud" / "frontend" / "index.html"
FETCH_SCRIPT = ROOT / "fetch_2026_midreport_upcoming_sse.py"
CLOUD_BUILD_SCRIPT = ROOT / "build_cloud_frontend.py"

sys.path.insert(0, str(ROOT))
from update_report_server import fetch_broker_forecast_html, fetch_financial_statements_html  # noqa: E402


app = FastAPI(title="A Share Midreport API")
update_lock = asyncio.Lock()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def index() -> FileResponse:
    if not FRONTEND_INDEX.exists():
        raise HTTPException(status_code=500, detail="frontend/index.html has not been built")
    return FileResponse(FRONTEND_INDEX, media_type="text/html; charset=utf-8")


@app.get("/api/health")
def health() -> dict[str, object]:
    return {"ok": True, "frontend_built": FRONTEND_INDEX.exists()}


@app.get("/api/broker")
def broker(code: str, response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    try:
        html = fetch_broker_forecast_html(code)
        return {"ok": True, "html": html}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/financials")
def financials(code: str, response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    try:
        html = fetch_financial_statements_html(code)
        return {"ok": True, "html": html}
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
            [sys.executable, str(CLOUD_BUILD_SCRIPT)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=240,
        )
        if build_result.returncode != 0:
            error = build_result.stderr[-3000:] or build_result.stdout[-3000:] or "cloud build failed"
            raise HTTPException(status_code=500, detail=error)

        return {
            "ok": True,
            "message": "更新完成",
            "fetch_output": fetch_result.stdout[-2000:],
            "build_output": build_result.stdout[-2000:],
        }
