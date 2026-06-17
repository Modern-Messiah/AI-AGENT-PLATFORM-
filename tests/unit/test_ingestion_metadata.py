from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from apps.worker.activities import ingestion
from apps.worker.activities import ingestion_status
from apps.worker.activities import visual_analysis
from apps.worker.activities.ingestion import (
    IngestionInput,
    ParsedDoc,
    VisualBatchRef,
    VisualPageAnalysis,
    _await_with_heartbeat,
    analyze_visual_page,
    chunk_and_embed,
    mark_done,
    mark_failed,
)
from packages.rag.parser import ParsedSegment
from packages.rag.summaries import DocumentInsights
from packages.rag.visual import OCRResult, VisualPage
from temporalio.converter import default


def test_parsed_doc_round_trips_through_temporal_payload_converter() -> None:
    converter = default().payload_converter
    parsed = ParsedDoc(
        segments=[
            ParsedSegment(
                text="Page four evidence.",
                metadata={"page": 4},
            )
        ],
        insights=DocumentInsights(summary="Page four evidence summary."),
    )

    payloads = converter.to_payloads([parsed])
    [decoded] = converter.from_payloads(payloads, type_hints=[ParsedDoc])

    assert decoded.segments[0].text == "Page four evidence."
    assert decoded.segments[0].metadata == {"page": 4}
    assert decoded.insights.summary == "Page four evidence summary."


def test_visual_batch_reference_round_trips_through_temporal() -> None:
    converter = default().payload_converter
    result = VisualBatchRef(
        object_key="tenant/document/visual-batches/1-4.json",
        processed_pages=4,
        warnings=["page 3: OCR failed"],
    )

    payloads = converter.to_payloads([result])
    [decoded] = converter.from_payloads(payloads, type_hints=[VisualBatchRef])

    assert decoded == result


async def test_long_page_analysis_heartbeats_until_completion(monkeypatch) -> None:
    heartbeats: list[dict[str, object]] = []
    monkeypatch.setattr(visual_analysis.activity, "heartbeat", heartbeats.append)

    async def slow_analysis() -> VisualPageAnalysis:
        await asyncio.sleep(0.03)
        return VisualPageAnalysis(
            text="done",
            ocr_text="done",
            ocr_confidence=0.9,
            vision_description="",
        )

    result = await _await_with_heartbeat(
        slow_analysis(),
        details={"page": 4, "stage": "ocr-vision"},
        interval_seconds=0.005,
    )

    assert result.text == "done"
    assert len(heartbeats) >= 2
    assert heartbeats[-1] == {"page": 4, "stage": "ocr-vision"}


async def test_text_layer_skips_ocr_and_vision() -> None:
    calls = []

    def fake_ocr(_image: bytes) -> OCRResult:
        calls.append("ocr")
        return OCRResult(text="unused", confidence=0.9)

    async def fake_vision(_image: bytes, _mime: str, *, prompt: str) -> str:
        calls.append(("vision", prompt))
        return "unused"

    page = VisualPage(
        page_number=2,
        preview_bytes=b"webp",
        width=100,
        height=200,
        text_layer=("Useful text layer " * 20).strip(),
        has_visuals=False,
    )

    result = await analyze_visual_page(
        page,
        ocr_reader=fake_ocr,
        vision_reader=fake_vision,
    )

    assert result == VisualPageAnalysis(
        text=page.text_layer,
        ocr_text=page.text_layer,
        ocr_confidence=1.0,
        vision_description="",
        ocr_latency_ms=0,
        vision_latency_ms=0,
    )
    assert calls == []


async def test_low_confidence_ocr_uses_vision_description() -> None:
    def fake_ocr(_image: bytes) -> OCRResult:
        return OCRResult(text="Схема", confidence=0.51)

    async def fake_vision(_image: bytes, _mime: str, *, prompt: str) -> str:
        assert "page 3" in prompt
        assert "nodes, conditions, directed transitions, and loops" in prompt
        assert "same language as the page" in prompt
        assert "Do not reconstruct or infer diagrams that are only mentioned" in prompt
        return "A deployment diagram with API and database nodes."

    page = VisualPage(
        page_number=3,
        preview_bytes=b"webp",
        width=100,
        height=200,
        text_layer="",
        has_visuals=True,
    )

    result = await analyze_visual_page(
        page,
        ocr_reader=fake_ocr,
        vision_reader=fake_vision,
    )

    assert result.ocr_confidence == 0.51
    assert result.ocr_latency_ms >= 0
    assert result.vision_latency_ms >= 0
    assert "Recognized text:\nСхема" in result.text
    assert "Visual description:\nA deployment diagram" in result.text


