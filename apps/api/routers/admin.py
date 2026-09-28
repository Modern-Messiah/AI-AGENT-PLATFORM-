"""Admin panel API — cross-tenant monitoring behind X-Admin-Secret.

Read-only surface over the whole deployment: overview counters, per-tenant
and per-user activity, the agent query log (who asked what, with answers),
cross-tenant document health (failed ingestions) and cross-tenant LLM usage
from ClickHouse. Reads go through admin_session(), whose session-local
app.admin_read flag enables the FOR SELECT RLS policies (migration 0019).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from packages.analytics.clickhouse import ch_client
from packages.core import settings
from packages.storage import (
    AgentQueryLog,
    ApiKey,
    ChatMessage,
    ChatSession,
    Chunk,
    Document,
    DocumentStatus,
    Notebook,
    User,
)
from packages.storage.db import admin_session
from sqlalchemy import TextClause, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.routers.health import _CHECK_NAMES, _run_check
from apps.api.schemas import (
    AdminDailyQueries,
    AdminDocumentCounts,
    AdminDocumentListItem,
    AdminDocumentListResponse,
    AdminHealthResponse,
    AdminKeyInfo,
    AdminOverviewResponse,
    AdminPromptDetail,
    AdminPromptListItem,
    AdminPromptListResponse,
    AdminQueryCounts,
    AdminTenantSummary,
    AdminUsageByModel,
    AdminUsageByTenant,
    AdminUsageDaily,
    AdminUsageResponse,
    AdminUsageTotals,
    AdminUserInfo,
)

router = APIRouter()

_OVERVIEW_DAILY_DAYS = 14
_ANSWER_PREVIEW_CHARS = 240
_MAX_TENANTS = 500
_MAX_USERS = 500


def _require_admin(x_admin_secret: str) -> None:
    if x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="invalid admin secret")


def _scalar(value: Any) -> int:
    return int(value or 0)


def _ch_str(row: dict[str, object], key: str) -> str:
    value = row.get(key)
    return str(value) if value is not None else ""


def _ch_float(row: dict[str, object], key: str) -> float:
    value: Any = row.get(key)
    return float(value) if value is not None else 0.0


def _ch_int(row: dict[str, object], key: str) -> int:
    value: Any = row.get(key)
    return int(value) if value is not None else 0


def _status_name(value: Any) -> str:
    return value.value if isinstance(value, DocumentStatus) else str(value)


# ── Overview ──────────────────────────────────────────────────────────────────


@router.get("/admin/overview", response_model=AdminOverviewResponse)
async def admin_overview(
    x_admin_secret: str = Header(..., alias="X-Admin-Secret"),
) -> AdminOverviewResponse:
    """Deployment-wide counters plus the last two weeks of query activity."""
    _require_admin(x_admin_secret)

    async with admin_session() as db:
        tenants = _scalar(
            (
                await db.execute(
                    text(
                        "SELECT count(*) FROM ("
                        " SELECT DISTINCT tenant_id FROM api_keys"
                        " UNION SELECT DISTINCT tenant_id FROM users"
                        " UNION SELECT DISTINCT tenant_id FROM documents) t"
                    )
                )
            ).scalar()
        )
        users = _scalar((await db.execute(select(func.count()).select_from(User))).scalar())
        active_keys = _scalar(
            (
                await db.execute(
                    select(func.count()).select_from(ApiKey).where(ApiKey.is_active.is_(True))
                )
            ).scalar()
        )
        chunks = _scalar((await db.execute(select(func.count()).select_from(Chunk))).scalar())
        notebooks = _scalar((await db.execute(select(func.count()).select_from(Notebook))).scalar())
        sessions = _scalar(
            (await db.execute(select(func.count()).select_from(ChatSession))).scalar()
        )
        messages = _scalar(
            (await db.execute(select(func.count()).select_from(ChatMessage))).scalar()
        )

        status_rows = (
            await db.execute(select(Document.status, func.count()).group_by(Document.status))
        ).all()
        by_status = {_status_name(row[0]): int(row[1]) for row in status_rows}
        documents = AdminDocumentCounts(
            total=sum(by_status.values()),
            done=by_status.get("done", 0),
            processing=by_status.get("processing", 0),
            failed=by_status.get("failed", 0),
            pending=by_status.get("pending", 0),
        )

        queries_row = (
            await db.execute(
                text(
                    "SELECT count(*),"
                    " count(*) FILTER (WHERE created_at >= current_date),"
                    " count(*) FILTER (WHERE status = 'error')"
                    " FROM agent_query_logs"
                )
            )
        ).one()
        queries = AdminQueryCounts(
            total=int(queries_row[0]),
            today=int(queries_row[1]),
            errors=int(queries_row[2]),
        )

        daily_rows = (
            await db.execute(
                text(
                    "SELECT to_char(d::date, 'YYYY-MM-DD') AS day,"
                    " count(l.id) AS count,"
                    " count(l.id) FILTER (WHERE l.status = 'error') AS errors"
                    " FROM generate_series("
                    " current_date - (CAST(:days AS int) - 1), current_date,"
                    " interval '1 day') d"
                    " LEFT JOIN agent_query_logs l ON l.created_at::date = d::date"
                    " GROUP BY d ORDER BY d"
                ),
                {"days": _OVERVIEW_DAILY_DAYS},
            )
        ).all()
        daily = [
            AdminDailyQueries(day=str(row[0]), count=int(row[1]), errors=int(row[2]))
            for row in daily_rows
        ]

    return AdminOverviewResponse(
        tenants=tenants,
        users=users,
        active_api_keys=active_keys,
        documents=documents,
        chunks=chunks,
        notebooks=notebooks,
        chat_sessions=sessions,
        chat_messages=messages,
        queries=queries,
        daily_queries=daily,
    )


# ── Tenants ───────────────────────────────────────────────────────────────────


async def _tenant_group_counts(db: AsyncSession, statement: TextClause) -> dict[str, int]:
    rows = (await db.execute(statement)).all()
    return {str(row[0]): int(row[1]) for row in rows}


@router.get("/admin/tenants", response_model=list[AdminTenantSummary])
async def admin_tenants(
    x_admin_secret: str = Header(..., alias="X-Admin-Secret"),
) -> list[AdminTenantSummary]:
    """Per-tenant activity: documents, chunks, sessions and 7-day query volume."""
    _require_admin(x_admin_secret)

    async with admin_session() as db:
        users = await _tenant_group_counts(
            db, text("SELECT tenant_id, count(*) FROM users GROUP BY tenant_id")
        )
        documents = await _tenant_group_counts(
            db, text("SELECT tenant_id, count(*) FROM documents GROUP BY tenant_id")
        )
        chunks = await _tenant_group_counts(
            db, text("SELECT tenant_id, count(*) FROM chunks GROUP BY tenant_id")
        )
        sessions = await _tenant_group_counts(
            db, text("SELECT tenant_id, count(*) FROM chat_sessions GROUP BY tenant_id")
        )
        queries = await _tenant_group_counts(
            db,
            text(
                "SELECT tenant_id, count(*) FROM agent_query_logs"
                " WHERE created_at >= now() - interval '7 days'"
                " GROUP BY tenant_id"
            ),
        )
        last_seen_rows = (
            await db.execute(
                text("SELECT tenant_id, max(created_at) FROM agent_query_logs GROUP BY tenant_id")
            )
        ).all()
    last_seen = {str(row[0]): row[1] for row in last_seen_rows}

    tenant_ids = users.keys() | documents.keys() | chunks.keys() | sessions.keys() | queries.keys()
    summaries = [
        AdminTenantSummary(
            tenant_id=tenant_id,
            users=users.get(tenant_id, 0),
            documents=documents.get(tenant_id, 0),
            chunks=chunks.get(tenant_id, 0),
            sessions=sessions.get(tenant_id, 0),
            queries_7d=queries.get(tenant_id, 0),
            last_query_at=last_seen.get(tenant_id),
        )
        for tenant_id in sorted(tenant_ids, key=lambda t: (-queries.get(t, 0), t))[:_MAX_TENANTS]
    ]
    return summaries


# ── Users ─────────────────────────────────────────────────────────────────────


@router.get("/admin/users", response_model=list[AdminUserInfo])
async def admin_users(
    x_admin_secret: str = Header(..., alias="X-Admin-Secret"),
    tenant_id: str | None = Query(default=None, max_length=64),
) -> list[AdminUserInfo]:
    """All users across tenants with key counts and query-log activity."""
    _require_admin(x_admin_secret)

    async with admin_session() as db:
        users_stmt = select(User).order_by(User.created_at.desc()).limit(_MAX_USERS)
        if tenant_id:
            users_stmt = users_stmt.where(User.tenant_id == tenant_id)
        users = (await db.execute(users_stmt)).scalars().all()

        key_rows = (
            await db.execute(
                select(
                    ApiKey.user_id,
                    func.count(),
                    func.count().filter(ApiKey.is_active.is_(True)),
                ).group_by(ApiKey.user_id)
            )
        ).all()
        keys_by_user = {row[0]: (int(row[1]), int(row[2])) for row in key_rows}

        query_rows = (
            await db.execute(
                text(
                    "SELECT user_id, count(*),"
                    " count(*) FILTER (WHERE created_at >= now() - interval '7 days'),"
                    " max(created_at)"
                    " FROM agent_query_logs WHERE user_id IS NOT NULL GROUP BY user_id"
                )
            )
        ).all()
        stats_by_user = {row[0]: (int(row[1]), int(row[2]), row[3]) for row in query_rows}

    items = []
    for user in users:
        keys, active_keys = keys_by_user.get(user.id, (0, 0))
        total, week, last_at = stats_by_user.get(user.id, (0, 0, None))
        items.append(
            AdminUserInfo(
                id=str(user.id),
                tenant_id=user.tenant_id,
                name=user.name,
                role=user.role,
                created_at=user.created_at,
                keys=keys,
                active_keys=active_keys,
                queries_total=total,
                queries_7d=week,
                last_query_at=last_at,
            )
        )
    return items


# ── API keys (access control + activity) ─────────────────────────────────────


@router.get("/admin/keys", response_model=list[AdminKeyInfo])
async def admin_keys(
    x_admin_secret: str = Header(..., alias="X-Admin-Secret"),
    tenant_id: str | None = Query(default=None, max_length=64),
) -> list[AdminKeyInfo]:
    """All API keys with their request activity (creation/revocation stay on
    POST /auth/keys and DELETE /auth/keys/{id} — same admin secret)."""
    _require_admin(x_admin_secret)

    async with admin_session() as db:
        keys_stmt = (
            select(ApiKey, User.name)
            .outerjoin(User, ApiKey.user_id == User.id)
            .order_by(ApiKey.created_at.desc())
            .limit(_MAX_USERS)
        )
        if tenant_id:
            keys_stmt = keys_stmt.where(ApiKey.tenant_id == tenant_id)
        key_rows = (await db.execute(keys_stmt)).all()

        stats_rows = (
            await db.execute(
                text(
                    "SELECT api_key_id, count(*),"
                    " count(*) FILTER (WHERE created_at >= now() - interval '7 days'),"
                    " max(created_at)"
                    " FROM agent_query_logs WHERE api_key_id IS NOT NULL"
                    " GROUP BY api_key_id"
                )
            )
        ).all()
    stats_by_key = {row[0]: (int(row[1]), int(row[2]), row[3]) for row in stats_rows}

    items = []
    for key_row, user_name in key_rows:
        total, week, last_at = stats_by_key.get(key_row.id, (0, 0, None))
        items.append(
            AdminKeyInfo(
                id=str(key_row.id),
                tenant_id=key_row.tenant_id,
                name=key_row.name,
                user_id=str(key_row.user_id) if key_row.user_id else None,
                user_name=user_name,
                is_active=key_row.is_active,
                created_at=key_row.created_at,
                last_used_at=key_row.last_used_at,
                queries_total=total,
                queries_7d=week,
                last_query_at=last_at,
            )
        )
    return items


# ── Query log (prompts) ───────────────────────────────────────────────────────


def _prompt_item(row: AgentQueryLog, *, preview_only: bool) -> dict[str, object]:
    item: dict[str, object] = {
        "id": str(row.id),
        "tenant_id": row.tenant_id,
        "user_id": str(row.user_id) if row.user_id else None,
        "user_name": row.user_name,
        "api_key_id": str(row.api_key_id) if row.api_key_id else None,
        "api_key_name": row.api_key_name,
        "mode": row.mode,
        "model": row.model,
        "session_id": str(row.session_id) if row.session_id else None,
        "workflow_id": row.workflow_id,
        "scope_type": row.scope_type,
        "scope_ref": str(row.scope_ref) if row.scope_ref else None,
        "query": row.query,
        "answer_preview": row.answer[:_ANSWER_PREVIEW_CHARS],
        "status": row.status,
        "error": row.error,
        "latency_ms": row.latency_ms,
        "cached": row.cached,
        "confidence": row.confidence,
        "sources_count": row.sources_count,
        "prompt_tokens": row.prompt_tokens,
        "completion_tokens": row.completion_tokens,
        "cost_usd": row.cost_usd,
        "created_at": row.created_at,
    }
    if not preview_only:
        item["answer"] = row.answer
        item["retrieval_query"] = row.retrieval_query
    return item


@router.get("/admin/prompts", response_model=AdminPromptListResponse)
async def admin_prompts(
    x_admin_secret: str = Header(..., alias="X-Admin-Secret"),
    tenant_id: str | None = Query(default=None, max_length=64),
    user_id: uuid.UUID | None = None,
    mode: str | None = Query(default=None, pattern="^(stream|run|research)$"),
    status: str | None = Query(default=None, pattern="^(ok|error|pending)$"),
    q: str | None = Query(default=None, max_length=256),
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AdminPromptListResponse:
    """Paginated agent query log with filters — the "who asked what" feed."""
    _require_admin(x_admin_secret)

    filters = [
        AgentQueryLog.created_at >= func.now() - timedelta(days=days),
    ]
    if tenant_id:
        filters.append(AgentQueryLog.tenant_id == tenant_id)
    if user_id is not None:
        filters.append(AgentQueryLog.user_id == user_id)
    if mode:
        filters.append(AgentQueryLog.mode == mode)
    if status:
        filters.append(AgentQueryLog.status == status)
    if q:
        pattern = f"%{q}%"
        filters.append(or_(AgentQueryLog.query.ilike(pattern), AgentQueryLog.answer.ilike(pattern)))

    async with admin_session() as db:
        total = _scalar(
            (
                await db.execute(select(func.count()).select_from(AgentQueryLog).where(*filters))
            ).scalar()
        )
        rows = await db.execute(
            select(AgentQueryLog)
            .where(*filters)
            .order_by(AgentQueryLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        items = [
            AdminPromptListItem(**_prompt_item(row, preview_only=True))
            for row in rows.scalars().all()
        ]

    return AdminPromptListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/admin/prompts/{log_id}", response_model=AdminPromptDetail)
async def admin_prompt_detail(
    log_id: uuid.UUID,
    x_admin_secret: str = Header(..., alias="X-Admin-Secret"),
) -> AdminPromptDetail:
    """Full log entry: complete answer, retrieval query, cost breakdown."""
    _require_admin(x_admin_secret)

    async with admin_session() as db:
        row = (
            await db.execute(select(AgentQueryLog).where(AgentQueryLog.id == log_id))
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="query log entry not found")
    return AdminPromptDetail(**_prompt_item(row, preview_only=False))


# ── Documents (cross-tenant health) ──────────────────────────────────────────


@router.get("/admin/documents", response_model=AdminDocumentListResponse)
async def admin_documents(
    x_admin_secret: str = Header(..., alias="X-Admin-Secret"),
    tenant_id: str | None = Query(default=None, max_length=64),
    status: str | None = Query(default=None, pattern="^(pending|processing|done|failed)$"),
    q: str | None = Query(default=None, max_length=256),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AdminDocumentListResponse:
    """All documents across tenants — ingestion failures and progress at a glance."""
    _require_admin(x_admin_secret)

    filters = []
    if tenant_id:
        filters.append(Document.tenant_id == tenant_id)
    if status:
        filters.append(Document.status == status)
    if q:
        filters.append(Document.filename.ilike(f"%{q}%"))

    async with admin_session() as db:
        total = _scalar(
            (await db.execute(select(func.count()).select_from(Document).where(*filters))).scalar()
        )
        rows = (
            (
                await db.execute(
                    select(Document)
                    .where(*filters)
                    .order_by(Document.created_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )

    items = [
        AdminDocumentListItem(
            id=str(doc.id),
            tenant_id=doc.tenant_id,
            filename=doc.filename,
            source_type=doc.source_type,
            status=_status_name(doc.status),
            processing_stage=doc.processing_stage,
            error=doc.error,
            size_bytes=doc.size_bytes,
            total_pages=doc.total_pages,
            processed_pages=doc.processed_pages,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
        )
        for doc in rows
    ]
    return AdminDocumentListResponse(items=items, total=total, limit=limit, offset=offset)


# ── LLM usage (cross-tenant ClickHouse) ──────────────────────────────────────


@router.get("/admin/usage", response_model=AdminUsageResponse)
async def admin_usage(
    x_admin_secret: str = Header(..., alias="X-Admin-Secret"),
    days: int = Query(default=7, ge=1, le=90),
) -> AdminUsageResponse:
    """LLM cost/token usage across all tenants, models and days."""
    _require_admin(x_admin_secret)

    by_tenant_sql = """
        SELECT
            tenant_id,
            round(sum(cost_usd), 6)     AS cost_usd,
            sum(total_tokens)           AS total_tokens,
            count()                     AS calls
        FROM analytics.llm_usage_events
        WHERE event_time >= now() - toIntervalDay({days:UInt32})
        GROUP BY tenant_id
        ORDER BY cost_usd DESC
        LIMIT 100
    """
    by_model_sql = """
        SELECT
            model,
            provider,
            round(sum(cost_usd), 6)     AS cost_usd,
            sum(total_tokens)           AS total_tokens,
            count()                     AS calls,
            round(avg(latency_ms))      AS avg_latency_ms
        FROM analytics.llm_usage_events
        WHERE event_time >= now() - toIntervalDay({days:UInt32})
        GROUP BY model, provider
        ORDER BY cost_usd DESC
    """
    daily_sql = """
        SELECT
            toDate(event_time)          AS day,
            round(sum(cost_usd), 6)     AS cost_usd,
            sum(total_tokens)           AS total_tokens,
            count()                     AS calls
        FROM analytics.llm_usage_events
        WHERE event_time >= now() - toIntervalDay({days:UInt32})
        GROUP BY day
        ORDER BY day ASC
    """
    try:
        tenant_rows = await ch_client.query(by_tenant_sql, {"days": days})
        model_rows = await ch_client.query(by_model_sql, {"days": days})
        daily_rows = await ch_client.query(daily_sql, {"days": days})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ClickHouse error: {e}") from e

    by_tenant = [
        AdminUsageByTenant(
            tenant_id=_ch_str(row, "tenant_id"),
            cost_usd=_ch_float(row, "cost_usd"),
            total_tokens=_ch_int(row, "total_tokens"),
            calls=_ch_int(row, "calls"),
        )
        for row in tenant_rows
    ]
    by_model = [
        AdminUsageByModel(
            model=_ch_str(row, "model"),
            provider=_ch_str(row, "provider"),
            cost_usd=_ch_float(row, "cost_usd"),
            total_tokens=_ch_int(row, "total_tokens"),
            calls=_ch_int(row, "calls"),
            avg_latency_ms=_ch_int(row, "avg_latency_ms"),
        )
        for row in model_rows
    ]
    daily = [
        AdminUsageDaily(
            day=_ch_str(row, "day"),
            cost_usd=_ch_float(row, "cost_usd"),
            total_tokens=_ch_int(row, "total_tokens"),
            calls=_ch_int(row, "calls"),
        )
        for row in daily_rows
    ]

    totals = AdminUsageTotals(
        cost_usd=round(sum(item.cost_usd for item in by_model), 6),
        total_tokens=sum(item.total_tokens for item in by_model),
        calls=sum(item.calls for item in by_model),
        avg_latency_ms=(
            round(
                sum(item.avg_latency_ms * item.calls for item in by_model)
                / max(sum(item.calls for item in by_model), 1)
            )
        ),
    )
    return AdminUsageResponse(
        days=days, totals=totals, by_tenant=by_tenant, by_model=by_model, daily=daily
    )


# ── Service health ────────────────────────────────────────────────────────────


@router.get("/admin/health", response_model=AdminHealthResponse)
async def admin_health(
    request: Request,
    x_admin_secret: str = Header(..., alias="X-Admin-Secret"),
) -> AdminHealthResponse:
    """Fresh dependency checks (postgres, redis, clickhouse, minio, temporal)."""
    _require_admin(x_admin_secret)

    results = await asyncio.gather(*(_run_check(name, request) for name in _CHECK_NAMES))
    checks = dict(results)
    ready = all(status == "ok" for status in checks.values())
    return AdminHealthResponse(status="ok" if ready else "unavailable", checks=checks)
