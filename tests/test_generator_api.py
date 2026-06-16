from copy import deepcopy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine.generator import build_deepseek_analysis_prompt, build_prompt, generate_answer
from engine.indexer import HybridIndexer
from engine.models import RetrievedChunk
from server import app


class FakeLLMClient:
    def __init__(self):
        self.prompts = []

    async def stream(self, prompt):
        self.prompts.append(prompt)
        for token in ["根据", "资料", "建议调整。"]:
            yield token


class FakeDeepSeekClient:
    def __init__(self):
        self.prompts = []

    async def stream(self, prompt):
        self.prompts.append(prompt)
        yield '{"key_facts":[{"content":"组织架构调整方案","source":"org.txt","language":"zh"}],'
        yield '"terminology":[{"zh":"组织架构","en":"organizational structure"}],'
        yield '"logic_chain":"先明确职责边界，再调整组织。"}'


class FakeNoAnswerDeepSeekClient:
    def __init__(self):
        self.prompts = []

    async def stream(self, prompt):
        self.prompts.append(prompt)
        yield "目前的知识库中并没有关于特斯拉 Optimus 人形机器人的直接信息，"
        yield "因此无法判断其具体关系或状态。来源：无适用资料"


class FakeNoAnswerWithChunkCitationClient:
    def __init__(self):
        self.prompts = []

    async def stream(self, prompt):
        self.prompts.append(prompt)
        yield "当前知识库缺少新能源汽车出海政策的信息，因此无法回答。\n\n"
        yield "来源：org.txt#2"


class FakeNoAnswerWithParenthesizedCitationClient:
    def __init__(self):
        self.prompts = []

    async def stream(self, prompt):
        self.prompts.append(prompt)
        yield "当前知识库中并没有关于宠物医疗保险理赔流程的相关信息。"
        yield "参考内容中提到了自动驾驶责任保险的早期探索（来源：org.txt#2）"


class FakeNoAnswerWithoutCitationClient:
    def __init__(self):
        self.prompts = []

    async def stream(self, prompt):
        self.prompts.append(prompt)
        yield "目前您的知识库中还没有与宠物医疗保险理赔流程直接相关的资料。"
        yield "现有参考内容无法用来回答这个问题。"


class FakeNoAnswerIrrelevantMaterialClient:
    def __init__(self):
        self.prompts = []

    async def stream(self, prompt):
        self.prompts.append(prompt)
        yield "根据您当前提供的知识库内容，我无法为您解答关于宠物医疗保险理赔流程的问题。"
        yield "这些材料与宠物医疗保险的理赔流程完全不相关，没有涵盖任何保险条款。"
        yield "\n\n来源：org.txt#2"


class FakeEmbeddingClient:
    def embed(self, texts):
        return [[1.0] + [0.0] * 1023 for _ in texts]


def sample_chunk():
    return RetrievedChunk(
        chunk_id="org.txt#2",
        text="组织架构调整方案",
        source_name="org.txt",
        source_type="txt",
        chunk_index=2,
        score=0.9,
        rank_fts5=1,
        rank_vector=1,
    )


def sample_file_chunk():
    return RetrievedChunk(
        chunk_id="report.pdf#0",
        text="组织架构调整方案",
        source_name="report.pdf",
        source_type="pdf",
        chunk_index=0,
        score=0.9,
        rank_fts5=1,
        rank_vector=1,
        raw_file_path="raw/2026-06-04/report.pdf",
    )


def install_temp_runtime(server, tmp_path, collection_name):
    original = (deepcopy(server.runtime.config), server.runtime.indexer, server.runtime.last_updated)
    server.runtime.config = {
        **deepcopy(original[0]),
        "data_dir": str(tmp_path / "data"),
        "fts5": {"db_path": str(tmp_path / "pka.db")},
        "chroma": {
            "persist_dir": str(tmp_path / "vector"),
            "collection_name": collection_name,
        },
    }
    server.runtime.indexer = HybridIndexer(
        fts_db_path=str(tmp_path / "pka.db"),
        vector_dir=str(tmp_path / "vector"),
        collection_name=collection_name,
        embedding_client=FakeEmbeddingClient(),
    )
    return original


def restore_runtime(server, original):
    server.runtime.config, server.runtime.indexer, server.runtime.last_updated = original


def test_build_prompt_includes_question_chunks_and_source_names():
    prompt = build_prompt("怎么调整组织？", [sample_chunk()])

    assert "个人知识库助手" in prompt
    assert "组织架构调整方案" in prompt
    assert "来源: org.txt" in prompt
    assert "怎么调整组织？" in prompt


def test_deepseek_prompts_forbid_external_knowledge_when_no_answer():
    zh_prompt = build_deepseek_analysis_prompt(
        "宠物医疗保险理赔流程有哪些？",
        [sample_chunk()],
        include_chinese_advice=True,
    )
    report_prompt = build_deepseek_analysis_prompt(
        "宠物医疗保险理赔流程有哪些？",
        [sample_chunk()],
        report_language="en",
    )

    required = (
        '如果参考内容中没有任何与该问题相关的信息，请只输出：\n'
        '"当前知识库缺少相关信息，无法回答该问题。建议补充相关资料后重新提问。"\n'
        "不要给出外部知识、推测或通用建议。"
    )
    assert required in zh_prompt
    assert required in report_prompt


