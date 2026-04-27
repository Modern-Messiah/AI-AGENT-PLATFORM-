"""OpenTelemetry → Langfuse wiring.

Langfuse v3 ingests OTel spans on /api/public/otel. PydanticAI emits OTel
traces natively, so we just point an OTLP exporter at Langfuse and every
agent run shows up in the UI.
"""

from __future__ import annotations

import base64
import logging

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from packages.core import settings

log = logging.getLogger(__name__)

_initialized = False


def setup_tracing(service_name: str) -> None:
    """Idempotently install an OTel tracer provider that ships to Langfuse."""
    global _initialized
    if _initialized:
        return

    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        log.warning("Langfuse keys not set — tracing disabled")
        _initialized = True
        return

    auth = base64.b64encode(
        f"{settings.langfuse_public_key}:{settings.langfuse_secret_key}".encode()
    ).decode()

    exporter = OTLPSpanExporter(
        endpoint=f"{settings.langfuse_host.rstrip('/')}/api/public/otel/v1/traces",
        headers={"Authorization": f"Basic {auth}"},
    )

    provider = TracerProvider(
        resource=Resource.create(
            {"service.name": service_name, "deployment.environment": settings.app_env}
        )
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    _initialized = True
    log.info("OTel → Langfuse tracing enabled for %s", service_name)
