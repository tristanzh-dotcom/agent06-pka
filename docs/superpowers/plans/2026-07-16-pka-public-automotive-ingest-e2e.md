# PKA Public Automotive Ingest E2E Implementation Plan

> **For agentic workers:** Execute this plan inline because the local disposable server, downloaded fixture corpus, and browser smoke test share one isolated runtime. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce reproducible evidence of PKA ingestion quality against public automotive documents without modifying the user knowledge base.

**Architecture:** Add a standalone verification runner that creates a temporary config and isolated data root, downloads a bounded public corpus, starts PKA on loopback, uploads each file through production APIs, polls OCR tasks, verifies source metadata plus FTS/vector recall, exercises duplicate/delete behavior, and emits JSON/Markdown reports. Browser smoke validation uses the same disposable server.

**Tech Stack:** Python 3, FastAPI/Uvicorn, httpx, Ollama bge-m3, PaddleOCR, Chroma, FTS5, browser automation.

## Global Constraints

- Never read, write, clear, or query the current configured PKA data directory.
- Download only the documented public URLs; record SHA-256 and response metadata.
- Bind the disposable process only to `127.0.0.1` on an unused non-default port.
- Disable Volcengine/cloud OCR; public image data is processed only by local PaddleOCR.
- Treat quality-gated zero-index outcomes as valid evidence, not automatic failures.
- Do not execute Git write operations.

---

### Task 1: Implement a reproducible isolated verification runner

**Files:**
- Create: `scripts/verify_public_automotive_ingest.py`
- Test: `tests/test_verify_public_automotive_ingest.py`

**Interfaces:**
- Produces: `python3 scripts/verify_public_automotive_ingest.py --report-dir <path>`.
- Produces: JSON and Markdown report containing sample provenance, upload state, quality, coverage, chunks, recall, duplicate, and delete/re-upload evidence.

- [ ] Write deterministic tests for manifest validation and report serialization without downloading, OCR, or starting a server.
- [ ] Run the tests and confirm failure before the runner exists.
- [ ] Implement fixed public-sample manifest, MIME validation, SHA-256 logging, and temporary runtime/config creation.
- [ ] Implement server lifecycle control, multipart upload, OCR task polling, source list/delete, FTS/vector recall checks, duplicate checks, and report generation.
- [ ] Run the deterministic runner tests and `python3 scripts/verify_public_automotive_ingest.py --help`.

### Task 2: Run the public corpus through the production backend

**Files:**
- Create at runtime only: `/tmp/pka-public-ingest-e2e-*`
- Create: `diagnostics/public-ingest-e2e-<timestamp>.json`
- Create: `diagnostics/public-ingest-e2e-<timestamp>.md`

**Interfaces:**
- Consumes: public URLs from the approved design and the production `/api/ingest/file`, `/api/tasks`, `/api/ingest/sources`, and source-index APIs.
- Produces: per-format pass/conditional-pass/fail classification with direct evidence.

- [ ] Run the runner with the real local Ollama and PaddleOCR configuration.
- [ ] Inspect every terminal upload status and require zero chunks for all rejected quality states.
- [ ] Verify expected anchors through FTS and vector retrieval for every indexed source.
- [ ] Verify unchanged re-upload is blocked; delete one source and verify it can be re-uploaded.
- [ ] Preserve all downloaded fixtures and diagnostics only under the disposable test root unless a report is copied into `diagnostics/`.

### Task 3: Browser smoke verification and final assessment

**Files:**
- Create: `diagnostics/public-ingest-e2e-<timestamp>.md`

**Interfaces:**
- Consumes: disposable server URL and an indexed representative document.
- Produces: visible upload status/source-list/delete evidence and a final issue classification.

- [ ] Upload one representative Office/PDF document through the browser UI.
- [ ] Verify visible quality/coverage status and source-list entry.
- [ ] Delete the same source from the UI and verify it disappears from the list.
- [ ] Terminate the disposable server and verify the configured user data directory has not changed.
- [ ] Run focused runner tests, relevant ingestion regression tests, `node --check static/app.js`, and `git diff --check`.
