from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from engine.models import RetrievedChunk
from engine.query_rewriter import QueryVariant


@dataclass(frozen=True)
class EvidenceCoverage:
    source_count: int
    chunk_count: int
    source_types: Dict[str, int]
    coverage_status: str
    low_evidence: bool
    query_variants: List[str]


@dataclass(frozen=True)
class EvidenceSourceSummary:
    source_name: str
    chunk_count: int


@dataclass(frozen=True)
class EvidenceReport:
    coverage: EvidenceCoverage
    top_sources: List[EvidenceSourceSummary]
    missing_evidence: List[str]

    def to_dict(self) -> dict:
        return {
            "coverage": {
                "source_count": self.coverage.source_count,
                "chunk_count": self.coverage.chunk_count,
                "source_types": self.coverage.source_types,
                "coverage_status": self.coverage.coverage_status,
                "low_evidence": self.coverage.low_evidence,
                "query_variants": self.coverage.query_variants,
            },
            "top_sources": [
                {"source_name": source.source_name, "chunk_count": source.chunk_count}
                for source in self.top_sources
            ],
            "missing_evidence": self.missing_evidence,
        }


def build_evidence_report(
    *,
    chunks: Sequence[RetrievedChunk],
    query_variants: Optional[Sequence[QueryVariant]] = None,
    variant_chunk_ids: Optional[Mapping[str, Sequence[str]]] = None,
) -> EvidenceReport:
    source_names = [chunk.source_name for chunk in chunks]
    source_count = len(set(source_names))
    chunk_count = len(chunks)
    status = _coverage_status(source_count, chunk_count)
    variants = [variant.query for variant in query_variants or []]
    missing = _missing_evidence(query_variants or [], variant_chunk_ids or {})
    coverage = EvidenceCoverage(
        source_count=source_count,
        chunk_count=chunk_count,
        source_types=dict(Counter(chunk.source_type for chunk in chunks)),
        coverage_status=status,
        low_evidence=status in {"no_answer", "thin"},
        query_variants=variants,
    )
    return EvidenceReport(
        coverage=coverage,
        top_sources=[
            EvidenceSourceSummary(source_name=source_name, chunk_count=count)
            for source_name, count in Counter(source_names).most_common()
        ],
        missing_evidence=missing,
    )


def _coverage_status(source_count: int, chunk_count: int) -> str:
    if chunk_count == 0:
        return "no_answer"
    if source_count < 2 or chunk_count < 2:
        return "thin"
    return "grounded"


def _missing_evidence(
    query_variants: Iterable[QueryVariant],
    variant_chunk_ids: Mapping[str, Sequence[str]],
) -> List[str]:
    missing = []
    for variant in query_variants:
        if variant.query in variant_chunk_ids and not variant_chunk_ids[variant.query]:
            missing.append(f"No chunks were retrieved for {variant.query}.")
    return missing
