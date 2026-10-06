from __future__ import annotations

import asyncio
import json
import logging
import uuid
import zipfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from tempfile import SpooledTemporaryFile
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from packages.auth import Actor, require_actor
from packages.core import settings
from packages.storage import (
    Chunk,
    Document,
    DocumentAsset,
    DocumentStatus,
    Notebook,
    NotebookDocument,
    object_store,
)
from packages.storage.db import tenant_session
from sqlalchemy import select, update
from starlette.responses import Response, StreamingResponse
from temporalio.client import Client

from apps.api.deps import ActorDep, TenantID, content_length_exceeds, read_with_limit
from apps.api.schemas import (
    AddUrlDocumentRequest,
    DocumentAssetResponse,
    DocumentChunkPreview,
    DocumentReindexResponse,
    DocumentResponse,
    DocumentShareRequest,
    UrlCheckRequest,
    UrlCheckResponse,
)
from apps.api.serializers import (
    chunk_excerpt,
    document_asset_response,
    document_response,
    metadata_page,
)
from apps.api.services.access import accessible_condition, can_access, can_manage, scope_condition
from apps.api.services.cache import invalidate_semantic_cache
from apps.api.services.filenames import safe_upload_filename
from apps.api.services.url_source_limits import enforce_url_ingest_limit
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


async def _store_url_source_objects(object_key: str, fetched: FetchedUrlSource) -> None:
    # MinIO SDK is synchronous — keep blocking I/O off the event loop.
    await asyncio.to_thread(
        object_store.put, object_key, fetched.data, content_type=fetched.content_type
    )
    await asyncio.to_thread(
        object_store.put,
        url_image_sidecar_key(object_key),
        url_image_sidecar_payload(fetched.image_sources),
        content_type="application/json",
    )


async def _object_bytes_or_none(object_key: str) -> bytes | None:
    try:
        return await asyncio.to_thread(object_store.get, object_key)
    except Exception as exc:
        log.debug("source object comparison skipped | key=%s error=%s", object_key, exc)
        return None


async def _url_source_objects_changed(object_key: str, fetched: FetchedUrlSource) -> bool:
    return await _object_bytes_or_none(object_key) != fetched.data or await _object_bytes_or_none(
        url_image_sidecar_key(object_key)
    ) != url_image_sidecar_payload(fetched.image_sources)


def _apply_url_source_metadata(doc: Document, fetched: FetchedUrlSource) -> None:
    doc.filename = fetched.filename
    doc.mime_type = fetched.content_type
    doc.size_bytes = fetched.size_bytes
    doc.source_type = fetched.source_type
    doc.source_url = fetched.final_url
    doc.source_title = fetched.title
    doc.source_checked_at = datetime.now(UTC)


