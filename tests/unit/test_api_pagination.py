from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

from apps.api.routers import documents as documents_router
from apps.api.routers import notebooks as notebooks_router
from apps.api.routers import sessions as sessions_router


class _Result:
    def __init__(self, values=None, *, rows=None) -> None:
        self.values = list(values or [])
        self.rows = list(rows or [])

    def scalars(self):
        return self

    def all(self):
        return self.rows if self.rows else self.values


class _FakeSession:
    def __init__(self, results) -> None:
        self.results = list(results)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self.results.pop(0)


class _FakeTenantSession:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> _FakeSession:
        return self.session

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


def _patch_tenant_session(monkeypatch, module, session: _FakeSession) -> None:
    monkeypatch.setattr(module, "tenant_session", lambda tenant_id: _FakeTenantSession(session))


def _notebook(notebook_id: str) -> SimpleNamespace:
    now = datetime(2026, 6, 17, tzinfo=UTC)
    return SimpleNamespace(
        id=UUID(notebook_id),
        tenant_id="tenant-a",
        title="Notebook",
        description=None,
        summary=None,
        suggested_questions=[],
        key_topics=[],
        insights_updated_at=None,
        created_at=now,
        updated_at=now,
    )


async def test_list_documents_applies_limit_and_offset(monkeypatch) -> None:
    session = _FakeSession([_Result([])])
    _patch_tenant_session(monkeypatch, documents_router, session)

    rows = await documents_router.list_documents("tenant-a", limit=7, offset=14)

    assert rows == []
    statement = str(session.statements[0])
    assert "LIMIT" in statement
    assert "OFFSET" in statement


async def test_list_sessions_applies_limit_and_offset(monkeypatch) -> None:
    session = _FakeSession([_Result(rows=[])])
    _patch_tenant_session(monkeypatch, sessions_router, session)

    rows = await sessions_router.list_sessions("tenant-a", limit=9, offset=18)

    assert rows == []
    statement = str(session.statements[0])
    assert "LIMIT" in statement
    assert "OFFSET" in statement


async def test_list_notebooks_batches_document_loading_in_two_queries(monkeypatch) -> None:
    session = _FakeSession([
        _Result([
            _notebook("5ef2d843-ddaf-4ae3-a73d-d25f27fb8621"),
            _notebook("318056a5-81b3-445c-bcb0-850b56fbce8f"),
        ]),
        _Result(rows=[]),
    ])
    _patch_tenant_session(monkeypatch, notebooks_router, session)

    rows = await notebooks_router.list_notebooks("tenant-a", limit=50, offset=0)

    assert len(rows) == 2
    assert len(session.statements) == 2
    assert "LIMIT" in str(session.statements[0])
    assert "OFFSET" in str(session.statements[0])
