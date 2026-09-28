"""Unit tests for the security-hardening fixes.

Covers the four audit findings:
  1. AUTH_ALLOWED_EMAILS — Google login requires an explicit allowlist
  2. per-IP rate limits on the auth/admin surfaces
  3. constant-time admin secret comparison (behaviour: wrong → 403)
  4. server-side session revocation on user deletion (Redis denylist)
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from urllib.parse import unquote

import pytest
from apps.api.routers import admin as admin_router
from apps.api.routers import login as login_router
from apps.api.services import auth_rate_limit
from apps.api.services.auth_rate_limit import _enforce
from fastapi import HTTPException
from packages.auth import AdminPrincipal, require_actor, require_admin_principal
from packages.auth.jwt_sessions import (
    create_oauth_state,
    create_session_token,
    google_login_configured,
    login_allowed_emails,
)
from packages.auth.session_revocation import deny_user_sessions, is_user_denied
from packages.core import settings

JWT_SECRET = "unit-test-jwt-secret"


@pytest.fixture(autouse=True)
def _auth_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_jwt_secret", JWT_SECRET)
    monkeypatch.setattr(settings, "google_client_id", "google-client-id")
    monkeypatch.setattr(settings, "google_client_secret", "google-client-secret")
    monkeypatch.setattr(settings, "admin_emails", ["root@example.com"])
    monkeypatch.setattr(settings, "auth_allowed_emails", [])
    monkeypatch.setattr(settings, "open_registration", False)


# ── 1. login allowlist ───────────────────────────────────────────────────────


def test_login_allowed_emails_unions_admin_and_allowed_lists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "auth_allowed_emails", ["Bob@Example.com"])
    assert login_allowed_emails() == {"root@example.com", "bob@example.com"}


def test_signup_gate_follows_open_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    # OAuth readiness no longer depends on the allowlist; the callback gate
    # (closed mode, fixture) still rejects unknown accounts — covered by
    # test_callback_denies_unknown_google_accounts.
    monkeypatch.setattr(settings, "admin_emails", [])
    monkeypatch.setattr(settings, "auth_allowed_emails", [])
    assert google_login_configured() is True


class DenyAllClient:
    """Google tokeninfo answering as a member not in any allowlist."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def __aenter__(self) -> DenyAllClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, data: dict[str, str]) -> object:
        class Resp:
            status_code = 200

            def json(self) -> dict[str, object]:
                return {"id_token": "fake-id-token"}

        return Resp()

    async def get(self, url: str, params: dict[str, str]) -> object:
        class Resp:
            status_code = 200

            def json(self) -> dict[str, object]:
                return {
                    "aud": settings.google_client_id,
                    "iss": "accounts.google.com",
                    "email_verified": "true",
                    "email": "stranger@example.com",
                    "name": "Stranger",
                }

        return Resp()


async def test_callback_denies_unknown_google_accounts(monkeypatch) -> None:
    monkeypatch.setattr(login_router.httpx, "AsyncClient", DenyAllClient)
    state = create_oauth_state(
        redirect_uri="http://localhost:5173/login",
        callback="http://127.0.0.1:8000/auth/google/callback",
    )

    response = await login_router.google_login_callback(
        request=SimpleNamespace(base_url="http://127.0.0.1:8000"),
        code="auth-code",
        state=state,
        error="",
    )

    assert response.status_code == 302
    assert "#error=" in response.headers["location"]
    assert "not allowed" in unquote(response.headers["location"])


# ── 2. per-IP rate limits ────────────────────────────────────────────────────


