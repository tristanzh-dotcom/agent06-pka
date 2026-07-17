import asyncio
from collections import Counter
import hashlib
import json
import os
import threading
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Dict, Optional
import urllib.error
import urllib.request
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine.chunker import chunk_text
from engine.config import load_config, sanitize_config, save_config, update_config
from engine.answer_planner import infer_answer_mode
from engine.answer_assets import (
    answer_asset_paths,
    delete_answer_asset,
    list_answer_assets,
    read_answer_asset,
    record_answer_asset_export,
    save_answer_asset,
    update_answer_asset_manifest,
)
from engine.evidence import build_evidence_report
from engine.exporter import export_to_ppt, export_to_word
from engine.generator import generate_answer
from engine.generated_knowledge import promote_answer_asset
from engine.indexer import HybridIndexer, OllamaEmbeddingClient
from engine.ingest_registry import ContentRegistry, ContentReservation, sha256_text
from engine.source_registry import SourceRegistry
from engine.input_fidelity import expand_adjacent_chunks
from engine.models import Chunk, ParseQuality, ParseResult
from engine.ocr import build_ocr_provider_chain
from engine.parser import ocr_org_chart_pre_chunks, parse_file, parse_text
from engine.ppt_maker_adapter import export_to_quality_ppt
from engine.query_rewriter import expand_query
from engine.query_context import filter_supported_chunks, resolve_query
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
        content_hash: str = "",
        source_id: str = "",
        original_name: str = "",
        replace_source_id: str = "",
        quality_policy: str = "review",
    ) -> str:
        task_id = f"ocr_task_{uuid4().hex[:12]}"
        payload = {
            "task_id": task_id,
            "status": "queued",
            "file_name": file_name,
            "raw_file_path": raw_file_path,
            "content_type": content_type,
            "content_hash": content_hash,
            "source_id": source_id,
            "original_name": original_name or file_name,
            "replace_source_id": replace_source_id,
            "quality_policy": quality_policy,
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
    conversation_id: str = ""
    previous_question: str = ""


class ExportRequest(BaseModel):
    question: str
    answer: str
    sources: list[dict] = []


class SaveAnswerAssetRequest(BaseModel):
    question: str
    answer: str
    sources: list[dict] = []
    source_status: str = "grounded"
    evidence: dict = {}
    language: str = "zh"
    answer_mode: str = "answer"
    model_route: str = ""
    title: str = ""


class AddGeneratedKnowledgeRequest(BaseModel):
    question: str
    answer: str
    sources: list[dict] = []
    source_status: str = "grounded"
    evidence: dict = {}
    language: str = "zh"
    answer_mode: str = "answer"
    model_route: str = ""
    created_at: str = ""


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


@app.get("/assets", response_class=HTMLResponse)
async def assets_page():
    return _html("assets.html")


@app.get("/settings", response_class=HTMLResponse)
async def settings_page():
    return _html("settings.html")


@app.post("/api/ingest/text")
async def ingest_text(request: TextIngestRequest):
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    source_name = "manual_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    source_id = f"source_{uuid4().hex}"
    content_hash = sha256_text(request.text)
    reservation = _content_registry().reserve(
        content_hash=content_hash,
        source_name=source_name,
        raw_file_path="",
        content_kind="manual_text",
    )
    if reservation.status != "reserved":
        return _duplicate_ingest_result(reservation)
    try:
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
        return await _ingest_parsed_result(
            parsed,
            content_type="text/plain",
            raw_file_path="",
            content_hash=content_hash,
            source_id=source_id,
            original_name=source_name,
        )
    except HTTPException:
        _content_registry().mark_failed(content_hash, "manual text ingest rejected")
        raise
    except Exception as exc:
        _content_registry().mark_failed(content_hash, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/ingest/file")
async def ingest_file(
    file: UploadFile = File(...),
    org_chart_mode: str = Form("disabled"),
    quality_policy: str = Form("review"),
    version_policy: str = Form("review"),
):
    ocr = _build_ocr_client()
    try:
        result = await _ingest_upload_file(
            file,
            ocr,
            extract_org_charts=_is_org_chart_mode_enabled(org_chart_mode),
            quality_policy=quality_policy,
            version_policy=version_policy,
        )
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
        "duplicate_of": result.get("duplicate_of"),
        "message": result.get("message", ""),
        "source_id": result.get("source_id", ""),
        "coverage": result.get("coverage", {}),
        "existing_source": result.get("existing_source"),
        "replacement_cleanup": result.get("replacement_cleanup", ""),
        "replacement_cleanup_error": result.get("replacement_cleanup_error", ""),
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
    duplicates = 0
    review_required = 0
    version_conflicts = 0
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
            elif result.get("status") in {"duplicate", "duplicate_pending"}:
                duplicates += 1
            elif result.get("status") == "review_required":
                review_required += 1
            elif result.get("status") == "version_conflict":
                version_conflicts += 1
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
        "status": "ok" if failed == 0 and skipped == 0 and review_required == 0 and version_conflicts == 0 else "partial",
        "total_files": len(files),
        "succeeded": succeeded,
        "accepted": accepted,
        "duplicates": duplicates,
        "review_required": review_required,
        "version_conflicts": version_conflicts,
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
            content_hash = str(task.get("content_hash") or "")
            if content_hash:
                _content_registry().mark_failed(content_hash, "raw file is missing")
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


async def _ingest_upload_file(
    file: UploadFile,
    ocr,
    extract_org_charts: bool = False,
    quality_policy: str = "review",
    version_policy: str = "review",
):
    raw_dir = Path(runtime.config["data_dir"]) / "raw" / datetime.now().strftime("%Y-%m-%d")
    raw_dir.mkdir(parents=True, exist_ok=True)
    output_path = raw_dir / Path(file.filename or "upload").name
    output_path = _dedupe_upload_path(output_path)
    original_name = Path(file.filename or "upload").name
    source_id = f"source_{uuid4().hex}"
    staging_path, content_hash = await _stage_upload_and_hash(file)
    registry = _content_registry()
    _backfill_indexed_raw_content_identities(registry)
    _backfill_source_registry()
    existing_source = _source_registry().find_active_by_original_name(original_name)
    previous_reservation = registry.lookup(content_hash)
    if (
        previous_reservation is not None
        and previous_reservation.status == "review_required"
        and str(quality_policy).lower() == "accept"
        and previous_reservation.raw_file_path
    ):
        data_dir = Path(runtime.config["data_dir"]).resolve()
        reviewed_path = (data_dir / previous_reservation.raw_file_path).resolve()
        if data_dir in reviewed_path.parents:
            output_path = reviewed_path
    reservation = registry.reserve(
        content_hash=content_hash,
        source_name=output_path.name,
        raw_file_path=str(output_path.relative_to(Path(runtime.config["data_dir"]))),
        content_kind="file",
        allow_review_retry=str(quality_policy).lower() == "accept",
        allow_version_retry=str(version_policy).lower() in {"replace", "keep"},
    )
    if reservation.status != "reserved":
        staging_path.unlink(missing_ok=True)
        if reservation.status == "version_conflict" and existing_source is not None:
            return _version_conflict_result(existing_source)
        if reservation.status == "review_required":
            return {
                "status": "review_required",
                "chunks": 0,
                "source_name": reservation.source_name,
                "chunk_ids": [],
                "raw_file_path": reservation.raw_file_path,
                "quality": None,
                "coverage": {},
                "source_id": "",
                "message": "该资料此前的解析质量或完整性需要确认，请选择是否仍然入库。",
            }
        return _duplicate_ingest_result(reservation)
    if existing_source is not None and str(version_policy).lower() not in {"replace", "keep"}:
        staging_path.unlink(missing_ok=True)
        registry.mark_version_conflict(content_hash, "same original filename has different content")
        return _version_conflict_result(existing_source)

    try:
        staging_path.replace(output_path)
        parsed = await parse_file(
            str(output_path),
            mime_type=file.content_type,
            ocr_client=ocr,
            extract_org_charts=extract_org_charts,
        )
    except Exception as exc:
        staging_path.unlink(missing_ok=True)
        registry.mark_failed(content_hash, str(exc))
        raise
    raw_file_path = str(output_path.relative_to(Path(runtime.config["data_dir"])))
    quality = parsed.quality
    if quality is not None and quality.status == "needs_ocr":
        task_id = _ocr_task_store().create_task(
            file_name=Path(file.filename or parsed.source_name).name,
            raw_file_path=raw_file_path,
            content_type=file.content_type or "",
            page_count=int(parsed.metadata.get("page_count", 0) or 0),
            content_hash=content_hash,
            source_id=source_id,
            original_name=original_name,
            replace_source_id=existing_source.source_id if existing_source and str(version_policy).lower() == "replace" else "",
            quality_policy=str(quality_policy).lower(),
        )
        registry.mark_pending(content_hash, task_id=task_id)
        return {
            "status": "accepted",
            "task_id": task_id,
            "file_name": Path(file.filename or parsed.source_name).name,
            "chunks": 0,
            "source_name": parsed.source_name,
            "chunk_ids": [],
            "raw_file_path": raw_file_path,
            "quality": _quality_payload(replace(quality, action="needs_ocr_queued")),
            "source_id": source_id,
            "coverage": parsed.metadata.get("coverage", {}),
        }
    if _requires_quality_review(parsed) and str(quality_policy).lower() != "accept":
        quality_payload = _quality_payload(quality)
        coverage = dict(parsed.metadata.get("coverage") or {})
        output_path.unlink(missing_ok=True)
        registry.mark_review_required(content_hash, "quality or extraction coverage requires review")
        return {
            "status": "review_required",
            "chunks": 0,
            "source_name": parsed.source_name,
            "chunk_ids": [],
            "raw_file_path": "",
            "quality": quality_payload,
            "coverage": coverage,
            "source_id": source_id,
            "message": "解析结果质量较低或内容不完整，请确认是否仍然入库。",
        }
    try:
        result = await _ingest_parsed_result(
            parsed,
            content_type=file.content_type,
            raw_file_path=raw_file_path,
            provider=locals().get("ocr_provider", ""),
            attempts=locals().get("ocr_attempts", []),
            ocr_result=locals().get("ocr_result_meta"),
            content_hash=content_hash,
            source_id=source_id,
            original_name=original_name,
        )
    except Exception as exc:
        registry.mark_failed(content_hash, str(exc))
        raise
    if existing_source is not None and str(version_policy).lower() == "replace":
        try:
            _delete_source_record(existing_source)
        except Exception as exc:
            _source_registry().mark_delete_failed(existing_source.source_id, str(exc))
            result["replacement_cleanup"] = "failed"
            result["replacement_cleanup_error"] = str(exc)
            result["message"] = "新版本已入库，但旧版本清理失败；两者暂时同时保留。"
    return result


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
                "coverage": {
                    "format": "pdf_ocr",
                    "status": "partial" if ocr_result.partial else "complete",
                    "warnings": ["OCR page limit reached"] if ocr_result.partial else [],
                    "counts": {
                        "pages": ocr_result.source_page_count,
                        "processed_pages": ocr_result.pages_processed,
                    },
                },
            },
            quality=quality,
            pre_chunks=pre_chunks,
        )
        if _requires_quality_review(parsed) and str(task.get("quality_policy") or "review").lower() != "accept":
            content_hash = str(task.get("content_hash") or "")
            if content_hash:
                _content_registry().mark_review_required(content_hash, "OCR quality or coverage requires review")
            store.update_task(
                task_id,
                {
                    "status": "review_required",
                    "progress": 100,
                    "result": {
                        "chunks_inserted": 0,
                        "quality_action": "ocr_review_required",
                        "quality": _quality_payload(quality, provider=ocr_result.provider, attempts=ocr_result.attempts, ocr_result=ocr_result),
                        "coverage": parsed.metadata["coverage"],
                        "source_id": task.get("source_id", ""),
                        "error": None,
                    },
                },
            )
            return
        ingest_result = _run_coroutine_sync(
            _ingest_parsed_result(
                parsed,
                content_type=task.get("content_type", "application/pdf"),
                raw_file_path=task["raw_file_path"],
                provider=ocr_result.provider,
                attempts=ocr_result.attempts,
                ocr_result=ocr_result,
                content_hash=str(task.get("content_hash") or ""),
                source_id=str(task.get("source_id") or ""),
                original_name=str(task.get("original_name") or task.get("file_name") or ""),
            )
        )
        replace_source_id = str(task.get("replace_source_id") or "")
        if replace_source_id:
            replaced = _source_registry().get(replace_source_id)
            if replaced is not None:
                try:
                    _delete_source_record(replaced)
                except Exception as exc:
                    _source_registry().mark_delete_failed(replaced.source_id, str(exc))
                    ingest_result["replacement_cleanup"] = "failed"
                    ingest_result["replacement_cleanup_error"] = str(exc)
        store.update_task(
            task_id,
            {
                "status": "completed",
                "progress": 100,
                "result": {
                    "chunks_inserted": ingest_result["chunks"],
                    "quality_action": "ocr",
                    "quality": ingest_result.get("quality"),
                    "coverage": ingest_result.get("coverage", {}),
                    "source_id": ingest_result.get("source_id", ""),
                    "raw_file_path": ingest_result.get("raw_file_path", ""),
                    "replacement_cleanup": ingest_result.get("replacement_cleanup", "ok"),
                    "replacement_cleanup_error": ingest_result.get("replacement_cleanup_error", ""),
                    "error": None,
                    **_ocr_task_org_chart_result(ingest_result),
                },
            },
        )
    except Exception as exc:
        content_hash = str(task.get("content_hash") or "")
        if content_hash:
            _content_registry().mark_failed(content_hash, str(exc))
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
    content_hash: str = "",
    source_id: str = "",
    original_name: str = "",
):
    quality_payload = _quality_payload(
        parsed.quality,
        provider=provider,
        attempts=attempts or [],
        ocr_result=ocr_result,
    )
    coverage = dict((getattr(parsed, "metadata", {}) or {}).get("coverage") or {})
    chunk_metadata = {
        **dict(getattr(parsed, "metadata", {}) or {}),
        "source_id": source_id,
        "original_name": original_name or parsed.source_name,
        "quality": quality_payload or {},
        "coverage": coverage,
    }
    chunks = [
        replace(
            chunk,
            id=f"{source_id}#{chunk.chunk_index}" if source_id else chunk.id,
            metadata={**dict(chunk.metadata or {}), **chunk_metadata},
        )
        for chunk in _chunk(parsed.text, parsed.source_name, parsed.source_type)
    ]
    pre_chunks = getattr(parsed, "pre_chunks", [])
    chunks.extend(
        _pre_chunk_records(
            pre_chunks,
            source_id=source_id,
            shared_metadata=chunk_metadata,
        )
    )
    if not chunks:
        raise ValueError("no indexable content")
    with ingest_lock:
        _enforce_sync_chunk_limit(len(chunks), parsed.source_name)
        count = runtime.indexer.upsert(chunks, raw_file_paths=[raw_file_path] * len(chunks))
        runtime.last_updated = datetime.now().isoformat()
    if content_hash:
        _content_registry().mark_indexed(content_hash, chunk_count=count)
    if source_id:
        _source_registry().create_indexed(
            source_id=source_id,
            content_hash=content_hash,
            content_kind="file" if raw_file_path else "manual_text",
            original_name=original_name or parsed.source_name,
            source_name=parsed.source_name,
            raw_file_path=raw_file_path,
            chunk_count=count,
            quality=quality_payload,
            coverage=coverage,
        )
    org_chart_pages = [record.metadata.get("page") for record in pre_chunks if getattr(record, "metadata", None)]
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
        "coverage": coverage,
        "source_id": source_id,
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


