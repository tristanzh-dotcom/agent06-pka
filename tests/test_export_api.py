from fastapi.testclient import TestClient

import server
from server import app


def test_word_export_api_returns_docx_attachment():
    client = TestClient(app)

    response = client.post(
        "/api/export/word",
        json={
            "question": "组织架构怎么调整？",
            "answer": "建议先明确职责边界。",
            "sources": [{"source_name": "org.txt", "chunk_index": 0, "relevance": 0.8}],
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert "attachment;" in response.headers["content-disposition"]
    assert response.content.startswith(b"PK")


def test_ppt_export_api_returns_pptx_attachment(monkeypatch):
    def fake_quality_export(question, answer, sources, output_path, config):
        raise RuntimeError("agent05 unavailable in unit test")

    monkeypatch.setattr(server, "export_to_quality_ppt", fake_quality_export)
    client = TestClient(app)

    response = client.post(
        "/api/export/ppt",
        json={
            "question": "组织架构怎么调整？",
            "answer": "建议先明确职责边界。",
            "sources": [{"source_name": "org.txt", "chunk_index": 0, "relevance": 0.8}],
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )
    assert "attachment;" in response.headers["content-disposition"]
    assert response.headers["content-disposition"].endswith('filename="pka_answer.pptx"') or ".pptx" in response.headers[
        "content-disposition"
    ]
    assert response.content.startswith(b"PK")


def test_ppt_export_api_prefers_agent05_quality_ppt(monkeypatch, tmp_path):
    quality_path = tmp_path / "agent05_quality.pptx"
    quality_path.write_bytes(b"PK-agent05-quality-pptx")

    def fake_quality_export(question, answer, sources, output_path, config):
        assert question == "组织架构怎么调整？"
        assert answer == "建议先明确职责边界。"
        assert sources == [{"source_name": "org.txt", "chunk_index": 0, "relevance": 0.8}]
        assert output_path.endswith(".pptx")
        assert config is server.runtime.config
        return str(quality_path)

    monkeypatch.setattr(server, "export_to_quality_ppt", fake_quality_export)
    client = TestClient(app)

    response = client.post(
        "/api/export/ppt",
        json={
            "question": "组织架构怎么调整？",
            "answer": "建议先明确职责边界。",
            "sources": [{"source_name": "org.txt", "chunk_index": 0, "relevance": 0.8}],
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )
    assert response.content == b"PK-agent05-quality-pptx"


def test_ppt_export_api_falls_back_to_local_ppt_when_agent05_fails(monkeypatch):
    def fake_quality_export(question, answer, sources, output_path, config):
        raise RuntimeError("agent05 unavailable")

    monkeypatch.setattr(server, "export_to_quality_ppt", fake_quality_export)
    client = TestClient(app)

    response = client.post(
        "/api/export/ppt",
        json={
            "question": "组织架构怎么调整？",
            "answer": "建议先明确职责边界。",
            "sources": [{"source_name": "org.txt", "chunk_index": 0, "relevance": 0.8}],
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )
    assert response.content.startswith(b"PK")
    assert response.content != b"PK-agent05-quality-pptx"
