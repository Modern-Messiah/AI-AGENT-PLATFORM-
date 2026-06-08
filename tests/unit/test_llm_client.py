from packages.llm.client import _provider_extra_body, _provider_error_message, _resolve_model


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
