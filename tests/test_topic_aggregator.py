from engine.models import RetrievedChunk
from engine.query_rewriter import QueryVariant
from engine.topic_aggregator import build_topic_dossier


def chunk(chunk_id, source_name, source_type="txt", text="项目复盘内容", score=0.9):
    return RetrievedChunk(
        chunk_id=chunk_id,
        text=text,
        source_name=source_name,
        source_type=source_type,
        chunk_index=int(chunk_id.rsplit("#", 1)[-1]),
        score=score,
        rank_fts5=1,
        rank_vector=1,
    )


def test_topic_dossier_deduplicates_chunks_and_groups_by_source():
    variants = [
        QueryVariant(query="JLR 面试", reason="base topic"),
        QueryVariant(query="JLR 面试复盘", reason="retrospective variant"),
    ]
    dossier = build_topic_dossier(
        question="整理一下 JLR 面试材料",
        variant_results=[
            (variants[0], [chunk("jlr_notes.md#0", "jlr_notes.md")]),
            (
                variants[1],
                [
                    chunk("jlr_notes.md#0", "jlr_notes.md"),
                    chunk("jlr_feedback.pdf#1", "jlr_feedback.pdf", "pdf"),
                ],
            ),
        ],
    )

    assert dossier.coverage.chunk_count == 2
    assert dossier.coverage.source_count == 2
    assert dossier.coverage.source_types == {"txt": 1, "pdf": 1}
    assert [group.source_name for group in dossier.groups] == ["jlr_notes.md", "jlr_feedback.pdf"]
    assert dossier.groups[0].chunk_count == 1
    assert "JLR 面试复盘" in dossier.query_variants
    assert not dossier.coverage.low_evidence


def test_topic_dossier_marks_empty_results_as_low_evidence():
    variants = [QueryVariant(query="JLR 面试反馈", reason="feedback variant")]
    dossier = build_topic_dossier(
        question="整理一下 JLR 面试材料",
        variant_results=[(variants[0], [])],
    )

    assert dossier.coverage.chunk_count == 0
    assert dossier.coverage.source_count == 0
    assert dossier.coverage.low_evidence is True
    assert dossier.missing_queries == ["JLR 面试反馈"]
    assert "Low evidence: true" in dossier.to_markdown()

