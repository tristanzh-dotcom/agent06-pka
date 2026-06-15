import mimetypes
from pathlib import Path
import re
from typing import Any, Optional

from engine.models import ParseResult, PreChunkedParseRecord
from engine.org_chart import (
    PdfTextBlock,
    generate_projection_text,
    infer_layout_hierarchy,
    merge_pdf_blocks,
    select_org_chart_title,
)


TEXT_TYPES = {".txt": "txt", ".md": "md"}
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp"}
ORG_CHART_MAX_PRE_CHUNK_CHARS = 3500


def parse_text(text: str, source_name: str = "manual_input") -> ParseResult:
    return ParseResult(
        text=text,
        source_name=source_name,
        source_type="text",
        metadata={"input": "manual"},
    )


async def parse_file(file_path: str, mime_type: Optional[str] = None, ocr_client: Any = None) -> ParseResult:
    path = Path(file_path)
    suffix = path.suffix.lower()
    detected_mime = mime_type or mimetypes.guess_type(str(path))[0] or ""

    try:
        if suffix in TEXT_TYPES:
            return ParseResult(
                text=path.read_text(encoding="utf-8"),
                source_name=path.name,
                source_type=TEXT_TYPES[suffix],
                metadata={"mime_type": detected_mime},
            )
        if suffix == ".docx":
            return _parse_docx(path)
        if suffix == ".pptx":
            return _parse_pptx(path)
        if suffix == ".pdf":
            return _parse_pdf(path)
        if suffix == ".xlsx":
            return _parse_xlsx(path)
        if suffix in IMAGE_TYPES or detected_mime.startswith("image/"):
            if ocr_client is None:
                raise ValueError("OCR client is required for image parsing")
            text = await ocr_client.extract([str(path)])
            return ParseResult(
                text=text,
                source_name=path.name,
                source_type="image",
                metadata={"ocr": True, "mime_type": detected_mime},
            )
    except ValueError:
        raise
    except RuntimeError:
        raise
    except Exception as exc:
        raise ValueError(f"Failed to parse {path.name}: {exc}") from exc

    raise ValueError(f"Unsupported file type: {path.suffix or detected_mime}")


def _parse_docx(path: Path) -> ParseResult:
    import docx

    document = docx.Document(path)
    paragraphs = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    return ParseResult(
        text="\n".join(paragraphs),
        source_name=path.name,
        source_type="docx",
        metadata={"paragraph_count": len(paragraphs)},
    )


def _parse_pptx(path: Path) -> ParseResult:
    import pptx

    presentation = pptx.Presentation(path)
    texts = []
    for slide_number, slide in enumerate(presentation.slides, start=1):
        slide_texts = []
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text.strip():
                slide_texts.append(shape.text.strip())
        if slide_texts:
            texts.append(f"## Slide {slide_number}\n" + "\n".join(slide_texts))
    return ParseResult(
        text="\n\n".join(texts),
        source_name=path.name,
        source_type="pptx",
        metadata={"slide_count": len(presentation.slides)},
    )


def _parse_pdf(path: Path) -> ParseResult:
    import fitz
    from engine.quality import assess_pdf_quality, clean_pdf_text

    document = fitz.open(path)
    pages = []
    pre_chunks = []
    try:
        for page_number, page in enumerate(document, start=1):
            page_text = page.get_text().strip()
            raw_blocks = page.get_text("blocks")
            if page_text:
                blocks = _pdf_text_blocks(raw_blocks, page_number)
                if _detect_org_chart_page(page_text, blocks):
                    pre_chunks.extend(
                        _org_chart_pre_chunks(
                            source_name=path.name,
                            page_number=page_number,
                            page_text=page_text,
                            blocks=blocks,
                            page_height=_page_height(page, blocks),
                        )
                    )
                    continue
                pages.append(page_text)
        page_count = document.page_count
    finally:
        document.close()
    raw_text = "\n\n".join(pages)
    cleaned_text = clean_pdf_text(raw_text, page_texts=pages, page_count=page_count)
    quality = assess_pdf_quality(raw_text, cleaned_text, page_count, len(pages))
    return ParseResult(
        text=cleaned_text,
        source_name=path.name,
        source_type="pdf",
        metadata={
            "page_count": page_count,
            "non_empty_pages": len(pages),
            "quality_status": quality.status,
            "quality_action": quality.action,
            "org_chart_pages": [record.metadata["page"] for record in pre_chunks],
            "org_chart_chunks": len(pre_chunks),
            "org_chart_mode": "pdf_layout_fallback" if pre_chunks else "",
        },
        quality=quality,
        pre_chunks=pre_chunks,
    )


def _parse_xlsx(path: Path) -> ParseResult:
    import openpyxl

    workbook = openpyxl.load_workbook(path, data_only=True)
    sections = []
    for sheet in workbook.worksheets:
        rows = [[_cell_to_text(cell) for cell in row] for row in sheet.iter_rows(values_only=True)]
        rows = [row for row in rows if any(cell for cell in row)]
        if not rows:
            continue
        width = max(len(row) for row in rows)
        normalized = [row + [""] * (width - len(row)) for row in rows]
        header = normalized[0]
        body = normalized[1:]
        table = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(["---"] * width) + " |",
        ]
        table.extend("| " + " | ".join(row) + " |" for row in body)
        sections.append(f"## Sheet: {sheet.title}\n" + "\n".join(table))
    return ParseResult(
        text="\n\n".join(sections),
        source_name=path.name,
        source_type="xlsx",
        metadata={"sheet_count": len(workbook.worksheets)},
    )


