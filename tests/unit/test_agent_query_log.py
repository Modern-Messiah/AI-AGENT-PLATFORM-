"""Unit tests for the agent query audit trail (admin panel data source).

The log write is best-effort: these tests pin the field capping, the cost
estimate and the contract that DB failures never propagate to the answer
path. Router-level tests pin that /agent/* actually emits one entry per
request with the key owner's identity attached.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from apps.api.routers import agent as agent_router
from apps.api.schemas import AgentStreamRequest
from apps.api.services.query_log import (
    QueryLogEntry,
    estimated_cost_usd,
    log_agent_query,
)
from packages.agents.schemas import AgentRunInput, AgentRunOutput
from packages.auth import Actor
from packages.core import settings
from packages.storage import AgentQueryLog

# ── log_agent_query ───────────────────────────────────────────────────────────


class CaptureSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    async def __aenter__(self) -> CaptureSession:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def begin(self) -> CaptureSession:
        return self

    def add(self, row: object) -> None:
        self.added.append(row)


class RaisingSession:
    async def __aenter__(self) -> RaisingSession:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def begin(self) -> RaisingSession:
        return self

    def add(self, row: object) -> None:
        raise RuntimeError("database is down")


async def test_log_agent_query_persists_entry_with_capped_fields(monkeypatch) -> None:
    session = CaptureSession()
    monkeypatch.setattr("apps.api.services.query_log.tenant_session", lambda tenant_id: session)
    entry = QueryLogEntry(
        tenant_id="tenant-a",
        mode="stream",
        model="moonshot/kimi-k2.6",
        query="вопрос",
        answer="а" * 20_000,
        error="e" * 3_000,
        prompt_tokens=1_000,
        completion_tokens=500,
        confidence=0.8,
        sources_count=3,
        latency_ms=1234,
    )

    await log_agent_query(entry)

    assert len(session.added) == 1
    row = session.added[0]
    assert isinstance(row, AgentQueryLog)
    assert row.tenant_id == "tenant-a"
    assert row.mode == "stream"
    assert row.status == "ok"
    assert len(row.answer) == 8_000
    assert len(row.error) == 1_000
    assert row.prompt_tokens == 1_000
    assert row.cost_usd is not None and row.cost_usd > 0
    assert row.confidence == 0.8
    assert row.sources_count == 3
    assert row.latency_ms == 1234


async def test_log_agent_query_never_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.api.services.query_log.tenant_session", lambda tenant_id: RaisingSession()
    )

    await log_agent_query(
        QueryLogEntry(tenant_id="tenant-a", mode="run", model="m", query="q")
    )  # must not raise


# ── estimated_cost_usd ────────────────────────────────────────────────────────


def test_estimated_cost_is_none_without_tokens() -> None:
    assert estimated_cost_usd("moonshot/kimi-k2.6", 0, 0) is None


def test_estimated_cost_uses_short_model_name() -> None:
    # kimi-k2.6 is priced $0.60 in / $2.50 out per 1M tokens.
    cost = estimated_cost_usd("moonshot/kimi-k2.6", 1_000_000, 1_000_000)
    assert cost == 0.60 + 2.50


# ── router integration: /agent/run ───────────────────────────────────────────


class ScalarResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar(self) -> object:
        return self.value


class _ScalarsResult(ScalarResult):
    def scalars(self) -> ScalarResult:
        return self

    def all(self) -> list[object]:
        return self.value if isinstance(self.value, list) else []


class ScalarSession:
    """Backs both scalar() and scalars().all() results (accessible ids query)."""

    def __init__(self, value: object = 0, *, scalars_value: list[object] | None = None) -> None:
        self.value = value
        self.scalars_value = scalars_value if scalars_value is not None else []

    async def __aenter__(self) -> ScalarSession:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def begin(self) -> ScalarSession:
        return self

    async def execute(self, statement: object) -> ScalarResult:
        return _ScalarsResult(self.scalars_value)


async def test_run_agent_logs_empty_kb_answer_with_user_attribution(monkeypatch) -> None:
    entries: list[QueryLogEntry] = []

    async def fake_log(entry: QueryLogEntry) -> None:
        entries.append(entry)

    monkeypatch.setattr(agent_router, "tenant_session", lambda tenant_id: ScalarSession(0))
    monkeypatch.setattr(agent_router, "log_agent_query", fake_log)
    user_id = uuid.uuid4()
    actor = Actor(tenant_id="tenant-a", role="member", user_id=user_id, user_name="alice")
    request = SimpleNamespace(app=SimpleNamespace(state={}))

    response = await agent_router.run_agent(
        AgentRunInput(user_query="что в документах?", model="moonshot/kimi-k2.6"),
        actor,
        request,
    )

    assert entries == [
        QueryLogEntry(
            tenant_id="tenant-a",
            user_id=user_id,
            user_name="alice",
            mode="run",
            model="moonshot/kimi-k2.6",
            query="что в документах?",
            answer=response.answer,
            confidence=1.0,
        )
    ]


# ── router integration: /agent/stream (cached hit) ──────────────────────────


class FakeSemanticCache:
    def __init__(self, cached: AgentRunOutput | None) -> None:
        self.cached = cached

    async def get(self, query: str, tenant_id: str, scope: str = "tenant") -> AgentRunOutput | None:
        return self.cached

    async def set(
        self, query: str, tenant_id: str, result: AgentRunOutput, scope: str = "tenant"
    ) -> None:
        return None


async def test_agent_stream_logs_cached_hit(monkeypatch) -> None:
    entries: list[QueryLogEntry] = []

    async def fake_log(entry: QueryLogEntry) -> None:
        entries.append(entry)

    async def fake_limits(tenant_id: str, query: str, endpoint: str) -> str:
        return query

    monkeypatch.setattr(agent_router, "enforce_agent_limits", fake_limits)
    monkeypatch.setattr(agent_router, "log_agent_query", fake_log)
    monkeypatch.setattr(
        agent_router,
        "semantic_cache",
        FakeSemanticCache(AgentRunOutput(answer="из кэша", confidence=0.9, sources=["a.txt"])),
    )
    # Unscoped stream resolves the actor's accessible documents first.
    monkeypatch.setattr(
        agent_router,
        "tenant_session",
        lambda tenant_id: ScalarSession(scalars_value=[uuid.uuid4()]),
    )
    actor = Actor(tenant_id="tenant-a", role=None, user_id=uuid.uuid4(), user_name="bob")

    response = await agent_router.agent_stream(AgentStreamRequest(user_query="вопрос"), actor)
    body = "".join([chunk async for chunk in response.body_iterator])

    assert '"cached": true' in body
    assert len(entries) == 1
    entry = entries[0]
    assert entry.mode == "stream"
    assert entry.tenant_id == "tenant-a"
    assert entry.user_name == "bob"
    assert entry.cached is True
    assert entry.answer == "из кэша"
    assert entry.confidence == 0.9
    assert entry.sources_count == 1


async def test_run_agent_logs_api_key_attribution(monkeypatch) -> None:
    entries: list[QueryLogEntry] = []

    async def fake_log(entry: QueryLogEntry) -> None:
        entries.append(entry)

    monkeypatch.setattr(agent_router, "tenant_session", lambda tenant_id: ScalarSession(0))
    monkeypatch.setattr(agent_router, "log_agent_query", fake_log)
    key_id = uuid.uuid4()
    actor = Actor(
        tenant_id="tenant-a",
        role="member",
        user_id=uuid.uuid4(),
        user_name="alice",
        api_key_id=key_id,
        api_key_name="laptop",
    )
    request = SimpleNamespace(app=SimpleNamespace(state={}))

    await agent_router.run_agent(AgentRunInput(user_query="вопрос"), actor, request)

    assert entries[0].api_key_id == key_id
    assert entries[0].api_key_name == "laptop"


async def test_log_agent_query_persists_key_fields(monkeypatch) -> None:
    session = CaptureSession()
    monkeypatch.setattr("apps.api.services.query_log.tenant_session", lambda tenant_id: session)
    key_id = uuid.uuid4()

    await log_agent_query(
        QueryLogEntry(
            tenant_id="tenant-a",
            mode="stream",
            model="m",
            query="q",
            api_key_id=key_id,
            api_key_name="laptop",
        )
    )

    row = session.added[0]
    assert isinstance(row, AgentQueryLog)
    assert row.api_key_id == key_id
    assert row.api_key_name == "laptop"


def test_resolve_chat_model_admin_only() -> None:
    from apps.api.routers.agent import resolve_chat_model

    admin = Actor(tenant_id="t", role="admin")
    member = Actor(tenant_id="t", role="member")

    # admins pick freely; members are pinned to the default regardless
    assert resolve_chat_model(admin, "deepseek/deepseek-v4-pro") == "deepseek/deepseek-v4-pro"
    assert resolve_chat_model(admin, None) == settings.strong_model
    assert resolve_chat_model(member, "deepseek/deepseek-v4-pro") == settings.strong_model
    assert resolve_chat_model(member, None) == settings.strong_model
