from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from packages.analytics.clickhouse import ch_client

from apps.api.deps import TenantID

router = APIRouter()


@router.get("/analytics/usage")
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
