import sqlite3
from urllib.error import URLError

import pytest

from engine.indexer import HybridIndexer, OllamaEmbeddingClient
from engine.models import Chunk
from engine.retriever import HybridRetriever, reciprocal_rank_fusion


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
