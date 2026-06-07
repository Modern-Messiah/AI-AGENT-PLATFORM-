import pytest
from apps.api.main import AgentStreamRequest, CreateNotebookRequest, NotebookResponse, app
from fastapi.routing import APIRoute
from pydantic import ValidationError


def test_notebook_routes_are_registered() -> None:
    routes = {
        (route.path, method)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }

    assert ("/notebooks", "GET") in routes
    assert ("/notebooks", "POST") in routes
    assert ("/notebooks/{notebook_id}", "GET") in routes
    assert ("/notebooks/{notebook_id}", "DELETE") in routes
    assert ("/notebooks/{notebook_id}/documents", "PUT") in routes
    assert ("/notebooks/{notebook_id}/insights", "POST") in routes


def test_notebook_create_schema_accepts_document_ids() -> None:
    request = CreateNotebookRequest(
        title="Product research",
        description="Source set for one project.",
        document_ids=["5ef2d843-ddaf-4ae3-a73d-d25f27fb8621"],
    )

    assert request.title == "Product research"
    assert str(request.document_ids[0]) == "5ef2d843-ddaf-4ae3-a73d-d25f27fb8621"


def test_notebook_response_schema_includes_documents() -> None:
    response = NotebookResponse(
        id="notebook-1",
        tenant_id="tenant-a",
        title="Product research",
        description="Source set for one project.",
        document_ids=["document-1"],
        document_count=1,
        documents=[],
        summary="Combined source overview.",
        suggested_questions=["Что общее в источниках?"],
        key_topics=["Revenue", "Expansion"],
        insights_updated_at="2026-06-07T00:00:00+00:00",
        created_at="2026-06-07T00:00:00+00:00",
        updated_at="2026-06-07T00:00:00+00:00",
    )

    assert response.document_count == 1
    assert response.document_ids == ["document-1"]
    assert response.summary == "Combined source overview."
    assert response.suggested_questions == ["Что общее в источниках?"]
    assert response.key_topics == ["Revenue", "Expansion"]


def test_agent_stream_request_accepts_notebook_scope() -> None:
    request = AgentStreamRequest(
        user_query="Что общее в источниках?",
        notebook_id="318056a5-81b3-445c-bcb0-850b56fbce8f",
    )

    assert str(request.notebook_id) == "318056a5-81b3-445c-bcb0-850b56fbce8f"


def test_agent_stream_request_rejects_two_scopes() -> None:
    with pytest.raises(ValidationError):
        AgentStreamRequest(
            user_query="Что внутри?",
            document_id="5ef2d843-ddaf-4ae3-a73d-d25f27fb8621",
            notebook_id="318056a5-81b3-445c-bcb0-850b56fbce8f",
        )
