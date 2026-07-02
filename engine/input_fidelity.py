from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from engine.models import RetrievedChunk


@dataclass(frozen=True)
class ChunkFidelity:
    chunk_id: str
    source_name: str
    chunk_index: int
    text_chars: int
    role: str

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "source_name": self.source_name,
            "chunk_index": self.chunk_index,
            "text_chars": self.text_chars,
            "role": self.role,
        }


@dataclass(frozen=True)
class InputFidelityReport:
    original_chunk_count: int
    final_chunk_count: int
    added_context_chunks: int
    source_count: int
    prompt_reference_chars: int
    continuity_status: str
    chunk_reports: List[ChunkFidelity]

    def to_dict(self) -> dict:
        return {
            "original_chunk_count": self.original_chunk_count,
            "final_chunk_count": self.final_chunk_count,
            "added_context_chunks": self.added_context_chunks,
            "source_count": self.source_count,
            "prompt_reference_chars": self.prompt_reference_chars,
            "continuity_status": self.continuity_status,
            "chunks": [chunk.to_dict() for chunk in self.chunk_reports],
        }


def expand_adjacent_chunks(
    chunks: Sequence[RetrievedChunk],
    indexer,
    *,
    radius: int = 1,
    max_added: int = 6,
) -> Tuple[List[RetrievedChunk], InputFidelityReport]:
    selected_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    roles: Dict[str, str] = {chunk.chunk_id: "retrieved" for chunk in chunks}
    expanded_by_id: Dict[str, RetrievedChunk] = dict(selected_by_id)
    added = 0
    for chunk in chunks:
        for offset in range(-radius, radius + 1):
            if offset == 0 or added >= max_added:
                continue
            neighbor = _neighbor_chunk(chunk, offset, indexer)
            if neighbor is None or neighbor.chunk_id in expanded_by_id:
                continue
            expanded_by_id[neighbor.chunk_id] = neighbor
            roles[neighbor.chunk_id] = "context_before" if offset < 0 else "context_after"
            added += 1
    expanded = sorted(
        expanded_by_id.values(),
        key=lambda item: (item.source_name, item.chunk_index, item.chunk_id),
    )
    report = build_input_fidelity_report(
        expanded,
        original_chunk_count=len(chunks),
        added_context_chunks=added,
        roles=roles,
    )
    return expanded, report


def build_input_fidelity_report(
    chunks: Sequence[RetrievedChunk],
    *,
    original_chunk_count: int,
    added_context_chunks: int,
    roles: Dict[str, str] | None = None,
) -> InputFidelityReport:
    roles = roles or {}
    source_count = len({chunk.source_name for chunk in chunks})
    return InputFidelityReport(
        original_chunk_count=original_chunk_count,
        final_chunk_count=len(chunks),
        added_context_chunks=added_context_chunks,
        source_count=source_count,
        prompt_reference_chars=sum(len(chunk.text or "") for chunk in chunks),
        continuity_status=_continuity_status(chunks),
        chunk_reports=[
            ChunkFidelity(
                chunk_id=chunk.chunk_id,
                source_name=chunk.source_name,
                chunk_index=chunk.chunk_index,
                text_chars=len(chunk.text or ""),
                role=roles.get(chunk.chunk_id, "retrieved"),
            )
            for chunk in chunks
        ],
    )


def _neighbor_chunk(chunk: RetrievedChunk, offset: int, indexer) -> RetrievedChunk | None:
    target_index = chunk.chunk_index + offset
    if target_index < 0:
        return None
    raw = indexer.get_chunk(f"{chunk.source_name}#{target_index}")
    if not raw:
        return None
    return RetrievedChunk(
        chunk_id=str(raw.get("chunk_id", f"{chunk.source_name}#{target_index}")),
        text=str(raw.get("text", "")),
        source_name=str(raw.get("source_name", chunk.source_name)),
        source_type=str(raw.get("source_type", chunk.source_type)),
        chunk_index=int(raw.get("chunk_index", target_index)),
        score=chunk.score,
        rank_fts5=chunk.rank_fts5,
        rank_vector=chunk.rank_vector,
        raw_file_path=str(raw.get("raw_file_path", chunk.raw_file_path)),
    )


def _continuity_status(chunks: Sequence[RetrievedChunk]) -> str:
    if not chunks:
        return "empty"
    by_source: Dict[str, List[int]] = {}
    for chunk in chunks:
        by_source.setdefault(chunk.source_name, []).append(chunk.chunk_index)
    if len(by_source) > 1:
        return "fragmented"
    indexes = sorted(next(iter(by_source.values())))
    expected = list(range(indexes[0], indexes[-1] + 1))
    return "continuous" if indexes == expected else "gapped"
