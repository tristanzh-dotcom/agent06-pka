from engine.evidence import build_evidence_report
from engine.models import RetrievedChunk
from engine.query_rewriter import QueryVariant


def chunk(chunk_id, source_name, source_type="txt"):
    return RetrievedChunk(
        chunk_id=chunk_id,
        text="资料内容",
        source_name=source_name,
        source_type=source_type,
        chunk_index=int(chunk_id.rsplit("#", 1)[-1]),
        score=0.8,
        rank_fts5=1,
        rank_vector=1,
    )


def test_evidence_report_summarizes_chunk_level_coverage():
    variants = [
        QueryVariant(query="JLR 面试", reason="base topic"),
        QueryVariant(query="JLR 面试反馈", reason="feedback variant"),
    ]
    report = build_evidence_report(
        chunks=[
            chunk("jlr_notes.md#0", "jlr_notes.md"),
            chunk("jlr_notes.md#1", "jlr_notes.md"),
            chunk("jlr_role.pdf#0", "jlr_role.pdf", "pdf"),
        ],
        query_variants=variants,
        variant_chunk_ids={
            "JLR 面试": ["jlr_notes.md#0", "jlr_notes.md#1", "jlr_role.pdf#0"],
            "JLR 面试反馈": [],
        },
    )

    payload = report.to_dict()
    assert payload["coverage"]["coverage_status"] == "grounded"
    assert payload["coverage"]["source_count"] == 2
    assert payload["coverage"]["chunk_count"] == 3
    assert payload["coverage"]["source_types"] == {"txt": 2, "pdf": 1}
    assert payload["top_sources"][0] == {"source_name": "jlr_notes.md", "chunk_count": 2}
    assert payload["missing_evidence"] == ["No chunks were retrieved for JLR 面试反馈."]
    assert "claims" not in payload


def test_evidence_report_marks_no_answer_and_thin_coverage():
    empty = build_evidence_report(chunks=[])
    thin = build_evidence_report(chunks=[chunk("single.md#0", "single.md")])

    assert empty.to_dict()["coverage"]["coverage_status"] == "no_answer"
    assert thin.to_dict()["coverage"]["coverage_status"] == "thin"
