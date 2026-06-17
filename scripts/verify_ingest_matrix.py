from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.config import load_config


MANUAL_TEXT = (
    "CARIAD is responsible for MIB-1 software integration. "
    "This manual text verifies unified ingest, text source typing, and empty raw_file_path."
)
Q6_EXPLANATION = "How should the organisation charts be read?"
Q8_STRUCTURAL = "Which people are structurally under Infotainment and Connectivity?"


@dataclass(frozen=True)
class AssetPaths:
    turtle_pdf: str
    geo_pdf: str
    jlr_pdf: str


class MatrixHttpClient:
    def __init__(self, base_url: str, *, data_dir: str, timeout_seconds: float = 180.0):
        self.base_url = base_url.rstrip("/")
        self.data_dir = Path(data_dir)
        self.timeout_seconds = timeout_seconds

    def clear(self) -> Dict[str, Any]:
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(f"{self.base_url}/api/ingest/clear")
            response.raise_for_status()
            return response.json()

    def ingest_text(self, text: str) -> Tuple[Dict[str, Any], float]:
        start = time.perf_counter()
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(f"{self.base_url}/api/ingest/text", json={"text": text})
            response.raise_for_status()
            return response.json(), time.perf_counter() - start

    def ingest_file(self, path: str, mime_type: str) -> Tuple[Dict[str, Any], float]:
        start = time.perf_counter()
        with Path(path).open("rb") as handle:
            files = {"files": (Path(path).name, handle, mime_type)}
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(f"{self.base_url}/api/ingest/files", files=files)
                response.raise_for_status()
                return response.json(), time.perf_counter() - start

    def stats(self) -> Dict[str, Any]:
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.get(f"{self.base_url}/api/stats")
            response.raise_for_status()
            return response.json()

    def query_sources(self, question: str) -> Dict[str, Any]:
        with httpx.Client(timeout=self.timeout_seconds) as client:
            with client.stream(
                "POST",
                f"{self.base_url}/api/query",
                json={"question": question, "language": "zh"},
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    event = json.loads(line.removeprefix("data: ").strip())
                    if event.get("type") == "sources":
                        return event
        raise AssertionError(f"query produced no sources event: {question}")

    def physical_counts(self) -> Dict[str, Any]:
        fts_db = self.data_dir / ".fts5" / "pka.db"
        with sqlite3.connect(str(fts_db)) as connection:
            fts5_count = connection.execute("select count(*) from chunks_fts").fetchone()[0]
            source_types = {
                source_type: count
                for source_type, count in connection.execute(
                    "select source_type, count(*) from chunks_fts group by source_type"
                )
            }

        import chromadb

        client = chromadb.PersistentClient(path=str(self.data_dir / ".vector"))
        collection = client.get_collection("pka_knowledge")
        return {"fts5": fts5_count, "chroma": collection.count(), "source_types": source_types}


def run_verification(
    *,
    client,
    asset_paths: AssetPaths,
    report_dir: str | Path,
    timestamp: str | None = None,
) -> Dict[str, Any]:
    timestamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    cases: Dict[str, Dict[str, Any]] = {}

    client.clear()

    text_payload, text_elapsed = client.ingest_text(MANUAL_TEXT)
    _assert(text_payload["status"] == "ok", "manual text ingest must succeed")
    _assert(text_payload["chunks"] == 1, "manual text must produce exactly one chunk")
    _assert(text_payload["source_type"] == "text", "manual text source_type must be text")
    _assert(text_payload["raw_file_path"] == "", "manual text raw_file_path must be empty")
    text_stats = client.stats()
    _assert(text_stats["total_chunks"] == 1, "manual text stats must report one chunk")
    cases["manual_text"] = {
        "status": "passed",
        "elapsed_seconds": round(text_elapsed, 3),
        "chunks": text_payload["chunks"],
        "source_type": text_payload["source_type"],
        "raw_file_path": text_payload["raw_file_path"],
    }

    client.clear()
    turtle_payload, turtle_elapsed = client.ingest_file(asset_paths.turtle_pdf, "application/pdf")
    turtle_file = _single_file(turtle_payload)
    _assert(turtle_payload["total_chunks"] == 0, "turtle ingest must not index chunks")
    _assert(turtle_file["status"] == "error", "turtle ingest must be marked error in batch result")
    _assert(
        turtle_file["quality"]["action"] == "too_large_skipped",
        "turtle ingest must trip too_large_skipped",
    )
    _assert(turtle_elapsed < 5.0, "turtle too-large fuse must return quickly")
    turtle_stats = client.stats()
    _assert(turtle_stats["total_chunks"] == 0, "turtle stats must remain empty")
    cases["turtle_too_large"] = {
        "status": "passed",
        "elapsed_seconds": round(turtle_elapsed, 3),
        "quality_action": turtle_file["quality"]["action"],
        "chunks": turtle_payload["total_chunks"],
    }

    client.clear()
    geo_payload, geo_elapsed = client.ingest_file(asset_paths.geo_pdf, "application/pdf")
    geo_file = _single_file(geo_payload)
    _assert(geo_payload["total_chunks"] == 0, "GEO ingest must not index chunks")
    _assert(geo_file["status"] == "skipped", "GEO scan must be skipped")
    _assert(
        geo_file["quality"]["action"] == "needs_ocr_skipped",
        "GEO scan must trip needs_ocr_skipped",
    )
    _assert(geo_elapsed < 5.0, "GEO OCR fuse must return quickly")
    geo_stats = client.stats()
    _assert(geo_stats["total_chunks"] == 0, "GEO stats must remain empty")
    cases["geo_needs_ocr"] = {
        "status": "passed",
        "elapsed_seconds": round(geo_elapsed, 3),
        "quality_action": geo_file["quality"]["action"],
        "chunks": geo_payload["total_chunks"],
    }

    client.clear()
    jlr_payload, jlr_elapsed = client.ingest_file(asset_paths.jlr_pdf, "application/pdf")
    jlr_file = _single_file(jlr_payload)
    _assert(jlr_payload["status"] == "ok", "JLR ingest batch must succeed")
    _assert(jlr_payload["total_chunks"] == 105, "JLR ingest must produce 105 chunks")
    _assert(jlr_file["org_chart_chunks"] == 83, "JLR ingest must produce 83 org_chart chunks")
    jlr_counts = client.physical_counts()
    _assert(jlr_counts["fts5"] == 105, "JLR FTS5 count must be 105")
    _assert(jlr_counts["chroma"] == 105, "JLR Chroma count must be 105")
    _assert(jlr_counts["source_types"] == {"org_chart": 83, "pdf": 22}, "JLR source_type counts mismatch")
    cases["jlr_ingest"] = {
        "status": "passed",
        "elapsed_seconds": round(jlr_elapsed, 3),
        "chunks": jlr_payload["total_chunks"],
        "org_chart_chunks": jlr_file["org_chart_chunks"],
        "source_types": jlr_counts["source_types"],
    }

    q6_sources = client.query_sources(Q6_EXPLANATION)
    _assert(q6_sources["source_status"] == "grounded", "Q6 must be grounded")
    _assert(q6_sources["sources"][0]["source_type"] == "pdf", "Q6 first source must be pdf")
    cases["q6_explanation"] = {
        "status": "passed",
        "first_source_type": q6_sources["sources"][0]["source_type"],
        "first_chunk_id": q6_sources["sources"][0]["chunk_id"],
    }

    q8_sources = client.query_sources(Q8_STRUCTURAL)
    _assert(q8_sources["source_status"] == "grounded", "Q8 must be grounded")
    _assert(q8_sources["sources"][0]["source_type"] == "org_chart", "Q8 first source must be org_chart")
    cases["q8_structural"] = {
        "status": "passed",
        "first_source_type": q8_sources["sources"][0]["source_type"],
        "first_chunk_id": q8_sources["sources"][0]["chunk_id"],
    }

    client.clear()
    restore_payload, restore_elapsed = client.ingest_file(asset_paths.jlr_pdf, "application/pdf")
    restore_file = _single_file(restore_payload)
    restore_counts = client.physical_counts()
    _assert(restore_payload["total_chunks"] == 105, "final restore must leave JLR 105 chunk baseline")
    _assert(restore_file["org_chart_chunks"] == 83, "final restore must leave 83 org_chart chunks")
    _assert(restore_counts["fts5"] == 105, "final restore FTS5 count must be 105")
    _assert(restore_counts["chroma"] == 105, "final restore Chroma count must be 105")
    cases["final_restore"] = {
        "status": "passed",
        "elapsed_seconds": round(restore_elapsed, 3),
        "chunks": restore_payload["total_chunks"],
        "org_chart_chunks": restore_file["org_chart_chunks"],
        "source_types": restore_counts["source_types"],
    }

    report = {
        "status": "passed",
        "timestamp": timestamp,
        "base_url": getattr(client, "base_url", ""),
        "summary": {
            "total_cases": len(cases),
            "failed_cases": 0,
        },
        "cases": cases,
    }
    report_path = Path(report_dir) / f"verification_report_{timestamp}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report["report_path"] = str(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _single_file(payload: Dict[str, Any]) -> Dict[str, Any]:
    files = payload.get("files") or []
    _assert(len(files) == 1, "batch response must contain exactly one file")
    return files[0]


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main(argv: list[str] | None = None) -> int:
    config = load_config("config.yaml")
    parser = argparse.ArgumentParser(description="Run PKA v1 ingest/retrieval acceptance matrix.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8086")
    parser.add_argument("--turtle-pdf", default="/Users/tristanzh/Downloads/Turtle of the world 2010.pdf")
    parser.add_argument("--geo-pdf", default="/Users/tristanzh/资料文档/2026中国新能源汽车品牌GEO现状研究报告-亿欧智库.pdf")
    parser.add_argument("--jlr-pdf", default="/Users/tristanzh/agent/Material/JLR_Corporate_Deck_Template_MASTER_25_.pptx.pdf")
    parser.add_argument("--report-dir", default="docs/superpowers/releases")
    parser.add_argument("--timestamp", default=None)
    args = parser.parse_args(argv)

    asset_paths = AssetPaths(
        turtle_pdf=args.turtle_pdf,
        geo_pdf=args.geo_pdf,
        jlr_pdf=args.jlr_pdf,
    )
    client = MatrixHttpClient(args.base_url, data_dir=config["data_dir"])
    report = run_verification(
        client=client,
        asset_paths=asset_paths,
        report_dir=args.report_dir,
        timestamp=args.timestamp,
    )
    print(json.dumps({"status": report["status"], "report_path": report["report_path"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