async def test_chunk_and_embed_preserves_segment_metadata(monkeypatch) -> None:
    async def fake_embed_texts(contents: list[str]) -> list[list[float]]:
        return [[float(index)] for index, _ in enumerate(contents)]

    monkeypatch.setattr(ingestion, "embed_texts", fake_embed_texts)
    parsed = ParsedDoc(
        segments=[
            ParsedSegment(
                text=("Page four evidence. " * 180).strip(),
                metadata={"page": 4},
            )
        ],
        insights=DocumentInsights(
            summary="Page four evidence summary.",
            suggested_questions=["Что есть на странице 4?"],
        ),
    )

    batch = await chunk_and_embed(parsed)

    assert len(batch.contents) > 1
    assert len(batch.contents) == len(batch.embeddings) == len(batch.metadata)
    assert all(
        metadata == {
            "page": 4,
            "embedding_model": ingestion.settings.embedding_model,
        }
        for metadata in batch.metadata
    )
    assert batch.summary == "Page four evidence summary."
    assert batch.suggested_questions == ["Что есть на странице 4?"]


class _FakeSession:
    def __init__(self, results=None) -> None:
        self.results = list(results or [])
        self.statements = []

    async def execute(self, statement) -> None:
        self.statements.append(statement)
        if self.results:
            return self.results.pop(0)
        return None


class _FakeTenantSession:
    def __init__(self, results=None) -> None:
        self.session = _FakeSession(results)

    async def __aenter__(self) -> _FakeSession:
        return self.session

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


async def test_mark_done_invalidates_tenant_semantic_cache(monkeypatch) -> None:
    tenant_session = _FakeTenantSession([None, _ScalarListResult([])])
    cleared: list[str] = []

    monkeypatch.setattr(ingestion_status, "tenant_session", lambda tenant_id: tenant_session)

    async def fake_clear(tenant_id: str) -> None:
        cleared.append(tenant_id)

    monkeypatch.setattr(ingestion_status.semantic_cache, "clear", fake_clear)

    await mark_done(
        IngestionInput(
            document_id="5ef2d843-ddaf-4ae3-a73d-d25f27fb8621",
            tenant_id="tenant-a",
            object_key="tenant-a/file.pdf",
            filename="file.pdf",
        )
    )

    assert cleared == ["tenant-a"]
    assert "documents.tenant_id" in str(tenant_session.session.statements[0])


async def test_mark_failed_update_is_explicitly_tenant_scoped(monkeypatch) -> None:
    tenant_session = _FakeTenantSession()
    monkeypatch.setattr(ingestion_status, "tenant_session", lambda tenant_id: tenant_session)

    await mark_failed(
        IngestionInput(
            document_id="5ef2d843-ddaf-4ae3-a73d-d25f27fb8621",
            tenant_id="tenant-a",
            object_key="tenant-a/file.pdf",
            filename="file.pdf",
        ),
        "OCR failed",
    )

    assert "documents.tenant_id" in str(tenant_session.session.statements[0])


class _ScalarListResult:
    def __init__(self, values) -> None:
        self.values = values

    def scalars(self):
        return self

    def all(self):
        return self.values


async def test_mark_done_invalidates_linked_notebook_insights(monkeypatch) -> None:
    document_id = "5ef2d843-ddaf-4ae3-a73d-d25f27fb8621"
    notebook = SimpleNamespace(
        id="notebook-a",
        title="Product research",
        summary="Old stale overview.",
        suggested_questions=["Old question?"],
        key_topics=["Old"],
        insights_updated_at=None,
        updated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )
    tenant_session = _FakeTenantSession(
        [
            None,
            _ScalarListResult([notebook]),
        ]
    )

    monkeypatch.setattr(ingestion_status, "tenant_session", lambda tenant_id: tenant_session)

    async def fake_clear(tenant_id: str) -> None:
        return None

    monkeypatch.setattr(ingestion_status.semantic_cache, "clear", fake_clear)

    await mark_done(
        IngestionInput(
            document_id=document_id,
            tenant_id="tenant-a",
            object_key="tenant-a/file.pdf",
            filename="file.pdf",
        )
    )

    assert notebook.summary is None
    assert notebook.suggested_questions == []
    assert notebook.key_topics == []
    assert notebook.insights_updated_at is None
