# Agent06 PKA Core Engineering Audit Snapshot
Generated at: Sun Jun 28 15:32:57 CST 2026

## 1. API Routes & Ingestion Controllers
### File: ./server.py
```python
import asyncio
import json
import threading
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine.chunker import chunk_text
from engine.config import load_config, sanitize_config, save_config, update_config
from engine.exporter import export_to_ppt, export_to_word
from engine.generator import generate_answer
from engine.indexer import HybridIndexer, OllamaEmbeddingClient
from engine.models import Chunk, ParseQuality, ParseResult
from engine.ocr import build_ocr_provider_chain
from engine.parser import parse_file, parse_text
from engine.ppt_maker_adapter import export_to_quality_ppt
from engine.retriever import HybridRetriever


CONFIG_PATH = Path("config.yaml")


@asynccontextmanager
async def lifespan(app_instance):
    recover_queued_ocr_tasks()
    yield


app = FastAPI(title="PKA", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
ingest_lock = threading.Lock()
ocr_executor = ThreadPoolExecutor(max_workers=1)


class OcrTaskStore:
    def __init__(self, data_dir: str):
        self.tasks_dir = Path(data_dir) / "runtime" / "tasks"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def create_task(
        self,
        *,
        file_name: str,
        raw_file_path: str,
        content_type: str = "",
        page_count: int = 0,
    ) -> str:
        task_id = f"ocr_task_{uuid4().hex[:12]}"
        payload = {
            "task_id": task_id,
            "status": "queued",
            "file_name": file_name,
            "raw_file_path": raw_file_path,
            "content_type": content_type,
            "page_count": page_count,
            "progress": 0,
            "result": {
                "chunks_inserted": 0,
                "quality_action": None,
                "error": None,
            },
        }
        self.save_task(task_id, payload)
        return task_id

    def get_task(self, task_id: str) -> Optional[dict]:
        path = self.tasks_dir / f"{task_id}.json"
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as source:
            return json.load(source)

    def update_task(self, task_id: str, updates: dict) -> Optional[dict]:
        with self.lock:
            task = self.get_task(task_id)
            if task is None:
                return None
            task.update(updates)
            self.save_task(task_id, task)
            return task

    def save_task(self, task_id: str, payload: dict) -> None:
        path = self.tasks_dir / f"{task_id}.json"
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=False, indent=2)
        tmp_path.replace(path)

    def list_tasks(self) -> list[dict]:
        tasks = []
        for path in sorted(self.tasks_dir.glob("*.json")):
            with path.open("r", encoding="utf-8") as source:
                tasks.append(json.load(source))
        return tasks


class TextIngestRequest(BaseModel):
    text: str


class QueryRequest(BaseModel):
    question: str
    language: str = "zh"
    debug: bool = False


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
async def ingest_file(file: UploadFile = File(...), org_chart_mode: str = Form("disabled")):
    ocr = _build_ocr_client()
    try:
        result = await _ingest_upload_file(file, ocr, extract_org_charts=_is_org_chart_mode_enabled(org_chart_mode))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result["status"] == "accepted":
        if ocr is not None:
            ocr_executor.submit(run_ocr_task_once, result["task_id"], ocr)
        return JSONResponse(
            status_code=202,
            content={
                "status": "accepted",
                "task_id": result["task_id"],
                "file_name": result["file_name"],
                "message": "文件需要重型 OCR 解析，已成功提交至后台异步队列进行处理。",
            },
        )
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


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    task = _ocr_task_store().get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@app.post("/api/ingest/files")
async def ingest_files(files: list[UploadFile] = File(...), org_chart_modes: Optional[list[str]] = Form(None)):
    if not files:
        raise HTTPException(status_code=400, detail="files are required")
    ocr = _build_ocr_client()
    results = []
    succeeded = 0
    accepted = 0
    skipped = 0
    failed = 0
    total_chunks = 0
    modes = org_chart_modes if isinstance(org_chart_modes, list) else []
    for index, file in enumerate(files):
        filename = Path(file.filename or "upload").name
        try:
            result = await _ingest_upload_file(
                file,
                ocr,
                extract_org_charts=_is_org_chart_mode_enabled(modes[index] if index < len(modes) else "disabled"),
            )
            if result.get("status") == "accepted":
                accepted += 1
                if ocr is not None:
                    ocr_executor.submit(run_ocr_task_once, result["task_id"], ocr)
            elif result.get("status") == "skipped":
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
    response_payload = {
        "status": "ok" if failed == 0 and skipped == 0 else "partial",
        "total_files": len(files),
        "succeeded": succeeded,
        "accepted": accepted,
        "skipped": skipped,
        "failed": failed,
        "total_chunks": total_chunks,
        "files": results,
    }
    if accepted:
        response_payload["status"] = "accepted" if failed == 0 else "partial"
        return JSONResponse(status_code=202, content=response_payload)
    return response_payload


def _is_org_chart_mode_enabled(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"enabled", "true", "1", "yes", "on"}


def _build_ocr_client():
    return build_ocr_provider_chain(runtime.config)


def _ocr_task_store() -> OcrTaskStore:
    return OcrTaskStore(runtime.config["data_dir"])


def recover_queued_ocr_tasks(executor=None) -> dict:
    store = _ocr_task_store()
    executor = executor or ocr_executor
    summary = {"requeued": 0, "failed": 0}
    for task in store.list_tasks():
        if task.get("status") not in {"queued", "processing"}:
            continue
        task_id = task["task_id"]
        raw_path = Path(runtime.config["data_dir"]) / task.get("raw_file_path", "")
        if raw_path.exists():
            store.update_task(
                task_id,
                {
                    "status": "queued",
                    "progress": 0,
                    "result": {
                        "chunks_inserted": 0,
                        "quality_action": None,
                        "error": None,
                    },
                },
            )
            executor.submit(run_ocr_task_once, task_id)
            summary["requeued"] += 1
        else:
            store.update_task(
                task_id,
                {
                    "status": "failed",
                    "progress": 100,
                    "result": {
                        "chunks_inserted": 0,
                        "quality_action": "ocr",
                        "error": "raw file is missing",
                    },
                },
            )
            summary["failed"] += 1
    return summary


async def _ingest_upload_file(file: UploadFile, ocr, extract_org_charts: bool = False):
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
    parsed = await parse_file(
        str(output_path),
        mime_type=file.content_type,
        ocr_client=ocr,
        extract_org_charts=extract_org_charts,
    )
    raw_file_path = str(output_path.relative_to(Path(runtime.config["data_dir"])))
    quality = parsed.quality
    if quality is not None and quality.status == "needs_ocr":
        task_id = _ocr_task_store().create_task(
            file_name=Path(file.filename or parsed.source_name).name,
            raw_file_path=raw_file_path,
            content_type=file.content_type or "",
            page_count=int(parsed.metadata.get("page_count", 0) or 0),
        )
        return {
            "status": "accepted",
            "task_id": task_id,
            "file_name": Path(file.filename or parsed.source_name).name,
            "chunks": 0,
            "source_name": parsed.source_name,
            "chunk_ids": [],
            "raw_file_path": raw_file_path,
            "quality": _quality_payload(replace(quality, action="needs_ocr_queued")),
        }
    return await _ingest_parsed_result(
        parsed,
        content_type=file.content_type,
        raw_file_path=raw_file_path,
        provider=locals().get("ocr_provider", ""),
        attempts=locals().get("ocr_attempts", []),
        ocr_result=locals().get("ocr_result_meta"),
    )


def run_ocr_task_once(task_id: str, ocr_chain=None) -> None:
    store = _ocr_task_store()
    task = store.get_task(task_id)
    if task is None:
        return
    store.update_task(task_id, {"status": "processing", "progress": 10})
    try:
        chain = ocr_chain or _build_ocr_client()
        if chain is None:
            raise RuntimeError("OCR provider chain is not configured")
        raw_path = Path(runtime.config["data_dir"]) / task["raw_file_path"]
        ocr_result = _run_coroutine_sync(
            chain.extract_pdf_until_usable(
                str(raw_path),
                page_count=int(task.get("page_count", 0) or 0),
                max_pages=int(runtime.config.get("ocr", {}).get("max_pdf_pages", 10) or 10),
            )
        )
        if ocr_result is None:
            raise RuntimeError("OCR did not produce usable text")
        quality = replace(ocr_result.quality, action="ocr") if ocr_result.quality is not None else None
        parsed = ParseResult(
            text=ocr_result.text,
            source_name=task["file_name"],
            source_type="pdf",
            metadata={
                "page_count": ocr_result.source_page_count,
                "non_empty_pages": ocr_result.pages_processed,
                "quality_status": quality.status if quality else "",
                "quality_action": quality.action if quality else "",
            },
            quality=quality,
        )
        ingest_result = _run_coroutine_sync(
            _ingest_parsed_result(
                parsed,
                content_type=task.get("content_type", "application/pdf"),
                raw_file_path=task["raw_file_path"],
                provider=ocr_result.provider,
                attempts=ocr_result.attempts,
                ocr_result=ocr_result,
            )
        )
        store.update_task(
            task_id,
            {
                "status": "completed",
                "progress": 100,
                "result": {
                    "chunks_inserted": ingest_result["chunks"],
                    "quality_action": "ocr",
                    "error": None,
                },
            },
        )
    except Exception as exc:
        store.update_task(
            task_id,
            {
                "status": "failed",
                "progress": 100,
                "result": {
                    "chunks_inserted": 0,
                    "quality_action": "ocr",
                    "error": str(exc),
                },
            },
        )


def _run_coroutine_sync(coroutine):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    raise RuntimeError("run_ocr_task_once cannot run inside an active event loop")


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
    with ingest_lock:
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
    with ingest_lock:
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
    debug_payload = None
    if request.debug:
        chunks, debug_payload = retriever.hybrid_search_with_debug(
            request.question,
            runtime.config["retrieval"]["final_top_k"],
        )
    else:
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
        debug_payload=debug_payload,
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
```

