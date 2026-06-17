"""FastAPI entrypoint.

Auth: every endpoint (except /health and /auth/keys) requires
  X-API-Key: <raw key>
Keys are created via POST /auth/keys (protected by X-Admin-Secret header).

Endpoints:
  POST /agent/run                    — single agent run (optional require_approval)
  POST /agent/research               — multi-step research via child workflows
  GET  /workflows/{id}/result        — poll HITL workflow result
  POST /workflows/{id}/approve       — send approve signal (HITL)
  POST /workflows/{id}/reject        — send reject signal (HITL)
  POST /documents                    — upload file, kick off IngestionWorkflow
  POST /documents/bulk               — upload multiple files
  GET  /documents/{id}               — ingestion status
  GET  /documents/{id}/chunks        — indexed chunk previews for one document
  POST /documents/{id}/reindex       — rebuild chunks/embeddings for existing file
  GET  /notebooks                    — list document collections
  POST /notebooks                    — create a document collection
  GET  /notebooks/{id}               — collection detail
  PUT  /notebooks/{id}/documents     — replace collection documents
  POST /notebooks/{id}/documents/upload — upload and attach a file
  POST /notebooks/{id}/insights      — rebuild collection overview
  GET  /analytics/usage              — cost/token aggregate for a tenant
  POST /auth/keys                    — create an API key (admin only)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from functools import lru_cache
from typing import AsyncIterator

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from packages.agents import (
    AgentRunInput,
    AgentRunOutput,
    MultiStepResearchInput,
    build_research_agent,
)
from packages.analytics.events import UsageEvent, record_usage
from packages.cache.redis import get_redis
from packages.cache.semantic import semantic_cache
from packages.core import settings
from packages.core.tenant_utils import check_workflow_tenant
from packages.llm import stream_chat_text
from packages.observability import setup_tracing
from packages.rag import (
    CitationSource,
    NotebookInsightSource,
    build_citations,
    build_grounded_messages,
    generate_notebook_insights,
    retrieve_chunks,
    select_answer_sources,
    select_diverse_chunks,
)
from packages.rag.embedder import embed_texts
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
from sqlalchemy import delete, func, select, update
from starlette.responses import Response, StreamingResponse
from temporalio.client import Client
from temporalio.service import RPCError

from apps.api.deps import TenantID, read_with_limit
from apps.api.routers import analytics_router, auth_router, health_router, sessions_router
from apps.api.schemas import (
    AddMessageRequest,
    AgentRunApiResponse,
    AgentStreamRequest,
    ChatMessageSchema,
    ChatSessionSchema,
    CreateKeyRequest,
    CreateKeyResponse,
    CreateNotebookRequest,
    CreateSessionRequest,
    DocumentAssetResponse,
    DocumentChunkPreview,
    DocumentResponse,
    NotebookResponse,
    UpdateSessionRequest,
    UpdateNotebookDocumentsRequest,
    WorkflowSignalResponse,
)
from apps.api.serializers import (
    chunk_excerpt,
    document_asset_response,
    document_response,
    metadata_page,
    notebook_response,
    serialize_sources,
)
from apps.worker.activities.ingestion import IngestionInput
from apps.worker.workflows.agent_run import AgentRunWorkflow
from apps.worker.workflows.ingestion import IngestionWorkflow
from apps.worker.workflows.multi_step import MultiStepResearchWorkflow

# Backward-compatible names imported by existing tests and scripts.
_chunk_excerpt = chunk_excerpt
_document_asset_response = document_asset_response
_document_response = document_response
_metadata_page = metadata_page
_notebook_response = notebook_response
_read_with_limit = read_with_limit
_serialize_sources = serialize_sources

logging.basicConfig(level=settings.log_level)
log = logging.getLogger(__name__)


@lru_cache(maxsize=8)
def _get_streaming_agent(model_name: str | None):  # type: ignore[return]
    return build_research_agent(model_name=model_name)


_PARTIAL_ANSWER_RE = re.compile(r'"answer"\s*:\s*"((?:\\.|[^"\\])*)')


def _extract_partial_answer(parts: list[object]) -> str | None:
    """Read the progressively streamed `answer` from the final_result tool args."""
    for part in parts:
        if getattr(part, "tool_name", None) != "final_result":
            continue

        args = getattr(part, "args", "")
        if not isinstance(args, str):
            continue

        match = _PARTIAL_ANSWER_RE.search(args)
        if match is None:
            continue

        raw = match.group(1)
        try:
            return json.loads(f'"{raw}"')
        except json.JSONDecodeError:
            return (
                raw
                .replace("\\n", "\n")
                .replace("\\t", "\t")
                .replace('\\"', '"')
                .replace("\\\\", "\\")
            )
    return None


def _serialize_sources(
    sources: list[str | CitationSource],
) -> list[str | dict[str, object]]:
    return [
        source.model_dump(mode="json") if isinstance(source, CitationSource) else source
        for source in sources
    ]


async def _invalidate_semantic_cache(tenant_id: str, reason: str) -> None:
    try:
        await semantic_cache.clear(tenant_id)
    except Exception as exc:
        log.warning(
            "semantic cache invalidation failed | tenant=%s reason=%s error=%s",
            tenant_id,
            reason,
            exc,
        )


def _validate_agent_query(query: str) -> str:
    query = query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="user_query must not be empty")
    if len(query) > settings.agent_query_max_chars:
        raise HTTPException(
            status_code=413,
            detail=f"user_query exceeds {settings.agent_query_max_chars} character limit",
        )
    return query


async def _check_agent_rate_limit(
    redis,
    tenant_id: str,
    *,
    limit: int,
    now_ms: int | None = None,
) -> None:
    window_ms = 60_000
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    key = f"rl:{tenant_id}:agent"
    member = f"{now_ms}:{uuid.uuid4().hex}"
    window_start = now_ms - window_ms

    pipe = redis.pipeline(transaction=True)
    pipe.zremrangebyscore(key, 0, window_start)
    pipe.zadd(key, {member: now_ms})
    pipe.zcard(key)
    pipe.expire(key, 120)
    _removed, _added, count, _expired = await pipe.execute()

    if count <= limit:
        return

    await redis.zrem(key, member)
    oldest = await redis.zrange(key, 0, 0, withscores=True)
    oldest_score = float(oldest[0][1]) if oldest else float(now_ms)
    retry_after = max(
        1,
        min(60, int((oldest_score + window_ms - now_ms + 999) // 1000)),
    )
    raise HTTPException(
        status_code=429,
        detail=f"rate limit exceeded: {limit} agent requests per minute",
        headers={"Retry-After": str(retry_after)},
    )


async def _enforce_agent_limits(tenant_id: str, query: str, route: str) -> str:
    query = _validate_agent_query(query)
    limit = settings.agent_rate_limit_per_minute
    if limit <= 0:
        return query

    try:
        await _check_agent_rate_limit(get_redis(), tenant_id, limit=limit)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("rate limit check failed open | tenant=%s route=%s error=%s", tenant_id, route, exc)
    return query

def _dedupe_uuid_list(ids: list[uuid.UUID]) -> list[uuid.UUID]:
    seen: set[uuid.UUID] = set()
    deduped: list[uuid.UUID] = []
    for item in ids:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _clean_notebook_title(title: str) -> str:
    cleaned = title.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="title must not be empty")
    return cleaned


async def _load_tenant_documents(
    db,
    tenant_id: str,
    document_ids: list[uuid.UUID],
) -> list[Document]:
    if not document_ids:
        return []
    rows = (
        await db.execute(
            select(Document)
            .where(Document.id.in_(document_ids), Document.tenant_id == tenant_id)
            .order_by(Document.created_at.desc())
        )
    ).scalars().all()
    if len(rows) != len(document_ids):
        raise HTTPException(status_code=404, detail="one or more documents not found")
    by_id = {doc.id: doc for doc in rows}
    return [by_id[doc_id] for doc_id in document_ids]


async def _load_notebook_documents(db, tenant_id: str, notebook_id: uuid.UUID) -> list[Document]:
    return (
        await db.execute(
            select(Document)
            .join(NotebookDocument, NotebookDocument.document_id == Document.id)
            .where(
                NotebookDocument.notebook_id == notebook_id,
                NotebookDocument.tenant_id == tenant_id,
                Document.tenant_id == tenant_id,
            )
            .order_by(NotebookDocument.created_at, Document.created_at.desc())
        )
    ).scalars().all()


async def _load_notebook_insight_sources(
    db,
    *,
    tenant_id: str,
    documents: list[Document],
) -> list[NotebookInsightSource]:
    if not documents:
        return []

    document_ids = [doc.id for doc in documents]
    chunks = (
        await db.execute(
            select(Chunk)
            .where(
                Chunk.document_id.in_(document_ids),
                Chunk.tenant_id == tenant_id,
            )
            .order_by(Chunk.document_id, Chunk.chunk_idx)
        )
    ).scalars().all()
    chunks_by_document: dict[uuid.UUID, list[str]] = {
        document_id: [] for document_id in document_ids
    }
    for chunk in chunks:
        chunks_by_document.setdefault(chunk.document_id, []).append(chunk.content)

    return [
        NotebookInsightSource(
            filename=doc.filename,
            summary=doc.summary or "",
            suggested_questions=doc.suggested_questions or [],
            chunks=chunks_by_document.get(doc.id, []),
        )
        for doc in documents
    ]


# ── App lifecycle ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_tracing("aap-api")
    log.info("warming up embedding model...")
    try:
        await embed_texts(["warmup"])
        log.info("embedding model ready")
    except Exception as exc:  # noqa: BLE001
        log.warning("embedding model warmup failed (%s) — will retry on first use", exc)
    app.state.temporal = await Client.connect(
        settings.temporal_address, namespace=settings.temporal_namespace
    )
    yield


app = FastAPI(title="AI Agent Platform", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(analytics_router)
app.include_router(sessions_router)


# ── Agent ─────────────────────────────────────────────────────────────────────

@app.post("/agent/run", response_model=AgentRunApiResponse)
async def run_agent(payload: AgentRunInput, tenant_id: TenantID) -> AgentRunApiResponse:
    """Single agent run. Set require_approval=true to pause for HITL review."""
    user_query = await _enforce_agent_limits(tenant_id, payload.user_query, "/agent/run")
    payload = payload.model_copy(update={"user_query": user_query})

    async with tenant_session(tenant_id) as db:
        chunk_count = (await db.execute(
            select(func.count()).select_from(Chunk).where(Chunk.tenant_id == tenant_id)
        )).scalar()
    if not chunk_count:
        return AgentRunApiResponse(
            answer=(
                "У вас ещё нет проиндексированных документов. "
                "Перейдите в раздел «Документы», загрузите файлы — "
                "после индексации я смогу отвечать на вопросы по ним."
            ),
            confidence=1.0,
        )

    payload = payload.model_copy(update={"tenant_id": tenant_id})
    client: Client = app.state.temporal
    workflow_id = f"agent-run-{tenant_id}-{uuid.uuid4()}"

    if payload.require_approval:
        try:
            await client.start_workflow(
                AgentRunWorkflow.run,
                payload,
                id=workflow_id,
                task_queue=settings.temporal_task_queue,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return AgentRunApiResponse(workflow_id=workflow_id, pending_approval=True)

    try:
        result: AgentRunOutput = await client.execute_workflow(
            AgentRunWorkflow.run,
            payload,
            id=workflow_id,
            task_queue=settings.temporal_task_queue,
        )
        return AgentRunApiResponse(
            answer=result.answer,
            confidence=result.confidence,
            sources=result.sources,
            cached=result.cached,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/agent/stream")
async def agent_stream(body: AgentStreamRequest, tenant_id: TenantID) -> StreamingResponse:
    """SSE streaming agent — bypasses Temporal for interactive chat."""
    user_query = await _enforce_agent_limits(tenant_id, body.user_query, "/agent/stream")
    model_name = body.model or settings.strong_model
    scoped_document_id = body.document_id
    scoped_notebook_id = body.notebook_id
    scoped_document_ids: list[uuid.UUID] | None = None

    if scoped_document_id is not None:
        async with tenant_session(tenant_id) as db:
            doc = (
                await db.execute(
                    select(Document).where(
                        Document.id == scoped_document_id,
                        Document.tenant_id == tenant_id,
                    )
                )
            ).scalar_one_or_none()
        if doc is None:
            raise HTTPException(status_code=404, detail="document not found")
        if doc.status != DocumentStatus.done:
            raise HTTPException(status_code=409, detail="document is not indexed yet")
    if scoped_notebook_id is not None:
        async with tenant_session(tenant_id) as db:
            notebook = (
                await db.execute(
                    select(Notebook).where(
                        Notebook.id == scoped_notebook_id,
                        Notebook.tenant_id == tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if notebook is None:
                raise HTTPException(status_code=404, detail="notebook not found")
            notebook_documents = await _load_notebook_documents(db, tenant_id, scoped_notebook_id)
        if not notebook_documents:
            raise HTTPException(status_code=409, detail="notebook has no documents")
        scoped_document_ids = [
            doc.id for doc in notebook_documents if doc.status == DocumentStatus.done
        ]
        if not scoped_document_ids:
            raise HTTPException(status_code=409, detail="notebook has no indexed documents yet")

    async def generate() -> AsyncIterator[str]:
        request_t0 = time.monotonic()
        scoped = scoped_document_id is not None or scoped_notebook_id is not None
        cached = None
        if not scoped:
            cache_t0 = time.monotonic()
            # Semantic cache — instant reply if hit. Scoped document requests skip it:
            # the same wording can mean different things inside different files.
            try:
                cached = await semantic_cache.get(user_query, tenant_id)
            except Exception:
                cached = None
            log.info(
                "agent_stream cache lookup | tenant=%s hit=%s latency_ms=%d",
                tenant_id,
                cached is not None,
                int((time.monotonic() - cache_t0) * 1000),
            )

        if cached is not None:
            cached_sources = cached.sources
            if all(isinstance(source, CitationSource) for source in cached_sources):
                cached_sources = select_answer_sources(cached.answer, cached_sources)
            cached_sources = _serialize_sources(cached_sources)
            yield f"data: {json.dumps({'type': 'token', 'content': cached.answer})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'answer': cached.answer, 'sources': cached_sources, 'confidence': cached.confidence, 'cached': True})}\n\n"
            return

        try:
            retrieve_t0 = time.monotonic()
            chunks = await retrieve_chunks(
                user_query,
                tenant_id,
                k=settings.fast_rag_candidate_k,
                max_distance=settings.retrieval_max_distance,
                document_id=scoped_document_id,
                document_ids=scoped_document_ids,
            )
            log.info(
                "agent_stream retrieve | tenant=%s document=%s notebook=%s chunks=%d latency_ms=%d matches=%s",
                tenant_id,
                scoped_document_id,
                scoped_notebook_id,
                len(chunks),
                int((time.monotonic() - retrieve_t0) * 1000),
                [(c.filename, round(c.score, 3)) for c in chunks],
            )

            if not chunks:
                answer = (
                    "Не нашёл релевантной информации в выбранном документе."
                    if scoped_document_id is not None
                    else "Не нашёл релевантной информации в выбранной коллекции."
                    if scoped_notebook_id is not None
                    else "Не нашёл релевантной информации в загруженных документах."
                )
                output = AgentRunOutput(answer=answer, sources=[], confidence=0.2, cached=False)
                yield f"data: {json.dumps({'type': 'token', 'content': answer})}\n\n"
                yield (
                    "data: "
                    f"{json.dumps({'type': 'done', 'answer': answer, 'sources': [], 'confidence': output.confidence, 'cached': False})}\n\n"
                )
                return

            selected_chunks = select_diverse_chunks(
                chunks,
                limit=settings.fast_rag_top_k,
                per_document=(
                    settings.fast_rag_top_k
                    if scoped_document_id is not None
                    else settings.fast_rag_per_document_k
                ),
            )
            sources = build_citations(selected_chunks)
            log.info(
                "agent_stream selected sources | tenant=%s sources=%s selected_chunks=%d",
                tenant_id,
                [source.filename for source in sources],
                len(selected_chunks),
            )

            answer_parts: list[str] = []
            prompt_tokens = 0
            completion_tokens = 0
            first_token_logged = False
            messages = build_grounded_messages(
                user_query,
                sources,
                max_context_chars=settings.fast_rag_context_max_chars,
            )

            async for event in stream_chat_text(model_name, messages):
                if event.type == "usage":
                    prompt_tokens = event.prompt_tokens
                    completion_tokens = event.completion_tokens
                    continue
                if event.type != "token" or not event.content:
                    continue
                if not first_token_logged:
                    first_token_logged = True
                    log.info(
                        "agent_stream first token | tenant=%s model=%s latency_ms=%d",
                        tenant_id,
                        model_name,
                        int((time.monotonic() - request_t0) * 1000),
                    )
                answer_parts.append(event.content)
                yield f"data: {json.dumps({'type': 'token', 'content': event.content})}\n\n"

            answer = "".join(answer_parts).strip()
            answer_sources = select_answer_sources(answer, sources)
            output = AgentRunOutput(
                answer=answer or "Не удалось получить ответ от модели.",
                sources=answer_sources if answer else [],
                confidence=0.85 if answer_sources else 0.2 if answer else 0.0,
                cached=False,
            )
            latency_ms = int((time.monotonic() - request_t0) * 1000)

            yield (
                "data: "
                f"{json.dumps({'type': 'done', 'answer': output.answer, 'sources': _serialize_sources(output.sources), 'confidence': output.confidence, 'cached': False})}\n\n"
            )
            log.info(
                "agent_stream done | tenant=%s model=%s latency_ms=%d",
                tenant_id,
                model_name,
                latency_ms,
            )

            try:
                await record_usage(UsageEvent(
                    tenant_id=tenant_id,
                    workflow_id=f"stream-{uuid.uuid4().hex[:12]}",
                    run_id=f"stream-{uuid.uuid4().hex[:12]}",
                    model=model_name,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    latency_ms=latency_ms,
                ))
            except Exception:
                pass

            if not scoped:
                try:
                    await semantic_cache.set(user_query, tenant_id, output)
                except Exception:
                    pass

        except Exception as exc:
            log.exception("agent_stream error | tenant=%s", tenant_id)
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/agent/research", response_model=AgentRunOutput)
async def run_research(payload: MultiStepResearchInput, tenant_id: TenantID) -> AgentRunOutput:
    """Multi-step research: fan-out sub-queries as child workflows, then synthesise."""
    main_query = await _enforce_agent_limits(tenant_id, payload.main_query, "/agent/research")
    sub_queries = [_validate_agent_query(q) for q in payload.sub_queries]
    payload = payload.model_copy(update={
        "tenant_id": tenant_id,
        "main_query": main_query,
        "sub_queries": sub_queries,
    })
    client: Client = app.state.temporal
    workflow_id = f"research-{tenant_id}-{uuid.uuid4()}"
    try:
        return await client.execute_workflow(
            MultiStepResearchWorkflow.run,
            payload,
            id=workflow_id,
            task_queue=settings.temporal_task_queue,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


# ── HITL signals ──────────────────────────────────────────────────────────────

@app.get("/workflows/{workflow_id}/result", response_model=AgentRunApiResponse)
async def get_workflow_result(workflow_id: str, tenant_id: TenantID) -> AgentRunApiResponse:
    """Poll for HITL workflow result. Returns pending_approval=True while still waiting."""
    check_workflow_tenant(workflow_id, tenant_id)
    client: Client = app.state.temporal
    handle = client.get_workflow_handle(workflow_id)
    try:
        result: AgentRunOutput = await asyncio.wait_for(handle.result(), timeout=2.0)
        return AgentRunApiResponse(
            answer=result.answer,
            confidence=result.confidence,
            sources=result.sources,
            workflow_id=workflow_id,
        )
    except asyncio.TimeoutError:
        return AgentRunApiResponse(workflow_id=workflow_id, pending_approval=True)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/workflows/{workflow_id}/approve", response_model=WorkflowSignalResponse)
async def approve_workflow(workflow_id: str, tenant_id: TenantID) -> WorkflowSignalResponse:
    check_workflow_tenant(workflow_id, tenant_id)
    client: Client = app.state.temporal
    try:
        await client.get_workflow_handle(workflow_id).signal(AgentRunWorkflow.approve)
    except RPCError as e:
        code = 404 if "not found" in str(e).lower() else 503
        detail = "workflow not found" if code == 404 else "workflow service unavailable"
        raise HTTPException(status_code=code, detail=detail) from e
    return WorkflowSignalResponse(workflow_id=workflow_id, action="approved")


@app.post("/workflows/{workflow_id}/reject", response_model=WorkflowSignalResponse)
async def reject_workflow(workflow_id: str, tenant_id: TenantID) -> WorkflowSignalResponse:
    check_workflow_tenant(workflow_id, tenant_id)
    client: Client = app.state.temporal
    try:
        await client.get_workflow_handle(workflow_id).signal(AgentRunWorkflow.reject)
    except RPCError as e:
        code = 404 if "not found" in str(e).lower() else 503
        detail = "workflow not found" if code == 404 else "workflow service unavailable"
        raise HTTPException(status_code=code, detail=detail) from e
    return WorkflowSignalResponse(workflow_id=workflow_id, action="rejected")


# ── Analytics ─────────────────────────────────────────────────────────────────

# ── Documents ─────────────────────────────────────────────────────────────────

@app.get("/documents", response_model=list[DocumentResponse])
async def list_documents(tenant_id: TenantID) -> list[DocumentResponse]:
    async with tenant_session(tenant_id) as s:
        rows = (await s.execute(
            select(Document)
            .where(Document.tenant_id == tenant_id)
            .order_by(Document.created_at.desc())
        )).scalars().all()
    return [_document_response(doc) for doc in rows]


@app.post("/documents", response_model=DocumentResponse, status_code=202)
async def upload_document(
    request: Request,
    tenant_id: TenantID,
    file: UploadFile = File(...),
) -> DocumentResponse:
    # Early rejection before reading body (Content-Length may include multipart overhead,
    # so use a 2× guard here; exact byte-level check happens inside _read_with_limit).
    cl = request.headers.get("content-length")
    if cl and int(cl) > settings.max_upload_bytes * 2:
        raise HTTPException(status_code=413, detail=f"file exceeds {settings.max_upload_bytes // (1024 * 1024)} MB limit")

    data = await _read_with_limit(file, settings.max_upload_bytes)
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

    await _invalidate_semantic_cache(tenant_id, f"document-upload:{document_id}")

    client: Client = app.state.temporal
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
    return _document_response(doc)


@app.post("/documents/bulk", response_model=list[DocumentResponse], status_code=202)
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

    # Phase 1 — read and validate ALL files before starting any workflow.
    # This prevents partial state where some workflows fire but a later file fails validation.
    cl = request.headers.get("content-length")
    if cl and int(cl) > settings.max_upload_bytes * len(files) * 2:
        raise HTTPException(status_code=413, detail="request body too large")

    validated: list[tuple[UploadFile, bytes]] = []
    total_bytes = 0
    for file in files:
        try:
            data = await _read_with_limit(file, settings.max_upload_bytes)
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

    # Phase 2 — store objects + DB rows + start workflows only after full validation.
    client: Client = app.state.temporal
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
        await _invalidate_semantic_cache(tenant_id, f"document-upload:{document_id}")
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
        responses.append(_document_response(doc))

    return responses


@app.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(document_id: uuid.UUID, tenant_id: TenantID) -> DocumentResponse:
    async with tenant_session(tenant_id) as s:
        doc = (
            await s.execute(
                select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    return _document_response(doc)


@app.get("/documents/{document_id}/assets", response_model=list[DocumentAssetResponse])
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
    return [_document_asset_response(asset) for asset in assets]


@app.get("/documents/{document_id}/assets/{asset_id}/content")
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
    if asset is None or not asset.preview_object_key:
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


@app.get("/documents/{document_id}/chunks", response_model=list[DocumentChunkPreview])
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
            page=_metadata_page(chunk.chunk_metadata or {}),
            excerpt=_chunk_excerpt(chunk.content),
        )
        for chunk in chunks
    ]


@app.post("/documents/{document_id}/reindex", response_model=DocumentResponse, status_code=202)
async def reindex_document(document_id: uuid.UUID, tenant_id: TenantID) -> DocumentResponse:
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

        doc.status = DocumentStatus.pending
        doc.processing_stage = "queued"
        doc.processed_pages = 0
        doc.total_pages = 0
        doc.warnings = []
        doc.error = None
        await s.flush()
        response = _document_response(doc)
        ingestion_input = IngestionInput(
            document_id=str(document_id),
            tenant_id=tenant_id,
            object_key=doc.object_key,
            filename=doc.filename,
        )

    await _invalidate_semantic_cache(tenant_id, f"document-reindex:{document_id}")

    client: Client = app.state.temporal
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


@app.delete("/documents/{document_id}", status_code=204)
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

    for key in [object_key, *preview_object_keys]:
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
    await _invalidate_semantic_cache(tenant_id, f"document-delete:{document_id}")


# ── Notebooks ─────────────────────────────────────────────────────────────────

@app.get("/notebooks", response_model=list[NotebookResponse])
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
            documents = await _load_notebook_documents(s, tenant_id, notebook.id)
            responses.append(_notebook_response(notebook, documents))
    return responses


@app.post("/notebooks", response_model=NotebookResponse, status_code=201)
async def create_notebook(
    body: CreateNotebookRequest,
    tenant_id: TenantID,
) -> NotebookResponse:
    document_ids = _dedupe_uuid_list(body.document_ids)
    async with tenant_session(tenant_id) as s:
        documents = await _load_tenant_documents(s, tenant_id, document_ids)
        notebook = Notebook(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            title=_clean_notebook_title(body.title),
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
        response = _notebook_response(notebook, documents)
    return response


@app.get("/notebooks/{notebook_id}", response_model=NotebookResponse)
async def get_notebook(notebook_id: uuid.UUID, tenant_id: TenantID) -> NotebookResponse:
    async with tenant_session(tenant_id) as s:
        notebook = (
            await s.execute(
                select(Notebook).where(Notebook.id == notebook_id, Notebook.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if notebook is None:
            raise HTTPException(status_code=404, detail="notebook not found")
        documents = await _load_notebook_documents(s, tenant_id, notebook_id)
        response = _notebook_response(notebook, documents)
    return response


@app.put("/notebooks/{notebook_id}/documents", response_model=NotebookResponse)
async def replace_notebook_documents(
    notebook_id: uuid.UUID,
    body: UpdateNotebookDocumentsRequest,
    tenant_id: TenantID,
) -> NotebookResponse:
    document_ids = _dedupe_uuid_list(body.document_ids)
    async with tenant_session(tenant_id) as s:
        notebook = (
            await s.execute(
                select(Notebook).where(Notebook.id == notebook_id, Notebook.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if notebook is None:
            raise HTTPException(status_code=404, detail="notebook not found")
        documents = await _load_tenant_documents(s, tenant_id, document_ids)
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
        response = _notebook_response(notebook, documents)
    return response


@app.post("/notebooks/{notebook_id}/documents/upload", response_model=DocumentResponse, status_code=202)
async def upload_notebook_document(
    notebook_id: uuid.UUID,
    request: Request,
    tenant_id: TenantID,
    file: UploadFile = File(...),
) -> DocumentResponse:
    cl = request.headers.get("content-length")
    if cl and int(cl) > settings.max_upload_bytes * 2:
        raise HTTPException(status_code=413, detail=f"file exceeds {settings.max_upload_bytes // (1024 * 1024)} MB limit")

    data = await _read_with_limit(file, settings.max_upload_bytes)
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
        response = _document_response(doc)

    await _invalidate_semantic_cache(tenant_id, f"notebook-document-upload:{notebook_id}:{document_id}")

    client: Client = app.state.temporal
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


@app.post("/notebooks/{notebook_id}/insights", response_model=NotebookResponse)
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

        documents = await _load_notebook_documents(s, tenant_id, notebook_id)
        ready_documents = [doc for doc in documents if doc.status == DocumentStatus.done]
        if not ready_documents:
            raise HTTPException(status_code=409, detail="notebook has no indexed documents yet")

        title = notebook.title
        ready_document_ids = {doc.id for doc in ready_documents}
        insight_sources = await _load_notebook_insight_sources(
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

        documents = await _load_notebook_documents(s, tenant_id, notebook_id)
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
        response = _notebook_response(notebook, documents)
    return response


@app.delete("/notebooks/{notebook_id}", status_code=204)
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
