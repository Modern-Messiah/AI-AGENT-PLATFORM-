"""Unit tests for per-user analytics attribution and endpoints."""

from __future__ import annotations

import pytest
from apps.api.routers import admin as admin_router
from apps.api.routers import analytics as analytics_router
from fastapi import HTTPException
from packages.agents.schemas import AgentRunInput
from packages.analytics.events import UsageEvent
from packages.auth import Actor, require_admin_principal


def test_usage_event_carries_user_id() -> None:
    event = UsageEvent(
        tenant_id="t",
        workflow_id="w",
        run_id="r",
        model="moonshot/kimi-k2.6",
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=100,
        user_id="u-1",
    )
    assert event.user_id == "u-1"
    # default остаётся пустым (старые вызовы без атрибуции)
    assert (
        UsageEvent(
            tenant_id="t",
            workflow_id="w",
            run_id="r",
            model="m",
            prompt_tokens=1,
            completion_tokens=1,
            latency_ms=1,
        ).user_id
        == ""
    )


def test_agent_run_input_accepts_user_id() -> None:
    payload = AgentRunInput(user_query="q", user_id="u-1")
    assert payload.user_id == "u-1"


# ── /analytics/usage scope ───────────────────────────────────────────────────


class FakeCH:
    def __init__(self) -> None:
        self.queries: list[tuple[str, dict[str, object]]] = []

    async def query(self, sql: str, params: dict[str, object]) -> list[dict[str, object]]:
        self.queries.append((sql, dict(params)))
        return []


@pytest.fixture
def fake_ch(monkeypatch: pytest.MonkeyPatch) -> FakeCH:
    ch = FakeCH()
    monkeypatch.setattr(analytics_router, "ch_client", ch)
    return ch


async def test_personal_scope_filters_by_user(fake_ch: FakeCH) -> None:
    import uuid

    actor = Actor(tenant_id="t", role="member", user_id=uuid.uuid4())
    result = await analytics_router.get_usage(actor=actor, days=7)

    assert result["scope"] == "user"
    sql, params = fake_ch.queries[0]
    assert "user_id = {user_id:String}" in sql
    assert params["user_id"] == str(actor.user_id)


async def test_tenant_scope_for_unbound_keys(fake_ch: FakeCH) -> None:
    actor = Actor(tenant_id="t", role=None)  # ключ без пользователя
    result = await analytics_router.get_usage(actor=actor, days=7)

    assert result["scope"] == "tenant"
    sql, params = fake_ch.queries[0]
    assert "user_id" not in params
    assert "user_id = " not in sql


async def test_admin_can_switch_to_personal_scope(fake_ch: FakeCH) -> None:
    import uuid

    actor = Actor(tenant_id="t", role="admin", user_id=uuid.uuid4())
    result = await analytics_router.get_usage(actor=actor, days=7, scope="user")

    assert result["scope"] == "user"
    assert result["can_switch_scope"] is True
    sql, params = fake_ch.queries[0]
    assert "user_id = {user_id:String}" in sql
    assert params["user_id"] == str(actor.user_id)


async def test_admin_defaults_to_personal_scope(fake_ch: FakeCH) -> None:
    import uuid

    actor = Actor(tenant_id="t", role="admin", user_id=uuid.uuid4())
    result = await analytics_router.get_usage(actor=actor, days=7, scope="auto")

    assert result["scope"] == "user"
    assert result["can_switch_scope"] is True
    sql, params = fake_ch.queries[0]
    assert "user_id = {user_id:String}" in sql
    assert params["user_id"] == str(actor.user_id)


async def test_admin_can_switch_to_tenant_scope(fake_ch: FakeCH) -> None:
    import uuid

    actor = Actor(tenant_id="t", role="admin", user_id=uuid.uuid4())
    result = await analytics_router.get_usage(actor=actor, days=7, scope="tenant")

    assert result["scope"] == "tenant"
    assert result["can_switch_scope"] is True
    _sql, params = fake_ch.queries[0]
    assert "user_id" not in params


async def test_member_cannot_view_tenant_scope(fake_ch: FakeCH) -> None:
    import uuid

    actor = Actor(tenant_id="t", role="member", user_id=uuid.uuid4())
    result = await analytics_router.get_usage(actor=actor, days=7, scope="tenant")

    assert result["scope"] == "user"
    assert result["can_switch_scope"] is False
    sql, _params = fake_ch.queries[0]
    assert "user_id = {user_id:String}" in sql


# ── /admin/analytics/users ──────────────────────────────────────────────────


class UsersCH:
    async def query(self, sql: str, params: dict[str, object]) -> list[dict[str, object]]:
        return [
            {
                "user_id": "00000000-0000-0000-0000-000000000001",
                "cost_usd": 1.5,
                "total_tokens": 1000,
                "calls": 9,
                "avg_latency_ms": 1200,
            },
            {
                "user_id": "",
                "cost_usd": 0.2,
                "total_tokens": 100,
                "calls": 1,
                "avg_latency_ms": 900,
            },
        ]


class UsersAdminSession:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    def begin(self):
        return self

    async def execute(self, statement, params=None):
        class R:
            def __init__(self, rows):
                self.rows = rows

            def scalars(self):
                return self

            def all(self):
                return self.rows

        return R(self.rows)


async def test_admin_user_analytics_merges_names(monkeypatch) -> None:
    from types import SimpleNamespace

    from packages.auth import AdminPrincipal

    monkeypatch.setattr(admin_router, "ch_client", UsersCH())
    user = SimpleNamespace(id="00000000-0000-0000-0000-000000000001", name="Alice", email="a@x.io")
    monkeypatch.setattr(admin_router, "admin_session", lambda: UsersAdminSession([user]))

    rows = await admin_router.admin_user_analytics(
        _principal=AdminPrincipal(via="secret", actor=None), days=7, tenant_id=None
    )

    assert rows[0].user_name == "Alice"
    assert rows[0].email == "a@x.io"
    assert rows[0].calls == 9
    assert rows[1].user_id is None  # события по ключам без пользователя


async def test_admin_user_analytics_requires_admin() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await require_admin_principal(x_admin_secret="wrong")
    assert exc_info.value.status_code == 403
