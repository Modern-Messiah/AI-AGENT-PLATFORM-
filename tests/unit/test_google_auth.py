"""Unit tests for Google OAuth login and JWT sessions.

The Google legs (token exchange, tokeninfo) are mocked with fakes; everything
else — state signing, token issue/verify, Bearer auth, admin-role separation,
user upsert — runs against the real code paths.
"""

from __future__ import annotations

import time
import uuid
from types import SimpleNamespace

import jwt as pyjwt
import pytest
from apps.api.routers import login as login_router
from fastapi import HTTPException
from packages.auth import (
    actor_from_claims,
    require_actor,
    require_admin_principal,
    require_tenant,
)
from packages.auth.jwt_sessions import (
    AuthConfigError,
    create_oauth_state,
    create_session_token,
    google_login_configured,
    verify_oauth_state,
    verify_session_token,
)
from packages.core import settings
from packages.storage import User

JWT_SECRET = "unit-test-jwt-secret"


@pytest.fixture(autouse=True)
def _auth_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_jwt_secret", JWT_SECRET)
    monkeypatch.setattr(settings, "google_client_id", "google-client-id")
    monkeypatch.setattr(settings, "google_client_secret", "google-client-secret")
    monkeypatch.setattr(settings, "admin_emails", ["root@example.com"])
    monkeypatch.setattr(settings, "default_tenant_id", "main")
    monkeypatch.setattr(settings, "open_registration", False)


# ── session tokens ───────────────────────────────────────────────────────────


def _token(role: str = "member", **overrides: object) -> str:
    claims: dict[str, object] = {
        "type": "session",
        "sub": str(uuid.uuid4()),
        "tid": "main",
        "email": "user@example.com",
        "name": "User",
        "role": role,
        "exp": int(time.time()) + 3600,
    }
    claims.update(overrides)
    return pyjwt.encode(claims, JWT_SECRET, algorithm="HS256")


def test_session_token_roundtrip() -> None:
    user_id = uuid.uuid4()
    token = create_session_token(
        user_id=user_id, tenant_id="main", email="a@x.io", name="A", role="admin"
    )
    claims = verify_session_token(token)

    assert claims["type"] == "session"
    assert claims["sub"] == str(user_id)
    assert claims["tid"] == "main"
    assert claims["role"] == "admin"
    actor = actor_from_claims(claims)
    assert actor.is_admin
    assert actor.email == "a@x.io"


def test_expired_session_token_rejected() -> None:
    token = _token(exp=int(time.time()) - 10)
    with pytest.raises(HTTPException) as exc_info:
        verify_session_token(token)
    assert exc_info.value.status_code == 401
    assert "expired" in str(exc_info.value.detail)


def test_tampered_and_foreign_tokens_rejected() -> None:
    with pytest.raises(HTTPException):
        verify_session_token(_token(role="admin") + "x")
    with pytest.raises(HTTPException):
        verify_session_token(pyjwt.encode({"type": "session"}, "other-secret", algorithm="HS256"))
    with pytest.raises(HTTPException):
        # state tokens must not authenticate as sessions
        verify_session_token(
            create_oauth_state(
                redirect_uri="http://localhost:5173/login",
                callback="http://127.0.0.1:8000/auth/google/callback",
            )
        )


def test_sessions_require_configured_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_jwt_secret", "")
    assert google_login_configured() is False
    with pytest.raises(AuthConfigError):
        create_session_token(
            user_id=uuid.uuid4(), tenant_id="t", email="e", name="n", role="member"
        )


# ── Bearer auth path ─────────────────────────────────────────────────────────


async def test_require_actor_prefers_bearer_session() -> None:
    token = _token(role="member", email="alice@example.com", name="Alice")
    actor = await require_actor(authorization=f"Bearer {token}")

    assert actor.tenant_id == "main"
    assert actor.email == "alice@example.com"
    assert actor.is_admin is False
    assert actor.api_key_id is None


async def test_require_actor_rejects_bad_bearer() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await require_actor(authorization="Bearer not-a-token")
    assert exc_info.value.status_code == 401


async def test_admin_principal_accepts_admin_session_and_secret() -> None:
    principal = await require_admin_principal(authorization=f"Bearer {_token(role='admin')}")
    assert principal.via == "session"
    assert principal.actor is not None and principal.actor.is_admin

    principal = await require_admin_principal(x_admin_secret=settings.admin_secret)
    assert principal.via == "secret"


async def test_admin_principal_rejects_member_session() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await require_admin_principal(authorization=f"Bearer {_token(role='member')}")
    assert exc_info.value.status_code == 403


# ── oauth state ──────────────────────────────────────────────────────────────


def test_oauth_state_roundtrip_and_tampering() -> None:
    state = create_oauth_state(
        redirect_uri="http://localhost:5173/login",
        callback="http://127.0.0.1:8000/auth/google/callback",
    )
    assert verify_oauth_state(state) == (
        "http://localhost:5173/login",
        "http://127.0.0.1:8000/auth/google/callback",
    )

    with pytest.raises(HTTPException):
        verify_oauth_state(state + "tamper")

    expired = pyjwt.encode(
        {
            "type": "state",
            "redirect_uri": "http://localhost:5173/login",
            "exp": int(time.time()) - 5,
        },
        JWT_SECRET,
        algorithm="HS256",
    )
    with pytest.raises(HTTPException):
        verify_oauth_state(expired)


