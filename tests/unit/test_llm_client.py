from types import SimpleNamespace

from packages.llm import client
from packages.llm.client import (
    _provider_error_message,
    _provider_extra_body,
    _resolve_model,
    complete_chat_json,
    complete_vision_text,
)


def test_deepseek_v4_uses_official_openai_compatible_base_url() -> None:
    provider, model_id, base_url, _api_key = _resolve_model("deepseek/deepseek-v4-pro")

    assert provider == "deepseek"
    assert model_id == "deepseek-v4-pro"
    assert base_url == "https://api.deepseek.com"


def test_deepseek_v4_disables_thinking_for_compatibility() -> None:
    assert _provider_extra_body("deepseek", "deepseek-v4-pro") == {
        "thinking": {"type": "disabled"}
    }


def test_deepseek_auth_errors_point_to_provider_key() -> None:
    message = _provider_error_message(
        "deepseek",
        401,
        {"error": {"message": "Authentication Fails, Your api key: ****c62b is invalid"}},
    )

    assert "DEEPSEEK_API_KEY" in message
    assert "tenant" not in message.lower()
    assert "****c62b" in message


async def test_complete_chat_json_uses_deepseek_json_mode(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"summary":"ok"}')
                    )
                ]
            )

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(client, "AsyncOpenAI", FakeAsyncOpenAI)

    result = await complete_chat_json(
        "deepseek/deepseek-v4-flash",
        [{"role": "user", "content": "Return json."}],
        max_tokens=1200,
    )

    assert result == '{"summary":"ok"}'
    assert captured["model"] == "deepseek-v4-flash"
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["max_tokens"] == 1200
    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}


async def test_complete_vision_text_sends_image_to_kimi(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="A diagram with three services.")
                    )
                ]
            )

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(client, "AsyncOpenAI", FakeAsyncOpenAI)

    result = await complete_vision_text(
        b"image-bytes",
        "image/webp",
        prompt="Describe the image.",
    )

    assert result == "A diagram with three services."
    assert captured["model"] == "kimi-k2.6"
    message = captured["messages"][0]
    assert message["content"][0] == {"type": "text", "text": "Describe the image."}
    assert message["content"][1]["type"] == "image_url"
    assert message["content"][1]["image_url"]["url"].startswith(
        "data:image/webp;base64,"
    )
    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}
