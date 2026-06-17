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
from functools import lru_cache
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
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
from packages.llm import stream_chat_text
from packages.observability import setup_tracing
from packages.rag import (
    CitationSource,
    build_citations,
    build_grounded_messages,
    retrieve_chunks,
    select_answer_sources,
    select_diverse_chunks,
)
from packages.rag.embedder import embed_texts
from packages.storage import (
    Chunk,
    Document,
    DocumentStatus,
    Notebook,
)
from packages.storage.db import tenant_session
from sqlalchemy import func, select
from starlette.responses import StreamingResponse
from temporalio.client import Client

from apps.api.deps import TenantID
from apps.api.routers import (
    analytics_router,
    auth_router,
    documents_router,
    health_router,
    notebooks_router,
    sessions_router,
    workflows_router,
)
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
    document_response,
    notebook_response,
    serialize_sources,
)
from apps.api.services.notebooks import (
    clean_notebook_title,
    dedupe_uuid_list,
    load_notebook_documents,
    load_notebook_insight_sources,
    load_tenant_documents,
)
from apps.worker.workflows.agent_run import AgentRunWorkflow
from apps.worker.workflows.multi_step import MultiStepResearchWorkflow

# Backward-compatible names imported by existing tests and scripts.
_document_response = document_response
_notebook_response = notebook_response
_clean_notebook_title = clean_notebook_title
_dedupe_uuid_list = dedupe_uuid_list
_load_notebook_documents = load_notebook_documents
_load_notebook_insight_sources = load_notebook_insight_sources
_load_tenant_documents = load_tenant_documents
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
app.include_router(documents_router)
app.include_router(notebooks_router)
app.include_router(sessions_router)
app.include_router(workflows_router)


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
