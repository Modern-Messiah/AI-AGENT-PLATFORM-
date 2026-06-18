from __future__ import annotations

from apps.api.services.url_sources import UrlImageSource, url_image_sidecar_payload
from apps.worker.activities.ingestion_types import IngestionInput, VisualPageAnalysis
from apps.worker.activities.url_visuals import append_url_visual_segments
from packages.rag.parser import ParsedSegment
from packages.rag.visual import VisualPage


async def test_url_visual_segments_are_hidden_from_ui_but_searchable(monkeypatch) -> None:
    input = IngestionInput(
        document_id="5ef2d843-ddaf-4ae3-a73d-d25f27fb8621",
        tenant_id="tenant-a",
        object_key="tenant-a/url-source.txt",
        filename="Example Page.txt",
    )
    source = UrlImageSource(
        url="https://docs.example.com/payment-flow.png",
        alt="Payment flow",
        title="Payment diagram",
    )

    monkeypatch.setattr(
        "apps.worker.activities.url_visuals._load_url_image_sources",
        lambda _object_key: [source],
    )

    cleared: list[str] = []
    fetched: list[str] = []
    previews: list[tuple[str, bytes, str]] = []

    async def fake_clear_assets(_input: IngestionInput) -> None:
        cleared.append(_input.document_id)

    async def fake_fetch_image(candidate: UrlImageSource):
        fetched.append(candidate.url)
        return b"png-bytes", "image/png", "payment-flow.png"

    def fake_render(data: bytes, filename: str, start_page: int, end_page: int):
        assert (data, filename, start_page, end_page) == (
            b"png-bytes",
            "payment-flow.png",
            1,
            1,
        )
        return [
            VisualPage(
                page_number=1,
                preview_bytes=b"webp-preview",
                width=640,
                height=480,
                text_layer="",
                has_visuals=True,
            )
        ]

    async def fake_analyze(page: VisualPage) -> VisualPageAnalysis:
        assert page.preview_bytes == b"webp-preview"
        return VisualPageAnalysis(
            text="Recognized text:\nОплата не найдена\n\nVisual description:\nСхема проверки оплаты.",
            ocr_text="Оплата не найдена",
            ocr_confidence=0.91,
            vision_description="Схема проверки оплаты.",
        )

    async def fake_upsert_asset(
        _input: IngestionInput,
        page: VisualPage,
        *,
        preview_object_key: str,
        analysis: VisualPageAnalysis,
    ) -> str:
        previews.append((preview_object_key, page.preview_bytes, analysis.ocr_text))
        return "asset-123"

    monkeypatch.setattr("apps.worker.activities.url_visuals._clear_url_image_assets", fake_clear_assets)
    monkeypatch.setattr("apps.worker.activities.url_visuals._fetch_url_image", fake_fetch_image)
    monkeypatch.setattr("apps.worker.activities.url_visuals.render_visual_pages", fake_render)
    monkeypatch.setattr("apps.worker.activities.url_visuals.analyze_visual_page", fake_analyze)
    monkeypatch.setattr("apps.worker.activities.url_visuals._upsert_url_image_asset", fake_upsert_asset)

    segments = await append_url_visual_segments(
        input,
        [ParsedSegment(text="Source URL: https://docs.example.com")],
    )

    assert cleared == [input.document_id]
    assert fetched == [source.url]
    assert previews == [
        (
            f"{input.tenant_id}/{input.document_id}/assets/url-image-1.webp",
            b"webp-preview",
            "Оплата не найдена",
        )
    ]
    assert [segment.text for segment in segments] == [
        "Source URL: https://docs.example.com",
        "Recognized text:\nОплата не найдена",
        "Visual description:\nСхема проверки оплаты.",
    ]
    assert segments[1].metadata == {
        "asset_id": "asset-123",
        "asset_kind": "url_image",
        "image_index": 1,
        "preview_available": False,
        "source_url": source.url,
        "source_alt": "Payment flow",
        "source_title": "Payment diagram",
    }
    assert segments[2].metadata == segments[1].metadata


