from __future__ import annotations

import logging
from typing import cast

from fastapi import APIRouter, HTTPException, Query
from packages.analytics.clickhouse import ch_client
from packages.storage.db import admin_session
from packages.storage.models import User
from sqlalchemy import select

from apps.api.deps import ActorDep

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/analytics/usage")
async def get_usage(
    actor: ActorDep,
    days: int = Query(default=30, ge=1, le=365),
    scope: str = Query(default="auto", pattern="^(auto|personal|user|tenant|all)$"),
) -> dict[str, object]:
    """Usage analytics with scope control:

    - Personal scope (user): returns usage for the requesting user.
    - Tenant scope (tenant/all): returns aggregate usage across all users in the tenant.
      Available to admins (and unbound API keys). Non-admins are restricted to personal scope.
    - Auto: defaults to tenant-wide for admins, personal for members.
    """
    tenant_id = actor.tenant_id
    user_id = str(actor.user_id) if actor.user_id else ""
    is_admin = bool(actor.is_admin or actor.role is None)

    # Resolve effective scope
    if not is_admin:
        effective_scope = "user" if user_id else "tenant"
    elif scope in ("tenant", "all"):
        effective_scope = "tenant"
    elif scope in ("user", "personal"):
        effective_scope = "user"
    else:  # "auto"
        effective_scope = "tenant" if is_admin else ("user" if user_id else "tenant")

    # Scope filter for ClickHouse queries
    if effective_scope == "user" and user_id:
        scope_filter = "AND user_id = {user_id:String}"
    else:
        scope_filter = ""

    sql = f"""
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
        WHERE tenant_id = {{tenant_id:String}}
          {scope_filter}
          AND event_time >= now() - toIntervalDay({{days:UInt32}})
        GROUP BY model, provider
        ORDER BY total_cost_usd DESC
    """
    daily_sql = f"""
        SELECT
            toDate(event_time)       AS day,
            sum(total_tokens)        AS total_tokens,
            round(sum(cost_usd), 6)  AS total_cost_usd,
            round(avg(latency_ms))   AS avg_latency_ms,
            count()                  AS call_count
        FROM analytics.llm_usage_events
        WHERE tenant_id = {{tenant_id:String}}
          {scope_filter}
          AND event_time >= now() - toIntervalDay({{days:UInt32}})
        GROUP BY day
        ORDER BY day ASC
    """
    params: dict[str, object] = {"tenant_id": tenant_id, "days": days}
    if scope_filter and user_id:
        params["user_id"] = user_id
    try:
        rows = await ch_client.query(sql, params)
        daily_rows = await ch_client.query(daily_sql, params)
    except Exception as e:
        # Client errors embed the ClickHouse endpoint (credentials included in
        # its URL) — log the details, return a generic message.
        log.exception("analytics usage query failed | tenant=%s", tenant_id)
        raise HTTPException(status_code=500, detail="ClickHouse error") from e

    total_cost = sum(cast(float, r.get("total_cost_usd") or 0) for r in rows)

    # When viewing tenant scope, admins also get per-user breakdown
    users_breakdown: list[dict[str, object]] = []
    if effective_scope == "tenant" and is_admin:
        users_sql = f"""
            SELECT
                user_id,
                round(sum(cost_usd), 6)  AS total_cost_usd,
                sum(total_tokens)        AS total_tokens,
                count()                  AS call_count,
                round(avg(latency_ms))   AS avg_latency_ms
            FROM analytics.llm_usage_events
            WHERE tenant_id = {{tenant_id:String}}
              AND event_time >= now() - toIntervalDay({{days:UInt32}})
            GROUP BY user_id
            ORDER BY total_cost_usd DESC
        """
        try:
            raw_users = await ch_client.query(users_sql, {"tenant_id": tenant_id, "days": days})
            async with admin_session() as db:
                db_users = (
                    await db.execute(select(User).where(User.tenant_id == tenant_id))
                ).scalars().all()
            by_id = {str(u.id): u for u in db_users}

            for r in raw_users:
                uid = str(r.get("user_id") or "")
                u_obj = by_id.get(uid)
                users_breakdown.append(
                    {
                        "user_id": uid or None,
                        "user_name": u_obj.name if u_obj else None,
                        "email": u_obj.email if u_obj else None,
                        "total_cost_usd": float(r.get("total_cost_usd") or 0),
                        "total_tokens": int(r.get("total_tokens") or 0),
                        "call_count": int(r.get("call_count") or 0),
                        "avg_latency_ms": int(r.get("avg_latency_ms") or 0),
                        "is_current": bool(user_id and uid == user_id),
                    }
                )

            # Ensure current admin user is present in the list even if 0 calls
            if user_id and user_id in by_id and not any(ub.get("user_id") == user_id for ub in users_breakdown):
                cur = by_id[user_id]
                users_breakdown.append(
                    {
                        "user_id": user_id,
                        "user_name": cur.name,
                        "email": cur.email,
                        "total_cost_usd": 0.0,
                        "total_tokens": 0,
                        "call_count": 0,
                        "avg_latency_ms": 0,
                        "is_current": True,
                    }
                )
        except Exception:
            log.warning("failed to query user breakdown for tenant %s", tenant_id, exc_info=True)

    return {
        "tenant_id": tenant_id,
        "scope": effective_scope,
        "can_switch_scope": is_admin,
        "days": days,
        "total_cost_usd": round(total_cost, 6),
        "breakdown": rows,
        "daily": daily_rows,
        "users": users_breakdown,
    }
