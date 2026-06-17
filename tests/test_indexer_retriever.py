import asyncio
import sqlite3
from urllib.error import URLError

import pytest

from engine.indexer import HybridIndexer, OllamaEmbeddingClient
from engine.models import Chunk
from engine.reranker import RerankResult
from engine.retriever import HybridRetriever, apply_org_chart_intent_bias, reciprocal_rank_fusion


class FakeEmbeddingClient:
    def embed(self, texts):
        vectors = []
        for text in texts:
            if "组织架构" in text:
                vectors.append([1.0] + [0.0] * 1023)
            elif "薪酬" in text:
                vectors.append([0.0, 1.0] + [0.0] * 1022)
            else:
                vectors.append([0.0, 0.0, 1.0] + [0.0] * 1021)
        return vectors


class CapturingEmbeddingClient:
    def __init__(self):
        self.texts = []

    def embed(self, texts):
        self.texts.extend(texts)
        return [[1.0] + [0.0] * 1023 for _ in texts]


def make_chunk(chunk_id, text, index):
    return Chunk(
        id=chunk_id,
        text=text,
        source_name=chunk_id.split("#")[0],
        source_type="txt",
        chunk_index=index,
        created_at="2026-06-04T12:00:00+08:00",
    )


def test_indexer_writes_chunks_and_keyword_search_finds_chinese_terms(tmp_path):
    indexer = HybridIndexer(
        fts_db_path=str(tmp_path / "pka.db"),
        vector_dir=str(tmp_path / "vector"),
        collection_name="test_collection",
        embedding_client=FakeEmbeddingClient(),
    )
    chunks = [
        make_chunk("a.txt#0", "组织架构调整方案", 0),
        make_chunk("b.txt#0", "薪酬激励复盘", 0),
    ]

    assert indexer.upsert(chunks) == 2
    results = indexer.search_fts("组织架构调整", top_k=5)

    assert results[0]["chunk_id"] == "a.txt#0"
    assert "组织架构" in results[0]["text"]
    assert not (tmp_path / "vector" / "test_collection.json").exists()


def test_fts_search_escapes_hud_ar_hud_query_syntax(tmp_path):
    indexer = HybridIndexer(
        fts_db_path=str(tmp_path / "pka.db"),
        vector_dir=str(tmp_path / "vector"),
        collection_name="test_collection",
        embedding_client=FakeEmbeddingClient(),
    )
    indexer.upsert([make_chunk("display.pdf#0", "HUD AR-HUD 车载显示的发展重点", 0)])

    results = indexer.search_fts("HUD、AR-HUD 或车载显示的发展重点是什么？", top_k=5)

    assert results
    assert results[0]["chunk_id"] == "display.pdf#0"


def test_indexer_clear_all_removes_vector_and_fts_entries(tmp_path):
    indexer = HybridIndexer(
        fts_db_path=str(tmp_path / "pka.db"),
        vector_dir=str(tmp_path / "vector"),
        collection_name="test_collection",
        embedding_client=FakeEmbeddingClient(),
    )
    indexer.upsert([make_chunk("a.txt#0", "组织架构调整方案", 0)])

    indexer.clear_all()

    assert indexer.count_chunks() == 0
    assert indexer.search_fts("组织架构", top_k=5) == []


def test_indexer_preserves_raw_file_path_in_search_and_lookup(tmp_path):
    indexer = HybridIndexer(
        fts_db_path=str(tmp_path / "pka.db"),
        vector_dir=str(tmp_path / "vector"),
        collection_name="test_collection",
        embedding_client=FakeEmbeddingClient(),
    )
    raw_path = "raw/2026-06-04/report.pdf"

    indexer.upsert([make_chunk("report.pdf#0", "组织架构调整方案", 0)], raw_file_paths=[raw_path])

    assert indexer.search_fts("组织架构", top_k=5)[0]["raw_file_path"] == raw_path
    assert indexer.search_vector("组织架构", top_k=5)[0]["raw_file_path"] == raw_path
    assert indexer.get_chunk("report.pdf#0")["raw_file_path"] == raw_path


def test_search_vector_fails_open_when_chroma_query_errors(tmp_path):
    indexer = HybridIndexer(
        fts_db_path=str(tmp_path / "pka.db"),
        vector_dir=str(tmp_path / "vector"),
        collection_name="test_collection",
        embedding_client=FakeEmbeddingClient(),
    )
    indexer.upsert([make_chunk("a.txt#0", "组织架构调整方案", 0)])

    class BrokenCollection:
        def count(self):
            return 1

        def query(self, **kwargs):
            raise RuntimeError("Cannot return the results in a contigious 2D array")

    indexer.collection = BrokenCollection()

    assert indexer.search_vector("组织架构", top_k=10) == []


