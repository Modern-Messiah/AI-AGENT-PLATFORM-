from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import fitz
from PIL import Image, ImageDraw, ImageFont

DATASET_PATH = Path(__file__).resolve().parents[1] / "datasets" / "golden_rag_ocr_vision.json"
GITHUB_DATASET_PATH = Path(__file__).resolve().parents[1] / "datasets" / "golden_github.json"
_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)


@dataclass(frozen=True)
class FixtureArtifact:
    source_id: str
    path: Path
    upload_kind: str
    content_type: str


@dataclass(frozen=True)
class EvalChunk:
    source_id: str | None
    document_id: str
    filename: str
    content: str
    score: float
    page: int | None = None
    asset_kind: str | None = None


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    query: str
    passed: bool
    failures: list[str]
    found_source_ids: list[str]
    matched_substrings: list[str]
    top_chunks: list[dict[str, object]]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _replace_placeholders(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        output = value
        for needle, replacement in replacements.items():
            output = output.replace(needle, replacement)
        return output
    if isinstance(value, list):
        return [_replace_placeholders(item, replacements) for item in value]
    if isinstance(value, dict):
        return {
            key: _replace_placeholders(item, replacements)
            for key, item in value.items()
        }
    return value


def load_golden_cases(
    path: Path = DATASET_PATH,
    *,
    extra_paths: list[Path] | None = None,
    replacements: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    for extra_path in extra_paths or []:
        cases.extend(json.loads(extra_path.read_text(encoding="utf-8")))
    if replacements:
        cases = [_replace_placeholders(case, replacements) for case in cases]
    return cases


def resolve_eval_font_path() -> Path | None:
    for candidate in _FONT_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            return path
    return None


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def evaluate_case(case: dict[str, Any], chunks: list[EvalChunk]) -> CaseResult:
    case_id = str(case["id"])
    query = str(case["query"])
    failures: list[str] = []
    found_source_ids = _unique([
        chunk.source_id or chunk.filename
        for chunk in chunks
        if chunk.source_id or chunk.filename
    ])
    matched_substrings: list[str] = []

    if case.get("expect_no_results") is True:
        if chunks:
            failures.append(f"expected no retrieval results, got {len(chunks)}")
        return CaseResult(
            case_id=case_id,
            query=query,
            passed=not failures,
            failures=failures,
            found_source_ids=found_source_ids,
            matched_substrings=[],
            top_chunks=_top_chunk_payloads(chunks),
        )

    expected_source_ids = [str(value) for value in case.get("expected_source_ids", [])]
    forbidden_source_ids = [str(value) for value in case.get("forbidden_source_ids", [])]
    expected_pages = [int(value) for value in case.get("expected_pages", [])]
    expected_asset_kind = case.get("expected_asset_kind")
    combined_text = _normalize_text("\n".join(chunk.content for chunk in chunks))

    for source_id in expected_source_ids:
        if source_id not in found_source_ids:
            failures.append(f"missing expected source: {source_id}")

    for source_id in forbidden_source_ids:
        if source_id in found_source_ids:
            failures.append(f"forbidden source retrieved: {source_id}")

    for substring in [str(value) for value in case.get("expected_substrings", [])]:
        if _normalize_text(substring) in combined_text:
            matched_substrings.append(substring)
        else:
            failures.append(f"missing expected substring: {substring}")

    if expected_pages:
        found_pages = {
            chunk.page
            for chunk in chunks
            if chunk.page is not None and (not expected_source_ids or chunk.source_id in expected_source_ids)
        }
        for page in expected_pages:
            if page not in found_pages:
                failures.append(f"missing expected page: {page}")

    if expected_asset_kind:
        if not any(chunk.asset_kind == expected_asset_kind for chunk in chunks):
            failures.append(f"missing expected asset kind: {expected_asset_kind}")

    return CaseResult(
        case_id=case_id,
        query=query,
        passed=not failures,
        failures=failures,
        found_source_ids=found_source_ids,
        matched_substrings=matched_substrings,
        top_chunks=_top_chunk_payloads(chunks),
    )


def summarize_results(results: list[CaseResult]) -> dict[str, object]:
    total = len(results)
    passed = sum(1 for result in results if result.passed)
    failed = total - passed
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
    }


def _top_chunk_payloads(chunks: list[EvalChunk], limit: int = 5) -> list[dict[str, object]]:
    return [
        {
            "source_id": chunk.source_id,
            "document_id": chunk.document_id,
            "filename": chunk.filename,
            "score": round(chunk.score, 4),
            "page": chunk.page,
            "asset_kind": chunk.asset_kind,
            "excerpt": re.sub(r"\s+", " ", chunk.content).strip()[:320],
        }
        for chunk in chunks[:limit]
    ]


def generate_fixture_files(output_dir: Path) -> dict[str, FixtureArtifact]:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "linux_text": _write_linux_text(output_dir / "golden_linux.txt"),
        "vim_text": _write_vim_text(output_dir / "golden_vim.txt"),
        "scan_pdf": _write_scan_pdf(output_dir / "golden_scan_ru.pdf"),
        "schema_pdf": _write_schema_pdf(output_dir / "golden_schema.pdf"),
        "table_pdf": _write_table_pdf(output_dir / "golden_table.pdf"),
        "url_image_page": _write_url_image_fixture(output_dir),
    }
    return artifacts


def _write_linux_text(path: Path) -> FixtureArtifact:
    path.write_text(
        "\n".join([
            "Golden Linux command notes.",
            "GOLDEN_LINUX_PWD: команда pwd показывает текущую директорию shell.",
            "Команда cd меняет каталог, а ls показывает файлы.",
        ]),
        encoding="utf-8",
    )
    return FixtureArtifact("linux_text", path, "file", "text/plain")


