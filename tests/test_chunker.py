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


def test_pdf_chunks_filter_short_titles_and_dotted_toc_lines_only_for_pdf():
    text = "第一章 概述\n\n............................ 23\n\n这是一个足够长的 PDF 正文段落，用于验证目录和短标题不会进入知识库检索索引。"

    pdf_chunks = chunk_text(text, "report.pdf", "pdf", max_chunk_size=200, chunk_overlap=20)
    txt_chunks = chunk_text(text, "note.txt", "txt", max_chunk_size=200, chunk_overlap=20)

    assert [chunk.text for chunk in pdf_chunks] == [
        "这是一个足够长的 PDF 正文段落，用于验证目录和短标题不会进入知识库检索索引。"
    ]
    assert "第一章 概述" in [chunk.text for chunk in txt_chunks]
    assert "............................ 23" in [chunk.text for chunk in txt_chunks]


def test_pdf_chunks_filter_multiline_mixed_dotted_leader_toc_block():
    toc = "\n".join(
        [
            "3.1.1 法规：从“沙盒试点”到“司法互信” ................................... 27",
            "3.1.2 技术：从单车智能到车路云协同 ................................... 30",
            "3.1.3 商业：Robotaxi 单车盈利验证 ................................... 35",
        ]
    )
    text = f"{toc}\n\n这是一个足够长的 PDF 正文段落，用于验证混合目录块不会进入知识库检索索引。"

    chunks = chunk_text(text, "report.pdf", "pdf", max_chunk_size=500, chunk_overlap=20)

    assert [chunk.text for chunk in chunks] == [
        "这是一个足够长的 PDF 正文段落，用于验证混合目录块不会进入知识库检索索引。"
    ]


def test_pdf_chunks_keep_body_when_only_one_line_is_dotted_leader():
    text = "\n".join(
        [
            "这一段正文讨论 L3 自动驾驶准入、DSSAD 数据记录、保险责任划分和司法采信流程。",
            "3.1.1 法规：从“沙盒试点”到“司法互信” ................................... 27",
            "由于只有一行目录样式内容混入正文，整段仍应保留，避免误删可用上下文。",
        ]
    )

    chunks = chunk_text(text, "report.pdf", "pdf", max_chunk_size=500, chunk_overlap=20)

    assert [chunk.text for chunk in chunks] == [text]


def test_mixed_dotted_leader_filter_only_applies_to_pdf():
    text = "\n".join(
        [
            "第一章 行业概述 ······························· 5",
            "第二章 市场规模 ······························· 18",
            "第三章 竞争格局 ······························· 32",
        ]
    )

    txt_chunks = chunk_text(text, "note.txt", "txt", max_chunk_size=500, chunk_overlap=20)
    md_chunks = chunk_text(text, "note.md", "md", max_chunk_size=500, chunk_overlap=20)

    assert [chunk.text for chunk in txt_chunks] == [text]
    assert [chunk.text for chunk in md_chunks] == [text]


def test_pdf_chunks_keep_numeric_market_paragraph_without_dotted_leader():
    text = (
        "2025年至2030年，中国智能座舱市场规模预计从1580亿元增长至2730亿元，"
        "年均复合增长率约11.6%，HUD市场从2020年的17亿元增长至2025年的47亿元。"
    )

    chunks = chunk_text(text, "report.pdf", "pdf", max_chunk_size=500, chunk_overlap=20)

    assert [chunk.text for chunk in chunks] == [text]


def test_long_paragraph_uses_overlapping_windows():
    text = "甲" * 220

    chunks = chunk_text(text, "long.txt", "txt", max_chunk_size=100, chunk_overlap=20)

    assert len(chunks) >= 3
    assert all(len(chunk.text) <= 100 for chunk in chunks)
    assert chunks[0].text[-20:] == chunks[1].text[:20]


def test_empty_text_returns_no_chunks():
    assert chunk_text("", "empty.txt", "txt") == []


def test_breadcrumb_goes_to_embedding_text_not_display_text():
    text = "# 行业分析\n\n## 市场规模\n\n2026 年市场规模达到 1200 亿元。"

    chunks = chunk_text(text, "report.md", "md", max_chunk_size=200, chunk_overlap=20)

    content_chunk = chunks[-1]
    assert "BREADCRUMB" not in content_chunk.text
    assert "行业分析" in content_chunk.embedding_text
    assert "市场规模" in content_chunk.embedding_text


def test_sentence_boundary_windowing_makes_progress_without_punctuation():
    text = "甲" * 2300

    chunks = chunk_text(text, "long.txt", "txt", max_chunk_size=1024, chunk_overlap=128)

    assert chunks
    assert all(len(chunk.text) <= 1024 for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