@pytest.mark.asyncio
async def test_generate_answer_streams_tokens_sources_and_done():
    deepseek_client = FakeDeepSeekClient()
    llm_client = FakeLLMClient()
    events = []
    async for event in generate_answer(
        question="怎么调整组织？",
        chunks=[sample_chunk()],
        language="en",
        deepseek_endpoint="https://deepseek.example",
        deepseek_api_key="deepseek-secret",
        deepseek_model="deepseek-v4-pro",
        generation_endpoint="https://example.test",
        generation_api_key="secret",
        generation_model="test-model",
        deepseek_client=deepseek_client,
        llm_client=llm_client,
    ):
        events.append(json.loads(event.removeprefix("data: ").strip()))

    assert [event["type"] for event in events] == ["token", "token", "token", "sources", "done"]
    assert events[-2]["sources"][0]["source_name"] == "org.txt"
    assert events[-2]["sources"][0]["chunk_index"] == 2
    assert len(deepseek_client.prompts) == 1
    assert len(llm_client.prompts) == 1
    assert "DeepSeek analysis" in llm_client.prompts[0]


@pytest.mark.asyncio
async def test_generate_answer_sources_include_raw_file_path():
    events = []
    async for event in generate_answer(
        question="怎么调整组织？",
        chunks=[sample_file_chunk()],
        language="zh",
        deepseek_endpoint="https://deepseek.example",
        deepseek_api_key="deepseek-secret",
        deepseek_model="deepseek-v4-pro",
        deepseek_client=FakeDeepSeekClient(),
    ):
        events.append(json.loads(event.removeprefix("data: ").strip()))

    sources = next(event["sources"] for event in events if event["type"] == "sources")
    assert sources[0]["raw_file_path"] == "raw/2026-06-04/report.pdf"


@pytest.mark.asyncio
async def test_generate_answer_hides_sources_when_deepseek_returns_no_answer():
    events = []
    async for event in generate_answer(
        question="特斯拉 Optimus 目前是什么关系？",
        chunks=[sample_chunk()],
        language="zh",
        deepseek_endpoint="https://deepseek.example",
        deepseek_api_key="deepseek-secret",
        deepseek_model="deepseek-v4-pro",
        deepseek_client=FakeNoAnswerDeepSeekClient(),
    ):
        events.append(json.loads(event.removeprefix("data: ").strip()))

    sources_event = next(event for event in events if event["type"] == "sources")
    assert sources_event["source_status"] == "no_answer"
    assert sources_event["sources"] == []


@pytest.mark.asyncio
async def test_generate_answer_removes_no_answer_chunk_citations_from_token_text():
    events = []
    async for event in generate_answer(
        question="新能源汽车出海政策有哪些？",
        chunks=[sample_chunk()],
        language="zh",
        deepseek_endpoint="https://deepseek.example",
        deepseek_api_key="deepseek-secret",
        deepseek_model="deepseek-v4-pro",
        deepseek_client=FakeNoAnswerWithChunkCitationClient(),
    ):
        events.append(json.loads(event.removeprefix("data: ").strip()))

    token_text = "".join(event.get("content", "") for event in events if event["type"] == "token")
    sources_event = next(event for event in events if event["type"] == "sources")
    assert "当前知识库缺少新能源汽车出海政策的信息" in token_text
    assert "org.txt#2" not in token_text
    assert sources_event["source_status"] == "no_answer"
    assert sources_event["sources"] == []


@pytest.mark.asyncio
async def test_generate_answer_removes_parenthesized_no_answer_citation_tail():
    events = []
    async for event in generate_answer(
        question="宠物医疗保险理赔流程有哪些？",
        chunks=[sample_chunk()],
        language="zh",
        deepseek_endpoint="https://deepseek.example",
        deepseek_api_key="deepseek-secret",
        deepseek_model="deepseek-v4-pro",
        deepseek_client=FakeNoAnswerWithParenthesizedCitationClient(),
    ):
        events.append(json.loads(event.removeprefix("data: ").strip()))

    token_text = "".join(event.get("content", "") for event in events if event["type"] == "token")
    assert "来源" not in token_text
    assert "org.txt#2" not in token_text
    assert not token_text.endswith("（")


@pytest.mark.asyncio
async def test_generate_answer_marks_directly_unrelated_material_as_no_answer():
    events = []
    async for event in generate_answer(
        question="宠物医疗保险理赔流程有哪些？",
        chunks=[sample_chunk()],
        language="zh",
        deepseek_endpoint="https://deepseek.example",
        deepseek_api_key="deepseek-secret",
        deepseek_model="deepseek-v4-pro",
        deepseek_client=FakeNoAnswerWithoutCitationClient(),
    ):
        events.append(json.loads(event.removeprefix("data: ").strip()))

    sources_event = next(event for event in events if event["type"] == "sources")
    assert sources_event["source_status"] == "no_answer"
    assert sources_event["sources"] == []


