from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from fb_ads_scraper.browser import is_chrome_healthy, is_playwright_available
from fb_ads_scraper.config import settings
from fb_ads_scraper.exporters import stream_csv, stream_json
from fb_ads_scraper.jobs import store
from fb_ads_scraper.models import Job, SearchRequest
from fb_ads_scraper.proxy import pool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(title="Meta Ads Library Scraper", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    backend = settings.browser_backend
    if backend == "chrome":
        ok = await is_chrome_healthy()
    else:
        ok = is_playwright_available()
    return {"backend": backend, "status": "ok" if ok else "unavailable"}


@app.get("/backends")
async def backends() -> list[dict]:
    return [
        {
            "name": "chrome",
            "available": True,
            "healthy": await is_chrome_healthy(),
            "supports_per_request_proxy": False,
        },
        {
            "name": "playwright",
            "available": is_playwright_available(),
            "healthy": is_playwright_available(),
            "supports_per_request_proxy": True,
        },
    ]


@app.post("/search", response_model=Job)
async def search(req: SearchRequest) -> Job:
    job = store.create(req)
    store.start(job)
    return job


@app.get("/jobs")
async def list_jobs() -> list[dict]:
    return [
        {
            "job_id": j.job_id,
            "status": j.status,
            "ad_count": j.ad_count,
            "pages_scrolled": j.pages_scrolled,
            "backend_used": j.backend_used,
            "started_at": j.started_at,
            "finished_at": j.finished_at,
        }
        for j in store.list()
    ]


@app.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return {
        "job_id": job.job_id,
        "status": job.status,
        "ad_count": job.ad_count,
        "pages_scrolled": job.pages_scrolled,
        "backend_used": job.backend_used,
        "error": job.error,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "request": job.request,
    }


@app.get("/jobs/{job_id}/results")
async def get_results(
    job_id: str,
    format: str = Query("json", pattern="^(json|csv)$"),
):
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    if format == "csv":
        return StreamingResponse(
            stream_csv(job.ads),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="ads-{job_id}.csv"'},
        )
    return StreamingResponse(
        stream_json(job.ads),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="ads-{job_id}.json"'},
    )


@app.get("/proxies")
async def list_proxies() -> dict:
    return {
        "current": pool.current.model_dump(mode="json") if pool.current else None,
        "working": [p.model_dump(mode="json") for p in pool.list_working()],
    }


@app.post("/proxies/refresh")
async def refresh_proxies() -> dict:
    working = await pool.refresh(force=True)
    return {"count": len(working), "working": [p.model_dump(mode="json") for p in working]}


@app.post("/proxies/rotate")
async def rotate_proxy() -> dict:
    new = await pool.rotate()
    return {"current": new.model_dump(mode="json") if new else None}
