from pathlib import Path

import pytest

from engine.exporter import export_to_ppt, export_to_word


def sample_sources():
    return [
        {
            "source_name": "组织架构调整方案.pptx",
            "chunk_index": 2,
            "relevance": 0.89,
            "chunk_id": "deck.pptx#2",
        },
        {
            "source_name": "薪酬复盘.docx",
            "chunk_index": 0,
            "relevance": 0.71,
            "chunk_id": "pay.docx#0",
        },
    ]


def test_export_to_word_creates_readable_docx_with_answer_and_source_table(tmp_path):
    docx = pytest.importorskip("docx")
    output_path = tmp_path / "answer.docx"

    returned_path = export_to_word(
        question="组织架构怎么调整？",
        answer="建议先明确职责边界，再调整汇报关系。",
        sources=sample_sources(),
        output_path=str(output_path),
    )

    assert returned_path == str(output_path)
    document = docx.Document(returned_path)
    paragraphs = [paragraph.text for paragraph in document.paragraphs]
    assert "组织架构怎么调整？" in paragraphs
    assert "建议先明确职责边界，再调整汇报关系。" in paragraphs
    assert len(document.tables) == 1
    table_text = "\n".join(cell.text for row in document.tables[0].rows for cell in row.cells)
    assert "组织架构调整方案.pptx" in table_text
    assert "deck.pptx#2" in table_text


def test_export_to_ppt_without_agent05_writes_markdown_fallback(tmp_path):
    output_path = tmp_path / "answer.pptx"

    returned_path = export_to_ppt(
        question="怎么做组织调整？",
        answer="先识别关键岗位。",
        sources=sample_sources(),
        output_path=str(output_path),
    )

    fallback = Path(returned_path)
    assert fallback.suffix == ".md"
    assert fallback.exists()
    content = fallback.read_text(encoding="utf-8")
    assert "PPT 导出需要 Agent05" in content
    assert "怎么做组织调整？" in content
    assert "组织架构调整方案.pptx" in content