def test_search_vector_retries_lower_n_results_when_chroma_hnsw_limit_errors(tmp_path):
    indexer = HybridIndexer(
        fts_db_path=str(tmp_path / "pka.db"),
        vector_dir=str(tmp_path / "vector"),
        collection_name="test_collection",
        embedding_client=FakeEmbeddingClient(),
    )

    class HnswLimitedCollection:
        def __init__(self):
            self.requested_n_results = []

        def count(self):
            return 10

        def query(self, **kwargs):
            n_results = kwargs["n_results"]
            self.requested_n_results.append(n_results)
            if n_results > 3:
                raise RuntimeError("Cannot return the results in a contigious 2D array")
            return {
                "ids": [["a.txt#0", "b.txt#0", "c.txt#0"][:n_results]],
                "documents": [["组织架构调整方案", "组织架构职责", "组织架构备注"][:n_results]],
                "metadatas": [[
                    {
                        "source_name": f"{name}.txt",
                        "source_type": "txt",
                        "chunk_index": index,
                        "created_at": "2026-06-04T12:00:00+08:00",
                        "raw_file_path": "",
                    }
                    for index, name in enumerate(["a", "b", "c"][:n_results])
                ]],
                "distances": [[0.1, 0.2, 0.3][:n_results]],
            }

    collection = HnswLimitedCollection()
    indexer.collection = collection

    results = indexer.search_vector("组织架构", top_k=10)

    assert [result["chunk_id"] for result in results] == ["a.txt#0", "b.txt#0", "c.txt#0"]
    assert collection.requested_n_results == [10, 5, 3]


@pytest.mark.asyncio
async def test_search_vector_queries_chroma_outside_running_event_loop(tmp_path):
    indexer = HybridIndexer(
        fts_db_path=str(tmp_path / "pka.db"),
        vector_dir=str(tmp_path / "vector"),
        collection_name="test_collection",
        embedding_client=FakeEmbeddingClient(),
    )

    class AsyncUnsafeCollection:
        def count(self):
            return 1

        def query(self, **kwargs):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                pass
            else:
                raise RuntimeError("Cannot return the results in a contigious 2D array")
            return {
                "ids": [["a.txt#0"]],
                "documents": [["组织架构调整方案"]],
                "metadatas": [[{
                    "source_name": "a.txt",
                    "source_type": "txt",
                    "chunk_index": 0,
                    "created_at": "2026-06-04T12:00:00+08:00",
                    "raw_file_path": "",
                }]],
                "distances": [[0.1]],
            }

    indexer.collection = AsyncUnsafeCollection()

    results = indexer.search_vector("组织架构", top_k=10)

    assert results[0]["chunk_id"] == "a.txt#0"
    assert results[0]["source_type"] == "txt"


def test_hybrid_retriever_returns_semantic_results_and_new_chunks_are_immediate(tmp_path):
    indexer = HybridIndexer(
        fts_db_path=str(tmp_path / "pka.db"),
        vector_dir=str(tmp_path / "vector"),
        collection_name="test_collection",
        embedding_client=FakeEmbeddingClient(),
    )
    indexer.upsert([make_chunk("a.txt#0", "组织架构调整方案", 0)])
    retriever = HybridRetriever(indexer=indexer, rrf_k=60)

    first = retriever.hybrid_search("管理变革", top_k=5)
    assert first[0].chunk_id == "a.txt#0"

    indexer.upsert([make_chunk("b.txt#0", "薪酬激励复盘", 0)])
    second = retriever.hybrid_search("薪酬", top_k=5)
    assert second[0].chunk_id == "b.txt#0"


def test_hybrid_retriever_passes_raw_file_path(tmp_path):
    indexer = HybridIndexer(
        fts_db_path=str(tmp_path / "pka.db"),
        vector_dir=str(tmp_path / "vector"),
        collection_name="test_collection",
        embedding_client=FakeEmbeddingClient(),
    )
    raw_path = "raw/2026-06-04/report.pdf"
    indexer.upsert([make_chunk("report.pdf#0", "组织架构调整方案", 0)], raw_file_paths=[raw_path])

    result = HybridRetriever(indexer=indexer).hybrid_search("组织架构", top_k=5)[0]

    assert result.raw_file_path == raw_path


