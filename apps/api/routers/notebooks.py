from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from sqlalchemy import delete, select, update
from temporalio.client import Client

from packages.core import settings
from packages.rag import generate_notebook_insights
from packages.storage import Document, DocumentStatus, Notebook, NotebookDocument, object_store
from packages.storage.db import tenant_session

from apps.api.deps import TenantID, read_with_limit
from apps.api.schemas import (
    CreateNotebookRequest,
    DocumentResponse,
    NotebookResponse,
    UpdateNotebookDocumentsRequest,
)
from apps.api.serializers import document_response, notebook_response
from apps.api.services.cache import invalidate_semantic_cache
from apps.api.services.notebooks import (
    clean_notebook_title,
    dedupe_uuid_list,
    load_notebook_documents,
    load_notebook_insight_sources,
    load_tenant_documents,
)
from apps.worker.activities.ingestion import IngestionInput
from apps.worker.workflows.ingestion import IngestionWorkflow

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/notebooks", response_model=list[NotebookResponse])
async def list_notebooks(tenant_id: TenantID) -> list[NotebookResponse]:
    async with tenant_session(tenant_id) as s:
        notebooks = (
            await s.execute(
                select(Notebook)
                .where(Notebook.tenant_id == tenant_id)
                .order_by(Notebook.created_at.desc())
            )
        ).scalars().all()
        responses: list[NotebookResponse] = []
        for notebook in notebooks:
            documents = await load_notebook_documents(s, tenant_id, notebook.id)
            responses.append(notebook_response(notebook, documents))
    return responses


@router.post("/notebooks", response_model=NotebookResponse, status_code=201)
async def create_notebook(
    body: CreateNotebookRequest,
    tenant_id: TenantID,
) -> NotebookResponse:
    document_ids = dedupe_uuid_list(body.document_ids)
    async with tenant_session(tenant_id) as s:
        documents = await load_tenant_documents(s, tenant_id, document_ids)
        notebook = Notebook(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            title=clean_notebook_title(body.title),
            description=body.description.strip() if body.description else None,
        )
        s.add(notebook)
        await s.flush()
        s.add_all(
            [
                NotebookDocument(
                    notebook_id=notebook.id,
                    document_id=document_id,
                    tenant_id=tenant_id,
                )
                for document_id in document_ids
            ]
        )
        await s.flush()
        await s.refresh(notebook)
        response = notebook_response(notebook, documents)
    return response


