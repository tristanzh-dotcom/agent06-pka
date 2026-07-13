from fastapi.testclient import TestClient

import server
from server import app


class FailingIndexer:
    def upsert(self, *args, **kwargs):
        raise AssertionError("answer result operation contract must not index before Agent10 storage is wired")


def answer_result_payload(**overrides):
    payload = {
        "question": "我之前关于组织架构的判断是什么？",
        "answer": "你倾向于先明确职责边界，再调整汇报关系。",
        "sources": [
            {
                "source_name": "org.txt",
                "source_type": "text",
                "chunk_index": 0,
                "relevance": 0.91,
                "chunk_id": "org.txt#0",
                "raw_file_path": "",
            }
        ],
        "source_status": "grounded",
        "evidence": {
            "coverage": {
                "coverage_status": "grounded",
                "source_count": 1,
                "chunk_count": 1,
            }
        },
        "language": "zh",
        "model_route": "deepseek",
        "answer_mode": "answer",
        "created_at": "2026-07-04T10:00:00+08:00",
    }
    payload.update(overrides)
    return payload


def test_add_generated_contract_rejects_empty_question_and_answer():
    client = TestClient(app)

    missing_question = client.post("/api/knowledge/add-generated", json=answer_result_payload(question="  "))
    missing_answer = client.post("/api/knowledge/add-generated", json=answer_result_payload(answer=""))

    assert missing_question.status_code == 400
    assert missing_question.json()["detail"] == "question is required"
    assert missing_answer.status_code == 400
    assert missing_answer.json()["detail"] == "answer is required"


def test_save_local_destination_reuses_same_answer_snapshot(tmp_path):
    original_config = server.runtime.config
    server.runtime.config = {**server.runtime.config, "data_dir": str(tmp_path)}
    try:
        client = TestClient(app)
        first = client.post("/api/answer-assets/save-local", json=answer_result_payload())
        second = client.post("/api/answer-assets/save-local", json=answer_result_payload())
    finally:
        server.runtime.config = original_config

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["asset_id"] == second.json()["asset_id"]
    assert first.json()["publication_status"] == "local_only"
    assert second.json()["outcome"] == "idempotent_reuse"


def test_publish_obsidian_destination_reuses_local_asset_and_reports_agent10_result(tmp_path, monkeypatch):
    calls = []

    def fake_publish(asset_dir):
        calls.append(asset_dir)
        return {"asset_id": "ast_publish", "path": "01_Agents/Agent06/note.md", "mode": "rest", "mirror_status": "upserted"}

    original_config = server.runtime.config
    server.runtime.config = {**server.runtime.config, "data_dir": str(tmp_path)}
    monkeypatch.setenv("AGENT10_CONTROL_TOKEN", "0" * 64)
    monkeypatch.setattr(server, "_publish_agent10_agent06_asset", fake_publish)
    try:
        response = TestClient(app).post("/api/answer-assets/publish-obsidian", json=answer_result_payload())
    finally:
        server.runtime.config = original_config

    assert response.status_code == 201
    assert response.json()["publication_status"] == "published"
    assert response.json()["agent10"]["asset_id"] == "ast_publish"
    assert len(calls) == 1


def test_add_generated_contract_rejects_no_answer_without_indexing(tmp_path):
    original_config = server.runtime.config
    original_indexer = server.runtime.indexer
    server.runtime.config = {**server.runtime.config, "data_dir": str(tmp_path)}
    server.runtime.indexer = FailingIndexer()
    try:
        client = TestClient(app)
        response = client.post(
            "/api/knowledge/add-generated",
            json=answer_result_payload(source_status="no_answer", sources=[]),
        )
    finally:
        server.runtime.config = original_config
        server.runtime.indexer = original_indexer

    assert response.status_code == 409
    assert response.json()["detail"] == "no_answer results cannot be added to knowledge yet"


def test_add_generated_contract_saves_local_asset_and_defers_when_agent10_unconfigured(tmp_path, monkeypatch):
    original_config = server.runtime.config
    original_indexer = server.runtime.indexer
    server.runtime.config = {**server.runtime.config, "data_dir": str(tmp_path)}
    server.runtime.indexer = FailingIndexer()
    monkeypatch.delenv("AGENT10_CONTROL_TOKEN", raising=False)
    monkeypatch.delenv("AGENT10_CONTROL_TOKEN_FILE", raising=False)
    try:
        client = TestClient(app)
        response = client.post("/api/knowledge/add-generated", json=answer_result_payload())
    finally:
        server.runtime.config = original_config
        server.runtime.indexer = original_indexer

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "deferred"
    assert body["storage_status"] == "agent10_not_configured"
    assert body["indexed"] is False
    assert body["local_asset"]["asset_path"].startswith("assets/answers/")
    assert (tmp_path / body["local_asset"]["manifest_path"]).exists()
    assert (tmp_path / body["local_asset"]["answer_path"]).exists()


def test_add_generated_contract_publishes_saved_answer_asset_to_agent10(tmp_path, monkeypatch):
    calls = []

    def fake_publish(asset_dir):
        calls.append(asset_dir)
        return {
            "asset_id": "ast_20260713_answer01",
            "path": "01_Agents/Agent06/2026-07-13 - answer.md",
            "mode": "rest",
            "mirror_status": "upserted",
            "producer_id": "agent06",
        }

    original_config = server.runtime.config
    original_indexer = server.runtime.indexer
    server.runtime.config = {**server.runtime.config, "data_dir": str(tmp_path)}
    server.runtime.indexer = FailingIndexer()
    monkeypatch.setenv("AGENT10_CONTROL_TOKEN", "0" * 64)
    monkeypatch.setattr(server, "_publish_agent10_agent06_asset", fake_publish)
    try:
        client = TestClient(app)
        response = client.post("/api/knowledge/add-generated", json=answer_result_payload())
    finally:
        server.runtime.config = original_config
        server.runtime.indexer = original_indexer

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ok"
    assert body["storage_status"] == "agent10_published"
    assert body["indexed"] is False
    assert body["agent10"]["asset_id"] == "ast_20260713_answer01"
    assert body["local_asset"]["asset_path"].startswith("assets/answers/")
    assert calls == [str((tmp_path / body["local_asset"]["asset_path"]).resolve())]


def test_ask_page_exposes_deferred_destination_controls_without_wiring_them():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    ask_html = (root / "static/ask.html").read_text(encoding="utf-8")
    app_js = (root / "static/app.js").read_text(encoding="utf-8")

    assert 'id="save-local-asset"' in ask_html
    assert 'id="publish-obsidian"' in ask_html
    assert 'id="add-pka-retrieval"' in ask_html
    assert 'id="add-knowledge"' not in ask_html
    assert "function buildAnswerResultSnapshot" in app_js
    assert "created_at: askState.createdAt" in app_js
    assert "evidence: askState.evidence" in app_js
    assert "source_status: askState.sourceStatus || \"grounded\"" in app_js
    assert "function canAddAnswerResultToKnowledge" not in app_js
    assert 'postJSON("api/knowledge/add-generated", buildAnswerResultSnapshot())' not in app_js
    assert 'document.getElementById("add-knowledge")?.addEventListener("click", addAnswerResultToKnowledge)' not in app_js
