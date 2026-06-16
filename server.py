from dataclasses import replace
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine.chunker import chunk_text
from engine.config import load_config, sanitize_config, save_config, update_config
from engine.exporter import export_to_ppt, export_to_word
from engine.generator import generate_answer
from engine.indexer import HybridIndexer, OllamaEmbeddingClient
from engine.models import Chunk, ParseQuality
from engine.ocr import build_ocr_provider_chain
from engine.parser import parse_file, parse_text
from engine.ppt_maker_adapter import export_to_quality_ppt
from engine.retriever import HybridRetriever


CONFIG_PATH = Path("config.yaml")
app = FastAPI(title="PKA")
app.mount("/static", StaticFiles(directory="static"), name="static")


class TextIngestRequest(BaseModel):
    text: str


class QueryRequest(BaseModel):
    question: str
    language: str = "zh"


class ExportRequest(BaseModel):
    question: str
    answer: str
    sources: list[dict] = []


class Runtime:
    def __init__(self):
        self.config = load_config(CONFIG_PATH)
        self.indexer = self._build_indexer()
        self.last_updated = None

    def _build_indexer(self) -> HybridIndexer:
        embedding_config = self.config.get("embedding", {})
        return HybridIndexer(
            fts_db_path=self.config["fts5"]["db_path"],
            vector_dir=self.config["chroma"]["persist_dir"],
            collection_name=self.config["chroma"]["collection_name"],
            embedding_client=OllamaEmbeddingClient(
                host=embedding_config.get("host", "http://localhost:11434"),
                model=embedding_config.get("model", "bge-m3"),
                query_prefix=embedding_config.get("query_prefix", ""),
            ),
        )

    def reload(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.indexer = self._build_indexer()


runtime = Runtime()


@app.get("/", response_class=HTMLResponse)
async def index_page():
    return _html("index.html")


@app.get("/ask", response_class=HTMLResponse)
async def ask_page():
    return _html("ask.html")


@app.get("/settings", response_class=HTMLResponse)
async def settings_page():
    return _html("settings.html")


@app.post("/api/ingest/text")
async def ingest_text(request: TextIngestRequest):
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    source_name = "manual_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    parsed = parse_text(request.text, source_name=source_name)
    parsed = replace(
        parsed,
        metadata={
            **parsed.metadata,
            "mime_type": "text/plain",
            "source_origin": "manual_text",
            "raw_file_path": "",
            "char_count": len(request.text),
        },
        quality=_manual_text_quality(request.text),
    )
    try:
        return await _ingest_parsed_result(parsed, content_type="text/plain", raw_file_path="")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/ingest/file")
async def ingest_file(file: UploadFile = File(...)):
    ocr = _build_ocr_client()
    try:
        result = await _ingest_upload_file(file, ocr)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result["chunks"] > 0:
        runtime.last_updated = datetime.now().isoformat()
    return {
        "status": result["status"],
        "chunks": result["chunks"],
        "source_name": result["source_name"],
        "chunk_ids": result["chunk_ids"],
        "raw_file_path": result.get("raw_file_path", ""),
        "quality": result.get("quality"),
    }


@app.post("/api/ingest/files")
async def ingest_files(files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="files are required")
    ocr = _build_ocr_client()
    results = []
    succeeded = 0
    skipped = 0
    failed = 0
    total_chunks = 0
    for file in files:
        filename = Path(file.filename or "upload").name
        try:
            result = await _ingest_upload_file(file, ocr)
            if result.get("status") == "skipped":
                skipped += 1
            else:
                succeeded += 1
                total_chunks += result["chunks"]
            results.append({"filename": filename, **result})
        except HTTPException as exc:
            failed += 1
            detail = exc.detail if isinstance(exc.detail, dict) else {"reason": str(exc.detail)}
            results.append({
                "filename": filename,
                "content_type": file.content_type,
                "status": "error",
                "error": detail.get("reason", str(exc.detail)),
                "quality": detail.get("quality"),
            })
        except Exception as exc:
            failed += 1
            results.append({
                "filename": filename,
                "content_type": file.content_type,
                "status": "error",
                "error": str(exc),
            })
    if total_chunks > 0:
        runtime.last_updated = datetime.now().isoformat()
    return {
        "status": "ok" if failed == 0 and skipped == 0 else "partial",
        "total_files": len(files),
        "succeeded": succeeded,
        "skipped": skipped,
        "failed": failed,
        "total_chunks": total_chunks,
        "files": results,
    }


def _build_ocr_client():
    return build_ocr_provider_chain(runtime.config)


async def _ingest_upload_file(file: UploadFile, ocr):
    raw_dir = Path(runtime.config["data_dir"]) / "raw" / datetime.now().strftime("%Y-%m-%d")
    raw_dir.mkdir(parents=True, exist_ok=True)
    output_path = raw_dir / Path(file.filename or "upload").name
    output_path = _dedupe_upload_path(output_path)
    with output_path.open("wb") as output:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
    parsed = await parse_file(str(output_path), mime_type=file.content_type, ocr_client=ocr)
    raw_file_path = str(output_path.relative_to(Path(runtime.config["data_dir"])))
    quality = parsed.quality
    if quality is not None and quality.status == "needs_ocr":
        return _skipped_ingest_result(
            parsed,
            file.content_type,
            raw_file_path,
            replace(quality, action="needs_ocr_skipped"),
        )
    return await _ingest_parsed_result(
        parsed,
        content_type=file.content_type,
        raw_file_path=raw_file_path,
        provider=locals().get("ocr_provider", ""),
        attempts=locals().get("ocr_attempts", []),
        ocr_result=locals().get("ocr_result_meta"),
    )


async def _ingest_parsed_result(
    parsed,
    *,
    content_type: str = "",
    raw_file_path: str = "",
    provider: str = "",
    attempts=None,
    ocr_result=None,
):
    chunks = _chunk(parsed.text, parsed.source_name, parsed.source_type)
    pre_chunks = getattr(parsed, "pre_chunks", [])
    chunks.extend(_pre_chunk_records(pre_chunks))
    if not chunks:
        raise ValueError("no indexable content")
    _enforce_sync_chunk_limit(len(chunks), parsed.source_name)
    count = runtime.indexer.upsert(chunks, raw_file_paths=[raw_file_path] * len(chunks))
    runtime.last_updated = datetime.now().isoformat()
    org_chart_pages = [record.metadata.get("page") for record in pre_chunks if getattr(record, "metadata", None)]
    quality_payload = _quality_payload(
        parsed.quality,
        provider=provider,
        attempts=attempts or [],
        ocr_result=ocr_result,
    )
    if quality_payload is not None and pre_chunks:
        quality_payload["org_chart_chunks"] = len(pre_chunks)
        quality_payload["org_chart_pages"] = org_chart_pages
        quality_payload["org_chart_mode"] = "pdf_layout_fallback"
    return {
        "status": "ok",
        "chunks": count,
        "source_name": parsed.source_name,
        "source_type": parsed.source_type,
        "content_type": content_type,
        "raw_file_path": raw_file_path,
        "org_chart_chunks": len(pre_chunks),
        "chunk_ids": [chunk.id for chunk in chunks],
        "quality": quality_payload,
    }


def _quality_payload(quality, provider="", attempts=None, ocr_result=None):
    if quality is None:
        return None
    payload = {
        "status": quality.status,
        "action": quality.action,
        "valid_ratio": quality.valid_ratio,
        "short_line_ratio": quality.short_line_ratio,
        "watermark_ratio": quality.watermark_ratio,
        "unique_line_ratio": quality.unique_line_ratio,
        "non_empty_pages": quality.non_empty_pages,
        "page_count": quality.page_count,
        "non_empty_page_ratio": quality.non_empty_page_ratio,
        "effective_chars_per_page": quality.effective_chars_per_page,
        "cleaned_chars_ratio": quality.cleaned_chars_ratio,
        "reasons": quality.reasons,
    }
    if provider:
        payload["provider"] = provider
    if attempts:
        payload["attempts"] = _attempts_payload(attempts)
    if ocr_result is not None:
        payload["source_page_count"] = ocr_result.source_page_count
        payload["ocr_pages_processed"] = ocr_result.pages_processed
        payload["ocr_page_limit_reached"] = ocr_result.page_limit_reached
        payload["ocr_partial"] = ocr_result.partial
    return payload


def _manual_text_quality(text: str) -> ParseQuality:
    char_count = len(text.strip())
    return ParseQuality(
        status="high",
        action="direct",
        valid_ratio=1.0,
        short_line_ratio=0.0,
        watermark_ratio=0.0,
        unique_line_ratio=1.0,
        non_empty_pages=1 if char_count else 0,
        page_count=1 if char_count else 0,
        non_empty_page_ratio=1.0 if char_count else 0.0,
        effective_chars_per_page=float(char_count),
        cleaned_chars_ratio=1.0 if char_count else 0.0,
        reasons=[],
    )


def _max_sync_chunks_per_file() -> int:
    ingest_config = runtime.config.get("ingest", {})
    return int(ingest_config.get("max_sync_chunks_per_file", 100) or 100)


def _enforce_sync_chunk_limit(chunk_count: int, source_name: str) -> None:
    limit = _max_sync_chunks_per_file()
    if chunk_count <= limit:
        return
    reason = f"文件 {source_name} 切分后产生 {chunk_count} 个片段，超过单次同步入库上限 {limit}，已阻止入库"
    raise HTTPException(
        status_code=413,
        detail={
            "status": "error",
            "action": "too_large_skipped",
            "source_name": source_name,
            "chunks": chunk_count,
            "limit": limit,
            "reason": reason,
            "quality": {
                "status": "too_large",
                "action": "too_large_skipped",
                "reasons": [reason],
            },
        },
    )


def _skipped_ingest_result(parsed, content_type, raw_file_path, quality):
    return {
        "status": "skipped",
        "chunks": 0,
        "source_name": parsed.source_name,
        "content_type": content_type,
        "raw_file_path": raw_file_path,
        "chunk_ids": [],
        "quality": _quality_payload(quality),
    }


def _attempts_payload(attempts):
    return [
        {
            "provider": attempt.provider,
            "status": attempt.status,
            "error": attempt.error,
        }
        for attempt in attempts
    ]


def _dedupe_upload_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 1000):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem}-{datetime.now().strftime('%H%M%S%f')}{suffix}")


