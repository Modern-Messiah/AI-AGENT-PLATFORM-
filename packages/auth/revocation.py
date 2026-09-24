"""Instant API-key revocation across API processes via Redis pub/sub.

The 30s in-process auth cache means a revoked key can stay valid in other
API processes until TTL expiry. DELETE /auth/keys/{id} now also publishes
the key hash to REVOCATION_CHANNEL; every API process runs a background
listener that drops the matching cache entry immediately. Best-effort like
everything Redis-related here: Redis being down just falls back to the
TTL window.
"""

from __future__ import annotations

import asyncio
import logging

from packages.auth.api_keys import revoke_cached
from packages.cache.redis import get_redis

log = logging.getLogger(__name__)

REVOCATION_CHANNEL = "aap:apikey-revoked"
_RECONNECT_DELAY_SECONDS = 5.0


def _decode(data: object) -> str | None:
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    if isinstance(data, str):
        return data
    return None


async def publish_revocation(key_hash: str) -> None:
    """Best-effort: notify all API processes to drop this key from cache."""
    try:
        await get_redis().publish(REVOCATION_CHANNEL, key_hash)
    except Exception as exc:
        log.warning("revocation publish failed (TTL window applies) | error=%s", type(exc).__name__)


def handle_revocation_message(message: dict[str, object]) -> str | None:
    """Drop a cached auth entry; returns the dropped hash (test hook)."""
    if message.get("type") != "message":
        return None
    key_hash = _decode(message.get("data"))
    if not key_hash:
        return None
    revoke_cached(key_hash)
    return key_hash


async def revocation_listener() -> None:
    """Background task: subscribe and evict cache entries on revocations.

    Runs forever; on Redis outages it retries every few seconds. Cancelled
    at app shutdown.
    """
    while True:
        try:
            pubsub = get_redis().pubsub()
            await pubsub.subscribe(REVOCATION_CHANNEL)
            async for message in pubsub.listen():
                handle_revocation_message(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning(
                "revocation listener disconnected (%s), retrying in %.0fs",
                type(exc).__name__,
                _RECONNECT_DELAY_SECONDS,
            )
            await asyncio.sleep(_RECONNECT_DELAY_SECONDS)
