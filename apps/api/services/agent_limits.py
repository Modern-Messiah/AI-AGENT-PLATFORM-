from __future__ import annotations

import logging
import time
import uuid

from fastapi import HTTPException

from packages.cache.redis import get_redis
from packages.core import settings

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
    redis,
    tenant_id: str,
    *,
    limit: int,
    now_ms: int | None = None,
) -> None:
    window_ms = 60_000
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    key = f"rl:{tenant_id}:agent"
    member = f"{now_ms}:{uuid.uuid4().hex}"
    window_start = now_ms - window_ms

    pipe = redis.pipeline(transaction=True)
    pipe.zremrangebyscore(key, 0, window_start)
    pipe.zadd(key, {member: now_ms})
    pipe.zcard(key)
    pipe.expire(key, 120)
    _removed, _added, count, _expired = await pipe.execute()

    if count <= limit:
        return

    await redis.zrem(key, member)
    oldest = await redis.zrange(key, 0, 0, withscores=True)
    oldest_score = float(oldest[0][1]) if oldest else float(now_ms)
    retry_after = max(
        1,
        min(60, int((oldest_score + window_ms - now_ms + 999) // 1000)),
    )
    raise HTTPException(
        status_code=429,
        detail=f"rate limit exceeded: {limit} agent requests per minute",
        headers={"Retry-After": str(retry_after)},
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
    except Exception as exc:  # noqa: BLE001
        log.warning("rate limit check failed open | tenant=%s route=%s error=%s", tenant_id, route, exc)
    return query
