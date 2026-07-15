from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path

from fastapi.testclient import TestClient

import server
from server import app


class FailingIndexer:
    def upsert(self, *args, **kwargs):
        raise AssertionError("saving answer assets must not index into RAG")


def install_asset_runtime(tmp_path):
    original = (deepcopy(server.runtime.config), server.runtime.indexer, server.runtime.last_updated)
    server.runtime.config = {
        **deepcopy(original[0]),
        "data_dir": str(tmp_path / "data"),
    }
    server.runtime.indexer = FailingIndexer()
    return original


def restore_runtime(original):
    server.runtime.config, server.runtime.indexer, server.runtime.last_updated = original


def sample_payload(**overrides):
    payload = {
        "question": "如何总结我这次 JLR 面试复盘？",
        "answer": "核心结论是先把组织调整经验讲清楚，再补充跨团队推进证据。",
        "sources": [
            {
                "source_name": "jlr_notes.md",
                "source_type": "md",
                "chunk_index": 2,
                "chunk_id": "jlr_notes.md#2",
                "relevance": 0.91,
                "raw_file_path": "raw/2026-06-04/jlr_notes.md",
            }
        ],
        "source_status": "grounded",
        "evidence": {"coverage": {"coverage_status": "grounded", "chunk_count": 1}},
        "language": "zh",
        "answer_mode": "retrospective",
        "model_route": "deepseek",
        "title": "JLR 面试复盘总结",
    }
    payload.update(overrides)
    return payload


def test_save_answer_asset_writes_manifest_and_markdown_without_indexing(tmp_path):
    original = install_asset_runtime(tmp_path)
    try:
        client = TestClient(app)

        response = client.post("/api/assets/answers", json=sample_payload())

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["asset_type"] == "answer_result"
        assert body["title"] == "JLR 面试复盘总结"
        assert body["rag_status"] == "not_indexed"
        assert body["asset_path"].startswith("assets/answers/")
        assert body["manifest_path"].endswith("/manifest.json")
        assert body["answer_path"].endswith("/answer.md")

        data_dir = Path(server.runtime.config["data_dir"])
        manifest_path = data_dir / body["manifest_path"]
        answer_path = data_dir / body["answer_path"]
        assert manifest_path.exists()
        assert answer_path.exists()

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["asset_id"] == body["asset_id"]
        assert manifest["asset_type"] == "answer_result"
        assert manifest["question"] == "如何总结我这次 JLR 面试复盘？"
        assert manifest["answer"] == "核心结论是先把组织调整经验讲清楚，再补充跨团队推进证据。"
        assert manifest["sources"][0]["chunk_id"] == "jlr_notes.md#2"
        assert manifest["source_status"] == "grounded"
        assert manifest["evidence"]["coverage"]["coverage_status"] == "grounded"
        assert manifest["language"] == "zh"
        assert manifest["answer_mode"] == "retrospective"
        assert manifest["model_route"] == "deepseek"
        assert manifest["rag_status"] == "not_indexed"
        assert manifest["exports"] == []

        markdown = answer_path.read_text(encoding="utf-8")
        assert "# JLR 面试复盘总结" in markdown
        assert "## Question" in markdown
        assert "如何总结我这次 JLR 面试复盘？" in markdown
        assert "## Answer" in markdown
        assert "核心结论是先把组织调整经验讲清楚" in markdown
        assert "jlr_notes.md#2" in markdown
        assert "rag_status: not_indexed" in markdown
    finally:
        restore_runtime(original)


def test_save_answer_asset_rejects_empty_question_and_answer(tmp_path):
    original = install_asset_runtime(tmp_path)
    try:
        client = TestClient(app)

        missing_question = client.post("/api/assets/answers", json=sample_payload(question="  "))
        missing_answer = client.post("/api/assets/answers", json=sample_payload(answer=""))

        assert missing_question.status_code == 400
        assert missing_answer.status_code == 400
    finally:
        restore_runtime(original)


def test_save_answer_asset_allows_no_answer_result_but_keeps_not_indexed(tmp_path):
    original = install_asset_runtime(tmp_path)
    try:
        client = TestClient(app)

        response = client.post(
            "/api/assets/answers",
            json=sample_payload(
                source_status="no_answer",
                sources=[],
                answer="当前知识库缺少相关信息，无法回答该问题。建议补充相关资料后重新提问。",
            ),
        )

        assert response.status_code == 200
        body = response.json()
        manifest = json.loads((Path(server.runtime.config["data_dir"]) / body["manifest_path"]).read_text(encoding="utf-8"))
        assert manifest["source_status"] == "no_answer"
        assert manifest["sources"] == []
        assert manifest["rag_status"] == "not_indexed"
    finally:
        restore_runtime(original)


def test_list_and_read_answer_assets(tmp_path):
    original = install_asset_runtime(tmp_path)
    try:
        client = TestClient(app)
        first = client.post("/api/assets/answers", json=sample_payload(title="第一条资产", question="第一条问题")).json()
        second = client.post("/api/assets/answers", json=sample_payload(title="第二条资产", question="第二条问题")).json()

        list_response = client.get("/api/assets/answers?limit=10")

        assert list_response.status_code == 200
        assets = list_response.json()["assets"]
        assert [asset["asset_id"] for asset in assets[:2]] == [second["asset_id"], first["asset_id"]]
        assert assets[0]["title"] == "第二条资产"
        assert assets[0]["rag_status"] == "not_indexed"
        assert "answer" not in assets[0]

        read_response = client.get(f"/api/assets/answers/{first['asset_id']}")

        assert read_response.status_code == 200
        asset = read_response.json()["asset"]
        assert asset["asset_id"] == first["asset_id"]
        assert asset["manifest"]["title"] == "第一条资产"
        assert "## Answer" in asset["answer_markdown"]
    finally:
        restore_runtime(original)


