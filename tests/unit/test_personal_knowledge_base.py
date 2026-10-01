"""Per-user knowledge base: ownership, access scoping, private sessions.

Covers the personal-KB contract: uploads are private by default and stamped
with the acting user, lists respect ?scope=, foreign private documents are
invisible (404) and unmanageable, unscoped agent chat never retrieves beyond
the user's accessible corpus, chat history is per-user, and semantic-cache
keys are user-scoped.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
from apps.api.routers import agent as agent_router
from apps.api.routers import documents as documents_router
from apps.api.routers import sessions as sessions_router
from apps.api.schemas import AgentStreamRequest, CreateSessionRequest
from apps.api.services.access import can_access, can_manage, scope_condition
from packages.auth import Actor
from packages.storage import Document, DocumentStatus, Notebook


def _user(name: str = "alice") -> Actor:
    return Actor(tenant_id="tenant-a", role="member", user_id=uuid.uuid4(), user_name=name)


def _other_user() -> Actor:
    return Actor(tenant_id="tenant-a", role="member", user_id=uuid.uuid4(), user_name="bob")


def _unbound_key() -> Actor:
    return Actor(tenant_id="tenant-a", role=None)


# ── access rules ─────────────────────────────────────────────────────────────


def _doc(owner: uuid.UUID | None, *, shared: bool = False) -> Document:
    from datetime import UTC, datetime

    return Document(
        id=uuid.uuid4(),
        tenant_id="tenant-a",
        owner_user_id=owner,
        is_shared=shared,
        filename="doc.pdf",
        mime_type="application/pdf",
        object_key="tenant-a/doc.pdf",
        size_bytes=128,
        summary=None,
        suggested_questions=[],
        processing_stage="done",
        processed_pages=1,
        total_pages=1,
        warnings=[],
        status=DocumentStatus.done,
        error=None,
        created_at=datetime.now(UTC),
    )


def test_private_document_is_visible_only_to_owner() -> None:
    owner = _user()
    doc = _doc(owner.user_id)
    assert can_access(owner, doc) is True
    assert can_access(_other_user(), doc) is False
    assert can_access(_unbound_key(), doc) is True


def test_shared_document_is_visible_to_everyone_in_tenant() -> None:
    doc = _doc(_user().user_id, shared=True)
    assert can_access(_other_user(), doc) is True


def test_legacy_document_backfilled_shared_stays_shared() -> None:
    # Migration 0029 backfills owner-NULL rows to is_shared=true; the flag
    # alone decides sharing from now on.
    doc = _doc(None, shared=True)
    assert can_access(_other_user(), doc) is True


def test_orphaned_private_document_is_invisible() -> None:
    # owner FK nulled by user deletion must NOT publish the document.
    doc = _doc(None, shared=False)
    assert can_access(_other_user(), doc) is False
    assert can_access(_unbound_key(), doc) is True


def test_can_manage_owner_admin_and_unbound_but_not_others() -> None:
    owner = _user()
    doc = _doc(owner.user_id)
    assert can_manage(owner, doc) is True
    assert can_manage(_unbound_key(), doc) is True
    assert can_manage(Actor("tenant-a", "admin", user_id=uuid.uuid4()), doc) is True
    assert can_manage(_other_user(), doc) is False


def test_scope_condition_mine_for_unbound_key_matches_nothing() -> None:
    condition = scope_condition(Document, _unbound_key(), "mine")
    assert condition is not None
    assert str(condition) == "false"


def test_scope_condition_all_adds_owner_or_clause_for_user() -> None:
    condition = scope_condition(Document, _user(), "all")
    assert condition is not None
    sql = str(condition)
    assert "owner_user_id" in sql
    assert "is_shared" in sql


def test_scope_condition_all_is_none_for_unbound_key() -> None:
    assert scope_condition(Document, _unbound_key(), "all") is None


# ── /documents listing and 404s ──────────────────────────────────────────────


class _Result:
    def __init__(self, values=None, *, rows=None) -> None:
        self.values = list(values or [])
        self.rows = list(rows or [])

    def scalars(self):
        return self

    def all(self):
        return self.rows if self.rows else self.values

    def scalar_one_or_none(self):
        return self.values[0] if self.values else None


class _FakeSession:
    def __init__(self, results) -> None:
        self.results = list(results)
        self.statements = []
        self.deleted: list[object] = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self.results.pop(0)

    async def flush(self) -> None:
        return None

    async def delete(self, row) -> None:
        self.deleted.append(row)


class _FakeTenantSession:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> _FakeSession:
        return self.session

    async def __aexit__(self, *args: object) -> None:
        return None


def _patch_tenant_session(monkeypatch, module, session: _FakeSession) -> None:
    monkeypatch.setattr(module, "tenant_session", lambda tenant_id: _FakeTenantSession(session))


async def test_list_documents_user_scope_filters_by_ownership(monkeypatch) -> None:
    session = _FakeSession([_Result([])])
    _patch_tenant_session(monkeypatch, documents_router, session)

    rows = await documents_router.list_documents(_user(), scope="mine", limit=10, offset=0)

    assert rows == []
    assert "owner_user_id" in str(session.statements[0])


async def test_get_document_hides_foreign_private_document(monkeypatch) -> None:
    doc = _doc(_other_user().user_id)
    session = _FakeSession([_Result([doc])])
    _patch_tenant_session(monkeypatch, documents_router, session)

    with pytest.raises(Exception) as exc:
        await documents_router.get_document(doc.id, _user())

    assert exc.value.status_code == 404


async def test_delete_document_owner_member_allowed(monkeypatch) -> None:
    owner = _user()
    doc = _doc(owner.user_id)
    session = _FakeSession([_Result([doc]), _Result([])])  # document row, then asset keys
    _patch_tenant_session(monkeypatch, documents_router, session)
    monkeypatch.setattr(
        documents_router,
        "invalidate_semantic_cache",
        lambda *a, **k: _noop(),
    )
    monkeypatch.setattr(documents_router.object_store, "delete", lambda key: None)

    await documents_router.delete_document(doc.id, owner)
    assert session.deleted == [doc]


async def _noop() -> None:
    return None


async def test_delete_document_foreign_private_hidden(monkeypatch) -> None:
    # A foreign private document is reported as missing — existence is
    # private too.
    doc = _doc(_other_user().user_id)
    session = _FakeSession([_Result([doc])])
    _patch_tenant_session(monkeypatch, documents_router, session)

    with pytest.raises(Exception) as exc:
        await documents_router.delete_document(doc.id, _user())

    assert exc.value.status_code == 404


async def test_delete_document_shared_denied_for_member(monkeypatch) -> None:
    # Tenant-shared documents stay admin/unbound-only to destroy, same
    # contract as require_destroy_permission before personal bases.
    doc = _doc(None, shared=True)
    session = _FakeSession([_Result([doc])])
    _patch_tenant_session(monkeypatch, documents_router, session)

    with pytest.raises(Exception) as exc:
        await documents_router.delete_document(doc.id, _user())

    assert exc.value.status_code == 403


# ── notebooks ────────────────────────────────────────────────────────────────


def test_notebook_access_follows_same_rules() -> None:
    owner = _user()
    notebook = Notebook(
        id=uuid.uuid4(), tenant_id="tenant-a", owner_user_id=owner.user_id, title="My base"
    )
    assert can_access(owner, notebook) is True
    assert can_access(_other_user(), notebook) is False
    assert can_manage(_other_user(), notebook) is False


async def test_shared_notebook_rejects_private_documents(monkeypatch) -> None:
    """Stored notebook insights are visible to everyone who can open the
    notebook — deriving them from a private document would leak content."""
    from apps.api.routers import notebooks as notebooks_router
    from apps.api.schemas import CreateNotebookRequest

    owner = _user()
    private_doc = _doc(owner.user_id)  # is_shared=False
    session = _FakeSession([_Result([private_doc])])
    monkeypatch.setattr(notebooks_router, "tenant_session", lambda tid: _FakeTenantSession(session))

    with pytest.raises(Exception) as exc:
        await notebooks_router.create_notebook(
            CreateNotebookRequest(
                title="Общий ноутбук", document_ids=[private_doc.id], shared=True
            ),
            owner,
        )

    assert exc.value.status_code == 400
    assert "private" in exc.value.detail


# ── agent chat scoping ───────────────────────────────────────────────────────


class _ScalarsSession:
    def __init__(self, scalars_value: list[object]) -> None:
        self.scalars_value = scalars_value

    async def __aenter__(self) -> _ScalarsSession:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def begin(self) -> _ScalarsSession:
        return self

    async def execute(self, statement: object) -> _Result:
        return _Result(self.scalars_value)


async def test_agent_stream_without_accessible_documents_answers_without_retrieval(
    monkeypatch,
) -> None:
    async def fake_limits(tenant_id: str, query: str, endpoint: str) -> str:
        return query

    logged: list[object] = []

    async def fake_log(entry) -> None:
        logged.append(entry)

    monkeypatch.setattr(agent_router, "enforce_agent_limits", fake_limits)
    monkeypatch.setattr(agent_router, "log_agent_query", fake_log)
    monkeypatch.setattr(agent_router, "tenant_session", lambda tid: _ScalarsSession([]))

    async def fail_retrieval(*args, **kwargs):
        raise AssertionError("retrieval must not run when the user has no accessible documents")

    monkeypatch.setattr(agent_router, "retrieve_chunks_with_expansion", fail_retrieval)

    response = await agent_router.agent_stream(AgentStreamRequest(user_query="вопрос"), _user())
    body = "".join([chunk async for chunk in response.body_iterator])

    # The refusal is answered immediately: no retrieval stage, one log entry.
    assert '"stage": "retrieval"' not in body
    assert '"type": "done"' in body
    assert len(logged) == 1


async def test_agent_research_without_accessible_documents_short_circuits(
    monkeypatch,
) -> None:
    """Regression: research used to fall through to an unscoped tenant
    search when the user had zero accessible documents (empty
    document_ids means "no filter" in the retriever)."""
    from packages.agents.schemas import MultiStepResearchInput

    async def fake_limits(tenant_id: str, query: str, endpoint: str) -> str:
        return query

    async def fake_validate(query: str) -> str:
        return query

    logged: list[object] = []

    async def fake_log(entry) -> None:
        logged.append(entry)

    def fail_workflow(*args, **kwargs):
        raise AssertionError("research must not start workflows over an empty corpus")

    monkeypatch.setattr(agent_router, "enforce_agent_limits", fake_limits)
    monkeypatch.setattr(agent_router, "validate_agent_query", fake_validate)
    monkeypatch.setattr(agent_router, "log_agent_query", fake_log)
    monkeypatch.setattr(agent_router, "tenant_session", lambda tid: _ScalarsSession([]))
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(temporal=SimpleNamespace(execute_workflow=fail_workflow))
        )
    )

    response = await agent_router.run_research(
        MultiStepResearchInput(main_query="вопрос", sub_queries=["подвопрос"]),
        _user(),
        request,
    )

    assert "нет доступных проиндексированных документов" in response.answer
    assert len(logged) == 1


async def test_agent_stream_scoped_to_foreign_private_document_returns_404(monkeypatch) -> None:
    async def fake_limits(tenant_id: str, query: str, endpoint: str) -> str:
        return query

    monkeypatch.setattr(agent_router, "enforce_agent_limits", fake_limits)
    doc = _doc(_other_user().user_id)
    session = _FakeSession([_Result([doc])])
    _patch_tenant_session(monkeypatch, agent_router, session)

    with pytest.raises(Exception) as exc:
        await agent_router.agent_stream(
            AgentStreamRequest(user_query="вопрос", document_id=doc.id), _user()
        )

    assert exc.value.status_code == 404


def test_semantic_cache_keys_are_user_scoped() -> None:
    from packages.cache.semantic import SemanticCache

    cache = SemanticCache()
    assert cache._idx_key("tenant-a", "user:bob") == "scache:tenant-a:user:bob:idx"
    assert cache._idx_key("tenant-a", "tenant") == "scache:tenant-a:tenant:idx"
    assert cache._entry_key("tenant-a", "user:bob", "e1") == "scache:tenant-a:user:bob:e1"


def test_document_response_carries_ownership_fields() -> None:
    from apps.api.serializers import document_response

    owner = uuid.uuid4()
    doc = _doc(owner)
    payload = json.loads(document_response(doc).model_dump_json())
    assert payload["owner_user_id"] == str(owner)
    assert payload["is_shared"] is False


# ── sessions ─────────────────────────────────────────────────────────────────


async def test_create_session_stamps_user_and_list_filters_by_user(monkeypatch) -> None:
    from datetime import UTC, datetime

    user = _user()
    created: list[object] = []

    class _CreateSession(_FakeSession):
        def add(self, row) -> None:
            created.append(row)

        async def flush(self) -> None:
            return None

        async def refresh(self, row) -> None:
            row.created_at = datetime.now(UTC)
            row.updated_at = datetime.now(UTC)

    session = _CreateSession([])
    _patch_tenant_session(monkeypatch, sessions_router, session)

    await sessions_router.create_session(CreateSessionRequest(title="Личное"), user)
    assert created[0].user_id == user.user_id

    list_session = _FakeSession([_Result(rows=[])])
    _patch_tenant_session(monkeypatch, sessions_router, list_session)
    await sessions_router.list_sessions(_other_user(), limit=10, offset=0)
    assert "user_id" in str(list_session.statements[0])


async def test_session_of_another_user_is_invisible(monkeypatch) -> None:
    owner = _user()
    sess = SimpleNamespace(id=uuid.uuid4(), user_id=owner.user_id)
    session = _FakeSession([_Result([sess]), _Result([])])
    _patch_tenant_session(monkeypatch, sessions_router, session)

    with pytest.raises(Exception) as exc:
        await sessions_router.get_messages(sess.id, _other_user())

    assert exc.value.status_code == 404


# ── share toggle (PATCH /documents/{id}/share) ───────────────────────────────


async def test_owner_can_share_and_unshare_document(monkeypatch) -> None:
    owner = _user()
    doc = _doc(owner.user_id)
    invalidated: list[str] = []

    def fake_invalidate(tenant_id: str, reason: str):
        invalidated.append(reason)

        async def _noop_coro() -> None:
            return None

        return _noop_coro()

    session = _FakeSession([_Result([doc])])
    _patch_tenant_session(monkeypatch, documents_router, session)
    monkeypatch.setattr(documents_router, "invalidate_semantic_cache", fake_invalidate)

    response = await documents_router.set_document_shared(
        doc.id, documents_router.DocumentShareRequest(shared=True), owner
    )

    assert response.is_shared is True
    assert doc.is_shared is True
    assert invalidated == [f"document-share:{doc.id}"]


async def test_member_cannot_share_foreign_document(monkeypatch) -> None:
    doc = _doc(_other_user().user_id, shared=True)  # visible, not manageable
    session = _FakeSession([_Result([doc])])
    _patch_tenant_session(monkeypatch, documents_router, session)

    with pytest.raises(Exception) as exc:
        await documents_router.set_document_shared(
            doc.id, documents_router.DocumentShareRequest(shared=False), _user()
        )

    assert exc.value.status_code == 403


async def test_unshare_blocked_while_in_shared_notebook(monkeypatch) -> None:
    owner = _user()
    doc = _doc(owner.user_id, shared=True)
    # First execute resolves the document, second — shared notebook titles.
    session = _FakeSession([_Result([doc]), _Result(["Общий сборник"])])
    _patch_tenant_session(monkeypatch, documents_router, session)

    with pytest.raises(Exception) as exc:
        await documents_router.set_document_shared(
            doc.id, documents_router.DocumentShareRequest(shared=False), owner
        )

    assert exc.value.status_code == 409
    assert "Общий сборник" in exc.value.detail
