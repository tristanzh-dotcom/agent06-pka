import json
import re

import pytest

from engine.config import load_config
from engine.generator import generate_answer
from engine.indexer import HybridIndexer, OllamaEmbeddingClient
from engine.retriever import HybridRetriever


QUALITY_GATE_CASES = [
    {
        "id": "Q1",
        "question": "Who is responsible for Off-cycle Concepts and Smart Cabin?",
        "expected_top_source_type": "org_chart",
        "must_include_source_types": ["org_chart"],
        "must_contain": ["OFF-CYCLE", "SMART CABIN", "Nico Reimel"],
        "source_status": "grounded",
        "sources_empty": False,
    },
    {
        "id": "Q2",
        "question": "Who reports to Nico Reimel?",
        "expected_top_source_type": "org_chart",
        "must_include_source_types": ["org_chart"],
        "must_contain": ["Nico Reimel", "OFF-CYCLE"],
        "source_status": "grounded",
        "sources_empty": False,
    },
    {
        "id": "Q3",
        "question": "Who works with James Vallance in Concepts?",
        "expected_top_source_type": "org_chart",
        "must_include_source_types": ["org_chart"],
        "must_contain": ["James Vallance", "Concept"],
        "source_status": "grounded",
        "sources_empty": False,
    },
    {
        "id": "Q4",
        "question": "What teams are under Software Defined Vehicle and Enterprise CI/CD?",
        "expected_top_source_type": "org_chart",
        "must_include_source_types": ["org_chart"],
        "must_contain": ["SOFTWARE DEFINED VEHICLE", "ENTERPRISE CI/CD"],
        "source_status": "grounded",
        "sources_empty": False,
    },
    {
        "id": "Q5",
        "question": "Who is associated with Architecture EDS and Cross Function?",
        "expected_top_source_type": "org_chart",
        "must_include_source_types": ["org_chart"],
        "must_contain": ["ARCHITECTURE", "EDS", "CROSS FUNCTION"],
        "source_status": "grounded",
        "sources_empty": False,
    },
    {
        "id": "Q6",
        "question": "How should the organisation charts be read?",
        "expected_top_source_type": "pdf",
        "must_include_source_types": ["pdf"],
        "must_contain": ["HOW TO READ", "ORGANISATION CHARTS"],
        "source_status": "grounded",
        "sources_empty": False,
    },
    {
        "id": "Q7",
        "question": "What is the DP first line structure?",
        "expected_top_source_type": "org_chart",
        "must_include_source_types": ["org_chart"],
        "must_contain": ["FIRST LINE STRUCTURE", "Digital Platform"],
        "source_status": "grounded",
        "sources_empty": False,
    },
    {
        "id": "Q8",
        "question": "Which people are structurally under Infotainment and Connectivity?",
        "expected_top_source_type": "org_chart",
        "must_include_source_types": ["org_chart"],
        "must_contain": ["INFOTAINMENT", "CONNECTIVITY"],
        "source_status": "grounded",
        "sources_empty": False,
    },
    {
        "id": "Q9",
        "question": "What org chart pages mention Smart Cabin and SDV Enterprise?",
        "expected_top_source_type": "org_chart",
        "must_include_source_types": ["org_chart"],
        "must_contain": ["Smart Cabin", "SDV", "Enterprise"],
        "source_status": "grounded",
        "sources_empty": False,
    },
    {
        "id": "Q10",
        "question": "宠物医疗保险理赔流程有哪些？",
        "expected_top_source_type": None,
        "must_include_source_types": [],
        "must_contain": [],
        "source_status": "no_answer",
        "sources_empty": True,
    },
]


_DOTTED_LEADER_RE = re.compile(r"[\.\s·…\d]{20,}")


class QualityGateDeepSeekClient:
    def __init__(self, no_answer: bool):
        self.no_answer = no_answer

    async def stream(self, prompt):
        if self.no_answer:
            yield "当前知识库缺少相关信息，无法回答该问题。建议补充相关资料后重新提问。"
            return
        yield "核心结论：该问题可以由当前知识库回答。来源：quality-gate.pdf#1"


