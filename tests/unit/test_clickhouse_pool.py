from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from packages.analytics.clickhouse import ClickHouseClient


@pytest.mark.asyncio
async def test_pooled_clickhouse_concurrent_queries() -> None:
    created_clients: list[MagicMock] = []

    def mock_create_raw():
        mock = MagicMock()
        mock.query.side_effect = lambda sql, parameters=None: MagicMock(
            named_results=lambda: [{"val": sql}]
        )
        created_clients.append(mock)
        return mock

    pool = ClickHouseClient(max_pool_size=3)

    with patch.object(pool, "_create_raw_client", side_effect=mock_create_raw):
        # Run 6 concurrent queries (more than pool size)
        async def run_query(i: int):
            return await pool.query(f"SELECT {i}")

        results = await asyncio.gather(*[run_query(i) for i in range(6)])

        assert len(results) == 6
        for i, res in enumerate(results):
            assert res == [{"val": f"SELECT {i}"}]

        # Pool size should not exceed max_pool_size (3)
        assert len(created_clients) <= 3


@pytest.mark.asyncio
async def test_pooled_clickhouse_discards_broken_client() -> None:
    created_clients: list[MagicMock] = []

    def mock_create_raw():
        mock = MagicMock()
        mock.query.side_effect = RuntimeError("ClickHouse connection reset")
        created_clients.append(mock)
        return mock

    pool = ClickHouseClient(max_pool_size=2)

    with patch.object(pool, "_create_raw_client", side_effect=mock_create_raw):
        with pytest.raises(RuntimeError, match="ClickHouse connection reset"):
            await pool.query("SELECT 1")

        # The broken client should have been closed and discarded
        assert created_clients[0].close.called
        assert pool._created_count == 0