def _requires_quality_review(parsed) -> bool:
    quality = getattr(parsed, "quality", None)
    if quality is not None and quality.status == "low":
        return True
    coverage = dict((getattr(parsed, "metadata", {}) or {}).get("coverage") or {})
    return coverage.get("status") == "partial"


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


def _content_registry() -> ContentRegistry:
    return ContentRegistry(Path(runtime.config["data_dir"]) / "runtime" / "content_registry.sqlite")


def _source_registry() -> SourceRegistry:
    return SourceRegistry(Path(runtime.config["data_dir"]) / "runtime" / "source_registry.sqlite")


def _source_record_payload(record) -> dict:
    return {
        "source_id": record.source_id,
        "content_hash": record.content_hash,
        "content_kind": record.content_kind,
        "original_name": record.original_name,
        "source_name": record.source_name,
        "raw_file_path": record.raw_file_path,
        "status": record.status,
        "chunk_count": record.chunk_count,
        "quality": record.quality,
        "coverage": record.coverage,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "error": record.error,
    }


def _decode_metadata_object(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _backfill_source_registry() -> None:
    registry = _source_registry()
    try:
        result = runtime.indexer.collection.get(include=["metadatas"])
    except Exception:
        return
    grouped = {}
    for metadata in result.get("metadatas", []):
        metadata = metadata or {}
        source_name = str(metadata.get("source_name") or "")
        raw_file_path = str(metadata.get("raw_file_path") or "")
        if not source_name:
            continue
        source_id = str(metadata.get("source_id") or "")
        if not source_id:
            legacy_key = hashlib.sha256(f"{source_name}\n{raw_file_path}".encode("utf-8")).hexdigest()[:24]
            source_id = f"legacy_{legacy_key}"
        entry = grouped.setdefault(
            source_id,
            {
                "source_id": source_id,
                "source_name": source_name,
                "original_name": str(metadata.get("original_name") or source_name),
                "raw_file_path": raw_file_path,
                "quality": _decode_metadata_object(metadata.get("quality")),
                "coverage": _decode_metadata_object(metadata.get("coverage")),
                "chunk_count": 0,
            },
        )
        entry["chunk_count"] += 1
    data_dir = Path(runtime.config["data_dir"]).resolve()
    for entry in grouped.values():
        if registry.get(entry["source_id"]) is not None:
            continue
        content_hash = ""
        raw_file_path = entry["raw_file_path"]
        if raw_file_path:
            candidate = (data_dir / raw_file_path).resolve()
            if candidate.is_file() and data_dir in candidate.parents:
                content_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
        registry.create_indexed(
            source_id=entry["source_id"],
            content_hash=content_hash,
            content_kind="file" if raw_file_path else "manual_text",
            original_name=entry["original_name"],
            source_name=entry["source_name"],
            raw_file_path=raw_file_path,
            chunk_count=entry["chunk_count"],
            quality=entry["quality"],
            coverage=entry["coverage"],
        )


def _backfill_indexed_raw_content_identities(registry: ContentRegistry) -> None:
    if not registry.needs_index_backfill():
        return
    try:
        result = runtime.indexer.collection.get(include=["metadatas"])
    except Exception:
        return
    records = {}
    for metadata in result.get("metadatas", []):
        metadata = metadata or {}
        raw_file_path = str(metadata.get("raw_file_path") or "")
        source_name = str(metadata.get("source_name") or "")
        if raw_file_path and source_name:
            records.setdefault(raw_file_path, {"source_name": source_name, "chunk_count": 0})["chunk_count"] += 1
    data_dir = Path(runtime.config["data_dir"]).resolve()
    for raw_file_path, record in records.items():
        candidate = (data_dir / raw_file_path).resolve()
        if not candidate.is_file() or data_dir not in candidate.parents:
            continue
        digest = hashlib.sha256()
        with candidate.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        registry.register_indexed_existing(
            content_hash=digest.hexdigest(),
            source_name=record["source_name"],
            raw_file_path=raw_file_path,
            content_kind="file",
            chunk_count=record["chunk_count"],
        )
    registry.mark_index_backfill_complete()


async def _stage_upload_and_hash(file: UploadFile) -> tuple[Path, str]:
    staging_dir = Path(runtime.config["data_dir"]) / "runtime" / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    staging_path = staging_dir / f"upload_{uuid4().hex}.tmp"
    digest = hashlib.sha256()
    with staging_path.open("wb") as output:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            output.write(chunk)
    return staging_path, digest.hexdigest()


def _duplicate_ingest_result(reservation: ContentReservation) -> dict:
    pending = reservation.status == "duplicate_pending"
    return {
        "status": reservation.status,
        "chunks": 0,
        "source_name": reservation.source_name,
        "chunk_ids": [],
        "raw_file_path": reservation.raw_file_path,
        "task_id": reservation.task_id,
        "duplicate_of": {
            "source_name": reservation.source_name,
            "raw_file_path": reservation.raw_file_path,
            "task_id": reservation.task_id,
            "chunk_count": reservation.chunk_count,
        },
        "message": "检测到完全相同的资料正在处理，未创建重复任务。" if pending else "检测到完全相同的资料，未重复录入。",
    }


def _version_conflict_result(existing_source) -> dict:
    return {
        "status": "version_conflict",
        "chunks": 0,
        "source_name": existing_source.source_name,
        "chunk_ids": [],
        "raw_file_path": "",
        "quality": None,
        "coverage": {},
        "source_id": "",
        "existing_source": _source_record_payload(existing_source),
        "message": "检测到同名资料已有不同版本，请选择替换旧版本或同时保留。",
    }


@app.get("/api/ingest/sources")
async def list_ingest_sources():
    _backfill_source_registry()
    return {
        "status": "ok",
        "sources": [_source_record_payload(record) for record in _source_registry().list_sources()],
    }


@app.delete("/api/ingest/sources/{source_id}")
async def delete_ingest_source(source_id: str):
    registry = _source_registry()
    record = registry.get(source_id)
    if record is None:
        raise HTTPException(status_code=404, detail="source not found")
    try:
        deleted_chunks = _delete_source_record(record)
    except Exception as exc:
        registry.mark_delete_failed(source_id, str(exc))
        raise HTTPException(status_code=500, detail=f"source deletion failed: {exc}") from exc
    return {
        "status": "ok",
        "deleted_source_id": source_id,
        "deleted_chunks": deleted_chunks,
    }


def _delete_source_record(record) -> int:
    registry = _source_registry()
    with ingest_lock:
        deleted_chunks = runtime.indexer.delete_source(record.source_id, source_name=record.source_name)
        if record.raw_file_path:
            data_dir = Path(runtime.config["data_dir"]).resolve()
            raw_path = (data_dir / record.raw_file_path).resolve()
            if data_dir not in raw_path.parents:
                raise ValueError("source raw path escapes data_dir")
            raw_path.unlink(missing_ok=True)
        _content_registry().delete(record.content_hash)
        registry.delete(record.source_id)
        runtime.last_updated = datetime.now().isoformat()
    return deleted_chunks


@app.post("/api/ingest/clear")
async def clear_knowledge():
    with ingest_lock:
        runtime.indexer.clear_all()
        _content_registry().clear()
        _source_registry().clear()
        runtime.last_updated = datetime.now().isoformat()
    return {"status": "ok", "message": "知识库已清空"}


@app.post("/api/query")
async def query(request: QueryRequest):
    resolution = resolve_query(request.question, request.previous_question)
    if resolution.status == "clarification_required":
        return StreamingResponse(
            _terminal_query_events(
                "这个问题需要上一轮主题才能继续。请明确说明要基于哪条资料或重新完整描述问题。",
                "clarification_required",
            ),
            media_type="text/event-stream",
        )

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
        retrieval_question=resolution.resolved_question,
        top_k=runtime.config["retrieval"]["final_top_k"],
    )
    if not chunks:
        return StreamingResponse(
            _terminal_query_events("当前知识库缺少相关信息，无法回答该问题。建议补充相关资料后重新提问。", "no_answer"),
            media_type="text/event-stream",
        )
    generator = generate_answer(
        question=resolution.resolved_question,
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


async def _terminal_query_events(content: str, source_status: str):
    yield f"data: {json.dumps({'type': 'token', 'content': content}, ensure_ascii=False)}\n\n"
    yield f"data: {json.dumps({'type': 'sources', 'sources': [], 'source_status': source_status}, ensure_ascii=False)}\n\n"
    yield 'data: {"type":"done"}\n\n'


def _retrieve_quality_context(*, retriever, request: QueryRequest, retrieval_question: str, top_k: int):
    expansion = expand_query(retrieval_question)
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
    dossier = build_topic_dossier(question=retrieval_question, variant_results=variant_results)
    supported_chunks = filter_supported_chunks(retrieval_question, dossier.chunks)
    chunks, fidelity_report = expand_adjacent_chunks(supported_chunks, runtime.indexer)
    answer_mode = infer_answer_mode(retrieval_question, request.language)
    evidence_payload = None
    if request.trace or request.debug:
        evidence_payload = build_evidence_report(
            chunks=chunks,
            query_variants=expansion.queries,
            variant_chunk_ids=variant_chunk_ids,
        ).to_dict()
        evidence_payload["input_fidelity"] = fidelity_report.to_dict()
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
    return chunks, debug_payload, evidence_payload


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


@app.post("/api/assets/answers")
async def save_answer_asset_endpoint(request: SaveAnswerAssetRequest):
    payload = request.model_dump() if hasattr(request, "model_dump") else request.dict()
    if not payload["question"].strip():
        raise HTTPException(status_code=400, detail="question is required")
    if not payload["answer"].strip():
        raise HTTPException(status_code=400, detail="answer is required")
    try:
        return save_answer_asset(runtime.config["data_dir"], payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/answer-assets/save-local")
async def save_local_answer_asset_endpoint(request: SaveAnswerAssetRequest):
    payload = request.model_dump() if hasattr(request, "model_dump") else request.dict()
    if not payload["question"].strip():
        raise HTTPException(status_code=400, detail="question is required")
    if not payload["answer"].strip():
        raise HTTPException(status_code=400, detail="answer is required")
    try:
        result = save_answer_asset(runtime.config["data_dir"], payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(status_code=200 if result["outcome"] == "idempotent_reuse" else 201, content=result)


@app.post("/api/answer-assets/publish-obsidian")
async def publish_answer_to_obsidian_endpoint(request: SaveAnswerAssetRequest):
    payload = request.model_dump() if hasattr(request, "model_dump") else request.dict()
    if not payload["question"].strip():
        raise HTTPException(status_code=400, detail="question is required")
    if not payload["answer"].strip():
        raise HTTPException(status_code=400, detail="answer is required")
    try:
        local_asset = save_answer_asset(runtime.config["data_dir"], payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    local_asset_dir = str((Path(runtime.config["data_dir"]) / local_asset["asset_path"]).resolve())
    if not _agent10_control_token():
        update_answer_asset_manifest(runtime.config["data_dir"], local_asset["asset_id"], {"publication_status": "pending_obsidian"})
        return JSONResponse(
            status_code=202,
            content={**local_asset, "status": "partial", "publication_status": "pending_obsidian", "message": "本地已保存，Obsidian 待发布"},
        )
    try:
        agent10_result = _publish_agent10_agent06_asset(local_asset_dir)
    except Exception as exc:
        update_answer_asset_manifest(runtime.config["data_dir"], local_asset["asset_id"], {"publication_status": "pending_obsidian"})
        raise HTTPException(status_code=502, detail={"message": "Obsidian 发布失败", "asset_id": local_asset["asset_id"], "error": str(exc)}) from exc
    update_answer_asset_manifest(
        runtime.config["data_dir"],
        local_asset["asset_id"],
        {"publication_status": "published", "agent10_asset": {key: agent10_result.get(key, "") for key in ("asset_id", "path", "mode", "mirror_status")}},
    )
    return JSONResponse(status_code=201, content={**local_asset, "status": "ok", "publication_status": "published", "agent10": agent10_result})


@app.post("/api/knowledge/add-generated")
async def add_generated_knowledge_endpoint(request: AddGeneratedKnowledgeRequest):
    payload = request.model_dump() if hasattr(request, "model_dump") else request.dict()
    if not payload["question"].strip():
        raise HTTPException(status_code=400, detail="question is required")
    if not payload["answer"].strip():
        raise HTTPException(status_code=400, detail="answer is required")
    if payload.get("source_status") == "no_answer":
        raise HTTPException(status_code=409, detail="no_answer results cannot be added to knowledge yet")
    try:
        local_asset = save_answer_asset(runtime.config["data_dir"], payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    local_asset_dir = str((Path(runtime.config["data_dir"]) / local_asset["asset_path"]).resolve())
    if not _agent10_control_token():
        return JSONResponse(
            status_code=202,
            content={
                "status": "deferred",
                "storage_status": "agent10_not_configured",
                "indexed": False,
                "local_asset": local_asset,
                "message": "AnswerResult saved locally; Agent10 producer API is not configured.",
            },
        )

    try:
        agent10_result = _publish_agent10_agent06_asset(local_asset_dir)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Agent10 producer API failed",
                "local_asset": local_asset,
                "error": str(exc),
            },
        ) from exc

    return JSONResponse(
        status_code=201,
        content={
            "status": "ok",
            "storage_status": "agent10_published",
            "indexed": False,
            "local_asset": local_asset,
            "agent10": agent10_result,
        },
    )


@app.post("/api/answer-assets/add-pka-retrieval")
async def add_answer_asset_to_pka_retrieval_endpoint(request: AddGeneratedKnowledgeRequest):
    payload = request.model_dump() if hasattr(request, "model_dump") else request.dict()
    if not payload["question"].strip():
        raise HTTPException(status_code=400, detail="question is required")
    if not payload["answer"].strip():
        raise HTTPException(status_code=400, detail="answer is required")
    if payload.get("source_status") == "no_answer":
        raise HTTPException(status_code=409, detail="no_answer results cannot be added to knowledge yet")
    try:
        local_asset = save_answer_asset(runtime.config["data_dir"], payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        promotion = promote_answer_asset(runtime.config["data_dir"], local_asset["asset_id"], runtime.indexer)
    except Exception as exc:
        vector_status = getattr(exc, "vector_status", "unknown")
        fts_status = getattr(exc, "fts_status", "unknown")
        quarantined = vector_status == "quarantined"
        update_answer_asset_manifest(
            runtime.config["data_dir"],
            local_asset["asset_id"],
            {"rag_status": "index_quarantined" if quarantined else "index_failed"},
        )
        return JSONResponse(
            status_code=202,
            content={
                "status": "partial",
                "local_status": "saved",
                "index_status": "quarantined" if quarantined else "failed",
                "fts_status": fts_status,
                "vector_status": vector_status,
                "publication_status": "not_attempted",
                "local_asset": local_asset,
                "index_error": str(exc),
            },
        )
    update_answer_asset_manifest(
        runtime.config["data_dir"],
        local_asset["asset_id"],
        {"rag_status": "indexed", "generated_knowledge": promotion},
    )
    local_asset_dir = str((Path(runtime.config["data_dir"]) / local_asset["asset_path"]).resolve())
    base_response = {
        "local_status": "saved",
        "index_status": "indexed",
        "local_asset": local_asset,
        "promotion": promotion,
    }
    if not _agent10_control_token():
        update_answer_asset_manifest(runtime.config["data_dir"], local_asset["asset_id"], {"publication_status": "pending_agent10"})
        return JSONResponse(
            status_code=202,
            content={
                **base_response,
                "status": "partial",
                "publication_status": "pending_agent10",
                "agent10": {"error": "Agent10 producer API is not configured."},
            },
        )
    try:
        agent10_result = _publish_agent10_agent06_asset(local_asset_dir)
    except Exception as exc:
        update_answer_asset_manifest(runtime.config["data_dir"], local_asset["asset_id"], {"publication_status": "pending_agent10"})
        return JSONResponse(
            status_code=202,
            content={
                **base_response,
                "status": "partial",
                "publication_status": "pending_agent10",
                "agent10": {"error": str(exc)},
            },
        )
    update_answer_asset_manifest(
        runtime.config["data_dir"],
        local_asset["asset_id"],
        {"publication_status": "published", "agent10_asset": agent10_result},
    )
    return JSONResponse(
        status_code=201,
        content={
            **base_response,
            "status": "ok",
            "publication_status": "published",
            "agent10": agent10_result,
        },
    )


def _publish_agent10_agent06_asset(source_asset_path: str) -> dict:
    token = _agent10_control_token()
    if not token:
        raise ValueError("Agent10 control token is not configured")
    endpoint = _agent10_base_url().rstrip("/") + "/api/agent10/producers/agent06/assets"
    body = json.dumps({"source_asset_path": source_asset_path}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "authorization": f"Bearer {token}",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Agent10 returned HTTP {exc.code}: {detail}") from exc
    return json.loads(payload)


def _agent10_base_url() -> str:
    return os.environ.get("AGENT10_BASE_URL", "http://127.0.0.1:8010")


def _agent10_control_token() -> str:
    token = os.environ.get("AGENT10_CONTROL_TOKEN", "").strip()
    if token:
        return token
    token_file = os.environ.get("AGENT10_CONTROL_TOKEN_FILE", "").strip()
    if not token_file:
        return ""
    try:
        return Path(token_file).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


@app.get("/api/assets/answers")
async def list_answer_assets_endpoint(limit: int = 50, before: str = ""):
    return {"status": "ok", "assets": list_answer_assets(runtime.config["data_dir"], limit=limit, before=before)}


@app.post("/api/assets/answers/{asset_id}/export/word")
async def export_answer_asset_word(asset_id: str):
    paths = answer_asset_paths(runtime.config["data_dir"], asset_id)
    asset = read_answer_asset(runtime.config["data_dir"], asset_id)
    if paths is None or asset is None:
        raise HTTPException(status_code=404, detail="asset not found")
    manifest = asset["manifest"]
    output_dir = paths["exports_dir"]
    output_path = output_dir / f"answer_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.docx"
    path = export_to_word(manifest["question"], manifest["answer"], manifest.get("sources", []), str(output_path))
    try:
        record_answer_asset_export(runtime.config["data_dir"], asset_id, export_format="word", export_path=path)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=Path(path).name,
    )


@app.post("/api/assets/answers/{asset_id}/export/ppt")
async def export_answer_asset_ppt(asset_id: str):
    paths = answer_asset_paths(runtime.config["data_dir"], asset_id)
    asset = read_answer_asset(runtime.config["data_dir"], asset_id)
    if paths is None or asset is None:
        raise HTTPException(status_code=404, detail="asset not found")
    manifest = asset["manifest"]
    output_dir = paths["exports_dir"]
    output_path = output_dir / f"answer_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.pptx"
    try:
        path = export_to_quality_ppt(
            manifest["question"],
            manifest["answer"],
            manifest.get("sources", []),
            str(output_path),
            runtime.config,
        )
    except Exception:
        path = export_to_ppt(manifest["question"], manifest["answer"], manifest.get("sources", []), str(output_path))
    try:
        record_answer_asset_export(runtime.config["data_dir"], asset_id, export_format="ppt", export_path=path)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=Path(path).name,
    )


@app.get("/api/assets/answers/{asset_id}")
async def read_answer_asset_endpoint(asset_id: str):
    asset = read_answer_asset(runtime.config["data_dir"], asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")
    return {"status": "ok", "asset": asset}


@app.delete("/api/assets/answers/{asset_id}")
async def delete_answer_asset_endpoint(asset_id: str):
    if not delete_answer_asset(runtime.config["data_dir"], asset_id):
        raise HTTPException(status_code=404, detail="asset not found")
    return {"status": "ok", "deleted_asset_id": asset_id}


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


def _chunk(text: str, source_name: str, source_type: str, *, metadata=None, source_id: str = ""):
    return chunk_text(
        text,
        source_name,
        source_type,
        max_chunk_size=runtime.config["chunking"]["max_chunk_size"],
        chunk_overlap=runtime.config["chunking"]["chunk_overlap"],
        metadata=metadata,
        source_id=source_id,
    )


def _pre_chunk_records(records, *, source_id: str = "", shared_metadata=None):
    created_at = datetime.now().astimezone().isoformat()
    chunks = []
    for index, record in enumerate(records):
        if not getattr(record, "is_pre_chunked", False):
            continue
        text = record.text
        chunks.append(
            Chunk(
                id=f"{source_id or record.source_name}#org_chart_{index}",
                text=text,
                source_name=record.source_name,
                source_type=record.source_type,
                chunk_index=index,
                created_at=created_at,
                embedding_text=text,
                metadata={**dict(shared_metadata or {}), **dict(getattr(record, "metadata", {}) or {})},
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