@router.get("/notebooks/{notebook_id}", response_model=NotebookResponse)
async def get_notebook(notebook_id: uuid.UUID, tenant_id: TenantID) -> NotebookResponse:
    async with tenant_session(tenant_id) as s:
        notebook = (
            await s.execute(
                select(Notebook).where(Notebook.id == notebook_id, Notebook.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if notebook is None:
            raise HTTPException(status_code=404, detail="notebook not found")
        documents = await load_notebook_documents(s, tenant_id, notebook_id)
        response = notebook_response(notebook, documents)
    return response


@router.put("/notebooks/{notebook_id}/documents", response_model=NotebookResponse)
async def replace_notebook_documents(
    notebook_id: uuid.UUID,
    body: UpdateNotebookDocumentsRequest,
    tenant_id: TenantID,
) -> NotebookResponse:
    document_ids = dedupe_uuid_list(body.document_ids)
    async with tenant_session(tenant_id) as s:
        notebook = (
            await s.execute(
                select(Notebook).where(Notebook.id == notebook_id, Notebook.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if notebook is None:
            raise HTTPException(status_code=404, detail="notebook not found")
        documents = await load_tenant_documents(s, tenant_id, document_ids)
        await s.execute(
            delete(NotebookDocument).where(
                NotebookDocument.notebook_id == notebook_id,
                NotebookDocument.tenant_id == tenant_id,
            )
        )
        s.add_all(
            [
                NotebookDocument(
                    notebook_id=notebook_id,
                    document_id=document_id,
                    tenant_id=tenant_id,
                )
                for document_id in document_ids
            ]
        )
        notebook.updated_at = datetime.now(timezone.utc)
        notebook.summary = None
        notebook.suggested_questions = []
        notebook.key_topics = []
        notebook.insights_updated_at = None
        await s.flush()
        response = notebook_response(notebook, documents)
    return response


@router.post("/notebooks/{notebook_id}/documents/upload", response_model=DocumentResponse, status_code=202)
async def upload_notebook_document(
    notebook_id: uuid.UUID,
    request: Request,
    tenant_id: TenantID,
    file: UploadFile = File(...),
) -> DocumentResponse:
    cl = request.headers.get("content-length")
    if cl and int(cl) > settings.max_upload_bytes * 2:
        raise HTTPException(status_code=413, detail=f"file exceeds {settings.max_upload_bytes // (1024 * 1024)} MB limit")

    data = await read_with_limit(file, settings.max_upload_bytes)
    if not data:
        raise HTTPException(status_code=400, detail="empty file")

    document_id = uuid.uuid4()
    filename = file.filename or "unnamed"
    object_key = f"{tenant_id}/{document_id}/{filename}"

    async with tenant_session(tenant_id) as s:
        notebook = (
            await s.execute(
                select(Notebook).where(Notebook.id == notebook_id, Notebook.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if notebook is None:
            raise HTTPException(status_code=404, detail="notebook not found")

        object_store.put(object_key, data, content_type=file.content_type or "application/octet-stream")
        doc = Document(
            id=document_id,
            tenant_id=tenant_id,
            filename=filename,
            mime_type=file.content_type or "application/octet-stream",
            object_key=object_key,
            size_bytes=len(data),
            status=DocumentStatus.pending,
        )
        s.add(doc)
        s.add(NotebookDocument(
            notebook_id=notebook_id,
            document_id=document_id,
            tenant_id=tenant_id,
        ))
        notebook.summary = None
        notebook.suggested_questions = []
        notebook.key_topics = []
        notebook.insights_updated_at = None
        await s.flush()
        response = document_response(doc)

    await invalidate_semantic_cache(tenant_id, f"notebook-document-upload:{notebook_id}:{document_id}")

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

    return response


@router.post("/notebooks/{notebook_id}/insights", response_model=NotebookResponse)
async def rebuild_notebook_insights(
    notebook_id: uuid.UUID,
    tenant_id: TenantID,
) -> NotebookResponse:
    async with tenant_session(tenant_id) as s:
        notebook = (
            await s.execute(
                select(Notebook).where(Notebook.id == notebook_id, Notebook.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if notebook is None:
            raise HTTPException(status_code=404, detail="notebook not found")

        documents = await load_notebook_documents(s, tenant_id, notebook_id)
        ready_documents = [doc for doc in documents if doc.status == DocumentStatus.done]
        if not ready_documents:
            raise HTTPException(status_code=409, detail="notebook has no indexed documents yet")

        title = notebook.title
        ready_document_ids = {doc.id for doc in ready_documents}
        insight_sources = await load_notebook_insight_sources(
            s,
            tenant_id=tenant_id,
            documents=ready_documents,
        )

    try:
        insights = await generate_notebook_insights(insight_sources, title=title)
    except Exception as exc:
        log.exception(
            "notebook insight generation failed | tenant=%s notebook=%s",
            tenant_id,
            notebook_id,
        )
        raise HTTPException(
            status_code=502,
            detail=f"DeepSeek overview generation failed: {exc}",
        ) from exc

    if not insights.summary:
        raise HTTPException(status_code=409, detail="notebook documents have no extractable text")

    async with tenant_session(tenant_id) as s:
        notebook = (
            await s.execute(
                select(Notebook).where(
                    Notebook.id == notebook_id,
                    Notebook.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if notebook is None:
            raise HTTPException(status_code=404, detail="notebook not found")

        documents = await load_notebook_documents(s, tenant_id, notebook_id)
        current_ready_ids = {
            doc.id for doc in documents if doc.status == DocumentStatus.done
        }
        if current_ready_ids != ready_document_ids:
            raise HTTPException(
                status_code=409,
                detail="notebook sources changed while the overview was generated; retry",
            )

        now = datetime.now(timezone.utc)
        notebook.summary = insights.summary
        notebook.suggested_questions = insights.suggested_questions
        notebook.key_topics = insights.key_topics
        notebook.insights_updated_at = now
        notebook.updated_at = now
        await s.flush()
        response = notebook_response(notebook, documents)
    return response


@router.delete("/notebooks/{notebook_id}", status_code=204)
async def delete_notebook(notebook_id: uuid.UUID, tenant_id: TenantID) -> None:
    async with tenant_session(tenant_id) as s:
        notebook = (
            await s.execute(
                select(Notebook).where(Notebook.id == notebook_id, Notebook.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if notebook is None:
            raise HTTPException(status_code=404, detail="notebook not found")
        await s.delete(notebook)
