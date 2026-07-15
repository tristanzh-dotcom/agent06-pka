import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from engine.answer_assets import read_answer_asset
from engine.chunker import chunk_text


GENERATED_SOURCE_TYPE = "generated_asset"


def promote_answer_asset(
    data_dir: str,
    asset_id: str,
    indexer,
    *,
    max_chunk_size: int = 1024,
    chunk_overlap: int = 128,
) -> Dict[str, Any]:
    asset = read_answer_asset(data_dir, asset_id)
    if asset is None:
        raise ValueError("answer asset not found")
    manifest = asset["manifest"]
    metadata = _generated_metadata(manifest)
    generated_path = _generated_path(data_dir, manifest)
    relative_path = generated_path.relative_to(Path(data_dir)).as_posix()
    chunks = chunk_text(
        asset["answer_markdown"],
        source_name=generated_path.name,
        source_type=GENERATED_SOURCE_TYPE,
        max_chunk_size=max_chunk_size,
        chunk_overlap=chunk_overlap,
        metadata=metadata,
    )
    if generated_path.exists():
        return {
            "rag_status": "indexed",
            "outcome": "idempotent_reuse",
            "generated_path": relative_path,
            "chunk_ids": [chunk.id for chunk in chunks],
            "chunks_indexed": 0,
        }

    generated_path.parent.mkdir(parents=True, exist_ok=True)
    generated_path.write_text(_render_generated_markdown(asset["answer_markdown"], metadata), encoding="utf-8")
    chunks = chunk_text(
        generated_path.read_text(encoding="utf-8"),
        source_name=generated_path.name,
        source_type=GENERATED_SOURCE_TYPE,
        max_chunk_size=max_chunk_size,
        chunk_overlap=chunk_overlap,
        metadata=metadata,
    )
    try:
        indexed = indexer.upsert(chunks, raw_file_paths=[relative_path] * len(chunks))
    except Exception:
        generated_path.unlink(missing_ok=True)
        raise
    return {
        "rag_status": "indexed",
        "outcome": "indexed",
        "generated_path": relative_path,
        "chunk_ids": [chunk.id for chunk in chunks],
        "chunks_indexed": indexed,
    }


def _generated_path(data_dir: str, manifest: Dict[str, Any]) -> Path:
    created_at = str(manifest.get("created_at") or datetime.now().isoformat())
    day = created_at[:10] if len(created_at) >= 10 else datetime.now().strftime("%Y-%m-%d")
    return Path(data_dir) / "generated" / "knowledge" / day / f"generated_{manifest['asset_id']}.md"


def _generated_metadata(manifest: Dict[str, Any]) -> Dict[str, Any]:
    sources = manifest.get("sources") or []
    chunk_ids = [str(source.get("chunk_id")) for source in sources if source.get("chunk_id")]
    source_names = sorted({str(source.get("source_name")) for source in sources if source.get("source_name")})
    coverage = manifest.get("evidence", {}).get("coverage", {}) if isinstance(manifest.get("evidence"), dict) else {}
    return {
        "generated": True,
        "not_primary_source": True,
        "user_confirmed_for_knowledge_base": True,
        "asset_id": manifest["asset_id"],
        "derived_from_chunk_ids": chunk_ids,
        "derived_from_sources": source_names,
        "question": manifest.get("question", ""),
        "language": manifest.get("language", "zh"),
        "model_route": manifest.get("model_route", ""),
        "created_at": manifest.get("created_at", ""),
        "evidence_coverage_status": coverage.get("coverage_status", manifest.get("source_status", "grounded")),
    }


def _render_generated_markdown(answer_markdown: str, metadata: Dict[str, Any]) -> str:
    header = ["---", f"source_type: {GENERATED_SOURCE_TYPE}", "generated: true", "not_primary_source: true", "user_confirmed_for_knowledge_base: true"]
    for key in ("asset_id", "language", "model_route", "created_at", "evidence_coverage_status"):
        header.append(f"{key}: {json.dumps(metadata.get(key, ''), ensure_ascii=False)}")
    header.extend(["---", ""])
    return "\n".join(header) + answer_markdown