# ── /auth/google/url ─────────────────────────────────────────────────────────


def _request(base: str = "http://127.0.0.1:8000") -> SimpleNamespace:
    return SimpleNamespace(base_url=base)


async def test_google_url_builds_consent_url() -> None:
    response = await login_router.google_login_url(
        request=_request(), redirect="http://localhost:5173/login"
    )

    assert response.url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "client_id=google-client-id" in response.url
    assert "scope=openid+email+profile" in response.url
    assert "state=" in response.url


async def test_google_url_rejects_untrusted_redirect() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await login_router.google_login_url(
            request=_request(), redirect="https://evil.example.com/login"
        )
    assert exc_info.value.status_code == 400


async def test_google_url_503_when_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "google_client_id", "")
    with pytest.raises(HTTPException) as exc_info:
        await login_router.google_login_url(
            request=_request(), redirect="http://localhost:5173/login"
        )
    assert exc_info.value.status_code == 503


# ── /auth/google/callback ────────────────────────────────────────────────────


class FakeUserSession:
    """In-memory users stand-in for the upsert path."""

    def __init__(self) -> None:
        self.users: dict[str, User] = {}

    async def __aenter__(self) -> FakeUserSession:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def begin(self) -> FakeUserSession:
        return self

    async def execute(self, statement: object) -> object:
        class Result:
            def __init__(self, row: object) -> None:
                self.row = row

            def scalar_one_or_none(self) -> object:
                return self.row

        text = str(statement)
        import re

        match = re.search(r"users\.email = :email_1", text)
        assert match, text  # lookup by email as required
        email = self._last_email
        return Result(self.users.get(email))

    _last_email: str = ""

    def add(self, user: User) -> None:
        self.users[user.email] = user


@pytest.fixture
def fake_users(monkeypatch: pytest.MonkeyPatch) -> FakeUserSession:
    session = FakeUserSession()

    async def get_email(email: str) -> str:
        session._last_email = email
        return email

    # _upsert_google_user builds the lookup with a bound param; run it for real
    # by stubbing select() results through the fake session's execute hook.
    monkeypatch.setattr(login_router, "async_session", lambda: session)
    return session


class FakeAsyncClient:
    """Serves the Google token exchange and tokeninfo endpoints."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def __aenter__(self) -> FakeAsyncClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, data: dict[str, str]) -> SimpleNamespace:
        class Resp:
            status_code = 200

            def json(self) -> dict[str, object]:
                return {"id_token": "fake-id-token"}

        return Resp()

    async def get(self, url: str, params: dict[str, str]) -> SimpleNamespace:
        class Resp:
            status_code = 200

            def json(self) -> dict[str, object]:
                return {
                    "aud": settings.google_client_id,
                    "iss": "accounts.google.com",
                    "email_verified": "true",
                    "email": "root@example.com",
                    "name": "Root Admin",
                }

        return Resp()


async def test_callback_issues_admin_session_for_admin_email(
    monkeypatch: pytest.MonkeyPatch, fake_users: FakeUserSession
) -> None:
    monkeypatch.setattr(login_router.httpx, "AsyncClient", FakeAsyncClient)

    state = create_oauth_state(
        redirect_uri="http://localhost:5173/login",
        callback="http://127.0.0.1:8000/auth/google/callback",
    )
    response = await login_router.google_login_callback(
        request=_request(), code="auth-code", state=state, error=""
    )

    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("http://localhost:5173/login#token=")
    token = location.split("#token=", 1)[1]
    claims = verify_session_token(token)
    assert claims["email"] == "root@example.com"
    assert claims["role"] == "admin"

    # user was created in the default tenant
    user = fake_users.users["root@example.com"]
    assert user.tenant_id == "main"
    assert user.role == "admin"


async def test_callback_redirects_google_errors_back(monkeypatch: pytest.MonkeyPatch) -> None:
    state = create_oauth_state(
        redirect_uri="http://localhost:5173/login",
        callback="http://127.0.0.1:8000/auth/google/callback",
    )
    response = await login_router.google_login_callback(
        request=_request(), code="", state=state, error="access_denied"
    )

    assert response.status_code == 302
    assert "#error=access_denied" in response.headers["location"]


async def test_callback_rejects_tampered_state(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await login_router.google_login_callback(
            request=_request(), code="c", state="not-a-state", error=""
        )
    assert exc_info.value.status_code == 400


# ── /auth/me ─────────────────────────────────────────────────────────────────


async def test_whoami_reports_session_principal() -> None:
    token = _token(role="member", email="bob@example.com", name="Bob")
    actor = await require_actor(authorization=f"Bearer {token}")
    info = await login_router.whoami(actor)

    assert info.email == "bob@example.com"
    assert info.is_admin is False
    assert info.tenant_id == "main"


async def test_require_tenant_accepts_bearer_sessions() -> None:
    # /documents & co. use the TenantID dependency — it must forward the
    # Authorization header, not just the API key.
    token = _token(role="member")
    tenant_id = await require_tenant(authorization=f"Bearer {token}")
    assert tenant_id == "main"
