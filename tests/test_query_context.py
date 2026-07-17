from engine.models import RetrievedChunk
from engine.query_context import filter_supported_chunks, resolve_query


def chunk(chunk_id: str, text: str, source_type: str = "text") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        text=text,
        source_name="notes.md",
        source_type=source_type,
        chunk_index=int(chunk_id.rsplit("#", 1)[-1]),
        score=0.9,
        rank_fts5=1,
        rank_vector=1,
    )


def test_context_dependent_follow_up_without_previous_question_requires_clarification():
    resolution = resolve_query("那这个问题下一步我具体应该怎么做？", previous_question="")

    assert resolution.status == "clarification_required"
    assert resolution.resolved_question == ""


def test_context_dependent_follow_up_uses_previous_question_as_retrieval_anchor():
    resolution = resolve_query(
        "那这个问题下一步我具体应该怎么做？",
        previous_question="请总结知识库中关于组织架构的信息",
    )

    assert resolution.status == "resolved"
    assert "组织架构" in resolution.resolved_question
    assert "下一步" in resolution.resolved_question


def test_sentence_initial_na_follow_up_uses_previous_question_as_retrieval_anchor():
    resolution = resolve_query(
        "那负责人需要在什么时候完成发布检查清单？",
        previous_question="合成测试项目 Alpha 的发布日期和负责人是谁？",
    )

    assert resolution.status == "resolved"
    assert "Alpha" in resolution.resolved_question
    assert "发布检查清单" in resolution.resolved_question


def test_generic_action_words_do_not_make_unrelated_chunk_supported():
    chunks = [
        chunk("notes.md#0", "这个项目的问题应该由供应商和预算委员会共同处理。"),
        chunk("notes.md#1", "具体执行时应当准备阶段性汇报材料。"),
    ]

    supported = filter_supported_chunks("那这个问题下一步我具体应该怎么做？", chunks)

    assert supported == []


def test_anchor_term_keeps_primary_source_and_demotes_generated_source():
    chunks = [
        chunk("generated.md#0", "组织架构的历史模型总结。", source_type="generated_asset"),
        chunk("notes.md#1", "组织架构调整先明确职责边界，再梳理汇报关系。"),
    ]

    supported = filter_supported_chunks("组织架构下一步怎么做", chunks)

    assert [item.chunk_id for item in supported] == ["notes.md#1", "generated.md#0"]
