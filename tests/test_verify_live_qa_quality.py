import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.verify_live_qa_quality import (
    AcceptanceCase,
    evaluate_case,
    parse_sse_events,
    render_markdown_report,
)


def test_parse_sse_events_collects_tokens_and_sources():
    body = "\n\n".join(
        [
            'data: {"type":"token","content":"发布日期为 2026 年 9 月 18 日。"}',
            'data: {"type":"sources","sources":[{"source_name":"qa-e2e.txt"}],"source_status":"grounded"}',
            'data: {"type":"done"}',
        ]
    )

    events = parse_sse_events(body)

    assert [event["type"] for event in events] == ["token", "sources", "done"]


def test_evaluate_grounded_case_requires_all_fact_anchors():
    case = AcceptanceCase(
        key="grounded",
        question="Alpha 何时发布，由谁负责？",
        expected_status="grounded",
        required_answer_terms=("2026年9月18日", "林岳"),
        forbidden_answer_terms=("你是项目负责人",),
    )
    events = [
        {"type": "token", "content": "Alpha 由林岳负责，发布日期是 2026 年 9 月 18 日。"},
        {
            "type": "sources",
            "sources": [{"source_name": "qa-e2e.txt"}],
            "source_status": "grounded",
        },
        {"type": "done"},
    ]

    result = evaluate_case(case, events)

    assert result["passed"] is True
    assert result["answer"] == "Alpha 由林岳负责，发布日期是 2026 年 9 月 18 日。"


def test_evaluate_grounded_case_fails_when_model_omits_fact():
    case = AcceptanceCase(
        key="grounded",
        question="Alpha 何时发布，由谁负责？",
        expected_status="grounded",
        required_answer_terms=("2026年9月18日", "林岳"),
    )
    events = [
        {"type": "token", "content": "Alpha 由林岳负责。"},
        {
            "type": "sources",
            "sources": [{"source_name": "qa-e2e.txt"}],
            "source_status": "grounded",
        },
        {"type": "done"},
    ]

    result = evaluate_case(case, events)

    assert result["passed"] is False
    assert any("2026年9月18日" in failure for failure in result["failures"])


def test_evaluate_grounded_case_rejects_unsupported_user_identity():
    case = AcceptanceCase(
        key="grounded",
        question="Alpha 何时发布，由谁负责？",
        expected_status="grounded",
        forbidden_answer_terms=("你是项目负责人",),
    )
    events = [
        {"type": "token", "content": "既然你是项目负责人，请提前安排检查。"},
        {
            "type": "sources",
            "sources": [{"source_name": "qa-e2e.txt"}],
            "source_status": "grounded",
        },
        {"type": "done"},
    ]

    result = evaluate_case(case, events)

    assert result["passed"] is False
    assert any("unsupported inference" in failure for failure in result["failures"])


@pytest.mark.parametrize("status", ["no_answer", "clarification_required"])
def test_evaluate_rejection_cases_require_empty_sources(status):
    case = AcceptanceCase(
        key=status,
        question="这个呢？",
        expected_status=status,
    )
    events = [
        {"type": "token", "content": "请补充资料或明确问题。"},
        {"type": "sources", "sources": [], "source_status": status},
        {"type": "done"},
    ]

    assert evaluate_case(case, events)["passed"] is True


def test_render_markdown_report_records_provider_without_secrets():
    report = {
        "status": "passed",
        "provider": "DeepSeek",
        "model": "deepseek-v4-pro",
        "cases": [
            {
                "key": "grounded",
                "passed": True,
                "source_status": "grounded",
                "answer": "通过",
                "failures": [],
            }
        ],
    }

    markdown = render_markdown_report(report)

    assert "# PKA Live QA Quality Verification" in markdown
    assert "DeepSeek" in markdown
    assert "deepseek-v4-pro" in markdown
    assert "api_key" not in markdown
    assert "sk-" not in markdown


def test_cli_help_runs_from_the_project_root():
    root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "scripts/verify_live_qa_quality.py", "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "synthetic source text" in result.stdout