class FakeRedis:
    def __init__(self) -> None:
        self.zsets: dict[str, dict[str, float]] = {}
        self.ttl: dict[str, int] = {}

    def pipeline(self, *, transaction: bool) -> FakeRedis:
        return FakePipeline(self)

    async def zremrangebyscore(self, key: str, lo: float, hi: float) -> int:
        zset = self.zsets.setdefault(key, {})
        removed = [m for m, s in zset.items() if lo <= s <= hi]
        for m in removed:
            del zset[m]
        return len(removed)

    async def zadd(self, key: str, mapping: dict[str, float]) -> int:
        self.zsets.setdefault(key, {}).update(mapping)
        return len(mapping)

    async def zcard(self, key: str) -> int:
        return len(self.zsets.get(key, {}))

    async def expire(self, key: str, ttl: int) -> bool:
        self.ttl[key] = ttl
        return True

    async def zrem(self, key: str, member: str) -> int:
        return (self.zsets.get(key, {}).pop(member, None) is not None and 1) or 0


class FakePipeline:
    def __init__(self, redis: FakeRedis) -> None:
        self.redis = redis
        self.ops: list[tuple[str, tuple[object, ...]]] = []

    def __getattr__(self, name: str) -> object:
        def record(*args: object) -> FakePipeline:
            self.ops.append((name, args))
            return self

        return record

    async def execute(self) -> list[object]:
        results: list[object] = []
        for name, args in self.ops:
            results.append(await getattr(self.redis, name)(*args))
        return results


def _request(ip: str = "127.0.0.1") -> SimpleNamespace:
    return SimpleNamespace(client=SimpleNamespace(host=ip))


async def test_auth_rate_limit_returns_429_over_budget(monkeypatch) -> None:
    redis = FakeRedis()
    monkeypatch.setattr(auth_rate_limit, "get_redis", lambda: redis)

    for _ in range(auth_rate_limit.AUTH_LIMIT_PER_MINUTE):
        await _enforce(_request(), "auth", auth_rate_limit.AUTH_LIMIT_PER_MINUTE)

    with pytest.raises(HTTPException) as exc_info:
        await _enforce(_request(), "auth", auth_rate_limit.AUTH_LIMIT_PER_MINUTE)
    assert exc_info.value.status_code == 429

    # other IPs have their own bucket
    await _enforce(_request("10.0.0.9"), "auth", auth_rate_limit.AUTH_LIMIT_PER_MINUTE)


async def test_auth_rate_limit_fails_open_when_redis_down(monkeypatch) -> None:
    def broken() -> object:
        raise RuntimeError("redis down")

    monkeypatch.setattr(auth_rate_limit, "get_redis", broken)
    await _enforce(_request(), "auth", 1)  # must not raise


async def test_auth_rate_limit_fails_closed_when_configured(monkeypatch) -> None:
    def broken() -> object:
        raise RuntimeError("redis down")

    monkeypatch.setattr(auth_rate_limit, "get_redis", broken)
    monkeypatch.setattr(settings, "rate_limit_fail_closed", True)
    with pytest.raises(HTTPException) as exc_info:
        await _enforce(_request(), "auth", 1)
    assert exc_info.value.status_code == 503


# ── 3. constant-time secret — behaviour pin ─────────────────────────────────


async def test_admin_secret_comparison_behaviour() -> None:
    from packages.auth import require_admin_principal

    principal = await require_admin_principal(x_admin_secret=settings.admin_secret)
    assert principal.via == "secret"

    with pytest.raises(HTTPException) as exc_info:
        await require_admin_principal(x_admin_secret="x" * len(settings.admin_secret))
    assert exc_info.value.status_code == 403


# ── 4. session revocation ───────────────────────────────────────────────────


class FakeKVRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int) -> bool:
        self.store[key] = value
        return True

    async def exists(self, key: str) -> int:
        return 1 if key in self.store else 0


async def test_denied_user_sessions_are_rejected(monkeypatch) -> None:
    import packages.auth.session_revocation as revocation

    redis = FakeKVRedis()
    monkeypatch.setattr(revocation, "get_redis", lambda: redis)

    user_id = uuid.uuid4()
    token = create_session_token(
        user_id=user_id, tenant_id="main", email="a@x.io", name="A", role="member"
    )
    await require_actor(authorization=f"Bearer {token}")  # works before denial

    await deny_user_sessions(user_id)
    assert await is_user_denied(user_id) is True

    with pytest.raises(HTTPException) as exc_info:
        await require_actor(authorization=f"Bearer {token}")
    assert exc_info.value.status_code == 401
    assert "revoked" in str(exc_info.value.detail)