@router.get("/documents", response_model=list[DocumentResponse])
async def list_documents(
    actor: ActorDep,
    scope: str = Query(default="all", pattern="^(mine|shared|all)$"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[DocumentResponse]:
    tenant_id = actor.tenant_id
    async with tenant_session(tenant_id) as s:
        stmt = (
            select(Document)
            .where(Document.tenant_id == tenant_id)
            .order_by(Document.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if (condition := scope_condition(Document, actor, scope)) is not None:
            stmt = stmt.where(condition)
        rows = (await s.execute(stmt)).scalars().all()
    return [document_response(doc) for doc in rows]


@router.get("/documents/export")
async def export_documents(actor: ActorDep) -> Response:
    """Download the acting user's knowledge base as a single ZIP.

    Exports every document the actor may access (own + shared — the same
    corpus the agent searches; the whole tenant for unbound keys): original
    object bytes plus a manifest.json with metadata and ownership. Must be
    declared before /documents/{document_id} or "export" would match the
    path parameter.
    """
    tenant_id = actor.tenant_id
    async with tenant_session(tenant_id) as s:
        stmt = (
            select(Document)
            .where(Document.tenant_id == tenant_id)
            .order_by(Document.created_at.desc())
        )
        if (condition := accessible_condition(Document, actor)) is not None:
            stmt = stmt.where(condition)
        rows = (await s.execute(stmt)).scalars().all()
    if not rows:
        raise HTTPException(status_code=404, detail="no documents to export")

    def build_archive(buffer: SpooledTemporaryFile[bytes]) -> int:
        def unique_name(name: str, used: set[str]) -> str:
            if name not in used:
                used.add(name)
                return name
            stem, dot, ext = name.rpartition(".")
            base = stem if dot else name
            ext_part = f".{ext}" if dot else ""
            index = 1
            while (candidate := f"{base} ({index}){ext_part}") in used:
                index += 1
            used.add(candidate)
            return candidate

        manifest: list[dict[str, object]] = []
        used_names: set[str] = set()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for doc in rows:
                try:
                    data = object_store.get(doc.object_key)
                except Exception as exc:
                    log.warning(
                        "export: object missing | tenant=%s document=%s error=%s",
                        tenant_id,
                        doc.id,
                        exc,
                    )
                    manifest.append(
                        {
                            "id": str(doc.id),
                            "filename": doc.filename,
                            "exported": False,
                            "error": "object not found in storage",
                        }
                    )
                    continue
                archive_name = unique_name(doc.filename or f"{doc.id}.bin", used_names)
                archive.writestr(archive_name, data)
                manifest.append(
                    {
                        "id": str(doc.id),
                        "filename": doc.filename,
                        "archive_name": archive_name,
                        "exported": True,
                        "status": str(getattr(doc.status, "value", doc.status)),
                        "size_bytes": doc.size_bytes,
                        "source_type": getattr(doc, "source_type", "file") or "file",
                        "source_url": getattr(doc, "source_url", None),
                        "is_mine": bool(actor.user_id and doc.owner_user_id == actor.user_id),
                        "is_shared": bool(doc.is_shared),
                        "created_at": doc.created_at.isoformat() if doc.created_at else None,
                    }
                )
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "tenant_id": tenant_id,
                        "exported_at": datetime.now(UTC).isoformat(),
                        "document_count": len(manifest),
                        "documents": manifest,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        return len(manifest)

    # MinIO SDK and zipfile are synchronous — keep both off the event loop.
    # SpooledTemporaryFile rolls to disk past 64 MB, so huge bases do not
    # sit in RAM. Starlette does not own the handle: the streaming
    # generator below closes it in finally.
    buffer: SpooledTemporaryFile[bytes] = SpooledTemporaryFile(max_size=64 * 1024 * 1024)  # noqa: SIM115
    count = await asyncio.to_thread(build_archive, buffer)
    if count == 0:
        buffer.close()
        raise HTTPException(status_code=404, detail="no documents to export")
    buffer.seek(0)

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")

    async def _stream() -> AsyncIterator[bytes]:
        try:
            while chunk := await asyncio.to_thread(buffer.read, 1024 * 1024):
                yield chunk
        finally:
            buffer.close()

    return StreamingResponse(
        _stream(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="knowledge-base-{tenant_id}-{stamp}.zip"',
        },
    )


@router.post("/documents", response_model=DocumentResponse, status_code=202)
async def upload_document(
    request: Request,
    actor: ActorDep,
    file: UploadFile = File(...),
    shared: bool = Form(default=False),
) -> DocumentResponse:
    tenant_id = actor.tenant_id
    # Early rejection before reading body (Content-Length may include multipart overhead,
    # so use a 2x guard here; exact byte-level check happens inside read_with_limit).
    if content_length_exceeds(request, settings.max_upload_bytes * 2):
        raise HTTPException(
            status_code=413,
            detail=f"file exceeds {settings.max_upload_bytes // (1024 * 1024)} MB limit",
        )

    data = await read_with_limit(file, settings.max_upload_bytes)
    if not data:
        raise HTTPException(status_code=400, detail="empty file")

    document_id = uuid.uuid4()
    filename = safe_upload_filename(file.filename)
    object_key = f"{tenant_id}/{document_id}/{filename}"
    await asyncio.to_thread(
        object_store.put,
        object_key,
        data,
        content_type=file.content_type or "application/octet-stream",
    )

    async with tenant_session(tenant_id) as s:
        s.add(
            Document(
                id=document_id,
                tenant_id=tenant_id,
                owner_user_id=actor.user_id,
                is_shared=shared,
                filename=filename,
                mime_type=file.content_type or "application/octet-stream",
                object_key=object_key,
                size_bytes=len(data),
                status=DocumentStatus.pending,
            )
        )

    await invalidate_semantic_cache(tenant_id, f"document-upload:{document_id}")

    client: Client = request.app.state.temporal
    try:
        await client.start_workflow(
            IngestionWorkflow.run,
            IngestionInput(
                document_id=str(document_id),
                tenant_id=tenant_id,
                object_key=object_key,
                filename=filename,
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
    actor: ActorDep,
    files: list[UploadFile] = File(...),
    shared: bool = Form(default=False),
) -> list[DocumentResponse]:
    """Upload multiple documents at once. Each gets its own IngestionWorkflow."""
    tenant_id = actor.tenant_id
    if not files:
        raise HTTPException(status_code=400, detail="no files provided")
    if len(files) > 20:
        raise HTTPException(status_code=400, detail="max 20 files per bulk upload")

    # Phase 1: read and validate ALL files before starting any workflow.
    # This prevents partial state where some workflows fire but a later file fails validation.
    if content_length_exceeds(request, settings.max_upload_bytes * len(files) * 2):
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
    workflow_start_failures = 0

    for file, data in validated:
        document_id = uuid.uuid4()
        filename = safe_upload_filename(file.filename)
        object_key = f"{tenant_id}/{document_id}/{filename}"
        await asyncio.to_thread(
            object_store.put,
            object_key,
            data,
            content_type=file.content_type or "application/octet-stream",
        )
        async with tenant_session(tenant_id) as s:
            s.add(
                Document(
                    id=document_id,
                    tenant_id=tenant_id,
                    owner_user_id=actor.user_id,
                    is_shared=shared,
                    filename=filename,
                    mime_type=file.content_type or "application/octet-stream",
                    object_key=object_key,
                    size_bytes=len(data),
                    status=DocumentStatus.pending,
                )
            )
        await invalidate_semantic_cache(tenant_id, f"document-upload:{document_id}")
        try:
            await client.start_workflow(
                IngestionWorkflow.run,
                IngestionInput(
                    document_id=str(document_id),
                    tenant_id=tenant_id,
                    object_key=object_key,
                    filename=filename,
                ),
                id=f"ingest-{tenant_id}-{document_id}",
                task_queue=settings.temporal_task_queue,
            )
        except Exception as exc:
            workflow_start_failures += 1
            log.warning(
                "bulk upload: ingestion workflow failed to start | tenant=%s document=%s error=%s",
                tenant_id,
                document_id,
                exc,
            )
            async with tenant_session(tenant_id) as s:
                await s.execute(
                    update(Document)
                    .where(Document.id == document_id)
                    .values(
                        status=DocumentStatus.failed, error="Failed to start ingestion workflow"
                    )
                )
        async with tenant_session(tenant_id) as s:
            doc = (await s.execute(select(Document).where(Document.id == document_id))).scalar_one()
        responses.append(document_response(doc))

    if workflow_start_failures == len(validated):
        # Total outage: same contract as the single-upload path — the client
        # must learn the batch never reached ingestion, not dig per-file
        # statuses out of a 202 body.
        raise HTTPException(status_code=503, detail="ingestion service unavailable")
    return responses


@router.post("/documents/url/check", response_model=UrlCheckResponse)
async def check_url_document(body: UrlCheckRequest, tenant_id: TenantID) -> UrlCheckResponse:
    await enforce_url_ingest_limit(tenant_id, "/documents/url/check")
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
    actor: ActorDep,
) -> DocumentResponse:
    tenant_id = actor.tenant_id
    await enforce_url_ingest_limit(tenant_id, "/documents/url")
    try:
        fetched = await fetch_url_source(body.url)
    except UrlSourceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    document_id = uuid.uuid4()
    object_key = f"{tenant_id}/{document_id}/{fetched.filename}"
    await _store_url_source_objects(object_key, fetched)
    checked_at = datetime.now(UTC)

    async with tenant_session(tenant_id) as s:
        s.add(
            Document(
                id=document_id,
                tenant_id=tenant_id,
                owner_user_id=actor.user_id,
                is_shared=body.shared,
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
            )
        )

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
async def get_document(document_id: uuid.UUID, actor: ActorDep) -> DocumentResponse:
    tenant_id = actor.tenant_id
    async with tenant_session(tenant_id) as s:
        doc = (
            await s.execute(
                select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
    # Inaccessible documents are reported as missing — existence is private too.
    if doc is None or not can_access(actor, doc):
        raise HTTPException(status_code=404, detail="document not found")
    return document_response(doc)


@router.get("/documents/{document_id}/assets", response_model=list[DocumentAssetResponse])
async def list_document_assets(
    document_id: uuid.UUID,
    actor: ActorDep,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[DocumentAssetResponse]:
    tenant_id = actor.tenant_id
    async with tenant_session(tenant_id) as s:
        doc = (
            await s.execute(
                select(Document).where(
                    Document.id == document_id,
                    Document.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if doc is None or not can_access(actor, doc):
            raise HTTPException(status_code=404, detail="document not found")
        assets = (
            (
                await s.execute(
                    select(DocumentAsset)
                    .where(
                        DocumentAsset.document_id == document_id,
                        DocumentAsset.tenant_id == tenant_id,
                    )
                    .order_by(DocumentAsset.page_number, DocumentAsset.created_at)
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
    return [document_asset_response(asset) for asset in assets]


@router.get("/documents/{document_id}/assets/{asset_id}/content")
async def get_document_asset_content(
    document_id: uuid.UUID,
    asset_id: uuid.UUID,
    actor: ActorDep,
) -> Response:
    tenant_id = actor.tenant_id
    async with tenant_session(tenant_id) as s:
        doc = (
            await s.execute(
                select(Document).where(
                    Document.id == document_id,
                    Document.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if doc is None or not can_access(actor, doc):
            raise HTTPException(status_code=404, detail="document not found")
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
    actor: ActorDep,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[DocumentChunkPreview]:
    tenant_id = actor.tenant_id
    async with tenant_session(tenant_id) as s:
        doc = (
            await s.execute(
                select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if doc is None or not can_access(actor, doc):
            raise HTTPException(status_code=404, detail="document not found")
        chunks = (
            (
                await s.execute(
                    select(Chunk)
                    .where(Chunk.document_id == document_id, Chunk.tenant_id == tenant_id)
                    .order_by(Chunk.chunk_idx)
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )

    return [
        DocumentChunkPreview(
            chunk_id=str(chunk.id),
            chunk_index=chunk.chunk_idx,
            page=metadata_page(chunk.chunk_metadata or {}),
            excerpt=chunk_excerpt(chunk.content),
        )
        for chunk in chunks
    ]


@router.post(
    "/documents/{document_id}/reindex", response_model=DocumentReindexResponse, status_code=202
)
async def reindex_document(
    document_id: uuid.UUID,
    actor: ActorDep,
    request: Request,
) -> DocumentReindexResponse:
    tenant_id = actor.tenant_id
    # Phase 1 — short read transaction: is the document reindexable right now?
    async with tenant_session(tenant_id) as s:
        doc = (
            await s.execute(
                select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if doc is None or not can_access(actor, doc):
            raise HTTPException(status_code=404, detail="document not found")
        if doc.status in {DocumentStatus.pending, DocumentStatus.processing}:
            raise HTTPException(status_code=409, detail="document is already being indexed")

        is_external = getattr(doc, "source_type", "file") in {"url", "github"}
        source_url = getattr(doc, "source_url", None)
        object_key = doc.object_key
        status_before = doc.status

    if is_external and not source_url:
        raise HTTPException(status_code=409, detail="external document has no source URL")

    # Phase 2 — external fetch + object-store I/O with NO transaction open:
    # a slow or malicious source (10s timeout per hop) must not pin pooled
    # DB connections; a handful of concurrent reindexes used to exhaust them.
    fetched: FetchedUrlSource | None = None
    changed = False
    if is_external and source_url:
        await enforce_url_ingest_limit(tenant_id, "/documents/reindex")
        try:
            fetched = await fetch_url_source(source_url)
        except UrlSourceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
        changed = await _url_source_objects_changed(object_key, fetched)
        if changed or status_before != DocumentStatus.done:
            await _store_url_source_objects(object_key, fetched)

    # Phase 3 — short write transaction: re-check (the document may have been
    # deleted or picked up by another reindex while we were fetching), apply,
    # queue.
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

        if fetched is not None:
            _apply_url_source_metadata(doc, fetched)
            if not changed and doc.status == DocumentStatus.done:
                await s.flush()
                return DocumentReindexResponse(
                    document=document_response(doc),
                    changed=False,
                    workflow_started=False,
                )

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

    return DocumentReindexResponse(document=response, changed=True, workflow_started=True)


@router.patch("/documents/{document_id}/share", response_model=DocumentResponse)
async def set_document_shared(
    document_id: uuid.UUID,
    body: DocumentShareRequest,
    actor: ActorDep,
) -> DocumentResponse:
    """Flip a document between private and tenant-shared after upload.

    Owner, admin or unbound-key only. Un-sharing is refused while the
    document belongs to a shared notebook: stored notebook insights are
    visible to everyone who can open it, so the shared-notebook invariant
    (shared notebooks contain only shared documents) must hold.
    """
    tenant_id = actor.tenant_id
    async with tenant_session(tenant_id) as s:
        doc = (
            await s.execute(
                select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if doc is None or not can_access(actor, doc):
            raise HTTPException(status_code=404, detail="document not found")
        if not can_manage(actor, doc):
            raise HTTPException(
                status_code=403,
                detail="member keys cannot change sharing of documents they do not own",
            )
        if not body.shared:
            shared_titles = list(
                (
                    await s.execute(
                        select(Notebook.title)
                        .join(NotebookDocument, NotebookDocument.notebook_id == Notebook.id)
                        .where(
                            NotebookDocument.document_id == document_id,
                            NotebookDocument.tenant_id == tenant_id,
                            Notebook.is_shared.is_(True),
                        )
                        .limit(3)
                    )
                )
                .scalars()
                .all()
            )
            if shared_titles:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "document is part of shared notebook(s) — remove it there first: "
                        + ", ".join(shared_titles)
                    ),
                )
        doc.is_shared = body.shared
        await s.flush()
        response = document_response(doc)
    # Sharing changes who may retrieve the document — cached answers
    # ("not found" refusals included) must not outlive the flip.
    await invalidate_semantic_cache(tenant_id, f"document-share:{document_id}")
    return response


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID, actor: Annotated[Actor, Depends(require_actor)]
) -> None:
    tenant_id = actor.tenant_id
    object_key = ""
    preview_object_keys: list[str] = []
    async with tenant_session(tenant_id) as s:
        doc = (
            await s.execute(
                select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if doc is None or not can_access(actor, doc):
            raise HTTPException(status_code=404, detail="document not found")
        if not can_manage(actor, doc):
            # Members may destroy only their own documents; shared/foreign
            # ones stay admin-only (same contract as require_destroy_permission).
            raise HTTPException(
                status_code=403, detail="member keys cannot delete shared documents"
            )
        object_key = doc.object_key
        preview_object_keys = list(
            (
                await s.execute(
                    select(DocumentAsset.preview_object_key).where(
                        DocumentAsset.document_id == document_id,
                        DocumentAsset.tenant_id == tenant_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        linked_notebook_ids = list(
            (
                await s.execute(
                    select(NotebookDocument.notebook_id).where(
                        NotebookDocument.document_id == document_id,
                        NotebookDocument.tenant_id == tenant_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        if linked_notebook_ids:
            await s.execute(
                update(Notebook)
                .where(Notebook.id.in_(linked_notebook_ids), Notebook.tenant_id == tenant_id)
                .values(
                    summary=None,
                    suggested_questions=[],
                    key_topics=[],
                    insights_updated_at=None,
                )
            )
        await s.delete(doc)  # CASCADE deletes chunks via FK ondelete="CASCADE"

    for key in [object_key, url_image_sidecar_key(object_key), *preview_object_keys]:
        try:
            await asyncio.to_thread(object_store.delete, key)
        except Exception as exc:
            log.warning(
                "object deletion failed | tenant=%s document=%s key=%s error=%s",
                tenant_id,
                document_id,
                key,
                exc,
            )
    await invalidate_semantic_cache(tenant_id, f"document-delete:{document_id}")