## 2. RAG Engine Component Source Implementations
### File: ./engine/reranker.py
```python
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class RerankResult:
    chunk_id: str
    score: float


class RerankerClient:
    def rerank(self, query: str, candidates: List[Dict[str, Any]]) -> List[RerankResult]:
        raise NotImplementedError
```

### File: ./engine/parser.py
```python
import mimetypes
from pathlib import Path
import re
from typing import Any, Optional

from engine.models import ParseResult, PreChunkedParseRecord
from engine.org_chart import (
    PdfTextBlock,
    generate_projection_text,
    infer_layout_hierarchy,
    merge_pdf_blocks,
    select_org_chart_title,
)


TEXT_TYPES = {".txt": "txt", ".md": "md"}
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp"}
ORG_CHART_MAX_PRE_CHUNK_CHARS = 3500


def parse_text(text: str, source_name: str = "manual_input") -> ParseResult:
    return ParseResult(
        text=text,
        source_name=source_name,
        source_type="text",
        metadata={"input": "manual"},
    )


async def parse_file(
    file_path: str,
    mime_type: Optional[str] = None,
    ocr_client: Any = None,
    extract_org_charts: bool = False,
) -> ParseResult:
    path = Path(file_path)
    suffix = path.suffix.lower()
    detected_mime = mime_type or mimetypes.guess_type(str(path))[0] or ""

    try:
        if suffix in TEXT_TYPES:
            return ParseResult(
                text=path.read_text(encoding="utf-8"),
                source_name=path.name,
                source_type=TEXT_TYPES[suffix],
                metadata={"mime_type": detected_mime},
            )
        if suffix == ".docx":
            return _parse_docx(path)
        if suffix == ".pptx":
            return _parse_pptx(path)
        if suffix == ".pdf":
            return _parse_pdf(path, extract_org_charts=extract_org_charts)
        if suffix == ".xlsx":
            return _parse_xlsx(path)
        if suffix in IMAGE_TYPES or detected_mime.startswith("image/"):
            from engine.quality import assess_image_ocr_quality

            if ocr_client is None:
                raise ValueError("OCR client is required for image parsing")
            text = await ocr_client.extract([str(path)])
            if not str(text or "").strip():
                raise ValueError("OCR produced no usable text for image")
            return ParseResult(
                text=text,
                source_name=path.name,
                source_type="image",
                metadata={"ocr": True, "mime_type": detected_mime},
                quality=assess_image_ocr_quality(text),
            )
    except ValueError:
        raise
    except RuntimeError:
        raise
    except Exception as exc:
        raise ValueError(f"Failed to parse {path.name}: {exc}") from exc

    raise ValueError(f"Unsupported file type: {path.suffix or detected_mime}")


def _parse_docx(path: Path) -> ParseResult:
    import docx

    document = docx.Document(path)
    paragraphs = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    return ParseResult(
        text="\n".join(paragraphs),
        source_name=path.name,
        source_type="docx",
        metadata={"paragraph_count": len(paragraphs)},
    )


def _parse_pptx(path: Path) -> ParseResult:
    import pptx

    presentation = pptx.Presentation(path)
    texts = []
    for slide_number, slide in enumerate(presentation.slides, start=1):
        slide_texts = []
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text.strip():
                slide_texts.append(shape.text.strip())
        if slide_texts:
            texts.append(f"## Slide {slide_number}\n" + "\n".join(slide_texts))
    return ParseResult(
        text="\n\n".join(texts),
        source_name=path.name,
        source_type="pptx",
        metadata={"slide_count": len(presentation.slides)},
    )


def _parse_pdf(path: Path, extract_org_charts: bool = False) -> ParseResult:
    import fitz
    from engine.quality import assess_pdf_quality, clean_pdf_text

    document = fitz.open(path)
    pages = []
    pre_chunks = []
    try:
        for page_number, page in enumerate(document, start=1):
            page_text = page.get_text().strip()
            raw_blocks = page.get_text("blocks")
            if page_text:
                blocks = _pdf_text_blocks(raw_blocks, page_number)
                if extract_org_charts and _detect_org_chart_page(page_text, blocks):
                    pre_chunks.extend(
                        _org_chart_pre_chunks(
                            source_name=path.name,
                            page_number=page_number,
                            page_text=page_text,
                            blocks=blocks,
                            page_height=_page_height(page, blocks),
                        )
                    )
                    continue
                pages.append(page_text)
        page_count = document.page_count
    finally:
        document.close()
    raw_text = "\n\n".join(pages)
    cleaned_text = clean_pdf_text(raw_text, page_texts=pages, page_count=page_count)
    quality = assess_pdf_quality(raw_text, cleaned_text, page_count, len(pages))
    return ParseResult(
        text=cleaned_text,
        source_name=path.name,
        source_type="pdf",
        metadata={
            "page_count": page_count,
            "non_empty_pages": len(pages),
            "quality_status": quality.status,
            "quality_action": quality.action,
            "org_chart_pages": [record.metadata["page"] for record in pre_chunks],
            "org_chart_chunks": len(pre_chunks),
            "org_chart_mode": "pdf_layout_fallback" if pre_chunks else "",
        },
        quality=quality,
        pre_chunks=pre_chunks,
    )


def _parse_xlsx(path: Path) -> ParseResult:
    import openpyxl

    workbook = openpyxl.load_workbook(path, data_only=True)
    sections = []
    for sheet in workbook.worksheets:
        rows = [[_cell_to_text(cell) for cell in row] for row in sheet.iter_rows(values_only=True)]
        rows = [row for row in rows if any(cell for cell in row)]
        if not rows:
            continue
        width = max(len(row) for row in rows)
        normalized = [row + [""] * (width - len(row)) for row in rows]
        header = normalized[0]
        body = normalized[1:]
        table = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(["---"] * width) + " |",
        ]
        table.extend("| " + " | ".join(row) + " |" for row in body)
        sections.append(f"## Sheet: {sheet.title}\n" + "\n".join(table))
    return ParseResult(
        text="\n\n".join(sections),
        source_name=path.name,
        source_type="xlsx",
        metadata={"sheet_count": len(workbook.worksheets)},
    )


def _cell_to_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _pdf_text_blocks(raw_blocks, page_number: int) -> list[PdfTextBlock]:
    blocks = []
    for raw in raw_blocks or []:
        if len(raw) < 5:
            continue
        x0, y0, x1, y1, text = raw[:5]
        cleaned = str(text).strip()
        if not cleaned:
            continue
        blocks.append(
            PdfTextBlock(
                text=cleaned,
                x0=float(x0),
                y0=float(y0),
                x1=float(x1),
                y1=float(y1),
                font_size=max(1.0, min(18.0, float(y1) - float(y0))),
                page=page_number,
            )
        )
    return blocks


def _page_height(page, blocks: list[PdfTextBlock]) -> float:
    rect = getattr(page, "rect", None)
    height = getattr(rect, "height", None)
    if height:
        return float(height)
    return max((block.y1 for block in blocks), default=0.0)


def _detect_org_chart_page(page_text: str, blocks: list[PdfTextBlock]) -> bool:
    normalized = page_text.upper()
    if re.search(r"\bORG(?:ANISATION|ANIZATION)?\s+CHART\b", normalized):
        return True
    if _looks_like_document_table_or_code_page(page_text, blocks):
        return False
    short_blocks = [block for block in blocks if len(block.text) <= 32]
    if len(short_blocks) < 12:
        return False
    y_bands = _count_y_bands(short_blocks)
    x_centers = {round(block.x_center / 80) for block in short_blocks}
    short_ratio = len(short_blocks) / max(len(blocks), 1)
    return short_ratio >= 0.65 and y_bands >= 3 and len(x_centers) >= 3


def _looks_like_document_table_or_code_page(page_text: str, blocks: list[PdfTextBlock]) -> bool:
    text = page_text.strip()
    normalized = text.upper()
    compact_lines = [line.strip() for line in text.splitlines() if line.strip()]
    block_texts = [block.text.strip() for block in blocks if block.text.strip()]
    combined_blocks = "\n".join(block_texts)

    table_markers = ["参数名称", "默认值", "描述", "类型", "输入列名", "输出", "说明"]
    if sum(1 for marker in table_markers if marker in text or marker in combined_blocks) >= 3:
        return True

    itinerary_markers = ["每日行程", "日期", "核心路线", "里程", "驾车时长", "行程亮点", "机场", "酒店"]
    if sum(1 for marker in itinerary_markers if marker in text or marker in combined_blocks) >= 4:
        return True

    travel_prep_markers = ["出行时间", "出行人数", "核心路线", "行前准备", "离线地图", "衣物储备", "随车物品", "预约状态"]
    if sum(1 for marker in travel_prep_markers if marker in text or marker in combined_blocks) >= 4:
        return True

    milestone_markers = ["开发计划", "阶段", "里程碑", "周期", "目标", "关键交付物", "GO/NO-GO", "BOM", "RFQ"]
    if sum(1 for marker in milestone_markers if marker in text or marker in normalized) >= 4:
        return True

    code_markers = ["PYTHON", "DF.WITH_COLUMN", "IMPORT ", "RETURN ", "COL(", "ARKLLMVISIONUNDERSTANDING"]
    if sum(1 for marker in code_markers if marker in normalized) >= 2:
        return True

    toc_markers = ["目录", "文档控制", "修订摘要", "执行摘要", "附录", "BOM", "验收方法"]
    numbered_lines = sum(1 for line in compact_lines if re.match(r"^(?:\d+\.|附录\s*[A-ZＡ-Ｚ]?\b)", line))
    if ("目录" in text or "TABLE OF CONTENTS" in normalized) and numbered_lines >= 3:
        return True
    if sum(1 for marker in toc_markers if marker in text or marker in normalized) >= 3 and numbered_lines >= 2:
        return True

    bullet_or_table_rows = sum(
        1
        for line in compact_lines
        if line.startswith(("•", "◦", "▪", "-", "")) or re.match(r"^[A-Za-z0-9_]+\s+(?:str|int|float|bool|list|dict)\b", line)
    )
    if bullet_or_table_rows >= 5 and any(marker in text for marker in ("参数", "默认", "说明", "输入", "输出")):
        return True

    return False


def _count_y_bands(blocks: list[PdfTextBlock], tolerance: float = 10.0) -> int:
    bands: list[float] = []
    for block in sorted(blocks, key=lambda item: item.y_center):
        for index, center in enumerate(bands):
            if abs(block.y_center - center) <= tolerance:
                bands[index] = (center + block.y_center) / 2
                break
        else:
            bands.append(block.y_center)
    return len(bands)


def _org_chart_pre_chunks(
    *,
    source_name: str,
    page_number: int,
    page_text: str,
    blocks: list[PdfTextBlock],
    page_height: float,
) -> list[PreChunkedParseRecord]:
    title, cleaned_blocks = select_org_chart_title(blocks, page_height)
    candidate_blocks = cleaned_blocks or blocks
    nodes = merge_pdf_blocks(candidate_blocks)
    edges = infer_layout_hierarchy(nodes)
    projection = generate_projection_text(
        source_name=source_name,
        source_page=page_number,
        title=title,
        extraction_mode="pdf_layout_fallback",
        confidence="medium",
        nodes=nodes,
        edges=edges,
        warnings=[
            "native_pptx_unavailable",
            "connector_relationships_inferred",
            "cross_page_links_not_supported_v1",
        ],
    )
    if len(projection) <= ORG_CHART_MAX_PRE_CHUNK_CHARS:
        return [
            _pre_chunk_record(
                text=projection,
                source_name=source_name,
                page_number=page_number,
                part_index=1,
            )
        ]
    return [
        _pre_chunk_record(
            text=text,
            source_name=source_name,
            page_number=page_number,
            part_index=index,
        )
        for index, text in enumerate(
            _split_large_org_chart_projection(
                projection,
                source_name=source_name,
                page_number=page_number,
                title=title,
            ),
            start=1,
        )
    ]


def _pre_chunk_record(
    *, text: str, source_name: str, page_number: int, part_index: int
) -> PreChunkedParseRecord:
    return PreChunkedParseRecord(
        text=text,
        source_name=source_name,
        source_type="org_chart",
        is_pre_chunked=True,
        metadata={
            "page": page_number,
            "chart_id": f"{source_name}#page_{page_number}#chart_1_part_{part_index}",
            "confidence": "medium",
            "org_chart_mode": "pdf_layout_fallback",
        },
    )


def _split_large_org_chart_projection(
    projection: str, *, source_name: str, page_number: int, title: str
) -> list[str]:
    body_lines = [
        line
        for line in projection.splitlines()
        if line
        and not line.startswith("[ORG_CHART]")
        and not line.startswith("[/ORG_CHART]")
        and not line.startswith("Source:")
        and not line.startswith("Page:")
        and not line.startswith("Title:")
        and not line.startswith("Extraction mode:")
        and not line.startswith("Confidence:")
    ]
    chunks: list[str] = []
    current: list[str] = []
    for line in body_lines:
        candidate = current + [line]
        if current and len(_org_chart_subtree_text(source_name, page_number, title, candidate)) > ORG_CHART_MAX_PRE_CHUNK_CHARS:
            chunks.append(_org_chart_subtree_text(source_name, page_number, title, current))
            current = [line]
        else:
            current = candidate
    if current:
        chunks.append(_org_chart_subtree_text(source_name, page_number, title, current))
    return chunks


def _org_chart_subtree_text(
    source_name: str, page_number: int, title: str, body_lines: list[str]
) -> str:
    return "\n".join(
        [
            "[ORG_CHART_SUBTREE]",
            f"Source: {source_name}",
            f"Page: {page_number}",
            f"Context Root: {title}",
            "Confidence: medium",
            "",
            *body_lines,
            "[/ORG_CHART_SUBTREE]",
        ]
    )


def _org_chart_title(page_text: str) -> str:
    for line in page_text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return "ORG CHART"
```

