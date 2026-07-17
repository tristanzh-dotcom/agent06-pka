from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, List

from engine.models import RetrievedChunk


FOLLOW_UP_MARKERS = (
    "这个",
    "那个",
    "上述",
    "上面",
    "继续",
    "下一步",
    "怎么做",
    "怎么办",
)

SENTENCE_INITIAL_FOLLOW_UP = re.compile(
    r"^那(?:么)?(?:个|这|他|她|它|其|负责人|项目|部分|方面|件事|一步|接下来|后来|结果|时间|原因|方案|建议|内容|问题)"
)

GENERIC_TERMS = {
    "这个",
    "那个",
    "问题",
    "一步",
    "下一步",
    "具体",
    "应该",
    "怎么",
    "怎么做",
    "怎么办",
    "如何",
    "请",
    "帮",
    "一下",
    "相关",
    "资料",
    "知识库",
    "信息",
    "内容",
    "目前",
    "当前",
    "我的",
    "你",
    "我",
    "的",
    "和",
}


@dataclass(frozen=True)
class QueryResolution:
    status: str
    resolved_question: str


def resolve_query(question: str, previous_question: str = "") -> QueryResolution:
    normalized = _normalize(question)
    previous = _normalize(previous_question)
    if _is_context_dependent(normalized):
        if not previous:
            return QueryResolution(status="clarification_required", resolved_question="")
        return QueryResolution(
            status="resolved",
            resolved_question=f"{previous}；追问：{normalized}",
        )
    return QueryResolution(status="standalone", resolved_question=normalized)


def filter_supported_chunks(question: str, chunks: Iterable[RetrievedChunk]) -> List[RetrievedChunk]:
    anchors = _anchor_terms(question)
    if not anchors:
        return []
    supported = []
    for chunk in chunks:
        searchable_text = " ".join((chunk.text, chunk.source_name, chunk.chunk_id)).lower()
        if any(anchor.lower() in searchable_text for anchor in anchors):
            supported.append(chunk)
    return sorted(
        supported,
        key=lambda chunk: (chunk.source_type == "generated_asset", -chunk.score),
    )


def _is_context_dependent(question: str) -> bool:
    return bool(question) and (
        any(marker in question for marker in FOLLOW_UP_MARKERS)
        or bool(SENTENCE_INITIAL_FOLLOW_UP.search(question))
    )


def _anchor_terms(question: str) -> List[str]:
    terms = []
    for term in _tokenize(question):
        normalized = term.strip(" ?？!！,，.。:：;；、").lower()
        if not normalized or normalized in GENERIC_TERMS or len(normalized) < 2:
            continue
        if normalized not in terms:
            terms.append(normalized)
    return terms


def _tokenize(question: str) -> List[str]:
    try:
        import jieba

        return [term.strip() for term in jieba.cut(question) if term.strip()]
    except Exception:
        return re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]{2,}", question)


def _normalize(value: str) -> str:
    return " ".join(str(value or "").split()).strip()
