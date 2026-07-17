from engine.ingest_registry import ContentRegistry, sha256_text


def test_registry_distinguishes_new_indexed_processing_and_failed_content(tmp_path):
    registry = ContentRegistry(tmp_path / "ingest_registry.sqlite")
    content_hash = sha256_text("同一份知识")

    first = registry.reserve(
        content_hash=content_hash,
        source_name="note.txt",
        raw_file_path="raw/note.txt",
        content_kind="file",
    )
    assert first.status == "reserved"

    pending = registry.reserve(
        content_hash=content_hash,
        source_name="note-copy.txt",
        raw_file_path="raw/note-copy.txt",
        content_kind="file",
    )
    assert pending.status == "duplicate_pending"

    registry.mark_indexed(content_hash, chunk_count=2)
    duplicate = registry.reserve(
        content_hash=content_hash,
        source_name="renamed.txt",
        raw_file_path="raw/renamed.txt",
        content_kind="file",
    )
    assert duplicate.status == "duplicate"
    assert duplicate.source_name == "note.txt"
    assert duplicate.chunk_count == 2

    failed_hash = sha256_text("失败后允许重试")
    registry.reserve(
        content_hash=failed_hash,
        source_name="retry.txt",
        raw_file_path="raw/retry.txt",
        content_kind="file",
    )
    registry.mark_failed(failed_hash, "解析失败")
    retry = registry.reserve(
        content_hash=failed_hash,
        source_name="retry.txt",
        raw_file_path="raw/retry.txt",
        content_kind="file",
    )
    assert retry.status == "reserved"


def test_sha256_text_normalizes_line_endings_and_outer_whitespace():
    assert sha256_text("\n同一段文本\r\n") == sha256_text("同一段文本\n")


def test_registry_clear_allows_reingest_after_knowledge_base_is_cleared(tmp_path):
    registry = ContentRegistry(tmp_path / "ingest_registry.sqlite")
    content_hash = sha256_text("清库后允许重新录入")
    registry.reserve(
        content_hash=content_hash,
        source_name="note.txt",
        raw_file_path="raw/note.txt",
        content_kind="file",
    )
    registry.mark_indexed(content_hash, chunk_count=1)

    registry.clear()

    assert registry.reserve(
        content_hash=content_hash,
        source_name="note.txt",
        raw_file_path="raw/note.txt",
        content_kind="file",
    ).status == "reserved"
