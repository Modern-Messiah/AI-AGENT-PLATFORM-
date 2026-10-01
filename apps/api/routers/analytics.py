from __future__ import annotations

import logging
from typing import cast

from fastapi import APIRouter, HTTPException, Query
from packages.analytics.clickhouse import ch_client

from apps.api.deps import ActorDep

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/analytics/usage")
async def get_usage(
    actor: ActorDep,
    days: int = Query(default=30, ge=1, le=365),
) -> dict[str, object]:
    """Personal usage for session logins; tenant-wide for unbound API keys."""
    tenant_id = actor.tenant_id
    user_id = str(actor.user_id) if actor.user_id else ""
    scope_filter = "AND user_id = {user_id:String}" if user_id else ""
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
    if user_id:
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
    return {
        "tenant_id": tenant_id,
        "scope": "user" if user_id else "tenant",
        "days": days,
        "total_cost_usd": round(total_cost, 6),
        "breakdown": rows,
        "daily": daily_rows,
    }
