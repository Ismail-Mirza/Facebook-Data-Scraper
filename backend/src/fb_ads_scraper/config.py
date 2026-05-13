from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BackendName = Literal["chrome", "playwright"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    browser_backend: BackendName = Field(default="chrome", alias="BROWSER_BACKEND")
    chrome_cdp_url: str = Field(default="http://chrome:3000", alias="CHROME_CDP_URL")
    chrome_proxy: str | None = Field(default=None, alias="CHROME_PROXY")

    frontend_origin: str = Field(default="http://localhost:5173", alias="FRONTEND_ORIGIN")
    output_dir: Path = Field(default=Path("output"), alias="OUTPUT_DIR")

    default_country: str = Field(default="ALL", alias="DEFAULT_COUNTRY")
    default_ad_type: str = Field(default="all", alias="DEFAULT_AD_TYPE")
    default_max_pages: int = Field(default=50, alias="DEFAULT_MAX_PAGES")

    # Playwright backend: launch a visible window (False) or run headless (True).
    # Default is visible — picking "Playwright local" is the "open the browser
    # and watch it scrape" mode. Force True in Docker via env (no display there).
    playwright_headless: bool = Field(default=False, alias="PLAYWRIGHT_HEADLESS")
    # Slow-motion delay between Playwright actions in ms (visible runs only).
    playwright_slow_mo_ms: int = Field(default=0, alias="PLAYWRIGHT_SLOW_MO_MS")

    scroll_idle_rounds: int = 3
    scroll_max_seconds: int = 300
    networkidle_timeout_ms: int = 3000


settings = Settings()
settings.output_dir.mkdir(parents=True, exist_ok=True)
