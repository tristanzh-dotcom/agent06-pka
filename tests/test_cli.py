import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from engine.config import load_config


def test_cli_serve_prints_uvicorn_command_without_starting_server():
    config = load_config("config.yaml")
    result = subprocess.run(
        [sys.executable, "cli.py", "serve", "--dry-run"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert f" -m uvicorn server:app --host {config['server']['host']} --port {config['server']['port']}" in result.stdout


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "cli.py", *args],
        capture_output=True,
        text=True,
    )


class FakePKAHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/stats":
            self._json({"indexed_files": 2, "total_chunks": 5, "last_updated": "2026-06-04T12:00:00"})
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)
        self.server.requests.append((self.path, self.headers.get("Content-Type", ""), body))
        if self.path == "/api/ingest/text":
            self._json({"status": "ok", "chunks": 1, "source_name": "manual", "chunk_ids": ["manual#0"]})
            return
        if self.path == "/api/ingest/file":
            self._json({"status": "ok", "chunks": 2, "source_name": "report.docx", "chunk_ids": ["report.docx#0"]})
            return
        if self.path == "/api/ingest/clear":
            self._json({"status": "ok", "message": "知识库已清空"})
            return
        if self.path == "/api/query":
            payload = (
                'data: {"type": "token", "content": "根据"}\n\n'
                'data: {"type": "token", "content": "资料回答。"}\n\n'
                'data: {"type": "sources", "sources": [{"source_name": "org.txt", "chunk_index": 0}]}\n\n'
                'data: {"type": "done"}\n\n'
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(payload.encode("utf-8"))
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        return

    def _json(self, payload):
        import json

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_fake_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakePKAHandler)
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_cli_ingest_text_outputs_json():
    server = start_fake_server()
    try:
        result = run_cli("--base-url", f"http://127.0.0.1:{server.server_port}", "ingest", "--text", "组织架构调整")
    finally:
        server.shutdown()

    assert result.returncode == 0
    assert '"status": "ok"' in result.stdout
    assert server.requests[0][0] == "/api/ingest/text"


def test_cli_ingest_file_uploads_multipart_and_outputs_json(tmp_path):
    upload = tmp_path / "report.txt"
    upload.write_text("报告内容", encoding="utf-8")
    server = start_fake_server()
    try:
        result = run_cli("--base-url", f"http://127.0.0.1:{server.server_port}", "ingest", "--file", str(upload))
    finally:
        server.shutdown()

    assert result.returncode == 0
    assert '"source_name": "report.docx"' in result.stdout
    assert server.requests[0][0] == "/api/ingest/file"
    assert "multipart/form-data" in server.requests[0][1]


def test_cli_stats_outputs_json():
    server = start_fake_server()
    try:
        result = run_cli("--base-url", f"http://127.0.0.1:{server.server_port}", "stats")
    finally:
        server.shutdown()

    assert result.returncode == 0
    assert '"total_chunks": 5' in result.stdout


def test_cli_clear_posts_clear_endpoint_and_outputs_json():
    server = start_fake_server()
    try:
        result = run_cli("--base-url", f"http://127.0.0.1:{server.server_port}", "clear")
    finally:
        server.shutdown()

    assert result.returncode == 0
    assert '"status": "ok"' in result.stdout
    assert server.requests[0][0] == "/api/ingest/clear"


def test_cli_query_collects_sse_tokens_and_sources_as_json():
    server = start_fake_server()
    try:
        result = run_cli("--base-url", f"http://127.0.0.1:{server.server_port}", "query", "怎么调整组织？")
    finally:
        server.shutdown()

    assert result.returncode == 0
    assert '"answer": "根据资料回答。"' in result.stdout
    assert '"source_name": "org.txt"' in result.stdout


def test_cli_reports_service_not_running_as_json():
    result = run_cli("--base-url", "http://127.0.0.1:9", "stats")

    assert result.returncode == 1
    assert '"status": "error"' in result.stdout
    assert "PKA service is not running" in result.stdout