@pytest.mark.asyncio
async def test_generate_answer_marks_irrelevant_material_language_as_no_answer():
    events = []
    async for event in generate_answer(
        question="宠物医疗保险理赔流程有哪些？",
        chunks=[sample_chunk()],
        language="zh",
        deepseek_endpoint="https://deepseek.example",
        deepseek_api_key="deepseek-secret",
        deepseek_model="deepseek-v4-pro",
        deepseek_client=FakeNoAnswerIrrelevantMaterialClient(),
    ):
        events.append(json.loads(event.removeprefix("data: ").strip()))

    token_text = "".join(event.get("content", "") for event in events if event["type"] == "token")
    sources_event = next(event for event in events if event["type"] == "sources")
    assert "来源" not in token_text
    assert sources_event["source_status"] == "no_answer"
    assert sources_event["sources"] == []


@pytest.mark.asyncio
async def test_generate_answer_returns_empty_knowledge_message_without_llm():
    events = []
    async for event in generate_answer(
        question="有什么资料？",
        chunks=[],
        language="zh",
        deepseek_endpoint="",
        deepseek_api_key="",
        deepseek_model="",
        generation_endpoint="",
        generation_api_key="",
        generation_model="",
        llm_client=FakeLLMClient(),
    ):
        events.append(json.loads(event.removeprefix("data: ").strip()))

    assert events[0] == {"type": "token", "content": "暂无相关内容。"}
    assert events[-1] == {"type": "done"}


@pytest.mark.asyncio
async def test_generate_answer_with_language_zh_uses_deepseek_path_without_codex():
    deepseek_client = FakeDeepSeekClient()
    llm_client = FakeLLMClient()
    events = []
    async for event in generate_answer(
        question="怎么调整组织？",
        chunks=[sample_chunk()],
        language="zh",
        deepseek_endpoint="https://deepseek.example",
        deepseek_api_key="deepseek-secret",
        deepseek_model="deepseek-v4-pro",
        generation_endpoint="",
        generation_api_key="",
        generation_model="codex-base",
        deepseek_client=deepseek_client,
        llm_client=llm_client,
    ):
        events.append(json.loads(event.removeprefix("data: ").strip()))

    token_text = "".join(event.get("content", "") for event in events if event["type"] == "token")
    assert "组织架构调整方案" in token_text
    assert not token_text.lstrip().startswith("{")
    assert "key_facts" not in token_text
    assert len(deepseek_client.prompts) == 1
    assert "中文个人建议" in deepseek_client.prompts[0]
    assert "输出 JSON 格式" not in deepseek_client.prompts[0]
    assert llm_client.prompts == []
    assert [event["type"] for event in events][-2:] == ["sources", "done"]


@pytest.mark.asyncio
async def test_generate_answer_with_language_zh_formats_deepseek_json_as_natural_language():
    events = []
    async for event in generate_answer(
        question="怎么调整组织？",
        chunks=[sample_chunk()],
        language="zh",
        deepseek_endpoint="https://deepseek.example",
        deepseek_api_key="deepseek-secret",
        deepseek_model="deepseek-v4-pro",
        deepseek_client=FakeDeepSeekClient(),
    ):
        events.append(json.loads(event.removeprefix("data: ").strip()))

    token_text = "".join(event.get("content", "") for event in events if event["type"] == "token")
    assert "核心结论" in token_text
    assert "关键依据" in token_text
    assert "组织架构调整方案" in token_text
    assert "org.txt" in token_text
    assert not token_text.lstrip().startswith("{")
    assert "key_facts" not in token_text


@pytest.mark.asyncio
async def test_generate_answer_with_language_en_uses_deepseek_then_codex():
    deepseek_client = FakeDeepSeekClient()
    llm_client = FakeLLMClient()
    events = []

    async for event in generate_answer(
        question="How should we adjust the organization?",
        chunks=[sample_chunk()],
        language="en",
        deepseek_endpoint="https://deepseek.example",
        deepseek_api_key="deepseek-secret",
        deepseek_model="deepseek-v4-pro",
        generation_endpoint="https://example.test",
        generation_api_key="secret",
        generation_model="codex-base",
        deepseek_client=deepseek_client,
        llm_client=llm_client,
    ):
        events.append(json.loads(event.removeprefix("data: ").strip()))

    assert len(deepseek_client.prompts) == 1
    assert len(llm_client.prompts) == 1
    assert "English report" in llm_client.prompts[0]
    assert "组织架构调整方案" in llm_client.prompts[0]
    assert [event["type"] for event in events] == ["token", "token", "token", "sources", "done"]


