from apps.api.main import AgentStreamRequest, DocumentAssetResponse, DocumentChunkPreview, app
from fastapi.routing import APIRoute


def test_document_chunks_route_is_registered() -> None:
    routes = {
        (path, method.upper())
        for path, methods in app.openapi()["paths"].items()
        for method in methods
    }

    assert ("/documents/{document_id}/chunks", "GET") in routes
    assert ("/documents/{document_id}/assets", "GET") in routes
    assert ("/documents/{document_id}/assets/{asset_id}/content", "GET") in routes


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


def test_document_asset_response_exposes_safe_metadata_only() -> None:
    response = DocumentAssetResponse(
        id="asset-1",
        document_id="document-1",
        page_number=2,
        asset_kind="page",
        ocr_text="Recognized text",
        ocr_confidence=0.91,
        vision_description="A diagram of the deployment flow.",
        width=1200,
        height=1600,
        status="done",
        preview_available=True,
    )

    payload = response.model_dump()

    assert payload["preview_available"] is True
    assert "preview_object_key" not in payload
