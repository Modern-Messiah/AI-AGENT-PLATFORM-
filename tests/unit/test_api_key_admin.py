from __future__ import annotations

from datetime import UTC, datetime

import pytest
from apps.api.main import ApiKeyInfo, app
from apps.api.routers import auth as auth_router
from fastapi import HTTPException


def test_key_admin_routes_are_registered() -> None:
    routes = {
        (path, method.upper())
        for path, methods in app.openapi()["paths"].items()
        for method in methods
    }

    assert ("/auth/keys", "POST") in routes
    assert ("/auth/keys", "GET") in routes
    assert ("/auth/keys/{key_id}", "DELETE") in routes


@pytest.mark.parametrize(
    "endpoint",
    [
        lambda: auth_router.list_api_keys(x_admin_secret="wrong"),
        lambda: auth_router.revoke_api_key(
            key_id="00000000-0000-0000-0000-000000000000", x_admin_secret="wrong"
        ),
    ],
)
async def test_key_admin_endpoints_reject_bad_admin_secret(endpoint) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await endpoint()
    assert exc_info.value.status_code == 403


def test_api_key_info_exposes_no_secrets() -> None:
    info = ApiKeyInfo(
        id="key-1",
        tenant_id="tenant-a",
        name="laptop",
        is_active=True,
        created_at=datetime(2026, 9, 24, tzinfo=UTC),
    )

    dumped = info.model_dump()
    assert set(dumped) == {
        "id",
        "tenant_id",
        "name",
        "is_active",
        "created_at",
        "last_used_at",
    }
    assert dumped["last_used_at"] is None