def test_rrf_ranks_intersection_above_single_list_results():
    fused = reciprocal_rank_fusion(
        [{"chunk_id": "a", "text": "A"}, {"chunk_id": "shared", "text": "S"}],
        [{"chunk_id": "shared", "text": "S"}, {"chunk_id": "b", "text": "B"}],
        k=60,
    )

    assert fused[0]["chunk_id"] == "shared"
    assert fused[0]["rank_fts5"] == 2
    assert fused[0]["rank_vector"] == 1


def test_rrf_tie_break_prefers_vector_rank_over_fts_insertion_order():
    fused = reciprocal_rank_fusion(
        [{"chunk_id": "fts_only", "text": "F"}],
        [{"chunk_id": "vector_only", "text": "V"}],
        k=60,
    )

    assert [item["chunk_id"] for item in fused] == ["vector_only", "fts_only"]
    assert fused[0]["score"] == fused[1]["score"]


def test_rrf_ordering_respects_score_before_tie_break_components():
    fused = reciprocal_rank_fusion(
        [
            {"chunk_id": "fts_rank_1", "text": "F1"},
            {"chunk_id": "dual", "text": "D"},
            {"chunk_id": "fts_rank_3", "text": "F3"},
        ],
        [
            {"chunk_id": "dual", "text": "D"},
            {"chunk_id": "vector_rank_2", "text": "V2"},
            {"chunk_id": "vector_rank_3", "text": "V3"},
        ],
        k=60,
    )

    assert [item["chunk_id"] for item in fused] == [
        "dual",
        "fts_rank_1",
        "vector_rank_2",
        "vector_rank_3",
        "fts_rank_3",
    ]


def test_empty_search_returns_empty_list(tmp_path):
    indexer = HybridIndexer(
        fts_db_path=str(tmp_path / "pka.db"),
        vector_dir=str(tmp_path / "vector"),
        collection_name="test_collection",
        embedding_client=FakeEmbeddingClient(),
    )
    retriever = HybridRetriever(indexer=indexer)

    assert retriever.hybrid_search("不存在", top_k=5) == []


def test_fts5_text_column_is_unindexed(tmp_path):
    HybridIndexer(
        fts_db_path=str(tmp_path / "pka.db"),
        vector_dir=str(tmp_path / "vector"),
        collection_name="test_collection",
        embedding_client=FakeEmbeddingClient(),
    )

    with sqlite3.connect(str(tmp_path / "pka.db")) as connection:
        sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'chunks_fts'"
        ).fetchone()[0]

    assert "text UNINDEXED" in sql


