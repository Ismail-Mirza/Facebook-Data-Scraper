from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import click

from fb_ads_scraper.browser import get_backend
from fb_ads_scraper.config import settings
from fb_ads_scraper.exporters import write_csv, write_json
from fb_ads_scraper.models import InputType, SearchRequest
from fb_ads_scraper.proxy import pool
from fb_ads_scraper.search import run_search_request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@click.command()
# Target
@click.option("--keyword", "-k", help="Search keyword (sets input_type=keyword)")
@click.option("--page-url", "-u", help="Facebook page URL (e.g. https://www.facebook.com/Nike/)")
@click.option("--slug", "-s", help="Page slug (e.g. Nike) or numeric page_id")
# FB Ads Library URL params — every one configurable.
@click.option("--country", default=None, help="ISO-2 country code or ALL")
@click.option("--ad-type", default=None, help="all | political_and_issue_ads | housing_ads | ...")
@click.option("--media-type", default="all", help="all | image | video | meme | ...")
@click.option(
    "--active-status",
    type=click.Choice(["active", "inactive", "all"]),
    default="all",
    help="Filter by ad active status",
)
@click.option(
    "--targeted-country/--no-targeted-country",
    "is_targeted_country",
    default=False,
    help="is_targeted_country flag",
)
@click.option(
    "--search-type",
    type=click.Choice(["keyword_unordered", "keyword_exact_phrase", "page"]),
    default=None,
    help="Override search_type (default: derived from input)",
)
@click.option(
    "--sort-direction",
    type=click.Choice(["asc", "desc"]),
    default="desc",
    help="sort_data[direction]",
)
@click.option(
    "--sort-mode",
    type=click.Choice(["relevancy_monthly_grouped", "total_impressions", "spend", "start_date", "end_date"]),
    default="relevancy_monthly_grouped",
    help="sort_data[mode]",
)
@click.option("--source", default=None, help="source query param (e.g. fb-logo)")
@click.option(
    "--param",
    "extra_params",
    multiple=True,
    help="Extra raw FB param as key=value. Repeatable. Example: --param 'sort_data[foo]=bar'",
)
# Scrape controls
@click.option("--max-pages", default=None, type=int, help="Maximum scroll rounds")
@click.option(
    "--backend",
    type=click.Choice(["chrome", "playwright"]),
    default=None,
    help="Browser backend (defaults to BROWSER_BACKEND env, which defaults to chrome)",
)
@click.option("--use-proxy/--no-proxy", default=False, help="Route via a rotating free proxy")
@click.option(
    "--headless/--show-browser",
    default=None,
    help="Playwright backend only. Default follows PLAYWRIGHT_HEADLESS env.",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    required=True,
    help="Output file (.csv or .json)",
)
def main(
    keyword: str | None,
    page_url: str | None,
    slug: str | None,
    country: str | None,
    ad_type: str | None,
    media_type: str,
    active_status: str,
    is_targeted_country: bool,
    search_type: str | None,
    sort_direction: str,
    sort_mode: str,
    source: str | None,
    extra_params: tuple[str, ...],
    max_pages: int | None,
    backend: str | None,
    use_proxy: bool,
    headless: bool | None,
    output: Path,
) -> None:
    """Scrape the Meta Ads Library and write results to CSV or JSON."""
    inputs = [(InputType.keyword, keyword), (InputType.page_url, page_url), (InputType.slug, slug)]
    chosen = [(t, v) for t, v in inputs if v]
    if len(chosen) != 1:
        raise click.UsageError("Provide exactly one of --keyword, --page-url, --slug")
    input_type, value = chosen[0]

    extras: dict[str, str] = {}
    for raw in extra_params:
        if "=" not in raw:
            raise click.UsageError(f"--param expects key=value, got {raw!r}")
        k, v = raw.split("=", 1)
        extras[k.strip()] = v.strip()

    req = SearchRequest(
        input_type=input_type,
        value=value,
        country=country or settings.default_country,
        ad_type=ad_type or settings.default_ad_type,
        media_type=media_type,
        active_status=active_status,  # type: ignore[arg-type]
        is_targeted_country=is_targeted_country,
        search_type=search_type,  # type: ignore[arg-type]
        sort_direction=sort_direction,  # type: ignore[arg-type]
        sort_mode=sort_mode,  # type: ignore[arg-type]
        source=source,
        extra_params=extras,
        max_pages=max_pages or settings.default_max_pages,
        use_proxy=use_proxy,
        backend=backend,  # type: ignore[arg-type]
        headless=headless,
    )

    asyncio.run(_run(req=req, output=output))


async def _run(*, req: SearchRequest, output: Path) -> None:
    backend = get_backend(req.backend, headless=req.headless)
    proxy = await pool.get_working() if req.use_proxy else None
    if req.use_proxy and proxy is None:
        click.echo("Warning: no working proxy available; continuing without one", err=True)

    click.echo(f"Using backend: {backend.name}")
    browser = await backend.connect(proxy=proxy)
    try:
        ads = await run_search_request(browser=browser, request=req)
    finally:
        await backend.close()

    click.echo(f"Collected {len(ads)} ads")
    suffix = output.suffix.lower()
    if suffix == ".csv":
        write_csv(ads, output)
    elif suffix == ".json":
        write_json(ads, output)
    else:
        raise click.UsageError("--output must end in .csv or .json")
    click.echo(f"Wrote {output}")


if __name__ == "__main__":
    main()
