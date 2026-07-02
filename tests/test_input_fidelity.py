from engine.input_fidelity import build_input_fidelity_report, expand_adjacent_chunks
from engine.models import RetrievedChunk


def chunk(chunk_id, source_name="notes.md", text="内容", score=0.9):
    return RetrievedChunk(
        chunk_id=chunk_id,
        text=text,
        source_name=source_name,
        source_type="md",
        chunk_index=int(chunk_id.rsplit("#", 1)[-1]),
        score=score,
        rank_fts5=1,
        rank_vector=1,
    )


class FakeIndexer:
    def __init__(self):
        self.records = {
            "notes.md#1": {
                "chunk_id": "notes.md#1",
                "text": "前文：项目背景和问题来源。",
                "source_name": "notes.md",
                "source_type": "md",
                "chunk_index": 1,
                "raw_file_path": "",
            },
            "notes.md#3": {
                "chunk_id": "notes.md#3",
                "text": "后文：结果复盘和后续行动。",
                "source_name": "notes.md",
                "source_type": "md",
                "chunk_index": 3,
                "raw_file_path": "",
            },
        }

    def get_chunk(self, chunk_id):
        return self.records.get(chunk_id)


def test_expand_adjacent_chunks_adds_same_source_context_without_duplicates():
    selected = [chunk("notes.md#2", text="中间：关键技术选型。")]

    expanded, report = expand_adjacent_chunks(selected, FakeIndexer(), radius=1, max_added=4)

    assert [item.chunk_id for item in expanded] == ["notes.md#1", "notes.md#2", "notes.md#3"]
    assert report.added_context_chunks == 2
    assert report.original_chunk_count == 1
    assert report.final_chunk_count == 3
    assert report.chunk_reports[0].role == "context_before"
    assert report.chunk_reports[1].role == "retrieved"
    assert report.chunk_reports[2].role == "context_after"


def test_input_fidelity_report_flags_fragmented_cross_source_context():
    chunks = [
        chunk("a.md#0", source_name="a.md", text="A" * 80),
        chunk("b.md#5", source_name="b.md", text="B" * 80),
    ]

    report = build_input_fidelity_report(chunks, original_chunk_count=2, added_context_chunks=0)

    payload = report.to_dict()
    assert payload["continuity_status"] == "fragmented"
    assert payload["source_count"] == 2
    assert payload["prompt_reference_chars"] == 160
    assert payload["chunks"][0]["text_chars"] == 80
    assert "text" not in payload["chunks"][0]
