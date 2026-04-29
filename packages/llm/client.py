"""Model factory — routes provider/model to the right OpenAI-compatible API."""

from __future__ import annotations

from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from packages.core import settings

_PROVIDER_CONFIG: dict[str, tuple[str, str]] = {
    "moonshot": ("https://api.moonshot.ai/v1", settings.moonshot_api_key),
    "deepseek": ("https://api.deepseek.com/v1", settings.deepseek_api_key),
}


def build_model(model_name: str | None = None) -> OpenAIModel:
    """Return a PydanticAI model for the given provider/model string.

    Format: "provider/model-name"  e.g. "deepseek/deepseek-chat"
    Falls back to settings.strong_model when model_name is None.
    """
    full_name = model_name or settings.strong_model
    parts = full_name.split("/", 1)

    if len(parts) == 2:
        provider_key, model_id = parts
        base_url, api_key = _PROVIDER_CONFIG.get(
            provider_key,
            ("https://api.openai.com/v1", ""),
        )
    else:
        model_id = full_name
        base_url, api_key = "https://api.openai.com/v1", ""

    client = AsyncOpenAI(base_url=base_url, api_key=api_key or "not-set")
    provider = OpenAIProvider(openai_client=client)
    return OpenAIModel(model_id, provider=provider)
