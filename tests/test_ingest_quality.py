from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import UploadFile

import server
from engine.models import ParseQuality, ParseResult
from engine.ocr import OCRAttempt, OCRChainResult


class RecordingIndexer:
    def __init__(self):
        self.upsert_calls = []

    def upsert(self, chunks, raw_file_paths=None):
        self.upsert_calls.append((chunks, raw_file_paths))
        return len(chunks)

    def count_chunks(self):
        return sum(len(chunks) for chunks, _ in self.upsert_calls)


def _pre_chunk(text=None):
    return SimpleNamespace(
        text=text or "[ORG_CHART]\nStructure:\n- Field 1: Nico Reimel\n[/ORG_CHART]",
        source_name="jlr_org.pdf",
        source_type="org_chart",
        is_pre_chunked=True,
        metadata={
            "page": 7,
            "chart_id": "jlr_org.pdf#page_7#chart_1",
            "confidence": "medium",
            "org_chart_mode": "pdf_layout_fallback",
        },
    )


def _needs_ocr_quality(action="needs_ocr_skipped"):
    return ParseQuality(
        status="needs_ocr",
        action=action,
        valid_ratio=0.0,
        short_line_ratio=1.0,
        watermark_ratio=0.0,
        unique_line_ratio=0.0,
        non_empty_pages=0,
        page_count=10,
        non_empty_page_ratio=0.0,
        effective_chars_per_page=0.0,
        cleaned_chars_ratio=0.0,
        reasons=["文本层为空或有效正文不足，OCR 未配置，未写入知识库"],
    )


def _high_quality(action="direct"):
    return ParseQuality(
        status="high",
        action=action,
        valid_ratio=1.0,
        short_line_ratio=0.0,
        watermark_ratio=0.0,
        unique_line_ratio=1.0,
        non_empty_pages=3,
        page_count=3,
        non_empty_page_ratio=1.0,
        effective_chars_per_page=180.0,
        cleaned_chars_ratio=1.0,
        reasons=[],
    )


def _low_quality():
    return ParseQuality(
        status="low",
        action="low_indexed",
        valid_ratio=0.8,
        short_line_ratio=0.7,
        watermark_ratio=0.2,
        unique_line_ratio=0.6,
        non_empty_pages=3,
        page_count=3,
        non_empty_page_ratio=1.0,
        effective_chars_per_page=120.0,
        cleaned_chars_ratio=0.8,
        reasons=["极短行占比 70.0%，超过 60%"],
    )


def _assert_needs_ocr_queued_result(result, indexer):
    assert result["status"] == "accepted"
    assert result["task_id"].startswith("ocr_task_")
    assert result["chunks"] == 0
    assert result["chunk_ids"] == []
    assert result["quality"]["action"] == "needs_ocr_queued"
    assert indexer.count_chunks() == 0


