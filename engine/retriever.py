import re
from typing import Any, Dict, List, Optional, Tuple

from engine.models import RetrievedChunk


ORG_CHART_INTENT_PATTERNS = [
    re.compile(r"\bstructurally under\b", re.IGNORECASE),
    re.compile(r"\breport\s+to\b", re.IGNORECASE),
    re.compile(r"\breports to\b", re.IGNORECASE),
    re.compile(r"\bwho reports\b", re.IGNORECASE),
    re.compile(r"\bpeople under\b", re.IGNORECASE),
    re.compile(r"\bteams? under\b", re.IGNORECASE),
    re.compile(r"\bwhich people\b.*\bunder\b", re.IGNORECASE),
    re.compile(r"\bwho is responsible for\b", re.IGNORECASE),
    re.compile(r"\bresponsible for\b", re.IGNORECASE),
    re.compile(r"\bleader\b", re.IGNORECASE),
    re.compile(r"\bleads?\b", re.IGNORECASE),
    re.compile(r"\bunder\s+(?:him|her|them)\b", re.IGNORECASE),
    re.compile(r"\bwho works with\b", re.IGNORECASE),
    re.compile(r"\bwho is associated with\b", re.IGNORECASE),
    re.compile(r"负责"),
    re.compile(r"领导"),
    re.compile(r"汇报"),
    re.compile(r"职位"),
    re.compile(r"组织架构"),
]

ORG_CHART_EXPLANATION_PATTERNS = [
    re.compile(r"\bhow should\b.*\bcharts?\b.*\bread\b", re.IGNORECASE),
    re.compile(r"\bhow to read\b", re.IGNORECASE),
    re.compile(r"\bwhat is an org chart\b", re.IGNORECASE),
]

