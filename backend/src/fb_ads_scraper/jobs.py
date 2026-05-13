from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from fb_ads_scraper.browser import get_backend
from fb_ads_scraper.config import settings
from fb_ads_scraper.models import Job, JobStatus, SearchRequest
from fb_ads_scraper.proxy import pool
from fb_ads_scraper.search import run_search_request

log = logging.getLogger(__name__)


class JobStore:
    """In-memory job store. V1 — jobs vanish on restart."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    def create(self, request: SearchRequest) -> Job:
        job_id = uuid.uuid4().hex[:12]
        job = Job(job_id=job_id, request=request)
        self._jobs[job_id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        return list(self._jobs.values())

    def start(self, job: Job) -> None:
        task = asyncio.create_task(self._run(job))
        self._tasks[job.job_id] = task

    async def _run(self, job: Job) -> None:
        job.status = JobStatus.running
        job.started_at = datetime.now(UTC)
        backend_name = job.request.backend or settings.browser_backend
        job.backend_used = backend_name

        backend = get_backend(backend_name, headless=job.request.headless)
        proxy = await pool.get_working() if job.request.use_proxy else None
        if job.request.use_proxy and proxy is None:
            log.warning("Job %s requested proxy but none are healthy", job.job_id)

        async def on_progress(pages: int, count: int) -> None:
            job.pages_scrolled = pages
            job.ad_count = count

        ads: list = []
        try:
            browser = await backend.connect(proxy=proxy)
            try:
                ads = await run_search_request(
                    browser=browser,
                    request=job.request,
                    on_progress=on_progress,
                )
            finally:
                try:
                    await backend.close()
                except Exception as close_exc:
                    log.warning("Job %s: backend.close() failed: %s", job.job_id, close_exc)
            job.ads = ads
            job.ad_count = len(ads)
            job.status = JobStatus.completed
        except Exception as exc:
            # Even if run_search_request raised, preserve whatever it
            # managed to return *before* the exception. Any partial list
            # is better than 0 ads in the response.
            log.exception("Job %s errored — preserving %d partial ads", job.job_id, len(ads))
            job.ads = ads
            job.ad_count = len(ads)
            job.error = f"{type(exc).__name__}: {exc}"
            # Partial-success semantics: if we have ads, call it completed
            # but keep the error string so the UI/caller can see context.
            job.status = JobStatus.completed if ads else JobStatus.failed
        finally:
            job.finished_at = datetime.now(UTC)


store = JobStore()
