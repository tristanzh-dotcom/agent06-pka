import mimetypes
from pathlib import Path
from typing import Any, Optional

from engine.models import ParseResult


TEXT_TYPES = {".txt": "txt", ".md": "md"}
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp"}


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

    document = fitz.open(path)
    pages = []
    try:
        for page_index, page in enumerate(document, start=1):
            pages.append(f"## Page {page_index}\n{page.get_text().strip()}")
        page_count = document.page_count
    finally:
        document.close()
    return ParseResult(
        text="\n\n".join(page for page in pages if page.strip()),
        source_name=path.name,
        source_type="pdf",
        metadata={"page_count": page_count},
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
