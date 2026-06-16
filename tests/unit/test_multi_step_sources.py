import asyncio

from apps.worker.workflows.multi_step import _collect_child_results, _merge_sources
from packages.agents.schemas import AgentRunOutput
from packages.rag.citations import CitationSource


def test_merge_sources_deduplicates_legacy_and_structured_sources() -> None:
    citation = CitationSource(
        id=1,
        document_id="document-1",
        chunk_id="chunk-1",
        filename="guide.pdf",
        page=3,
        chunk_index=4,
        excerpt="Grounded evidence.",
        score=0.9,
    )

    merged = _merge_sources(["legacy.txt", citation], [citation, "legacy.txt"])

    assert merged == ["legacy.txt", citation]


async def test_collect_child_results_awaits_child_handles_instead_of_calling_result() -> None:
    first = AgentRunOutput(answer="first", confidence=0.8)
    second = AgentRunOutput(answer="second", confidence=0.8)

    async def resolve_later(value: AgentRunOutput) -> AgentRunOutput:
        await asyncio.sleep(0)
        return value

    handles = [
        asyncio.create_task(resolve_later(first)),
        asyncio.create_task(resolve_later(second)),
    ]

    results = await _collect_child_results(handles)

    assert results == [first, second]
