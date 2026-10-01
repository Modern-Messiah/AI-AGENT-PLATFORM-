from __future__ import annotations

import contextlib
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from packages.agents import AgentRunInput, AgentRunOutput, MultiStepResearchInput
from packages.analytics.events import UsageEvent, record_usage
from packages.auth import Actor
from packages.cache.semantic import semantic_cache
from packages.core import settings
from packages.llm import stream_chat_text
from packages.rag import (
    CitationSource,
    build_citations,
    build_grounded_messages,
    calibrate_confidence,
    normalize_citation_sources,
    retrieve_chunks_with_expansion,
    select_answer_sources,
    select_diverse_chunks,
    verify_answer_faithfulness,
)
from packages.storage import ChatMessage, ChatSession, Document, DocumentStatus, Notebook
from packages.storage.db import tenant_session
from sqlalchemy import select
from starlette.responses import StreamingResponse
from temporalio.client import Client

from apps.api.deps import ActorDep
from apps.api.schemas import AgentRunApiResponse, AgentStreamRequest
from apps.api.serializers import serialize_sources
from apps.api.services.access import accessible_document_ids, can_access
from apps.api.services.agent_limits import enforce_agent_limits, validate_agent_query
from apps.api.services.notebooks import load_notebook_documents
from apps.api.services.query_condensation import condense_query
from apps.api.services.query_log import QueryLogEntry, log_agent_query
from apps.worker.workflows.agent_run import AgentRunWorkflow
from apps.worker.workflows.multi_step import MultiStepResearchWorkflow

log = logging.getLogger(__name__)
router = APIRouter()


@router.post("/agent/run", response_model=AgentRunApiResponse)
async def run_agent(
    payload: AgentRunInput,
    actor: ActorDep,
    request: Request,
) -> AgentRunApiResponse:
    """Single agent run. Set require_approval=true to pause for HITL review."""
    tenant_id = actor.tenant_id
    user_query = await enforce_agent_limits(tenant_id, payload.user_query, "/agent/run")
    payload = payload.model_copy(update={"user_query": user_query})
    model_name = resolve_chat_model(actor, payload.model)

    # Personal knowledge base: the run may only retrieve documents the acting
    # user can access (own + shared). Unbound tenant keys search everything.
    async with tenant_session(tenant_id) as db:
        accessible_ids = await accessible_document_ids(db, tenant_id, actor)
    if accessible_ids is not None and not accessible_ids:
        answer = (
            "У вас ещё нет доступных проиндексированных документов. "
            "Перейдите в раздел «Документы», загрузите файлы — "
            "после индексации я смогу отвечать на вопросы по ним."
        )
        await log_agent_query(
            QueryLogEntry(
                tenant_id=tenant_id,
                user_id=actor.user_id,
                user_name=actor.user_name,
                api_key_id=actor.api_key_id,
                api_key_name=actor.api_key_name,
                mode="run",
                model=model_name,
                query=user_query,
                answer=answer,
                confidence=1.0,
            )
        )
        return AgentRunApiResponse(answer=answer, confidence=1.0)

    payload = payload.model_copy(
        update={
            "tenant_id": tenant_id,
            "user_id": str(actor.user_id) if actor.user_id else "",
            "document_ids": [str(doc_id) for doc_id in accessible_ids or []],
        }
    )
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
        except Exception as e:
            await log_agent_query(
                QueryLogEntry(
                    tenant_id=tenant_id,
                    user_id=actor.user_id,
                    user_name=actor.user_name,
                    api_key_id=actor.api_key_id,
                    api_key_name=actor.api_key_name,
                    mode="run",
                    model=model_name,
                    query=user_query,
                    status="error",
                    error=str(e),
                    workflow_id=workflow_id,
                )
            )
            # Workflow startup errors carry Temporal gRPC internals — keep the
            # detail in the query log, return a generic message to the client.
            raise HTTPException(status_code=500, detail="agent run failed") from e
        await log_agent_query(
            QueryLogEntry(
                tenant_id=tenant_id,
                user_id=actor.user_id,
                user_name=actor.user_name,
                api_key_id=actor.api_key_id,
                api_key_name=actor.api_key_name,
                mode="run",
                model=model_name,
                query=user_query,
                status="pending",
                workflow_id=workflow_id,
            )
        )
        return AgentRunApiResponse(workflow_id=workflow_id, pending_approval=True)

    try:
        result: AgentRunOutput = await client.execute_workflow(
            AgentRunWorkflow.run,
            payload,
            id=workflow_id,
            task_queue=settings.temporal_task_queue,
        )
        sources = normalize_citation_sources(result.answer, result.sources)
        await log_agent_query(
            QueryLogEntry(
                tenant_id=tenant_id,
                user_id=actor.user_id,
                user_name=actor.user_name,
                api_key_id=actor.api_key_id,
                api_key_name=actor.api_key_name,
                mode="run",
                model=model_name,
                query=user_query,
                answer=result.answer,
                confidence=result.confidence,
                sources_count=len(sources),
                cached=result.cached,
                workflow_id=workflow_id,
            )
        )
        return AgentRunApiResponse(
            answer=result.answer,
            confidence=result.confidence,
            sources=sources,
            cached=result.cached,
        )
    except Exception as e:
        await log_agent_query(
            QueryLogEntry(
                tenant_id=tenant_id,
                user_id=actor.user_id,
                user_name=actor.user_name,
                api_key_id=actor.api_key_id,
                api_key_name=actor.api_key_name,
                mode="run",
                model=model_name,
                query=user_query,
                status="error",
                error=str(e),
                workflow_id=workflow_id,
            )
        )
        raise HTTPException(status_code=500, detail="agent run failed") from e


