from __future__ import annotations

import pytest
from apps.api.services import query_condensation as condensation_module
from apps.api.services.query_condensation import condense_query, render_history
from packages.core import settings


def _fake_llm(response: str | Exception) -> list[list[dict]]:
    calls: list[list[dict]] = []

    async def fake_complete(model_name: str, messages: list[dict], *, max_tokens: int) -> str:
        calls.append(messages)
        if isinstance(response, Exception):
            raise response
        return response

    return calls, fake_complete


async def test_condense_query_resolves_followup_with_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "query_condensation_enabled", True)
    calls, fake = _fake_llm('{"standalone_query": "Какие ограничения во втором документе?"}')
    monkeypatch.setattr(condensation_module, "complete_chat_json", fake)

    result = await condense_query(
        [("user", "Расскажи про документы"), ("agent", "Вот обзор двух документов…")],
        "а подробнее про второй?",
    )

    assert result == "Какие ограничения во втором документе?"
    assert len(calls) == 1
    assert "Follow-up question:" in calls[0][1]["content"]


async def test_condense_query_falls_back_to_raw_query_on_llm_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "query_condensation_enabled", True)
    _, fake = _fake_llm(RuntimeError("provider down"))
    monkeypatch.setattr(condensation_module, "complete_chat_json", fake)

    result = await condense_query([("user", "контекст")], "вопрос")

    assert result == "вопрос"


async def test_condense_query_falls_back_on_malformed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "query_condensation_enabled", True)
    _, fake = _fake_llm("not json at all")
    monkeypatch.setattr(condensation_module, "complete_chat_json", fake)

    assert await condense_query([("user", "контекст")], "вопрос") == "вопрос"


async def test_condense_query_without_history_skips_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail(*args: object, **kwargs: object) -> str:
        raise AssertionError("no history — the LLM must not be called")

    monkeypatch.setattr(condensation_module, "complete_chat_json", fail)

    assert await condense_query([], "вопрос") == "вопрос"


async def test_condense_query_disabled_by_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "query_condensation_enabled", False)

    assert await condense_query([("user", "контекст")], "вопрос") == "вопрос"


def test_render_history_caps_messages_and_chars() -> None:
    history = [
        ("user", "x" * 1000),
        ("agent", "короткий ответ"),
        ("user", "последний вопрос"),
    ]

    rendered = render_history(history)

    # newest message kept fully, long messages truncated to the char cap
    assert rendered.endswith("user: последний вопрос")
    assert len(rendered.splitlines()) == 3
    assert max(len(line) for line in rendered.splitlines()) <= len("user: ") + 400
