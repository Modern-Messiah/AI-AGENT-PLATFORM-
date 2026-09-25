from packages.rag.parser import ParsedSegment
from packages.rag.summaries import build_document_insights, generate_document_insights


def test_build_document_insights_creates_summary_and_questions() -> None:
    segments = [
        ParsedSegment(
            text=(
                "Revenue grew by 24 percent in Q1. Operating margin improved. "
                "The company plans to expand into enterprise customers. "
                "Customer churn declined after onboarding changes."
            )
        )
    ]

    insights = build_document_insights(segments, filename="report.pdf")

    assert insights.summary.startswith("Revenue grew by 24 percent in Q1.")
    assert len(insights.summary) <= 700
    assert insights.suggested_questions == [
        "Кратко объясни, что внутри report.pdf?",
        "Какие ключевые факты есть в report.pdf?",
        "Какие выводы можно сделать из report.pdf?",
    ]


def test_build_document_insights_handles_empty_segments() -> None:
    insights = build_document_insights([], filename="empty.pdf")

    assert insights.summary == ""
    assert insights.suggested_questions == []


async def test_generate_document_insights_uses_llm_when_enabled(monkeypatch) -> None:
    from packages.core import settings
    from packages.rag.parser import ParsedSegment

    monkeypatch.setattr(settings, "ai_document_insights_enabled", True)

    async def fake_complete(model, messages, *, max_tokens):
        assert "report.pdf" in messages[1]["content"]
        return (
            '{"summary": "Инструкция по развёртыванию сервиса с требованиями к среде.", '
            '"suggested_questions": ["Какие требования к среде?", "Как запустить сервис?", "Где хранятся логи?"]}'
        )

    segments = [ParsedSegment(text="Deploy guide. " * 40, metadata={})]
    insights = await generate_document_insights(
        segments, filename="report.pdf", complete_json=fake_complete
    )

    assert "разворачиванию" in insights.summary or "сервис" in insights.summary
    assert len(insights.suggested_questions) == 3


async def test_generate_document_insights_falls_back_on_bad_json(monkeypatch) -> None:
    from packages.core import settings
    from packages.rag.parser import ParsedSegment

    monkeypatch.setattr(settings, "ai_document_insights_enabled", True)

    async def broken_complete(model, messages, *, max_tokens):
        return "not json"

    segments = [
        ParsedSegment(
            text="Требования к среде. Нужен Python 3.12. Запуск через uvicorn.", metadata={}
        )
    ]
    segments = [segments[0]] * 20
    insights = await generate_document_insights(
        segments, filename="guide.txt", complete_json=broken_complete
    )
    heuristic = build_document_insights(segments, filename="guide.txt")
    assert insights.summary == heuristic.summary
    assert insights.suggested_questions == heuristic.suggested_questions


async def test_generate_document_insights_skips_llm_for_short_documents() -> None:
    from packages.rag.parser import ParsedSegment

    async def fail_complete(model, messages, *, max_tokens):
        raise AssertionError("short documents must use the heuristic directly")

    segments = [ParsedSegment(text="короткий текст", metadata={})]
    insights = await generate_document_insights(
        segments, filename="tiny.txt", complete_json=fail_complete
    )
    assert insights.summary
