"""Isolated end-to-end verification for public automotive ingest samples.

The deterministic helpers in this module deliberately do not download samples or
start PKA.  A live invocation creates every mutable path under a fresh directory
in ``/tmp`` before it fetches the approved public manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
POLL_SECONDS = 2.0
POLL_TIMEOUT_SECONDS = 180.0


def ensure_project_import_path() -> None:
    """Allow the standalone script to import PKA modules after server startup."""
    project_root = str(PROJECT_ROOT)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)


ensure_project_import_path()


@dataclass(frozen=True)
class PublicSample:
    key: str
    filename: str
    url: str
    expected_mime_types: tuple[str, ...]
    anchor_query: str
    enabled: bool = True
    exclusion_reason: str = ""
    allow_quality_accept: bool = False


@dataclass(frozen=True)
class LocalSample:
    key: str
    filename: str
    path: str
    mime_type: str
    anchor_query: str


def parse_local_sample(spec: str) -> LocalSample:
    """Parse an explicit local `PATH::QUERY` E2E sample without reading its content."""
    path_text, delimiter, query = str(spec or "").rpartition("::")
    path = Path(path_text).expanduser()
    if not delimiter or not path_text.strip() or not query.strip():
        raise ValueError("local sample must use PATH::QUERY")
    if not path.is_file():
        raise ValueError(f"local sample does not exist: {path}")
    mime_type, _ = mimetypes.guess_type(path.name)
    if not mime_type:
        raise ValueError(f"local sample MIME type is not supported: {path.name}")
    key_stem = re.sub(r"[^\w]+", "_", path.stem.lower()).strip("_") or "sample"
    return LocalSample(
        key=f"local_{key_stem}",
        filename=path.name,
        path=str(path),
        mime_type=mime_type,
        anchor_query=query.strip(),
    )


PUBLIC_SAMPLE_MANIFEST = (
    PublicSample("automotive_docx_exclusion", "automotive_public.docx", "", ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",), "automotive", enabled=False, exclusion_reason="The approved UNECE DOCX returned HTTP 403 from this execution network; do not substitute a non-automotive fixture or bypass source access controls."),
    PublicSample("automotive_pptx_exclusion", "automotive_public.pptx", "", ("application/vnd.openxmlformats-officedocument.presentationml.presentation",), "automotive", enabled=False, exclusion_reason="The approved UNECE PPTX returned HTTP 403 from this execution network; do not substitute a non-automotive fixture or bypass source access controls."),
    PublicSample("ons_vehicle_registrations_xlsx", "smmt_vehicle_registrations.xlsx", "https://www.ons.gov.uk/file?uri=%2Feconomy%2Feconomicoutputandproductivity%2Foutput%2Fdatasets%2Fuknewvehicleregistrationsandproduction%2F2026%2Fsmmtvehicleregandproddataset090726.xlsx", ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",), "vehicle registrations production"),
    PublicSample("nhtsa_automotive_pdf", "MC-10249194-0001.pdf", "https://static.nhtsa.gov/odi/tsbs/2024/MC-10249194-0001.pdf", ("application/pdf",), "vehicle service bulletin", allow_quality_accept=True),
    PublicSample("apollo_autonomous_vehicle_png", "cyber_monitor.png", "https://raw.githubusercontent.com/ApolloAuto/apollo/master/cyber/docs/images/cyber_monitor.png", ("image/png",), "autonomous vehicle cyber monitor", allow_quality_accept=True),
    PublicSample("nuscenes_can_bus_markdown", "nuscenes_can_bus_README.md", "https://raw.githubusercontent.com/nutonomy/nuscenes-devkit/refs/heads/master/python-sdk/nuscenes/can_bus/README.md", ("text/plain", "text/markdown"), "CAN bus vehicle monitor"),
    PublicSample("apollo_canbus_txt", "canbus_conf.pb.txt", "https://raw.githubusercontent.com/ApolloAuto/apollo/master/modules/canbus/conf/canbus_conf.pb.txt", ("text/plain",), "canbus vehicle chassis"),
)


def validate_manifest(samples: Iterable[PublicSample]) -> tuple[PublicSample, ...]:
    """Reject ambiguous or non-public manifest entries before any network I/O."""
    validated = tuple(samples)
    keys: set[str] = set()
    for sample in validated:
        if not sample.key or sample.key in keys:
            raise ValueError(f"manifest sample key must be unique and non-empty: {sample.key!r}")
        keys.add(sample.key)
        if not sample.filename or not sample.expected_mime_types or not sample.anchor_query:
            raise ValueError(f"{sample.key} is missing filename, MIME type, or anchor query")
        if sample.enabled:
            if not sample.url.startswith("https://"):
                raise ValueError(f"{sample.key} must use a public https URL")
            guessed_mime, _ = mimetypes.guess_type(sample.filename)
            if guessed_mime and guessed_mime not in sample.expected_mime_types:
                raise ValueError(f"{sample.key} filename implies {guessed_mime}, not {sample.expected_mime_types}")
        elif not sample.exclusion_reason:
            raise ValueError(f"{sample.key} exclusion must document its reason")
    return validated


def serialize_report(report: dict[str, Any], report_dir: str | Path, *, timestamp: str | None = None) -> dict[str, Path]:
    """Write stable JSON and human-readable Markdown evidence reports."""
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = timestamp or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = report_dir / f"general_ingest_{timestamp}.json"
    markdown_path = report_dir / f"general_ingest_{timestamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# PKA General Content Ingest Verification",
        "",
        f"- status: {report.get('status', 'unknown')}",
        f"- started_at: {report.get('started_at', '')}",
        f"- finished_at: {report.get('finished_at', '')}",
        f"- runtime_root: {report.get('runtime_root', '')}",
        "",
        "## Sample evidence",
        "",
        "| sample | SHA-256 | upload | quality | coverage | chunks | server query | duplicate | delete/re-upload |",
        "|---|---|---|---|---|---:|---|---|---|",
    ]
    for sample in report.get("samples", []):
        upload = sample.get("upload") or {}
        quality = sample.get("quality") or {}
        coverage = sample.get("coverage") or {}
        recall = sample.get("recall") or {}
        duplicate = sample.get("duplicate") or {}
        lifecycle = sample.get("delete_reupload") or {}
        lines.append(
            "| {key} | {sha} | {upload} | {quality} | {coverage} | {chunks} | matched={fts}; source_chunks={vector} | {duplicate} | {lifecycle} |".format(
                key=sample.get("key", ""), sha=sample.get("sha256", ""), upload=upload.get("status", ""),
                quality=quality.get("status", ""), coverage=coverage.get("status", ""), chunks=sample.get("chunks", 0),
                fts=recall.get("query", False), vector=recall.get("source_count", 0),
                duplicate=duplicate.get("blocked", False), lifecycle="deleted={}; reuploaded={}".format(lifecycle.get("deleted", False), lifecycle.get("reuploaded", False)),
            )
        )
        if sample.get("url"):
            lines.append(f"  - provenance: {sample['url']}")
        if sample.get("local_path"):
            lines.append(f"  - local provenance: {sample['local_path']}")
    failures = report.get("failures") or []
    lines.extend(["", "## Failures", ""])
    lines.extend([f"- {failure}" for failure in failures] or ["- none"])
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _create_isolated_runtime() -> tuple[Path, Path, int]:
    root = Path(tempfile.mkdtemp(prefix="pka-public-automotive-ingest-", dir=tempfile.gettempdir()))
    data_dir = root / "PKA_Data"
    port = _free_loopback_port()
    static_link = root / "static"
    static_link.symlink_to(PROJECT_ROOT / "static", target_is_directory=True)
    config = {
        "data_dir": str(data_dir),
        "chroma": {"collection_name": "pka_public_automotive", "persist_dir": str(data_dir / ".vector")},
        "fts5": {"db_path": str(data_dir / ".fts5" / "pka.db")},
        "embedding": {"host": "http://127.0.0.1:11434", "model": "bge-m3", "query_prefix": ""},
        "ocr": {"provider_order": ["paddle"], "paddle": {"enabled": True, "lang": "en", "use_angle_cls": True, "dpi": 150}, "volcengine": {"enabled": False, "endpoint": "", "api_key": ""}},
        "deepseek": {"endpoint": "", "api_key": ""},
        "generation": {"endpoint": "", "api_key": ""},
        "reranker": {"enabled": False},
        "ingest": {"max_sync_chunks_per_file": 5000},
        "server": {"host": "127.0.0.1", "port": port},
    }
    (root / "config.yaml").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return root, data_dir, port


def _download_sample(sample: PublicSample, downloads_dir: Path) -> dict[str, Any]:
    request = urllib.request.Request(sample.url, headers={"User-Agent": "PKA-public-ingest-verifier/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        content_type = response.headers.get_content_type().lower()
        if content_type not in sample.expected_mime_types:
            raise ValueError(f"{sample.key} returned MIME {content_type}, expected {sample.expected_mime_types}")
        declared_size = response.headers.get("Content-Length")
        if declared_size and int(declared_size) > MAX_DOWNLOAD_BYTES:
            raise ValueError(f"{sample.key} exceeds {MAX_DOWNLOAD_BYTES} byte download limit")
        body = response.read(MAX_DOWNLOAD_BYTES + 1)
    if len(body) > MAX_DOWNLOAD_BYTES:
        raise ValueError(f"{sample.key} exceeds {MAX_DOWNLOAD_BYTES} byte download limit")
    path = downloads_dir / sample.filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return {"path": path, "mime_type": content_type, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body), "retrieved_at": _now()}


def _copy_local_sample(sample: LocalSample, downloads_dir: Path) -> dict[str, Any]:
    source = Path(sample.path)
    size = source.stat().st_size
    if size > MAX_DOWNLOAD_BYTES:
        raise ValueError(f"{sample.key} exceeds {MAX_DOWNLOAD_BYTES} byte upload limit")
    path = downloads_dir / sample.filename
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, path)
    body = path.read_bytes()
    return {
        "path": path,
        "mime_type": sample.mime_type,
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
        "retrieved_at": _now(),
        "local_path": sample.path,
    }


def _wait_for_server(base_url: str, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("isolated PKA server exited before becoming ready")
        try:
            if httpx.get(f"{base_url}/", timeout=1.0).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise TimeoutError("isolated PKA server did not become ready within 30 seconds")


def _upload(client: httpx.Client, sample: PublicSample | LocalSample, download: dict[str, Any]) -> dict[str, Any]:
    with Path(download["path"]).open("rb") as handle:
        response = client.post("/api/ingest/file", files={"file": (sample.filename, handle, download["mime_type"])}, data={"quality_policy": "accept" if getattr(sample, "allow_quality_accept", False) else "review"})
    response.raise_for_status()
    payload = response.json()
    if response.status_code == 202:
        task_id = payload["task_id"]
        deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            task = client.get(f"/api/tasks/{task_id}").json()
            if task.get("status") in {"completed", "failed", "review_required"}:
                payload["task"] = task
                result = task.get("result") or {}
                payload.update({"chunks": result.get("chunks_inserted", 0), "source_id": result.get("source_id", ""), "quality": result.get("quality"), "coverage": result.get("coverage", {})})
                break
            time.sleep(POLL_SECONDS)
        else:
            raise TimeoutError(f"OCR task {task_id} did not finish")
    return payload


def _recall(client: httpx.Client, sample: PublicSample | LocalSample, source_id: str) -> dict[str, Any]:
    """Exercise the server-owned hybrid retriever through the real query endpoint."""
    response = client.post("/api/query", json={"question": sample.anchor_query, "language": "en", "debug": True})
    response.raise_for_status()
    sources = []
    for line in response.text.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            event = json.loads(line.removeprefix("data: "))
        except json.JSONDecodeError:
            continue
        if event.get("type") == "sources":
            sources = event.get("sources") or []
            break
    matching = [source for source in sources if str(source.get("chunk_id") or "").startswith(f"{source_id}#")]
    return {"query": bool(matching), "source_count": len(matching), "returned_sources": len(sources)}


def run_live_verification(
    report_dir: str | Path,
    *,
    keep_runtime: bool = False,
    local_samples: Iterable[LocalSample] = (),
    include_public_samples: bool = True,
) -> tuple[dict[str, Any], dict[str, Path]]:
    public_samples = validate_manifest(PUBLIC_SAMPLE_MANIFEST) if include_public_samples else ()
    local_samples = tuple(local_samples)
    sample_keys = [sample.key for sample in [*public_samples, *local_samples]]
    if len(sample_keys) != len(set(sample_keys)):
        raise ValueError("public and local sample keys must be unique")
    samples = (*public_samples, *local_samples)
    runtime_root, data_dir, port = _create_isolated_runtime()
    base_url = f"http://127.0.0.1:{port}"
    report: dict[str, Any] = {"status": "passed", "started_at": _now(), "finished_at": "", "runtime_root": str(runtime_root), "base_url": base_url, "manifest": [asdict(sample) for sample in samples], "samples": [], "failures": []}
    env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(port)], cwd=runtime_root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        _wait_for_server(base_url, process)
        with httpx.Client(base_url=base_url, timeout=180.0) as client:
            for sample in samples:
                is_public = isinstance(sample, PublicSample)
                item: dict[str, Any] = {"key": sample.key, "url": sample.url if is_public else "", "local_path": sample.path if not is_public else "", "status": "excluded" if is_public and not sample.enabled else "pending"}
                report["samples"].append(item)
                if is_public and not sample.enabled:
                    item["exclusion_reason"] = sample.exclusion_reason
                    continue
                try:
                    download = _download_sample(sample, runtime_root / "downloads") if is_public else _copy_local_sample(sample, runtime_root / "downloads")
                    item.update({key: value for key, value in download.items() if key != "path"})
                    uploaded = _upload(client, sample, download)
                    item.update({"upload": {"status": uploaded.get("status"), "source_id": uploaded.get("source_id", "")}, "quality": uploaded.get("quality") or {}, "coverage": uploaded.get("coverage") or {}, "chunks": uploaded.get("chunks", 0)})
                    source_id = str(uploaded.get("source_id") or "")
                    if uploaded.get("status") == "review_required":
                        item["status"] = "conditional_pass" if item["chunks"] == 0 else "failed"
                        item["recall"] = {"fts": False, "vector": False}
                    else:
                        if not source_id or int(item["chunks"] or 0) <= 0:
                            raise AssertionError("accepted source must have a source_id and indexed chunks")
                        item["recall"] = _recall(client, sample, source_id)
                        if not item["recall"]["query"]:
                            raise AssertionError("expected source was not returned by the server-owned hybrid query")
                        duplicate = _upload(client, sample, download)
                        item["duplicate"] = {"blocked": duplicate.get("status") in {"duplicate", "duplicate_pending"}, "status": duplicate.get("status")}
                        if not item["duplicate"]["blocked"]:
                            raise AssertionError("unchanged re-upload was not duplicate-blocked")
                        deleted = client.delete(f"/api/ingest/sources/{source_id}")
                        deleted.raise_for_status()
                        reuploaded = _upload(client, sample, download)
                        item["delete_reupload"] = {"deleted": deleted.json().get("deleted_source_id") == source_id, "reuploaded": reuploaded.get("status") == "ok"}
                        if not all(item["delete_reupload"].values()):
                            raise AssertionError("delete/re-upload lifecycle did not complete")
                        item["status"] = "passed"
                except Exception as exc:
                    item["status"] = "failed"
                    item["error"] = str(exc)
                    item["traceback"] = traceback.format_exc()
                    report["failures"].append(f"{sample.key}: {exc}")
            if report["failures"]:
                report["status"] = "failed"
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        report["finished_at"] = _now()
    paths = serialize_report(report, report_dir)
    if not keep_runtime:
        shutil.rmtree(runtime_root, ignore_errors=True)
        report["runtime_root"] = "removed (isolated /tmp runtime)"
        paths = serialize_report(report, report_dir)
    return report, paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify PKA general-content ingest in an isolated /tmp runtime.")
    parser.add_argument("--report-dir", required=True, help="Directory for JSON and Markdown evidence reports.")
    parser.add_argument("--keep-runtime", action="store_true", help="Preserve the isolated /tmp runtime for diagnosis.")
    parser.add_argument("--local-sample", action="append", default=[], metavar="PATH::QUERY", help="Local file and its retrieval anchor; may be repeated. Local samples run without the public matrix unless --include-public-samples is set.")
    parser.add_argument("--include-public-samples", action="store_true", help="Run the public matrix together with explicitly supplied local samples.")
    args = parser.parse_args(argv)
    local_samples = tuple(parse_local_sample(spec) for spec in args.local_sample)
    report, paths = run_live_verification(
        args.report_dir,
        keep_runtime=args.keep_runtime,
        local_samples=local_samples,
        include_public_samples=args.include_public_samples or not local_samples,
    )
    print(json.dumps({"status": report["status"], "json_report": str(paths["json"]), "markdown_report": str(paths["markdown"])}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