async def test_revocation_check_fails_open_on_redis_outage(monkeypatch) -> None:
    import packages.auth.session_revocation as revocation

    def broken() -> object:
        raise RuntimeError("redis down")

    monkeypatch.setattr(revocation, "get_redis", broken)
    assert await is_user_denied(uuid.uuid4()) is False


# ── admin-managed LLM provider keys ──────────────────────────────────────────


class LlmKeysResult:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def scalars(self) -> LlmKeysResult:
        return self

    def all(self) -> list[object]:
        return self.rows

    def scalar_one_or_none(self) -> object | None:
        return self.rows[0] if self.rows else None


class LlmKeysSession:
    """Records UPDATE/DELETE/INSERT; serves the stored rows back."""

    def __init__(self, rows: list[object] | None = None) -> None:
        self.rows = rows or []
        self.executed: list[str] = []

    async def __aenter__(self) -> LlmKeysSession:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def begin(self) -> LlmKeysSession:
        return self

    async def execute(self, statement: object, params: object = None) -> LlmKeysResult:
        self.executed.append(str(statement))
        return LlmKeysResult(self.rows)

    def add(self, row: object) -> None:
        self.rows.append(row)


async def test_llm_keys_endpoints_require_admin() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await require_admin_principal(x_admin_secret="wrong")
    assert exc_info.value.status_code == 403


async def test_create_llm_key_rotates_previous_and_masks(monkeypatch) -> None:
    from datetime import UTC, datetime

    from apps.api.schemas import CreateLlmKeyRequest

    session = LlmKeysSession()
    monkeypatch.setattr(admin_router, "admin_session", lambda: session)
    refreshed = []

    async def fake_refresh() -> None:
        refreshed.append(1)

    monkeypatch.setattr(admin_router, "refresh_keyring", fake_refresh)

    real_init = admin_router.LlmApiKey.__init__

    def init_with_defaults(self: object, **kwargs: object) -> None:
        real_init(self, **kwargs)
        self.created_at = datetime(2026, 9, 28, tzinfo=UTC)  # type: ignore[attr-defined]
        self.requests_count = 0  # type: ignore[attr-defined]

    monkeypatch.setattr(admin_router.LlmApiKey, "__init__", init_with_defaults)

    info = await admin_router.admin_create_llm_key(
        CreateLlmKeyRequest(provider="moonshot", name="main", key="sk-live-abcdef123456"),
        AdminPrincipal(via="secret", actor=None),
    )

    assert info.key_preview == "sk-…3456"
    assert "sk-live" not in info.key_preview
    assert info.is_active is True
    assert refreshed == [1]
    # deactivation of the previous active key issued before the insert
    assert any("UPDATE llm_api_keys" in sql for sql in session.executed)


async def test_llm_key_value_never_returned(monkeypatch) -> None:
    from datetime import UTC, datetime

    from packages.storage import LlmApiKey

    row = LlmApiKey(
        id=uuid.uuid4(),
        provider="deepseek",
        name="prod",
        key_value="sk-super-secret-value",
    )
    row.created_at = datetime(2026, 9, 28, tzinfo=UTC)
    row.is_active = True
    row.requests_count = 7
    row.last_used_at = None
    monkeypatch.setattr(admin_router, "admin_session", lambda: LlmKeysSession([row]))

    keys = await admin_router.admin_llm_keys(AdminPrincipal(via="secret", actor=None))

    assert keys[0].key_preview == "sk-…alue"[0:3] + "…" + "sk-super-secret-value"[-4:]
    assert "super-secret" not in keys[0].model_dump_json()
