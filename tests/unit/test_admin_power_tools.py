"""Unit tests for the admin power tools: role switch, block/unblock, config."""

from __future__ import annotations

import uuid

import pytest
from apps.api.routers import admin as admin_router
from fastapi import HTTPException
from packages.auth import AdminPrincipal, require_admin_principal
from packages.core import settings
from packages.storage import User

SECRET_PRINCIPAL = AdminPrincipal(via="secret", actor=None)


class Session:
    def __init__(self, user: User | None) -> None:
        self.user = user

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    def begin(self):
        return self

    async def execute(self, statement, params=None):
        class R:
            def __init__(self, row):
                self.row = row

            def scalar_one_or_none(self):
                return self.row

        return R(self.user)

    def delete(self, obj):
        pass


def _user(role: str = "member", active: bool = True) -> User:
    from datetime import UTC, datetime

    u = User(id=uuid.uuid4(), tenant_id="main", name="X", email="x@example.com", role=role)
    u.is_active = active
    u.password_hash = None
    u.created_at = datetime(2026, 9, 29, tzinfo=UTC)
    return u


async def test_role_change(monkeypatch) -> None:
    from apps.api.schemas import AdminRoleChangeRequest

    user = _user(role="member")
    monkeypatch.setattr(admin_router, "admin_session", lambda: Session(user))

    info = await admin_router.admin_change_user_role(
        user.id, AdminRoleChangeRequest(role="admin"), SECRET_PRINCIPAL
    )
    assert user.role == "admin"
    assert info.role == "admin"


async def test_block_denies_sessions(monkeypatch) -> None:
    user = _user(active=True)
    monkeypatch.setattr(admin_router, "admin_session", lambda: Session(user))

    denied = []

    async def fake_deny(uid):
        denied.append(uid)

    monkeypatch.setattr(admin_router, "deny_user_sessions", fake_deny)
    await admin_router.admin_block_user(user.id, SECRET_PRINCIPAL)

    assert user.is_active is False
    assert denied == [user.id]


async def test_unblock_restores(monkeypatch) -> None:
    user = _user(active=False)
    monkeypatch.setattr(admin_router, "admin_session", lambda: Session(user))
    await admin_router.admin_unblock_user(user.id, SECRET_PRINCIPAL)
    assert user.is_active is True


async def test_blocked_login_rejected(monkeypatch) -> None:
    """The login guard fires for explicitly blocked accounts only."""
    from apps.api.routers import login as login_module
    from apps.api.schemas import EmailLoginRequest
    from packages.auth.passwords import hash_password

    user = _user()
    user.password_hash = hash_password("long-enough-pass")

    class LoginSession(Session):
        async def execute(self, statement, params=None):
            class R:
                def __init__(self, row):
                    self.row = row

                def scalar_one_or_none(self):
                    return self.row

            return R(user)

    monkeypatch.setattr(login_module, "async_session", lambda: LoginSession(user))

    # активен — вход проходит
    response = await login_module.login(
        EmailLoginRequest(email=user.email, password="long-enough-pass")
    )
    assert len(response.token) > 50

    # заблокирован — 403
    user.is_active = False
    with pytest.raises(HTTPException) as exc_info:
        await login_module.login(EmailLoginRequest(email=user.email, password="long-enough-pass"))
    assert exc_info.value.status_code == 403
    assert "blocked" in str(exc_info.value.detail)


async def test_config_endpoint_flags(monkeypatch) -> None:
    monkeypatch.setattr(settings, "open_registration", True)
    monkeypatch.setattr(settings, "enable_code_exec", False)
    config = await admin_router.admin_config(SECRET_PRINCIPAL)
    assert config.open_registration is True
    assert config.enable_code_exec is False
    assert config.models["strong"] == settings.strong_model


async def test_power_tools_require_admin() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await require_admin_principal(x_admin_secret="wrong")
    assert exc_info.value.status_code == 403
