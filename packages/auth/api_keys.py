"""API key authentication.

Keys are stored as SHA-256 hashes in the api_keys table.
The raw key is returned only at creation time — never stored.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
from datetime import datetime, timezone

from fastapi import Header, HTTPException
from sqlalchemy import select, update

from packages.storage.db import async_session
from packages.storage.models import ApiKey

_AUTH_CACHE_TTL_SECONDS = 30.0
_AUTH_CACHE: dict[str, tuple[str, float]] = {}
_AUTH_LOCKS: dict[str, asyncio.Lock] = {}


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_key() -> tuple[str, str]:
    """Return (raw_key, key_hash). Caller stores only the hash."""
    raw = secrets.token_urlsafe(32)
    return raw, _hash(raw)


async def require_tenant(x_api_key: str = Header(..., alias="X-API-Key")) -> str:
    """FastAPI dependency — validates the key and returns tenant_id."""
    key_hash = _hash(x_api_key)

    now = time.monotonic()
    cached = _AUTH_CACHE.get(key_hash)
    if cached is not None:
        tenant_id, expires_at = cached
        if expires_at > now:
            return tenant_id
        _AUTH_CACHE.pop(key_hash, None)

    lock = _AUTH_LOCKS.setdefault(key_hash, asyncio.Lock())
    async with lock:
        now = time.monotonic()
        cached = _AUTH_CACHE.get(key_hash)
        if cached is not None:
            tenant_id, expires_at = cached
            if expires_at > now:
                return tenant_id
            _AUTH_CACHE.pop(key_hash, None)

        async with async_session() as s:
            row = (
                await s.execute(
                    select(ApiKey).where(
                        ApiKey.key_hash == key_hash,
                        ApiKey.is_active.is_(True),
                    )
                )
            ).scalar_one_or_none()

        if row is None:
            raise HTTPException(status_code=401, detail="invalid or inactive API key")

        tenant_id = row.tenant_id
        _AUTH_CACHE[key_hash] = (tenant_id, now + _AUTH_CACHE_TTL_SECONDS)

        async with async_session() as s, s.begin():
            await s.execute(
                update(ApiKey)
                .where(ApiKey.key_hash == key_hash)
                .values(last_used_at=datetime.now(timezone.utc))
            )

        return tenant_id