def resolve_chat_model(actor: Actor, requested: str | None) -> str:
    """Admins may pick any model; members are pinned to the default one."""
    if actor.is_admin and requested:
        return requested
    return settings.strong_model


@router.post("/agent/stream")
async def agent_stream(body: AgentStreamRequest, actor: ActorDep) -> StreamingResponse:
    """SSE streaming agent — bypasses Temporal for interactive chat."""
    tenant_id = actor.tenant_id
    user_query = await enforce_agent_limits(tenant_id, body.user_query, "/agent/stream")
    model_name = resolve_chat_model(actor, body.model)
    scoped_document_id = body.document_id
    scoped_notebook_id = body.notebook_id
    scoped_document_ids: list[uuid.UUID] | None = None
    # Cached answers are private per user: a member's answer over their
    # personal documents must never surface for a colleague.
    cache_scope = f"user:{actor.user_id}" if actor.user_id else "tenant"

    # Conversation memory: load recent turns of the session (when the client
    # sent one) and rewrite follow-ups into a standalone retrieval query.
    history: list[tuple[str, str]] = []
    if body.session_id is not None:
        async with tenant_session(tenant_id) as db:
            session = (
                await db.execute(
                    select(ChatSession).where(
                        ChatSession.id == body.session_id,
                        ChatSession.tenant_id == tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if session is None or (
                session.user_id is not None
                and actor.user_id is not None
                and session.user_id != actor.user_id
            ):
                raise HTTPException(status_code=404, detail="session not found")
            rows = (
                (
                    await db.execute(
                        select(ChatMessage)
                        .where(
                            ChatMessage.session_id == session.id,
                            ChatMessage.tenant_id == tenant_id,
                            ChatMessage.role.in_(["user", "agent"]),
                        )
                        .order_by(ChatMessage.created_at.desc())
                        .limit(settings.chat_history_messages)
                    )
                )
                .scalars()
                .all()
            )
        history = [(msg.role, msg.content) for msg in reversed(rows)]
    retrieval_query = await condense_query(history, user_query)

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
        if doc is None or not can_access(actor, doc):
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
            if notebook is None or not can_access(actor, notebook):
                raise HTTPException(status_code=404, detail="notebook not found")
            notebook_documents = await load_notebook_documents(
                db, tenant_id, scoped_notebook_id, actor
            )
        if not notebook_documents:
            raise HTTPException(status_code=409, detail="notebook has no documents")
        scoped_document_ids = [
            doc.id for doc in notebook_documents if doc.status == DocumentStatus.done
        ]
        if not scoped_document_ids:
            raise HTTPException(status_code=409, detail="notebook has no indexed documents yet")

    # Personal knowledge base: without an explicit scope, retrieval is limited
    # to the acting user's documents plus shared ones. None = unbound tenant
    # key = whole tenant corpus (empty list must NOT reach the retriever: it
    # treats an empty document_ids as "no filter").
    accessible_ids: list[uuid.UUID] | None = None
    no_accessible_documents = False
    if scoped_document_id is None and scoped_notebook_id is None:
        async with tenant_session(tenant_id) as db:
            accessible_ids = await accessible_document_ids(db, tenant_id, actor)
        no_accessible_documents = accessible_ids is not None and not accessible_ids

    async def generate() -> AsyncIterator[str]:
        request_t0 = time.monotonic()
        scoped = scoped_document_id is not None or scoped_notebook_id is not None
        scope_type = (
            "document"
            if scoped_document_id is not None
            else "notebook"
            if scoped_notebook_id is not None
            else None
        )
        scope_ref = scoped_document_id if scoped_document_id is not None else scoped_notebook_id

        def log_entry(
            answer: str = "",
            confidence: float | None = None,
            cached_hit: bool = False,
            sources_count: int = 0,
            prompt_tokens: int = 0,
            completion_tokens: int = 0,
            status: str = "ok",
            error: str | None = None,
        ) -> QueryLogEntry:
            return QueryLogEntry(
                tenant_id=tenant_id,
                user_id=actor.user_id,
                user_name=actor.user_name,
                api_key_id=actor.api_key_id,
                api_key_name=actor.api_key_name,
                mode="stream",
                model=model_name,
                query=user_query,
                session_id=body.session_id,
                scope_type=scope_type,
                scope_ref=scope_ref,
                retrieval_query=retrieval_query,
                answer=answer,
                status=status,
                error=error,
                latency_ms=int((time.monotonic() - request_t0) * 1000),
                cached=cached_hit,
                confidence=confidence,
                sources_count=sources_count,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )

        if no_accessible_documents:
            answer = (
                "У вас ещё нет доступных проиндексированных документов. "
                "Перейдите в раздел «Документы», загрузите файлы — "
                "после индексации я смогу отвечать на вопросы по ним."
            )
            yield f"data: {json.dumps({'type': 'token', 'content': answer})}\n\n"
            yield (
                "data: "
                f"{json.dumps({'type': 'done', 'answer': answer, 'sources': [], 'confidence': 1.0, 'cached': False})}\n\n"
            )
            await log_agent_query(log_entry(answer=answer, confidence=1.0))
            return

        cached = None
        if not scoped:
            cache_t0 = time.monotonic()
            # Semantic cache - instant reply if hit. Scoped document requests skip it:
            # the same wording can mean different things inside different files.
            try:
                cached = await semantic_cache.get(retrieval_query, tenant_id, scope=cache_scope)
            except Exception:
                cached = None
            log.info(
                "agent_stream cache lookup | tenant=%s hit=%s latency_ms=%d",
                tenant_id,
                cached is not None,
                int((time.monotonic() - cache_t0) * 1000),
            )

        if cached is not None:
            yield f"data: {json.dumps({'type': 'stage', 'stage': 'cache', 'elapsed_ms': int((time.monotonic() - request_t0) * 1000)})}\n\n"
            structured = [source for source in cached.sources if isinstance(source, CitationSource)]
            answer_sources: list[str | CitationSource] = list(cached.sources)
            if len(structured) == len(cached.sources):
                answer_sources = list(select_answer_sources(cached.answer, structured))
            cached_sources = serialize_sources(answer_sources)
            yield f"data: {json.dumps({'type': 'token', 'content': cached.answer})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'answer': cached.answer, 'sources': cached_sources, 'confidence': cached.confidence, 'cached': True})}\n\n"
            await log_agent_query(
                log_entry(
                    answer=cached.answer,
                    confidence=cached.confidence,
                    cached_hit=True,
                    sources_count=len(answer_sources),
                )
            )
            return

        try:

            def stage(name: str) -> str:
                return f"data: {json.dumps({'type': 'stage', 'stage': name, 'elapsed_ms': int((time.monotonic() - request_t0) * 1000)})}\n\n"

            retrieve_t0 = time.monotonic()
            yield stage("retrieval")
            chunks = await retrieve_chunks_with_expansion(
                retrieval_query,
                tenant_id,
                k=settings.fast_rag_candidate_k,
                max_distance=settings.retrieval_max_distance,
                document_id=scoped_document_id,
                # Unscoped chat searches the actor's personal + shared corpus
                # (accessible_ids is None only for unbound tenant keys).
                document_ids=scoped_document_ids
                if scoped_document_ids is not None
                else accessible_ids,
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
                await log_agent_query(log_entry(answer=answer, confidence=0.2))
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
                history=history,
            )

            yield stage("generation")
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
            structured_sources = select_answer_sources(answer, sources)
            yield stage("verification")
            verdict = await verify_answer_faithfulness(answer, structured_sources)
            if answer and verdict.unsupported_sentences and not verdict.supported_sentences:
                # Nothing in the answer is grounded — refuse instead of
                # streaming an invention through.
                answer = (
                    "Не удалось подтвердить ответ источниками — информация "
                    "в базе знаний отсутствует или противоречива."
                )
                structured_sources = []
            output = AgentRunOutput(
                answer=answer or "Не удалось получить ответ от модели.",
                sources=structured_sources if answer else [],
                confidence=calibrate_confidence(
                    selected_chunks, structured_sources, answer, verdict=verdict
                ),
                cached=False,
            )
            latency_ms = int((time.monotonic() - request_t0) * 1000)

            yield (
                "data: "
                f"{json.dumps({'type': 'done', 'answer': output.answer, 'sources': serialize_sources(output.sources), 'confidence': output.confidence, 'cached': False, 'verified': verdict.verified, 'unsupported_count': len(verdict.unsupported_sentences)})}\n\n"
            )
            log.info(
                "agent_stream done | tenant=%s model=%s latency_ms=%d",
                tenant_id,
                model_name,
                latency_ms,
            )

            with contextlib.suppress(Exception):
                await record_usage(
                    UsageEvent(
                        tenant_id=tenant_id,
                        user_id=str(actor.user_id) if actor.user_id else "",
                        workflow_id=f"stream-{uuid.uuid4().hex[:12]}",
                        run_id=f"stream-{uuid.uuid4().hex[:12]}",
                        model=model_name,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        latency_ms=latency_ms,
                    )
                )

            await log_agent_query(
                log_entry(
                    answer=output.answer,
                    confidence=output.confidence,
                    sources_count=len(output.sources),
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
            )

            if not scoped:
                with contextlib.suppress(Exception):
                    await semantic_cache.set(retrieval_query, tenant_id, output, scope=cache_scope)

        except Exception as exc:
            log.exception("agent_stream error | tenant=%s", tenant_id)
            # Provider/worker error bodies may carry internals — the full text
            # is logged above and in the query log; the SSE client gets a
            # generic message.
            yield f"data: {json.dumps({'type': 'error', 'message': 'agent run failed'})}\n\n"
            await log_agent_query(log_entry(status="error", error=str(exc)))

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
    actor: ActorDep,
    request: Request,
) -> AgentRunApiResponse:
    """Multi-step research: fan-out sub-queries as child workflows, then synthesise."""
    tenant_id = actor.tenant_id
    main_query = await enforce_agent_limits(tenant_id, payload.main_query, "/agent/research")
    sub_queries = [validate_agent_query(q) for q in payload.sub_queries]
    async with tenant_session(tenant_id) as db:
        research_accessible_ids = await accessible_document_ids(db, tenant_id, actor)
    payload = payload.model_copy(
        update={
            "tenant_id": tenant_id,
            "user_id": str(actor.user_id) if actor.user_id else "",
            "main_query": main_query,
            "sub_queries": sub_queries,
            "document_ids": [str(doc_id) for doc_id in research_accessible_ids or []],
        }
    )
    model_name = resolve_chat_model(actor, payload.model)
    client: Client = request.app.state.temporal
    workflow_id = f"research-{tenant_id}-{uuid.uuid4()}"
    try:
        result: AgentRunOutput = await client.execute_workflow(
            MultiStepResearchWorkflow.run,
            payload,
            id=workflow_id,
            task_queue=settings.temporal_task_queue,
        )
        sources = normalize_citation_sources(result.answer, result.sources)
        await log_agent_query(
            QueryLogEntry(
                tenant_id=tenant_id,
                user_id=actor.user_id,
                user_name=actor.user_name,
                api_key_id=actor.api_key_id,
                api_key_name=actor.api_key_name,
                mode="research",
                model=model_name,
                query=main_query,
                answer=result.answer,
                confidence=result.confidence,
                sources_count=len(sources),
                cached=result.cached,
                workflow_id=workflow_id,
            )
        )
        return AgentRunApiResponse(
            answer=result.answer,
            confidence=result.confidence,
            sources=sources,
            cached=result.cached,
        )
    except Exception as e:
        await log_agent_query(
            QueryLogEntry(
                tenant_id=tenant_id,
                user_id=actor.user_id,
                user_name=actor.user_name,
                api_key_id=actor.api_key_id,
                api_key_name=actor.api_key_name,
                mode="research",
                model=model_name,
                query=main_query,
                status="error",
                error=str(e),
                workflow_id=workflow_id,
            )
        )
        raise HTTPException(status_code=500, detail="research run failed") from e
