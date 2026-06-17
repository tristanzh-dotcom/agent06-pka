from copy import deepcopy
from pathlib import Path

from fastapi.testclient import TestClient

import server
from engine.indexer import HybridIndexer
from engine.models import ParseQuality, ParseResult
from server import app


class FakeEmbeddingClient:
    def embed(self, texts):
        return [[1.0] + [0.0] * 1023 for _ in texts]


def install_temp_runtime(tmp_path, collection_name):
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


def restore_runtime(original):
    server.runtime.config, server.runtime.indexer, server.runtime.last_updated = original


def needs_ocr_quality():
    return ParseQuality(
        status="needs_ocr",
        action="needs_ocr_skipped",
        valid_ratio=0.0,
        short_line_ratio=1.0,
        watermark_ratio=0.0,
        unique_line_ratio=0.0,
        non_empty_pages=0,
        page_count=10,
        non_empty_page_ratio=0.0,
        effective_chars_per_page=0.0,
        cleaned_chars_ratio=0.0,
        reasons=["文本层为空，需要 OCR"],
    )


def ocr_quality():
    return ParseQuality(
        status="high",
        action="ocr",
        valid_ratio=1.0,
        short_line_ratio=0.0,
        watermark_ratio=0.0,
        unique_line_ratio=1.0,
        non_empty_pages=10,
        page_count=10,
        non_empty_page_ratio=1.0,
        effective_chars_per_page=120.0,
        cleaned_chars_ratio=1.0,
        reasons=[],
    )


def test_ingest_file_returns_202_and_queued_status_for_scan_pdf(monkeypatch, tmp_path):
    original = install_temp_runtime(tmp_path, "test_async_ocr_accepts_scan")

    async def fake_parse_file(file_path, mime_type=None, ocr_client=None):
        return ParseResult(
            text="",
            source_name=Path(file_path).name,
            source_type="pdf",
            metadata={"page_count": 10, "non_empty_pages": 0},
            quality=needs_ocr_quality(),
        )

    monkeypatch.setattr(server, "parse_file", fake_parse_file)
    monkeypatch.setattr(server, "_build_ocr_client", lambda: None)
    client = TestClient(app)

    try:
        response = client.post(
            "/api/ingest/file",
            files={"file": ("GEO_Scan_Report.pdf", b"%PDF scan", "application/pdf")},
        )

        assert response.status_code == 202
        payload = response.json()
        assert payload["status"] in {"accepted", "queued"}
        assert payload["task_id"].startswith("ocr_task_")
        assert payload["file_name"] == "GEO_Scan_Report.pdf"
        assert server.runtime.indexer.count_chunks() == 0
    finally:
        restore_runtime(original)


def test_task_store_persistence_and_polling_endpoint(monkeypatch, tmp_path):
    original = install_temp_runtime(tmp_path, "test_async_ocr_task_polling")

    async def fake_parse_file(file_path, mime_type=None, ocr_client=None):
        return ParseResult(
            text="",
            source_name=Path(file_path).name,
            source_type="pdf",
            metadata={"page_count": 10, "non_empty_pages": 0},
            quality=needs_ocr_quality(),
        )

    monkeypatch.setattr(server, "parse_file", fake_parse_file)
    monkeypatch.setattr(server, "_build_ocr_client", lambda: None)
    client = TestClient(app)

    try:
        response = client.post(
            "/api/ingest/file",
            files={"file": ("GEO_Scan_Report.pdf", b"%PDF scan", "application/pdf")},
        )
        task_id = response.json()["task_id"]
        task_path = Path(server.runtime.config["data_dir"]) / "runtime" / "tasks" / f"{task_id}.json"

        assert task_path.exists()
        task_response = client.get(f"/api/tasks/{task_id}")
        assert task_response.status_code == 200
        task = task_response.json()
        assert task["task_id"] == task_id
        assert task["status"] == "queued"
        assert task["progress"] == 0
        assert task["result"]["chunks_inserted"] == 0
        assert task["result"]["quality_action"] is None
        assert task["result"]["error"] is None
    finally:
        restore_runtime(original)


