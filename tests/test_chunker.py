from engine.chunker import chunk_text


def test_markdown_with_h2_splits_into_sections_including_heading():
    text = "# 总览\n\n## 第一节\n内容 A\n\n## 第二节\n内容 B\n\n## 第三节\n内容 C"

    chunks = chunk_text(text, "plan.md", "md", max_chunk_size=200, chunk_overlap=20)

    assert [chunk.chunk_index for chunk in chunks] == [0, 1, 2, 3]
    assert chunks[0].text.startswith("# 总览")
    assert chunks[1].text.startswith("## 第一节")
    assert chunks[2].text.startswith("## 第二节")
    assert chunks[3].id == "plan.md#3"


def test_markdown_preserves_h1_preface_before_multiple_h2_sections():
    text = "# 总览\n\n项目背景\n\n## 第一节\n内容 A\n\n## 第二节\n内容 B"

    chunks = chunk_text(text, "mixed.md", "md", max_chunk_size=200, chunk_overlap=20)

    assert chunks[0].text == "# 总览\n\n项目背景"
    assert chunks[1].text.startswith("## 第一节")
    assert chunks[2].text.startswith("## 第二节")


def test_single_hash_text_without_h2_uses_plain_paragraph_split():
    text = "#普通标签\n\n第二段"

    chunks = chunk_text(text, "tag.txt", "txt", max_chunk_size=200, chunk_overlap=20)

    assert [chunk.text for chunk in chunks] == ["#普通标签", "第二段"]


def test_plain_text_splits_by_paragraph():
    text = "第一段\n\n第二段\n\n第三段"

    chunks = chunk_text(text, "note.txt", "txt", max_chunk_size=200, chunk_overlap=20)

    assert [chunk.text for chunk in chunks] == ["第一段", "第二段", "第三段"]
    assert all(chunk.source_name == "note.txt" for chunk in chunks)


def test_long_paragraph_uses_overlapping_windows():
    text = "甲" * 220

    chunks = chunk_text(text, "long.txt", "txt", max_chunk_size=100, chunk_overlap=20)

    assert len(chunks) >= 3
    assert all(len(chunk.text) <= 100 for chunk in chunks)
    assert chunks[0].text[-20:] == chunks[1].text[:20]


def test_empty_text_returns_no_chunks():
    assert chunk_text("", "empty.txt", "txt") == []
