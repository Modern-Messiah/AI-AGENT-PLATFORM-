"""Model factory — routes provider/model to the right OpenAI-compatible API."""

from __future__ import annotations

from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.models import openai as pai_openai
from pydantic_ai.providers.openai import OpenAIProvider

from packages.core import settings

_PROVIDER_CONFIG: dict[str, tuple[str, str]] = {
    "moonshot": ("https://api.moonshot.ai/v1", settings.moonshot_api_key),
    "deepseek": ("https://api.deepseek.com/v1", settings.deepseek_api_key),
}


class ProviderCompatOpenAIModel(OpenAIModel):
    """OpenAI-compatible model with provider quirks required by Kimi/DeepSeek.

    pydantic-ai 0.0.55 does not forward arbitrary extra_body fields, and it
    sends tool_choice="required" whenever structured output is represented as a
    tool. Kimi needs thinking disabled for required tool calls; DeepSeek v4
    reasoning aliases reject required tool_choice but accept auto.
    """

    def __init__(
        self,
        model_id: str,
        *,
        provider: OpenAIProvider,
        extra_body: dict | None = None,
        force_tool_choice_auto: bool = False,
    ) -> None:
        super().__init__(model_id, provider=provider)
        self._extra_body = extra_body
        self._force_tool_choice_auto = force_tool_choice_auto

    async def _completions_create(
        self,
        messages: list[pai_openai.ModelMessage],
        stream: bool,
        model_settings: pai_openai.OpenAIModelSettings,
        model_request_parameters: pai_openai.ModelRequestParameters,
    ) -> pai_openai.chat.ChatCompletion | pai_openai.AsyncStream[pai_openai.ChatCompletionChunk]:
        tools = self._get_tools(model_request_parameters)

        if not tools:
            tool_choice = None
        elif self._force_tool_choice_auto:
            tool_choice = "auto"
        elif not model_request_parameters.allow_text_result:
            tool_choice = "required"
        else:
            tool_choice = "auto"

        openai_messages: list[pai_openai.chat.ChatCompletionMessageParam] = []
        for m in messages:
            async for msg in self._map_message(m):
                openai_messages.append(msg)

        extra: dict = {}
        if self._extra_body is not None:
            extra["extra_body"] = self._extra_body

        try:
            return await self.client.chat.completions.create(
                model=self._model_name,
                messages=openai_messages,
                n=1,
                parallel_tool_calls=model_settings.get("parallel_tool_calls", pai_openai.NOT_GIVEN),
                tools=tools or pai_openai.NOT_GIVEN,
                tool_choice=tool_choice or pai_openai.NOT_GIVEN,
                stream=stream,
                stream_options={"include_usage": True} if stream else pai_openai.NOT_GIVEN,
                stop=model_settings.get("stop_sequences", pai_openai.NOT_GIVEN),
                max_completion_tokens=model_settings.get("max_tokens", pai_openai.NOT_GIVEN),
                temperature=model_settings.get("temperature", pai_openai.NOT_GIVEN),
                top_p=model_settings.get("top_p", pai_openai.NOT_GIVEN),
                timeout=model_settings.get("timeout", pai_openai.NOT_GIVEN),
                seed=model_settings.get("seed", pai_openai.NOT_GIVEN),
                presence_penalty=model_settings.get("presence_penalty", pai_openai.NOT_GIVEN),
                frequency_penalty=model_settings.get("frequency_penalty", pai_openai.NOT_GIVEN),
                logit_bias=model_settings.get("logit_bias", pai_openai.NOT_GIVEN),
                reasoning_effort=model_settings.get("openai_reasoning_effort", pai_openai.NOT_GIVEN),
                user=model_settings.get("openai_user", pai_openai.NOT_GIVEN),
                extra_headers={"User-Agent": pai_openai.get_user_agent()},
                **extra,
            )
        except pai_openai.APIStatusError as e:
            if (status_code := e.status_code) >= 400:
                raise pai_openai.ModelHTTPError(
                    status_code=status_code,
                    model_name=self.model_name,
                    body=e.body,
                ) from e
            raise


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

    extra_body = None
    force_tool_choice_auto = False
    if provider_key == "moonshot" and "kimi" in model_id:
        extra_body = {"thinking": {"type": "disabled"}}
    if provider_key == "deepseek" and model_id in {"deepseek-v4-pro", "deepseek-v4-flash"}:
        extra_body = {"thinking": {"type": "disabled"}}
        force_tool_choice_auto = True

    return ProviderCompatOpenAIModel(
        model_id,
        provider=provider,
        extra_body=extra_body,
        force_tool_choice_auto=force_tool_choice_auto,
    )
