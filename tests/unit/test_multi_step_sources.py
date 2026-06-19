import asyncio

from apps.worker.workflows.multi_step import _collect_child_results, _merge_sources
from packages.agents.schemas import AgentRunOutput
from packages.rag.citations import CitationSource


def test_merge_sources_returns_only_structured_sources() -> None:
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

    assert merged == [citation]


def test_merge_sources_drops_legacy_only_sources() -> None:
    assert _merge_sources(["legacy-a.txt"], ["legacy-b.txt"]) == []


def test_merge_sources_renumbers_duplicate_local_citation_ids() -> None:
    first = CitationSource(
        id=7,
        document_id="document-1",
        chunk_id="chunk-1",
        filename="guide.pdf",
        chunk_index=1,
        excerpt="First evidence.",
        score=0.9,
    )
    second = CitationSource(
        id=7,
        document_id="document-2",
        chunk_id="chunk-2",
        filename="manual.pdf",
        chunk_index=2,
        excerpt="Second evidence.",
        score=0.8,
    )

    merged = _merge_sources([first], [second])

    assert [source.id for source in merged] == [1, 2]
    assert [(source.document_id, source.chunk_id) for source in merged] == [
        ("document-1", "chunk-1"),
        ("document-2", "chunk-2"),
    ]


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
