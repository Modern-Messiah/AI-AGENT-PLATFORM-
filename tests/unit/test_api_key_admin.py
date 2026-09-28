from __future__ import annotations

from datetime import UTC, datetime

import pytest
from apps.api.main import ApiKeyInfo, app
from fastapi import HTTPException
from packages.auth import require_admin_principal


def test_key_admin_routes_are_registered() -> None:
    routes = {
        (path, method.upper())
        for path, methods in app.openapi()["paths"].items()
        for method in methods
    }

    assert ("/auth/keys", "POST") in routes
    assert ("/auth/keys", "GET") in routes
    assert ("/auth/keys/{key_id}", "DELETE") in routes


async def test_key_admin_endpoints_reject_bad_admin_secret() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await require_admin_principal(x_admin_secret="wrong")
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
        "user_id",
        "is_active",
        "created_at",
        "last_used_at",
    }
    assert dumped["user_id"] is None
    assert dumped["last_used_at"] is None