async def test_missing_url_image_sidecar_keeps_original_segments(monkeypatch) -> None:
    input = IngestionInput(
        document_id="5ef2d843-ddaf-4ae3-a73d-d25f27fb8621",
        tenant_id="tenant-a",
        object_key="tenant-a/url-source.txt",
        filename="Example Page.txt",
    )
    original = [ParsedSegment(text="Only readable HTML text.")]

    monkeypatch.setattr(
        "apps.worker.activities.url_visuals.object_store.get",
        lambda _key: (_ for _ in ()).throw(FileNotFoundError("missing")),
    )

    assert await append_url_visual_segments(input, original) == original


async def test_multiple_url_images_get_distinct_asset_indexes(monkeypatch) -> None:
    input = IngestionInput(
        document_id="5ef2d843-ddaf-4ae3-a73d-d25f27fb8621",
        tenant_id="tenant-a",
        object_key="tenant-a/url-source.txt",
        filename="Example Page.txt",
    )
    sources = [
        UrlImageSource(url="https://docs.example.com/one.png"),
        UrlImageSource(url="https://docs.example.com/two.png"),
    ]
    seen_page_numbers: list[int] = []

    monkeypatch.setattr(
        "apps.worker.activities.url_visuals._load_url_image_sources",
        lambda _object_key: sources,
    )
    async def fake_clear_assets(_input: IngestionInput) -> None:
        return None

    monkeypatch.setattr("apps.worker.activities.url_visuals._clear_url_image_assets", fake_clear_assets)

    async def fake_fetch_image(candidate: UrlImageSource):
        return f"{candidate.url}-bytes".encode(), "image/png", "image.png"

    def fake_render(_data: bytes, _filename: str, _start_page: int, _end_page: int):
        return [
            VisualPage(
                page_number=1,
                preview_bytes=b"webp-preview",
                width=100,
                height=100,
                text_layer="",
                has_visuals=True,
            )
        ]

    async def fake_analyze(_page: VisualPage) -> VisualPageAnalysis:
        return VisualPageAnalysis(
            text="Recognized text:\nvisible text",
            ocr_text="visible text",
            ocr_confidence=0.9,
            vision_description="",
        )

    async def fake_upsert_asset(
        _input: IngestionInput,
        page: VisualPage,
        *,
        preview_object_key: str,
        analysis: VisualPageAnalysis,
    ) -> str:
        seen_page_numbers.append(page.page_number)
        return f"asset-{page.page_number}"

    monkeypatch.setattr("apps.worker.activities.url_visuals._fetch_url_image", fake_fetch_image)
    monkeypatch.setattr("apps.worker.activities.url_visuals.render_visual_pages", fake_render)
    monkeypatch.setattr("apps.worker.activities.url_visuals.analyze_visual_page", fake_analyze)
    monkeypatch.setattr("apps.worker.activities.url_visuals._upsert_url_image_asset", fake_upsert_asset)
    monkeypatch.setattr("apps.worker.activities.url_visuals.object_store.put", lambda *args: None)

    segments = await append_url_visual_segments(input, [])

    assert seen_page_numbers == [1, 2]
    assert [segment.metadata["image_index"] for segment in segments] == [1, 2]
    assert [segment.metadata["asset_id"] for segment in segments] == ["asset-1", "asset-2"]


def test_url_image_sidecar_payload_fixture_matches_worker_contract() -> None:
    payload = url_image_sidecar_payload([
        UrlImageSource(
            url="https://docs.example.com/payment-flow.png",
            alt="Payment flow",
            title="Payment diagram",
        )
    ])

    assert payload == (
        b'{"images":[{"url":"https://docs.example.com/payment-flow.png",'
        b'"alt":"Payment flow","title":"Payment diagram"}]}'
    )
