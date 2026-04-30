"""Activities are where I/O happens — LLM calls, DB queries, HTTP, etc."""

from __future__ import annotations

import logging
import time

from temporalio import activity

from pydantic_ai.settings import ModelSettings

from packages.agents import AgentDeps, AgentRunInput, AgentRunOutput, build_research_agent
from packages.analytics.events import UsageEvent, record_usage
from packages.cache.semantic import semantic_cache
from packages.core import settings

log = logging.getLogger(__name__)


@activity.defn
async def run_agent_step(payload: AgentRunInput) -> AgentRunOutput:
    info = activity.info()

    # ── Semantic cache lookup ────────────────────────────────────────────────
    cached = await semantic_cache.get(payload.user_query, payload.tenant_id)
    if cached is not None:
        await record_usage(UsageEvent(
            tenant_id=payload.tenant_id,
            workflow_id=info.workflow_id,
            run_id=info.workflow_run_id,
            model=payload.model or settings.strong_model,
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=0,
            status="cache_hit",
        ))
        return cached.model_copy(update={"cached": True})

    # ── LLM call ─────────────────────────────────────────────────────────────
    agent = build_research_agent(model_name=payload.model)
    deps = AgentDeps(tenant_id=payload.tenant_id)

    model_name = payload.model or settings.strong_model

    # kimi-k2.6 has thinking enabled by default which is incompatible with
    # tool_choice='required' that PydanticAI sends when tools are registered.
    # Disable thinking via extra_body so tools work normally.
    ms: ModelSettings = {}
    if "kimi" in model_name or "v4-pro" in model_name:
        ms = {"extra_body": {"thinking": {"type": "disabled"}}}

    t0 = time.monotonic()
    result = await agent.run(payload.user_query, deps=deps, model_settings=ms)
    latency_ms = int((time.monotonic() - t0) * 1000)

    usage = result.usage()
    resolved_model = model_name

    # Moonshot / OpenAI return cached_tokens in usage.details when prompt
    # caching fires. Log it so we can verify cache hit rate in production.
    cached_tokens = (usage.details or {}).get("cached_tokens", 0)
    if cached_tokens:
        log.info(
            "prompt cache hit | tenant=%s model=%s cached_tokens=%d",
            payload.tenant_id,
            resolved_model,
            cached_tokens,
        )

    await record_usage(UsageEvent(
        tenant_id=payload.tenant_id,
        workflow_id=info.workflow_id,
        run_id=info.workflow_run_id,
        model=resolved_model,
        prompt_tokens=usage.request_tokens or 0,
        completion_tokens=usage.response_tokens or 0,
        latency_ms=latency_ms,
    ))

    # Store result for future semantic cache hits.
    output = result.output
    await semantic_cache.set(payload.user_query, payload.tenant_id, output)

    return output
