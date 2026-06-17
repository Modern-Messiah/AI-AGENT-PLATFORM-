from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, HTTPException

from packages.auth import generate_key
from packages.core import settings
from packages.storage import ApiKey, async_session

from apps.api.schemas import CreateKeyRequest, CreateKeyResponse

router = APIRouter()


@router.post("/auth/keys", response_model=CreateKeyResponse, status_code=201)
async def create_api_key(
    body: CreateKeyRequest,
    x_admin_secret: str = Header(..., alias="X-Admin-Secret"),
) -> CreateKeyResponse:
    """Create an API key for a tenant. Protected by X-Admin-Secret header."""
    if x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="invalid admin secret")

    raw_key, key_hash = generate_key()
    key_id = uuid.uuid4()

    async with async_session() as s, s.begin():
        s.add(ApiKey(
            id=key_id,
            tenant_id=body.tenant_id,
            key_hash=key_hash,
            name=body.name,
        ))

    return CreateKeyResponse(
        id=str(key_id),
        tenant_id=body.tenant_id,
        name=body.name,
        raw_key=raw_key,
    )
