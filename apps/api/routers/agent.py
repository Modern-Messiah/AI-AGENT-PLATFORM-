from __future__ import annotations

import json
import logging
import time
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, select
from starlette.responses import StreamingResponse
from temporalio.client import Client

from packages.agents import AgentRunInput, AgentRunOutput, MultiStepResearchInput
from packages.analytics.events import UsageEvent, record_usage
from packages.cache.semantic import semantic_cache
from packages.core import settings
from packages.llm import stream_chat_text
from packages.rag import (
    CitationSource,
    build_citations,
    build_grounded_messages,
    normalize_citation_sources,
    retrieve_chunks,
    select_answer_sources,
    select_diverse_chunks,
)
from packages.storage import Chunk, Document, DocumentStatus, Notebook
from packages.storage.db import tenant_session

from apps.api.deps import TenantID
from apps.api.schemas import AgentRunApiResponse, AgentStreamRequest
from apps.api.serializers import serialize_sources
from apps.api.services.agent_limits import enforce_agent_limits, validate_agent_query
from apps.api.services.notebooks import load_notebook_documents
from apps.worker.workflows.agent_run import AgentRunWorkflow
from apps.worker.workflows.multi_step import MultiStepResearchWorkflow

log = logging.getLogger(__name__)
router = APIRouter()


@router.post("/agent/run", response_model=AgentRunApiResponse)
async def run_agent(
    payload: AgentRunInput,
    tenant_id: TenantID,
    request: Request,
) -> AgentRunApiResponse:
    """Single agent run. Set require_approval=true to pause for HITL review."""
    user_query = await enforce_agent_limits(tenant_id, payload.user_query, "/agent/run")
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
    client: Client = request.app.state.temporal
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
        sources = normalize_citation_sources(result.answer, result.sources)
        return AgentRunApiResponse(
            answer=result.answer,
            confidence=result.confidence,
            sources=sources,
            cached=result.cached,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/agent/stream")
async def agent_stream(body: AgentStreamRequest, tenant_id: TenantID) -> StreamingResponse:
    """SSE streaming agent — bypasses Temporal for interactive chat."""
    user_query = await enforce_agent_limits(tenant_id, body.user_query, "/agent/stream")
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
            notebook_documents = await load_notebook_documents(db, tenant_id, scoped_notebook_id)
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
            # Semantic cache - instant reply if hit. Scoped document requests skip it:
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
            cached_sources = serialize_sources(cached_sources)
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
                f"{json.dumps({'type': 'done', 'answer': output.answer, 'sources': serialize_sources(output.sources), 'confidence': output.confidence, 'cached': False})}\n\n"
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


@router.post("/agent/research", response_model=AgentRunApiResponse)
async def run_research(
    payload: MultiStepResearchInput,
    tenant_id: TenantID,
    request: Request,
) -> AgentRunOutput:
    """Multi-step research: fan-out sub-queries as child workflows, then synthesise."""
    main_query = await enforce_agent_limits(tenant_id, payload.main_query, "/agent/research")
    sub_queries = [validate_agent_query(q) for q in payload.sub_queries]
    payload = payload.model_copy(update={
        "tenant_id": tenant_id,
        "main_query": main_query,
        "sub_queries": sub_queries,
    })
    client: Client = request.app.state.temporal
    workflow_id = f"research-{tenant_id}-{uuid.uuid4()}"
    try:
        result: AgentRunOutput = await client.execute_workflow(
            MultiStepResearchWorkflow.run,
            payload,
            id=workflow_id,
            task_queue=settings.temporal_task_queue,
        )
        return AgentRunApiResponse(
            answer=result.answer,
            confidence=result.confidence,
            sources=normalize_citation_sources(result.answer, result.sources),
            cached=result.cached,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e
