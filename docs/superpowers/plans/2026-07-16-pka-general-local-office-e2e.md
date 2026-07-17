# PKA General Local Office E2E Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow the isolated E2E verifier to validate explicit local DOCX/PPTX samples without persisting them outside its disposable runtime.

**Architecture:** Add a local-sample parser that converts `PATH::QUERY` into the existing sample record plus a local-path field. The existing lifecycle flow consumes a unified materialized-file object, using bounded copy for local sources and bounded download for public sources.

**Tech Stack:** Python 3.9, FastAPI/HTTPX, local Ollama bge-m3, local PaddleOCR, pytest.

## Global Constraints

- All mutable verification data stays under a fresh temporary root.
- Local medical documents must not be sent to any external provider.
- Product code and the current PKA knowledge base are out of scope.
- Do not perform Git write operations.

---

### Task 1: Local sample contract

**Files:**
- Modify: `scripts/verify_public_automotive_ingest.py`
- Modify: `tests/test_verify_public_automotive_ingest.py`

**Interfaces:**
- Produces `parse_local_sample(spec: str) -> LocalSample`.
- `LocalSample` has `path`, `key`, `filename`, `mime_type`, and `anchor_query`.

- [ ] **Step 1: Write failing tests** for valid DOCX/PPTX parsing and malformed/missing inputs.
- [ ] **Step 2: Run** `python3 -m pytest -q tests/test_verify_public_automotive_ingest.py` and confirm the new tests fail because the parser does not exist.
- [ ] **Step 3: Implement** deterministic local-spec parsing with file existence and MIME validation.
- [ ] **Step 4: Run** the same test command and confirm it passes.

### Task 2: Unified local E2E execution

**Files:**
- Modify: `scripts/verify_public_automotive_ingest.py`
- Test: `tests/test_verify_public_automotive_ingest.py`

**Interfaces:**
- `run_live_verification(..., local_samples: Iterable[LocalSample] = ())` merges public and local sample evidence.
- CLI accepts repeated `--local-sample PATH::QUERY`.

- [ ] **Step 1: Write a failing deterministic report test** that expects local-path provenance without a public URL.
- [ ] **Step 2: Run** `python3 -m pytest -q tests/test_verify_public_automotive_ingest.py` and verify failure.
- [ ] **Step 3: Implement** bounded local-file copy into the temporary runtime, report local provenance, and CLI wiring.
- [ ] **Step 4: Run** focused tests, compile the runner, and inspect `--help`.

### Task 3: User-supplied Office E2E run

**Files:**
- Create: `diagnostics/general_ingest_*.json`
- Create: `diagnostics/general_ingest_*.md`

- [ ] **Step 1: Run** the verifier with the supplied DOCX and PPTX and Chinese anchor queries.
- [ ] **Step 2: Confirm** each sample completed parser, index, server-query, duplicate, delete, and re-upload checks.
- [ ] **Step 3: Run** directly affected regression tests and `git diff --check`.