@pytest.fixture(scope="module")
def retriever():
    config = load_config("config.yaml")
    embedding_config = config.get("embedding", {})
    indexer = HybridIndexer(
        config["fts5"]["db_path"],
        config["chroma"]["persist_dir"],
        config["chroma"]["collection_name"],
        OllamaEmbeddingClient(
            host=embedding_config.get("host", "http://localhost:11434"),
            model=embedding_config.get("model", "bge-m3"),
            query_prefix=embedding_config.get("query_prefix", ""),
        ),
    )
    assert indexer.count_chunks() > 0
    return HybridRetriever(
        indexer=indexer,
        fts5_top_k=config["retrieval"]["fts5_top_k"],
        vector_top_k=config["retrieval"]["vector_top_k"],
        rrf_k=config["retrieval"]["rrf_k"],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("case", QUALITY_GATE_CASES, ids=[case["id"] for case in QUALITY_GATE_CASES])
async def test_retrieval_quality_gate_current_jlr_org_chart_corpus(retriever, case):
    chunks = retriever.hybrid_search(case["question"], top_k=5)
    source_types = [chunk.source_type for chunk in chunks]
    combined_text = "\n".join(chunk.text for chunk in chunks)

    assert chunks, f"{case['id']} returned no chunks"
    if case["expected_top_source_type"] is not None:
        assert source_types[0] == case["expected_top_source_type"]
    for required_source_type in case["must_include_source_types"]:
        assert required_source_type in source_types
    for required_text in case["must_contain"]:
        assert _compact(required_text) in _compact(combined_text)
    if case["expected_top_source_type"] == "org_chart":
        assert chunks[0].text.startswith("[ORG_CHART")
        assert _has_org_chart_projection_features(chunks[0].text)
    assert [_noise_type(chunk.text) for chunk in chunks] == ["", "", "", "", ""]

    events = []
    async for event in generate_answer(
        question=case["question"],
        chunks=chunks,
        language="zh",
        deepseek_endpoint="https://deepseek.example",
        deepseek_api_key="test-key",
        deepseek_model="deepseek-test",
        deepseek_client=QualityGateDeepSeekClient(no_answer=case["source_status"] == "no_answer"),
    ):
        events.append(json.loads(event.removeprefix("data: ").strip()))

    sources_event = next(event for event in events if event["type"] == "sources")
    assert sources_event["source_status"] == case["source_status"]
    if case["sources_empty"]:
        assert sources_event["sources"] == []
    else:
        assert sources_event["sources"]
        assert all(source.get("chunk_id") for source in sources_event["sources"])


def test_org_chart_intent_bias_lifts_structural_query_but_not_explanation_query(retriever):
    structural_chunks = retriever.hybrid_search(
        "Which people are structurally under Infotainment and Connectivity?",
        top_k=5,
    )
    explanation_chunks = retriever.hybrid_search(
        "How should the organisation charts be read?",
        top_k=5,
    )

    assert structural_chunks
    assert structural_chunks[0].source_type == "org_chart"
    assert "INFOTAINMENT" in structural_chunks[0].text
    assert "CONNECTIVITY" in structural_chunks[0].text
    assert structural_chunks[0].text.startswith("[ORG_CHART")
    assert _has_org_chart_projection_features(structural_chunks[0].text)

    assert explanation_chunks
    assert explanation_chunks[0].source_type == "pdf"
    assert _compact("HOW TO READ") in _compact(explanation_chunks[0].text)
    assert _compact("ORGANISATION CHARTS") in _compact(explanation_chunks[0].text)


def _noise_type(text: str) -> str:
    stripped = text.strip()
    if len(stripped) < 30:
        return "short"
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if stripped and all(ch in ". ·…0123456789\t\n\r " for ch in stripped):
        return "pure_dotted"
    if lines and sum(1 for line in lines if _DOTTED_LEADER_RE.search(line)) / len(lines) > 0.5:
        return "mixed_toc"
    return ""


def _compact(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "", text).lower()


def _has_org_chart_projection_features(text: str) -> bool:
    return (
        "Structure:" in text
        or "Semantic Search Triggers:" in text
        or "is structurally under" in text
    )
