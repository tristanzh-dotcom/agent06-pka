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
from engine.indexer import HybridIndexer
from engine.ocr import VolcengineOCR
from engine.parser import parse_file, parse_text
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
        return HybridIndexer(
            fts_db_path=self.config["fts5"]["db_path"],
            vector_dir=self.config["chroma"]["persist_dir"],
            collection_name=self.config["chroma"]["collection_name"],
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
    chunks = _chunk(parsed.text, parsed.source_name, parsed.source_type)
    count = runtime.indexer.upsert(chunks)
    runtime.last_updated = datetime.now().isoformat()
    return {
        "status": "ok",
        "chunks": count,
        "source_name": parsed.source_name,
        "chunk_ids": [chunk.id for chunk in chunks],
    }


@app.post("/api/ingest/file")
async def ingest_file(file: UploadFile = File(...)):
    raw_dir = Path(runtime.config["data_dir"]) / "raw" / datetime.now().strftime("%Y-%m-%d")
    raw_dir.mkdir(parents=True, exist_ok=True)
    output_path = raw_dir / Path(file.filename or "upload").name
    with output_path.open("wb") as output:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
    ocr = VolcengineOCR(
        runtime.config["ocr"]["endpoint"],
        runtime.config["ocr"]["api_key"],
        runtime.config["ocr"]["model"],
    )
    try:
        parsed = await parse_file(str(output_path), mime_type=file.content_type, ocr_client=ocr)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    chunks = _chunk(parsed.text, parsed.source_name, parsed.source_type)
    raw_file_path = str(output_path.relative_to(Path(runtime.config["data_dir"])))
    count = runtime.indexer.upsert(chunks, raw_file_paths=[raw_file_path] * len(chunks))
    runtime.last_updated = datetime.now().isoformat()
    return {
        "status": "ok",
        "chunks": count,
        "source_name": parsed.source_name,
        "chunk_ids": [chunk.id for chunk in chunks],
    }


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
    path = export_to_ppt(request.question, request.answer, request.sources, str(output_path))
    return FileResponse(path, media_type="text/markdown; charset=utf-8", filename=Path(path).name)


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
    return JSONResponse({"status": "ok", "message": "配置接口可用；外部模型请通过一次实际问答验证。"})


def _chunk(text: str, source_name: str, source_type: str):
    return chunk_text(
        text,
        source_name,
        source_type,
        max_chunk_size=runtime.config["chunking"]["max_chunk_size"],
        chunk_overlap=runtime.config["chunking"]["chunk_overlap"],
    )


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
