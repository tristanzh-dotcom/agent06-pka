import json
import hashlib
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4


ASSET_TYPE = "answer_result"
RAG_STATUS = "not_indexed"


def save_answer_asset(data_dir: str, payload: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    operation_key = _operation_key(payload)
    existing = _find_by_operation_key(data_dir, operation_key)
    if existing is not None:
        manifest, asset_rel = existing
        response = _response_payload(manifest, asset_rel)
        response["outcome"] = "idempotent_reuse"
        return response
    created_at = (now or datetime.now()).isoformat()
    day = created_at[:10]
    asset_id = f"ans_{_timestamp_id(created_at)}_{uuid4().hex[:6]}"
    title = _derive_title(payload.get("title") or payload.get("question") or "")
    asset_rel = Path("assets") / "answers" / day / asset_id
    asset_dir = Path(data_dir) / asset_rel
    asset_dir.mkdir(parents=True, exist_ok=False)

    manifest = {
        "asset_id": asset_id,
        "asset_type": ASSET_TYPE,
        "title": title,
        "question": str(payload.get("question", "")).strip(),
        "answer": str(payload.get("answer", "")).strip(),
        "sources": _clean_sources(payload.get("sources") or []),
        "source_status": str(payload.get("source_status") or "grounded"),
        "evidence": payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {},
        "language": str(payload.get("language") or "zh"),
        "answer_mode": str(payload.get("answer_mode") or "answer"),
        "model_route": str(payload.get("model_route") or ""),
        "created_at": created_at,
        "updated_at": created_at,
        "tags": [],
        "status": "saved",
        "rag_status": RAG_STATUS,
        "publication_status": "local_only",
        "operation_key": operation_key,
        "exports": [],
    }

    manifest_path = asset_dir / "manifest.json"
    answer_path = asset_dir / "answer.md"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    answer_path.write_text(_render_answer_markdown(manifest), encoding="utf-8")

    return _response_payload(manifest, asset_rel)


def list_answer_assets(data_dir: str, limit: int = 50, before: str = "") -> List[Dict[str, Any]]:
    root = Path(data_dir) / "assets" / "answers"
    if not root.exists():
        return []
    safe_limit = min(max(0, int(limit)), 200)
    assets = []
    for manifest_path in root.glob("*/*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if before and str(manifest.get("created_at", "")) >= before:
            continue
        asset_rel = manifest_path.parent.relative_to(Path(data_dir))
        assets.append(_list_item(manifest, asset_rel))
    assets.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return assets[:safe_limit]


def read_answer_asset(data_dir: str, asset_id: str) -> Optional[Dict[str, Any]]:
    paths = answer_asset_paths(data_dir, asset_id)
    if paths is None:
        return None
    try:
        manifest = json.loads(paths["manifest_path"].read_text(encoding="utf-8"))
        answer_markdown = paths["answer_path"].read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError):
        return None
    return {
        "asset_id": manifest.get("asset_id", asset_id),
        "manifest": manifest,
        "answer_markdown": answer_markdown,
    }


def delete_answer_asset(data_dir: str, asset_id: str) -> bool:
    paths = answer_asset_paths(data_dir, asset_id)
    if paths is None:
        return False
    data_root = Path(data_dir).resolve()
    asset_dir = paths["asset_dir"].resolve()
    try:
        asset_dir.relative_to((data_root / "assets" / "answers").resolve())
    except ValueError:
        return False
    shutil.rmtree(asset_dir)
    return True


def answer_asset_paths(data_dir: str, asset_id: str) -> Optional[Dict[str, Path]]:
    root = Path(data_dir) / "assets" / "answers"
    if not root.exists() or not _safe_asset_id(asset_id):
        return None
    matches = list(root.glob(f"*/{asset_id}/manifest.json"))
    if not matches:
        return None
    manifest_path = matches[0]
    asset_dir = manifest_path.parent
    return {
        "asset_dir": asset_dir,
        "manifest_path": manifest_path,
        "answer_path": asset_dir / "answer.md",
        "exports_dir": asset_dir / "exports",
    }


def update_answer_asset_manifest(data_dir: str, asset_id: str, changes: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    paths = answer_asset_paths(data_dir, asset_id)
    if paths is None:
        return None
    try:
        manifest = json.loads(paths["manifest_path"].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    manifest.update(changes)
    manifest["updated_at"] = datetime.now().isoformat()
    paths["manifest_path"].write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def record_answer_asset_export(
    data_dir: str,
    asset_id: str,
    *,
    export_format: str,
    export_path: str,
    now: Optional[datetime] = None,
    max_records: int = 5,
) -> Optional[Dict[str, Any]]:
    paths = answer_asset_paths(data_dir, asset_id)
    if paths is None:
        return None
    manifest_path = paths["manifest_path"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    data_root = Path(data_dir).resolve()
    export_file = Path(export_path).resolve()
    try:
        export_rel = export_file.relative_to(data_root)
    except ValueError:
        raise ValueError("export path must be inside data_dir")
    record = {
        "format": export_format,
        "path": export_rel.as_posix(),
        "created_at": (now or datetime.now()).isoformat(),
    }
    exports = list(manifest.get("exports") or [])
    exports.append(record)
    exports.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    kept = exports[:max_records]
    pruned = exports[max_records:]
    for item in pruned:
        _delete_export_file_if_safe(data_root, paths["exports_dir"], item.get("path", ""))
    kept.sort(key=lambda item: item.get("created_at", ""))
    manifest["exports"] = kept
    manifest["updated_at"] = record["created_at"]
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def _response_payload(manifest: Dict[str, Any], asset_rel: Path) -> Dict[str, Any]:
    manifest_rel = asset_rel / "manifest.json"
    answer_rel = asset_rel / "answer.md"
    return {
        "status": "ok",
        "asset_id": manifest["asset_id"],
        "asset_type": ASSET_TYPE,
        "title": manifest["title"],
        "asset_path": asset_rel.as_posix(),
        "manifest_path": manifest_rel.as_posix(),
        "answer_path": answer_rel.as_posix(),
        "rag_status": RAG_STATUS,
        "publication_status": manifest.get("publication_status", "local_only"),
        "outcome": "created",
        "created_at": manifest["created_at"],
    }


def _operation_key(payload: Dict[str, Any]) -> str:
    stable = {
        "question": str(payload.get("question", "")).strip(),
        "answer": str(payload.get("answer", "")).strip(),
        "sources": _clean_sources(payload.get("sources") or []),
        "source_status": str(payload.get("source_status") or "grounded"),
        "evidence": payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {},
        "language": str(payload.get("language") or "zh"),
        "answer_mode": str(payload.get("answer_mode") or "answer"),
        "model_route": str(payload.get("model_route") or ""),
    }
    encoded = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _find_by_operation_key(data_dir: str, operation_key: str):
    root = Path(data_dir) / "assets" / "answers"
    if not root.exists():
        return None
    for manifest_path in root.glob("*/*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("operation_key") == operation_key:
            return manifest, manifest_path.parent.relative_to(Path(data_dir))
    return None


def _list_item(manifest: Dict[str, Any], asset_rel: Path) -> Dict[str, Any]:
    return {
        "asset_id": manifest.get("asset_id", ""),
        "title": manifest.get("title", ""),
        "question": manifest.get("question", ""),
        "language": manifest.get("language", ""),
        "answer_mode": manifest.get("answer_mode", ""),
        "source_status": manifest.get("source_status", ""),
        "rag_status": manifest.get("rag_status", RAG_STATUS),
        "created_at": manifest.get("created_at", ""),
        "asset_path": asset_rel.as_posix(),
        "source_count": len(manifest.get("sources") or []),
        "export_count": len(manifest.get("exports") or []),
    }


def _render_answer_markdown(manifest: Dict[str, Any]) -> str:
    source_lines = _source_lines(manifest.get("sources") or [])
    return "\n".join(
        [
            f"# {manifest['title']}",
            "",
            "## Question",
            "",
            manifest["question"],
            "",
            "## Answer",
            "",
            manifest["answer"],
            "",
            "## Sources",
            "",
            *source_lines,
            "",
            "## Metadata",
            "",
            f"- asset_id: {manifest['asset_id']}",
            f"- asset_type: {ASSET_TYPE}",
            f"- source_status: {manifest['source_status']}",
            f"- language: {manifest['language']}",
            f"- answer_mode: {manifest['answer_mode']}",
            f"- model_route: {manifest['model_route']}",
            f"- rag_status: {RAG_STATUS}",
            f"- created_at: {manifest['created_at']}",
            "",
        ]
    )


def _source_lines(sources: List[Dict[str, Any]]) -> List[str]:
    if not sources:
        return ["- 无"]
    lines = []
    for source in sources:
        chunk_id = str(source.get("chunk_id") or "").strip()
        source_name = str(source.get("source_name") or "未知来源").strip()
        chunk_index = source.get("chunk_index")
        if chunk_id:
            label = chunk_id
        elif chunk_index is not None:
            label = f"{source_name}#{chunk_index}"
        else:
            label = source_name
        lines.append(f"- {label}")
    return lines


def _clean_sources(sources: Any) -> List[Dict[str, Any]]:
    if not isinstance(sources, list):
        raise ValueError("sources must be a list")
    cleaned = []
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("sources must contain objects")
        cleaned.append(dict(source))
    return cleaned


def _derive_title(value: str) -> str:
    title = " ".join(str(value or "").split())
    if not title:
        return "未命名资料"
    return title[:40]


def _timestamp_id(value: str) -> str:
    return re.sub(r"[^0-9]", "", value)[:14]


def _safe_asset_id(asset_id: str) -> bool:
    return bool(re.fullmatch(r"ans_[0-9]{14}_[a-f0-9]{6}", str(asset_id or "")))


def _delete_export_file_if_safe(data_root: Path, exports_dir: Path, export_rel_path: str) -> None:
    if not export_rel_path:
        return
    candidate = (data_root / export_rel_path).resolve()
    try:
        candidate.relative_to(exports_dir.resolve())
    except ValueError:
        return
    try:
        if candidate.is_file():
            candidate.unlink()
    except OSError:
        return
