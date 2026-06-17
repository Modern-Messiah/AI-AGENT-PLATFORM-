from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class IngestionInput:
    document_id: str
    tenant_id: str
    object_key: str
    filename: str


@dataclass
class ParsedDoc:
    # Keep this DTO JSON-like: workflow payload decoding must not depend on parser
    # runtime classes inside Temporal's sandbox.
    segments: list = field(default_factory=list)
    text: str = ""
    summary: str = ""
    suggested_questions: list = field(default_factory=list)


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
