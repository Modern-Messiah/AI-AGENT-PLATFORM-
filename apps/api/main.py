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
from typing import Annotated, AsyncIterator

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from packages.agents import (
    AgentRunInput,
    AgentRunOutput,
    MultiStepResearchInput,
    build_research_agent,
)
from packages.analytics.clickhouse import ch_client
from packages.analytics.events import UsageEvent, record_usage
from packages.auth import generate_key, require_tenant
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
    select_diverse_chunks,
)
from packages.rag.embedder import embed_texts
from packages.storage import (
    ApiKey,
    ChatMessage,
    ChatSession,
    Chunk,
    Document,
    DocumentStatus,
    Notebook,
    NotebookDocument,
    async_session,
    object_store,
)
from packages.storage.db import tenant_session
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, func, select, update
from starlette.responses import StreamingResponse
from temporalio.client import Client
from temporalio.service import RPCError

from apps.worker.activities.ingestion import IngestionInput
from apps.worker.workflows.agent_run import AgentRunWorkflow
from apps.worker.workflows.ingestion import IngestionWorkflow
from apps.worker.workflows.multi_step import MultiStepResearchWorkflow

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


async def _enforce_agent_limits(tenant_id: str, query: str, route: str) -> str:
    query = _validate_agent_query(query)
    limit = settings.agent_rate_limit_per_minute
    if limit <= 0:
        return query

    now = int(time.time())
    retry_after = 60 - (now % 60)
    key = f"rl:{tenant_id}:agent:{now // 60}"
    try:
        r = get_redis()
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, 70)
        if count > limit:
            raise HTTPException(
                status_code=429,
                detail=f"rate limit exceeded: {limit} agent requests per minute",
                headers={"Retry-After": str(retry_after)},
            )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("rate limit check failed open | tenant=%s route=%s error=%s", tenant_id, route, exc)
    return query

TenantID = Annotated[str, Depends(require_tenant)]

_READ_CHUNK = 64 * 1024  # 64 KB


async def _read_with_limit(file: UploadFile, max_bytes: int) -> bytes:
    """Read an upload in chunks; raise HTTP 413 as soon as limit is exceeded."""
    chunks: list[bytes] = []
    received = 0
    while True:
        chunk = await file.read(_READ_CHUNK)
        if not chunk:
            break
        received += len(chunk)
        if received > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"file exceeds {max_bytes // (1024 * 1024)} MB limit",
            )
        chunks.append(chunk)
    return b"".join(chunks)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ChatMessageSchema(BaseModel):
    id: str
    role: str
    content: str
    sources: list[str | CitationSource] = []
    cached: bool = False
    created_at: str


class ChatSessionSchema(BaseModel):
    id: str
    title: str
    model: str | None
    created_at: str
    updated_at: str
    message_count: int = 0


class CreateSessionRequest(BaseModel):
    title: str = "New Chat"
    model: str | None = None


class UpdateSessionRequest(BaseModel):
    title: str | None = None
    model: str | None = None


class AddMessageRequest(BaseModel):
    role: str
    content: str
    sources: list[str | CitationSource] = []
    cached: bool = False


class DocumentResponse(BaseModel):
    id: str
    tenant_id: str
    filename: str
    status: DocumentStatus
    size_bytes: int = 0
    summary: str | None = None
    suggested_questions: list[str] = Field(default_factory=list)
    error: str | None = None
    created_at: str | None = None


class DocumentChunkPreview(BaseModel):
    chunk_id: str
    chunk_index: int
    page: int | None = None
    excerpt: str


class CreateNotebookRequest(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=2000)
    document_ids: list[uuid.UUID] = Field(default_factory=list)


class UpdateNotebookDocumentsRequest(BaseModel):
    document_ids: list[uuid.UUID] = Field(default_factory=list)


class NotebookResponse(BaseModel):
    id: str
    tenant_id: str
    title: str
    description: str | None = None
    document_ids: list[str] = Field(default_factory=list)
    document_count: int = 0
    documents: list[DocumentResponse] = Field(default_factory=list)
    summary: str | None = None
    suggested_questions: list[str] = Field(default_factory=list)
    key_topics: list[str] = Field(default_factory=list)
    insights_updated_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class AgentRunApiResponse(BaseModel):
    answer: str = ""
    confidence: float = 0.0
    sources: list[str | CitationSource] = []
    cached: bool = False
    workflow_id: str | None = None
    pending_approval: bool = False


class WorkflowSignalResponse(BaseModel):
    workflow_id: str
    action: str