@app.post("/api/ingest/clear")
async def clear_knowledge():
    runtime.indexer.clear_all()
    runtime.last_updated = datetime.now().isoformat()
    return {"status": "ok", "message": "知识库已清空"}


@app.post("/api/query")
async def query(request: QueryRequest):
    retriever = HybridRetriever(
        indexer=runtime.indexer,
        fts5_top_k=runtime.config["retrieval"]["fts5_top_k"],
        vector_top_k=runtime.config["retrieval"]["vector_top_k"],
        rrf_k=runtime.config["retrieval"]["rrf_k"],
    )
    chunks = retriever.hybrid_search(request.question, runtime.config["retrieval"]["final_top_k"])
    generator = generate_answer(
        question=request.question,
        chunks=chunks,
        language=request.language,
        deepseek_endpoint=runtime.config["deepseek"]["endpoint"],
        deepseek_api_key=runtime.config["deepseek"]["api_key"],
        deepseek_model=runtime.config["deepseek"]["model"],
        generation_endpoint=runtime.config["generation"]["endpoint"],
        generation_api_key=runtime.config["generation"]["api_key"],
        generation_model=runtime.config["generation"]["model"],
    )
    return StreamingResponse(generator, media_type="text/event-stream")


@app.post("/api/export/word")
async def export_word(request: ExportRequest):
    output_dir = Path(runtime.config["data_dir"]) / "exports"
    output_path = output_dir / f"pka_answer_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    path = export_to_word(request.question, request.answer, request.sources, str(output_path))
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=Path(path).name,
    )


