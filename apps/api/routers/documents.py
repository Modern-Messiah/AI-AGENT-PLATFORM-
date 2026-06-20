from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from packages.core import settings
from packages.storage import Chunk, Document, DocumentAsset, DocumentStatus, object_store
from packages.storage.db import tenant_session
from sqlalchemy import select, update
from starlette.responses import Response
from temporalio.client import Client

from apps.api.deps import TenantID, read_with_limit
from apps.api.schemas import (
    AddUrlDocumentRequest,
    DocumentAssetResponse,
    DocumentChunkPreview,
    DocumentResponse,
    UrlCheckRequest,
    UrlCheckResponse,
)
from apps.api.serializers import (
    chunk_excerpt,
    document_asset_response,
    document_response,
    metadata_page,
)
from apps.api.services.cache import invalidate_semantic_cache
from apps.api.services.url_sources import (
    FetchedUrlSource,
    UrlSourceError,
    fetch_url_source,
    url_image_sidecar_key,
    url_image_sidecar_payload,
)
from apps.worker.activities.ingestion import IngestionInput
from apps.worker.workflows.ingestion import IngestionWorkflow

log = logging.getLogger(__name__)
router = APIRouter()


def _store_url_source_objects(object_key: str, fetched: FetchedUrlSource) -> None:
    object_store.put(object_key, fetched.data, content_type=fetched.content_type)
    object_store.put(
        url_image_sidecar_key(object_key),
        url_image_sidecar_payload(fetched.image_sources),
        content_type="application/json",
    )


