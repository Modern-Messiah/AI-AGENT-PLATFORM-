import json

import pytest
from apps.api.main import (
    AddMessageRequest,
    AgentRunApiResponse,
    ChatMessageSchema,
    _serialize_sources,
)
from packages.agents import AgentRunInput, AgentRunOutput
from packages.rag.citations import CitationSource
from pydantic import ValidationError


def test_agent_input_requires_query() -> None:
    with pytest.raises(ValidationError):
        AgentRunInput()  # user_query has no default


def test_agent_output_clamps_confidence() -> None:
    with pytest.raises(ValidationError):
        AgentRunOutput(answer="x", confidence=1.5)


def test_agent_output_accepts_structured_and_legacy_sources() -> None:
    citation = CitationSource(
        id=1,
        document_id="document-1",
        chunk_id="chunk-1",
        filename="guide.pdf",
        page=3,
        chunk_index=4,
        excerpt="Grounded evidence.",
        score=0.9,
    )

    output = AgentRunOutput(
        answer="Grounded answer [1]",
        confidence=0.9,
        sources=["legacy.txt", citation],
    )

    assert output.sources[0] == "legacy.txt"
    assert output.sources[1] == citation


def test_chat_api_schemas_accept_serialized_citations() -> None:
    citation = {
        "id": 1,
        "document_id": "document-1",
        "chunk_id": "chunk-1",
        "filename": "guide.pdf",
        "page": 3,
        "chunk_index": 4,
        "excerpt": "Grounded evidence.",
        "score": 0.9,
    }

    add_request = AddMessageRequest(
        role="agent",
        content="Grounded answer [1]",
        sources=[citation],
    )
    chat_message = ChatMessageSchema(
        id="message-1",
        role="agent",
        content="Grounded answer [1]",
        sources=[citation],
        created_at="2026-06-07T00:00:00+00:00",
    )
    api_response = AgentRunApiResponse(
        answer="Grounded answer [1]",
        confidence=0.9,
        sources=[citation],
    )

    assert isinstance(add_request.sources[0], CitationSource)
    assert isinstance(chat_message.sources[0], CitationSource)
    assert isinstance(api_response.sources[0], CitationSource)
    assert add_request.sources[0].page == 3
    assert chat_message.sources[0].filename == "guide.pdf"
    assert api_response.sources[0].chunk_id == "chunk-1"
    assert json.loads(json.dumps(_serialize_sources(add_request.sources))) == [citation]


def test_document_response_accepts_insights() -> None:
    from apps.api.main import DocumentResponse
    from packages.storage import DocumentStatus

    response = DocumentResponse(
        id="document-1",
        tenant_id="tenant-a",
        filename="guide.pdf",
        status=DocumentStatus.done,
        summary="Short document summary.",
        suggested_questions=["Что внутри guide.pdf?"],
    )

    assert response.summary == "Short document summary."
    assert response.suggested_questions == ["Что внутри guide.pdf?"]
