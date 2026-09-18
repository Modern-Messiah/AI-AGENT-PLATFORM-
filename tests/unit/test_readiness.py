from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any, cast

import pytest
from apps.api.routers import health as health_module
from apps.api.routers.health import readiness


def _fake_request() -> Any:
    return cast(Any, SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(temporal=object()))))


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    health_module._reset_readiness_cache()
    yield
    health_module._reset_readiness_cache()


@pytest.mark.parametrize("failing_check", health_module._CHECK_NAMES)
async def test_readiness_reports_503_when_any_dependency_fails(
    monkeypatch: pytest.MonkeyPatch, failing_check: str
) -> None:
    async def ok(request: object) -> None:
        return None

    async def broken(request: object) -> None:
        raise RuntimeError("boom")

    for name in health_module._CHECK_NAMES:
        monkeypatch.setattr(health_module, f"_check_{name}", ok)
    monkeypatch.setattr(health_module, f"_check_{failing_check}", broken)

    response = await readiness(_fake_request())

    assert response.status_code == 503
    assert '"status":"unavailable"' in bytes(response.body).decode()
    checks = health_module._cached_checks
    assert checks is not None
    assert checks[failing_check] == "error: RuntimeError"
    for name in health_module._CHECK_NAMES:
        if name != failing_check:
            assert checks[name] == "ok"


async def test_readiness_returns_200_when_all_dependencies_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def ok(request: object) -> None:
        return None

    for name in health_module._CHECK_NAMES:
        monkeypatch.setattr(health_module, f"_check_{name}", ok)

    response = await readiness(_fake_request())

    assert response.status_code == 200
    assert '"status":"ok"' in bytes(response.body).decode()
    assert "age_seconds" not in bytes(response.body).decode()


async def test_readiness_serves_cached_result_within_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_count = 0

    async def counting_ok(request: object) -> None:
        nonlocal call_count
        call_count += 1

    for name in health_module._CHECK_NAMES:
        monkeypatch.setattr(health_module, f"_check_{name}", counting_ok)

    first = await readiness(_fake_request())
    second = await readiness(_fake_request())

    assert first.status_code == 200
    assert second.status_code == 200
    assert call_count == len(health_module._CHECK_NAMES)
    assert '"age_seconds"' in bytes(second.body).decode()
    assert '"age_seconds"' not in bytes(first.body).decode()


async def test_readiness_expired_cache_is_recomputed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def ok(request: object) -> None:
        return None

    for name in health_module._CHECK_NAMES:
        monkeypatch.setattr(health_module, f"_check_{name}", ok)

    await readiness(_fake_request())
    # Simulate TTL expiry.
    health_module._cached_at -= health_module._RESULT_TTL_SECONDS + 1

    response = await readiness(_fake_request())

    assert response.status_code == 200
    assert "age_seconds" not in bytes(response.body).decode()
