from __future__ import annotations

from temporalio import activity


def heartbeat_safe(details: dict[str, object]) -> None:
    """Heartbeat the current activity, ignoring calls made outside Temporal.

    Unit tests and direct local calls have no Temporal activity context, so the
    heartbeat degrades to a no-op instead of failing the caller.
    """
    if not activity.in_activity():
        return
    activity.heartbeat(details)
