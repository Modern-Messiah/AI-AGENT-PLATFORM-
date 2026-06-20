from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field, replace
from pathlib import PurePosixPath
from urllib.parse import urljoin, urlparse

import httpx
from packages.core import settings
from packages.rag.parser import ParsedSegment
from packages.rag.visual import VisualPage, render_visual_pages, split_visual_sections
from packages.storage import DocumentAsset, DocumentAssetStatus, object_store
from packages.storage.db import tenant_session
from sqlalchemy import delete, select
from temporalio import activity

from apps.api.services.url_sources import (
    URL_SOURCE_HEADERS,
    UrlImageSource,
    UrlSourceError,
    url_image_sidecar_key,
    validate_fetch_url,
)
from apps.worker.activities.ingestion_types import IngestionInput, VisualPageAnalysis
from apps.worker.activities.visual_analysis import analyze_visual_page
from apps.worker.activities.visual_storage import upsert_document_asset

log = logging.getLogger(__name__)

_FETCH_TIMEOUT = 10.0
_MAX_REDIRECTS = 3
_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


@dataclass(frozen=True)
class UrlVisualSegmentsResult:
    segments: list[ParsedSegment]
    warnings: list[str] = field(default_factory=list)

    def __iter__(self):
        return iter(self.segments)

    def __len__(self) -> int:
        return len(self.segments)

    def __getitem__(self, index):
        return self.segments[index]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, list):
            return self.segments == other
        if isinstance(other, UrlVisualSegmentsResult):
            return self.segments == other.segments and self.warnings == other.warnings
        return NotImplemented


def _heartbeat(details: dict[str, object]) -> None:
    try:
        activity.heartbeat(details)
    except RuntimeError:
        # Unit tests and direct local calls have no Temporal activity context.
        return


def _content_type_header(value: str | None) -> str:
    if not value:
        return ""
    return value.split(";", 1)[0].strip().lower()


def _safe_image_filename(url: str, content_type: str) -> str:
    suffix = _IMAGE_TYPES.get(_content_type_header(content_type), "")
    parsed = urlparse(url)
    name = PurePosixPath(parsed.path).name
    if name and PurePosixPath(name).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        return name
    return f"url-image{suffix or '.png'}"


def _plural(value: int, singular: str, plural: str) -> str:
    return singular if value == 1 else plural


def _url_image_summary_warning(processed: int, failed: int) -> str | None:
    if failed <= 0:
        return None
    processed_label = _plural(processed, "image", "images")
    return f"{processed} URL {processed_label} processed, {failed} skipped"


def _load_url_image_sources(object_key: str) -> list[UrlImageSource] | None:
    try:
        payload = object_store.get(url_image_sidecar_key(object_key))
    except Exception as exc:
        log.debug("url image sidecar not available | object_key=%s error=%s", object_key, exc)
        return None

    try:
        parsed = json.loads(payload.decode("utf-8"))
    except Exception as exc:
        log.warning("url image sidecar is invalid | object_key=%s error=%s", object_key, exc)
        return []

    images = parsed.get("images", [])
    if not isinstance(images, list):
        return []

    sources: list[UrlImageSource] = []
    for image in images:
        if not isinstance(image, dict):
            continue
        url = str(image.get("url", "")).strip()
        if not url:
            continue
        sources.append(UrlImageSource(
            url=url,
            alt=str(image.get("alt", "")).strip()[:500],
            title=str(image.get("title", "")).strip()[:500],
        ))
    return sources


async def _clear_url_image_assets(input: IngestionInput) -> None:
    document_id = uuid.UUID(input.document_id)
    async with tenant_session(input.tenant_id) as session:
        previous_assets = (
            await session.execute(
                select(DocumentAsset).where(
                    DocumentAsset.document_id == document_id,
                    DocumentAsset.tenant_id == input.tenant_id,
                    DocumentAsset.asset_kind.in_(("image", "url_image")),
                )
            )
        ).scalars().all()
        await session.execute(
            delete(DocumentAsset).where(
                DocumentAsset.document_id == document_id,
                DocumentAsset.tenant_id == input.tenant_id,
                DocumentAsset.asset_kind.in_(("image", "url_image")),
            )
        )

    for asset in previous_assets:
        try:
            await asyncio.to_thread(object_store.delete, asset.preview_object_key)
        except Exception as exc:
            log.warning("stale URL image cleanup failed | key=%s error=%s", asset.preview_object_key, exc)


