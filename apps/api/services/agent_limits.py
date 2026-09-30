from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException
from packages.cache.redis import get_redis
from packages.core import settings

from apps.api.services.rate_limit import check_sliding_window_limit

log = logging.getLogger(__name__)


def validate_agent_query(query: str) -> str:
    query = query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="user_query must not be empty")
    if len(query) > settings.agent_query_max_chars:
        raise HTTPException(
            status_code=413,
            detail=f"user_query exceeds {settings.agent_query_max_chars} character limit",
        )
    return query


async def check_agent_rate_limit(
    redis: Any,
    tenant_id: str,
    *,
    limit: int,
    now_ms: int | None = None,
) -> None:
    await check_sliding_window_limit(
        redis,
        f"rl:{tenant_id}:agent",
        limit=limit,
        window_ms=60_000,
        label="agent requests per minute",
        now_ms=now_ms,
    )


async def enforce_agent_limits(tenant_id: str, query: str, route: str) -> str:
    query = validate_agent_query(query)
    limit = settings.agent_rate_limit_per_minute
    if limit <= 0:
        return query

    try:
        await check_agent_rate_limit(get_redis(), tenant_id, limit=limit)
    except HTTPException:
        raise
    except Exception as exc:
        if settings.rate_limit_fail_closed:
            log.warning(
                "rate limit check failed CLOSED | tenant=%s route=%s error=%s",
                tenant_id,
                route,
                exc,
            )
            raise HTTPException(
                status_code=503,
                detail="rate limiter unavailable and RATE_LIMIT_FAIL_CLOSED=true",
            ) from exc
        log.warning(
            "rate limit check failed open | tenant=%s route=%s error=%s", tenant_id, route, exc
        )
    return query
