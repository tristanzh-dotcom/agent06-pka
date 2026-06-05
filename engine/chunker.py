from datetime import datetime, timezone
from typing import Iterable, List

from engine.models import Chunk


def chunk_text(
    text: str,
    source_name: str,
    source_type: str,
    max_chunk_size: int = 1024,
    chunk_overlap: int = 128,
) -> List[Chunk]:
    if not text or not text.strip():
        return []

    sections = _markdown_h2_sections(text) if _looks_like_markdown(text) else _paragraphs(text)
    chunk_texts: List[str] = []
    for section in sections:
        chunk_texts.extend(_window_text(section, max_chunk_size, chunk_overlap))

    created_at = datetime.now(timezone.utc).astimezone().isoformat()
    return [
        Chunk(
            id=f"{source_name}#{index}",
            text=chunk,
            source_name=source_name,
            source_type=source_type,
            chunk_index=index,
            created_at=created_at,
        )
        for index, chunk in enumerate(chunk_texts)
        if chunk.strip()
    ]


def _looks_like_markdown(text: str) -> bool:
    return any(line.startswith("##") for line in text.splitlines())


def _markdown_h2_sections(text: str) -> List[str]:
    sections: List[List[str]] = []
    current: List[str] = []
    saw_first_h2 = False
    for line in text.splitlines():
        if line.startswith("## "):
            if current:
                sections.append(current)
            current = [line]
            saw_first_h2 = True
        elif not saw_first_h2:
            current.append(line)
        else:
            current.append(line)
    if current:
        sections.append(current)
    return ["\n".join(section).strip() for section in sections] if sections else _paragraphs(text)


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