@app.post("/api/export/ppt")
async def export_ppt(request: ExportRequest):
    output_dir = Path(runtime.config["data_dir"]) / "exports"
    output_path = output_dir / f"pka_answer_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pptx"
    try:
        path = export_to_quality_ppt(request.question, request.answer, request.sources, str(output_path), runtime.config)
    except Exception:
        path = export_to_ppt(request.question, request.answer, request.sources, str(output_path))
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=Path(path).name,
    )


@app.get("/api/stats")
async def stats():
    return {
        "indexed_files": runtime.indexer.count_sources(),
        "total_chunks": runtime.indexer.count_chunks(),
        "last_updated": runtime.last_updated,
    }


@app.get("/api/config")
async def get_config():
    return sanitize_config(runtime.config)


@app.post("/api/config")
async def post_config(payload: Dict[str, Any]):
    updated = update_config(runtime.config, payload)
    save_config(updated, CONFIG_PATH)
    runtime.reload(updated)
    return sanitize_config(runtime.config)


@app.get("/api/sources/{chunk_id:path}")
async def get_source(chunk_id: str):
    return _source_payload(chunk_id)


@app.get("/api/sources")
async def get_source_by_query(chunk_id: str, request: Request):
    payload = _source_payload(chunk_id)
    accept = request.headers.get("accept", "")
    if "text/html" not in accept:
        return payload
    source_label = _display_source_name(payload["source_name"])
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>来源片段</title>
  <style>
    body {{ margin: 0; padding: 24px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #243746; background: #f6fbfd; }}
    main {{ max-width: 880px; margin: 0 auto; }}
    h1 {{ font-size: 20px; margin: 0 0 8px; }}
    .meta {{ color: #607789; margin-bottom: 16px; }}
    pre {{ white-space: pre-wrap; line-height: 1.65; padding: 16px; border: 1px solid #cfdde5; background: #fff; border-radius: 8px; }}
  </style>
</head>
<body>
  <main>
    <h1>来源片段</h1>
    <div class="meta">{escape(source_label)} · 第 {payload["chunk_index"]} 段</div>
    <pre>{escape(payload["text"])}</pre>
  </main>
</body>
</html>"""
    return HTMLResponse(html)


@app.get("/api/files/{raw_path:path}")
async def serve_raw_file(raw_path: str):
    data_dir = Path(runtime.config["data_dir"]).resolve()
    full_path = (data_dir / raw_path).resolve()
    try:
        full_path.relative_to(data_dir)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="access denied") from exc
    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(full_path, filename=full_path.name)


@app.post("/api/test-connection")
async def test_connection():
    checks = [
        _configured_check(
            "deepseek",
            "DeepSeek 中文语义分析",
            runtime.config.get("deepseek", {}),
            ("endpoint", "api_key", "model"),
            "用于中文语义分析与问答结构化理解。",
        ),
        _ocr_check(),
        _embedding_check(),
    ]
    statuses = {check["status"] for check in checks}
    status = "error" if "error" in statuses else "partial" if "warn" in statuses else "ok"
    return JSONResponse({"status": status, "checks": checks})


def _ocr_check() -> Dict[str, str]:
    config = runtime.config.get("ocr", {})
    volcengine = config.get("volcengine", {}) if isinstance(config.get("volcengine", {}), dict) else {}
    provider_order = config.get("provider_order", ["paddle", "volcengine"])
    provider_label = " -> ".join(str(provider) for provider in provider_order)
    try:
        chain = build_ocr_provider_chain(runtime.config)
        available_providers = [provider.name for provider in chain.providers if provider.available()]
    except Exception:
        available_providers = []
    if available_providers:
        details = [f"Provider 顺序: {provider_label}"]
        if "paddle" in available_providers:
            details.append("PaddleOCR 本地可用")
        if "volcengine" in available_providers:
            model = volcengine.get("model") or config.get("model", "")
            details.append(f"Volcengine 模型 {model} 已配置")
        return {
            "id": "ocr",
            "label": "OCR 图片解析",
            "status": "ok",
            "detail": "；".join(details) + "。",
        }
    endpoint = volcengine.get("endpoint") or config.get("endpoint", "")
    api_key = volcengine.get("api_key") or config.get("api_key", "")
    model = volcengine.get("model") or config.get("model", "")
    if endpoint and api_key and model:
        return {
            "id": "ocr",
            "label": "OCR 图片解析",
            "status": "ok",
            "detail": f"Provider 顺序: {provider_label}；Volcengine 模型 {model} 已配置。",
        }
    missing = [
        name
        for name, value in [("endpoint", endpoint), ("api_key", api_key), ("model", model)]
        if not value
    ]
    return {
        "id": "ocr",
        "label": "OCR 图片解析",
        "status": "warn",
        "detail": f"未配置 Volcengine OCR ({', '.join(missing)})；PaddleOCR 未安装或不可用时，扫描 PDF 将跳过入库。",
    }


def _configured_check(
    check_id: str,
    label: str,
    config: Dict[str, Any],
    required_keys: tuple[str, ...],
    ok_detail: str,
    missing_status: str = "error",
) -> Dict[str, str]:
    missing = [key for key in required_keys if not str(config.get(key) or "").strip()]
    if missing:
        return {
            "id": check_id,
            "label": label,
            "status": missing_status,
            "detail": f"未配置 {', '.join(missing)}。",
        }
    model = str(config.get("model") or "").strip()
    return {
        "id": check_id,
        "label": label,
        "status": "ok",
        "detail": f"{model} 已配置；{ok_detail}",
    }


def _embedding_check() -> Dict[str, str]:
    config = runtime.config.get("embedding", {})
    model = str(config.get("model") or "bge-m3").strip() or "bge-m3"
    try:
        vector = runtime.indexer.embedding_client.embed(["连接测试"])[0]
    except Exception as exc:
        return {
            "id": "embedding",
            "label": "bge-m3 向量检索",
            "status": "error",
            "detail": f"Ollama / {model} 不可用：{exc}",
        }
    return {
        "id": "embedding",
        "label": "bge-m3 向量检索",
        "status": "ok",
        "detail": f"Ollama / {model} 可用，返回 {len(vector)} 维向量。",
    }


def _chunk(text: str, source_name: str, source_type: str):
    return chunk_text(
        text,
        source_name,
        source_type,
        max_chunk_size=runtime.config["chunking"]["max_chunk_size"],
        chunk_overlap=runtime.config["chunking"]["chunk_overlap"],
    )


def _pre_chunk_records(records):
    created_at = datetime.now().astimezone().isoformat()
    chunks = []
    for index, record in enumerate(records):
        if not getattr(record, "is_pre_chunked", False):
            continue
        text = record.text
        chunks.append(
            Chunk(
                id=f"{record.source_name}#org_chart_{index}",
                text=text,
                source_name=record.source_name,
                source_type=record.source_type,
                chunk_index=index,
                created_at=created_at,
                embedding_text=text,
            )
        )
    return chunks


def _source_payload(chunk_id: str) -> dict:
    chunk = runtime.indexer.get_chunk(chunk_id)
    if not chunk and "#" not in chunk_id:
        chunk_id = f"{chunk_id}#0"
        chunk = runtime.indexer.get_chunk(chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="chunk not found")
    return {
        "chunk_id": chunk_id,
        "text": chunk["text"],
        "source_name": chunk["source_name"],
        "source_type": chunk["source_type"],
        "chunk_index": chunk["chunk_index"],
        "raw_file_path": chunk.get("raw_file_path", ""),
    }


def _display_source_name(source_name: str) -> str:
    if source_name.startswith("manual_") and len(source_name) == len("manual_YYYYMMDD_HHMMSS"):
        time = source_name.rsplit("_", 1)[-1]
        return f"手动录入 {time[:2]}:{time[2:4]}"
    return source_name


def _read_static(name: str) -> str:
    return (Path("static") / name).read_text(encoding="utf-8")


def _html(name: str) -> HTMLResponse:
    return HTMLResponse(_read_static(name), headers={"Cache-Control": "no-store"})