class CreateKeyRequest(BaseModel):
    tenant_id: str
    name: str | None = None


class CreateKeyResponse(BaseModel):
    id: str
    tenant_id: str
    name: str | None
    raw_key: str  # shown once — store it now


def _chat_session_response(sess: ChatSession, message_count: int = 0) -> ChatSessionSchema:
    return ChatSessionSchema(
        id=str(sess.id),
        title=sess.title,
        model=sess.model,
        created_at=sess.created_at.isoformat(),
        updated_at=sess.updated_at.isoformat(),
        message_count=message_count,
    )


def _chat_message_response(msg: ChatMessage) -> ChatMessageSchema:
    return ChatMessageSchema(
        id=str(msg.id),
        role=msg.role,
        content=msg.content,
        sources=msg.sources or [],
        cached=msg.cached,
        created_at=msg.created_at.isoformat(),
    )


def _document_response(doc: Document) -> DocumentResponse:
    return DocumentResponse(
        id=str(doc.id),
        tenant_id=doc.tenant_id,
        filename=doc.filename,
        status=doc.status,
        size_bytes=doc.size_bytes,
        summary=doc.summary,
        suggested_questions=doc.suggested_questions or [],
        error=doc.error,
        created_at=doc.created_at.isoformat() if doc.created_at else None,
    )


def _dedupe_uuid_list(ids: list[uuid.UUID]) -> list[uuid.UUID]:
    seen: set[uuid.UUID] = set()
    deduped: list[uuid.UUID] = []
    for item in ids:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _notebook_response(
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
        documents=[_document_response(doc) for doc in docs],
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


def _metadata_page(metadata: dict[str, object]) -> int | None:
    page = metadata.get("page")
    if isinstance(page, bool) or page is None:
        return None
    try:
        parsed = int(page)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _chunk_excerpt(content: str, max_chars: int = 520) -> str:
    excerpt = re.sub(r"\s+", " ", content).strip()
    if len(excerpt) <= max_chars:
        return excerpt
    return f"{excerpt[:max_chars].rstrip()}…"


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


# ── Public ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# ── Auth management ───────────────────────────────────────────────────────────

@app.post("/auth/keys", response_model=CreateKeyResponse, status_code=201)
async def create_api_key(
    body: CreateKeyRequest,
    x_admin_secret: str = Header(..., alias="X-Admin-Secret"),
) -> CreateKeyResponse:
    """Create an API key for a tenant. Protected by X-Admin-Secret header."""
    if x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="invalid admin secret")

    raw_key, key_hash = generate_key()
    key_id = uuid.uuid4()

    async with async_session() as s, s.begin():
        s.add(ApiKey(
            id=key_id,
            tenant_id=body.tenant_id,
            key_hash=key_hash,
            name=body.name,
        ))

    return CreateKeyResponse(
        id=str(key_id),
        tenant_id=body.tenant_id,
        name=body.name,
        raw_key=raw_key,
    )


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