@pytest.mark.asyncio
async def test_english_report_asks_deepseek_for_english_report_facing_analysis():
    deepseek_client = FakeDeepSeekClient()
    events = []

    async for event in generate_answer(
        question="What did I think about the organization design?",
        chunks=[sample_chunk()],
        language="en",
        deepseek_endpoint="https://deepseek.example",
        deepseek_api_key="deepseek-secret",
        deepseek_model="deepseek-v4-pro",
        generation_endpoint="",
        generation_api_key="",
        generation_model="codex-base",
        deepseek_client=deepseek_client,
    ):
        events.append(json.loads(event.removeprefix("data: ").strip()))

    assert len(deepseek_client.prompts) == 1
    prompt = deepseek_client.prompts[0]
    assert "Write all report-facing JSON values in English" in prompt
    assert "content" in prompt
    assert "logic_chain" in prompt
    assert "Keep language as the original source language marker" in prompt


@pytest.mark.asyncio
async def test_query_without_deepseek_returns_config_error_for_zh():
    events = []

    async for event in generate_answer(
        question="怎么调整组织？",
        chunks=[sample_chunk()],
        language="zh",
        deepseek_endpoint="",
        deepseek_api_key="",
        deepseek_model="deepseek-v4-pro",
        generation_endpoint="",
        generation_api_key="",
        generation_model="codex-base",
    ):
        events.append(json.loads(event.removeprefix("data: ").strip()))

    token_text = "".join(event.get("content", "") for event in events if event["type"] == "token")
    assert "DeepSeek 模型未配置" in token_text
    assert [event["type"] for event in events][-2:] == ["sources", "done"]


@pytest.mark.asyncio
async def test_query_without_generation_returns_config_error_for_en():
    events = []

    async for event in generate_answer(
        question="How should we adjust the organization?",
        chunks=[sample_chunk()],
        language="en",
        deepseek_endpoint="https://deepseek.example",
        deepseek_api_key="deepseek-secret",
        deepseek_model="deepseek-v4-pro",
        generation_endpoint="",
        generation_api_key="",
        generation_model="",
        deepseek_client=FakeDeepSeekClient(),
    ):
        events.append(json.loads(event.removeprefix("data: ").strip()))

    token_text = "".join(event.get("content", "") for event in events if event["type"] == "token")
    assert "英文输出模型未配置" in token_text
    assert [event["type"] for event in events][-2:] == ["sources", "done"]


@pytest.mark.asyncio
async def test_english_report_codex_base_fallback_is_readable_not_raw_analysis_dump():
    events = []

    async for event in generate_answer(
        question="Create an English report from these interview materials.",
        chunks=[
            RetrievedChunk(
                chunk_id="interview_case.xlsx#0",
                text="候选人在中英双语材料中展示了组织设计、跨部门协作和复盘能力。",
                source_name="interview_case.xlsx",
                source_type="xlsx",
                chunk_index=0,
                score=0.9,
                rank_fts5=1,
                rank_vector=1,
                raw_file_path="raw/2026-06-13/interview_case.xlsx",
            )
        ],
        language="en",
        deepseek_endpoint="https://deepseek.example",
        deepseek_api_key="deepseek-secret",
        deepseek_model="deepseek-v4-pro",
        generation_endpoint="",
        generation_api_key="",
        generation_model="codex-base",
        deepseek_client=FakeDeepSeekClient(),
    ):
        events.append(json.loads(event.removeprefix("data: ").strip()))

    token_text = "".join(event.get("content", "") for event in events if event["type"] == "token")
    assert "English Report" in token_text
    assert "Executive Summary" in token_text
    assert "Key Findings" in token_text
    assert "Sources" in token_text
    assert "DeepSeek analysis:" not in token_text
    assert "Reference excerpts:" not in token_text
    assert "key_facts" not in token_text
    assert not token_text.lstrip().startswith("{")


def test_web_pages_and_core_api_routes_are_available():
    client = TestClient(app)

    for path in ["/", "/ask", "/settings"]:
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/stats").status_code == 200
    config_response = client.get("/api/config")
    assert config_response.status_code == 200
    assert "api_key" in config_response.json()["generation"]
    assert config_response.json()["generation"]["model"] == "codex-base"


def test_text_ingest_stats_and_source_lookup_round_trip(tmp_path):
    import server

    original = install_temp_runtime(server, tmp_path, "test_text_ingest")
    client = TestClient(app)

    try:
        response = client.post("/api/ingest/text", json={"text": "组织架构调整方案\n\n薪酬激励复盘"})
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["chunks"] >= 1

        stats = client.get("/api/stats").json()
        assert stats["total_chunks"] >= body["chunks"]

        chunk_id = body["chunk_ids"][0]
        source = client.get(f"/api/sources/{chunk_id}").json()
        assert source["chunk_id"] == chunk_id
        assert source["text"]
    finally:
        restore_runtime(server, original)


