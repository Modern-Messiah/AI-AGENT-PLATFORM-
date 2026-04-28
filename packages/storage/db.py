"""SQLAlchemy async engine + session factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from packages.core import settings

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    echo=False,
)

async_session = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def tenant_session(tenant_id: str) -> AsyncIterator[AsyncSession]:
    """Open a session with SET LOCAL app.tenant_id so RLS policies apply."""
    async with async_session() as session, session.begin():
        await session.execute(
            sa.text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )
        yield session
