"""Prometheus metrics for the API process.

Scraped at GET /metrics (no tenant auth — it exposes only aggregate
counters/histograms with route-template labels, never tenant ids or
query text). Label cardinality is bounded by using route templates
("/documents/{document_id}") instead of concrete paths.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.types import Receive, Scope, Send

http_requests_total = Counter(
    "aap_http_requests_total",
    "HTTP requests by method, route template and status",
    ["method", "path", "status"],
)
http_request_duration_seconds = Histogram(
    "aap_http_request_duration_seconds",
    "HTTP request latency by method and route template",
    ["method", "path"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)
agent_tokens_total = Counter(
    "aap_agent_tokens_total",
    "LLM tokens consumed by the streaming agent",
    ["model", "kind"],  # kind: prompt | completion
)
agent_cache_requests_total = Counter(
    "aap_agent_cache_requests_total",
    "Semantic cache lookups",
    ["result"],  # result: hit | miss
)


def _route_template(scope: Scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "unmatched"


class MetricsMiddleware:
    """Starlette middleware: request counters + latency histogram."""

    def __init__(self, app: Callable[..., Any]) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "?")
        start = time.perf_counter()
        status_holder = {"status": "500"}

        async def send_wrapper(message: Any) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = str(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = _route_template(scope)
            status = status_holder["status"]
            http_requests_total.labels(method, path, status).inc()
            http_request_duration_seconds.labels(method, path).observe(time.perf_counter() - start)


async def metrics_response() -> Any:
    from starlette.responses import Response

    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
