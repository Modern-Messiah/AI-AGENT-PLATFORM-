from packages.rag.parser import ParsedSegment
from packages.rag.summaries import build_document_insights


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
