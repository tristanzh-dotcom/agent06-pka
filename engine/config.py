from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Union

import yaml


DEFAULT_CONFIG: Dict[str, Any] = {
    "data_dir": "~/Documents/PKA_Data",
    "chroma": {
        "collection_name": "pka_knowledge",
        "persist_dir": "{data_dir}/.vector",
    },
    "fts5": {"db_path": "{data_dir}/.fts5/pka.db"},
    "embedding": {
        "host": "http://localhost:11434",
        "model": "bge-m3",
        "query_prefix": "",
    },
    "ocr": {
        "provider_order": ["paddle", "volcengine"],
        "max_pdf_pages": 10,
        "timeout_seconds": 120,
        "endpoint": "",
        "api_key": "",
        "model": "doubao-1-5-vision-pro-32k",
        "max_images_per_request": 10,
        "paddle": {
            "enabled": True,
            "lang": "ch",
            "use_angle_cls": True,
            "dpi": 150,
        },
        "volcengine": {
            "enabled": True,
            "endpoint": "",
            "api_key": "",
            "model": "doubao-1-5-vision-pro-32k",
            "max_images_per_request": 10,
        },
    },
    "deepseek": {
        "endpoint": "",
        "api_key": "",
        "model": "deepseek-v4-pro",
    },
    "generation": {
        "endpoint": "",
        "api_key": "",
        "model": "codex-base",
        "max_context_chunks": 10,
    },
    "ppt_maker": {
        "enabled": True,
        "http_base_url": "http://127.0.0.1:8000",
        "ws_url": "ws://127.0.0.1:8000/ws/generate",
        "timeout_seconds": 180,
        "page_count": 5,
        "style": "business-summary",
    },
    "chunking": {
        "max_chunk_size": 1024,
        "chunk_overlap": 128,
        "md_split_by": "##",
    },
    "ingest": {
        "max_sync_chunks_per_file": 100,
    },
    "retrieval": {
        "fts5_top_k": 10,
        "vector_top_k": 10,
        "rrf_k": 60,
        "final_top_k": 10,
    },
    "reranker": {
        "enabled": False,
        "host": "http://localhost:11434",
        "model": "qllama/bge-reranker-v2-m3",
        "query_prefix": "Represent this sentence for searching relevant passages: ",
        "candidate_top_k": 20,
        "final_top_k": 7,
        "timeout_seconds": 30,
        "fail_open": True,
    },
    "server": {"host": "0.0.0.0", "port": 8080},
}


def deep_merge(base: Dict[str, Any], updates: Mapping[str, Any]) -> Dict[str, Any]:
    merged = deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _expand_paths(config: Dict[str, Any]) -> Dict[str, Any]:
    expanded = deepcopy(config)
    data_dir = str(Path(expanded["data_dir"]).expanduser())
    expanded["data_dir"] = data_dir
    for section, key in [("chroma", "persist_dir"), ("fts5", "db_path")]:
        value = expanded[section][key]
        expanded[section][key] = str(Path(value.format(data_dir=data_dir)).expanduser())
    return expanded


def _normalize_ocr_config(config: Dict[str, Any], source: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    normalized = deepcopy(config)
    ocr = normalized.setdefault("ocr", {})
    ocr.setdefault("provider_order", ["paddle", "volcengine"])
    ocr.setdefault("max_pdf_pages", 10)
    ocr.setdefault("timeout_seconds", 120)
    ocr.setdefault("paddle", {})
    ocr.setdefault("volcengine", {})
    ocr["paddle"].setdefault("enabled", True)
    ocr["paddle"].setdefault("lang", "ch")
    ocr["paddle"].setdefault("use_angle_cls", True)
    ocr["paddle"].setdefault("dpi", 150)
    ocr["volcengine"].setdefault("enabled", True)
    source_ocr = source.get("ocr", {}) if isinstance(source, Mapping) else {}
    source_volcengine = source_ocr.get("volcengine", {}) if isinstance(source_ocr, Mapping) else {}
    for key in ("endpoint", "api_key", "model", "max_images_per_request"):
        legacy_value = ocr.get(key, DEFAULT_CONFIG["ocr"].get(key))
        ocr.setdefault(key, legacy_value)
        if key in source_ocr and key not in source_volcengine:
            ocr["volcengine"][key] = ocr.get(key, "")
        else:
            ocr["volcengine"].setdefault(key, ocr.get(key, ""))
    return normalized


def load_config(config_path: Union[str, Path] = "config.yaml") -> Dict[str, Any]:
    path = Path(config_path)
    raw: Dict[str, Any] = {}
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        raw = loaded if isinstance(loaded, dict) else {}
    return _expand_paths(_normalize_ocr_config(deep_merge(DEFAULT_CONFIG, raw), raw))


def save_config(config: Mapping[str, Any], config_path: Union[str, Path] = "config.yaml") -> None:
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(dict(config), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def update_config(config: Mapping[str, Any], updates: Mapping[str, Any]) -> Dict[str, Any]:
    return _expand_paths(_normalize_ocr_config(deep_merge(dict(config), updates), updates))


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "****"
    return "****" + value[-4:]


def sanitize_config(config: Mapping[str, Any]) -> Dict[str, Any]:
    sanitized = deepcopy(dict(config))
    for section in ("generation", "ocr", "deepseek"):
        if section in sanitized and "api_key" in sanitized[section]:
            sanitized[section]["api_key"] = mask_secret(str(sanitized[section]["api_key"]))
        if section in sanitized:
            _mask_nested_api_keys(sanitized[section])
    return sanitized


def _mask_nested_api_keys(value: Any) -> None:
    if not isinstance(value, dict):
        return
    for key, nested in value.items():
        if key == "api_key":
            value[key] = mask_secret(str(nested))
        elif isinstance(nested, dict):
            _mask_nested_api_keys(nested)
