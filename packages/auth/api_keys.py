"""API key + JWT session authentication.

Two credential paths resolve to the same Actor:

  X-API-Key: <raw key>            — tenant keys, hashed at rest (legacy path)
  Authorization: Bearer <token>   — Google-login session token (HS256, ours)

Keys are stored as SHA-256 hashes in the api_keys table.
The raw key is returned only at creation time — never stored.

Role semantics (enforcement): a key may be bound to a user (api_keys.user_id).
The resolved Actor carries that user's identity (id, name, role):
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
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import Header, HTTPException
from sqlalchemy import select, update

from packages.auth.jwt_sessions import verify_session_token
from packages.core import settings
from packages.storage.db import async_session
from packages.storage.models import ApiKey, User

_AUTH_CACHE_TTL_SECONDS = 30.0
# key_hash -> (tenant_id, role, user_id, user_name, key_id, key_name, expires_at)
_AUTH_CACHE: dict[
    str,
    tuple[str, str | None, uuid.UUID | None, str | None, uuid.UUID | None, str | None, float],
] = {}
_AUTH_LOCKS: dict[str, asyncio.Lock] = {}


@dataclass(frozen=True)
class Actor:
    """Who is acting on this request: the tenant plus the identity."""

    tenant_id: str
    role: str | None  # None when the key is not bound to a user
    user_id: uuid.UUID | None = None
    user_name: str | None = None
    api_key_id: uuid.UUID | None = None
    api_key_name: str | None = None
    email: str | None = None

    @property
    def can_destroy(self) -> bool:
        """Unbound (tenant-level) and admin keys may delete shared data."""
        return self.role is None or self.role == "admin"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def actor_from_claims(claims: dict[str, Any]) -> Actor:
    """Build an Actor from verified session-token claims."""
    role = str(claims.get("role") or "") or None
    sub = claims.get("sub")
    return Actor(
        tenant_id=str(claims.get("tid") or ""),
        role=role,
        user_id=uuid.UUID(str(sub)) if sub else None,
        user_name=str(claims["name"]) if claims.get("name") else None,
        email=str(claims["email"]) if claims.get("email") else None,
    )


def _bearer_token(authorization: object) -> str | None:
    # Direct (non-FastAPI) calls pass the raw Header default, not a string.
    if not isinstance(authorization, str) or not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


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


async def require_actor(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    authorization: str | None = Header(None, alias="Authorization"),
) -> Actor:
    """FastAPI dependency — resolves the acting principal.

    Authorization: Bearer takes precedence (Google-login session); otherwise
    the X-API-Key path runs.
    """
    bearer = _bearer_token(authorization)
    if bearer is not None:
        return actor_from_claims(verify_session_token(bearer))

    if not isinstance(x_api_key, str) or not x_api_key.strip():
        raise HTTPException(
            status_code=401, detail="missing credentials: X-API-Key or Bearer session"
        )

    key_hash = _hash(x_api_key)

    now = time.monotonic()
    cached = _AUTH_CACHE.get(key_hash)
    if cached is not None:
        tenant_id, role, user_id, user_name, key_id, key_name, expires_at = cached
        if expires_at > now:
            return Actor(
                tenant_id=tenant_id,
                role=role,
                user_id=user_id,
                user_name=user_name,
                api_key_id=key_id,
                api_key_name=key_name,
            )
        _AUTH_CACHE.pop(key_hash, None)

    lock = _AUTH_LOCKS.setdefault(key_hash, asyncio.Lock())
    async with lock:
        now = time.monotonic()
        cached = _AUTH_CACHE.get(key_hash)
        if cached is not None:
            tenant_id, role, user_id, user_name, key_id, key_name, expires_at = cached
            if expires_at > now:
                return Actor(
                    tenant_id=tenant_id,
                    role=role,
                    user_id=user_id,
                    user_name=user_name,
                    api_key_id=key_id,
                    api_key_name=key_name,
                )
            _AUTH_CACHE.pop(key_hash, None)

        async with async_session() as s:
            row = (
                await s.execute(
                    select(ApiKey, User.id, User.role, User.name)
                    .outerjoin(User, ApiKey.user_id == User.id)
                    .where(
                        ApiKey.key_hash == key_hash,
                        ApiKey.is_active.is_(True),
                    )
                )
            ).first()

        if row is None:
            raise HTTPException(status_code=401, detail="invalid or inactive API key")

        api_key_row, user_id, role, user_name = row
        tenant_id = api_key_row.tenant_id
        _AUTH_CACHE[key_hash] = (
            tenant_id,
            role,
            user_id,
            user_name,
            api_key_row.id,
            api_key_row.name,
            now + _AUTH_CACHE_TTL_SECONDS,
        )

        async with async_session() as s, s.begin():
            await s.execute(
                update(ApiKey)
                .where(ApiKey.key_hash == key_hash)
                .values(last_used_at=datetime.now(UTC))
            )

        return Actor(
            tenant_id=tenant_id,
            role=role,
            user_id=user_id,
            user_name=user_name,
            api_key_id=api_key_row.id,
            api_key_name=api_key_row.name,
        )


async def require_tenant(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    authorization: str | None = Header(None, alias="Authorization"),
) -> str:
    """Backward-compatible dependency — resolves the actor, returns tenant_id."""
    actor = await require_actor(x_api_key, authorization)
    return actor.tenant_id


def require_destroy_permission(actor: Actor) -> None:
    """Raise 403 when the acting member-key may not delete shared data."""
    if not actor.can_destroy:
        raise HTTPException(
            status_code=403,
            detail="member keys cannot delete shared documents or notebooks",
        )


@dataclass(frozen=True)
class AdminPrincipal:
    """How an admin-surface request authenticated: shared secret or session."""

    via: str  # "secret" | "session"
    actor: Actor | None  # set for session logins


async def require_admin_principal(
    x_admin_secret: str | None = Header(None, alias="X-Admin-Secret"),
    authorization: str | None = Header(None, alias="Authorization"),
) -> AdminPrincipal:
    """FastAPI dependency for /admin/* and /auth/* management endpoints.

    Accepts either an admin-role session token (Google login with the email
    listed in ADMIN_EMAILS) or the classic X-Admin-Secret header.
    """
    bearer = _bearer_token(authorization)
    if bearer is not None:
        claims = verify_session_token(bearer)
        actor = actor_from_claims(claims)
        if actor.is_admin:
            return AdminPrincipal(via="session", actor=actor)
        raise HTTPException(status_code=403, detail="admin role required")
    if isinstance(x_admin_secret, str) and x_admin_secret == settings.admin_secret:
        return AdminPrincipal(via="secret", actor=None)
    raise HTTPException(status_code=403, detail="invalid admin secret")
