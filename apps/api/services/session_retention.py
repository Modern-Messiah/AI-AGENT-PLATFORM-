"""Chat session retention: delete sessions idle for longer than N days.

Sessions grow without bound in a long-lived self-hosted deployment.
CHAT_SESSION_RETENTION_DAYS=0 (default) keeps everything; a positive value
runs a cleanup at API startup and then once a day, deleting sessions whose
updated_at is older than the cutoff. Messages cascade with the session.
Tenant data other than chats (documents, notebooks) is never touched.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from packages.core import settings
from packages.storage import ChatSession, async_session
from sqlalchemy import delete

log = logging.getLogger(__name__)

_CLEANUP_INTERVAL_SECONDS = 24 * 60 * 60


def retention_cutoff(retention_days: int, *, now: datetime | None = None) -> datetime | None:
    """Cutoff timestamp for stale sessions; None when retention is off."""
    if retention_days <= 0:
        return None
    now = now or datetime.now(UTC)
    return now - timedelta(days=retention_days)


async def delete_stale_sessions(cutoff: datetime) -> int:
    """Delete sessions not updated since the cutoff. Returns deleted count."""
    async with async_session() as session, session.begin():
        result = await session.execute(delete(ChatSession).where(ChatSession.updated_at < cutoff))
    return int(getattr(result, "rowcount", 0) or 0)


async def retention_loop() -> None:
    """Startup task: prune once, then daily. Cancelled on shutdown."""
    while True:
        try:
            cutoff = retention_cutoff(settings.chat_session_retention_days)
            if cutoff is not None:
                deleted = await delete_stale_sessions(cutoff)
                if deleted:
                    log.info(
                        "session retention: deleted %d session(s) idle since before %s",
                        deleted,
                        cutoff.isoformat(),
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("session retention run failed | error=%s", type(exc).__name__)
        await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
