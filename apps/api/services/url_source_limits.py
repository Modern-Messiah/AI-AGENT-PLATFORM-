"""Rate limit for URL-source ingestion endpoints.

/documents/url, /documents/url/check and external reindex each drive full
outbound HTTP fetches under plain tenant auth; without a limiter one API
key can push unbounded outbound traffic (and memory pressure via large
sources). Shares the sliding-window implementation with the agent limiter;
the window is hourly because URL ingests are minutes-slow, not chat-fast.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException
from packages.cache.redis import get_redis
from packages.core import settings

from apps.api.services.rate_limit import check_sliding_window_limit

log = logging.getLogger(__name__)

_WINDOW_MS = 60 * 60_000


async def enforce_url_ingest_limit(tenant_id: str, route: str) -> None:
    limit = settings.url_ingest_rate_per_hour
    if limit <= 0:
        return
    try:
        await check_sliding_window_limit(
            get_redis(),
            f"rl:{tenant_id}:url_ingest",
            limit=limit,
            window_ms=_WINDOW_MS,
            label="URL ingest requests per hour",
        )
    except HTTPException:
        raise
    except Exception as exc:
        if settings.rate_limit_fail_closed:
            log.warning(
                "url ingest rate limit failed CLOSED | tenant=%s route=%s error=%s",
                tenant_id,
                route,
                exc,
            )
            raise HTTPException(
                status_code=503,
                detail="rate limiter unavailable and RATE_LIMIT_FAIL_CLOSED=true",
            ) from exc
        log.warning(
            "url ingest rate limit failed open | tenant=%s route=%s error=%s",
            tenant_id,
            route,
            exc,
        )
