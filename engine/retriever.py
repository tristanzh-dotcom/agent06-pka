from typing import Any, Dict, List

from engine.models import RetrievedChunk


def reciprocal_rank_fusion(
    results_a: List[Dict[str, Any]],
    results_b: List[Dict[str, Any]],
    k: int = 60,
) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}

    def add(results: List[Dict[str, Any]], rank_key: str) -> None:
        for rank, item in enumerate(results, start=1):
            chunk_id = item["chunk_id"]
            record = merged.setdefault(
                chunk_id,
                {
                    **item,
                    "score": 0.0,
                    "rank_fts5": None,
                    "rank_vector": None,
                },
            )
            record["score"] += 1.0 / (k + rank)
            record[rank_key] = rank
            for key, value in item.items():
                record.setdefault(key, value)

    add(results_a, "rank_fts5")
    add(results_b, "rank_vector")
    def sort_key(item: Dict[str, Any]):
        rank_fts5 = item.get("rank_fts5")
        rank_vector = item.get("rank_vector")
        dual_channel = rank_fts5 is not None and rank_vector is not None
        return (
            -item["score"],
            not dual_channel,
            rank_vector if rank_vector is not None else float("inf"),
            rank_fts5 if rank_fts5 is not None else float("inf"),
        )

    return sorted(merged.values(), key=sort_key)


class HybridRetriever:
    def __init__(
        self,
        indexer,
        fts5_top_k: int = 10,
        vector_top_k: int = 10,
        rrf_k: int = 60,
        reranker=None,
        rerank_candidate_top_k: int = 20,
    ):
        self.indexer = indexer
        self.fts5_top_k = fts5_top_k
        self.vector_top_k = vector_top_k
        self.rrf_k = rrf_k
        self.reranker = reranker
        self.rerank_candidate_top_k = rerank_candidate_top_k

    def hybrid_search(self, query: str, top_k: int = 10) -> List[RetrievedChunk]:
        fts_results = self.indexer.search_fts(query, self.fts5_top_k)
        vector_results = self.indexer.search_vector(query, self.vector_top_k)
        fused = reciprocal_rank_fusion(fts_results, vector_results, self.rrf_k)
        fused = self._rerank(query, fused)
        return [
            RetrievedChunk(
                chunk_id=item["chunk_id"],
                text=item["text"],
                source_name=item["source_name"],
                source_type=item["source_type"],
                chunk_index=int(item["chunk_index"]),
                score=float(item["score"]),
                rank_fts5=item.get("rank_fts5"),
                rank_vector=item.get("rank_vector"),
                raw_file_path=item.get("raw_file_path", ""),
            )
            for item in fused[:top_k]
        ]

    def _rerank(self, query: str, fused: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not self.reranker or not fused:
            return fused
        candidates = fused[: self.rerank_candidate_top_k]
        remainder = fused[self.rerank_candidate_top_k :]
        try:
            reranked = self.reranker.rerank(query, candidates)
        except Exception:
            return fused
        candidate_map = {item["chunk_id"]: item for item in candidates}
        seen = set()
        ordered: List[Dict[str, Any]] = []
        for result in reranked:
            item = candidate_map.get(result.chunk_id)
            if item is None:
                continue
            updated = {**item, "score": float(result.score)}
            ordered.append(updated)
            seen.add(result.chunk_id)
        ordered.extend(item for item in candidates if item["chunk_id"] not in seen)
        ordered.extend(remainder)
        return ordered
