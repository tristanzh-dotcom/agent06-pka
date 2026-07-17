from engine.source_registry import SourceRegistry


def test_source_registry_creates_lists_finds_and_deletes_active_source(tmp_path):
    registry = SourceRegistry(tmp_path / "sources.sqlite")
    quality = {"status": "high", "action": "direct"}
    coverage = {"format": "docx", "status": "complete", "warnings": [], "counts": {"tables": 1}}

    created = registry.create_indexed(
        source_id="source-1",
        content_hash="a" * 64,
        content_kind="file",
        original_name="report.docx",
        source_name="report.docx",
        raw_file_path="raw/2026-07-15/report.docx",
        chunk_count=3,
        quality=quality,
        coverage=coverage,
    )

    assert created.source_id == "source-1"
    assert registry.get("source-1").quality == quality
    assert registry.find_active_by_original_name("report.docx").source_id == "source-1"
    assert [item.source_id for item in registry.list_sources()] == ["source-1"]

    registry.delete("source-1")

    assert registry.get("source-1") is None
    assert registry.find_active_by_original_name("report.docx") is None


def test_source_registry_marks_failed_deletion_without_claiming_source_removed(tmp_path):
    registry = SourceRegistry(tmp_path / "sources.sqlite")
    registry.create_indexed(
        source_id="source-2",
        content_hash="b" * 64,
        content_kind="manual_text",
        original_name="手工文本",
        source_name="manual-note",
        raw_file_path="",
        chunk_count=1,
        quality={},
        coverage={},
    )

    registry.mark_delete_failed("source-2", "vector delete failed")

    record = registry.get("source-2")
    assert record.status == "delete_failed"
    assert record.error == "vector delete failed"