@pytest.mark.asyncio
async def test_unified_ingest_parsed_result_indexes_normal_and_pre_chunks(monkeypatch, tmp_path):
    indexer = RecordingIndexer()
    monkeypatch.setitem(server.runtime.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(server.runtime, "indexer", indexer)
    pre_chunk = _pre_chunk()
    parsed = ParseResult(
        text="This normal paragraph is long enough to be chunked as a regular PDF record.",
        source_name="mixed.pdf",
        source_type="pdf",
        metadata={"page_count": 2},
        quality=_high_quality(),
        pre_chunks=[pre_chunk],
    )

    result = await server._ingest_parsed_result(
        parsed,
        content_type="application/pdf",
        raw_file_path="raw/2026-06-16/mixed.pdf",
    )

    assert result["status"] == "ok"
    assert result["chunks"] == 2
    assert result["source_type"] == "pdf"
    assert result["raw_file_path"] == "raw/2026-06-16/mixed.pdf"
    assert result["quality"]["action"] == "direct"
    chunks, raw_paths = indexer.upsert_calls[0]
    assert [chunk.source_type for chunk in chunks] == ["pdf", "org_chart"]
    assert chunks[1].text == pre_chunk.text
    assert raw_paths == ["raw/2026-06-16/mixed.pdf", "raw/2026-06-16/mixed.pdf"]


async def test_ingest_persists_source_identity_quality_and_coverage_in_chunks(monkeypatch, tmp_path):
    indexer = RecordingIndexer()
    monkeypatch.setattr(server.runtime, "indexer", indexer)
    monkeypatch.setitem(server.runtime.config, "data_dir", str(tmp_path))
    quality = _high_quality()
    coverage = {
        "format": "docx",
        "status": "complete",
        "warnings": [],
        "counts": {"paragraphs": 1, "tables": 1, "table_rows": 2},
    }
    parsed = ParseResult(
        text="项目负责人负责交付。",
        source_name="report.docx",
        source_type="docx",
        metadata={"coverage": coverage},
        quality=quality,
    )

    result = await server._ingest_parsed_result(
        parsed,
        raw_file_path="raw/2026-07-15/report.docx",
        content_hash="c" * 64,
        source_id="source-fixed",
        original_name="report.docx",
    )

    chunks, _ = indexer.upsert_calls[0]
    assert result["source_id"] == "source-fixed"
    assert chunks[0].id == "source-fixed#0"
    assert chunks[0].metadata["source_id"] == "source-fixed"
    assert chunks[0].metadata["original_name"] == "report.docx"
    assert chunks[0].metadata["quality"]["status"] == "high"
    assert chunks[0].metadata["coverage"] == coverage
    stored = server._source_registry().get("source-fixed")
    assert stored.source_name == "report.docx"
    assert stored.chunk_count == 1


@pytest.mark.asyncio
async def test_unified_ingest_parsed_result_rejects_empty_parsed_content(monkeypatch, tmp_path):
    indexer = RecordingIndexer()
    monkeypatch.setitem(server.runtime.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(server.runtime, "indexer", indexer)
    parsed = ParseResult(
        text="",
        source_name="empty.txt",
        source_type="text",
        metadata={"input": "manual"},
        quality=_high_quality(),
    )

    with pytest.raises(ValueError, match="no indexable content"):
        await server._ingest_parsed_result(parsed, content_type="text/plain", raw_file_path="")

    assert indexer.upsert_calls == []


@pytest.mark.asyncio
async def test_needs_ocr_without_ocr_is_skipped_and_not_indexed(monkeypatch, tmp_path):
    indexer = RecordingIndexer()
    monkeypatch.setitem(server.runtime.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(server.runtime, "indexer", indexer)

    async def fake_parse_file(file_path, mime_type=None, ocr_client=None, extract_org_charts=False):
        return ParseResult(
            text="",
            source_name=Path(file_path).name,
            source_type="pdf",
            metadata={"page_count": 10, "non_empty_pages": 0},
            quality=_needs_ocr_quality(),
        )

    monkeypatch.setattr(server, "parse_file", fake_parse_file)
    upload = UploadFile(filename="scan.pdf", file=BytesIO(b"%PDF empty scan"), headers=None)

    result = await server._ingest_upload_file(upload, ocr=None)

    _assert_needs_ocr_queued_result(result, indexer)


@pytest.mark.asyncio
async def test_needs_ocr_sync_ingest_skips_without_running_ocr_chain(monkeypatch, tmp_path):
    indexer = RecordingIndexer()
    monkeypatch.setitem(server.runtime.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(server.runtime, "indexer", indexer)

    async def fake_parse_file(file_path, mime_type=None, ocr_client=None, extract_org_charts=False):
        return ParseResult(
            text="",
            source_name=Path(file_path).name,
            source_type="pdf",
            metadata={"page_count": 41, "non_empty_pages": 0},
            quality=_needs_ocr_quality(),
        )

    class FakeOCRChain:
        calls = 0

        async def extract_pdf_until_usable(self, pdf_path, *, page_count, max_pages):
            self.calls += 1
            return OCRChainResult(
                text="\n".join(["OCR text should not be indexed."] * 12),
                quality=_high_quality(),
                provider="paddle",
                attempts=[OCRAttempt(provider="paddle", status="accepted", quality=_high_quality())],
                source_page_count=41,
                pages_processed=10,
                page_limit_reached=True,
                partial=True,
            )

    ocr_chain = FakeOCRChain()
    monkeypatch.setattr(server, "parse_file", fake_parse_file)
    upload = UploadFile(filename="scan.pdf", file=BytesIO(b"%PDF scan"), headers=None)

    result = await server._ingest_upload_file(upload, ocr=ocr_chain)

    assert ocr_chain.calls == 0
    assert indexer.upsert_calls == []
    _assert_needs_ocr_queued_result(result, indexer)


@pytest.mark.asyncio
async def test_ingest_upload_indexes_pre_chunks_without_chunk_text_split(monkeypatch, tmp_path):
    indexer = RecordingIndexer()
    monkeypatch.setitem(server.runtime.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(server.runtime, "indexer", indexer)
    projection = "[ORG_CHART]\n" + "\n".join(f"- Person {idx}" for idx in range(200)) + "\n[/ORG_CHART]"
    pre_chunk = _pre_chunk(projection)

    async def fake_parse_file(file_path, mime_type=None, ocr_client=None, extract_org_charts=False):
        return SimpleNamespace(
            text="",
            source_name=Path(file_path).name,
            source_type="pdf",
            metadata={"page_count": 1, "non_empty_pages": 1},
            quality=None,
            pre_chunks=[pre_chunk],
        )

    monkeypatch.setattr(server, "parse_file", fake_parse_file)
    upload = UploadFile(filename="jlr_org.pdf", file=BytesIO(b"%PDF org chart"), headers=None)

    result = await server._ingest_upload_file(upload, ocr=None)

    assert result["status"] == "ok"
    assert result["chunks"] == 1
    chunks, raw_paths = indexer.upsert_calls[0]
    assert len(chunks) == 1
    assert chunks[0].text == projection
    assert chunks[0].embedding_text == projection
    assert chunks[0].source_type == "org_chart"
    assert raw_paths == [result["raw_file_path"]]


@pytest.mark.asyncio
async def test_mixed_pdf_indexes_normal_chunks_and_org_chart_chunks(monkeypatch, tmp_path):
    indexer = RecordingIndexer()
    monkeypatch.setitem(server.runtime.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(server.runtime, "indexer", indexer)
    pre_chunk = _pre_chunk()

    async def fake_parse_file(file_path, mime_type=None, ocr_client=None, extract_org_charts=False):
        return SimpleNamespace(
            text="This normal PDF paragraph is long enough to survive PDF chunk noise filtering and be indexed.",
            source_name=Path(file_path).name,
            source_type="pdf",
            metadata={"page_count": 2, "non_empty_pages": 2},
            quality=None,
            pre_chunks=[pre_chunk],
        )

    monkeypatch.setattr(server, "parse_file", fake_parse_file)
    upload = UploadFile(filename="mixed.pdf", file=BytesIO(b"%PDF mixed"), headers=None)

    result = await server._ingest_upload_file(upload, ocr=None)

    assert result["status"] == "ok"
    assert result["chunks"] == 2
    chunks, raw_paths = indexer.upsert_calls[0]
    assert [chunk.source_type for chunk in chunks] == ["pdf", "org_chart"]
    assert chunks[1].text == pre_chunk.text
    assert raw_paths == [result["raw_file_path"], result["raw_file_path"]]


@pytest.mark.asyncio
async def test_needs_ocr_with_legacy_pdf_ocr_is_skipped_before_ocr(monkeypatch, tmp_path):
    indexer = RecordingIndexer()
    monkeypatch.setitem(server.runtime.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(server.runtime, "indexer", indexer)

    async def fake_parse_file(file_path, mime_type=None, ocr_client=None, extract_org_charts=False):
        return ParseResult(
            text="",
            source_name=Path(file_path).name,
            source_type="pdf",
            metadata={"page_count": 10, "non_empty_pages": 0},
            quality=_needs_ocr_quality(),
        )

    class FakePDFOCR:
        endpoint = "configured"
        api_key = "secret"
        calls = 0

        async def extract_pdf(self, pdf_path, max_pages=50):
            self.calls += 1
            return "\n".join(
                ["OCR 转写正文，包含 2026 年市场规模和 23.7% 渗透率，供应链能力持续提升。"] * 20
            )

    ocr = FakePDFOCR()
    monkeypatch.setattr(server, "parse_file", fake_parse_file)
    upload = UploadFile(filename="scan.pdf", file=BytesIO(b"%PDF empty scan"), headers=None)

    result = await server._ingest_upload_file(upload, ocr=ocr)

    assert ocr.calls == 0
    _assert_needs_ocr_queued_result(result, indexer)


@pytest.mark.asyncio
async def test_needs_ocr_provider_chain_is_not_called_in_sync_ingest(monkeypatch, tmp_path):
    indexer = RecordingIndexer()
    monkeypatch.setitem(server.runtime.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(server.runtime, "indexer", indexer)

    async def fake_parse_file(file_path, mime_type=None, ocr_client=None, extract_org_charts=False):
        return ParseResult(
            text="",
            source_name=Path(file_path).name,
            source_type="pdf",
            metadata={"page_count": 3, "non_empty_pages": 0},
            quality=_needs_ocr_quality(),
        )

    class FakeOCRChain:
        calls = 0

        async def extract_pdf_until_usable(self, pdf_path, *, page_count, max_pages):
            self.calls += 1
            return OCRChainResult(
                text="\n".join(["OCR 转写正文包含 2026 年市场规模和 23.7% 渗透率。"] * 12),
                quality=_high_quality(),
                provider="paddle",
                attempts=[OCRAttempt(provider="paddle", status="accepted", quality=_high_quality())],
                source_page_count=40,
                pages_processed=10,
                page_limit_reached=True,
                partial=True,
            )

    ocr_chain = FakeOCRChain()
    monkeypatch.setattr(server, "parse_file", fake_parse_file)
    upload = UploadFile(filename="scan.pdf", file=BytesIO(b"%PDF empty scan"), headers=None)

    result = await server._ingest_upload_file(upload, ocr=ocr_chain)

    assert ocr_chain.calls == 0
    assert result["quality"].get("provider", "") == ""
    assert result["quality"].get("attempts", []) == []
    _assert_needs_ocr_queued_result(result, indexer)


@pytest.mark.asyncio
async def test_needs_ocr_skips_before_provider_chain_timeout_path(monkeypatch, tmp_path):
    indexer = RecordingIndexer()
    monkeypatch.setitem(server.runtime.config, "data_dir", str(tmp_path))
    monkeypatch.setitem(server.runtime.config["ocr"], "timeout_seconds", 0.01)
    monkeypatch.setattr(server.runtime, "indexer", indexer)

    async def fake_parse_file(file_path, mime_type=None, ocr_client=None, extract_org_charts=False):
        return ParseResult(
            text="",
            source_name=Path(file_path).name,
            source_type="pdf",
            metadata={"page_count": 40, "non_empty_pages": 0},
            quality=_needs_ocr_quality(),
        )

    class SlowOCRChain:
        calls = 0

        async def extract_pdf_until_usable(self, pdf_path, *, page_count, max_pages):
            self.calls += 1
            return OCRChainResult(
                text="too late",
                quality=_high_quality(),
                provider="paddle",
                attempts=[],
            )

    ocr_chain = SlowOCRChain()
    monkeypatch.setattr(server, "parse_file", fake_parse_file)
    upload = UploadFile(filename="scan.pdf", file=BytesIO(b"%PDF empty scan"), headers=None)

    result = await server._ingest_upload_file(upload, ocr=ocr_chain)

    assert ocr_chain.calls == 0
    _assert_needs_ocr_queued_result(result, indexer)


@pytest.mark.asyncio
async def test_needs_ocr_skips_before_provider_chain_failure_path(monkeypatch, tmp_path):
    indexer = RecordingIndexer()
    monkeypatch.setitem(server.runtime.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(server.runtime, "indexer", indexer)

    async def fake_parse_file(file_path, mime_type=None, ocr_client=None, extract_org_charts=False):
        return ParseResult(
            text="",
            source_name=Path(file_path).name,
            source_type="pdf",
            metadata={"page_count": 3, "non_empty_pages": 0},
            quality=_needs_ocr_quality(),
        )

    class FakeOCRChain:
        calls = 0

        async def extract_pdf_until_usable(self, pdf_path, *, page_count, max_pages):
            self.calls += 1
            return None

    ocr_chain = FakeOCRChain()
    monkeypatch.setattr(server, "parse_file", fake_parse_file)
    upload = UploadFile(filename="scan.pdf", file=BytesIO(b"%PDF empty scan"), headers=None)

    result = await server._ingest_upload_file(upload, ocr=ocr_chain)

    assert ocr_chain.calls == 0
    _assert_needs_ocr_queued_result(result, indexer)


@pytest.mark.asyncio
async def test_low_quality_pdf_requires_review_without_indexing(monkeypatch, tmp_path):
    indexer = RecordingIndexer()
    monkeypatch.setitem(server.runtime.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(server.runtime, "indexer", indexer)

    async def fake_parse_file(file_path, mime_type=None, ocr_client=None, extract_org_charts=False):
        return ParseResult(
            text="\n".join(["低质量但仍有正文，包含企业战略、市场份额和供应链变化。"] * 10),
            source_name=Path(file_path).name,
            source_type="pdf",
            metadata={"page_count": 3, "non_empty_pages": 3},
            quality=_low_quality(),
        )

    class FailingIfCalledOCRChain:
        async def extract_pdf_until_usable(self, pdf_path, *, page_count, max_pages):
            raise AssertionError("low quality PDFs must not trigger OCR")

    monkeypatch.setattr(server, "parse_file", fake_parse_file)
    upload = UploadFile(filename="low.pdf", file=BytesIO(b"%PDF low quality"), headers=None)

    result = await server._ingest_upload_file(upload, ocr=FailingIfCalledOCRChain())

    assert result["status"] == "review_required"
    assert result["quality"]["action"] == "low_indexed"
    assert result["chunks"] == 0
    assert indexer.count_chunks() == 0

    repeated = await server._ingest_upload_file(
        UploadFile(filename="low.pdf", file=BytesIO(b"%PDF low quality"), headers=None),
        ocr=None,
    )
    assert repeated["status"] == "review_required"
    assert "确认" in repeated["message"]


@pytest.mark.asyncio
async def test_explicit_quality_acceptance_indexes_low_quality_content(monkeypatch, tmp_path):
    indexer = RecordingIndexer()
    monkeypatch.setitem(server.runtime.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(server.runtime, "indexer", indexer)

    async def fake_parse_file(file_path, mime_type=None, ocr_client=None, extract_org_charts=False):
        return ParseResult(
            text="\n".join(["用户确认仍然入库的低质量正文内容。"] * 10),
            source_name=Path(file_path).name,
            source_type="pdf",
            metadata={"coverage": {"format": "pdf", "status": "complete", "warnings": [], "counts": {"pages": 3}}},
            quality=_low_quality(),
        )

    monkeypatch.setattr(server, "parse_file", fake_parse_file)
    first = UploadFile(filename="low.pdf", file=BytesIO(b"%PDF reviewed low"), headers=None)
    reviewed = await server._ingest_upload_file(first, ocr=None)
    second = UploadFile(filename="low.pdf", file=BytesIO(b"%PDF reviewed low"), headers=None)

    accepted = await server._ingest_upload_file(second, ocr=None, quality_policy="accept")

    assert reviewed["status"] == "review_required"
    assert accepted["status"] == "ok"
    assert accepted["chunks"] > 0
    chunks, _ = indexer.upsert_calls[0]
    assert chunks[0].metadata["quality"]["status"] == "low"


@pytest.mark.asyncio
async def test_partial_structured_coverage_requires_review(monkeypatch, tmp_path):
    indexer = RecordingIndexer()
    monkeypatch.setitem(server.runtime.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(server.runtime, "indexer", indexer)

    async def fake_parse_file(file_path, mime_type=None, ocr_client=None, extract_org_charts=False):
        return ParseResult(
            text="正文存在，但有结构未能提取。",
            source_name=Path(file_path).name,
            source_type="docx",
            metadata={"coverage": {"format": "docx", "status": "partial", "warnings": ["unsupported_chart"], "counts": {}}},
        )

    monkeypatch.setattr(server, "parse_file", fake_parse_file)
    upload = UploadFile(filename="partial.docx", file=BytesIO(b"partial docx"), headers=None)

    result = await server._ingest_upload_file(upload, ocr=None)

    assert result["status"] == "review_required"
    assert result["chunks"] == 0
    assert result["coverage"]["status"] == "partial"
    assert indexer.count_chunks() == 0


@pytest.mark.asyncio
async def test_needs_ocr_skips_before_legacy_pdf_ocr_failure_path(monkeypatch, tmp_path):
    indexer = RecordingIndexer()
    monkeypatch.setitem(server.runtime.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(server.runtime, "indexer", indexer)

    async def fake_parse_file(file_path, mime_type=None, ocr_client=None, extract_org_charts=False):
        return ParseResult(
            text="",
            source_name=Path(file_path).name,
            source_type="pdf",
            metadata={"page_count": 10, "non_empty_pages": 0},
            quality=_needs_ocr_quality(),
        )

    class FailingPDFOCR:
        endpoint = "configured"
        api_key = "secret"
        calls = 0

        async def extract_pdf(self, pdf_path, max_pages=50):
            self.calls += 1
            raise RuntimeError("OCR failed")

    ocr = FailingPDFOCR()
    monkeypatch.setattr(server, "parse_file", fake_parse_file)
    upload = UploadFile(filename="scan.pdf", file=BytesIO(b"%PDF empty scan"), headers=None)

    result = await server._ingest_upload_file(upload, ocr=ocr)

    assert ocr.calls == 0
    _assert_needs_ocr_queued_result(result, indexer)


@pytest.mark.asyncio
async def test_batch_counts_skipped_separately_from_failed(monkeypatch):
    async def fake_ingest_upload_file(file, ocr, extract_org_charts=False):
        if file.filename == "ok.txt":
            return {
                "status": "ok",
                "chunks": 2,
                "source_name": "ok.txt",
                "content_type": "text/plain",
                "raw_file_path": "raw/ok.txt",
                "chunk_ids": ["ok.txt#0", "ok.txt#1"],
                "quality": None,
            }
        if file.filename == "scan.pdf":
            return {
                "status": "skipped",
                "chunks": 0,
                "source_name": "scan.pdf",
                "content_type": "application/pdf",
                "raw_file_path": "raw/scan.pdf",
                "chunk_ids": [],
                "quality": {"status": "needs_ocr", "action": "needs_ocr_skipped"},
            }
        raise ValueError("broken file")

    monkeypatch.setattr(server, "_ingest_upload_file", fake_ingest_upload_file)
    monkeypatch.setattr(server, "_build_ocr_client", lambda: None)
    uploads = [
        UploadFile(filename="ok.txt", file=BytesIO(b"ok"), headers=None),
        UploadFile(filename="scan.pdf", file=BytesIO(b"scan"), headers=None),
        UploadFile(filename="broken.docx", file=BytesIO(b"broken"), headers=None),
    ]

    response = await server.ingest_files(uploads)

    assert response["succeeded"] == 1
    assert response["skipped"] == 1
    assert response["failed"] == 1
    assert response["total_chunks"] == 2


@pytest.mark.asyncio
async def test_batch_image_with_empty_ocr_text_fails_without_indexing(monkeypatch, tmp_path):
    indexer = RecordingIndexer()
    monkeypatch.setitem(server.runtime.config, "data_dir", str(tmp_path))
    monkeypatch.setattr(server.runtime, "indexer", indexer)

    class EmptyImageOCR:
        async def extract(self, image_paths):
            return "   \n"

    monkeypatch.setattr(server, "_build_ocr_client", lambda: EmptyImageOCR())
    upload = UploadFile(filename="screen.jpeg", file=BytesIO(b"not a real jpeg"), headers=None)

    response = await server.ingest_files([upload])

    assert response["status"] == "partial"
    assert response["succeeded"] == 0
    assert response["failed"] == 1
    assert response["total_chunks"] == 0
    assert response["files"][0]["status"] == "error"
    assert response["files"][0]["error"] == "OCR produced no usable text for image"
    assert indexer.count_chunks() == 0
