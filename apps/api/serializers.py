from __future__ import annotations

import re

from packages.rag import CitationSource
from packages.storage import ChatMessage, ChatSession, Document, DocumentAsset, Notebook

from apps.api.schemas import (
    ChatMessageSchema,
    ChatSessionSchema,
    DocumentAssetResponse,
    DocumentResponse,
    NotebookResponse,
)


def serialize_sources(
    sources: list[str | CitationSource],
) -> list[str | dict[str, object]]:
    return [
        source.model_dump(mode="json") if isinstance(source, CitationSource) else source
        for source in sources
    ]


def chat_session_response(sess: ChatSession, message_count: int = 0) -> ChatSessionSchema:
    return ChatSessionSchema(
        id=str(sess.id),
        title=sess.title,
        model=sess.model,
        created_at=sess.created_at.isoformat(),
        updated_at=sess.updated_at.isoformat(),
        message_count=message_count,
    )


def chat_message_response(msg: ChatMessage) -> ChatMessageSchema:
    return ChatMessageSchema(
        id=str(msg.id),
        role=msg.role,
        content=msg.content,
        sources=msg.sources or [],
        cached=msg.cached,
        created_at=msg.created_at.isoformat(),
    )


def document_response(doc: Document) -> DocumentResponse:
    return DocumentResponse(
        id=str(doc.id),
        tenant_id=doc.tenant_id,
        filename=doc.filename,
        status=doc.status,
        size_bytes=doc.size_bytes,
        source_type=getattr(doc, "source_type", "file") or "file",
        source_url=getattr(doc, "source_url", None),
        source_title=getattr(doc, "source_title", None),
        source_checked_at=(
            doc.source_checked_at.isoformat()
            if getattr(doc, "source_checked_at", None)
            else None
        ),
        summary=doc.summary,
        suggested_questions=doc.suggested_questions or [],
        processing_stage=doc.processing_stage,
        processed_pages=doc.processed_pages,
        total_pages=doc.total_pages,
        warnings=doc.warnings or [],
        error=doc.error,
        created_at=doc.created_at.isoformat() if doc.created_at else None,
    )


def document_asset_response(asset: DocumentAsset) -> DocumentAssetResponse:
    return DocumentAssetResponse(
        id=str(asset.id),
        document_id=str(asset.document_id),
        page_number=asset.page_number,
        asset_kind=asset.asset_kind,
        ocr_text=asset.ocr_text,
        ocr_confidence=asset.ocr_confidence,
        vision_description=asset.vision_description,
        width=asset.width,
        height=asset.height,
        status=asset.status,
        error=asset.error,
        preview_available=bool(asset.preview_object_key),
    )


def notebook_response(
    notebook: Notebook,
    documents: list[Document] | None = None,
) -> NotebookResponse:
    docs = documents or []
    return NotebookResponse(
        id=str(notebook.id),
        tenant_id=notebook.tenant_id,
        title=notebook.title,
        description=notebook.description,
        document_ids=[str(doc.id) for doc in docs],
        document_count=len(docs),
        documents=[document_response(doc) for doc in docs],
        summary=notebook.summary,
        suggested_questions=notebook.suggested_questions or [],
        key_topics=notebook.key_topics or [],
        insights_updated_at=(
            notebook.insights_updated_at.isoformat()
            if notebook.insights_updated_at
            else None
        ),
        created_at=notebook.created_at.isoformat() if notebook.created_at else None,
        updated_at=notebook.updated_at.isoformat() if notebook.updated_at else None,
    )


def metadata_page(metadata: dict[str, object]) -> int | None:
    page = metadata.get("page")
    if isinstance(page, bool) or page is None:
        return None
    try:
        parsed = int(page)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def chunk_excerpt(content: str, max_chars: int = 520) -> str:
    excerpt = re.sub(r"\s+", " ", content).strip()
    if len(excerpt) <= max_chars:
        return excerpt
    return f"{excerpt[:max_chars].rstrip()}…"
