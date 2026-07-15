from pathlib import Path

from engine.answer_assets import save_answer_asset
from engine.generated_knowledge import promote_answer_asset
from engine.generator import build_deepseek_analysis_prompt
from engine.indexer import HybridIndexer
from engine.models import RetrievedChunk


class FakeIndexer:
    def __init__(self):
        self.calls = []

    def upsert(self, chunks, raw_file_paths=None):
        self.calls.append((chunks, raw_file_paths))
        return len(chunks)


class FakeEmbeddingClient:
    def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, query):
        return [1.0, 0.0]


def _payload(**overrides):
    payload = {
        "question": "我之前的技术选型结论是什么？",
        "answer": "先稳定边界，再逐步扩展。",
        "sources": [{"chunk_id": "architecture.md#2", "source_name": "architecture.md", "source_type": "md"}],
        "source_status": "grounded",
        "evidence": {"coverage": {"coverage_status": "grounded"}},
        "language": "zh",
        "model_route": "local-test",
    }
    payload.update(overrides)
    return payload


def test_promotion_writes_generated_secondary_source_and_indexes_it(tmp_path):
    asset = save_answer_asset(str(tmp_path), _payload())
    indexer = FakeIndexer()

    result = promote_answer_asset(str(tmp_path), asset["asset_id"], indexer, max_chunk_size=200, chunk_overlap=20)

    assert result["rag_status"] == "indexed"
    assert result["outcome"] == "indexed"
    generated_path = tmp_path / result["generated_path"]
    assert generated_path.exists()
    text = generated_path.read_text(encoding="utf-8")
    assert "source_type: generated_asset" in text
    assert "not_primary_source: true" in text
    chunks, raw_paths = indexer.calls[0]
    assert chunks[0].source_type == "generated_asset"
    assert chunks[0].metadata["generated"] is True
    assert raw_paths == [result["generated_path"]] * len(chunks)


def test_promotion_reuses_existing_generated_source_without_reindexing(tmp_path):
    asset = save_answer_asset(str(tmp_path), _payload())
    indexer = FakeIndexer()
    first = promote_answer_asset(str(tmp_path), asset["asset_id"], indexer)
    second = promote_answer_asset(str(tmp_path), asset["asset_id"], indexer)

    assert first["chunk_ids"] == second["chunk_ids"]
    assert second["outcome"] == "idempotent_reuse"
    assert len(indexer.calls) == 1


def test_promotion_preserves_generated_metadata_in_fts_and_vector_results(tmp_path):
    asset = save_answer_asset(str(tmp_path), _payload())
    indexer = HybridIndexer(
        fts_db_path=str(tmp_path / "pka.db"),
        vector_dir=str(tmp_path / "vector"),
        collection_name="generated_metadata",
        embedding_client=FakeEmbeddingClient(),
    )

    promote_answer_asset(str(tmp_path), asset["asset_id"], indexer)

    fts_result = indexer.search_fts("稳定边界", top_k=1)[0]
    vector_result = indexer.search_vector("稳定边界", top_k=1)[0]
    assert fts_result["metadata"]["generated"] is True
    assert fts_result["metadata"]["not_primary_source"] is True
    assert vector_result["metadata"]["generated"] is True
    assert vector_result["metadata"]["derived_from_chunk_ids"] == ["architecture.md#2"]


def test_generated_chunks_are_labeled_as_secondary_context_in_prompt():
    prompt = build_deepseek_analysis_prompt(
        "我之前的技术选型结论是什么？",
        [
            RetrievedChunk(
                chunk_id="generated.md#0",
                text="先稳定边界，再逐步扩展。",
                source_name="generated.md",
                source_type="generated_asset",
                chunk_index=0,
                score=0.9,
                rank_fts5=1,
                rank_vector=1,
            )
        ],
    )

    assert "Generated knowledge chunks" in prompt
    assert "secondary context" in prompt
    assert "not primary evidence" in prompt