def _cell_to_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _pdf_text_blocks(raw_blocks, page_number: int) -> list[PdfTextBlock]:
    blocks = []
    for raw in raw_blocks or []:
        if len(raw) < 5:
            continue
        x0, y0, x1, y1, text = raw[:5]
        cleaned = str(text).strip()
        if not cleaned:
            continue
        blocks.append(
            PdfTextBlock(
                text=cleaned,
                x0=float(x0),
                y0=float(y0),
                x1=float(x1),
                y1=float(y1),
                font_size=max(1.0, min(18.0, float(y1) - float(y0))),
                page=page_number,
            )
        )
    return blocks


def _page_height(page, blocks: list[PdfTextBlock]) -> float:
    rect = getattr(page, "rect", None)
    height = getattr(rect, "height", None)
    if height:
        return float(height)
    return max((block.y1 for block in blocks), default=0.0)


def _detect_org_chart_page(page_text: str, blocks: list[PdfTextBlock]) -> bool:
    normalized = page_text.upper()
    if re.search(r"\bORG(?:ANISATION|ANIZATION)?\s+CHART\b", normalized):
        return True
    short_blocks = [block for block in blocks if len(block.text) <= 32]
    if len(short_blocks) < 12:
        return False
    y_bands = _count_y_bands(short_blocks)
    x_centers = {round(block.x_center / 80) for block in short_blocks}
    short_ratio = len(short_blocks) / max(len(blocks), 1)
    return short_ratio >= 0.65 and y_bands >= 3 and len(x_centers) >= 3


def _count_y_bands(blocks: list[PdfTextBlock], tolerance: float = 10.0) -> int:
    bands: list[float] = []
    for block in sorted(blocks, key=lambda item: item.y_center):
        for index, center in enumerate(bands):
            if abs(block.y_center - center) <= tolerance:
                bands[index] = (center + block.y_center) / 2
                break
        else:
            bands.append(block.y_center)
    return len(bands)


def _org_chart_pre_chunks(
    *,
    source_name: str,
    page_number: int,
    page_text: str,
    blocks: list[PdfTextBlock],
    page_height: float,
) -> list[PreChunkedParseRecord]:
    title, cleaned_blocks = select_org_chart_title(blocks, page_height)
    candidate_blocks = cleaned_blocks or blocks
    nodes = merge_pdf_blocks(candidate_blocks)
    edges = infer_layout_hierarchy(nodes)
    projection = generate_projection_text(
        source_name=source_name,
        source_page=page_number,
        title=title,
        extraction_mode="pdf_layout_fallback",
        confidence="medium",
        nodes=nodes,
        edges=edges,
        warnings=[
            "native_pptx_unavailable",
            "connector_relationships_inferred",
            "cross_page_links_not_supported_v1",
        ],
    )
    if len(projection) <= ORG_CHART_MAX_PRE_CHUNK_CHARS:
        return [
            _pre_chunk_record(
                text=projection,
                source_name=source_name,
                page_number=page_number,
                part_index=1,
            )
        ]
    return [
        _pre_chunk_record(
            text=text,
            source_name=source_name,
            page_number=page_number,
            part_index=index,
        )
        for index, text in enumerate(
            _split_large_org_chart_projection(
                projection,
                source_name=source_name,
                page_number=page_number,
                title=title,
            ),
            start=1,
        )
    ]


def _pre_chunk_record(
    *, text: str, source_name: str, page_number: int, part_index: int
) -> PreChunkedParseRecord:
    return PreChunkedParseRecord(
        text=text,
        source_name=source_name,
        source_type="org_chart",
        is_pre_chunked=True,
        metadata={
            "page": page_number,
            "chart_id": f"{source_name}#page_{page_number}#chart_1_part_{part_index}",
            "confidence": "medium",
            "org_chart_mode": "pdf_layout_fallback",
        },
    )


def _split_large_org_chart_projection(
    projection: str, *, source_name: str, page_number: int, title: str
) -> list[str]:
    body_lines = [
        line
        for line in projection.splitlines()
        if line
        and not line.startswith("[ORG_CHART]")
        and not line.startswith("[/ORG_CHART]")
        and not line.startswith("Source:")
        and not line.startswith("Page:")
        and not line.startswith("Title:")
        and not line.startswith("Extraction mode:")
        and not line.startswith("Confidence:")
    ]
    chunks: list[str] = []
    current: list[str] = []
    for line in body_lines:
        candidate = current + [line]
        if current and len(_org_chart_subtree_text(source_name, page_number, title, candidate)) > ORG_CHART_MAX_PRE_CHUNK_CHARS:
            chunks.append(_org_chart_subtree_text(source_name, page_number, title, current))
            current = [line]
        else:
            current = candidate
    if current:
        chunks.append(_org_chart_subtree_text(source_name, page_number, title, current))
    return chunks


def _org_chart_subtree_text(
    source_name: str, page_number: int, title: str, body_lines: list[str]
) -> str:
    return "\n".join(
        [
            "[ORG_CHART_SUBTREE]",
            f"Source: {source_name}",
            f"Page: {page_number}",
            f"Context Root: {title}",
            "Confidence: medium",
            "",
            *body_lines,
            "[/ORG_CHART_SUBTREE]",
        ]
    )


def _org_chart_title(page_text: str) -> str:
    for line in page_text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return "ORG CHART"