def _write_vim_text(path: Path) -> FixtureArtifact:
    path.write_text(
        "\n".join([
            "Golden Vim notes.",
            "GOLDEN_VIM_VISUAL: клавиша v включает visual mode в Vim.",
            "Клавиша V включает line visual mode, а Ctrl+v включает block visual mode.",
        ]),
        encoding="utf-8",
    )
    return FixtureArtifact("vim_text", path, "file", "text/plain")


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_path = resolve_eval_font_path()
    if font_path is not None:
        return ImageFont.truetype(str(font_path), size=size)
    return ImageFont.load_default(size=size)


def _png_with_lines(lines: list[str], *, size: tuple[int, int] = (1400, 900)) -> bytes:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    y = 120
    for line in lines:
        draw.text((90, y), line, fill="black", font=_font(62))
        y += 110
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _write_scan_pdf(path: Path) -> FixtureArtifact:
    image_bytes = _png_with_lines([
        "СКАН МАЯК 42",
        "Проверка OCR русского текста",
        "Документ без текстового слоя",
    ])
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=image_bytes)
    doc.save(path)
    doc.close()
    return FixtureArtifact("scan_pdf", path, "file", "application/pdf")


def _insert_text(
    page: fitz.Page,
    point: tuple[float, float],
    text: str,
    *,
    fontsize: float,
) -> None:
    font_path = resolve_eval_font_path()
    kwargs: dict[str, object] = {"fontsize": fontsize}
    if font_path is not None:
        kwargs["fontname"] = "EvalUnicode"
        kwargs["fontfile"] = str(font_path)
    page.insert_text(point, text, **kwargs)


def _insert_textbox(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    *,
    fontsize: float,
    align: int = 0,
) -> None:
    font_path = resolve_eval_font_path()
    kwargs: dict[str, object] = {"fontsize": fontsize, "align": align}
    if font_path is not None:
        kwargs["fontname"] = "EvalUnicode"
        kwargs["fontfile"] = str(font_path)
    page.insert_textbox(rect, text, **kwargs)


def _insert_box(page: fitz.Page, rect: fitz.Rect, text: str) -> None:
    page.draw_rect(rect, color=(0, 0, 0), width=1.0)
    _insert_textbox(page, rect + (4, 4, -4, -4), text, fontsize=10, align=1)


def _write_schema_pdf(path: Path) -> FixtureArtifact:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    _insert_text(page, (72, 60), "PAYMENT_FLOW_GOLDEN: Схема проверки оплаты", fontsize=16)
    boxes = [
        (fitz.Rect(70, 120, 230, 175), "NEW_TICKET\nНовый тикет? Да"),
        (fitz.Rect(310, 120, 470, 175), "INTERNET_DOWN\nне работает интернет"),
        (fitz.Rect(70, 250, 230, 305), "CHECK_PAYMENT\nПроверка оплаты"),
        (fitz.Rect(310, 250, 470, 305), "NO_PAYMENT\nНет оплаты"),
        (fitz.Rect(190, 390, 390, 445), "RESTART_ROUTER\nперезагрузка роутера"),
    ]
    for rect, text in boxes:
        _insert_box(page, rect, text)
    lines = [
        ((230, 147), (310, 147)),
        ((150, 175), (150, 250)),
        ((230, 277), (310, 277)),
        ((390, 305), (320, 390)),
    ]
    for start, end in lines:
        page.draw_line(fitz.Point(*start), fitz.Point(*end), color=(0, 0, 0), width=1.2)
    doc.save(path)
    doc.close()
    return FixtureArtifact("schema_pdf", path, "file", "application/pdf")


def _write_table_pdf(path: Path) -> FixtureArtifact:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    _insert_text(page, (72, 60), "GOLDEN_TABLE_PLAN: Тарифная таблица", fontsize=16)
    rows = [
        ["Plan", "Speed", "Price"],
        ["Basic", "50 Mbps", "4900"],
        ["Premium", "200 Mbps", "9900"],
        ["Business", "500 Mbps", "19900"],
    ]
    left, top = 72, 120
    col_widths = [140, 140, 140]
    row_height = 42
    for row_index, row in enumerate(rows):
        y = top + row_index * row_height
        x = left
        for col_index, value in enumerate(row):
            rect = fitz.Rect(x, y, x + col_widths[col_index], y + row_height)
            page.draw_rect(rect, color=(0, 0, 0), width=1.0)
            _insert_textbox(page, rect + (6, 10, -6, -6), value, fontsize=11)
            x += col_widths[col_index]
    doc.save(path)
    doc.close()
    return FixtureArtifact("table_pdf", path, "file", "application/pdf")


def _write_url_image_fixture(output_dir: Path) -> FixtureArtifact:
    image_path = output_dir / "golden_url_image.png"
    image_path.write_bytes(_png_with_lines([
        "URL_IMAGE_GOLDEN",
        "restart router",
        "hidden page image should be searchable",
    ], size=(1400, 640)))
    html_path = output_dir / "golden_url_image.html"
    html_path.write_text(
        (
            "<!doctype html><html><head><title>Golden URL Image</title></head>"
            "<body><h1>Golden URL source</h1>"
            "<p>URL_PAGE_GOLDEN_TEXT: visible HTML text for retrieval.</p>"
            '<img src="/golden_url_image.png" width="1400" height="640" '
            'alt="Router action diagram">'
            "</body></html>"
        ),
        encoding="utf-8",
    )
    return FixtureArtifact("url_image_page", html_path, "url", "text/html")
