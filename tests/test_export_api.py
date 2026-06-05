from fastapi.testclient import TestClient

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


def test_ppt_export_api_returns_markdown_fallback_when_agent05_absent():
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
    assert response.headers["content-type"].startswith("text/markdown")
    assert "PPT 导出需要 Agent05" in response.text
