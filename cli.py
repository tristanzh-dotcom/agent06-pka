import argparse
import json
import mimetypes
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Dict, Iterable, Tuple

from engine.config import load_config


def main() -> int:
    config = load_config("config.yaml")
    parser = argparse.ArgumentParser(prog="obs-asset")
    parser.add_argument("--base-url", default=f"http://localhost:{config['server']['port']}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest")
    ingest_group = ingest_parser.add_mutually_exclusive_group(required=True)
    ingest_group.add_argument("--text")
    ingest_group.add_argument("--file")

    query_parser = subparsers.add_parser("query")
    query_parser.add_argument("question")

    subparsers.add_parser("stats")

    subparsers.add_parser("clear")

    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    if args.command == "serve":
        return _serve(config, args.dry_run)

    try:
        if args.command == "ingest":
            if args.text is not None:
                return _print_result(_post_json(args.base_url, "/api/ingest/text", {"text": args.text}))
            return _print_result(_post_file(args.base_url, "/api/ingest/file", Path(args.file)))
        if args.command == "query":
            return _print_result(_query(args.base_url, args.question))
        if args.command == "stats":
            return _print_result(_get_json(args.base_url, "/api/stats"))
        if args.command == "clear":
            return _print_result(_post_json(args.base_url, "/api/ingest/clear", {}))
    except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
        return _print_json(
            {
                "status": "error",
                "message": f"PKA service is not running or unreachable: {exc}",
            },
            exit_code=1,
        )
    except Exception as exc:
        return _print_json({"status": "error", "message": str(exc)}, exit_code=1)

    return _print_json({"status": "error", "message": "unknown command"}, exit_code=2)


def _serve(config: Dict, dry_run: bool) -> int:
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "server:app",
        "--host",
        str(config["server"]["host"]),
        "--port",
        str(config["server"]["port"]),
    ]
    if dry_run:
        print(" ".join(command))
        return 0
    return subprocess.call(command)


def _post_json(base_url: str, path: str, payload: Dict) -> Dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        _url(base_url, path),
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return _read_json(request)


def _get_json(base_url: str, path: str) -> Dict:
    request = urllib.request.Request(_url(base_url, path), method="GET")
    return _read_json(request)


def _post_file(base_url: str, path: str, file_path: Path) -> Dict:
    if not file_path.exists():
        raise FileNotFoundError(str(file_path))
    boundary = "pka-" + uuid.uuid4().hex
    content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    body = _multipart_body(
        boundary,
        "file",
        file_path.name,
        content_type,
        file_path.read_bytes(),
    )
    request = urllib.request.Request(
        _url(base_url, path),
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    return _read_json(request)


def _query(base_url: str, question: str) -> Dict:
    body = json.dumps({"question": question}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        _url(base_url, "/api/query"),
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    answer_parts = []
    sources = []
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode("utf-8")
    for payload in _parse_sse(raw):
        event_type = payload.get("type")
        if event_type == "token":
            answer_parts.append(payload.get("content", ""))
        elif event_type == "sources":
            sources = payload.get("sources", [])
        elif event_type == "error":
            return {"status": "error", "answer": "".join(answer_parts), "message": payload.get("content", "")}
    return {"status": "ok", "answer": "".join(answer_parts), "sources": sources}


def _read_json(request: urllib.request.Request) -> Dict:
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8")
        message = detail or "PKA service is not running or unreachable"
        return {"status": "error", "status_code": exc.code, "message": message}


def _multipart_body(boundary: str, field_name: str, filename: str, content_type: str, content: bytes) -> bytes:
    chunks = [
        f"--{boundary}\r\n".encode("utf-8"),
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode("utf-8"),
        f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
        content,
        b"\r\n",
        f"--{boundary}--\r\n".encode("utf-8"),
    ]
    return b"".join(chunks)


def _parse_sse(raw: str) -> Iterable[Dict]:
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block.startswith("data: "):
            continue
        data = block.removeprefix("data: ").strip()
        if data:
            yield json.loads(data)


def _url(base_url: str, path: str) -> str:
    return urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def _print_json(payload: Dict, exit_code: int = 0) -> int:
    print(json.dumps(payload, ensure_ascii=False))
    return exit_code


def _print_result(payload: Dict) -> int:
    return _print_json(payload, exit_code=1 if payload.get("status") == "error" else 0)


if __name__ == "__main__":
    sys.exit(main())
