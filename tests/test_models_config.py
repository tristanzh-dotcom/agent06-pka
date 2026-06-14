from dataclasses import FrozenInstanceError, is_dataclass
from pathlib import Path

import pytest

from engine.config import (
    DEFAULT_CONFIG,
    load_config,
    mask_secret,
    save_config,
    sanitize_config,
    update_config,
)
from engine.models import Chunk, ParseResult, RetrievedChunk


def test_parse_result_and_chunk_are_frozen_dataclasses():
    parsed = ParseResult(
        text="hello",
        source_name="note.txt",
        source_type="txt",
        metadata={"encoding": "utf-8"},
    )
    chunk = Chunk(
        id="note.txt#0",
        text="hello",
        source_name="note.txt",
        source_type="txt",
        chunk_index=0,
        created_at="2026-06-04T12:00:00+08:00",
    )

    assert is_dataclass(parsed)
    assert is_dataclass(chunk)
    with pytest.raises(FrozenInstanceError):
        parsed.text = "changed"
    with pytest.raises(FrozenInstanceError):
        chunk.text = "changed"


def test_retrieved_chunk_exposes_rank_metadata():
    retrieved = RetrievedChunk(
        chunk_id="note.txt#0",
        text="组织架构调整方案",
        source_name="note.txt",
        source_type="txt",
        chunk_index=0,
        score=0.25,
        rank_fts5=1,
        rank_vector=None,
    )

    assert retrieved.chunk_id == "note.txt#0"
    assert retrieved.rank_fts5 == 1
    assert retrieved.rank_vector is None
    assert retrieved.raw_file_path == ""


def test_config_loads_defaults_and_expands_data_paths(tmp_path):
    config_path = tmp_path / "config.yaml"
    config = load_config(config_path)

    assert config["data_dir"].endswith("PKA_Data")
    assert config["chroma"]["persist_dir"].endswith(".vector")
    assert config["fts5"]["db_path"].endswith("pka.db")
    assert config["generation"]["model"] == "codex-base"
    assert config["generation"]["endpoint"] == ""
    assert config["generation"]["api_key"] == ""
    assert config["generation"]["max_context_chunks"] == DEFAULT_CONFIG["generation"]["max_context_chunks"]
    assert config["deepseek"]["endpoint"] == ""
    assert config["deepseek"]["api_key"] == ""
    assert config["deepseek"]["model"] == "deepseek-v4-pro"
    assert config["ocr"]["provider_order"] == ["paddle", "volcengine"]
    assert config["ocr"]["max_pdf_pages"] == 10
    assert config["ocr"]["paddle"]["enabled"] is True
    assert config["ocr"]["paddle"]["lang"] == "ch"
    assert config["ocr"]["volcengine"]["enabled"] is True


def test_config_update_persists_and_sanitizes_api_keys(tmp_path):
    config_path = tmp_path / "config.yaml"
    config = load_config(config_path)
    updated = update_config(
        config,
        {
            "generation": {
                "endpoint": "https://example.test/v1/chat/completions",
                "api_key": "sk-test-secret",
                "model": "test-model",
            },
            "ocr": {"api_key": "ocr-secret"},
            "deepseek": {
                "endpoint": "https://deepseek.example/v1/chat/completions",
                "api_key": "deepseek-secret",
                "model": "deepseek-v4-pro",
            },
            "retrieval": {"final_top_k": 4},
        },
    )
    save_config(updated, config_path)

    reloaded = load_config(config_path)
    assert reloaded["generation"]["api_key"] == "sk-test-secret"
    assert reloaded["generation"]["model"] == "test-model"
    assert reloaded["deepseek"]["api_key"] == "deepseek-secret"
    assert reloaded["deepseek"]["model"] == "deepseek-v4-pro"
    assert reloaded["retrieval"]["final_top_k"] == 4

    sanitized = sanitize_config(reloaded)
    assert sanitized["generation"]["api_key"] == "****cret"
    assert sanitized["ocr"]["api_key"] == "****cret"
    assert sanitized["deepseek"]["api_key"] == "****cret"


def test_legacy_volcengine_ocr_config_is_mirrored_to_nested_provider(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "ocr:",
                "  endpoint: https://legacy-ocr.example/v1/chat/completions",
                "  api_key: legacy-ocr-secret",
                "  model: legacy-vision-model",
                "  max_images_per_request: 8",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config["ocr"]["volcengine"]["endpoint"] == "https://legacy-ocr.example/v1/chat/completions"
    assert config["ocr"]["volcengine"]["api_key"] == "legacy-ocr-secret"
    assert config["ocr"]["volcengine"]["model"] == "legacy-vision-model"
    assert config["ocr"]["volcengine"]["max_images_per_request"] == 8


def test_sanitize_config_masks_nested_volcengine_key(tmp_path):
    config = load_config(tmp_path / "config.yaml")
    config["ocr"]["api_key"] = "legacy-secret"
    config["ocr"]["volcengine"]["api_key"] = "nested-secret"

    sanitized = sanitize_config(config)

    assert sanitized["ocr"]["api_key"] == "****cret"
    assert sanitized["ocr"]["volcengine"]["api_key"] == "****cret"


def test_config_example_declares_deepseek_section():
    example = (Path(__file__).resolve().parents[1] / "config.example.yaml").read_text(encoding="utf-8")

    assert "deepseek:" in example
    assert 'model: "deepseek-v4-pro"' in example


def test_config_example_declares_ocr_provider_chain():
    example = (Path(__file__).resolve().parents[1] / "config.example.yaml").read_text(encoding="utf-8")

    assert "provider_order:" in example
    assert "- paddle" in example
    assert "- volcengine" in example
    assert "paddle:" in example
    assert "volcengine:" in example
    assert "max_pdf_pages: 10" in example


def test_mask_secret_does_not_reveal_short_values():
    assert mask_secret("") == ""
    assert mask_secret("abcd") == "****"
    assert mask_secret("abcdefghi") == "****fghi"