def test_ollama_embedding_client_calls_local_embeddings_api(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return b'{"embedding": [0.1, 0.2, 0.3]}'

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = request.data.decode("utf-8")
        captured["content_type"] = request.headers["Content-type"]
        return FakeResponse()

    monkeypatch.setattr("engine.indexer.urllib.request.urlopen", fake_urlopen)

    client = OllamaEmbeddingClient(host="http://localhost:11434", model="bge-m3")

    assert client.embed(["组织架构调整方案"]) == [[0.1, 0.2, 0.3]]
    assert captured["url"] == "http://localhost:11434/api/embeddings"
    assert captured["timeout"] == 60
    assert '"model": "bge-m3"' in captured["body"]
    assert '"prompt": "组织架构调整方案"' in captured["body"]
    assert captured["content_type"] == "application/json"


def test_ollama_embedding_client_raises_instead_of_hash_fallback(monkeypatch):
    def fake_urlopen(request, timeout):
        raise URLError("connection refused")

    monkeypatch.setattr("engine.indexer.urllib.request.urlopen", fake_urlopen)
    client = OllamaEmbeddingClient(host="http://localhost:11434", model="bge-m3")

    with pytest.raises(RuntimeError, match="Ollama embedding failed"):
        client.embed(["组织架构调整方案"])


def test_embedding_text_used_only_for_vector_embedding(tmp_path):
    embedding_client = CapturingEmbeddingClient()
    indexer = HybridIndexer(
        fts_db_path=str(tmp_path / "pka.db"),
        vector_dir=str(tmp_path / "vector"),
        collection_name="test_collection",
        embedding_client=embedding_client,
    )
    chunk = Chunk(
        id="report.pdf#0",
        text="市场规模达到 1200 亿元。",
        embedding_text="[BREADCRUMB]# 智能座舱 > ## 市场规模[/BREADCRUMB]\n\n市场规模达到 1200 亿元。",
        source_name="report.pdf",
        source_type="pdf",
        chunk_index=0,
        created_at="2026-06-13T12:00:00+08:00",
    )

    indexer.upsert([chunk])

    assert embedding_client.texts[0].startswith("[BREADCRUMB]")
    assert indexer.search_fts("BREADCRUMB", top_k=5) == []
    assert indexer.get_chunk("report.pdf#0")["text"] == "市场规模达到 1200 亿元。"


def test_query_embedding_uses_prefix_but_document_embedding_does_not(monkeypatch):
    captured = []

    def fake_embed_one(text):
        captured.append(text)
        return [0.1] * 1024

    client = OllamaEmbeddingClient(
        host="http://localhost:11434",
        model="bge-m3",
        query_prefix="Represent this sentence for searching relevant passages: ",
    )
    monkeypatch.setattr(client, "_embed_one", fake_embed_one)

    client.embed(["入库文本"])
    client.embed_query("查询文本")

    assert captured[0] == "入库文本"
    assert captured[1].startswith("Represent this sentence for searching relevant passages: ")


class FakeSearchIndexer:
    def search_fts(self, query, top_k):
        return [
            {
                "chunk_id": "noise",
                "text": "Page 12",
                "source_name": "a.pdf",
                "source_type": "pdf",
                "chunk_index": 0,
            },
            {
                "chunk_id": "answer",
                "text": "组织架构调整存在品牌能力丢失风险。",
                "source_name": "b.pdf",
                "source_type": "pdf",
                "chunk_index": 1,
            },
        ]

    def search_vector(self, query, top_k):
        return [
            {
                "chunk_id": "answer",
                "text": "组织架构调整存在品牌能力丢失风险。",
                "source_name": "b.pdf",
                "source_type": "pdf",
                "chunk_index": 1,
            },
            {
                "chunk_id": "noise2",
                "text": "© 水印",
                "source_name": "c.pdf",
                "source_type": "pdf",
                "chunk_index": 2,
            },
        ]


def test_hybrid_retriever_uses_reranker_after_rrf():
    class FakeReranker:
        def rerank(self, query, candidates):
            return [
                RerankResult(chunk_id="answer", score=0.98),
                RerankResult(chunk_id="noise", score=0.05),
                RerankResult(chunk_id="noise2", score=0.01),
            ]

    retriever = HybridRetriever(indexer=FakeSearchIndexer(), reranker=FakeReranker())
    results = retriever.hybrid_search("我之前关于组织架构的看法是什么？", top_k=2)

    assert results[0].chunk_id == "answer"
    assert results[0].score == 0.98


def test_hybrid_retriever_fails_open_when_reranker_errors():
    class FailingReranker:
        def rerank(self, query, candidates):
            raise RuntimeError("reranker unavailable")

    retriever = HybridRetriever(indexer=FakeSearchIndexer(), reranker=FailingReranker())
    results = retriever.hybrid_search("组织架构", top_k=2)

    assert len(results) == 2
    assert {item.chunk_id for item in results}


def test_org_chart_intent_bias_only_reorders_nearby_projection_chunks():
    fused = [
        {
            "chunk_id": "pdf",
            "text": "I N F O T A I N M E N T and connectivity overview",
            "source_type": "pdf",
            "score": 0.03055,
            "rank_fts5": 4,
            "rank_vector": 7,
        },
        {
            "chunk_id": "org",
            "text": "[ORG_CHART]\nSemantic Search Triggers:\n- A is structurally under B.",
            "source_type": "org_chart",
            "score": 0.03031,
            "rank_fts5": 7,
            "rank_vector": 5,
        },
    ]

    biased = apply_org_chart_intent_bias(
        "Which people are structurally under Infotainment and Connectivity?",
        fused,
    )

    assert [item["chunk_id"] for item in biased] == ["org", "pdf"]


def test_org_chart_intent_bias_does_not_affect_explanation_queries():
    fused = [
        {
            "chunk_id": "pdf",
            "text": "HOW TO READ THE ORGANISATION CHARTS",
            "source_type": "pdf",
            "score": 0.03055,
            "rank_fts5": 1,
            "rank_vector": 7,
        },
        {
            "chunk_id": "org",
            "text": "[ORG_CHART]\nSemantic Search Triggers:\n- A is structurally under B.",
            "source_type": "org_chart",
            "score": 0.03031,
            "rank_fts5": 7,
            "rank_vector": 5,
        },
    ]

    biased = apply_org_chart_intent_bias("How should the organisation charts be read?", fused)

    assert [item["chunk_id"] for item in biased] == ["pdf", "org"]


def test_org_chart_intent_bias_requires_projection_evidence_not_score_window():
    fused = [
        {
            "chunk_id": "pdf",
            "text": "Infotainment and connectivity overview",
            "source_type": "pdf",
            "score": 0.04,
            "rank_fts5": 1,
            "rank_vector": 3,
        },
        {
            "chunk_id": "bad_org",
            "text": "plain text mislabeled as org chart",
            "source_type": "org_chart",
            "score": 0.0399,
            "rank_fts5": 2,
            "rank_vector": 1,
        },
        {
            "chunk_id": "far_org",
            "text": "[ORG_CHART]\nSemantic Search Triggers:\n- A is structurally under B.",
            "source_type": "org_chart",
            "score": 0.035,
            "rank_fts5": 3,
            "rank_vector": 2,
        },
    ]

    biased = apply_org_chart_intent_bias(
        "Which people are structurally under Infotainment and Connectivity?",
        fused,
    )

    assert [item["chunk_id"] for item in biased] == ["far_org", "pdf", "bad_org"]


def test_hybrid_search_with_debug_returns_dict_with_chunk_id_keys():
    class DebugSearchIndexer:
        def search_fts(self, query, top_k):
            return [
                {
                    "chunk_id": "jlr.pdf#org_chart_51",
                    "text": "[ORG_CHART]\nSemantic Search Triggers:\n- A is structurally under B.",
                    "source_name": "jlr.pdf",
                    "source_type": "org_chart",
                    "chunk_index": 51,
                    "score": 0.0,
                },
                {
                    "chunk_id": "jlr.pdf#4",
                    "text": "HOW TO READ THE ORGANISATION CHARTS",
                    "source_name": "jlr.pdf",
                    "source_type": "pdf",
                    "chunk_index": 4,
                    "score": 0.0,
                },
            ]

        def search_vector(self, query, top_k):
            return [
                {
                    "chunk_id": "jlr.pdf#4",
                    "text": "HOW TO READ THE ORGANISATION CHARTS",
                    "source_name": "jlr.pdf",
                    "source_type": "pdf",
                    "chunk_index": 4,
                    "score": 0.0,
                },
                {
                    "chunk_id": "jlr.pdf#org_chart_51",
                    "text": "[ORG_CHART]\nSemantic Search Triggers:\n- A is structurally under B.",
                    "source_name": "jlr.pdf",
                    "source_type": "org_chart",
                    "chunk_index": 51,
                    "score": 0.0,
                },
            ]

    retriever = HybridRetriever(indexer=DebugSearchIndexer(), rrf_k=60)

    chunks, debug_by_chunk_id = retriever.hybrid_search_with_debug(
        query="Which people are structurally under Infotainment and Connectivity?",
        top_k=2,
    )

    assert [chunk.chunk_id for chunk in chunks] == ["jlr.pdf#org_chart_51", "jlr.pdf#4"]
    assert set(debug_by_chunk_id) == {"jlr.pdf#org_chart_51", "jlr.pdf#4"}
    org_debug = debug_by_chunk_id["jlr.pdf#org_chart_51"]
    assert org_debug["chunk_id"] == "jlr.pdf#org_chart_51"
    assert org_debug["source_type"] == "org_chart"
    assert org_debug["fts_rank"] == 1
    assert org_debug["vector_rank"] == 2
    assert org_debug["rrf_score"] > 0
    assert org_debug["final_rank"] == 1
    assert org_debug["intent_bias_triggered"] is True
    assert org_debug["intent_bias_applied"] is True


def test_reranker_receives_display_text_not_embedding_text():
    captured = {}

    class CapturingReranker:
        def rerank(self, query, candidates):
            captured["candidates"] = candidates
            return [RerankResult(chunk_id=candidates[0]["chunk_id"], score=0.9)]

    class DisplayTextIndexer:
        def search_fts(self, query, top_k):
            return [
                {
                    "chunk_id": "report.pdf#0",
                    "text": "市场规模达到 1200 亿元。",
                    "source_name": "report.pdf",
                    "source_type": "pdf",
                    "chunk_index": 0,
                }
            ]

        def search_vector(self, query, top_k):
            return []

    retriever = HybridRetriever(indexer=DisplayTextIndexer(), reranker=CapturingReranker())
    retriever.hybrid_search("市场规模", top_k=1)

    assert captured["candidates"][0]["text"] == "市场规模达到 1200 亿元。"
    assert "BREADCRUMB" not in captured["candidates"][0]["text"]
