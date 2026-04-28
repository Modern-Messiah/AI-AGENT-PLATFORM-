"""FastAPI entrypoint.

Endpoints:
  POST /agent/run                    — single agent run (optional require_approval)
  POST /agent/research               — multi-step research via child workflows
  POST /workflows/{id}/approve       — send approve signal (HITL)
  POST /workflows/{id}/reject        — send reject signal (HITL)
  POST /documents                    — upload file, kick off IngestionWorkflow
  GET  /documents/{id}               — ingestion status
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from temporalio.client import Client

from apps.worker.activities.ingestion import IngestionInput
from apps.worker.workflows.agent_run import AgentRunWorkflow
from apps.worker.workflows.ingestion import IngestionWorkflow
from apps.worker.workflows.multi_step import MultiStepResearchWorkflow
from packages.agents import AgentRunInput, AgentRunOutput, MultiStepResearchInput
from packages.analytics.clickhouse import ch_client
from packages.core import settings
from packages.observability import setup_tracing
from packages.storage import Document, DocumentStatus, async_session, object_store


class DocumentResponse(BaseModel):
    id: str
    tenant_id: str
    filename: str
    status: DocumentStatus
    error: str | None = None


class WorkflowSignalResponse(BaseModel):
    workflow_id: str
    action: str


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_tracing("aap-api")
    app.state.temporal = await Client.connect(
        settings.temporal_address, namespace=settings.temporal_namespace
    )
    yield


app = FastAPI(title="AI Agent Platform", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# ── Agent ────────────────────────────────────────────────────────────────────

@app.post("/agent/run", response_model=AgentRunOutput)
async def run_agent(payload: AgentRunInput) -> AgentRunOutput:
    """Single agent run. Set require_approval=true to pause for HITL review."""
    client: Client = app.state.temporal
    workflow_id = f"agent-run-{payload.tenant_id}-{uuid.uuid4()}"
    try:
        return await client.execute_workflow(
            AgentRunWorkflow.run,
            payload,
            id=workflow_id,
            task_queue=settings.temporal_task_queue,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/agent/research", response_model=AgentRunOutput)
async def run_research(payload: MultiStepResearchInput) -> AgentRunOutput:
    """Multi-step research: fan-out sub-queries as child workflows, then synthesise."""
    client: Client = app.state.temporal
    workflow_id = f"research-{payload.tenant_id}-{uuid.uuid4()}"
    try:
        return await client.execute_workflow(
            MultiStepResearchWorkflow.run,
            payload,
            id=workflow_id,
            task_queue=settings.temporal_task_queue,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


# ── HITL signals ─────────────────────────────────────────────────────────────

@app.post("/workflows/{workflow_id}/approve", response_model=WorkflowSignalResponse)
async def approve_workflow(workflow_id: str) -> WorkflowSignalResponse:
    """Send an 'approve' signal to a paused AgentRunWorkflow."""
    client: Client = app.state.temporal
    try:
        handle = client.get_workflow_handle(workflow_id)
        await handle.signal(AgentRunWorkflow.approve)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(e)) from e
    return WorkflowSignalResponse(workflow_id=workflow_id, action="approved")


@app.post("/workflows/{workflow_id}/reject", response_model=WorkflowSignalResponse)
async def reject_workflow(workflow_id: str) -> WorkflowSignalResponse:
    """Send a 'reject' signal to a paused AgentRunWorkflow."""
    client: Client = app.state.temporal
    try:
        handle = client.get_workflow_handle(workflow_id)
        await handle.signal(AgentRunWorkflow.reject)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(e)) from e
    return WorkflowSignalResponse(workflow_id=workflow_id, action="rejected")


# ── Analytics ────────────────────────────────────────────────────────────────

@app.get("/analytics/usage")
async def get_usage(
    tenant_id: str = Query(..., description="Tenant to query"),
    days: int = Query(default=30, ge=1, le=365, description="Lookback window in days"),
) -> dict:
    """Aggregate LLM cost and token usage for a tenant over the last N days."""
    sql = """
        SELECT
            model,
            provider,
            sum(prompt_tokens)      AS total_prompt_tokens,
            sum(completion_tokens)  AS total_completion_tokens,
            sum(total_tokens)       AS total_tokens,
            round(sum(cost_usd), 6) AS total_cost_usd,
            round(avg(latency_ms))  AS avg_latency_ms,
            count()                 AS call_count
        FROM analytics.llm_usage_events
        WHERE tenant_id = {tenant_id:String}
          AND event_time >= now() - toIntervalDay({days:UInt32})
        GROUP BY model, provider
        ORDER BY total_cost_usd DESC
    """
    try:
        rows = await ch_client.query(sql, {"tenant_id": tenant_id, "days": days})
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"ClickHouse error: {e}") from e

    total_cost = sum(r.get("total_cost_usd") or 0 for r in rows)
    return {
        "tenant_id": tenant_id,
        "days": days,
        "total_cost_usd": round(total_cost, 6),
        "breakdown": rows,
    }


# ── Documents ─────────────────────────────────────────────────────────────────

@app.post("/documents", response_model=DocumentResponse, status_code=202)
async def upload_document(
    tenant_id: str = Form(...),
    file: UploadFile = File(...),
) -> DocumentResponse:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")

    document_id = uuid.uuid4()
    object_key = f"{tenant_id}/{document_id}/{file.filename}"
    object_store.put(object_key, data, content_type=file.content_type or "application/octet-stream")

    async with async_session() as s, s.begin():
        doc = Document(
            id=document_id,
            tenant_id=tenant_id,
            filename=file.filename or "unnamed",
            mime_type=file.content_type or "application/octet-stream",
            object_key=object_key,
            status=DocumentStatus.pending,
        )
        s.add(doc)

    client: Client = app.state.temporal
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

    return DocumentResponse(
        id=str(document_id),
        tenant_id=tenant_id,
        filename=file.filename or "unnamed",
        status=DocumentStatus.pending,
    )


@app.post("/documents/bulk", response_model=list[DocumentResponse], status_code=202)
async def upload_documents_bulk(
    tenant_id: str = Form(...),
    files: list[UploadFile] = File(...),
) -> list[DocumentResponse]:
    """Upload multiple documents at once. Each gets its own IngestionWorkflow."""
    if not files:
        raise HTTPException(status_code=400, detail="no files provided")

    client: Client = app.state.temporal
    responses: list[DocumentResponse] = []

    for file in files:
        data = await file.read()
        if not data:
            continue
        document_id = uuid.uuid4()
        object_key = f"{tenant_id}/{document_id}/{file.filename}"
        object_store.put(
            object_key, data,
            content_type=file.content_type or "application/octet-stream",
        )
        async with async_session() as s, s.begin():
            doc = Document(
                id=document_id,
                tenant_id=tenant_id,
                filename=file.filename or "unnamed",
                mime_type=file.content_type or "application/octet-stream",
                object_key=object_key,
                status=DocumentStatus.pending,
            )
            s.add(doc)
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
        responses.append(DocumentResponse(
            id=str(document_id),
            tenant_id=tenant_id,
            filename=file.filename or "unnamed",
            status=DocumentStatus.pending,
        ))

    return responses


@app.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(document_id: uuid.UUID) -> DocumentResponse:
    async with async_session() as s:
        doc = (
            await s.execute(select(Document).where(Document.id == document_id))
        ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    return DocumentResponse(
        id=str(doc.id),
        tenant_id=doc.tenant_id,
        filename=doc.filename,
        status=doc.status,
        error=doc.error,
    )
