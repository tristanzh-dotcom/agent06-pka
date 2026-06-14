from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List
from urllib.parse import quote, urlparse, urlunparse

import httpx


class PPTMakerExportError(RuntimeError):
    pass


def export_to_quality_ppt(
    question: str,
    answer: str,
    sources: List[Dict],
    output_path: str,
    config: Dict,
) -> str:
    ppt_config = dict(config.get("ppt_maker") or {})
    if not ppt_config.get("enabled", True):
        raise PPTMakerExportError("ppt maker integration disabled")

    try:
        import websocket
    except ImportError as exc:
        raise PPTMakerExportError("websocket-client is not installed") from exc

    http_base_url = str(ppt_config.get("http_base_url") or "http://127.0.0.1:8000").rstrip("/")
    ws_url = str(ppt_config.get("ws_url") or _ws_url_from_http_base(http_base_url))
    timeout_seconds = float(ppt_config.get("timeout_seconds") or 180)
    page_count = int(ppt_config.get("page_count") or 5)
    style = str(ppt_config.get("style") or "business-summary")

    result = _run_agent05_generation(
        websocket_module=websocket,
        ws_url=ws_url,
        timeout_seconds=timeout_seconds,
        payload={
            "mode": "prompt_to_ppt",
            "prompt": _build_pka_report_prompt(question, answer, sources, page_count),
            "page_count": page_count,
            "style": style,
            "purpose": "personal-knowledge-report",
        },
    )
    file_id = str(result.get("file_id") or "").strip()
    if not file_id:
        raise PPTMakerExportError("agent05 did not return file_id")

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _download_pptx(http_base_url, file_id, path, timeout_seconds)
    return str(path)


def _run_agent05_generation(websocket_module, ws_url: str, timeout_seconds: float, payload: Dict) -> Dict:
    deadline = time.monotonic() + timeout_seconds
    socket = websocket_module.create_connection(ws_url, timeout=timeout_seconds)
    try:
        socket.send(json.dumps({"type": "generate", "payload": payload}, ensure_ascii=False))
        while time.monotonic() < deadline:
            raw_message = socket.recv()
            if not raw_message:
                continue
            message = json.loads(raw_message)
            message_type = message.get("type")
            if message_type == "template_candidates":
                candidates = message.get("candidates") if isinstance(message.get("candidates"), list) else []
                if candidates:
                    template_slug = str(candidates[0].get("slug") or "")
                    if template_slug:
                        socket.send(json.dumps({"type": "select_template", "template_slug": template_slug}))
            elif message_type == "complete":
                result = message.get("result")
                if isinstance(result, dict):
                    return result
                raise PPTMakerExportError("agent05 complete event missing result")
            elif message_type == "error":
                raise PPTMakerExportError(str(message.get("message") or "agent05 generation failed"))
            elif message_type == "cancelled":
                raise PPTMakerExportError("agent05 generation cancelled")
    finally:
        socket.close()
    raise PPTMakerExportError("agent05 generation timed out")


def _download_pptx(http_base_url: str, file_id: str, output_path: Path, timeout_seconds: float) -> None:
    safe_file_id = quote(file_id, safe="/")
    url = f"{http_base_url}/api/files/{safe_file_id}/download"
    with httpx.Client(timeout=timeout_seconds) as client:
        response = client.get(url)
        response.raise_for_status()
        content = response.content
    if not content.startswith(b"PK"):
        raise PPTMakerExportError("agent05 download is not a pptx package")
    output_path.write_bytes(content)


def _ws_url_from_http_base(http_base_url: str) -> str:
    parsed = urlparse(http_base_url)
    if parsed.scheme == "https":
        scheme = "wss"
    elif parsed.scheme == "http":
        scheme = "ws"
    else:
        raise PPTMakerExportError(f"unsupported ppt maker base URL: {http_base_url}")
    return urlunparse((scheme, parsed.netloc, "/ws/generate", "", "", ""))


def _build_pka_report_prompt(question: str, answer: str, sources: List[Dict], page_count: int) -> str:
    source_lines = []
    for source in sources[:8]:
        source_name = str(source.get("source_name", "")).strip() or "未知来源"
        chunk_index = str(source.get("chunk_index", "")).strip()
        relevance = source.get("relevance")
        suffix = f" chunk {chunk_index}" if chunk_index else ""
        score = f" relevance {float(relevance):.4f}" if isinstance(relevance, (int, float)) else ""
        source_lines.append(f"- {source_name}{suffix}{score}")
    sources_text = "\n".join(source_lines) if source_lines else "- 无明确来源"
    return (
        f"请基于以下个人知识库问答结果，生成一份 {page_count} 页中文商务汇报 PPT。\n"
        "要求：封面、核心结论、依据拆解、行动建议、参考来源。语言克制、结构清晰，避免堆长段落。\n\n"
        f"## 用户问题\n{question}\n\n"
        f"## 问答结论\n{answer}\n\n"
        f"## 参考来源\n{sources_text}\n"
    )
