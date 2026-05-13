from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class InputType(StrEnum):
    keyword = "keyword"
    page_url = "page_url"
    slug = "slug"


ActiveStatus = Literal["active", "inactive", "all"]
SearchTypeName = Literal["keyword_unordered", "keyword_exact_phrase", "page"]
SortDirection = Literal["asc", "desc"]
SortMode = Literal[
    "relevancy_monthly_grouped",
    "total_impressions",
    "spend",
    "start_date",
    "end_date",
]


class SearchRequest(BaseModel):
    # Core
    input_type: InputType
    value: str

    # FB Ads Library URL params — all configurable, all map 1:1 to query string.
    country: str = "ALL"
    ad_type: str = "all"
    media_type: str = "all"
    active_status: ActiveStatus = "all"
    is_targeted_country: bool = False
    search_type: SearchTypeName | None = None  # None → derived from input_type
    sort_direction: SortDirection = "desc"
    sort_mode: SortMode = "relevancy_monthly_grouped"
    source: str | None = None  # e.g. "fb-logo"
    # Pass-throughs for any FB params not modelled above. Bracket keys allowed,
    # e.g. {"sort_data[foo]": "bar"}.
    extra_params: dict[str, str] = Field(default_factory=dict)

    # Scrape controls
    max_pages: int = 50
    use_proxy: bool = False
    backend: Literal["chrome", "playwright"] | None = None
    # Playwright backend only — None means "use env default", True/False overrides
    # per-request. Ignored by ChromeBackend (always headless).
    headless: bool | None = None


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class Ad(BaseModel):
    ad_archive_id: str
    page_id: str | None = None
    page_name: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    is_active: bool | None = None
    publisher_platforms: list[str] = Field(default_factory=list)
    body_text: str | None = None
    cta_text: str | None = None
    cta_type: str | None = None
    display_format: str | None = None
    images: list[str] = Field(default_factory=list)
    videos: list[str] = Field(default_factory=list)
    landing_url: str | None = None

    # Political / issue / EU-only
    spend: dict[str, Any] | None = None
    impressions: dict[str, Any] | None = None
    currency: str | None = None
    funded_by: str | None = None
    demographic_distribution: list[dict[str, Any]] | None = None
    region_distribution: list[dict[str, Any]] | None = None
    eu_total_reach: int | None = None

    raw: dict[str, Any] | None = None


class Job(BaseModel):
    job_id: str
    status: JobStatus = JobStatus.queued
    request: SearchRequest
    backend_used: str | None = None
    ad_count: int = 0
    pages_scrolled: int = 0
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    ads: list[Ad] = Field(default_factory=list)


class ProxyEntry(BaseModel):
    host: str
    port: int
    protocol: Literal["http", "https", "socks4", "socks5"] = "http"
    username: str | None = None
    password: str | None = None
    country: str | None = None
    last_checked: datetime | None = None
    healthy: bool | None = None

    @property
    def url(self) -> str:
        auth = ""
        if self.username:
            from urllib.parse import quote

            user = quote(self.username, safe="")
            pwd = quote(self.password or "", safe="")
            auth = f"{user}:{pwd}@"
        return f"{self.protocol}://{auth}{self.host}:{self.port}"
