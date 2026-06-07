from apps.worker.workflows.multi_step import _merge_sources
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