@router.get("/documents", response_model=list[DocumentResponse])
async def list_documents(
    tenant_id: TenantID,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[DocumentResponse]:
    async with tenant_session(tenant_id) as s:
        rows = (await s.execute(
            select(Document)
            .where(Document.tenant_id == tenant_id)
            .order_by(Document.created_at.desc())
            .limit(limit)
            .offset(offset)
        )).scalars().all()
    return [document_response(doc) for doc in rows]


@router.post("/documents", response_model=DocumentResponse, status_code=202)
async def upload_document(
    request: Request,
    tenant_id: TenantID,
    file: UploadFile = File(...),
) -> DocumentResponse:
    # Early rejection before reading body (Content-Length may include multipart overhead,
    # so use a 2x guard here; exact byte-level check happens inside read_with_limit).
    cl = request.headers.get("content-length")
    if cl and int(cl) > settings.max_upload_bytes * 2:
        raise HTTPException(status_code=413, detail=f"file exceeds {settings.max_upload_bytes // (1024 * 1024)} MB limit")

    data = await read_with_limit(file, settings.max_upload_bytes)
    if not data:
        raise HTTPException(status_code=400, detail="empty file")

    document_id = uuid.uuid4()
    object_key = f"{tenant_id}/{document_id}/{file.filename}"
    object_store.put(object_key, data, content_type=file.content_type or "application/octet-stream")

    async with tenant_session(tenant_id) as s:
        s.add(Document(
            id=document_id,
            tenant_id=tenant_id,
            filename=file.filename or "unnamed",
            mime_type=file.content_type or "application/octet-stream",
            object_key=object_key,
            size_bytes=len(data),
            status=DocumentStatus.pending,
        ))

    await invalidate_semantic_cache(tenant_id, f"document-upload:{document_id}")

    client: Client = request.app.state.temporal
    try:
        await client.start_workflow(
            IngestionWorkflow.run,
            IngestionInput(
                document_id=str(document_id),
                tenant_id=tenant_id,
                object_key=object_key,
                filename=file.filename or "unnamed",
            ),
            id=f"ingest-{tenant_id}-{document_id}",
            task_queue=settings.temporal_task_queue,
        )
    except Exception as e:
        async with tenant_session(tenant_id) as s:
            await s.execute(
                update(Document)
                .where(Document.id == document_id)
                .values(status=DocumentStatus.failed, error="Failed to start ingestion workflow")
            )
        raise HTTPException(status_code=503, detail="ingestion service unavailable") from e

    async with tenant_session(tenant_id) as s:
        doc = (await s.execute(select(Document).where(Document.id == document_id))).scalar_one()
    return document_response(doc)


@router.post("/documents/bulk", response_model=list[DocumentResponse], status_code=202)
async def upload_documents_bulk(
    request: Request,
    tenant_id: TenantID,
    files: list[UploadFile] = File(...),
) -> list[DocumentResponse]:
    """Upload multiple documents at once. Each gets its own IngestionWorkflow."""
    if not files:
        raise HTTPException(status_code=400, detail="no files provided")
    if len(files) > 20:
        raise HTTPException(status_code=400, detail="max 20 files per bulk upload")

    # Phase 1: read and validate ALL files before starting any workflow.
    # This prevents partial state where some workflows fire but a later file fails validation.
    cl = request.headers.get("content-length")
    if cl and int(cl) > settings.max_upload_bytes * len(files) * 2:
        raise HTTPException(status_code=413, detail="request body too large")

    validated: list[tuple[UploadFile, bytes]] = []
    total_bytes = 0
    for file in files:
        try:
            data = await read_with_limit(file, settings.max_upload_bytes)
        except HTTPException as exc:
            raise HTTPException(
                status_code=413,
                detail=f"{file.filename}: {exc.detail}",
            ) from exc
        if not data:
            continue
        total_bytes += len(data)
        if total_bytes > settings.max_bulk_total_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"total bulk upload exceeds {settings.max_bulk_total_bytes // (1024 * 1024)} MB limit",
            )
        validated.append((file, data))

    if not validated:
        raise HTTPException(status_code=400, detail="no non-empty files provided")

    # Phase 2: store objects + DB rows + start workflows only after full validation.
    client: Client = request.app.state.temporal
    responses: list[DocumentResponse] = []

    for file, data in validated:
        document_id = uuid.uuid4()
        object_key = f"{tenant_id}/{document_id}/{file.filename}"
        object_store.put(
            object_key, data,
            content_type=file.content_type or "application/octet-stream",
        )
        async with tenant_session(tenant_id) as s:
            s.add(Document(
                id=document_id,
                tenant_id=tenant_id,
                filename=file.filename or "unnamed",
                mime_type=file.content_type or "application/octet-stream",
                object_key=object_key,
                size_bytes=len(data),
                status=DocumentStatus.pending,
            ))
        await invalidate_semantic_cache(tenant_id, f"document-upload:{document_id}")
        try:
            await client.start_workflow(
                IngestionWorkflow.run,
                IngestionInput(
                    document_id=str(document_id),
                    tenant_id=tenant_id,
                    object_key=object_key,
                    filename=file.filename or "unnamed",
                ),
                id=f"ingest-{tenant_id}-{document_id}",
                task_queue=settings.temporal_task_queue,
            )
        except Exception:
            async with tenant_session(tenant_id) as s:
                await s.execute(
                    update(Document)
                    .where(Document.id == document_id)
                    .values(status=DocumentStatus.failed, error="Failed to start ingestion workflow")
                )
        async with tenant_session(tenant_id) as s:
            doc = (await s.execute(select(Document).where(Document.id == document_id))).scalar_one()
        responses.append(document_response(doc))

    return responses


@router.post("/documents/url/check", response_model=UrlCheckResponse)
async def check_url_document(body: UrlCheckRequest, tenant_id: TenantID) -> UrlCheckResponse:
    try:
        fetched = await fetch_url_source(body.url)
    except UrlSourceError as exc:
        return UrlCheckResponse(
            ok=False,
            url=body.url,
            reason=exc.message,
        )
    return UrlCheckResponse(
        ok=True,
        url=fetched.requested_url,
        final_url=fetched.final_url,
        content_type=fetched.content_type,
        title=fetched.title,
        size_bytes=fetched.size_bytes,
        source_type=fetched.source_type,
        file_count=fetched.file_count,
        image_count=len(fetched.image_sources),
        preview_files=fetched.discovered_files[:8],
    )


