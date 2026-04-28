"""API key authentication.

Keys are stored as SHA-256 hashes in the api_keys table.
The raw key is returned only at creation time — never stored.
"""

from __future__ import annotations

import hashlib
import secrets

from fastapi import Header, HTTPException
from sqlalchemy import select

from packages.storage.db import async_session
from packages.storage.models import ApiKey


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_key() -> tuple[str, str]:
    """Return (raw_key, key_hash). Caller stores only the hash."""
    raw = secrets.token_urlsafe(32)
    return raw, _hash(raw)


async def require_tenant(x_api_key: str = Header(..., alias="X-API-Key")) -> str:
    """FastAPI dependency — validates the key and returns tenant_id."""
    key_hash = _hash(x_api_key)
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
    return row.tenant_id
