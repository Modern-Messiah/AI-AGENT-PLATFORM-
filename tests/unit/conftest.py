from __future__ import annotations

from collections.abc import Iterator

import pytest
from packages.core import settings


@pytest.fixture(autouse=True)
def _no_external_llm(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Unit tests must never reach real LLM providers.

    LLM-backed features (document insights, query condensation) all have
    deterministic fallbacks; disable the LLM leg by default. Individual
    tests opt back in by monkeypatching the flag to True with a fake
    completion function.
    """
    monkeypatch.setattr(settings, "ai_document_insights_enabled", False)
    monkeypatch.setattr(settings, "query_condensation_enabled", False)
    monkeypatch.setattr(settings, "query_expansion_enabled", False)
    yield


@pytest.fixture(autouse=True)
def _passthrough_fetch_targets(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Unit tests must not resolve real DNS for URL fetch targets.

    url_sources.resolve_fetch_target pins the validated IP for real
    requests; unit tests fake validation per-test via validate_fetch_url
    patches and use placeholder hosts, so the resolver would otherwise hit
    real DNS. Passthrough (no pin) by default; pinning tests re-patch
    resolve_fetch_target on top.
    """
    from apps.api.services import url_sources

    async def fake_resolve(url: str) -> url_sources.FetchTarget:
        # Still run the (per-test patched) validation so redirect and
        # blocklist assertions keep working.
        normalized = await url_sources.validate_fetch_url(url)
        return url_sources.FetchTarget(url=normalized, pin_ip=None)

    real_resolve = url_sources.resolve_fetch_target
    monkeypatch.setattr(url_sources, "resolve_fetch_target", fake_resolve)
    # Pinning tests re-enable the real resolver via this alias.
    monkeypatch.setattr(url_sources, "_real_resolve_fetch_target", real_resolve, raising=False)
    yield
