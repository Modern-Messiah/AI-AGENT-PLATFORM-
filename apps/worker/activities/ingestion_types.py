from __future__ import annotations

from dataclasses import dataclass, field

from packages.rag.parser import ParsedSegment
from packages.rag.summaries import DocumentInsights


@dataclass
class IngestionInput:
    document_id: str
    tenant_id: str
    object_key: str
    filename: str


@dataclass
class ParsedDoc:
    # `text` remains for Temporal compatibility with already-produced activity results.
    segments: list[ParsedSegment] = field(default_factory=list)
    text: str = ""
    insights: DocumentInsights = field(default_factory=DocumentInsights)


@dataclass
class ChunkBatch:
    contents: list[str]
    embeddings: list[list[float]]
    metadata: list[dict] = field(default_factory=list)
    summary: str = ""
    suggested_questions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VisualBatchRef:
    object_key: str
    processed_pages: int
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VisualManifest:
    is_visual: bool
    total_pages: int = 0
    batches: list[tuple[int, int]] = field(default_factory=list)


@dataclass(frozen=True)
class VisualBatchInput:
    ingestion: IngestionInput
    start_page: int
    end_page: int


@dataclass(frozen=True)
class VisualPageAnalysis:
    text: str
    ocr_text: str
    ocr_confidence: float | None
    vision_description: str
    warning: str | None = None
    ocr_latency_ms: int = 0
    vision_latency_ms: int = 0