### File: ./engine/generator.py
```python
import json
import re
from typing import Any, AsyncGenerator, Iterable, List, Optional

import httpx

from engine.models import RetrievedChunk


NO_ANSWER_CONSTRAINT = """如果参考内容中没有任何与该问题相关的信息，请只输出：
"当前知识库缺少相关信息，无法回答该问题。建议补充相关资料后重新提问。"
不要给出外部知识、推测或通用建议。"""


def build_prompt(question: str, chunks: List[RetrievedChunk]) -> str:
    references = []
    for index, chunk in enumerate(chunks, start=1):
        references.append(f"--- chunk_{index} (来源: {chunk.source_name})\n{chunk.text}")
    reference_text = "\n".join(references)
    return f"""你是一个个人知识库助手。用户积累了大量个人文档、笔记、面试复盘、项目报告等内容。
现在用户基于这些内容向你提问。你需要：

1. 仔细阅读所有 [参考内容] 片段
2. 综合分析这些片段中的信息
3. 如果信息充分，给出专业、具体的建议和回答
4. 如果某些方面的信息不足，请明确指出"当前知识库中缺少关于 XX 的信息"
5. 在回答末尾列出本次引用的来源文件

[参考内容]
{reference_text}

[用户问题]
{question}

请回答：
"""


def build_deepseek_analysis_prompt(
    question: str,
    chunks: List[RetrievedChunk],
    include_chinese_advice: bool = False,
    report_language: str = "zh",
) -> str:
    references = []
    for index, chunk in enumerate(chunks, start=1):
        references.append(
            f"--- chunk_{index}\n"
            f"source: {chunk.source_name}#{chunk.chunk_index}\n"
            f"text: {chunk.text}"
        )
    org_chart_instruction = _org_chart_grounding_instruction(chunks)
    if include_chinese_advice:
        return f"""你是一个个人知识库中文问答助手。用户给出了一个问题，以及从其个人资料库中检索到的相关材料。
请直接给用户一段自然、可读的中文个人建议，不要输出 JSON、代码块、字段名或调试结构。

回答要求：
1. 先给出核心结论
2. 再列出关键依据，依据必须来自参考内容
3. 给出具体、可执行的中文个人建议
4. 在回答末尾列出来源，格式为“来源：文件名#段落号”
5. 如果资料不足，明确说明当前知识库缺少哪些信息
{NO_ANSWER_CONSTRAINT}
{org_chart_instruction}

[参考内容]
{chr(10).join(references)}

[用户问题]
{question}

请用中文回答：
"""
    english_report_instruction = ""
    if report_language == "en":
        english_report_instruction = """
English Report mode:
- Write all report-facing JSON values in English.
- Translate Chinese source meaning into fluent English for key_facts.content and logic_chain.
- Keep language as the original source language marker: "zh" for Chinese source text and "en" for English source text.
- Keep terminology.zh in Chinese when relevant, but terminology.en must be natural English.
- Do not output Chinese prose in key_facts.content or logic_chain unless it is a proper noun, title, or unavoidable source term.
"""
    return f"""你是一个跨语言个人知识库分析助手。用户给出了一个问题，以及从其个人资料库中检索到的相关材料。
材料中包含中文文档（个人简历、笔记、心得）和英文文档（外部报告、组织架构图）。
{english_report_instruction}

请完成以下分析：
1. 从材料中提取与问题相关的关键事实，分别标注原文语言
2. 列出关键术语中英对照表
3. 梳理材料之间的逻辑关系（因果、时间线、对比等）
{NO_ANSWER_CONSTRAINT}
{org_chart_instruction}

输出 JSON 格式：
{{
  "key_facts": [
    {{"content": "...", "source": "文件名", "language": "zh|en"}}
  ],
  "terminology": [
    {{"zh": "组织架构", "en": "organizational structure"}}
  ],
  "logic_chain": "这些材料之间的逻辑关系..."
}}

[参考内容]
{chr(10).join(references)}

[用户问题]
{question}
"""


def _org_chart_grounding_instruction(chunks: List[RetrievedChunk]) -> str:
    if not any(chunk.source_type == "org_chart" or chunk.text.startswith("[ORG_CHART") for chunk in chunks):
        return ""
    return """
组织架构图关系题额外规则：
- 必须只依据同一个结构链中的明示父子关系、"is structurally under" 关系或同一 Page/Context Root 内的结构缩进回答。
- 不要把不同 Page、不同 Context Root 或不同分支的人员关系拼接成新的汇报链。
- 如果多个 org chart 片段看起来都相关，优先使用包含问题中明确人名/团队名的片段；其它片段只能作为补充背景，不能创造跨分支结论。
- 如果参考内容只显示名字拆行，可以合并为同一个人名，但必须说明这是基于同一结构链的合并；例如 "Dave" 下一层是 "Ross"，应合并为 Dave Ross；例如 "Ireland" 下是 "Paul" 再下一层 "Girr"，应合并为 Paul Girr。
""".strip()


def build_english_report_prompt(question: str, analysis: str, chunks: List[RetrievedChunk]) -> str:
    references = []
    for index, chunk in enumerate(chunks, start=1):
        references.append(f"--- chunk_{index} ({chunk.source_name}#{chunk.chunk_index})\n{chunk.text}")
    return f"""You are writing an English report based on a personal knowledge base.

DeepSeek analysis:
{analysis}

Original references:
{chr(10).join(references)}

User question:
{question}

Write a concise English report. Use the DeepSeek analysis as the primary structure, keep claims grounded in the references, and mention source files where useful.
"""


class RemoteLLMClient:
    def __init__(self, endpoint: str, api_key: str, model_name: str):
        self.endpoint = endpoint
        self.api_key = api_key
        self.model_name = model_name

    async def stream(self, prompt: str) -> AsyncGenerator[str, None]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream("POST", self.endpoint, headers=headers, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line.removeprefix("data: ").strip()
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = event.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield content


async def analyze_with_deepseek(
    question: str,
    chunks: List[RetrievedChunk],
    endpoint: str,
    api_key: str,
    model_name: str,
    client: Optional[Any] = None,
    include_chinese_advice: bool = False,
    report_language: str = "zh",
) -> str:
    deepseek = client or RemoteLLMClient(endpoint, api_key, model_name)
    prompt = build_deepseek_analysis_prompt(
        question,
        chunks,
        include_chinese_advice=include_chinese_advice,
        report_language=report_language,
    )
    parts = []
    async for token in deepseek.stream(prompt):
        parts.append(token)
    return "".join(parts)


async def generate_answer(
    question: str,
    chunks: List[RetrievedChunk],
    language: str = "zh",
    deepseek_endpoint: str = "",
    deepseek_api_key: str = "",
    deepseek_model: str = "deepseek-v4-pro",
    generation_endpoint: str = "",
    generation_api_key: str = "",
    generation_model: str = "codex-base",
    deepseek_client: Optional[Any] = None,
    llm_client: Optional[Any] = None,
    debug_payload: Optional[dict] = None,
) -> AsyncGenerator[str, None]:
    if not chunks:
        yield _sse({"type": "token", "content": "暂无相关内容。"})
        yield _sse({"type": "done"})
        return

    normalized_language = language if language in {"zh", "en"} else "zh"
    if not _is_deepseek_available(deepseek_endpoint, deepseek_client):
        yield _sse({"type": "token", "content": "DeepSeek 模型未配置。"})
        yield _sse(_sources_event(chunks, debug_payload=debug_payload))
        yield _sse({"type": "done"})
        return

    if normalized_language == "zh":
        try:
            analysis = await analyze_with_deepseek(
                question,
                chunks,
                deepseek_endpoint,
                deepseek_api_key,
                deepseek_model,
                client=deepseek_client,
                include_chinese_advice=True,
            )
            answer = _format_chinese_answer(analysis, chunks)
            if _is_no_answer(answer) and _has_direct_query_evidence(question, chunks):
                answer = _generate_grounded_chinese_fallback(question, chunks)
            yield _sse({"type": "token", "content": answer})
        except Exception as exc:
            yield _sse({"type": "error", "content": f"DeepSeek 调用失败: {exc}"})
            answer = ""
        yield _sse(_sources_event(chunks, answer, debug_payload=debug_payload))
        yield _sse({"type": "done"})
        return

    try:
        analysis = await analyze_with_deepseek(
            question,
            chunks,
            deepseek_endpoint,
            deepseek_api_key,
            deepseek_model,
            client=deepseek_client,
            report_language="en",
        )
    except Exception as exc:
        yield _sse({"type": "error", "content": f"DeepSeek 调用失败: {exc}"})
        yield _sse(_sources_event(chunks, debug_payload=debug_payload))
        yield _sse({"type": "done"})
        return

    if not generation_model and llm_client is None:
        yield _sse({"type": "token", "content": "英文输出模型未配置。"})
        yield _sse(_sources_event(chunks, debug_payload=debug_payload))
        yield _sse({"type": "done"})
        return

    if not generation_endpoint and llm_client is None:
        if generation_model == "codex-base":
            for token in _generate_codex_base_english_report(question, analysis, chunks):
                yield _sse({"type": "token", "content": token})
            yield _sse(_sources_event(chunks, analysis, debug_payload=debug_payload))
            yield _sse({"type": "done"})
            return
        yield _sse({"type": "token", "content": "英文输出模型未配置。"})
        yield _sse(_sources_event(chunks, debug_payload=debug_payload))
        yield _sse({"type": "done"})
        return

    client = llm_client or RemoteLLMClient(generation_endpoint, generation_api_key, generation_model)
    prompt = build_english_report_prompt(question, analysis, chunks)
    try:
        async for token in client.stream(prompt):
            yield _sse({"type": "token", "content": token})
    except Exception as exc:
        yield _sse({"type": "error", "content": f"LLM 调用失败: {exc}"})
    yield _sse(_sources_event(chunks, analysis, debug_payload=debug_payload))
    yield _sse({"type": "done"})


def _sources(chunks: Iterable[RetrievedChunk]) -> List[dict]:
    return [
        {
            "source_name": chunk.source_name,
            "source_type": chunk.source_type,
            "chunk_index": chunk.chunk_index,
            "relevance": chunk.score,
            "chunk_id": chunk.chunk_id,
            "raw_file_path": chunk.raw_file_path,
        }
        for chunk in chunks
    ]


def _source_refs(chunks: Iterable[RetrievedChunk]) -> List[str]:
    refs = []
    for chunk in chunks:
        source = f"{chunk.source_name}#{chunk.chunk_index}"
        if source not in refs:
            refs.append(source)
    return refs


def _sources_event(
    chunks: Iterable[RetrievedChunk],
    answer: str = "",
    debug_payload: Optional[dict] = None,
) -> dict:
    if _is_no_answer(answer):
        event = {"type": "sources", "source_status": "no_answer", "sources": []}
    else:
        event = {"type": "sources", "source_status": "grounded", "sources": _sources(chunks)}
    if debug_payload is not None:
        event["_debug"] = debug_payload
    return event


def _is_no_answer(answer: str) -> bool:
    text = " ".join(str(answer or "").split())
    if not text:
        return False
    head = text[:500]
    no_answer_markers = [
        "无法回答",
        "暂无相关内容",
        "无匹配来源",
        "没有匹配来源",
        "没有任何信息涉及",
        "没有直接涉及",
        "无法为您解答",
        "没有关于",
        "没有与",
        "还没有与",
        "并没有关于",
        "知识库缺少",
        "当前知识库缺少",
        "知识库中缺少",
        "当前知识库缺失",
        "知识库缺失",
        "没有涉及",
        "没有直接相关",
        "无直接相关",
        "未涉及",
        "未提及",
        "无法用来回答",
        "无法判断",
        "无适用资料",
        "完全不包含",
        "完全不相关",
        "不包含相关主题",
        "没有涵盖任何",
        "资料不足",
        "信息不足",
    ]
    return any(marker in head for marker in no_answer_markers)


def _strip_source_references(answer: str) -> str:
    stripped = re.split(r"(?:\n\s*)?来源[:：]", answer, maxsplit=1)[0].strip()
    return re.sub(r"[（(【\[]\s*$", "", stripped).rstrip()


def _generate_codex_base_fallback(question: str, chunks: List[RetrievedChunk]) -> Iterable[str]:
    lines = [
        "基于当前知识库检索结果，先给出可执行的初步回答。\n\n",
        f"问题：{question}\n\n",
        "相关内容：\n",
    ]
    for index, chunk in enumerate(chunks[:5], start=1):
        excerpt = " ".join(chunk.text.split())
        if len(excerpt) > 220:
            excerpt = excerpt[:220] + "..."
        lines.append(f"{index}. {excerpt}（来源：{chunk.source_name}#{chunk.chunk_index}）\n")
    lines.append("\n建议：优先围绕以上来源中的事实继续追问或补充材料；如果需要更强的综合推理，可在配置页接入外部生成模型。\n")
    return lines


def _generate_grounded_chinese_fallback(question: str, chunks: List[RetrievedChunk]) -> str:
    lines = [
        "检索到与问题直接相关的资料，但模型未能完成综合判断。先基于当前知识库给出可追溯的初步结论。\n\n",
        f"问题：{question}\n\n",
        "相关依据：\n",
    ]
    for index, chunk in enumerate(chunks[:5], start=1):
        excerpt = _compact_text(chunk.text, 220)
        if excerpt:
            lines.append(f"{index}. {excerpt}（来源：{chunk.source_name}#{chunk.chunk_index}）\n")
    lines.append("\n建议：请优先打开以上来源核对原文；如需更明确状态判断，可以继续追问“只基于这些来源归纳当前状态”。")
    return "".join(lines)


def _generate_codex_base_english_report(question: str, analysis: str, chunks: List[RetrievedChunk]) -> Iterable[str]:
    parsed = _parse_json_object(analysis)
    facts = parsed.get("key_facts") if isinstance(parsed, dict) and isinstance(parsed.get("key_facts"), list) else []
    terminology = parsed.get("terminology") if isinstance(parsed, dict) and isinstance(parsed.get("terminology"), list) else []
    logic_chain = parsed.get("logic_chain") if isinstance(parsed, dict) and isinstance(parsed.get("logic_chain"), str) else ""

    lines = [
        "English Report\n\n",
        "Executive Summary\n",
        f"This report answers the user question: {question}\n",
    ]
    if logic_chain:
        lines.append(f"{logic_chain.strip()}\n")
    elif facts:
        first_fact = facts[0] if isinstance(facts[0], dict) else {}
        content = str(first_fact.get("content", "")).strip()
        if content:
            lines.append(f"The most relevant evidence is: {content}\n")
    else:
        summary = _compact_text(analysis, 260)
        if summary:
            lines.append(f"The retrieved materials indicate the following: {summary}\n")

    if facts:
        lines.append("\nKey Findings\n")
        for index, fact in enumerate(facts[:6], start=1):
            if not isinstance(fact, dict):
                continue
            content = str(fact.get("content", "")).strip()
            source = str(fact.get("source", "")).strip()
            if not content:
                continue
            suffix = f" Source: {source}." if source else ""
            lines.append(f"{index}. {content}{suffix}\n")
    else:
        lines.append("\nKey Findings\n")
        for index, chunk in enumerate(chunks[:5], start=1):
            excerpt = _compact_text(chunk.text, 180)
            if excerpt:
                lines.append(f"{index}. {excerpt} Source: {chunk.source_name}#{chunk.chunk_index}.\n")

    term_lines = []
    for term in terminology[:8]:
        if not isinstance(term, dict):
            continue
        zh = str(term.get("zh", "")).strip()
        en = str(term.get("en", "")).strip()
        if zh and en:
            term_lines.append(f"- {en}: {zh}\n")
    if term_lines:
        lines.extend(["\nTerminology\n", *term_lines])

    lines.append("\nRecommended Use\n")
    lines.append(
        "Use this as a readable first draft. Where the source material is sparse or image-derived, verify the original file before making final decisions.\n"
    )

    lines.append("\nSources\n")
    seen_sources = set()
    for chunk in chunks[:8]:
        label = f"{chunk.source_name}#{chunk.chunk_index}"
        if label in seen_sources:
            continue
        seen_sources.add(label)
        lines.append(f"- {label}\n")
    return lines


def _format_chinese_answer(raw_answer: str, chunks: List[RetrievedChunk]) -> str:
    answer = raw_answer.strip()
    if _is_no_answer(answer):
        return _strip_source_references(answer)

    parsed = _parse_json_object(answer)
    if not isinstance(parsed, dict):
        return answer

    facts = parsed.get("key_facts") if isinstance(parsed.get("key_facts"), list) else []
    terminology = parsed.get("terminology") if isinstance(parsed.get("terminology"), list) else []
    logic_chain = parsed.get("logic_chain") if isinstance(parsed.get("logic_chain"), str) else ""

    if not facts and not logic_chain:
        return answer

    lines = ["核心结论："]
    if logic_chain:
        lines.append(logic_chain)
    else:
        first_fact = facts[0] if isinstance(facts[0], dict) else {}
        lines.append(str(first_fact.get("content", "")).strip())

    if facts:
        lines.extend(["", "关键依据："])
        for index, fact in enumerate(facts, start=1):
            if not isinstance(fact, dict):
                continue
            content = str(fact.get("content", "")).strip()
            if content:
                lines.append(f"{index}. {content}")

    if terminology:
        term_lines = []
        for term in terminology:
            if not isinstance(term, dict):
                continue
            zh = str(term.get("zh", "")).strip()
            en = str(term.get("en", "")).strip()
            if zh and en:
                term_lines.append(f"- {zh}：{en}")
        if term_lines:
            lines.extend(["", "相关术语：", *term_lines])

    sources = _source_refs(chunks)
    if sources:
        lines.extend(["", "来源：", *[f"- {source}" for source in sources]])

    return "\n".join(lines).strip()


def _compact_text(text: str, limit: int) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) > limit:
        return compact[:limit].rstrip() + "..."
    return compact


DIRECT_EVIDENCE_STOPWORDS = {
    "目前",
    "我的",
    "什么",
    "哪些",
    "是否",
    "怎么",
    "如何",
    "这个",
    "那个",
    "当前",
    "一下",
    "相关",
}


def _has_direct_query_evidence(question: str, chunks: List[RetrievedChunk]) -> bool:
    terms = _meaningful_query_terms(question)
    if len(terms) < 2:
        return False
    required_hits = min(2, len(terms))
    for chunk in chunks[:5]:
        text = chunk.text.lower()
        hits = sum(1 for term in terms if term.lower() in text)
        if hits >= required_hits:
            return True
    return False


def _meaningful_query_terms(question: str) -> List[str]:
    try:
        import jieba

        raw_terms = [term.strip() for term in jieba.cut(question) if term.strip()]
    except Exception:
        raw_terms = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]{2,}", question)

    terms = []
    for term in raw_terms:
        normalized = term.strip(" ?？!！,，.。:：;；、").lower()
        if not normalized or normalized in DIRECT_EVIDENCE_STOPWORDS:
            continue
        if len(normalized) >= 2 and normalized not in terms:
            terms.append(normalized)
    return terms


def _parse_json_object(text: str) -> Optional[dict]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _is_deepseek_available(endpoint: str, client: Optional[Any]) -> bool:
    return bool(endpoint or client is not None)


def _sse(payload: dict) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
```

