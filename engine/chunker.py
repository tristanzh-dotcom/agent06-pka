from datetime import datetime, timezone
import re
from typing import Iterable, List, Tuple

from engine.models import Chunk


_PDF_TOC_LINE_RE = re.compile(r"^[\.\s·…\d]+$")
_PDF_DOTTED_LEADER_RE = re.compile(r"[\.\s·…\d]{20,}")


def chunk_text(
    text: str,
    source_name: str,
    source_type: str,
    max_chunk_size: int = 1024,
    chunk_overlap: int = 128,
) -> List[Chunk]:
    if not text or not text.strip():
        return []

    sections = _markdown_sections(text) if _looks_like_markdown(text) else [(paragraph, "") for paragraph in _paragraphs(text)]
    chunk_records: List[Tuple[str, str]] = []
    for section, breadcrumb in sections:
        for window in _window_text(section, max_chunk_size, chunk_overlap):
            if _skip_pdf_noise_chunk(window, source_type):
                continue
            embedding_text = (
                f"[BREADCRUMB]{breadcrumb}[/BREADCRUMB]\n\n{window}"
                if breadcrumb
                else ""
            )
            chunk_records.append((window, embedding_text))

    created_at = datetime.now(timezone.utc).astimezone().isoformat()
    return [
        Chunk(
            id=f"{source_name}#{index}",
            text=chunk,
            source_name=source_name,
            source_type=source_type,
            chunk_index=index,
            created_at=created_at,
            embedding_text=embedding_text,
        )
        for index, (chunk, embedding_text) in enumerate(chunk_records)
        if chunk.strip()
    ]


def _skip_pdf_noise_chunk(chunk: str, source_type: str) -> bool:
    if source_type != "pdf":
        return False
    stripped = chunk.strip()
    if len(stripped) < 30:
        return True
    if _PDF_TOC_LINE_RE.fullmatch(stripped):
        return True
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if not lines:
        return False
    dotted_leader_lines = sum(1 for line in lines if _PDF_DOTTED_LEADER_RE.search(line))
    return dotted_leader_lines / len(lines) > 0.5


def _looks_like_markdown(text: str) -> bool:
    return any(line.startswith("##") for line in text.splitlines())


def _markdown_sections(text: str) -> List[Tuple[str, str]]:
    sections: List[List[str]] = []
    current: List[str] = []
    saw_first_h2 = False
    h1 = ""
    h2 = ""
    breadcrumbs: List[str] = []

    def current_breadcrumb() -> str:
        parts = [part for part in [h1, h2] if part]
        return " > ".join(parts)

    for line in text.splitlines():
        if line.startswith("# ") and not line.startswith("## "):
            h1 = line
        if line.startswith("## "):
            if current:
                sections.append(current)
                breadcrumbs.append(current_breadcrumb())
            h2 = line
            current = [line]
            saw_first_h2 = True
        elif not saw_first_h2:
            current.append(line)
        else:
            current.append(line)
    if current:
        sections.append(current)
        breadcrumbs.append(current_breadcrumb())
    if not sections:
        return [(paragraph, "") for paragraph in _paragraphs(text)]
    return [
        ("\n".join(section).strip(), breadcrumb)
        for section, breadcrumb in zip(sections, breadcrumbs)
        if "\n".join(section).strip()
    ]


def _paragraphs(text: str) -> List[str]:
    return [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]


def _window_text(text: str, max_chunk_size: int, chunk_overlap: int) -> Iterable[str]:
    cleaned = text.strip()
    if len(cleaned) <= max_chunk_size:
        yield cleaned
        return

    step = max(1, max_chunk_size - chunk_overlap)
    start = 0
    while start < len(cleaned):
        yield cleaned[start : start + max_chunk_size]
        if start + max_chunk_size >= len(cleaned):
            break
        start += step