ORG_CHART_INTENT_BONUS = 0.02
ORG_CHART_FOCUS_STOPWORDS = {
    "apac",
    "and",
    "china",
    "digital",
    "jlr",
    "leader",
    "leaders",
    "lead",
    "leads",
    "org",
    "chart",
    "charts",
    "does",
    "in",
    "position",
    "report",
    "responsible",
    "role",
    "structurally",
    "the",
    "to",
    "under",
    "what",
    "who",
    "him",
    "his",
    "her",
    "them",
}


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
        fused = self._search_fused(query)
        return self._chunks_from_fused(fused[:top_k])

    def hybrid_search_with_debug(
        self,
        query: str,
        top_k: int = 10,
    ) -> Tuple[List[RetrievedChunk], Dict[str, Dict[str, Any]]]:
        fused, intent_debug = self._search_fused_with_intent_debug(query)
        limited = fused[:top_k]
        chunks = self._chunks_from_fused(limited)
        debug_payload = {
            item["chunk_id"]: {
                "fts_rank": item.get("rank_fts5"),
                "vector_rank": item.get("rank_vector"),
                "rrf_score": item.get("score"),
                "final_rank": index + 1,
                "intent_bias_triggered": intent_debug["triggered"],
                "intent_bias_applied": item["chunk_id"] in intent_debug["applied_chunk_ids"],
                "source_type": item.get("source_type"),
                "chunk_id": item["chunk_id"],
            }
            for index, item in enumerate(limited)
        }
        return chunks, debug_payload

    def _search_fused(self, query: str) -> List[Dict[str, Any]]:
        fused, _ = self._search_fused_with_intent_debug(query)
        return fused

    def _search_fused_with_intent_debug(self, query: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        fts_results = self.indexer.search_fts(query, self.fts5_top_k)
        fts_results = self._with_org_chart_focus_fts_results(query, fts_results)
        vector_results = self.indexer.search_vector(query, self.vector_top_k)
        fused = reciprocal_rank_fusion(fts_results, vector_results, self.rrf_k)
        intent_debug = _org_chart_intent_debug(query, fused)
        fused = apply_org_chart_intent_bias(query, fused)
        return self._rerank(query, fused), intent_debug

    def _with_org_chart_focus_fts_results(self, query: str, fts_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not _has_org_chart_relation_intent(query):
            return fts_results
        seen = {item["chunk_id"] for item in fts_results}
        expanded = list(fts_results)
        for token in _org_chart_focus_tokens(query):
            for item in self.indexer.search_fts(token, min(self.fts5_top_k, 5)):
                if item["chunk_id"] in seen:
                    continue
                seen.add(item["chunk_id"])
                expanded.append(item)
        return expanded

    def _chunks_from_fused(self, fused: List[Dict[str, Any]]) -> List[RetrievedChunk]:
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
            for item in fused
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


def apply_org_chart_intent_bias(query: str, fused: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not fused or not _has_org_chart_relation_intent(query):
        return fused

    def intent_score(item: Dict[str, Any]) -> float:
        eligible = (
            item.get("source_type") == "org_chart"
            and _has_org_chart_projection_evidence(item.get("text", ""))
        )
        return item["score"] + (ORG_CHART_INTENT_BONUS if eligible else 0.0)

    def sort_key(item: Dict[str, Any]):
        rank_fts5 = item.get("rank_fts5")
        rank_vector = item.get("rank_vector")
        dual_channel = rank_fts5 is not None and rank_vector is not None
        return (
            -intent_score(item),
            not dual_channel,
            rank_vector if rank_vector is not None else float("inf"),
            rank_fts5 if rank_fts5 is not None else float("inf"),
        )

    biased = sorted(fused, key=sort_key)
    return _prioritize_named_org_chart_focus_pages(query, biased)


def _org_chart_intent_debug(query: str, fused: List[Dict[str, Any]]) -> Dict[str, Any]:
    triggered = bool(fused and _has_org_chart_relation_intent(query))
    if not triggered:
        return {"triggered": False, "applied_chunk_ids": set()}
    applied_chunk_ids = {
        item["chunk_id"]
        for item in fused
        if (
            item.get("source_type") == "org_chart"
            and _has_org_chart_projection_evidence(item.get("text", ""))
        )
    }
    return {"triggered": True, "applied_chunk_ids": applied_chunk_ids}


def _has_org_chart_relation_intent(query: str) -> bool:
    if any(pattern.search(query) for pattern in ORG_CHART_EXPLANATION_PATTERNS):
        return False
    return any(pattern.search(query) for pattern in ORG_CHART_INTENT_PATTERNS)


def _has_org_chart_projection_evidence(text: str) -> bool:
    return (
        text.startswith("[ORG_CHART")
        and (
            "Semantic Search Triggers:" in text
            or "is structurally under" in text
            or "Structure:" in text
        )
    )


def _prioritize_named_org_chart_focus_pages(query: str, fused: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    focus_tokens = _org_chart_focus_tokens(query)
    if not focus_tokens:
        return fused

    focus_pages = set()
    focus_source_names = set()
    for item in fused:
        if item.get("source_type") != "org_chart":
            continue
        text = item.get("text", "")
        if not _text_contains_any_token(text, focus_tokens):
            continue
        page_key = _org_chart_page_key(item)
        if page_key is not None:
            focus_pages.add(page_key)
            focus_source_names.add(page_key[0])
    if not focus_pages:
        return fused

    focused_org = []
    other_non_org = []
    other_org = []
    for item in fused:
        if item.get("source_type") != "org_chart" and item.get("source_name") in focus_source_names:
            other_non_org.append(item)
        elif _org_chart_page_key(item) in focus_pages:
            focused_org.append(item)
        else:
            other_org.append(item)
    focused_org = sorted(
        focused_org,
        key=lambda item: not _text_contains_any_token(item.get("text", ""), focus_tokens),
    )
    return focused_org + other_non_org


def _org_chart_focus_tokens(query: str) -> List[str]:
    tokens = []
    for token in re.findall(r"(?<![A-Za-z])[A-Za-z]{3,}(?![A-Za-z])", query):
        lowered = token.lower()
        if lowered in ORG_CHART_FOCUS_STOPWORDS:
            continue
        if token not in tokens:
            tokens.append(token)
    return tokens


def _text_contains_any_token(text: str, tokens: List[str]) -> bool:
    return any(re.search(rf"\b{re.escape(token)}\b", text, re.IGNORECASE) for token in tokens)


def _org_chart_page_key(item: Dict[str, Any]) -> Optional[Tuple[str, int]]:
    page = _org_chart_page_number(item.get("text", ""))
    if page is None:
        return None
    return (str(item.get("source_name", "")), page)


def _org_chart_page_number(text: str) -> Optional[int]:
    match = re.search(r"^Page:\s*(\d+)\s*$", text, re.MULTILINE)
    if not match:
        return None
    return int(match.group(1))
