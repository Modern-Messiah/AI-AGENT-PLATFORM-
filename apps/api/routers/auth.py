from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, HTTPException, Query
from packages.auth import generate_key, publish_revocation
from packages.core import settings
from packages.storage import ApiKey, async_session
from sqlalchemy import select

from apps.api.schemas import ApiKeyInfo, CreateKeyRequest, CreateKeyResponse

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
        s.add(
            ApiKey(
                id=key_id,
                tenant_id=body.tenant_id,
                key_hash=key_hash,
                name=body.name,
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
