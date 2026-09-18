from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from packages.analytics.clickhouse import ch_client
from packages.cache.redis import get_redis
from packages.storage.db import async_session
from packages.storage.object_store import object_store

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# ── Readiness ─────────────────────────────────────────────────────────────────
#
# GET /health is a shallow liveness probe (process is up). GET /health/ready
# additionally verifies that every stateful dependency answers within a short
# timeout. Results are cached for a few seconds so a burst of probes (docker
# healthcheck + load balancer + curl) cannot stampede the dependencies.

_CHECK_TIMEOUT_SECONDS = 2.0
_RESULT_TTL_SECONDS = 5.0


def _reset_readiness_cache() -> None:
    """Test hook: drop the cached readiness result."""
    global _cached_checks, _cached_at
    _cached_checks = None
    _cached_at = 0.0


async def _check_postgres(request: Request) -> None:
    async with async_session() as session:
        await session.execute(sa.text("SELECT 1"))


async def _check_redis(request: Request) -> None:
    await get_redis().ping()


async def _check_clickhouse(request: Request) -> None:
    await ch_client.query("SELECT 1")


async def _check_minio(request: Request) -> None:
    await asyncio.to_thread(object_store.ping)


async def _check_temporal(request: Request) -> None:
    client = getattr(request.app.state, "temporal", None)
    if client is None:
        raise RuntimeError("temporal client not initialised")
    await client.check_health()


_CHECK_NAMES = ("postgres", "redis", "clickhouse", "minio", "temporal")

_result_cache_lock = asyncio.Lock()
_cached_checks: dict[str, str] | None = None
_cached_at: float = 0.0


async def _run_check(name: str, request: Request) -> tuple[str, str]:
    # Resolved at call time so tests can monkeypatch the module-level checks.
    check = globals()[f"_check_{name}"]
    try:
        await asyncio.wait_for(check(request), timeout=_CHECK_TIMEOUT_SECONDS)
        return name, "ok"
    except Exception as exc:
        # Exception text may embed connection strings — report the type only.
        log.warning("readiness check failed | check=%s error=%s", name, type(exc).__name__)
        return name, f"error: {type(exc).__name__}"


@router.get("/health/ready")
async def readiness(request: Request) -> JSONResponse:
    global _cached_checks, _cached_at

    now = time.monotonic()
    checks = _cached_checks
    from_cache = checks is not None and now - _cached_at < _RESULT_TTL_SECONDS
    if not from_cache:
        async with _result_cache_lock:
            # Another request may have refreshed the cache while we waited.
            now = time.monotonic()
            from_cache = _cached_checks is not None and now - _cached_at < _RESULT_TTL_SECONDS
            if not from_cache:
                results = await asyncio.gather(
                    *(_run_check(name, request) for name in _CHECK_NAMES)
                )
                checks = dict(results)
                _cached_checks = checks
                _cached_at = now
            else:
                checks = _cached_checks
    assert checks is not None

    ready = all(status == "ok" for status in checks.values())
    body: dict[str, Any] = {
        "status": "ok" if ready else "unavailable",
        "checks": checks,
    }
    if from_cache:
        body["age_seconds"] = round(now - _cached_at, 2)
    return JSONResponse(body, status_code=200 if ready else 503)
