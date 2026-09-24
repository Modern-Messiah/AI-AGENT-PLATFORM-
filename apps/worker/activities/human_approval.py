"""Human-in-the-loop approval activity.

Notifies a reviewer that an answer awaits approval. Without configuration
it only logs (the original scaffold behaviour). With HITL_WEBHOOK_URL set
it also POSTs a Slack-compatible JSON payload — best-effort: a failed
notification never fails the activity, the workflow waits for the signal
either way.

Signal the workflow via:
  POST /workflows/{workflow_id}/approve
  POST /workflows/{workflow_id}/reject
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

import httpx
from packages.core import settings
from temporalio import activity

log = logging.getLogger(__name__)

Notifier = Callable[[dict[str, object]], Awaitable[None]]


async def send_hitl_webhook(payload: dict[str, object], *, url: str | None = None) -> None:
    """POST a Slack-compatible message about a pending approval.

    Slack renders the "text" field; other receivers get the structured
    fields alongside. Never raises — notification delivery is best-effort.
    """
    target = url if url is not None else settings.hitl_webhook_url
    if not target:
        return

    workflow_id = str(payload.get("workflow_id", "?"))
    confidence = float(str(payload.get("confidence", 0.0) or 0.0))
    query_preview = str(payload.get("user_query", ""))[:200]
    answer_preview = str(payload.get("answer", ""))[:280]
    base_url = settings.hitl_webhook_base_url.rstrip("/") if settings.hitl_webhook_base_url else ""

    approve_hint = (
        f"\nApprove: {base_url}/api/workflows/{workflow_id}/approve"
        if base_url
        else f"\nApprove: POST /workflows/{workflow_id}/approve"
    )
    message: dict[str, object] = {
        "text": (
            f"Answer awaiting human approval\n"
            f"workflow: {workflow_id}\n"
            f"confidence: {confidence:.2f}\n"
            f"question: {query_preview}\n"
            f"answer preview: {answer_preview}"
            f"{approve_hint}"
        ),
        "workflow_id": workflow_id,
        "confidence": confidence,
        "user_query": query_preview,
        "answer_preview": answer_preview,
    }

    try:
        async with httpx.AsyncClient(timeout=settings.hitl_webhook_timeout_seconds) as client:
            response = await client.post(target, json=message)
            response.raise_for_status()
    except Exception as exc:  # best-effort notification
        log.warning(
            "HITL webhook delivery failed | workflow=%s error=%s",
            workflow_id,
            type(exc).__name__,
        )


@activity.defn
async def request_human_approval(
    payload: dict[str, object], notify: Notifier | None = None
) -> None:
    sender = notify or send_hitl_webhook
    await sender(payload)
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
