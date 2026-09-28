"""Runtime provider-key resolution backed by the llm_api_keys table.

Admins add provider keys through /admin/llm-keys; the running services
pick them up here without a restart: an in-process cache refreshed at
startup, on every admin change and by a periodic loop. Falls back to the
static env key when no DB key is active, so nothing breaks out of the box.

Every resolution bumps the key's request counter; the refresh loop
persists counters and last_used_at back to the table (best-effort) — that
is the per-key activity the admin panel shows.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, update

from packages.storage import LlmApiKey
from packages.storage.db import async_session

log = logging.getLogger(__name__)

REFRESH_INTERVAL_SECONDS = 30


@dataclass
class ActiveKey:
    id: uuid.UUID
    provider: str
    value: str
    requests: int = 0


_active: dict[str, ActiveKey] = {}
_dirty: set[uuid.UUID] = set()


def active_key(provider: str) -> ActiveKey | None:
    """Current DB-managed key for the provider (sync; from the cache)."""
    return _active.get(provider)


def resolve_api_key(provider: str, env_fallback: str) -> str:
    """DB key if active, else the env value. Counts as one use of the key."""
    key = _active.get(provider)
    if key is None:
        return env_fallback
    key.requests += 1
    _dirty.add(key.id)
    return key.value


async def refresh_from_db() -> None:
    """Load the newest active key per provider; persist pending counters."""
    global _active
    await _persist_counters()
    try:
        async with async_session() as s:
            rows = (
                (
                    await s.execute(
                        select(LlmApiKey)
                        .where(LlmApiKey.is_active.is_(True))
                        .order_by(LlmApiKey.provider, LlmApiKey.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )
    except Exception:
        log.warning("llm keyring refresh failed — keeping current keys", exc_info=True)
        return

    latest: dict[str, LlmApiKey] = {}
    for row in rows:
        latest.setdefault(row.provider, row)  # first = newest by ordering

    previous = _active
    _active = {
        provider: ActiveKey(
            id=row.id,
            provider=provider,
            value=row.key_value,
            requests=previous[provider].requests if provider in previous else row.requests_count,
        )
        for provider, row in latest.items()
    }
    providers = ", ".join(sorted(_active)) or "none (env fallback)"
    log.info("llm keyring refreshed | active providers: %s", providers)


async def _persist_counters() -> None:
    global _dirty
    if not _dirty:
        return
    pending = _dirty
    _dirty = set()
    try:
        async with async_session() as s, s.begin():
            for key_id in pending:
                key = next((k for k in _active.values() if k.id == key_id), None)
                if key is None:
                    continue
                await s.execute(
                    update(LlmApiKey)
                    .where(LlmApiKey.id == key_id)
                    .values(requests_count=key.requests, last_used_at=func.now())
                )
    except Exception:
        log.warning("llm keyring counter persist failed", exc_info=True)


async def keyring_refresh_loop() -> None:
    """Background task: keep the cache warm and persist activity counters."""
    while True:
        try:
            await asyncio.sleep(REFRESH_INTERVAL_SECONDS)
            await refresh_from_db()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("keyring refresh loop iteration failed", exc_info=True)
