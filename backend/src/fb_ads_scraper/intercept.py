from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from playwright.async_api import Page, Response

log = logging.getLogger(__name__)

# GraphQL operation names that return Ads Library data. The set isn't exhaustive
# — Meta renames these — so we also accept any payload that contains an
# `ad_archive_id` somewhere in its JSON tree.
AD_LIBRARY_OPS = {
    "AdLibrarySearchPaginationQuery",
    "AdLibrarySearchResultsQuery",
    "AdLibraryMobileFocusedStateProviderRefetchQuery",
    "AdLibrarySearchPagesQueryRenderer",
    "AdLibrarySearchPagesQuery",
    "useAdLibraryTypeaheadDataSource",
}


class GraphQLInterceptor:
    """Captures Ads Library GraphQL XHR responses on a Playwright Page.

    Use as an async context manager. While active, every matching response body
    is parsed and pushed onto `queue`. Body reads happen in a fire-and-forget
    task so the event loop keeps draining the network queue.
    """

    def __init__(self, page: Page) -> None:
        self.page = page
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._tasks: set[asyncio.Task] = set()
        self._handler = self._on_response

    async def __aenter__(self) -> GraphQLInterceptor:
        self.page.on("response", self._handler)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.page.remove_listener("response", self._handler)
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    def _on_response(self, response: Response) -> None:
        url = response.url
        if "/api/graphql/" not in url:
            return
        request = response.request
        if request.method != "POST":
            return
        post_data = request.post_data or ""
        if not any(op in post_data for op in AD_LIBRARY_OPS) and "ad_library" not in post_data:
            return
        task = asyncio.create_task(self._read_body(response))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _read_body(self, response: Response) -> None:
        try:
            body = await response.body()
        except Exception as exc:
            log.debug("response.body() failed: %s", exc)
            return
        text = body.decode("utf-8", errors="replace").strip()
        # Meta sometimes returns multiple JSON objects separated by newlines.
        for chunk in text.split("\n"):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                payload = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            await self.queue.put(payload)

    async def drain(self, timeout: float = 0.5) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        while True:
            try:
                item = await asyncio.wait_for(self.queue.get(), timeout=timeout)
            except TimeoutError:
                break
            out.append(item)
        return out
