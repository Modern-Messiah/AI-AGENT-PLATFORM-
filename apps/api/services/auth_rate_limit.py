"""Per-IP rate limits for the auth and admin surfaces.

These endpoints answer 401/403 without any limiter today, which makes the
admin secret brute-forceable. The same Redis sliding window as the agent
limiter, keyed by the peer IP instead of the tenant. Fails open when Redis
is unavailable (RATE_LIMIT_FAIL_CLOSED=true makes it fail closed), matching
the platform-wide availability choice.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import HTTPException, Request
from packages.cache.redis import get_redis
from packages.core import settings

log = logging.getLogger(__name__)

_WINDOW_MS = 60_000

# Management surfaces are used rarely; the admin panel makes a handful of
# calls per tab switch. Both limits sit far above normal use.
AUTH_LIMIT_PER_MINUTE = 15
ADMIN_LIMIT_PER_MINUTE = 60


def _client_ip(request: Request) -> str:
    # request.client.host only: X-Forwarded-For is client-spoofable and
    # must not be trusted for rate-limit keys without a trusted-proxy list.
    client = request.client
    return client.host if client else "unknown"


async def _check(key: str, limit: int) -> None:
    redis: Any = get_redis()
    now_ms = int(time.time() * 1000)
    member = f"{now_ms}:{uuid.uuid4().hex}"

    pipe = redis.pipeline(transaction=True)
    pipe.zremrangebyscore(key, 0, now_ms - _WINDOW_MS)
    pipe.zadd(key, {member: now_ms})
    pipe.zcard(key)
    pipe.expire(key, 120)
    _removed, _added, count, _expired = await pipe.execute()

    if count <= limit:
        return

    await redis.zrem(key, member)
    raise HTTPException(
        status_code=429,
        detail=f"rate limit exceeded: {limit} requests per minute",
    )


async def _enforce(request: Request, bucket: str, limit: int) -> None:
    key = f"rl:{_client_ip(request)}:{bucket}"
    try:
        await _check(key, limit)
    except HTTPException:
        raise  # 429 from _check is the limiter working — always propagate
    except Exception:
        if settings.rate_limit_fail_closed:
            raise HTTPException(status_code=503, detail="rate limiter unavailable") from None
        log.warning("auth rate limit check failed (fail-open) | bucket=%s", bucket)


async def enforce_auth_rate_limit(request: Request) -> None:
    """FastAPI dependency for /auth/* — key issuance and user management."""
    await _enforce(request, "auth", AUTH_LIMIT_PER_MINUTE)


async def enforce_admin_rate_limit(request: Request) -> None:
    """FastAPI dependency for /admin/* — the admin-secret surface."""
    await _enforce(request, "admin", ADMIN_LIMIT_PER_MINUTE)
