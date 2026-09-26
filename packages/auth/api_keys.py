"""API key authentication.

Keys are stored as SHA-256 hashes in the api_keys table.
The raw key is returned only at creation time — never stored.

Role semantics (enforcement): a key may be bound to a user (api_keys.user_id).
The resolved Actor carries that user's role:
  - unbound key or role "admin"  -> full access (tenant-level key)
  - role "member"                -> no destructive operations
Which operations count as destructive is decided by the routers
(require_admin_role guard); this module only resolves the actor.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Header, HTTPException
from sqlalchemy import select, update

from packages.storage.db import async_session
from packages.storage.models import ApiKey, User

_AUTH_CACHE_TTL_SECONDS = 30.0
# key_hash -> (tenant_id, role | None, expires_at)
_AUTH_CACHE: dict[str, tuple[str, str | None, float]] = {}
_AUTH_LOCKS: dict[str, asyncio.Lock] = {}


@dataclass(frozen=True)
class Actor:
    """Who is acting on this request: the tenant plus the key owner's role."""

    tenant_id: str
    role: str | None  # None when the key is not bound to a user

    @property
    def can_destroy(self) -> bool:
        """Unbound (tenant-level) and admin keys may delete shared data."""
        return self.role is None or self.role == "admin"


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_key() -> tuple[str, str]:
    """Return (raw_key, key_hash). Caller stores only the hash."""
    raw = secrets.token_urlsafe(32)
    return raw, _hash(raw)


def revoke_cached(key_hash: str) -> None:
    """Drop a key from the in-process auth cache (called by the revocation listener)."""
    _AUTH_CACHE.pop(key_hash, None)
    _AUTH_LOCKS.pop(key_hash, None)


async def require_actor(x_api_key: str | None = Header(None, alias="X-API-Key")) -> Actor:
    """FastAPI dependency — validates the key and resolves the acting principal."""
    if x_api_key is None or not x_api_key.strip():
        raise HTTPException(status_code=401, detail="missing API key")

    key_hash = _hash(x_api_key)

    now = time.monotonic()
    cached = _AUTH_CACHE.get(key_hash)
    if cached is not None:
        tenant_id, role, expires_at = cached
        if expires_at > now:
            return Actor(tenant_id=tenant_id, role=role)
        _AUTH_CACHE.pop(key_hash, None)

    lock = _AUTH_LOCKS.setdefault(key_hash, asyncio.Lock())
    async with lock:
        now = time.monotonic()
        cached = _AUTH_CACHE.get(key_hash)
        if cached is not None:
            tenant_id, role, expires_at = cached
            if expires_at > now:
                return Actor(tenant_id=tenant_id, role=role)
            _AUTH_CACHE.pop(key_hash, None)

        async with async_session() as s:
            row = (
                await s.execute(
                    select(ApiKey, User.role)
                    .outerjoin(User, ApiKey.user_id == User.id)
                    .where(
                        ApiKey.key_hash == key_hash,
                        ApiKey.is_active.is_(True),
                    )
                )
            ).first()

        if row is None:
            raise HTTPException(status_code=401, detail="invalid or inactive API key")

        api_key_row, role = row
        tenant_id = api_key_row.tenant_id
        _AUTH_CACHE[key_hash] = (tenant_id, role, now + _AUTH_CACHE_TTL_SECONDS)

        async with async_session() as s, s.begin():
            await s.execute(
                update(ApiKey)
                .where(ApiKey.key_hash == key_hash)
                .values(last_used_at=datetime.now(UTC))
            )

        return Actor(tenant_id=tenant_id, role=role)


async def require_tenant(x_api_key: str | None = Header(None, alias="X-API-Key")) -> str:
    """Backward-compatible dependency — validates the key, returns tenant_id."""
    actor = await require_actor(x_api_key)
    return actor.tenant_id


def require_destroy_permission(actor: Actor) -> None:
    """Raise 403 when the acting member-key may not delete shared data."""
    if not actor.can_destroy:
        raise HTTPException(
            status_code=403,
            detail="member keys cannot delete shared documents or notebooks",
        )
