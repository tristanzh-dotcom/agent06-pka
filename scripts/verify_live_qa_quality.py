#!/usr/bin/env python3
"""Run a bounded live-provider QA matrix without reading the user's knowledge base."""

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
import re
import sys
from typing import Iterable, Optional

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server
from engine.models import RetrievedChunk


@dataclass(frozen=True)
class AcceptanceCase:
    key: str
    question: str
    expected_status: str
    required_answer_terms: tuple[str, ...] = ()
    previous_question: Optional[str] = None


SYNTHETIC_SOURCE_TEXT = (
    "合成测试项目 Alpha 的正式发布日期为 2026 年 9 月 18 日。"
    "项目负责人是林岳。林岳需要在 2026 年 9 月 10 日前完成发布检查清单。"
    "这些内容仅用于 PKA 自动化问答质量验收，不代表真实项目或个人信息。"
)


def acceptance_cases() -> tuple[AcceptanceCase, ...]:
    initial_question = "合成测试项目 Alpha 的发布日期和负责人是谁？"
    return (
        AcceptanceCase(
            key="grounded_initial",
            question=initial_question,
            expected_status="grounded",
            required_answer_terms=("2026年9月18日", "林岳"),
        ),
        AcceptanceCase(
            key="grounded_follow_up",
            question="那负责人需要在什么时候完成发布检查清单？",
            previous_question=initial_question,
            expected_status="grounded",
            required_answer_terms=("2026年9月10日",),
        ),
        AcceptanceCase(
            key="context_free_follow_up",
            question="那这个项目呢？",
            expected_status="clarification_required",
        ),
        AcceptanceCase(
            key="out_of_corpus",
            question="合成测试项目 Beta 的预算是多少？",
            expected_status="no_answer",
        ),
    )


class SyntheticAcceptanceRetriever:
    def hybrid_search(self, query: str, top_k: int):
        if "Alpha" not in query:
            return []
        return [
            RetrievedChunk(
                chunk_id="qa-live-synthetic.txt#0",
                text=SYNTHETIC_SOURCE_TEXT,
                source_name="qa-live-synthetic.txt",
                source_type="txt",
                chunk_index=0,
                score=1.0,
                rank_fts5=1,
                rank_vector=1,
            )
        ][:top_k]


def parse_sse_events(body: str) -> list[dict]:
    events = []
    for line in body.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line.removeprefix("data: ").strip()
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def evaluate_case(case: AcceptanceCase, events: Iterable[dict]) -> dict:
    event_list = list(events)
    answer = "".join(
        str(event.get("content") or "")
        for event in event_list
        if event.get("type") == "token"
    )
    sources_event = next(
        (event for event in event_list if event.get("type") == "sources"),
        {},
    )
    source_status = str(sources_event.get("source_status") or "")
    sources = list(sources_event.get("sources") or [])
    failures = []
    if any(event.get("type") == "error" for event in event_list):
        failures.append("provider returned an error event")
    if not any(event.get("type") == "done" for event in event_list):
        failures.append("stream did not finish")
    if source_status != case.expected_status:
        failures.append(
            f"expected source_status={case.expected_status}, got {source_status or 'missing'}"
        )
    if case.expected_status == "grounded" and not sources:
        failures.append("grounded answer returned no sources")
    if case.expected_status in {"no_answer", "clarification_required"} and sources:
        failures.append("rejection path returned sources")
    compact_answer = _compact(answer)
    for term in case.required_answer_terms:
        if _compact(term) not in compact_answer:
            failures.append(f"answer omitted required fact: {term}")
    return {
        "key": case.key,
        "question": case.question,
        "previous_question": case.previous_question,
        "expected_status": case.expected_status,
        "source_status": source_status,
        "source_count": len(sources),
        "answer": answer,
        "failures": failures,
        "passed": not failures,
    }


def run_live_verification() -> dict:
    deepseek = server.runtime.config.get("deepseek", {})
    endpoint = str(deepseek.get("endpoint") or "")
    api_key = str(deepseek.get("api_key") or "")
    model = str(deepseek.get("model") or "")
    if not endpoint or not api_key:
        return {
            "status": "blocked",
            "provider": "DeepSeek",
            "model": model,
            "reason": "DeepSeek endpoint or API key is not configured",
            "cases": [],
        }

    original_retriever = server.HybridRetriever
    original_get_chunk = server.runtime.indexer.get_chunk
    server.HybridRetriever = lambda **kwargs: SyntheticAcceptanceRetriever()
    server.runtime.indexer.get_chunk = lambda chunk_id: None
    results = []
    try:
        client = TestClient(server.app)
        for case in acceptance_cases():
            payload = {"question": case.question, "language": "zh"}
            if case.previous_question:
                payload["previous_question"] = case.previous_question
                payload["conversation_id"] = "qa-live-acceptance"
            response = client.post("/api/query", json=payload)
            if response.status_code != 200:
                results.append(
                    {
                        **asdict(case),
                        "source_status": "",
                        "source_count": 0,
                        "answer": "",
                        "failures": [f"HTTP {response.status_code}"],
                        "passed": False,
                    }
                )
                continue
            results.append(evaluate_case(case, parse_sse_events(response.text)))
    finally:
        server.HybridRetriever = original_retriever
        server.runtime.indexer.get_chunk = original_get_chunk

    return {
        "status": "passed" if all(item["passed"] for item in results) else "failed",
        "provider": "DeepSeek",
        "model": model,
        "data_boundary": "synthetic text only; no user documents or live knowledge-base chunks",
        "executed_at": datetime.now().astimezone().isoformat(),
        "cases": results,
    }


def render_markdown_report(report: dict) -> str:
    lines = [
        "# PKA Live QA Quality Verification",
        "",
        f"- status: {report.get('status', '')}",
        f"- provider: {report.get('provider', '')}",
        f"- model: {report.get('model', '')}",
    ]
    if report.get("data_boundary"):
        lines.append(f"- data boundary: {report['data_boundary']}")
    if report.get("reason"):
        lines.append(f"- reason: {report['reason']}")
    lines.extend(
        [
            "",
            "| case | passed | expected | actual | sources | answer |",
            "|---|---|---|---|---:|---|",
        ]
    )
    for item in report.get("cases", []):
        answer = str(item.get("answer") or "").replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {item.get('key', '')} | {item.get('passed', False)} | "
            f"{item.get('expected_status', '')} | {item.get('source_status', '')} | "
            f"{item.get('source_count', 0)} | {answer} |"
        )
        for failure in item.get("failures", []):
            lines.append(f"  - {item.get('key', '')}: {failure}")
    return "\n".join(lines) + "\n"


def _compact(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "", value or "").lower()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the PKA live-provider QA matrix with synthetic source text."
    )
    parser.add_argument("--report-dir", required=True)
    args = parser.parse_args()
    report = run_live_verification()
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = report_dir / f"live_qa_quality_{stamp}.json"
    markdown_path = report_dir / f"live_qa_quality_{stamp}.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown_report(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "json_report": str(json_path),
                "markdown_report": str(markdown_path),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
