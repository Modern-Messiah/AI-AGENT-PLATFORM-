import json

from packages.rag.summaries import (
    NotebookInsightSource,
    generate_notebook_insights,
)


async def test_generate_notebook_insights_uses_all_source_chunks() -> None:
    calls: list[tuple[str, list[dict[str, str]], int]] = []

    async def fake_complete(
        model_name: str,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
    ) -> str:
        calls.append((model_name, messages, max_tokens))
        return json.dumps(
            {
                "summary": (
                    "Коллекция объединяет справочники по командной строке Linux и редактору Vim. "
                    "Вместе они помогают быстрее работать в терминале и редактировать файлы."
                ),
                "key_topics": ["Linux", "Bash", "Vim"],
                "suggested_questions": [
                    "Какие команды Linux чаще всего нужны для работы с файлами?",
                    "Какие сочетания клавиш Vim ускоряют редактирование?",
                    "Как совместно использовать команды Bash и Vim?",
                ],
            },
            ensure_ascii=False,
        )

    insights = await generate_notebook_insights(
        [
            NotebookInsightSource(
                filename="linux.pdf",
                summary="",
                chunks=["uname -a shows system and kernel information."],
            ),
            NotebookInsightSource(
                filename="vim.pdf",
                summary="",
                chunks=["Use h, j, k and l to move the cursor in Vim."],
            ),
        ],
        title="Команды",
        complete_json=fake_complete,
    )

    assert calls[0][0] == "deepseek/deepseek-v4-flash"
    assert calls[0][2] == 1200
    prompt = calls[0][1][-1]["content"]
    assert "linux.pdf" in prompt
    assert "uname -a" in prompt
    assert "vim.pdf" in prompt
    assert "h, j, k and l" in prompt
    assert insights.key_topics == ["Linux", "Bash", "Vim"]
    assert len(insights.suggested_questions) == 3


async def test_generate_notebook_insights_returns_empty_without_source_text() -> None:
    async def should_not_run(
        model_name: str,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
    ) -> str:
        raise AssertionError("DeepSeek should not run without source text")

    insights = await generate_notebook_insights(
        [NotebookInsightSource(filename="empty.pdf")],
        title="Empty",
        complete_json=should_not_run,
    )

    assert insights.summary == ""
    assert insights.key_topics == []
    assert insights.suggested_questions == []
