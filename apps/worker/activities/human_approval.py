"""Human-in-the-loop approval activity.

In production: send a Slack message, email, or write to an approvals table.
Here we just log so the scaffold is wired up end-to-end.

Signal the workflow via:
  POST /workflows/{workflow_id}/approve
  POST /workflows/{workflow_id}/reject
"""

from __future__ import annotations

import logging

from temporalio import activity

log = logging.getLogger(__name__)


@activity.defn
async def request_human_approval(payload: dict) -> None:
    workflow_id = payload.get("workflow_id", "?")
    confidence = payload.get("confidence", 0.0)
    answer_preview = str(payload.get("answer", ""))[:120]
    log.info(
        "HITL pending | workflow=%s confidence=%.2f | preview=%r | "
        "approve: POST /workflows/%s/approve",
        workflow_id,
        confidence,
        answer_preview,
        workflow_id,
    )
