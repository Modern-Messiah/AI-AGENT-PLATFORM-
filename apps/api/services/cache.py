from __future__ import annotations

import logging

from packages.cache.semantic import semantic_cache

log = logging.getLogger(__name__)


async def invalidate_semantic_cache(tenant_id: str, reason: str) -> None:
    try:
        await semantic_cache.clear(tenant_id)
    except Exception as exc:
        log.warning(
            "semantic cache invalidation failed | tenant=%s reason=%s error=%s",
            tenant_id,
            reason,
            exc,
        )