### File: ./engine/indexer.py
```python
import asyncio
import json
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.request

from engine.models import Chunk


class OllamaEmbeddingClient:
    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "bge-m3",
        query_prefix: str = "",
    ):
        self.host = host
        self.model = model
        self.query_prefix = query_prefix

    def embed(self, texts: List[str]) -> List[List[float]]:
        vectors = []
        for text in texts:
            vectors.append(self._embed_one(text))
        return vectors

    def embed_query(self, query: str) -> List[float]:
        prompt = f"{self.query_prefix}{query}" if self.query_prefix else query
        return self._embed_one(prompt)

    def _embed_one(self, text: str) -> List[float]:
        request = urllib.request.Request(
            url=f"{self.host.rstrip('/')}/api/embeddings",
            data=json.dumps({"model": self.model, "prompt": text}, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Ollama embedding failed for model {self.model}: {exc}") from exc

        embedding = payload.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            raise RuntimeError(f"Ollama embedding returned no vector for model {self.model}")
        return [float(value) for value in embedding]


class HybridIndexer:
    def __init__(
        self,
        fts_db_path: str,
        vector_dir: str,
        collection_name: str,
        embedding_client: Optional[Any] = None,
    ):
        self.fts_db_path = Path(fts_db_path)
        self.vector_dir = Path(vector_dir)
        self.collection_name = collection_name
        self.embedding_client = embedding_client or OllamaEmbeddingClient()
        self.fts_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.vector_dir.mkdir(parents=True, exist_ok=True)
        self.client, self.collection = self._build_collection()
        self._init_fts()

    def _build_collection(self):
        import chromadb
        from chromadb.config import Settings

        client = chromadb.PersistentClient(
            path=str(self.vector_dir),
            settings=Settings(anonymized_telemetry=False),
        )
        collection = client.get_or_create_collection(name=self.collection_name)
        return client, collection

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.fts_db_path))

    def _init_fts(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    chunk_id UNINDEXED,
                    text UNINDEXED,
                    tokens,
                    source_name UNINDEXED,
                    source_type UNINDEXED,
                    chunk_index UNINDEXED,
                    created_at UNINDEXED
                )
                """
            )

    def upsert(self, chunks: List[Chunk], raw_file_paths: Optional[List[str]] = None) -> int:
        if not chunks:
            return 0
        if raw_file_paths is not None and len(raw_file_paths) != len(chunks):
            raise ValueError("raw_file_paths length must match chunks length")
        vectors = self.embedding_client.embed([chunk.embedding_text or chunk.text for chunk in chunks])
        with self._connect() as connection:
            for chunk in chunks:
                connection.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (chunk.id,))
                connection.execute(
                    """
                    INSERT INTO chunks_fts(chunk_id, text, tokens, source_name, source_type, chunk_index, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk.id,
                        chunk.text,
                        _tokenize(chunk.text),
                        chunk.source_name,
                        chunk.source_type,
                        chunk.chunk_index,
                        chunk.created_at,
                    ),
                )
        self.collection.upsert(
            ids=[chunk.id for chunk in chunks],
            embeddings=vectors,
            metadatas=[
                {
                    "source_name": chunk.source_name,
                    "source_type": chunk.source_type,
                    "chunk_index": chunk.chunk_index,
                    "created_at": chunk.created_at,
                    "raw_file_path": raw_file_paths[index] if raw_file_paths else "",
                }
                for index, chunk in enumerate(chunks)
            ],
            documents=[chunk.text for chunk in chunks],
        )
        return len(chunks)

    def clear_all(self) -> None:
        result = self.collection.get()
        ids = result.get("ids", [])
        if ids:
            self.collection.delete(ids=ids)
        with self._connect() as connection:
            connection.execute("DELETE FROM chunks_fts")

    def search_fts(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        tokens = _safe_fts_query(_tokenize(query))
        if not tokens:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT chunk_id, text, source_name, source_type, chunk_index, bm25(chunks_fts) AS rank
                FROM chunks_fts
                WHERE tokens MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (tokens, top_k),
            ).fetchall()
        path_map = self._metadata_path_map([row[0] for row in rows])
        return [
            {
                "chunk_id": row[0],
                "text": row[1],
                "source_name": row[2],
                "source_type": row[3],
                "chunk_index": int(row[4]),
                "score": float(row[5]),
                "raw_file_path": path_map.get(row[0], ""),
            }
            for row in rows
        ]

    def search_vector(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        collection_count = self.collection.count()
        if collection_count == 0:
            return []
        if hasattr(self.embedding_client, "embed_query"):
            query_vector = self.embedding_client.embed_query(query)
        else:
            query_vector = self.embedding_client.embed([query])[0]
        results = None
        for n_results in _vector_n_results_attempts(min(top_k, collection_count)):
            try:
                results = self._query_collection(
                    query_vector=query_vector,
                    n_results=n_results,
                )
                break
            except RuntimeError:
                continue
        if results is None:
            return []
        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        return [
            {
                "chunk_id": chunk_id,
                "text": document,
                "source_name": metadata["source_name"],
                "source_type": metadata["source_type"],
                "chunk_index": int(metadata["chunk_index"]),
                "score": _distance_to_score(distance),
                "raw_file_path": metadata.get("raw_file_path", ""),
            }
            for chunk_id, document, metadata, distance in zip(ids, documents, metadatas, distances)
        ]

    def _query_collection(self, *, query_vector: List[float], n_results: int) -> Dict[str, Any]:
        query_kwargs = {
            "query_embeddings": [query_vector],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
        }
        if not _running_event_loop_in_current_thread():
            return self.collection.query(**query_kwargs)

        result_box = []
        error_box = []

        def run_query():
            try:
                result_box.append(self.collection.query(**query_kwargs))
            except BaseException as exc:
                error_box.append(exc)

        thread = threading.Thread(target=run_query, name="pka-chroma-query")
        thread.start()
        thread.join()
        if error_box:
            raise error_box[0]
        return result_box[0]

    def get_chunk(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        result = self.collection.get(
            ids=[chunk_id],
            include=["documents", "metadatas", "embeddings"],
        )
        if not result.get("ids"):
            return None
        metadata = result["metadatas"][0]
        return {
            "chunk_id": chunk_id,
            "vector": result["embeddings"][0],
            "text": result["documents"][0],
            "source_name": metadata["source_name"],
            "source_type": metadata["source_type"],
            "chunk_index": metadata["chunk_index"],
            "created_at": metadata["created_at"],
            "raw_file_path": metadata.get("raw_file_path", ""),
        }

    def count_chunks(self) -> int:
        return self.collection.count()

    def count_sources(self) -> int:
        result = self.collection.get(include=["metadatas"])
        return len({metadata["source_name"] for metadata in result.get("metadatas", [])})

    def _metadata_path_map(self, chunk_ids: List[str]) -> Dict[str, str]:
        if not chunk_ids:
            return {}
        result = self.collection.get(ids=chunk_ids, include=["metadatas"])
        return {
            chunk_id: (metadata or {}).get("raw_file_path", "")
            for chunk_id, metadata in zip(result.get("ids", []), result.get("metadatas", []))
        }


def _tokenize(text: str) -> str:
    try:
        import jieba

        tokens = [token.strip() for token in jieba.cut(text) if token.strip()]
    except Exception:
        tokens = [text]
    return " ".join(tokens)


def _running_event_loop_in_current_thread() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def _vector_n_results_attempts(n_results: int) -> List[int]:
    attempts = [max(1, int(n_results))]
    for fallback in (5, 3, 1):
        if fallback < attempts[0] and fallback not in attempts:
            attempts.append(fallback)
    return attempts


def _safe_fts_query(tokens: str) -> str:
    """Remove FTS5 syntax characters and quote terms before MATCH."""
    safe = re.sub(r"[、，,;；:：\-\(\)\[\]{}]", " ", tokens)
    terms = [term.strip() for term in safe.split() if term.strip()]
    if not terms:
        return ""
    return " OR ".join(f'"{term}"' for term in terms[:10])


def _distance_to_score(distance: float) -> float:
    return 1.0 / (1.0 + float(distance))
```

