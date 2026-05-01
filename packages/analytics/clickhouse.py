"""Lazy ClickHouse client. Connects on first use, not on import."""

from __future__ import annotations

import asyncio
import threading
from urllib.parse import urlparse

import clickhouse_connect
from clickhouse_connect.driver.client import Client

from packages.core import settings

_init_lock = threading.Lock()


class ClickHouseClient:
    def __init__(self) -> None:
        self._ch_client: Client | None = None

    @property
    def _client(self) -> Client:
        # Double-checked locking: asyncio.to_thread runs in real OS threads,
        # so cached_property's non-thread-safe write is a real race here.
        if self._ch_client is None:
            with _init_lock:
                if self._ch_client is None:
                    u = urlparse(settings.clickhouse_url)
                    self._ch_client = clickhouse_connect.get_client(
                        host=u.hostname or "localhost",
                        port=u.port or 8123,
                        username=u.username or "default",
                        password=u.password or "",
                        database=u.path.lstrip("/") or "analytics",
                    )
        return self._ch_client

    async def insert(self, table: str, rows: list[list], column_names: list[str]) -> None:
        await asyncio.to_thread(
            self._client.insert, table, rows, column_names=column_names
        )

    async def query(self, sql: str, parameters: dict | None = None) -> list[dict]:
        result = await asyncio.to_thread(
            self._client.query, sql, parameters=parameters or {}
        )
        return list(result.named_results())


ch_client = ClickHouseClient()
