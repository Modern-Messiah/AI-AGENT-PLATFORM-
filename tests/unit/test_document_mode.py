from apps.api.main import AgentStreamRequest, DocumentChunkPreview, app
from fastapi.routing import APIRoute


def test_document_chunks_route_is_registered() -> None:
    routes = {
        (route.path, method)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }

    assert ("/documents/{document_id}/chunks", "GET") in routes


def test_document_chunk_preview_schema() -> None:
    preview = DocumentChunkPreview(
        chunk_id="chunk-1",
        chunk_index=2,
        page=5,
        excerpt="Relevant document fragment.",
    )

    assert preview.page == 5
    assert preview.excerpt == "Relevant document fragment."


def test_agent_stream_request_accepts_document_scope() -> None:
    request = AgentStreamRequest(
        user_query="Что внутри документа?",
        document_id="5ef2d843-ddaf-4ae3-a73d-d25f27fb8621",
    )

    assert str(request.document_id) == "5ef2d843-ddaf-4ae3-a73d-d25f27fb8621"