def test_source_lookup_accepts_chunk_id_query_parameter_with_hash(tmp_path):
    import server

    original = install_temp_runtime(server, tmp_path, "test_source_query_lookup")
    client = TestClient(app)

    try:
        response = client.post("/api/ingest/text", json={"text": "狗狗粪便管理需要设置清理制度。"})
        assert response.status_code == 200
        chunk_id = response.json()["chunk_ids"][0]
        assert "#" in chunk_id

        source = client.get("/api/sources", params={"chunk_id": chunk_id}).json()

        assert source["chunk_id"] == chunk_id
        assert "狗狗粪便管理" in source["text"]
    finally:
        restore_runtime(server, original)


def test_source_lookup_query_parameter_can_render_html_for_browser_click(tmp_path):
    import server

    original = install_temp_runtime(server, tmp_path, "test_source_query_html")
    client = TestClient(app)

    try:
        response = client.post("/api/ingest/text", json={"text": "狗狗粪便管理需要设置清理制度。"})
        chunk_id = response.json()["chunk_ids"][0]

        response = client.get(
            "/api/sources",
            params={"chunk_id": chunk_id},
            headers={"accept": "text/html"},
        )

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "来源片段" in response.text
        assert "狗狗粪便管理" in response.text
        assert '{"detail"' not in response.text
    finally:
        restore_runtime(server, original)


def test_clear_knowledge_resets_index(tmp_path):
    import server

    original = install_temp_runtime(server, tmp_path, "test_clear_api")
    client = TestClient(app)

    try:
        response = client.post("/api/ingest/text", json={"text": "测试数据"})
        assert response.status_code == 200
        before = client.get("/api/stats").json()
        assert before["total_chunks"] >= 1

        response = client.post("/api/ingest/clear")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        after = client.get("/api/stats").json()
        assert after["total_chunks"] == 0
        assert after["indexed_files"] == 0
    finally:
        restore_runtime(server, original)


