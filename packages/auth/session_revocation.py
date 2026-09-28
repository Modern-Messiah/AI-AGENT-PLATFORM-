"""Server-side session revocation.

JWT sessions are stateless; without this, deleting a user (or wanting to
cut someone off) leaves their token valid for up to AUTH_SESSION_TTL_HOURS.
Denying a user records their id in Redis for slightly longer than the token
TTL; require_actor checks the denylist on every Bearer request. Redis being
down fails OPEN — availability over strictness, like the rate limiter.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from packages.cache.redis import get_redis
from packages.core import settings

log = logging.getLogger(__name__)

_DENIED_TTL_MARGIN_SECONDS = 300


def _denied_key(user_id: uuid.UUID) -> str:
    return f"aap:denied-user:{user_id}"


async def deny_user_sessions(user_id: uuid.UUID) -> None:
    """Best-effort: revoke all live session tokens of this user."""
    ttl = settings.auth_session_ttl_hours * 3600 + _DENIED_TTL_MARGIN_SECONDS
    try:
        redis: Any = get_redis()
        await redis.set(_denied_key(user_id), "1", ex=ttl)
    except Exception:
        log.warning("session denylist write failed | user_id=%s", user_id, exc_info=True)


async def is_user_denied(user_id: uuid.UUID | None) -> bool:
    if user_id is None:
        return False
    try:
        redis: Any = get_redis()
        return bool(await redis.exists(_denied_key(user_id)))
    except Exception:
        log.warning("session denylist check failed (fail-open) | user_id=%s", user_id)
        return False
