from engine.quality import assess_extracted_text_quality, assess_pdf_quality, clean_pdf_text


def test_empty_text_needs_ocr():
    q = assess_pdf_quality("", "", page_count=10, non_empty_pages=0)

    assert q.status == "needs_ocr"
    assert q.effective_chars_per_page == 0
    assert "OCR" in " ".join(q.reasons)


def test_page_number_only_pdf_needs_ocr():
    raw = "\n".join(f"Page {index}" for index in range(1, 21))
    cleaned = clean_pdf_text(raw)
    q = assess_pdf_quality(raw, cleaned, page_count=20, non_empty_pages=20)

    assert cleaned.strip() == ""
    assert q.status == "needs_ocr"
    assert q.cleaned_chars_ratio == 0


def test_watermark_heavy_pdf_is_low_or_needs_ocr_after_cleaning():
    raw = "\n".join(["©亿欧智库-大王"] * 50 + ["中国新能源汽车品牌 GEO 研究"])
    cleaned = clean_pdf_text(raw)
    q = assess_pdf_quality(raw, cleaned, page_count=20, non_empty_pages=20)

    assert q.status in {"low", "needs_ocr"}
    assert q.watermark_ratio > 0.4
    assert "©亿欧智库-大王" not in cleaned


def test_high_quality_pdf_text_is_high():
    raw = "\n\n".join(
        [
            "智能座舱市场规模持续增长，2026 年预计达到 1200 亿元。",
            "主机厂围绕座舱域控、HUD、语音交互和大模型助手展开竞争。",
            "供应链集中度提升，头部厂商利润率和交付能力成为关键变量。",
        ]
        * 10
    )
    cleaned = clean_pdf_text(raw)
    q = assess_pdf_quality(raw, cleaned, page_count=3, non_empty_pages=3)

    assert q.status == "high"
    assert q.effective_chars_per_page > 80
    assert q.unique_line_ratio > 0.2


def test_clean_pdf_text_removes_lines_repeated_across_pages():
    page_texts = [
        "章节一\n真实正文 A\n扫码访问网站\nwww.example.com",
        "章节二\n真实正文 B\n扫码访问网站\nwww.example.com",
        "章节三\n真实正文 C\n扫码访问网站\nwww.example.com",
        "章节四\n真实正文 D\n扫码访问网站\nwww.example.com",
        "章节五\n真实正文 E",
    ]
    raw = "\n\n".join(page_texts)

    cleaned = clean_pdf_text(raw, page_texts=page_texts, page_count=5)

    assert "扫码访问网站" not in cleaned
    assert "www.example.com" not in cleaned
    assert "真实正文 A" in cleaned
    assert "真实正文 E" in cleaned


def test_clean_pdf_text_keeps_lines_repeated_within_single_page_table():
    page_texts = [
        "表格页\n2026E\n2026E\n100.0%\n100.0%\n真实正文 A",
        "章节二\n真实正文 B",
        "章节三\n真实正文 C",
        "章节四\n真实正文 D",
        "章节五\n真实正文 E",
    ]
    raw = "\n\n".join(page_texts)

    cleaned = clean_pdf_text(raw, page_texts=page_texts, page_count=5)

    assert "2026E" in cleaned
    assert "100.0%" in cleaned


def test_short_valid_extracted_text_is_high_quality():
    quality = assess_extracted_text_quality("会议结论：下周完成供应商评审。")

    assert quality.status == "high"
    assert quality.reasons == []


def test_replacement_character_heavy_extracted_text_requires_review():
    quality = assess_extracted_text_quality("有效标题\n" + "�\x00" * 80)

    assert quality.status == "low"
    assert "异常字符" in " ".join(quality.reasons)


def test_highly_repeated_extracted_text_requires_review():
    quality = assess_extracted_text_quality("\n".join(["重复页眉内容"] * 12))

    assert quality.status == "low"
    assert quality.unique_line_ratio < 0.2
    assert "重复" in " ".join(quality.reasons)
