from pathlib import Path
from typing import Dict, List


def export_to_word(question: str, answer: str, sources: List[Dict], output_path: str) -> str:
    import docx

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    document = docx.Document()
    document.add_heading("PKA 问答导出", level=1)
    document.add_heading("问题", level=2)
    document.add_paragraph(question)
    document.add_heading("回答", level=2)
    document.add_paragraph(answer)
    document.add_heading("参考来源", level=2)

    table = document.add_table(rows=1, cols=4)
    table.style = "Table Grid"
    headers = ["来源文件", "Chunk", "相关度", "Chunk ID"]
    for cell, value in zip(table.rows[0].cells, headers):
        cell.text = value

    for source in sources:
        row = table.add_row().cells
        row[0].text = str(source.get("source_name", ""))
        row[1].text = str(source.get("chunk_index", ""))
        row[2].text = _format_relevance(source.get("relevance"))
        row[3].text = str(source.get("chunk_id", ""))

    document.save(path)
    return str(path)


def export_to_ppt(question: str, answer: str, sources: List[Dict], output_path: str) -> str:
    path = Path(output_path)
    fallback_path = path.with_suffix(".md")
    fallback_path.parent.mkdir(parents=True, exist_ok=True)
    fallback_path.write_text(
        _ppt_fallback_markdown(question, answer, sources),
        encoding="utf-8",
    )
    return str(fallback_path)


def _ppt_fallback_markdown(question: str, answer: str, sources: List[Dict]) -> str:
    source_lines = []
    for source in sources:
        source_lines.append(
            "- "
            + str(source.get("source_name", ""))
            + f" | chunk {source.get('chunk_index', '')}"
            + (f" | {source.get('chunk_id')}" if source.get("chunk_id") else "")
        )
    return "\n".join(
        [
            "# PPT 导出需要 Agent05",
            "",
            "当前环境未接入 Agent05 PPT-maker，已生成可交给 Agent05 的 Markdown 大纲。",
            "",
            "## 问题",
            question,
            "",
            "## 回答",
            answer,
            "",
            "## 参考来源",
            "\n".join(source_lines) if source_lines else "- 无",
            "",
        ]
    )


def _format_relevance(value) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return str(value)
