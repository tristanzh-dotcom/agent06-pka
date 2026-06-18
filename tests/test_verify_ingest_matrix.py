import json
import subprocess
import sys
from pathlib import Path

from scripts.verify_ingest_matrix import AssetPaths, run_verification


class FakeMatrixClient:
    def __init__(self):
        self.calls = []
        self.total_chunks = 105

    def clear(self):
        self.calls.append(("clear",))
        self.total_chunks = 0
        return {"status": "ok"}

    def ingest_text(self, text):
        self.calls.append(("ingest_text", text))
        self.total_chunks = 1
        return {
            "status": "ok",
            "chunks": 1,
            "source_type": "text",
            "raw_file_path": "",
            "quality": {"status": "high", "action": "direct"},
        }, 1.17

    def ingest_file(self, path, mime_type, org_chart_mode="disabled"):
        self.calls.append(("ingest_file", Path(path).name, org_chart_mode))
        name = Path(path).name
        if "Turtle" in name:
            self.total_chunks = 0
            return {
                "status": "partial",
                "total_chunks": 0,
                "files": [{
                    "status": "error",
                    "quality": {"status": "too_large", "action": "too_large_skipped"},
                }],
            }, 0.85
        if "GEO" in name:
            self.total_chunks = 0
            return {
                "status": "accepted",
                "accepted": 1,
                "total_chunks": 0,
                "files": [{
                    "status": "accepted",
                    "task_id": "ocr_task_fake_geo",
                    "chunks": 0,
                    "quality": {"status": "needs_ocr", "action": "needs_ocr_queued"},
                }],
            }, 0.03
        if "JLR" in name:
            self.total_chunks = 105
            return {
                "status": "ok",
                "succeeded": 1,
                "skipped": 0,
                "failed": 0,
                "total_chunks": 105,
                "files": [{
                    "status": "ok",
                    "chunks": 105,
                    "source_type": "pdf",
                    "org_chart_chunks": 83,
                    "quality": {
                        "status": "high",
                        "action": "cleaned",
                        "org_chart_mode": "pdf_layout_fallback",
                    },
                }],
            }, 13.14
        raise AssertionError(f"unexpected file {name}")

    def stats(self):
        self.calls.append(("stats",))
        return {"indexed_files": 1 if self.total_chunks else 0, "total_chunks": self.total_chunks}

    def physical_counts(self):
        self.calls.append(("physical_counts",))
        if self.total_chunks == 105:
            return {"fts5": 105, "chroma": 105, "source_types": {"org_chart": 83, "pdf": 22}}
        return {"fts5": 0, "chroma": 0, "source_types": {}}

    def query_sources(self, question):
        self.calls.append(("query_sources", question))
        if "How should" in question:
            return {"source_status": "grounded", "sources": [{"source_type": "pdf", "chunk_id": "jlr.pdf#4"}]}
        if "structurally under" in question:
            return {
                "source_status": "grounded",
                "sources": [{"source_type": "org_chart", "chunk_id": "jlr.pdf#org_chart_51"}],
            }
        raise AssertionError(f"unexpected question {question}")


def test_verify_ingest_matrix_restores_jlr_baseline_and_writes_json_report(tmp_path):
    client = FakeMatrixClient()
    paths = AssetPaths(
        turtle_pdf="/fixtures/Turtle of the world 2010.pdf",
        geo_pdf="/fixtures/2026中国新能源汽车品牌GEO现状研究报告-亿欧智库.pdf",
        jlr_pdf="/fixtures/JLR_Corporate_Deck_Template_MASTER_25_.pptx.pdf",
    )

    report = run_verification(
        client=client,
        asset_paths=paths,
        report_dir=tmp_path,
        timestamp="20260616_183000",
    )

    assert report["status"] == "passed"
    assert client.calls[0] == ("clear",)
    assert client.calls[-3:] == [
        ("clear",),
        ("ingest_file", "JLR_Corporate_Deck_Template_MASTER_25_.pptx.pdf", "enabled"),
        ("physical_counts",),
    ]
    assert ("ingest_file", "Turtle of the world 2010.pdf", "disabled") in client.calls
    assert ("ingest_file", "2026中国新能源汽车品牌GEO现状研究报告-亿欧智库.pdf", "disabled") in client.calls
    assert report["summary"]["total_cases"] == 7
    assert report["summary"]["failed_cases"] == 0
    assert report["cases"]["manual_text"]["chunks"] == 1
    assert report["cases"]["turtle_too_large"]["quality_action"] == "too_large_skipped"
    assert report["cases"]["geo_needs_ocr"]["quality_action"] == "needs_ocr_queued"
    assert report["cases"]["geo_needs_ocr"]["task_id"] == "ocr_task_fake_geo"
    assert report["cases"]["jlr_ingest"]["org_chart_chunks"] == 83
    assert report["cases"]["q6_explanation"]["first_source_type"] == "pdf"
    assert report["cases"]["q8_structural"]["first_source_type"] == "org_chart"
    assert report["cases"]["final_restore"]["chunks"] == 105

    report_path = tmp_path / "verification_report_20260616_183000.json"
    assert report_path.exists()
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["status"] == "passed"
    assert saved["cases"]["final_restore"]["source_types"] == {"org_chart": 83, "pdf": 22}


def test_verify_ingest_matrix_cli_help_runs_from_script_path():
    project_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "scripts/verify_ingest_matrix.py", "--help"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Run PKA v1 ingest/retrieval acceptance matrix." in result.stdout
