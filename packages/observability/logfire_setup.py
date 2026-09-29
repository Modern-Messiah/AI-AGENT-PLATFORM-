"""Optional Pydantic Logfire integration.

Enabled only when LOGFIRE_TOKEN is set (https://logfire.pydantic.dev —
create a project, copy a write token). Without a token the platform runs
exactly as before: Langfuse keeps the LLM-trace role, Prometheus/Grafana
keep the metrics role, and this module is a no-op.

What gets instrumented when enabled:
  - FastAPI — every request with routes, statuses and exceptions
  - OpenAI clients — every LLM call with model, parameters, prompts and
    completions (record_content defaults on for OpenAI instrumentation)
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core import settings

log = logging.getLogger(__name__)

_initialized = False


def logfire_enabled() -> bool:
    return bool(settings.logfire_token)


def setup_logfire(service_name: str) -> bool:
    """Configure Logfire once per process; returns True when active."""
    global _initialized
    if _initialized or not settings.logfire_token:
        return False
    _initialized = True

    import logfire

    logfire.configure(
        token=settings.logfire_token,
        service_name=service_name,
        environment=settings.app_env,
        send_to_logfire=True,
    )
    try:
        # LLM calls through the openai package (both providers are
        # OpenAI-compatible): model, params, prompt and completion bodies.
        logfire.instrument_openai()
    except Exception as exc:  # instrumentation is best-effort
        log.warning("logfire openai instrumentation failed: %s", exc)
    log.info("logfire enabled | service=%s env=%s", service_name, settings.app_env)
    return True


def instrument_fastapi_app(app: Any) -> None:
    """Attach request instrumentation to the FastAPI app (no-op without token)."""
    if not settings.logfire_token:
        return
    try:
        import logfire

        logfire.instrument_fastapi(app, capture_headers=True)
    except Exception as exc:
        log.warning("logfire fastapi instrumentation failed: %s", exc)
