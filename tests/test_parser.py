from pathlib import Path

import pytest

from engine.models import ParseResult
from engine.parser import parse_file, parse_text


def test_parse_text_returns_manual_parse_result():
    parsed = parse_text("今天面试了一个自动驾驶 CTO 岗位。", source_name="manual_note")

    assert parsed == ParseResult(
        text="今天面试了一个自动驾驶 CTO 岗位。",
        source_name="manual_note",
        source_type="text",
        metadata={"input": "manual"},
    )


async def test_parse_txt_and_markdown_files(tmp_path):
    txt = tmp_path / "note.txt"
    md = tmp_path / "plan.md"
    txt.write_text("纯文本内容", encoding="utf-8")
    md.write_text("# 标题\n\n## 小节\nMarkdown 内容", encoding="utf-8")

    parsed_txt = await parse_file(str(txt))
    parsed_md = await parse_file(str(md))

    assert parsed_txt.text == "纯文本内容"
    assert parsed_txt.source_type == "txt"
    assert "Markdown 内容" in parsed_md.text
    assert parsed_md.source_type == "md"


async def test_parse_docx_extracts_all_paragraphs(tmp_path):
    docx = pytest.importorskip("docx")
    path = tmp_path / "report.docx"
    document = docx.Document()
    document.add_paragraph("第一段")
    document.add_paragraph("第二段")
    document.add_paragraph("第三段")
    document.save(path)

    parsed = await parse_file(str(path))

    assert parsed.source_type == "docx"
    assert "第一段\n第二段\n第三段" in parsed.text
    assert parsed.metadata["paragraph_count"] == 3


async def test_parse_pptx_extracts_slide_text(tmp_path):
    pptx = pytest.importorskip("pptx")
    path = tmp_path / "deck.pptx"
    deck = pptx.Presentation()
    for text in ["第一页内容", "第二页内容"]:
        slide = deck.slides.add_slide(deck.slide_layouts[5])
        textbox = slide.shapes.add_textbox(0, 0, 1000000, 1000000)
        textbox.text = text
    deck.save(path)

    parsed = await parse_file(str(path))

    assert parsed.source_type == "pptx"
    assert "第一页内容" in parsed.text
    assert "第二页内容" in parsed.text
    assert parsed.metadata["slide_count"] == 2


async def test_parse_pdf_extracts_all_pages(tmp_path):
    fitz = pytest.importorskip("fitz")
    path = tmp_path / "brief.pdf"
    doc = fitz.open()
    for text in ["第一页 PDF 内容", "第二页 PDF 内容"]:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()

    parsed = await parse_file(str(path))

    assert parsed.source_type == "pdf"
    assert "PDF" in parsed.text
    assert "## Page" not in parsed.text
    assert parsed.metadata["page_count"] == 2
    assert parsed.metadata["non_empty_pages"] == 2
    assert parsed.quality is not None


async def test_parse_pdf_cleaning_reassesses_quality(tmp_path):
    fitz = pytest.importorskip("fitz")
    path = tmp_path / "paged.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Page 1\n智能座舱市场规模持续增长，2026 年预计达到 1200 亿元。")
    doc.save(path)
    doc.close()

    parsed = await parse_file(str(path))

    assert "Page 1" not in parsed.text
    assert parsed.quality is not None
    assert parsed.quality.status in {"high", "low"}
    assert parsed.metadata["quality_status"] == parsed.quality.status


async def test_parse_xlsx_converts_sheets_to_markdown_tables(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "data.xlsx"
    workbook = openpyxl.Workbook()
    first = workbook.active
    first.title = "候选人"
    first.append(["姓名", "评分"])
    first.append(["TZ", 95])
    second = workbook.create_sheet("项目")
    second.append(["项目", "状态"])
    second.append(["PKA", "进行中"])
    workbook.save(path)

    parsed = await parse_file(str(path))

    assert parsed.source_type == "xlsx"
    assert "## Sheet: 候选人" in parsed.text
    assert "| 姓名 | 评分 |" in parsed.text
    assert "| PKA | 进行中 |" in parsed.text
    assert parsed.metadata["sheet_count"] == 2


class FakeOCR:
    async def extract(self, image_paths):
        assert image_paths == [self.expected_path]
        return "图片里的中文"


class FailingOCR:
    async def extract(self, image_paths):
        raise RuntimeError("OCR failed after 3 retries: timeout")


async def test_parse_image_uses_injected_ocr_client_inside_running_event_loop(tmp_path):
    path = tmp_path / "screenshot.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    ocr = FakeOCR()
    ocr.expected_path = str(path)

    parsed = await parse_file(str(path), ocr_client=ocr)

    assert parsed.source_type == "image"
    assert parsed.text == "图片里的中文"
    assert parsed.metadata["ocr"] is True


async def test_parse_image_raises_clear_error_when_ocr_fails(tmp_path):
    path = tmp_path / "broken.png"
    path.write_bytes(b"not a real image")

    with pytest.raises(RuntimeError, match="OCR failed after 3 retries"):
        await parse_file(str(path), ocr_client=FailingOCR())


async def test_parse_corrupt_docx_raises_clear_error(tmp_path):
    path = tmp_path / "broken.docx"
    path.write_text("not a real docx", encoding="utf-8")

    with pytest.raises(ValueError, match="Failed to parse"):
        await parse_file(str(path))
