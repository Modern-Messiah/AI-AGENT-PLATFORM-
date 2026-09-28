"""Unit tests for email+password authentication.

The DB layer is faked; password hashing, allowlist gating, role resolution
and session issuance run against the real code paths.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.routers import login as login_router
from apps.api.schemas import EmailLoginRequest, RegisterRequest
from fastapi import HTTPException
from packages.auth.passwords import hash_password, verify_password
from packages.core import settings
from packages.storage import User

JWT_SECRET = "unit-test-jwt-secret"
ADMIN_EMAIL = "root@example.com"
MEMBER_EMAIL = "bob@example.com"


@pytest.fixture(autouse=True)
def _auth_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_jwt_secret", JWT_SECRET)
    monkeypatch.setattr(settings, "admin_emails", [ADMIN_EMAIL])
    monkeypatch.setattr(settings, "auth_allowed_emails", [MEMBER_EMAIL])
    monkeypatch.setattr(settings, "default_tenant_id", "main")
    monkeypatch.setattr(settings, "open_registration", False)


class UsersResult:
    def __init__(self, row: object | None) -> None:
        self.row = row

    def scalar_one_or_none(self) -> object | None:
        return self.row


class UsersSession:
    def __init__(self, users: dict[str, User]) -> None:
        self.users = users

    async def __aenter__(self) -> UsersSession:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def begin(self) -> UsersSession:
        return self

    async def execute(self, statement: object, params: object = None) -> UsersResult:
        text = str(statement)
        if "WHERE users.email" in text:
            compiled = statement.compile()
            email = str(compiled.params.get("email_1", "")).lower().strip()
            return UsersResult(self.users.get(email))
        if "WHERE users.id" in text:
            compiled = statement.compile()
            user_id = compiled.params.get("id_1")
            return UsersResult(next((u for u in self.users.values() if u.id == user_id), None))
        return UsersResult(None)

    def add(self, user: User) -> None:
        self.users[user.email] = user


@pytest.fixture
def users(monkeypatch: pytest.MonkeyPatch) -> dict[str, User]:
    store: dict[str, User] = {}
    monkeypatch.setattr(login_router, "async_session", lambda: UsersSession(store))
    return store


# ── register ─────────────────────────────────────────────────────────────────


async def test_register_creates_member_and_issues_session(users) -> None:
    response = await login_router.register(
        RegisterRequest(email=MEMBER_EMAIL, password="long-enough-pass", name="Bob")
    )

    user = users[MEMBER_EMAIL]
    assert user.tenant_id == "main"
    assert user.role == "member"
    assert user.password_hash and user.password_hash.startswith("scrypt$")
    assert user.name == "Bob"
    assert response.role == "member"
    assert response.is_admin is False
    assert len(response.token) > 50


async def test_register_admin_email_gets_admin_role(users) -> None:
    response = await login_router.register(
        RegisterRequest(email=ADMIN_EMAIL, password="long-enough-pass", name="Root")
    )
    assert response.role == "admin"
    assert response.is_admin is True


async def test_register_rejects_emails_outside_allowlist(users) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await login_router.register(
            RegisterRequest(email="stranger@example.com", password="long-enough-pass")
        )
    assert exc_info.value.status_code == 403


async def test_register_rejects_duplicate_email(users) -> None:
    await login_router.register(RegisterRequest(email=MEMBER_EMAIL, password="long-enough-pass"))
    with pytest.raises(HTTPException) as exc_info:
        await login_router.register(
            RegisterRequest(email=MEMBER_EMAIL, password="another-long-pass")
        )
    assert exc_info.value.status_code == 409


async def test_register_closed_without_allowlist_rejects(
    users, monkeypatch: pytest.MonkeyPatch
) -> None:
    # open_registration is False in the fixture: with no allowlist at all,
    # nobody may register (403 — email login itself stays available).
    monkeypatch.setattr(settings, "auth_allowed_emails", [])
    monkeypatch.setattr(settings, "admin_emails", [])
    with pytest.raises(HTTPException) as exc_info:
        await login_router.register(
            RegisterRequest(email=MEMBER_EMAIL, password="long-enough-pass")
        )
    assert exc_info.value.status_code == 403


# ── login ────────────────────────────────────────────────────────────────────


async def test_login_with_correct_password(users) -> None:
    await login_router.register(RegisterRequest(email=MEMBER_EMAIL, password="long-enough-pass"))

    response = await login_router.login(
        EmailLoginRequest(email=MEMBER_EMAIL, password="long-enough-pass")
    )

    assert response.email == MEMBER_EMAIL
    assert response.role == "member"
    assert len(response.token) > 50


async def test_login_wrong_password_is_uniform_401(users) -> None:
    await login_router.register(RegisterRequest(email=MEMBER_EMAIL, password="long-enough-pass"))

    wrong = pytest.raises(HTTPException)
    with wrong as exc_info:
        await login_router.login(EmailLoginRequest(email=MEMBER_EMAIL, password="wrong-password"))
    assert exc_info.value.status_code == 401

    # unknown email answers identically (no account enumeration)
    with pytest.raises(HTTPException) as unknown:
        await login_router.login(
            EmailLoginRequest(email="nobody@example.com", password="whatever-pass")
        )
    assert unknown.value.status_code == 401
    assert unknown.value.detail == exc_info.value.detail


async def test_login_promotes_admin_email_role(users) -> None:
    user = User(
        id=uuid.uuid4(),
        tenant_id="main",
        name="Root",
        email=ADMIN_EMAIL,
        password_hash=hash_password("long-enough-pass"),
        role="member",  # registered before being added to ADMIN_EMAILS
    )
    users[ADMIN_EMAIL] = user

    response = await login_router.login(
        EmailLoginRequest(email=ADMIN_EMAIL, password="long-enough-pass")
    )
    assert response.role == "admin"


# ── passwords module ─────────────────────────────────────────────────────────


def test_password_hashing_roundtrip_and_uniqueness() -> None:
    first = hash_password("same-password-1")
    second = hash_password("same-password-1")
    assert first != second  # unique salts
    assert verify_password("same-password-1", first)
    assert verify_password("same-password-1", second)
    assert not verify_password("other", first)
    assert not verify_password("same-password-1", None)
    assert not verify_password("same-password-1", "garbage")


async def test_open_registration_allows_any_email(users, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "open_registration", True)
    response = await login_router.register(
        RegisterRequest(email="random.person@gmail.com", password="long-enough-pass")
    )
    assert response.email == "random.person@gmail.com"
    assert response.role == "member"


async def test_login_never_demotes_admin_granted_role(users) -> None:
    """A role granted via the admin panel survives login (only ADMIN_EMAILS
    may promote; it must not overwrite an existing admin grant)."""
    user = User(
        id=uuid.uuid4(),
        tenant_id="main",
        name="Deputy",
        email=MEMBER_EMAIL,  # NOT in ADMIN_EMAILS
        password_hash=hash_password("long-enough-pass"),
        role="admin",
    )
    users[MEMBER_EMAIL] = user

    response = await login_router.login(
        EmailLoginRequest(email=MEMBER_EMAIL, password="long-enough-pass")
    )
    assert response.role == "admin"
    assert response.is_admin is True
