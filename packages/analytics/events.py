"""Write LLM usage events to ClickHouse and fire budget alerts."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from packages.analytics.clickhouse import ch_client
from packages.analytics.pricing import cost_usd
from packages.core import settings

log = logging.getLogger(__name__)

_TABLE = "analytics.llm_usage_events"
_COLUMNS = [
    "event_time",
    "tenant_id",
    "workflow_id",
    "run_id",
    "model",
    "provider",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cost_usd",
    "latency_ms",
    "status",
    "error",
]


@dataclass
class UsageEvent:
    tenant_id: str
    workflow_id: str
    run_id: str
    model: str          # full name, e.g. "moonshot/kimi-k2-turbo-preview"
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    status: str = "ok"
    error: str = ""
    event_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def provider(self) -> str:
        parts = self.model.split("/", 1)
        return parts[0] if len(parts) == 2 else "unknown"

    @property
    def model_short(self) -> str:
        return self.model.split("/", 1)[-1]

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def cost(self) -> float:
        return cost_usd(self.model_short, self.prompt_tokens, self.completion_tokens)


async def record_usage(event: UsageEvent) -> None:
    """Insert one usage row into ClickHouse; log a warning if cost exceeds threshold."""
    row = [[
        event.event_time,
        event.tenant_id,
        event.workflow_id,
        event.run_id,
        event.model_short,
        event.provider,
        event.prompt_tokens,
        event.completion_tokens,
        event.total_tokens,
        event.cost,
        event.latency_ms,
        event.status,
        event.error,
    ]]

    try:
        await ch_client.insert(_TABLE, row, column_names=_COLUMNS)
    except Exception as exc:  # noqa: BLE001
        # Never let analytics failure crash the agent activity.
        log.warning("ClickHouse insert failed: %s", exc)

    if event.cost > settings.budget_alert_usd_per_call:
        log.warning(
            "BUDGET ALERT | tenant=%s model=%s cost=$%.4f exceeds threshold=$%.4f",
            event.tenant_id,
            event.model_short,
            event.cost,
            settings.budget_alert_usd_per_call,
        )
