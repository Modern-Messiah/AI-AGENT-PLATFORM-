"""SQLAlchemy async engine + session factory."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.core import settings

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    echo=False,
)

async_session = async_sessionmaker(engine, expire_on_commit=False)