def test_list_answer_assets_supports_before_cursor_and_caps_limit(tmp_path, monkeypatch):
    original = install_asset_runtime(tmp_path)
    base_time = datetime(2026, 7, 3, 9, 0, 0)
    ticks = iter(base_time + timedelta(minutes=index) for index in range(3))

    class FixedDatetime:
        @classmethod
        def now(cls):
            return next(ticks)

    monkeypatch.setattr("engine.answer_assets.datetime", FixedDatetime)
    try:
        client = TestClient(app)
        first = client.post("/api/assets/answers", json=sample_payload(title="第一条资产", question="第一条问题")).json()
        second = client.post("/api/assets/answers", json=sample_payload(title="第二条资产", question="第二条问题")).json()
        third = client.post("/api/assets/answers", json=sample_payload(title="第三条资产", question="第三条问题")).json()

        first_page = client.get("/api/assets/answers?limit=1").json()["assets"]
        before_second = client.get(f"/api/assets/answers?limit=10&before={second['created_at']}").json()["assets"]
        capped = client.get("/api/assets/answers?limit=999").json()["assets"]

        assert [asset["asset_id"] for asset in first_page] == [third["asset_id"]]
        assert [asset["asset_id"] for asset in before_second] == [first["asset_id"]]
        assert len(capped) == 3
    finally:
        restore_runtime(original)


def test_read_rejects_unsafe_asset_ids(tmp_path):
    original = install_asset_runtime(tmp_path)
    try:
        client = TestClient(app)

        traversal = client.get("/api/assets/answers/..%2Fconfig.yaml")
        dotted = client.get("/api/assets/answers/ans_../../secret")

        assert traversal.status_code == 404
        assert dotted.status_code == 404
    finally:
        restore_runtime(original)


def test_delete_answer_asset_removes_saved_files_and_hides_from_list(tmp_path):
    original = install_asset_runtime(tmp_path)
    try:
        client = TestClient(app)
        saved = client.post("/api/assets/answers", json=sample_payload()).json()
        data_dir = Path(server.runtime.config["data_dir"])
        asset_dir = data_dir / saved["asset_path"]

        response = client.delete(f"/api/assets/answers/{saved['asset_id']}")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "deleted_asset_id": saved["asset_id"]}
        assert not asset_dir.exists()
        assert client.get(f"/api/assets/answers/{saved['asset_id']}").status_code == 404
        assert client.get("/api/assets/answers?limit=10").json()["assets"] == []
    finally:
        restore_runtime(original)


def test_delete_answer_asset_rejects_missing_or_unsafe_asset_ids(tmp_path):
    original = install_asset_runtime(tmp_path)
    try:
        client = TestClient(app)

        traversal = client.delete("/api/assets/answers/..%2Fconfig.yaml")
        missing = client.delete("/api/assets/answers/ans_20260703120000_abcdef")

        assert traversal.status_code == 404
        assert missing.status_code == 404
    finally:
        restore_runtime(original)


def test_asset_word_export_uses_saved_asset_and_records_latest_five_exports(tmp_path):
    original = install_asset_runtime(tmp_path)
    try:
        client = TestClient(app)
        saved = client.post("/api/assets/answers", json=sample_payload()).json()

        responses = [
            client.post(f"/api/assets/answers/{saved['asset_id']}/export/word")
            for _ in range(6)
        ]

        assert all(response.status_code == 200 for response in responses)
        assert responses[-1].headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        data_dir = Path(server.runtime.config["data_dir"])
        manifest_path = data_dir / saved["manifest_path"]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        exports = manifest["exports"]
        assert len(exports) == 5
        assert all(item["format"] == "word" for item in exports)
        export_paths = [data_dir / item["path"] for item in exports]
        assert all(path.exists() for path in export_paths)

        all_docx = list((data_dir / saved["asset_path"] / "exports").glob("*.docx"))
        assert len(all_docx) == 5
    finally:
        restore_runtime(original)


def test_asset_ppt_export_uses_saved_asset_and_agent05_fallback(monkeypatch, tmp_path):
    original = install_asset_runtime(tmp_path)
    try:
        def fake_quality_export(question, answer, sources, output_path, config):
            raise RuntimeError("agent05 unavailable")

        monkeypatch.setattr(server, "export_to_quality_ppt", fake_quality_export)
        client = TestClient(app)
        saved = client.post("/api/assets/answers", json=sample_payload()).json()

        response = client.post(f"/api/assets/answers/{saved['asset_id']}/export/ppt")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        )
        manifest = json.loads((Path(server.runtime.config["data_dir"]) / saved["manifest_path"]).read_text(encoding="utf-8"))
        assert manifest["exports"][0]["format"] == "ppt"
        assert manifest["rag_status"] == "not_indexed"
    finally:
        restore_runtime(original)
