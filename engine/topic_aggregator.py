from __future__ import annotations

from collections import Counter, OrderedDict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple

from engine.models import RetrievedChunk
from engine.query_rewriter import QueryVariant


@dataclass(frozen=True)
class TopicCoverage:
    source_count: int
    chunk_count: int
    source_types: Dict[str, int]
    low_evidence: bool


@dataclass(frozen=True)
class TopicEvidenceGroup:
    source_name: str
    source_type: str
    chunks: List[RetrievedChunk]

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)


@dataclass(frozen=True)
class TopicDossier:
    question: str
    query_variants: List[str]
    groups: List[TopicEvidenceGroup]
    chunks: List[RetrievedChunk]
    coverage: TopicCoverage
    missing_queries: List[str]

    def to_markdown(self) -> str:
        lines = [
            "[TOPIC_DOSSIER]",
            f"Question: {self.question}",
            f"Low evidence: {str(self.coverage.low_evidence).lower()}",
            f"Sources: {self.coverage.source_count}",
            f"Chunks: {self.coverage.chunk_count}",
            "",
            "Query variants:",
        ]
        lines.extend(f"- {query}" for query in self.query_variants)
        if self.missing_queries:
            lines.extend(["", "Missing evidence:"])
            lines.extend(f"- No chunks were retrieved for {query}." for query in self.missing_queries)
        lines.extend(["", "Source groups:"])
        for group in self.groups:
            lines.append(f"- {group.source_name} ({group.source_type}): {group.chunk_count} chunks")
        lines.append("[/TOPIC_DOSSIER]")
        return "\n".join(lines)


def build_topic_dossier(
    *,
    question: str,
    variant_results: Sequence[Tuple[QueryVariant, Sequence[RetrievedChunk]]],
) -> TopicDossier:
    query_variants = [variant.query for variant, _ in variant_results]
    missing_queries = [variant.query for variant, chunks in variant_results if not chunks]
    chunks = _dedupe_chunks(chunk for _, result_chunks in variant_results for chunk in result_chunks)
    groups = _group_by_source(chunks)
    source_types = dict(Counter(chunk.source_type for chunk in chunks))
    source_count = len({chunk.source_name for chunk in chunks})
    coverage = TopicCoverage(
        source_count=source_count,
        chunk_count=len(chunks),
        source_types=source_types,
        low_evidence=len(chunks) == 0,
    )
    return TopicDossier(
        question=question,
        query_variants=query_variants,
        groups=groups,
        chunks=chunks,
        coverage=coverage,
        missing_queries=missing_queries,
    )


def _dedupe_chunks(chunks: Iterable[RetrievedChunk]) -> List[RetrievedChunk]:
    by_id: OrderedDict[str, RetrievedChunk] = OrderedDict()
    for chunk in chunks:
        by_id.setdefault(chunk.chunk_id, chunk)
    return list(by_id.values())


def _group_by_source(chunks: List[RetrievedChunk]) -> List[TopicEvidenceGroup]:
    grouped: OrderedDict[str, List[RetrievedChunk]] = OrderedDict()
    for chunk in chunks:
        grouped.setdefault(chunk.source_name, []).append(chunk)
    return [
        TopicEvidenceGroup(
            source_name=source_name,
            source_type=source_chunks[0].source_type if source_chunks else "",
            chunks=source_chunks,
        )
        for source_name, source_chunks in grouped.items()
    ]
