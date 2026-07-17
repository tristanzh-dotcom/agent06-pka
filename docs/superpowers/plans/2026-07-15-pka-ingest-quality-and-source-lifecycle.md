# PKA Ingest Quality and Source Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make supported document ingestion complete enough to trust, gate questionable content before indexing, and let one user replace, retain, undo or delete individual sources.

**Architecture:** Parsers emit deterministic extraction coverage; a local SQLite source registry owns source lifecycle and version lookup; UUID source IDs own chunk identity; quality and coverage metadata flow into every chunk. File upload adds explicit review/version policies, while the ingest UI renders inline actions and a managed-source list.

**Tech Stack:** Python 3, FastAPI, SQLite, ChromaDB, FTS5, python-docx, python-pptx, openpyxl, vanilla JavaScript, pytest.

## Global Constraints

- Exact duplicate content remains blocked before parsing, OCR, embedding or index writes.
- Low-quality or structurally partial content produces zero chunks unless `quality_policy=accept`.
- Replacement deletes the old source only after the new source indexes successfully.
- Existing `/api/ingest/file`, `/api/ingest/files` and `/api/ingest/text` success contracts remain compatible.
- Existing historical chunks remain readable without migration.
- Do not run Git write operations.

---

### Task 1: Structured-document extraction coverage

**Files:**
- Modify: `engine/parser.py`
- Test: `tests/test_parser.py`

**Interfaces:**
- Produces: `ParseResult.metadata["coverage"] -> {format, status, warnings, counts}`.

- [ ] Add failing parser tests for DOCX table cells, PPTX table cells and notes, and XLSX formula expressions.
- [ ] Run the four focused tests and confirm they fail because content or coverage is absent.
- [ ] Add ordered DOCX block extraction, PPTX shape/table/note extraction and paired XLSX formula/value extraction.
- [ ] Add deterministic coverage metadata to TXT/Markdown/DOCX/PPTX/PDF/XLSX/image results.
- [ ] Rerun focused and full parser tests.

### Task 2: Durable source registry and source-aware chunk identity

**Files:**
- Create: `engine/source_registry.py`
- Modify: `server.py`
- Test: `tests/test_source_registry.py`, `tests/test_ingest_quality.py`

**Interfaces:**
- Produces: `SourceRegistry.create_indexed`, `find_active_by_original_name`, `list_sources`, `get`, `mark_delete_failed`, `delete`.
- Produces: UUID `source_id` and chunk metadata keys `source_id`, `original_name`, `quality`, `coverage`.

- [ ] Add failing registry tests for create/list/version lookup/delete and deterministic legacy records.
- [ ] Add failing ingest test proving source ID changes chunk IDs and quality/coverage reach stored metadata.
- [ ] Implement the SQLite source registry and schema initialization.
- [ ] Pass parsed metadata and quality into ordinary and pre-chunked chunks.
- [ ] Register a source only after the index write succeeds.
- [ ] Rerun registry and metadata tests.

### Task 3: Single-source list, delete and undo contract

**Files:**
- Modify: `engine/indexer.py`, `engine/ingest_registry.py`, `server.py`
- Test: `tests/test_indexer_retriever.py`, `tests/test_generator_api.py`

**Interfaces:**
- Produces: `HybridIndexer.delete_source(source_id, source_name) -> int`.
- Produces: `GET /api/ingest/sources` and `DELETE /api/ingest/sources/{source_id}`.

- [ ] Add failing indexer test proving one source is removed from FTS and vector stores without affecting another.
- [ ] Add failing API test proving source deletion also removes its raw file and content identity, then permits re-upload.
- [ ] Implement vector/FTS deletion by source metadata with legacy source-name fallback.
- [ ] Implement source-list backfill, safe raw deletion and source/content registry cleanup.
- [ ] Rerun source lifecycle tests.

### Task 4: Low-quality review gate

**Files:**
- Modify: `engine/ingest_registry.py`, `server.py`
- Test: `tests/test_ingest_quality.py`, `tests/test_generator_api.py`

**Interfaces:**
- Consumes: `quality_policy` form value `review|accept`.
- Produces: `review_required` response with zero chunks and review details.

- [ ] Add failing tests proving low PDF, low image OCR and partial structured coverage do not index by default.
- [ ] Add failing test proving `quality_policy=accept` indexes and persists the reviewed quality state.
- [ ] Add a retryable `review_required` content-registry state.
- [ ] Gate low/partial results before `_ingest_parsed_result`; remove unaccepted raw data so resubmission uses the original path.
- [ ] Update batch counters and response status for review-required files.
- [ ] Rerun focused quality and duplicate regressions.

### Task 5: Same-name version conflict, replace and keep

**Files:**
- Modify: `server.py`, `engine/source_registry.py`
- Test: `tests/test_generator_api.py`

**Interfaces:**
- Consumes: `version_policy` form value `review|replace|keep`.
- Produces: `version_conflict` response and `existing_source` payload.

- [ ] Add failing test proving different bytes with an active same original name return `version_conflict` before parser invocation.
- [ ] Add failing test proving `keep` indexes both sources.
- [ ] Add failing test proving `replace` preserves the old source on new-index failure and removes it after success.
- [ ] Implement active-name lookup before parsing and policy handling after exact-duplicate reservation.
- [ ] Rerun version and batch regressions.

### Task 6: Ingest-page source management and inline decisions

**Files:**
- Modify: `static/index.html`, `static/app.js`, `static/style.css`
- Test: `tests/test_project_files.py`

**Interfaces:**
- Consumes: source list/delete APIs and `review_required|version_conflict` upload responses.
- Produces: inline `仍然入库`, `替换旧版本`, `同时保留`, `取消`, `撤销本次录入`, and per-source `删除` actions.

- [ ] Add failing static contracts for managed-source section and all inline actions.
- [ ] Add source list rendering, deletion refresh and immediate undo.
- [ ] Add per-slot policy resubmission using the retained `File` object.
- [ ] Add theme-token-following styles for source rows and decision buttons.
- [ ] Run frontend contracts and `node --check static/app.js`.

### Task 7: Regression verification

**Files:**
- Test: ingestion, parser, indexer, async OCR and project-file suites.

- [ ] Run `python3 -m pytest -q tests/test_parser.py tests/test_quality.py tests/test_chunker.py tests/test_ingest_registry.py tests/test_source_registry.py tests/test_ingest_quality.py tests/test_async_ocr_pipeline.py tests/test_indexer_retriever.py tests/test_generator_api.py`.
- [ ] Run focused ingest-page contracts in `tests/test_project_files.py`.
- [ ] Run `node --check static/app.js` and `git diff --check`.
- [ ] Report unrelated pre-existing suite failures separately and do not alter unrelated shared-Web contracts.
