# PKA Content Deduplication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent exact duplicate files and manual text from entering PKA after the content identity is known.

**Architecture:** A local SQLite registry records SHA-256 content identities and processing state. Uploads stream into a staging file while hashing, reserve the identity before parsing, and remove staging data immediately for duplicates. Manual text uses the same registry before a source name is generated. The existing index remains unchanged for historical data; indexed raw paths are lazily backfilled into the registry.

**Tech Stack:** Python standard library `hashlib` and `sqlite3`, FastAPI, pytest.

## Global Constraints

- Exact duplicates must not trigger permanent raw-file save, parser execution, OCR task creation, embedding, or index write.
- No historical raw file or index deletion in this change.
- Preserve existing `/api/ingest/file`, `/api/ingest/files`, and `/api/ingest/text` compatibility while adding explicit duplicate states.
- Do not run Git write operations.

---

### Task 1: Local content-identity registry

**Files:**
- Create: `engine/ingest_registry.py`
- Test: `tests/test_ingest_registry.py`

**Interfaces:**
- Produces: `ContentRegistry.reserve`, `mark_indexed`, `mark_failed`, `lookup`, and `sha256_text`.

- [x] Write failing registry tests for new, indexed duplicate, processing duplicate, and failed retry states.
- [x] Run `python3 -m pytest -q tests/test_ingest_registry.py` and observe failure.
- [x] Implement the SQLite registry and hashing helpers.
- [x] Rerun the registry tests and observe success.

### Task 2: File and OCR duplicate gate

**Files:**
- Modify: `server.py`
- Test: `tests/test_generator_api.py`, `tests/test_async_ocr_pipeline.py`

**Interfaces:**
- Consumes: `ContentRegistry` reservation result.
- Produces: file response statuses `duplicate` and `duplicate_pending`.

- [x] Write failing API tests proving duplicate file uploads never invoke `parse_file` or `indexer.upsert` and duplicate pending uploads do not create another OCR task.
- [x] Run the focused tests and observe failure.
- [x] Stream upload bytes to staging while calculating SHA-256; reserve the identity before parsing; remove staging data for duplicates; update the registry after sync or async indexing.
- [x] Rerun focused API and OCR tests and observe success.

### Task 3: Manual text and batch-feedback duplicate contract

**Files:**
- Modify: `server.py`, `static/app.js`
- Modify: `tests/test_generator_api.py`, `tests/test_project_files.py`

**Interfaces:**
- Consumes: normalized text content hash and batch `duplicates` counter.
- Produces: manual-text duplicate response and UI feedback that names duplicate files.

- [x] Write failing tests for repeated text and duplicate batch result display.
- [x] Run focused tests and observe failure.
- [x] Add the text reservation gate and duplicate feedback rendering.
- [x] Rerun the focused tests and observe success.

### Task 4: Regression verification

**Files:**
- Test: affected ingestion, async OCR, and project-file suites.

- [x] Run `python3 -m pytest -q tests/test_ingest_registry.py tests/test_generator_api.py tests/test_async_ocr_pipeline.py tests/test_project_files.py`.
- [x] Run `node --check static/app.js && git diff --check`.
