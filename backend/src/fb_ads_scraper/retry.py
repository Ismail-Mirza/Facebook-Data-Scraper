from __future__ import annotations

import logging

from tenacity import (
    AsyncRetrying,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)


cdp_connect_retry = retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=16),
    reraise=True,
)

graphql_body_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
    reraise=True,
)


def make_async_retry(attempts: int = 3, max_wait: int = 8) -> AsyncRetrying:
    return AsyncRetrying(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=1, min=1, max=max_wait),
        reraise=True,
    )


__all__ = [
    "cdp_connect_retry",
    "graphql_body_retry",
    "make_async_retry",
    "retry_if_exception_type",
]