def test_config_endpoint_updates_runtime_config(tmp_path, monkeypatch):
    import server

    original_config = deepcopy(server.runtime.config)
    monkeypatch.setattr(server, "CONFIG_PATH", tmp_path / "config.yaml")
    client = TestClient(app)

    try:
        response = client.post(
            "/api/config",
            json={"generation": {"endpoint": "https://example.test", "api_key": "secret-value", "model": "m"}},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["generation"]["api_key"] == "****alue"
        assert body["generation"]["model"] == "m"
        assert (tmp_path / "config.yaml").exists()
    finally:
        server.runtime.reload(original_config)


def test_connection_endpoint_returns_readable_component_diagnostics(monkeypatch):
    import server

    original_config = deepcopy(server.runtime.config)

    class FakeEmbeddingClient:
        def embed(self, texts):
            assert texts == ["连接测试"]
            return [[0.1, 0.2, 0.3]]

    class FakeOCRChain:
        providers = []

    server.runtime.config = {
        **deepcopy(original_config),
        "deepseek": {
            "endpoint": "https://deepseek.example/v1/chat/completions",
            "api_key": "deepseek-secret",
            "model": "deepseek-v4-pro",
        },
        "ocr": {
            "endpoint": "",
            "api_key": "",
            "model": "doubao-1-5-vision-pro-32k",
            "max_images_per_request": 10,
        },
        "embedding": {"host": "http://localhost:11434", "model": "bge-m3"},
    }
    monkeypatch.setattr(server.runtime.indexer, "embedding_client", FakeEmbeddingClient())
    monkeypatch.setattr(server, "build_ocr_provider_chain", lambda config: FakeOCRChain())
    client = TestClient(app)

    try:
        response = client.post("/api/test-connection")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "partial"
        checks = {item["id"]: item for item in body["checks"]}
        assert checks["deepseek"]["status"] == "ok"
        assert checks["deepseek"]["label"] == "DeepSeek 中文语义分析"
        assert "deepseek-v4-pro" in checks["deepseek"]["detail"]
        assert checks["embedding"]["status"] == "ok"
        assert checks["embedding"]["label"] == "bge-m3 向量检索"
        assert "Ollama" in checks["embedding"]["detail"]
        assert checks["ocr"]["status"] == "warn"
        assert checks["ocr"]["label"] == "OCR 图片解析"
        assert "未配置" in checks["ocr"]["detail"]
    finally:
        server.runtime.reload(original_config)


def test_connection_endpoint_recognizes_nested_volcengine_ocr_config(monkeypatch):
    import server

    original_config = deepcopy(server.runtime.config)

    class FakeEmbeddingClient:
        def embed(self, texts):
            return [[0.1, 0.2, 0.3]]

    server.runtime.config = {
        **deepcopy(original_config),
        "deepseek": {
            "endpoint": "https://deepseek.example/v1/chat/completions",
            "api_key": "deepseek-secret",
            "model": "deepseek-v4-pro",
        },
        "ocr": {
            "endpoint": "",
            "api_key": "",
            "model": "doubao-1-5-vision-pro-32k",
            "provider_order": ["paddle", "volcengine"],
            "paddle": {"enabled": True, "lang": "ch", "use_angle_cls": True, "dpi": 150},
            "volcengine": {
                "enabled": True,
                "endpoint": "https://ocr.example/v1/chat/completions",
                "api_key": "ocr-secret",
                "model": "doubao-1-5-vision-pro-32k",
                "max_images_per_request": 10,
            },
        },
        "embedding": {"host": "http://localhost:11434", "model": "bge-m3"},
    }
    monkeypatch.setattr(server.runtime.indexer, "embedding_client", FakeEmbeddingClient())
    client = TestClient(app)

    try:
        response = client.post("/api/test-connection")

        assert response.status_code == 200
        checks = {item["id"]: item for item in response.json()["checks"]}
        assert checks["ocr"]["status"] == "ok"
        assert checks["ocr"]["label"] == "OCR 图片解析"
        assert "doubao-1-5-vision-pro-32k" in checks["ocr"]["detail"]
    finally:
        server.runtime.reload(original_config)


def test_connection_endpoint_recognizes_local_paddle_ocr_provider(monkeypatch):
    import server

    original_config = deepcopy(server.runtime.config)

    class FakeEmbeddingClient:
        def embed(self, texts):
            return [[0.1, 0.2, 0.3]]

    class FakeProvider:
        name = "paddle"

        def available(self):
            return True

    class FakeOCRChain:
        providers = [FakeProvider()]

    server.runtime.config = {
        **deepcopy(original_config),
        "deepseek": {
            "endpoint": "https://deepseek.example/v1/chat/completions",
            "api_key": "deepseek-secret",
            "model": "deepseek-v4-pro",
        },
        "ocr": {
            "endpoint": "",
            "api_key": "",
            "model": "doubao-1-5-vision-pro-32k",
            "provider_order": ["paddle", "volcengine"],
            "paddle": {"enabled": True, "lang": "ch", "use_angle_cls": True, "dpi": 150},
            "volcengine": {
                "enabled": True,
                "endpoint": "",
                "api_key": "",
                "model": "doubao-1-5-vision-pro-32k",
                "max_images_per_request": 10,
            },
        },
        "embedding": {"host": "http://localhost:11434", "model": "bge-m3"},
    }
    monkeypatch.setattr(server.runtime.indexer, "embedding_client", FakeEmbeddingClient())
    monkeypatch.setattr(server, "build_ocr_provider_chain", lambda config: FakeOCRChain())
    client = TestClient(app)

    try:
        response = client.post("/api/test-connection")

        assert response.status_code == 200
        checks = {item["id"]: item for item in response.json()["checks"]}
        assert checks["ocr"]["status"] == "ok"
        assert checks["ocr"]["label"] == "OCR 图片解析"
        assert "PaddleOCR 本地可用" in checks["ocr"]["detail"]
    finally:
        server.runtime.reload(original_config)


def test_query_endpoint_passes_language_and_dual_model_config(monkeypatch):
    import server

    captured = {}
    original_config = deepcopy(server.runtime.config)

    class FakeRetriever:
        def hybrid_search(self, question, top_k):
            captured["retriever_question"] = question
            captured["top_k"] = top_k
            return [sample_chunk()]

    async def fake_generate_answer(**kwargs):
        captured["generate_kwargs"] = kwargs
        yield 'data: {"type":"done"}\n\n'

    monkeypatch.setattr(server, "HybridRetriever", lambda **kwargs: FakeRetriever())
    monkeypatch.setattr(server, "generate_answer", fake_generate_answer)
    server.runtime.config = {
        **deepcopy(original_config),
        "deepseek": {
            "endpoint": "https://deepseek.example/v1/chat/completions",
            "api_key": "deepseek-secret",
            "model": "deepseek-v4-pro",
        },
        "generation": {
            "endpoint": "",
            "api_key": "",
            "model": "codex-base",
            "max_context_chunks": 10,
        },
    }
    client = TestClient(app)

    try:
        response = client.post("/api/query", json={"question": "组织架构怎么调？", "language": "en"})

        assert response.status_code == 200
        assert captured["retriever_question"] == "组织架构怎么调？"
        assert captured["generate_kwargs"]["language"] == "en"
        assert captured["generate_kwargs"]["deepseek_endpoint"] == "https://deepseek.example/v1/chat/completions"
        assert captured["generate_kwargs"]["deepseek_api_key"] == "deepseek-secret"
        assert captured["generate_kwargs"]["deepseek_model"] == "deepseek-v4-pro"
        assert captured["generate_kwargs"]["generation_model"] == "codex-base"
    finally:
        server.runtime.reload(original_config)


def test_file_ingest_streams_uploaded_content_to_disk(tmp_path, monkeypatch):
    import server
    from engine.models import ParseResult

    original = install_temp_runtime(server, tmp_path, "test_file_stream")
    seen = {}

    async def fake_parse_file(file_path, mime_type=None, ocr_client=None):
        seen["size"] = Path(file_path).stat().st_size
        return ParseResult(
            text="大文件内容",
            source_name=Path(file_path).name,
            source_type="txt",
            metadata={},
        )

    try:
        monkeypatch.setattr(server, "parse_file", fake_parse_file)
        client = TestClient(app)
        content = b"x" * (1024 * 1024 + 7)

        response = client.post(
            "/api/ingest/file",
            files={"file": ("large.txt", content, "text/plain")},
        )

        assert response.status_code == 200
        assert seen["size"] == len(content)
    finally:
        restore_runtime(server, original)


def test_file_ingest_preserves_raw_file_path_in_source_lookup(tmp_path, monkeypatch):
    import server
    from engine.models import ParseResult

    original = install_temp_runtime(server, tmp_path, "test_raw_file_path")

    async def fake_parse_file(file_path, mime_type=None, ocr_client=None):
        return ParseResult(
            text="附件中的组织架构调整方案已经完成，包含岗位职责、汇报关系和跨部门协作边界说明。",
            source_name=Path(file_path).name,
            source_type="pdf",
            metadata={},
        )

    monkeypatch.setattr(server, "parse_file", fake_parse_file)
    client = TestClient(app)

    try:
        response = client.post(
            "/api/ingest/file",
            files={"file": ("report.pdf", b"pdf bytes", "application/pdf")},
        )
        assert response.status_code == 200
        chunk_id = response.json()["chunk_ids"][0]

        source = client.get(f"/api/sources/{chunk_id}").json()

        assert source["raw_file_path"].startswith("raw/")
        assert source["raw_file_path"].endswith("report.pdf")
    finally:
        restore_runtime(server, original)


def test_file_ingest_rejects_too_many_sync_chunks_before_upsert(tmp_path, monkeypatch):
    import server
    from engine.models import Chunk, ParseResult

    original = install_temp_runtime(server, tmp_path, "test_file_chunk_limit")

    class RecordingIndexer:
        def __init__(self):
            self.upsert_calls = []

        def upsert(self, chunks, raw_file_paths=None):
            self.upsert_calls.append((chunks, raw_file_paths))
            return len(chunks)

        def count_chunks(self):
            return sum(len(chunks) for chunks, _ in self.upsert_calls)

    def fake_chunks(count):
        return [
            Chunk(
                id=f"huge.pdf#{index}",
                text=f"chunk {index}",
                source_name="huge.pdf",
                source_type="pdf",
                chunk_index=index,
                created_at="2026-06-16T00:00:00+08:00",
            )
            for index in range(count)
        ]

    async def fake_parse_file(file_path, mime_type=None, ocr_client=None):
        return ParseResult(
            text="oversized pdf text",
            source_name=Path(file_path).name,
            source_type="pdf",
            metadata={},
        )

    indexer = RecordingIndexer()
    server.runtime.indexer = indexer
    server.runtime.config = {
        **server.runtime.config,
        "ingest": {"max_sync_chunks_per_file": 100},
    }
    monkeypatch.setattr(server, "parse_file", fake_parse_file)
    monkeypatch.setattr(server, "_chunk", lambda text, source_name, source_type: fake_chunks(101))
    client = TestClient(app)

    try:
        response = client.post(
            "/api/ingest/file",
            files={"file": ("huge.pdf", b"pdf bytes", "application/pdf")},
        )

        assert response.status_code == 413
        assert "101" in response.text
        assert "100" in response.text
        assert indexer.upsert_calls == []
    finally:
        restore_runtime(server, original)


def test_bulk_file_ingest_returns_per_file_results_and_preserves_raw_files(tmp_path, monkeypatch):
    import server
    from engine.models import ParseResult

    original = install_temp_runtime(server, tmp_path, "test_bulk_files")
    parsed_files = []

    async def fake_parse_file(file_path, mime_type=None, ocr_client=None):
        parsed_files.append((Path(file_path).name, mime_type))
        return ParseResult(
            text=f"{Path(file_path).stem} 里的知识内容",
            source_name=Path(file_path).name,
            source_type=Path(file_path).suffix.removeprefix(".") or "txt",
            metadata={},
        )

    monkeypatch.setattr(server, "parse_file", fake_parse_file)
    client = TestClient(app)

    try:
        response = client.post(
            "/api/ingest/files",
            files=[
                ("files", ("alpha.txt", b"alpha", "text/plain")),
                ("files", ("beta.md", b"beta", "text/markdown")),
            ],
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["total_files"] == 2
        assert body["succeeded"] == 2
        assert body["failed"] == 0
        assert body["total_chunks"] >= 2
        assert [item["filename"] for item in body["files"]] == ["alpha.txt", "beta.md"]
        assert all(item["status"] == "ok" for item in body["files"])
        assert all(item["chunks"] >= 1 for item in body["files"])
        assert all(item["raw_file_path"].startswith("raw/") for item in body["files"])
        assert parsed_files == [("alpha.txt", "text/plain"), ("beta.md", "text/markdown")]
    finally:
        restore_runtime(server, original)


def test_bulk_file_ingest_marks_oversized_file_error_and_keeps_small_success(tmp_path, monkeypatch):
    import server
    from engine.models import Chunk, ParseResult

    original = install_temp_runtime(server, tmp_path, "test_bulk_chunk_limit")

    class RecordingIndexer:
        def __init__(self):
            self.upsert_calls = []

        def upsert(self, chunks, raw_file_paths=None):
            self.upsert_calls.append((chunks, raw_file_paths))
            return len(chunks)

        def count_chunks(self):
            return sum(len(chunks) for chunks, _ in self.upsert_calls)

    async def fake_parse_file(file_path, mime_type=None, ocr_client=None):
        return ParseResult(
            text=f"{Path(file_path).name} text",
            source_name=Path(file_path).name,
            source_type="pdf",
            metadata={},
        )

    def fake_chunk(text, source_name, source_type):
        count = 101 if source_name == "huge.pdf" else 1
        return [
            Chunk(
                id=f"{source_name}#{index}",
                text=f"{source_name} chunk {index}",
                source_name=source_name,
                source_type=source_type,
                chunk_index=index,
                created_at="2026-06-16T00:00:00+08:00",
            )
            for index in range(count)
        ]

    indexer = RecordingIndexer()
    server.runtime.indexer = indexer
    server.runtime.config = {
        **server.runtime.config,
        "ingest": {"max_sync_chunks_per_file": 100},
    }
    monkeypatch.setattr(server, "parse_file", fake_parse_file)
    monkeypatch.setattr(server, "_chunk", fake_chunk)
    client = TestClient(app)

    try:
        response = client.post(
            "/api/ingest/files",
            files=[
                ("files", ("small.pdf", b"small", "application/pdf")),
                ("files", ("huge.pdf", b"huge", "application/pdf")),
            ],
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "partial"
        assert body["succeeded"] == 1
        assert body["failed"] == 1
        assert body["total_chunks"] == 1
        assert body["files"][0]["status"] == "ok"
        assert body["files"][1]["status"] == "error"
        assert "101" in body["files"][1]["error"]
        assert "100" in body["files"][1]["error"]
        assert body["files"][1]["quality"]["action"] == "too_large_skipped"
        assert len(indexer.upsert_calls) == 1
        assert len(indexer.upsert_calls[0][0]) == 1
    finally:
        restore_runtime(server, original)


def test_bulk_file_ingest_keeps_successes_when_one_file_fails(tmp_path, monkeypatch):
    import server
    from engine.models import ParseResult

    original = install_temp_runtime(server, tmp_path, "test_bulk_partial")

    async def fake_parse_file(file_path, mime_type=None, ocr_client=None):
        if Path(file_path).name == "bad.pdf":
            raise ValueError("无法解析文件内容")
        return ParseResult(
            text="可入库内容",
            source_name=Path(file_path).name,
            source_type="txt",
            metadata={},
        )

    monkeypatch.setattr(server, "parse_file", fake_parse_file)
    client = TestClient(app)

    try:
        response = client.post(
            "/api/ingest/files",
            files=[
                ("files", ("good.txt", b"good", "text/plain")),
                ("files", ("bad.pdf", b"bad", "application/pdf")),
            ],
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "partial"
        assert body["total_files"] == 2
        assert body["succeeded"] == 1
        assert body["failed"] == 1
        assert body["total_chunks"] >= 1
        assert body["files"][0]["status"] == "ok"
        assert body["files"][1]["status"] == "error"
        assert body["files"][1]["error"] == "无法解析文件内容"
    finally:
        restore_runtime(server, original)


def test_manual_text_has_no_raw_file_path(tmp_path):
    import server

    original = install_temp_runtime(server, tmp_path, "test_manual_raw_path")
    client = TestClient(app)

    try:
        response = client.post("/api/ingest/text", json={"text": "纯文本来源"})
        chunk_id = response.json()["chunk_ids"][0]
        source = client.get(f"/api/sources/{chunk_id}").json()

        assert source.get("raw_file_path", "") == ""
    finally:
        restore_runtime(server, original)


def test_raw_file_download_returns_original_file(tmp_path):
    import server

    original_config = deepcopy(server.runtime.config)
    data_dir = tmp_path / "data"
    raw_file = data_dir / "raw" / "2026-06-04" / "report.pdf"
    raw_file.parent.mkdir(parents=True)
    raw_file.write_bytes(b"original pdf bytes")
    server.runtime.config = {**deepcopy(original_config), "data_dir": str(data_dir)}
    client = TestClient(app)

    try:
        response = client.get("/api/files/raw/2026-06-04/report.pdf")

        assert response.status_code == 200
        assert response.content == b"original pdf bytes"
        assert response.headers["content-disposition"].endswith('filename="report.pdf"')
    finally:
        server.runtime.config = original_config


def test_raw_file_path_traversal_blocked(tmp_path):
    import server

    original_config = deepcopy(server.runtime.config)
    server.runtime.config = {**deepcopy(original_config), "data_dir": str(tmp_path / "data")}
    client = TestClient(app)

    try:
        response = client.get("/api/files/..%2F..%2F..%2Fetc%2Fpasswd")

        assert response.status_code == 403
    finally:
        server.runtime.config = original_config
