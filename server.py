import asyncio
from collections import Counter
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
from engine.answer_planner import infer_answer_mode
from engine.evidence import build_evidence_report
from engine.exporter import export_to_ppt, export_to_word
from engine.generator import generate_answer
from engine.indexer import HybridIndexer, OllamaEmbeddingClient
from engine.models import Chunk, ParseQuality, ParseResult
from engine.ocr import build_ocr_provider_chain
from engine.parser import ocr_org_chart_pre_chunks, parse_file, parse_text
from engine.ppt_maker_adapter import export_to_quality_ppt
from engine.query_rewriter import expand_query
from engine.reranker import RerankerClient
from engine.retriever import HybridRetriever
from engine.topic_aggregator import build_topic_dossier


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
    trace: bool = False


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
        pre_chunks = ocr_org_chart_pre_chunks(
            ocr_result.text,
            source_name=task["file_name"],
            page_number=1,
        )
        parsed = ParseResult(
            text="" if pre_chunks else ocr_result.text,
            source_name=task["file_name"],
            source_type="org_chart" if pre_chunks else "pdf",
            metadata={
                "page_count": ocr_result.source_page_count,
                "non_empty_pages": ocr_result.pages_processed,
                "quality_status": quality.status if quality else "",
                "quality_action": quality.action if quality else "",
                "org_chart_pages": [record.metadata["page"] for record in pre_chunks],
                "org_chart_chunks": len(pre_chunks),
                "org_chart_mode": "ocr_layout_fallback" if pre_chunks else "",
            },
            quality=quality,
            pre_chunks=pre_chunks,
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
                    **_ocr_task_org_chart_result(ingest_result),
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
        quality_payload["org_chart_mode"] = _org_chart_mode(pre_chunks)
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


def _org_chart_mode(pre_chunks) -> str:
    for record in pre_chunks:
        metadata = getattr(record, "metadata", {}) or {}
        mode = metadata.get("org_chart_mode")
        if mode:
            return mode
    return "pdf_layout_fallback"


def _ocr_task_org_chart_result(ingest_result: dict) -> dict:
    quality = ingest_result.get("quality") or {}
    org_chart_chunks = quality.get("org_chart_chunks") or ingest_result.get("org_chart_chunks")
    if not org_chart_chunks:
        return {}
    payload = {"org_chart_chunks": org_chart_chunks}
    if quality.get("org_chart_mode"):
        payload["org_chart_mode"] = quality["org_chart_mode"]
    if quality.get("org_chart_pages"):
        payload["org_chart_pages"] = quality["org_chart_pages"]
    return payload


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
    reranker_config = runtime.config.get("reranker", {})
    reranker = None
    if reranker_config.get("enabled"):
        reranker = RerankerClient(
            host=reranker_config.get("host", "http://localhost:11434"),
            model=reranker_config.get("model", ""),
            query_prefix=reranker_config.get("query_prefix", ""),
            timeout_seconds=reranker_config.get("timeout_seconds", 30),
        )
    retriever = HybridRetriever(
        indexer=runtime.indexer,
        fts5_top_k=runtime.config["retrieval"]["fts5_top_k"],
        vector_top_k=runtime.config["retrieval"]["vector_top_k"],
        rrf_k=runtime.config["retrieval"]["rrf_k"],
        reranker=reranker,
        rerank_candidate_top_k=reranker_config.get("candidate_top_k", 20),
        rerank_timeout_seconds=reranker_config.get("timeout_seconds", 30),
    )
    chunks, debug_payload, evidence_payload = _retrieve_quality_context(
        retriever=retriever,
        request=request,
        top_k=runtime.config["retrieval"]["final_top_k"],
    )
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
        evidence_payload=evidence_payload,
    )
    return StreamingResponse(generator, media_type="text/event-stream")


def _retrieve_quality_context(*, retriever, request: QueryRequest, top_k: int):
    expansion = expand_query(request.question)
    variant_results = []
    variant_chunk_ids = {}
    debug_payload = None
    for index, variant in enumerate(expansion.queries):
        if request.debug and index == 0 and hasattr(retriever, "hybrid_search_with_debug"):
            chunks, debug_payload = retriever.hybrid_search_with_debug(variant.query, top_k)
        else:
            chunks = retriever.hybrid_search(variant.query, top_k)
        variant_results.append((variant, chunks))
        variant_chunk_ids[variant.query] = [chunk.chunk_id for chunk in chunks]
    dossier = build_topic_dossier(question=request.question, variant_results=variant_results)
    answer_mode = infer_answer_mode(request.question, request.language)
    evidence_payload = None
    if request.trace or request.debug:
        evidence_payload = build_evidence_report(
            chunks=dossier.chunks,
            query_variants=expansion.queries,
            variant_chunk_ids=variant_chunk_ids,
        ).to_dict()
        evidence_payload["answer_mode"] = {
            "mode": answer_mode.mode,
            "reason": answer_mode.reason,
        }
    if debug_payload is not None:
        debug_payload = {
            **debug_payload,
            "query_expansion": [
                {"query": variant.query, "reason": variant.reason}
                for variant in expansion.queries
            ],
            "answer_mode": {"mode": answer_mode.mode, "reason": answer_mode.reason},
        }
    return dossier.chunks, debug_payload, evidence_payload


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


@app.get("/api/knowledge/health")
async def knowledge_health():
    tasks = _ocr_task_store().list_tasks()
    task_statuses = Counter(task.get("status", "unknown") for task in tasks)
    quality_actions = Counter(
        (task.get("result") or {}).get("quality_action", "") for task in tasks
    )
    quality_actions.pop("", None)
    return {
        "indexed_sources": runtime.indexer.count_sources(),
        "total_chunks": runtime.indexer.count_chunks(),
        "source_types": _source_type_distribution(runtime.indexer),
        "ocr_tasks": dict(task_statuses),
        "recent_quality_actions": dict(quality_actions),
        "model_calls_required": False,
    }


def _source_type_distribution(indexer) -> dict:
    try:
        result = indexer.collection.get(include=["metadatas"])
    except Exception:
        return {}
    return dict(Counter((metadata or {}).get("source_type", "") for metadata in result.get("metadatas", []) if metadata))


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
