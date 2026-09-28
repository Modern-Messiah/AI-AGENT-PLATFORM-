"""Best-effort audit trail for agent requests (admin panel data source).

Every /agent/stream, /agent/run and /agent/research call ends with exactly
one log_agent_query() write. Failures are logged and swallowed: monitoring
must never break the answer path (same contract as record_usage).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from packages.analytics.pricing import cost_usd
from packages.storage import AgentQueryLog
from packages.storage.db import tenant_session

log = logging.getLogger(__name__)

# Keep stored payloads bounded even if a provider misbehaves.
_MAX_ANSWER_CHARS = 8000
_MAX_ERROR_CHARS = 1000


@dataclass(slots=True)
class QueryLogEntry:
    """Everything the admin panel needs to know about one agent request."""

    tenant_id: str
    mode: str  # stream | run | research
    model: str
    query: str
    user_id: uuid.UUID | None = None
    user_name: str | None = None
    api_key_id: uuid.UUID | None = None
    api_key_name: str | None = None
    session_id: uuid.UUID | None = None
    workflow_id: str | None = None
    scope_type: str | None = None
    scope_ref: uuid.UUID | None = None
    retrieval_query: str | None = None
    answer: str = ""
    status: str = "ok"  # ok | error
    error: str | None = None
    latency_ms: int = 0
    cached: bool = False
    confidence: float | None = None
    sources_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


def estimated_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Price one request from the analytics table; None when no tokens were used."""
    if not prompt_tokens and not completion_tokens:
        return None
    return cost_usd(model.split("/", 1)[-1], prompt_tokens, completion_tokens)


async def log_agent_query(entry: QueryLogEntry) -> None:
    """Persist one query log row; never raises."""
    try:
        row = AgentQueryLog(
            tenant_id=entry.tenant_id,
            user_id=entry.user_id,
            user_name=entry.user_name,
            api_key_id=entry.api_key_id,
            api_key_name=entry.api_key_name,
            mode=entry.mode,
            model=entry.model,
            session_id=entry.session_id,
            workflow_id=entry.workflow_id,
            scope_type=entry.scope_type,
            scope_ref=entry.scope_ref,
            query=entry.query,
            retrieval_query=entry.retrieval_query,
            answer=entry.answer[:_MAX_ANSWER_CHARS],
            status=entry.status,
            error=entry.error[:_MAX_ERROR_CHARS] if entry.error else None,
            latency_ms=entry.latency_ms,
            cached=entry.cached,
            confidence=entry.confidence,
            sources_count=entry.sources_count,
            prompt_tokens=entry.prompt_tokens,
            completion_tokens=entry.completion_tokens,
            cost_usd=estimated_cost_usd(entry.model, entry.prompt_tokens, entry.completion_tokens),
        )
        async with tenant_session(entry.tenant_id) as s:
            s.add(row)
    except Exception:
        log.warning(
            "query log write failed | tenant=%s mode=%s — monitoring degraded, "
            "the answer itself is unaffected",
            entry.tenant_id,
            entry.mode,
            exc_info=True,
        )
