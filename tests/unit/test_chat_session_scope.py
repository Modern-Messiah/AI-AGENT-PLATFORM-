from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from apps.api.schemas import CreateSessionRequest
from apps.api.serializers import chat_session_response
from pydantic import ValidationError


def test_create_session_request_accepts_document_scope() -> None:
    request = CreateSessionRequest(
        title="Документ: manual.pdf",
        model="moonshot/kimi-k2.6",
        document_id="5ef2d843-ddaf-4ae3-a73d-d25f27fb8621",
    )

    assert str(request.document_id) == "5ef2d843-ddaf-4ae3-a73d-d25f27fb8621"
    assert request.notebook_id is None


def test_create_session_request_rejects_two_scopes() -> None:
    with pytest.raises(ValidationError):
        CreateSessionRequest(
            title="Mixed scope",
            document_id="5ef2d843-ddaf-4ae3-a73d-d25f27fb8621",
            notebook_id="318056a5-81b3-445c-bcb0-850b56fbce8f",
        )


def test_chat_session_response_includes_persisted_scope() -> None:
    now = datetime(2026, 6, 19, tzinfo=UTC)
    sess = SimpleNamespace(
        id=UUID("11111111-1111-4111-8111-111111111111"),
        title="Документ: manual.pdf",
        model="moonshot/kimi-k2.6",
        scope_type="document",
        document_id=UUID("5ef2d843-ddaf-4ae3-a73d-d25f27fb8621"),
        notebook_id=None,
        created_at=now,
        updated_at=now,
    )

    response = chat_session_response(sess, message_count=3)

    assert response.scope_type == "document"
    assert response.document_id == "5ef2d843-ddaf-4ae3-a73d-d25f27fb8621"
    assert response.notebook_id is None
    assert response.message_count == 3
