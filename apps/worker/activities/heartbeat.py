from __future__ import annotations

from temporalio import activity


def heartbeat_safe(details: dict[str, object] | None = None) -> None:
    """Heartbeat the current activity, ignoring calls made outside Temporal.

    Unit tests and direct local calls have no Temporal activity context, so the
    heartbeat degrades to a no-op instead of failing the caller.
    """
    try:
        if details is not None:
            activity.heartbeat(details)
        else:
            activity.heartbeat()
    except RuntimeError:
        return
