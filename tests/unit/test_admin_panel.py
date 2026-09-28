"""Unit tests for the admin panel API (X-Admin-Secret surface).

Focus: every endpoint is registered, every endpoint rejects a bad secret,
the usage aggregation math is right, and the prompt feed pagination/preview
contract holds. DB/ClickHouse access is faked — live behaviour is covered
by the e2e smoke suite.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from apps.api.main import app
from apps.api.routers import admin as admin_router
from fastapi import HTTPException
from packages.core import settings
from packages.storage import AgentQueryLog, DocumentStatus

SECRET = "unit-test-admin-secret"


@pytest.fixture(autouse=True)
def _admin_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "admin_secret", SECRET)


def test_admin_routes_are_registered() -> None:
    routes = {
        (path, method.upper())
        for path, methods in app.openapi()["paths"].items()
        for method in methods
    }

    assert ("/admin/overview", "GET") in routes
    assert ("/admin/tenants", "GET") in routes
    assert ("/admin/users", "GET") in routes
    assert ("/admin/prompts", "GET") in routes
    assert ("/admin/documents", "GET") in routes
    assert ("/admin/usage", "GET") in routes
    assert ("/admin/health", "GET") in routes


@pytest.mark.parametrize(
    "endpoint",
    [
        lambda: admin_router.admin_overview(x_admin_secret="wrong"),
        lambda: admin_router.admin_tenants(x_admin_secret="wrong"),
        lambda: admin_router.admin_users(x_admin_secret="wrong"),
        lambda: admin_router.admin_prompts(x_admin_secret="wrong"),
        lambda: admin_router.admin_prompt_detail(log_id=uuid.uuid4(), x_admin_secret="wrong"),
        lambda: admin_router.admin_documents(x_admin_secret="wrong"),
        lambda: admin_router.admin_usage(x_admin_secret="wrong"),
        lambda: admin_router.admin_health(request=SimpleNamespace(), x_admin_secret="wrong"),
    ],
)
async def test_admin_endpoints_reject_bad_secret(endpoint) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await endpoint()
    assert exc_info.value.status_code == 403


# ── /admin/usage aggregation ─────────────────────────────────────────────────


class FakeClickHouse:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def query(self, sql: str, params: dict[str, object]) -> list[dict[str, object]]:
        self.queries.append(sql)
        if "GROUP BY tenant_id" in sql:
            return [
                {"tenant_id": "tenant-a", "cost_usd": 1.5, "total_tokens": 1000, "calls": 10},
                {"tenant_id": "tenant-b", "cost_usd": 0.5, "total_tokens": 500, "calls": 5},
            ]
        if "GROUP BY model, provider" in sql:
            return [
                {
                    "model": "kimi-k2.6",
                    "provider": "moonshot",
                    "cost_usd": 2.0,
                    "total_tokens": 1500,
                    "calls": 15,
                    "avg_latency_ms": 2000,
                },
            ]
        return [
            {"day": "2026-09-27", "cost_usd": 1.0, "total_tokens": 800, "calls": 8},
            {"day": "2026-09-28", "cost_usd": 1.0, "total_tokens": 700, "calls": 7},
        ]


async def test_admin_usage_aggregates_totals_from_model_rows(monkeypatch) -> None:
    fake = FakeClickHouse()
    monkeypatch.setattr(admin_router, "ch_client", fake)

    response = await admin_router.admin_usage(x_admin_secret=SECRET, days=7)

    assert response.days == 7
    assert response.totals.cost_usd == 2.0
    assert response.totals.total_tokens == 1500
    assert response.totals.calls == 15
    assert response.totals.avg_latency_ms == 2000
    assert [t.tenant_id for t in response.by_tenant] == ["tenant-a", "tenant-b"]
    assert len(response.by_model) == 1
    assert len(response.daily) == 2
    assert len(fake.queries) == 3


async def test_admin_usage_maps_clickhouse_failure_to_500(monkeypatch) -> None:
    class BrokenClickHouse:
        async def query(self, sql: str, params: dict[str, object]) -> list[dict[str, object]]:
            raise RuntimeError("clickhouse down")

    monkeypatch.setattr(admin_router, "ch_client", BrokenClickHouse())

    with pytest.raises(HTTPException) as exc_info:
        await admin_router.admin_usage(x_admin_secret=SECRET, days=7)
    assert exc_info.value.status_code == 500
    assert "ClickHouse error" in str(exc_info.value.detail)


# ── /admin/prompts feed ──────────────────────────────────────────────────────


class FakeScalars:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def all(self) -> list[object]:
        return self.rows


class FakeResult:
    def __init__(self, rows: list[object], scalar_value: int) -> None:
        self._scalars = FakeScalars(rows)
        self._scalar_value = scalar_value

    def scalar(self) -> int:
        return self._scalar_value

    def scalar_one_or_none(self) -> object | None:
        return self._scalars.all()[0] if self._scalars.all() else None

    def scalars(self) -> FakeScalars:
        return self._scalars


class FakeAdminSession:
    """Returns the count for SELECT count(...) and the rows otherwise."""

    def __init__(self, rows: list[object], total: int) -> None:
        self.rows = rows
        self.total = total
        self.statements: list[str] = []

    async def __aenter__(self) -> FakeAdminSession:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def begin(self) -> FakeAdminSession:
        return self

    async def execute(self, statement: object) -> FakeResult:
        text = str(statement)
        self.statements.append(text)
        if text.startswith("SELECT count("):
            return FakeResult([], self.total)
        return FakeResult(self.rows, self.total)


def _log_row(answer: str = "короткий ответ") -> AgentQueryLog:
    return AgentQueryLog(
        id=uuid.uuid4(),
        tenant_id="tenant-a",
        user_name="alice",
        mode="stream",
        model="moonshot/kimi-k2.6",
        query="вопрос",
        answer=answer,
        status="ok",
        latency_ms=432,
        cached=False,
        confidence=0.8,
        sources_count=2,
        prompt_tokens=100,
        completion_tokens=50,
        cost_usd=0.01,
        created_at=datetime(2026, 9, 28, 12, 0, tzinfo=UTC),
    )


async def test_admin_prompts_returns_paginated_feed_with_previews(monkeypatch) -> None:
    row = _log_row(answer="д" * 5_000)
    session = FakeAdminSession(rows=[row], total=42)
    monkeypatch.setattr(admin_router, "admin_session", lambda: session)

    response = await admin_router.admin_prompts(
        x_admin_secret=SECRET,
        tenant_id="tenant-a",
        user_id=None,
        mode=None,
        status=None,
        q=None,
        days=30,
        limit=10,
        offset=20,
    )

    assert response.total == 42
    assert response.limit == 10
    assert response.offset == 20
    assert len(response.items) == 1
    item = response.items[0]
    assert item.tenant_id == "tenant-a"
    assert item.user_name == "alice"
    assert item.mode == "stream"
    assert len(item.answer_preview) == admin_router._ANSWER_PREVIEW_CHARS
    # list responses never carry the full answer — only the detail endpoint does
    assert not hasattr(item, "answer")


async def test_admin_prompt_detail_returns_full_answer(monkeypatch) -> None:
    row = _log_row()

    class FoundSession(FakeAdminSession):
        async def execute(self, statement: object) -> FakeResult:
            return FakeResult([row], 1)

    monkeypatch.setattr(admin_router, "admin_session", lambda: FoundSession([], 1))

    detail = await admin_router.admin_prompt_detail(log_id=row.id, x_admin_secret=SECRET)

    assert detail.answer == "короткий ответ"
    assert detail.retrieval_query is None
    assert detail.sources_count == 2


async def test_admin_prompt_detail_404_for_missing_entry(monkeypatch) -> None:
    class EmptySession(FakeAdminSession):
        async def execute(self, statement: object) -> FakeResult:
            return FakeResult([], 0)

    monkeypatch.setattr(admin_router, "admin_session", lambda: EmptySession([], 0))

    with pytest.raises(HTTPException) as exc_info:
        await admin_router.admin_prompt_detail(log_id=uuid.uuid4(), x_admin_secret=SECRET)
    assert exc_info.value.status_code == 404


# ── /admin/health ────────────────────────────────────────────────────────────


async def test_admin_health_reports_fresh_checks(monkeypatch) -> None:
    async def fake_check(name: str, request: object) -> tuple[str, str]:
        return name, "ok" if name != "redis" else "error: ConnectionError"

    monkeypatch.setattr(admin_router, "_run_check", fake_check)

    response = await admin_router.admin_health(request=SimpleNamespace(), x_admin_secret=SECRET)

    assert response.status == "unavailable"
    assert response.checks["postgres"] == "ok"
    assert response.checks["redis"] == "error: ConnectionError"
    assert set(response.checks) == set(admin_router._CHECK_NAMES)


# ── /admin/overview SQL ──────────────────────────────────────────────────────


class OverviewResult:
    def __init__(self, payload: object, one_row: tuple[int, int, int] | None = None) -> None:
        self.payload = payload
        self.one_row = one_row or (5, 2, 1)

    def scalar(self) -> object:
        return self.payload

    def one(self) -> tuple[int, int, int]:
        return self.one_row

    def all(self) -> list[object]:
        if isinstance(self.payload, list):
            return self.payload
        return []


class OverviewSession:
    """Content-sniffing fake: serves scalar/one/all for the overview queries."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    async def __aenter__(self) -> OverviewSession:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def begin(self) -> OverviewSession:
        return self

    async def execute(self, statement: object, params: object = None) -> OverviewResult:
        sql = str(statement)
        self.statements.append(sql)
        if "generate_series" in sql:
            return OverviewResult([("2026-09-28", 3, 0)])
        if "FILTER" in sql and "FROM agent_query_logs" in sql:
            return OverviewResult(None)
        if "SELECT count" in sql or "count_1" in sql:
            return OverviewResult(1)
        return OverviewResult([(DocumentStatus.done, 2)])


async def test_admin_overview_daily_series_uses_cast_not_postgres_cast_operator(
    monkeypatch,
) -> None:
    # ':days::int' inside text() mangles the SQL sent to Postgres (live-stack
    # catch: "syntax error at or near ':'"). The bind must use CAST(... AS int).
    session = OverviewSession()
    monkeypatch.setattr(admin_router, "admin_session", lambda: session)

    response = await admin_router.admin_overview(x_admin_secret=SECRET)

    assert response.queries.total == 5
    assert response.daily_queries[-1].day == "2026-09-28"
    daily_sql = next(sql for sql in session.statements if "generate_series" in sql)
    assert "CAST(:days AS int)" in daily_sql
    assert "::int" not in daily_sql
