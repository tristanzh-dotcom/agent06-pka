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
        "question": "座舱智能化的发展阶段和趋势是什么？",
        "expected_top1": "智能座舱",
        "must_include": ["智能座舱"],
        "source_status": "grounded",
        "sources_empty": False,
    },
    {
        "id": "Q2",
        "question": "中国智能座舱关键部件渗透率有什么变化？",
        "expected_top1": "智能座舱",
        "must_include": ["智能座舱"],
        "source_status": "grounded",
        "sources_empty": False,
    },
    {
        "id": "Q3",
        "question": "HUD 和 AR-HUD 在智能座舱中的发展情况如何？",
        "expected_top1": "智能座舱",
        "must_include": ["智能座舱"],
        "source_status": "grounded",
        "sources_empty": False,
    },
    {
        "id": "Q4",
        "question": "AI 大模型如何影响车载语音和智能座舱交互？",
        "expected_top1": "智能座舱",
        "must_include": ["智能座舱"],
        "source_status": "grounded",
        "sources_empty": False,
    },
    {
        "id": "Q5",
        "question": "自动驾驶商业化落地面临哪些关键挑战？",
        "expected_top1": "自动驾驶",
        "must_include": ["自动驾驶"],
        "source_status": "grounded",
        "sources_empty": False,
    },
    {
        "id": "Q6",
        "question": "Robotaxi 的发展现状和商业化路径是什么？",
        "expected_top1": "自动驾驶",
        "must_include": ["自动驾驶"],
        "source_status": "grounded",
        "sources_empty": False,
    },
    {
        "id": "Q7",
        "question": "自动驾驶产业链或生态参与者包括哪些类型？",
        "expected_top1": "自动驾驶",
        "must_include": ["自动驾驶"],
        "source_status": "grounded",
        "sources_empty": False,
    },
    {
        "id": "Q8",
        "question": "L2 到 L4 自动驾驶的发展差异体现在哪里？",
        "expected_top1": "自动驾驶",
        "must_include": ["自动驾驶"],
        "source_status": "grounded",
        "sources_empty": False,
    },
    {
        "id": "Q9",
        "question": "座舱智能化与自动驾驶的融合趋势体现在哪些方面？",
        "expected_top1": "智能座舱",
        "must_include": ["智能座舱", "自动驾驶"],
        "source_status": "grounded",
        "sources_empty": False,
    },
    {
        "id": "Q10",
        "question": "宠物医疗保险理赔流程有哪些？",
        "expected_top1": None,
        "must_include": [],
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
async def test_retrieval_quality_gate_current_two_pdf_corpus(retriever, case):
    chunks = retriever.hybrid_search(case["question"], top_k=5)
    source_labels = [_source_label(chunk.source_name) for chunk in chunks]

    assert chunks, f"{case['id']} returned no chunks"
    if case["expected_top1"] is not None:
        assert source_labels[0] == case["expected_top1"]
    for required_source in case["must_include"]:
        assert required_source in source_labels
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


def _source_label(source_name: str) -> str:
    if "智能座舱" in source_name:
        return "智能座舱"
    if "自动驾驶" in source_name:
        return "自动驾驶"
    return "其他"


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