async def _fetch_url_image(source: UrlImageSource) -> tuple[bytes, str, str]:
    current_url = await validate_fetch_url(source.url)
    max_bytes = settings.url_source_image_max_bytes

    async with httpx.AsyncClient(
        timeout=_FETCH_TIMEOUT,
        follow_redirects=False,
        headers=URL_SOURCE_HEADERS,
    ) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            try:
                response = await client.get(current_url)
            except httpx.RequestError as exc:
                raise UrlSourceError(f"URL image request failed: {exc}") from exc

            if 300 <= response.status_code < 400 and response.headers.get("location"):
                current_url = await validate_fetch_url(urljoin(current_url, response.headers["location"]))
                continue

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise UrlSourceError(f"URL image returned HTTP {exc.response.status_code}") from exc

            content_type = _content_type_header(response.headers.get("content-type"))
            if content_type not in _IMAGE_TYPES:
                raise UrlSourceError("URL image content type is not supported")

            length = response.headers.get("content-length")
            if length and length.isdigit() and int(length) > max_bytes:
                raise UrlSourceError(
                    f"URL image exceeds {max_bytes // (1024 * 1024)} MB limit",
                    status_code=413,
                )

            data = response.content
            if len(data) > max_bytes:
                raise UrlSourceError(
                    f"URL image exceeds {max_bytes // (1024 * 1024)} MB limit",
                    status_code=413,
                )
            return data, content_type, _safe_image_filename(current_url, content_type)

    raise UrlSourceError("URL image redirected too many times")


async def _upsert_url_image_asset(
    input: IngestionInput,
    page: VisualPage,
    *,
    preview_object_key: str,
    analysis: VisualPageAnalysis,
) -> str:
    return await upsert_document_asset(
        input,
        page,
        preview_object_key=preview_object_key,
        analysis=analysis,
        status=DocumentAssetStatus.done,
        asset_kind="url_image",
    )


async def append_url_visual_segments(
    input: IngestionInput,
    segments: list[ParsedSegment],
) -> UrlVisualSegmentsResult:
    sources = _load_url_image_sources(input.object_key)
    if sources is None:
        return UrlVisualSegmentsResult(segments=list(segments))

    await _clear_url_image_assets(input)
    if not sources:
        log.info(
            "URL image analysis summary | tenant=%s document=%s found=0 processed=0 failed=0 segments=0",
            input.tenant_id,
            input.document_id,
        )
        return UrlVisualSegmentsResult(segments=list(segments))

    enriched = list(segments)
    processed = 0
    failed = 0
    segment_count = 0
    for index, source in enumerate(sources, start=1):
        _heartbeat({
            "document_id": input.document_id,
            "stage": "url-image-start",
            "image_index": index,
        })
        try:
            data, _content_type, filename = await _fetch_url_image(source)
            pages = await asyncio.to_thread(render_visual_pages, data, filename, 1, 1)
            if not pages:
                raise ValueError("URL image could not be rendered")
            page = replace(pages[0], page_number=index)
            analysis = await analyze_visual_page(page)
            if not analysis.text.strip():
                raise ValueError("URL image contains no extractable visual content")

            preview_key = (
                f"{input.tenant_id}/{input.document_id}/assets/"
                f"url-image-{index}.webp"
            )
            await asyncio.to_thread(
                object_store.put,
                preview_key,
                page.preview_bytes,
                "image/webp",
            )
            asset_id = await _upsert_url_image_asset(
                input,
                page,
                preview_object_key=preview_key,
                analysis=analysis,
            )
            metadata = {
                "asset_id": asset_id,
                "asset_kind": "url_image",
                "image_index": index,
                "preview_available": False,
                "source_url": source.url,
                "source_alt": source.alt,
                "source_title": source.title,
            }
            page_segments = [
                ParsedSegment(text=text, metadata=metadata)
                for text in split_visual_sections(
                    analysis.ocr_text,
                    analysis.vision_description,
                )
                if text.strip()
            ]
            enriched.extend(page_segments)
            processed += 1
            segment_count += len(page_segments)
        except Exception as exc:
            failed += 1
            log.warning(
                "URL image analysis failed | tenant=%s document=%s image=%s error=%s",
                input.tenant_id,
                input.document_id,
                source.url,
                exc,
            )
        _heartbeat({
            "document_id": input.document_id,
            "stage": "url-image-complete",
            "image_index": index,
        })
    log.info(
        "URL image analysis summary | tenant=%s document=%s found=%s processed=%s failed=%s segments=%s",
        input.tenant_id,
        input.document_id,
        len(sources),
        processed,
        failed,
        segment_count,
    )
    warnings = []
    summary_warning = _url_image_summary_warning(processed, failed)
    if summary_warning:
        warnings.append(summary_warning)
    return UrlVisualSegmentsResult(segments=enriched, warnings=warnings)
