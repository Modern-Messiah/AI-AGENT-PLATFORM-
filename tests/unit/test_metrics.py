from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from apps.api.metrics import (
    MetricsMiddleware,
    agent_cache_requests_total,
    agent_tokens_total,
    metrics_response,
)
from prometheus_client import REGISTRY


def _sample(name: str, **labels: str) -> float | None:
    return REGISTRY.get_sample_value(name, labels)


async def _noop_receive() -> dict[str, Any]:
    return {"type": "http.disconnect"}


async def _noop_send(message: Any) -> None:
    return None


async def test_middleware_counts_by_route_template_and_status() -> None:
    async def app(scope: Any, receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 204})
        await send({"type": "http.response.body", "body": b""})

    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "route": SimpleNamespace(path="/documents/{document_id}"),
    }
    middleware = MetricsMiddleware(app)

    before = (
        _sample(
            "aap_http_requests_total", method="GET", path="/documents/{document_id}", status="204"
        )
        or 0.0
    )
    await middleware(scope, _noop_receive, _noop_send)
    after = (
        _sample(
            "aap_http_requests_total", method="GET", path="/documents/{document_id}", status="204"
        )
        or 0.0
    )

    assert after == before + 1


async def test_middleware_labels_unmatched_routes_without_path() -> None:
    async def app(scope: Any, receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 404})
        await send({"type": "http.response.body", "body": b""})

    scope: dict[str, Any] = {"type": "http", "method": "POST"}

    before = (
        _sample("aap_http_requests_total", method="POST", path="unmatched", status="404") or 0.0
    )
    await MetricsMiddleware(app)(scope, _noop_receive, _noop_send)
    after = _sample("aap_http_requests_total", method="POST", path="unmatched", status="404") or 0.0

    assert after == before + 1


async def test_metrics_endpoint_exposes_counters() -> None:
    agent_tokens_total.labels(model="moonshot/kimi-k2.6", kind="prompt").inc(10)
    agent_cache_requests_total.labels(result="hit").inc()

    response = await metrics_response()

    assert response.status_code == 200
    body = bytes(response.body).decode()
    assert "aap_http_requests_total" in body
    assert "aap_agent_tokens_total" in body
    assert "aap_agent_cache_requests_total" in body
    assert 'model="moonshot/kimi-k2.6"' in body


async def test_non_http_scope_passes_through_uncounted() -> None:
    called = {"lifespan": False}

    async def app(scope: Any, receive: Any, send: Any) -> None:
        called["lifespan"] = True

    await MetricsMiddleware(app)({"type": "lifespan"}, _noop_receive, _noop_send)

    assert called["lifespan"] is True
    assert _sample("aap_http_requests_total", method="?", path="unmatched", status="500") is None
