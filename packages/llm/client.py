"""Model factory — points PydanticAI at Bifrost over the OpenAI-compatible API."""

from __future__ import annotations

from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from packages.core import settings


def build_model(model_name: str | None = None) -> OpenAIModel:
    """Return a PydanticAI model that routes through Bifrost.

    Bifrost exposes an OpenAI-compatible endpoint and forwards to the
    underlying provider based on the `provider/model` prefix (e.g.
    `anthropic/claude-...`). The OpenAI SDK is happy with that as long as
    base_url and api_key are set.
    """
    client = AsyncOpenAI(
        base_url=settings.bifrost_base_url,
        api_key=settings.bifrost_api_key,
    )
    provider = OpenAIProvider(openai_client=client)
    return OpenAIModel(model_name or settings.default_model, provider=provider)