def test_ingest_files_returns_202_when_any_file_is_queued(monkeypatch, tmp_path):
    original = install_temp_runtime(tmp_path, "test_async_ocr_batch_accepts_scan")

    async def fake_parse_file(file_path, mime_type=None, ocr_client=None):
        return ParseResult(
            text="",
            source_name=Path(file_path).name,
            source_type="pdf",
            metadata={"page_count": 10, "non_empty_pages": 0},
            quality=needs_ocr_quality(),
        )

    monkeypatch.setattr(server, "parse_file", fake_parse_file)
    monkeypatch.setattr(server, "_build_ocr_client", lambda: None)
    client = TestClient(app)

    try:
        response = client.post(
            "/api/ingest/files",
            files=[("files", ("GEO_Scan_Report.pdf", b"%PDF scan", "application/pdf"))],
        )

        assert response.status_code == 202
        payload = response.json()
        assert payload["status"] == "accepted"
        assert payload["accepted"] == 1
        assert payload["files"][0]["task_id"].startswith("ocr_task_")
        assert server.runtime.indexer.count_chunks() == 0
    finally:
        restore_runtime(original)


def test_async_ocr_worker_flows_back_to_unified_ingest_and_respects_limits(monkeypatch, tmp_path):
    original = install_temp_runtime(tmp_path, "test_async_ocr_failure_atomicity")

    async def fake_parse_file(file_path, mime_type=None, ocr_client=None):
        return ParseResult(
            text="",
            source_name=Path(file_path).name,
            source_type="pdf",
            metadata={"page_count": 10, "non_empty_pages": 0},
            quality=needs_ocr_quality(),
        )

    class TooLargeOCRChain:
        async def extract_pdf_until_usable(self, pdf_path, *, page_count, max_pages):
            return type(
                "OCRResult",
                (),
                {
                    "text": "\n\n".join(f"OCR paragraph {index} " + "x" * 220 for index in range(151)),
                    "quality": ocr_quality(),
                    "provider": "paddle",
                    "attempts": [],
                    "source_page_count": 10,
                    "pages_processed": 10,
                    "page_limit_reached": False,
                    "partial": False,
                },
            )()

    monkeypatch.setattr(server, "parse_file", fake_parse_file)
    monkeypatch.setattr(server, "_build_ocr_client", lambda: None)
    client = TestClient(app)

    try:
        response = client.post(
            "/api/ingest/file",
            files={"file": ("GEO_Scan_Report.pdf", b"%PDF scan", "application/pdf")},
        )
        task_id = response.json()["task_id"]

        server.run_ocr_task_once(task_id, TooLargeOCRChain())

        task = client.get(f"/api/tasks/{task_id}").json()
        assert task["status"] == "failed"
        assert task["result"]["chunks_inserted"] == 0
        assert "超过单次同步入库上限" in task["result"]["error"]
        assert server.runtime.indexer.count_chunks() == 0
    finally:
        restore_runtime(original)


def test_recover_queued_tasks_requeues_existing_raw_file_and_fails_missing_raw_file(tmp_path):
    original = install_temp_runtime(tmp_path, "test_async_ocr_recovery")
    store = server.OcrTaskStore(server.runtime.config["data_dir"])
    data_dir = Path(server.runtime.config["data_dir"])
    raw_dir = data_dir / "raw" / "2026-06-17"
    raw_dir.mkdir(parents=True)
    (raw_dir / "scan.pdf").write_bytes(b"%PDF scan")
    existing_task = {
        "task_id": "ocr_task_existing",
        "status": "processing",
        "file_name": "scan.pdf",
        "raw_file_path": "raw/2026-06-17/scan.pdf",
        "content_type": "application/pdf",
        "page_count": 10,
        "progress": 40,
        "result": {"chunks_inserted": 0, "quality_action": None, "error": None},
    }
    missing_task = {
        "task_id": "ocr_task_missing",
        "status": "queued",
        "file_name": "missing.pdf",
        "raw_file_path": "raw/2026-06-17/missing.pdf",
        "content_type": "application/pdf",
        "page_count": 10,
        "progress": 0,
        "result": {"chunks_inserted": 0, "quality_action": None, "error": None},
    }
    store.save_task(existing_task["task_id"], existing_task)
    store.save_task(missing_task["task_id"], missing_task)

    class RecordingExecutor:
        def __init__(self):
            self.submissions = []

        def submit(self, fn, *args):
            self.submissions.append((fn, args))

    executor = RecordingExecutor()

    try:
        summary = server.recover_queued_ocr_tasks(executor=executor)

        assert summary == {"requeued": 1, "failed": 1}
        assert executor.submissions[0][0] is server.run_ocr_task_once
        assert executor.submissions[0][1] == ("ocr_task_existing",)
        assert store.get_task("ocr_task_existing")["status"] == "queued"
        failed = store.get_task("ocr_task_missing")
        assert failed["status"] == "failed"
        assert "raw file is missing" in failed["result"]["error"]
    finally:
        restore_runtime(original)
