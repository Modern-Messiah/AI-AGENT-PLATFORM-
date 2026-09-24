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
    yield
