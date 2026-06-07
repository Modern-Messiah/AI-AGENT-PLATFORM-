from packages.rag.summaries import NotebookInsightSource, build_notebook_insights


def test_build_notebook_insights_combines_document_summaries() -> None:
    insights = build_notebook_insights(
        [
            NotebookInsightSource(
                filename="q1.pdf",
                summary="Revenue grew by 24 percent in Q1. Enterprise demand improved.",
                suggested_questions=["Какие факты есть в q1.pdf?"],
            ),
            NotebookInsightSource(
                filename="plan.md",
                summary="Expansion focuses on enterprise customers and onboarding.",
                suggested_questions=["Какие выводы можно сделать из plan.md?"],
            ),
        ],
        title="Product research",
    )

    assert insights.summary.startswith("q1.pdf: Revenue grew by 24 percent in Q1.")
    assert len(insights.summary) <= 900
    assert insights.suggested_questions == [
        "Что объединяет документы в Product research?",
        "Какие ключевые темы повторяются в Product research?",
        "Какие выводы можно сделать по коллекции Product research?",
    ]
    assert "Revenue" in insights.key_topics
    assert "Enterprise" in insights.key_topics


def test_build_notebook_insights_handles_empty_sources() -> None:
    insights = build_notebook_insights([], title="Empty")

    assert insights.summary == ""
    assert insights.suggested_questions == []
    assert insights.key_topics == []