@router.post("/documents/url", response_model=DocumentResponse, status_code=202)
async def add_url_document(
    body: AddUrlDocumentRequest,
    request: Request,
    tenant_id: TenantID,
) -> DocumentResponse:
    try:
        fetched = await fetch_url_source(body.url)
    except UrlSourceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    document_id = uuid.uuid4()
    object_key = f"{tenant_id}/{document_id}/{fetched.filename}"
    _store_url_source_objects(object_key, fetched)
    checked_at = datetime.now(timezone.utc)

    async with tenant_session(tenant_id) as s:
        s.add(Document(
            id=document_id,
            tenant_id=tenant_id,
            filename=fetched.filename,
            mime_type=fetched.content_type,
            object_key=object_key,
            size_bytes=fetched.size_bytes,
            source_type=fetched.source_type,
            source_url=fetched.final_url,
            source_title=fetched.title,
            source_checked_at=checked_at,
            status=DocumentStatus.pending,
            processing_stage="queued",
            processed_pages=0,
            total_pages=0,
            warnings=[],
        ))

    await invalidate_semantic_cache(tenant_id, f"document-url:{document_id}")

    client: Client = request.app.state.temporal
    try:
        await client.start_workflow(
            IngestionWorkflow.run,
            IngestionInput(
                document_id=str(document_id),
                tenant_id=tenant_id,
                object_key=object_key,
                filename=fetched.filename,
            ),
            id=f"ingest-{tenant_id}-{document_id}",
            task_queue=settings.temporal_task_queue,
        )
    except Exception as e:
        async with tenant_session(tenant_id) as s:
            await s.execute(
                update(Document)
                .where(Document.id == document_id)
                .values(status=DocumentStatus.failed, error="Failed to start ingestion workflow")
            )
        raise HTTPException(status_code=503, detail="ingestion service unavailable") from e

    async with tenant_session(tenant_id) as s:
        doc = (await s.execute(select(Document).where(Document.id == document_id))).scalar_one()
    return document_response(doc)


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(document_id: uuid.UUID, tenant_id: TenantID) -> DocumentResponse:
    async with tenant_session(tenant_id) as s:
        doc = (
            await s.execute(
                select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    return document_response(doc)


@router.get("/documents/{document_id}/assets", response_model=list[DocumentAssetResponse])
async def list_document_assets(
    document_id: uuid.UUID,
    tenant_id: TenantID,
) -> list[DocumentAssetResponse]:
    async with tenant_session(tenant_id) as s:
        doc = (
            await s.execute(
                select(Document).where(
                    Document.id == document_id,
                    Document.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if doc is None:
            raise HTTPException(status_code=404, detail="document not found")
        assets = (
            await s.execute(
                select(DocumentAsset)
                .where(
                    DocumentAsset.document_id == document_id,
                    DocumentAsset.tenant_id == tenant_id,
                )
                .order_by(DocumentAsset.page_number, DocumentAsset.created_at)
            )
        ).scalars().all()
    return [document_asset_response(asset) for asset in assets]


@router.get("/documents/{document_id}/assets/{asset_id}/content")
async def get_document_asset_content(
    document_id: uuid.UUID,
    asset_id: uuid.UUID,
    tenant_id: TenantID,
) -> Response:
    async with tenant_session(tenant_id) as s:
        asset = (
            await s.execute(
                select(DocumentAsset).where(
                    DocumentAsset.id == asset_id,
                    DocumentAsset.document_id == document_id,
                    DocumentAsset.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
    if (
        asset is None
        or not asset.preview_object_key
        or getattr(asset, "asset_kind", "") == "url_image"
    ):
        raise HTTPException(status_code=404, detail="document asset not found")

    try:
        content = await asyncio.to_thread(object_store.get, asset.preview_object_key)
    except Exception as exc:
        log.warning(
            "asset preview read failed | tenant=%s document=%s asset=%s error=%s",
            tenant_id,
            document_id,
            asset_id,
            exc,
        )
        raise HTTPException(status_code=404, detail="document asset content not found") from exc

    return Response(
        content=content,
        media_type="image/webp",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/documents/{document_id}/chunks", response_model=list[DocumentChunkPreview])
async def list_document_chunks(
    document_id: uuid.UUID,
    tenant_id: TenantID,
    limit: int = Query(default=25, ge=1, le=100),
) -> list[DocumentChunkPreview]:
    async with tenant_session(tenant_id) as s:
        doc = (
            await s.execute(
                select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if doc is None:
            raise HTTPException(status_code=404, detail="document not found")
        chunks = (
            await s.execute(
                select(Chunk)
                .where(Chunk.document_id == document_id, Chunk.tenant_id == tenant_id)
                .order_by(Chunk.chunk_idx)
                .limit(limit)
            )
        ).scalars().all()

    return [
        DocumentChunkPreview(
            chunk_id=str(chunk.id),
            chunk_index=chunk.chunk_idx,
            page=metadata_page(chunk.chunk_metadata or {}),
            excerpt=chunk_excerpt(chunk.content),
        )
        for chunk in chunks
    ]


@router.post("/documents/{document_id}/reindex", response_model=DocumentResponse, status_code=202)
async def reindex_document(
    document_id: uuid.UUID,
    tenant_id: TenantID,
    request: Request,
) -> DocumentResponse:
    async with tenant_session(tenant_id) as s:
        doc = (
            await s.execute(
                select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if doc is None:
            raise HTTPException(status_code=404, detail="document not found")
        if doc.status in {DocumentStatus.pending, DocumentStatus.processing}:
            raise HTTPException(status_code=409, detail="document is already being indexed")

        if getattr(doc, "source_type", "file") in {"url", "github"}:
            if not doc.source_url:
                raise HTTPException(status_code=409, detail="external document has no source URL")
            try:
                fetched = await fetch_url_source(doc.source_url)
            except UrlSourceError as exc:
                raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

            _store_url_source_objects(doc.object_key, fetched)
            doc.filename = fetched.filename
            doc.mime_type = fetched.content_type
            doc.size_bytes = fetched.size_bytes
            doc.source_type = fetched.source_type
            doc.source_url = fetched.final_url
            doc.source_title = fetched.title
            doc.source_checked_at = datetime.now(timezone.utc)

        doc.status = DocumentStatus.pending
        doc.processing_stage = "queued"
        doc.processed_pages = 0
        doc.total_pages = 0
        doc.warnings = []
        doc.error = None
        await s.flush()
        response = document_response(doc)
        ingestion_input = IngestionInput(
            document_id=str(document_id),
            tenant_id=tenant_id,
            object_key=doc.object_key,
            filename=doc.filename,
        )

    await invalidate_semantic_cache(tenant_id, f"document-reindex:{document_id}")

    client: Client = request.app.state.temporal
    try:
        await client.start_workflow(
            IngestionWorkflow.run,
            ingestion_input,
            id=f"reindex-{tenant_id}-{document_id}-{uuid.uuid4()}",
            task_queue=settings.temporal_task_queue,
        )
    except Exception as e:
        async with tenant_session(tenant_id) as s:
            await s.execute(
                update(Document)
                .where(Document.id == document_id)
                .values(status=DocumentStatus.failed, error="Failed to start reindex workflow")
            )
        raise HTTPException(status_code=503, detail="ingestion service unavailable") from e

    return response


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(document_id: uuid.UUID, tenant_id: TenantID) -> None:
    object_key = ""
    preview_object_keys: list[str] = []
    async with tenant_session(tenant_id) as s:
        doc = (
            await s.execute(
                select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if doc is None:
            raise HTTPException(status_code=404, detail="document not found")
        object_key = doc.object_key
        preview_object_keys = list(
            (
                await s.execute(
                    select(DocumentAsset.preview_object_key).where(
                        DocumentAsset.document_id == document_id,
                        DocumentAsset.tenant_id == tenant_id,
                    )
                )
            ).scalars().all()
        )
        await s.delete(doc)  # CASCADE deletes chunks via FK ondelete="CASCADE"

    for key in [object_key, url_image_sidecar_key(object_key), *preview_object_keys]:
        try:
            object_store.delete(key)
        except Exception as exc:
            log.warning(
                "object deletion failed | tenant=%s document=%s key=%s error=%s",
                tenant_id,
                document_id,
                key,
                exc,
            )
    await invalidate_semantic_cache(tenant_id, f"document-delete:{document_id}")
