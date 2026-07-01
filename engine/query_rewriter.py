from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, List, Optional


@dataclass(frozen=True)
class QueryVariant:
    query: str
    reason: str


@dataclass(frozen=True)
class QueryExpansionPlan:
    original_query: str
    queries: List[QueryVariant]


def expand_query(
    question: str,
    *,
    source_titles: Optional[Iterable[str]] = None,
    max_variants: int = 6,
) -> QueryExpansionPlan:
    original = " ".join(str(question or "").split()).strip()
    variants: List[QueryVariant] = []
    _add_variant(variants, original, "original query", max_variants)
    entity = _primary_entity(original)
    if entity:
        context = _primary_context(original)
        if context:
            _add_variant(variants, f"{entity} {context}", "base topic", max_variants)
        for query, reason in _entity_variants(entity, context):
            _add_variant(variants, query, reason, max_variants)
        for query in _source_title_variants(entity, source_titles or []):
            _add_variant(variants, query, "source title hint", max_variants)
    return QueryExpansionPlan(original_query=original, queries=variants)


def _add_variant(
    variants: List[QueryVariant],
    query: str,
    reason: str,
    max_variants: int,
) -> None:
    normalized = " ".join(str(query or "").split()).strip()
    if not normalized or len(variants) >= max_variants:
        return
    if any(item.query == normalized for item in variants):
        return
    variants.append(QueryVariant(query=normalized, reason=reason))


def _primary_entity(question: str) -> str:
    matches = re.findall(r"\b[A-Z][A-Z0-9]{1,9}\b", question)
    if matches:
        return matches[0]
    if _primary_context(question):
        common_words = {"What", "Which", "Who", "How", "When", "Where", "Why", "The", "This", "That"}
        for token in re.findall(r"\b[A-Z][A-Za-z0-9]{1,19}\b", question):
            if token not in common_words:
                return token
    return ""


def _primary_context(question: str) -> str:
    if "面试" in question or re.search(r"\binterview\b", question, re.IGNORECASE):
        return "面试"
    if "项目" in question or re.search(r"\bproject\b", question, re.IGNORECASE):
        return "项目"
    if "复盘" in question or re.search(r"\bretrospective\b", question, re.IGNORECASE):
        return "复盘"
    if "技术选型" in question:
        return "技术选型"
    return ""


def _entity_variants(entity: str, context: str) -> List[tuple[str, str]]:
    if context == "面试":
        return [
            (f"{entity} 面试准备", "preparation variant"),
            (f"{entity} 职位要求", "requirement variant"),
            (f"{entity} 面试复盘", "retrospective variant"),
            (f"{entity} 面试反馈", "feedback variant"),
        ]
    if context == "项目":
        return [
            (f"{entity} 项目复盘", "retrospective variant"),
            (f"{entity} 技术选型", "technical choice variant"),
            (f"{entity} 项目经验", "lessons variant"),
            (f"{entity} 项目总结", "summary variant"),
        ]
    return [
        (f"{entity} 准备", "preparation variant"),
        (f"{entity} 复盘", "retrospective variant"),
        (f"{entity} 反馈", "feedback variant"),
        (f"{entity} 总结", "summary variant"),
    ]


def _source_title_variants(entity: str, source_titles: Iterable[str]) -> List[str]:
    variants = []
    for title in source_titles:
        compact = str(title or "").replace("_", " ").replace("-", " ")
        if entity.lower() not in compact.lower():
            continue
        lowered = compact.lower()
        if "retro" in lowered or "复盘" in compact:
            variants.append(f"{entity} 项目复盘")
        if "interview" in lowered or "面试" in compact:
            variants.append(f"{entity} 面试")
        if "技术选型" in compact:
            variants.append(f"{entity} 技术选型")
    return variants
