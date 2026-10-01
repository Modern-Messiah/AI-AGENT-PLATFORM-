"""Lazy ClickHouse client with connection pooling for concurrent async queries."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from urllib.parse import urlparse

import clickhouse_connect
from clickhouse_connect.driver.client import Client

from packages.core import settings


class ClickHouseClient:
    """Connection-pooled ClickHouse client.

    clickhouse_connect Client instances are not thread-safe and maintain an
    internal session state. Executing concurrent queries against the same Client
    instance raises:
        'Attempt to execute concurrent queries within the same session.
         Please use a separate client instance per thread/process.'

    This pool manages a bounded set of Client instances so concurrent asyncio
    tasks/endpoints can execute ClickHouse queries simultaneously without session collision.
    """

    def __init__(self, max_pool_size: int = 10) -> None:
        self._max_pool_size = max_pool_size
        self._pool: asyncio.Queue[Client] | None = None
        self._created_count = 0
        self._async_lock: asyncio.Lock | None = None
        self._fallback_client: Client | None = None

    def _create_raw_client(self) -> Client:
        u = urlparse(settings.clickhouse_url)
        return clickhouse_connect.get_client(
            host=u.hostname or "localhost",
            port=u.port or 8123,
            username=u.username or "default",
            password=u.password or "",
            database=u.path.lstrip("/") or "analytics",
        )

    @property
    def _client(self) -> Client:
        """Legacy access to a single client instance (thread-safe creation)."""
        if self._fallback_client is None:
            self._fallback_client = self._create_raw_client()
        return self._fallback_client

    def _get_async_lock(self) -> asyncio.Lock:
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()
        return self._async_lock

    async def _get_client(self) -> Client:
        if self._pool is None:
            async with self._get_async_lock():
                if self._pool is None:
                    self._pool = asyncio.Queue(maxsize=self._max_pool_size)

        # 1. Try to take an existing idle client from the pool
        try:
            return self._pool.get_nowait()
        except asyncio.QueueEmpty:
            pass

        # 2. If under limit, create a new client
        async with self._get_async_lock():
            if self._created_count < self._max_pool_size:
                self._created_count += 1
                return await asyncio.to_thread(self._create_raw_client)

        # 3. If at limit, wait for an available client to be released back
        return await self._pool.get()

    def _release_client(self, client: Client) -> None:
        if self._pool is not None:
            try:
                self._pool.put_nowait(client)
            except asyncio.QueueFull:
                with contextlib.suppress(Exception):
                    client.close()

    def _discard_client(self, client: Client) -> None:
        with contextlib.suppress(Exception):
            client.close()
        if self._created_count > 0:
            self._created_count -= 1

    @contextlib.asynccontextmanager
    async def acquire(self) -> AsyncIterator[Client]:
        client = await self._get_client()
        broken = False
        try:
            yield client
        except Exception:
            broken = True
            self._discard_client(client)
            raise
        finally:
            if not broken:
                self._release_client(client)

    async def insert(self, table: str, rows: list[list[object]], column_names: list[str]) -> None:
        async with self.acquire() as client:
            await asyncio.to_thread(client.insert, table, rows, column_names=column_names)

    async def query(
        self, sql: str, parameters: dict[str, object] | None = None
    ) -> list[dict[str, object]]:
        async with self.acquire() as client:
            result = await asyncio.to_thread(client.query, sql, parameters=parameters or {})
            return list(result.named_results())

    async def command(self, cmd: str) -> None:
        async with self.acquire() as client:
            await asyncio.to_thread(client.command, cmd)


ch_client = ClickHouseClient()


_schema_checked = False


async def ensure_usage_schema() -> None:
    """Idempotent column additions for analytics.llm_usage_events.

    init.sql only runs on the first ClickHouse boot; for existing stacks the
    per-user analytics columns are added here, once per process.
    """
    global _schema_checked
    if _schema_checked:
        return
    _schema_checked = True
    try:
        await ch_client.command(
            "ALTER TABLE analytics.llm_usage_events "
            "ADD COLUMN IF NOT EXISTS user_id String DEFAULT ''"
        )
    except Exception:
        log.warning("usage schema ensure failed — per-user analytics may lack attribution")


log = logging.getLogger(__name__)
