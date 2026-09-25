from __future__ import annotations

from datetime import UTC, datetime

import pytest
from apps.api.main import CreateUserRequest, UserInfo, app
from apps.api.routers import auth as auth_router
from fastapi import HTTPException


def test_user_admin_routes_are_registered() -> None:
    routes = {
        (path, method.upper())
        for path, methods in app.openapi()["paths"].items()
        for method in methods
    }

    assert ("/auth/users", "POST") in routes
    assert ("/auth/users", "GET") in routes
    assert ("/auth/users/{user_id}", "DELETE") in routes


@pytest.mark.parametrize(
    "endpoint",
    [
        lambda: auth_router.list_users(x_admin_secret="wrong"),
        lambda: auth_router.delete_user(
            user_id="00000000-0000-0000-0000-000000000000", x_admin_secret="wrong"
        ),
    ],
)
async def test_user_admin_endpoints_reject_bad_admin_secret(endpoint) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await endpoint()
    assert exc_info.value.status_code == 403


def test_create_user_request_validates_role() -> None:
    ok = CreateUserRequest(tenant_id="t", name="Anna", role="admin")
    assert ok.role == "admin"

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CreateUserRequest(tenant_id="t", name="Anna", role="superuser")


def test_user_info_schema_shape() -> None:
    info = UserInfo(
        id="u-1",
        tenant_id="t",
        name="Anna",
        role="member",
        created_at=datetime(2026, 9, 24, tzinfo=UTC),
    )
    assert set(info.model_dump()) == {"id", "tenant_id", "name", "role", "created_at"}


def test_api_key_info_carries_user_attribution() -> None:
    info = __import__("apps.api.main", fromlist=["ApiKeyInfo"]).ApiKeyInfo(
        id="k-1",
        tenant_id="t",
        name="laptop",
        is_active=True,
        created_at=datetime(2026, 9, 24, tzinfo=UTC),
        user_id="u-1",
    )
    assert info.model_dump()["user_id"] == "u-1"
