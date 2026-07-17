import json
import shutil
import sys

import pytest

import scripts.verify_public_automotive_ingest as ingest_verifier
from scripts.verify_public_automotive_ingest import (
    LocalSample,
    PUBLIC_SAMPLE_MANIFEST,
    PROJECT_ROOT,
    PublicSample,
    _create_isolated_runtime,
    ensure_project_import_path,
    parse_local_sample,
    serialize_report,
    validate_manifest,
)


def test_completed_async_upload_counts_as_successful_reupload():
    completed_upload_succeeded = getattr(
        ingest_verifier,
        "_completed_upload_succeeded",
        lambda _payload: False,
    )

    assert completed_upload_succeeded(
        {
            "status": "accepted",
            "source_id": "source_scan",
            "chunks": 1,
        }
    )
    assert not completed_upload_succeeded(
        {
            "status": "accepted",
            "source_id": "",
            "chunks": 0,
        }
    )


def test_parse_local_sample_accepts_existing_docx_with_explicit_query(tmp_path):
    document = tmp_path / "functional_medicine.docx"
    document.write_bytes(b"PK\x03\x04")

    sample = parse_local_sample(f"{document}::功能医学 演讲")

    assert sample == LocalSample(
        key="local_functional_medicine",
        filename="functional_medicine.docx",
        path=str(document),
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        anchor_query="功能医学 演讲",
    )


def test_parse_local_sample_uses_supported_extension_when_platform_mime_is_missing(
    tmp_path,
    monkeypatch,
):
    document = tmp_path / "random_notes.md"
    document.write_text("# Random notes\n", encoding="utf-8")
    monkeypatch.setattr(
        "scripts.verify_public_automotive_ingest.mimetypes.guess_type",
        lambda _filename: (None, None),
    )

    sample = parse_local_sample(f"{document}::Random notes")

    assert sample.mime_type == "text/markdown"


@pytest.mark.parametrize("spec", ["", "missing.docx::功能医学", "document.docx::"])
def test_parse_local_sample_rejects_missing_path_or_query(tmp_path, spec):
    if spec == "document.docx::":
        spec = f"{tmp_path / 'document.docx'}::"
        (tmp_path / "document.docx").write_bytes(b"PK\x03\x04")

    with pytest.raises(ValueError):
        parse_local_sample(spec)


def test_runner_keeps_project_root_importable_for_post_upload_index_verification(monkeypatch):
    monkeypatch.setattr(sys, "path", [path for path in sys.path if path != str(PROJECT_ROOT)])
    ensure_project_import_path()
    assert str(PROJECT_ROOT) in sys.path


def test_isolated_runtime_raises_sync_chunk_limit_for_realistic_spreadsheets():
    root, _data_dir, _port = _create_isolated_runtime()
    try:
        config = json.loads((root / "config.yaml").read_text(encoding="utf-8"))
        assert config["ingest"]["max_sync_chunks_per_file"] >= 500
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_public_manifest_contains_only_documented_public_samples_and_valid_mime_types():
    samples = validate_manifest(PUBLIC_SAMPLE_MANIFEST)

    assert [sample.key for sample in samples] == [
        "automotive_docx_exclusion",
        "automotive_pptx_exclusion",
        "ons_vehicle_registrations_xlsx",
        "nhtsa_automotive_pdf",
        "apollo_autonomous_vehicle_png",
        "nuscenes_can_bus_markdown",
        "apollo_canbus_txt",
    ]
    assert all(sample.url.startswith("https://") for sample in samples if sample.enabled)
    assert [sample.key for sample in samples if not sample.enabled] == [
        "automotive_docx_exclusion",
        "automotive_pptx_exclusion",
    ]
    assert all(sample.exclusion_reason for sample in samples if not sample.enabled)


def test_manifest_validation_rejects_enabled_sample_with_mismatched_mime_type():
    invalid = PublicSample(
        key="bad_pdf",
        filename="bad.pdf",
        url="https://example.org/bad.pdf",
        expected_mime_types=("image/png",),
        anchor_query="automotive",
    )

    with pytest.raises(ValueError, match="bad_pdf.*application/pdf"):
        validate_manifest((invalid,))


def test_report_serialization_writes_json_and_markdown_with_required_evidence(tmp_path):
    report = {
        "status": "passed",
        "started_at": "2026-07-16T09:00:00+08:00",
        "finished_at": "2026-07-16T09:00:03+08:00",
        "runtime_root": "/tmp/pka-public-ingest-example",
        "samples": [
            {
                "key": "unece_r154_docx",
                "url": "https://wiki.unece.org/example.docx",
                "sha256": "abc123",
                "upload": {"status": "ok", "source_id": "source_1"},
                "quality": {"status": "ok"},
                "coverage": {"status": "complete"},
                "chunks": 4,
                "recall": {"fts": True, "vector": True},
                "duplicate": {"blocked": True},
                "delete_reupload": {"deleted": True, "reuploaded": True},
            }
        ],
        "failures": [],
    }

    paths = serialize_report(report, tmp_path, timestamp="20260716_090003")

    saved = json.loads(paths["json"].read_text(encoding="utf-8"))
    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert saved == report
    assert "# PKA General Content Ingest Verification" in markdown
    assert "unece_r154_docx" in markdown
    assert "abc123" in markdown
    assert "duplicate" in markdown
    assert "delete/re-upload" in markdown


def test_report_serialization_labels_local_sample_provenance(tmp_path):
    report = {
        "status": "passed",
        "samples": [{
            "key": "local_functional_medicine",
            "local_path": "/Users/tz/Desktop/functional_medicine.docx",
            "sha256": "localhash",
            "upload": {"status": "ok"},
            "coverage": {"status": "complete"},
            "chunks": 2,
            "recall": {"query": True, "source_count": 1},
            "duplicate": {"blocked": True},
            "delete_reupload": {"deleted": True, "reuploaded": True},
        }],
        "failures": [],
    }

    paths = serialize_report(report, tmp_path, timestamp="20260716_local")
    markdown = paths["markdown"].read_text(encoding="utf-8")

    assert "# PKA General Content Ingest Verification" in markdown
    assert "local provenance: /Users/tz/Desktop/functional_medicine.docx" in markdown