class AgentStreamRequest(BaseModel):
    user_query: str
    model: str | None = None
    document_id: uuid.UUID | None = None
    notebook_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def validate_single_scope(self) -> AgentStreamRequest:
        if self.document_id is not None and self.notebook_id is not None:
            raise ValueError("document_id and notebook_id cannot be used together")
        return self


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
            cached_sources = _serialize_sources(cached.sources)
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
            output = AgentRunOutput(
                answer=answer or "Не удалось получить ответ от модели.",
                sources=sources if answer else [],
                confidence=0.85 if answer else 0.0,
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

@app.get("/analytics/usage")
async def get_usage(
    tenant_id: TenantID,
    days: int = Query(default=30, ge=1, le=365),
) -> dict:
    """Aggregate LLM cost and token usage for the authenticated tenant over N days."""
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
    daily_sql = """
        SELECT
            toDate(event_time)       AS day,
            sum(total_tokens)        AS total_tokens,
            round(sum(cost_usd), 6)  AS total_cost_usd,
            round(avg(latency_ms))   AS avg_latency_ms,
            count()                  AS call_count
        FROM analytics.llm_usage_events
        WHERE tenant_id = {tenant_id:String}
          AND event_time >= now() - toIntervalDay({days:UInt32})
        GROUP BY day
        ORDER BY day ASC
    """
    try:
        rows = await ch_client.query(sql, {"tenant_id": tenant_id, "days": days})
        daily_rows = await ch_client.query(daily_sql, {"tenant_id": tenant_id, "days": days})
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"ClickHouse error: {e}") from e

    total_cost = sum(r.get("total_cost_usd") or 0 for r in rows)
    return {
        "tenant_id": tenant_id,
        "days": days,
        "total_cost_usd": round(total_cost, 6),
        "breakdown": rows,
        "daily": daily_rows,
    }


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
    async with tenant_session(tenant_id) as s:
        doc = (
            await s.execute(
                select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if doc is None:
            raise HTTPException(status_code=404, detail="document not found")
        object_key = doc.object_key
        await s.delete(doc)  # CASCADE deletes chunks via FK ondelete="CASCADE"

    try:
        object_store.delete(object_key)
    except Exception as exc:
        log.warning(
            "object deletion failed | tenant=%s document=%s key=%s error=%s",
            tenant_id,
            document_id,
            object_key,
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


# ── Chat sessions ─────────────────────────────────────────────────────────────

@app.get("/sessions", response_model=list[ChatSessionSchema])
async def list_sessions(tenant_id: TenantID) -> list[ChatSessionSchema]:
    msg_count_sq = (
        select(func.count())
        .select_from(ChatMessage)
        .where(ChatMessage.session_id == ChatSession.id)
        .correlate(ChatSession)
        .scalar_subquery()
    )
    async with tenant_session(tenant_id) as s:
        rows = (await s.execute(
            select(ChatSession, msg_count_sq.label("cnt"))
            .where(ChatSession.tenant_id == tenant_id)
            .order_by(ChatSession.updated_at.desc())
        )).all()
    return [
        ChatSessionSchema(
            id=str(sess.id),
            title=sess.title,
            model=sess.model,
            created_at=sess.created_at.isoformat(),
            updated_at=sess.updated_at.isoformat(),
            message_count=cnt,
        )
        for sess, cnt in rows
    ]


@app.post("/sessions", response_model=ChatSessionSchema, status_code=201)
async def create_session(body: CreateSessionRequest, tenant_id: TenantID) -> ChatSessionSchema:
    async with tenant_session(tenant_id) as s:
        sess = ChatSession(tenant_id=tenant_id, title=body.title, model=body.model)
        s.add(sess)
        await s.flush()
        await s.refresh(sess)
        return _chat_session_response(sess)


@app.patch("/sessions/{session_id}", response_model=ChatSessionSchema)
async def update_session(session_id: uuid.UUID, body: UpdateSessionRequest, tenant_id: TenantID) -> ChatSessionSchema:
    async with tenant_session(tenant_id) as s:
        sess = (await s.execute(
            select(ChatSession).where(ChatSession.id == session_id, ChatSession.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if sess is None:
            raise HTTPException(status_code=404, detail="session not found")
        if body.title is not None:
            sess.title = body.title
        if body.model is not None:
            sess.model = body.model
        await s.flush()
        await s.refresh(sess)
        return _chat_session_response(sess)


@app.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: uuid.UUID, tenant_id: TenantID) -> None:
    async with tenant_session(tenant_id) as s:
        sess = (await s.execute(
            select(ChatSession).where(ChatSession.id == session_id, ChatSession.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if sess is None:
            raise HTTPException(status_code=404, detail="session not found")
        await s.delete(sess)


@app.get("/sessions/{session_id}/messages", response_model=list[ChatMessageSchema])
async def get_messages(session_id: uuid.UUID, tenant_id: TenantID) -> list[ChatMessageSchema]:
    async with tenant_session(tenant_id) as s:
        msgs = (await s.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id, ChatMessage.tenant_id == tenant_id)
            .order_by(ChatMessage.created_at)
        )).scalars().all()
    return [_chat_message_response(m) for m in msgs]


@app.post("/sessions/{session_id}/messages", response_model=ChatMessageSchema, status_code=201)
async def add_message(session_id: uuid.UUID, body: AddMessageRequest, tenant_id: TenantID) -> ChatMessageSchema:
    async with tenant_session(tenant_id) as s:
        sess = (await s.execute(
            select(ChatSession).where(ChatSession.id == session_id, ChatSession.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if sess is None:
            raise HTTPException(status_code=404, detail="session not found")
        sess.updated_at = datetime.now(timezone.utc)
        msg = ChatMessage(
            session_id=session_id, tenant_id=tenant_id,
            role=body.role, content=body.content,
            sources=_serialize_sources(body.sources), cached=body.cached,
        )
        s.add(msg)
        await s.flush()
        await s.refresh(msg)
        return _chat_message_response(msg)