## 3. Configuration & Template Architecture
### File: ./config.yaml
```
data_dir: /Users/tristanzh/Documents/PKA_Data
chroma:
  collection_name: pka_knowledge
  persist_dir: /Users/tristanzh/Documents/PKA_Data/.vector
fts5:
  db_path: /Users/tristanzh/Documents/PKA_Data/.fts5/pka.db
embedding:
  host: http://localhost:11434
  model: bge-m3
  query_prefix: ''
ocr:
  endpoint: ''
  api_key: ''
  model: doubao-1-5-vision-pro-32k
  max_images_per_request: 10
deepseek:
  endpoint: 'https://api.deepseek.com/v1/chat/completions'
  api_key: 'sk-9368df4cac3941b7803b25d3ba8c4218'
  model: deepseek-v4-pro
generation:
  endpoint: ''
  api_key: ''
  model: codex-base
  max_context_chunks: 10
ppt_maker:
  enabled: true
  http_base_url: http://127.0.0.1:8000
  ws_url: ws://127.0.0.1:8000/ws/generate
  timeout_seconds: 180
  page_count: 5
  style: business-summary
chunking:
  max_chunk_size: 1024
  chunk_overlap: 128
  md_split_by: '##'
ingest:
  max_sync_chunks_per_file: 150
retrieval:
  fts5_top_k: 10
  vector_top_k: 10
  rrf_k: 60
  final_top_k: 10
reranker:
  enabled: false
  host: http://localhost:11434
  model: qllama/bge-reranker-v2-m3
  query_prefix: 'Represent this sentence for searching relevant passages: '
  candidate_top_k: 20
  final_top_k: 7
  timeout_seconds: 30
  fail_open: true
server:
  host: 0.0.0.0
  port: 8086
```

