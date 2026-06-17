from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from packages.storage import ChatMessage, ChatSession
from packages.storage.db import tenant_session

from apps.api.deps import TenantID
from apps.api.schemas import (
    AddMessageRequest,
    ChatMessageSchema,
    ChatSessionSchema,
    CreateSessionRequest,
    UpdateSessionRequest,
)
from apps.api.serializers import (
    chat_message_response,
    chat_session_response,
    serialize_sources,
)

router = APIRouter()


@router.get("/sessions", response_model=list[ChatSessionSchema])
async def list_sessions(
    tenant_id: TenantID,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[ChatSessionSchema]:
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
            .limit(limit)
            .offset(offset)
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


@router.post("/sessions", response_model=ChatSessionSchema, status_code=201)
async def create_session(body: CreateSessionRequest, tenant_id: TenantID) -> ChatSessionSchema:
    async with tenant_session(tenant_id) as s:
        sess = ChatSession(tenant_id=tenant_id, title=body.title, model=body.model)
        s.add(sess)
        await s.flush()
        await s.refresh(sess)
        return chat_session_response(sess)


@router.patch("/sessions/{session_id}", response_model=ChatSessionSchema)
async def update_session(
    session_id: uuid.UUID,
    body: UpdateSessionRequest,
    tenant_id: TenantID,
) -> ChatSessionSchema:
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
        return chat_session_response(sess)


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: uuid.UUID, tenant_id: TenantID) -> None:
    async with tenant_session(tenant_id) as s:
        sess = (await s.execute(
            select(ChatSession).where(ChatSession.id == session_id, ChatSession.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if sess is None:
            raise HTTPException(status_code=404, detail="session not found")
        await s.delete(sess)


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageSchema])
async def get_messages(session_id: uuid.UUID, tenant_id: TenantID) -> list[ChatMessageSchema]:
    async with tenant_session(tenant_id) as s:
        msgs = (await s.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id, ChatMessage.tenant_id == tenant_id)
            .order_by(ChatMessage.created_at)
        )).scalars().all()
    return [chat_message_response(m) for m in msgs]


@router.post("/sessions/{session_id}/messages", response_model=ChatMessageSchema, status_code=201)
async def add_message(
    session_id: uuid.UUID,
    body: AddMessageRequest,
    tenant_id: TenantID,
) -> ChatMessageSchema:
    async with tenant_session(tenant_id) as s:
        sess = (await s.execute(
            select(ChatSession).where(ChatSession.id == session_id, ChatSession.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if sess is None:
            raise HTTPException(status_code=404, detail="session not found")
        sess.updated_at = datetime.now(timezone.utc)
        msg = ChatMessage(
            session_id=session_id,
            tenant_id=tenant_id,
            role=body.role,
            content=body.content,
            sources=serialize_sources(body.sources),
            cached=body.cached,
        )
        s.add(msg)
        await s.flush()
        await s.refresh(msg)
        return chat_message_response(msg)
