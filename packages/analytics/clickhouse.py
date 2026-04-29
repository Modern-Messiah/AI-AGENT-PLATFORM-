"""Lazy ClickHouse client. Connects on first use, not on import."""

from __future__ import annotations

import asyncio
from functools import cached_property
from urllib.parse import urlparse

import clickhouse_connect
from clickhouse_connect.driver.client import Client

from packages.core import settings


class ClickHouseClient:
    @cached_property
    def _client(self) -> Client:
        u = urlparse(settings.clickhouse_url)
        return clickhouse_connect.get_client(
            host=u.hostname or "localhost",
            port=u.port or 8123,
            username=u.username or "default",
            password=u.password or "",
            database=u.path.lstrip("/") or "analytics",
        )

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
