from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, HTTPException, Query
from packages.auth import generate_key, publish_revocation
from packages.core import settings
from packages.storage import ApiKey, User, async_session
from sqlalchemy import select

from apps.api.schemas import (
    ApiKeyInfo,
    CreateKeyRequest,
    CreateKeyResponse,
    CreateUserRequest,
    UserInfo,
)

router = APIRouter()


def _require_admin(x_admin_secret: str) -> None:
    if x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="invalid admin secret")


@router.post("/auth/keys", response_model=CreateKeyResponse, status_code=201)
async def create_api_key(
    body: CreateKeyRequest,
    x_admin_secret: str = Header(..., alias="X-Admin-Secret"),
) -> CreateKeyResponse:
    """Create an API key for a tenant. Protected by X-Admin-Secret header."""
    _require_admin(x_admin_secret)

    raw_key, key_hash = generate_key()
    key_id = uuid.uuid4()

    async with async_session() as s, s.begin():
        user_id = None
        if body.user_id is not None:
            user = (
                await s.execute(
                    select(User).where(
                        User.id == body.user_id,
                        User.tenant_id == body.tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if user is None:
                raise HTTPException(status_code=404, detail="user not found in this tenant")
            user_id = user.id
        s.add(
            ApiKey(
                id=key_id,
                tenant_id=body.tenant_id,
                key_hash=key_hash,
                name=body.name,
                user_id=user_id,
            )
        )

    return CreateKeyResponse(
        id=str(key_id),
        tenant_id=body.tenant_id,
        name=body.name,
        raw_key=raw_key,
    )


@router.get("/auth/keys", response_model=list[ApiKeyInfo])
async def list_api_keys(
    x_admin_secret: str = Header(..., alias="X-Admin-Secret"),
    tenant_id: str | None = Query(default=None),
) -> list[ApiKeyInfo]:
    """List tenant API keys (no hashes, no raw keys). X-Admin-Secret only."""
    _require_admin(x_admin_secret)

    async with async_session() as s:
        stmt = select(ApiKey).order_by(ApiKey.created_at.desc()).limit(500)
        if tenant_id:
            stmt = stmt.where(ApiKey.tenant_id == tenant_id)
        rows = (await s.execute(stmt)).scalars().all()

    return [
        ApiKeyInfo(
            id=str(row.id),
            tenant_id=row.tenant_id,
            name=row.name,
            user_id=str(row.user_id) if row.user_id else None,
            is_active=row.is_active,
            created_at=row.created_at,
            last_used_at=row.last_used_at,
        )
        for row in rows
    ]


@router.delete("/auth/keys/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: uuid.UUID,
    x_admin_secret: str = Header(..., alias="X-Admin-Secret"),
) -> None:
    """Deactivate a key. Protected by X-Admin-Secret.

    Revocation takes effect within the require_tenant cache TTL (<=30s per
    API process) — the same window that already applies to deactivation.
    The row is kept for audit; reissuing a new key is the rotation path.
    """
    _require_admin(x_admin_secret)

    async with async_session() as s, s.begin():
        row = (await s.execute(select(ApiKey).where(ApiKey.id == key_id))).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="key not found")
        row.is_active = False
    # Cross-process cache eviction: revoke within ms instead of the 30s TTL.
    await publish_revocation(row.key_hash)


@router.post("/auth/users", response_model=UserInfo, status_code=201)
async def create_user(
    body: CreateUserRequest,
    x_admin_secret: str = Header(..., alias="X-Admin-Secret"),
) -> UserInfo:
    """Register a user within a tenant. Protected by X-Admin-Secret."""
    _require_admin(x_admin_secret)

    user_id = uuid.uuid4()
    async with async_session() as s, s.begin():
        existing = (
            await s.execute(
                select(User).where(
                    User.tenant_id == body.tenant_id,
                    User.name == body.name,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(status_code=409, detail="user name already exists in tenant")
        s.add(User(id=user_id, tenant_id=body.tenant_id, name=body.name, role=body.role))
        row = (await s.execute(select(User).where(User.id == user_id))).scalar_one()

    return UserInfo(
        id=str(row.id),
        tenant_id=row.tenant_id,
        name=row.name,
        role=row.role,
        created_at=row.created_at,
    )


@router.get("/auth/users", response_model=list[UserInfo])
async def list_users(
    x_admin_secret: str = Header(..., alias="X-Admin-Secret"),
    tenant_id: str | None = Query(default=None),
) -> list[UserInfo]:
    """List users (optionally filtered by tenant). Protected by X-Admin-Secret."""
    _require_admin(x_admin_secret)

    async with async_session() as s:
        stmt = select(User).order_by(User.created_at.desc()).limit(500)
        if tenant_id:
            stmt = stmt.where(User.tenant_id == tenant_id)
        rows = (await s.execute(stmt)).scalars().all()

    return [
        UserInfo(
            id=str(row.id),
            tenant_id=row.tenant_id,
            name=row.name,
            role=row.role,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.delete("/auth/users/{user_id}", status_code=204)
async def delete_user(
    user_id: uuid.UUID,
    x_admin_secret: str = Header(..., alias="X-Admin-Secret"),
) -> None:
    """Remove a user; their API keys survive with user_id cleared.

    Key revocation stays an explicit admin action — deleting a person is
    not silently treated as revoking their keys.
    """
    _require_admin(x_admin_secret)

    async with async_session() as s, s.begin():
        row = (await s.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="user not found")
        await s.delete(row)
