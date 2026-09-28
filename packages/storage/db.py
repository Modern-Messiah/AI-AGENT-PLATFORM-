"""SQLAlchemy async engine + session factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from packages.core import settings

engine = create_async_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
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


@asynccontextmanager
async def admin_session() -> AsyncIterator[AsyncSession]:
    """Open a cross-tenant read session for admin endpoints.

    Sets the session-local app.admin_read flag, which enables the admin_read
    SELECT policies (migration 0019) on the RLS-protected tables. Writes stay
    tenant-scoped: the policies are FOR SELECT only. Routers must gate this
    behind X-Admin-Secret.
    """
    async with async_session() as session, session.begin():
        await session.execute(sa.text("SELECT set_config('app.admin_read', 'on', true)"))
        yield session
