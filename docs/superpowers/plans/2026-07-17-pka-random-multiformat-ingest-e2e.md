# PKA Random Multi-Format Ingest E2E Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce reproducible quality evidence from a new, diverse public batch covering every supported PKA file extension.

**Architecture:** Materialize a URL manifest into a temporary corpus, validate file signatures and hashes, then pass every file to the existing isolated general-content E2E runner as a local sample. Merge runner evidence with URL provenance and classify expected fail-closed image/scanned outcomes separately from defects.

**Tech Stack:** Python 3, curl/httpx, FastAPI/Uvicorn, local Ollama bge-m3, local PaddleOCR, Chroma, FTS5, pytest.

## Global Constraints

- Do not reuse the previous verification files.
- Never read or mutate the configured user PKA data directory.
- Disable cloud OCR and do not invoke DeepSeek.
- Cover DOCX, PPTX, XLSX, PDF, PNG, JPG/JPEG, WebP, TXT and Markdown.
- Record URL, timestamp, SHA-256, MIME, size, anchor and terminal outcome.
- Do not execute Git write operations.

---

### Task 1: Public sample manifest

**Files:**
- Create at runtime: `/tmp/pka-random-multiformat-*/manifest.json`

**Interfaces:**
- Produces: records with `key`, `format`, `url`, `filename`, `anchor_query`, `expected_outcome`.

- [x] Select about eighteen new files across at least four independent public domains.
- [x] Resolve direct download URLs and reject redirects to HTML/login pages.
- [x] Download with bounded time and size, then verify ZIP/PDF/image/text signatures.
- [x] Record hashes, MIME types, sizes and retrieval timestamps.

### Task 2: Isolated production-path verification

**Files:**
- Create: `diagnostics/random_multiformat_ingest_<timestamp>.json`
- Create: `diagnostics/random_multiformat_ingest_<timestamp>.md`

**Interfaces:**
- Consumes: `PATH::QUERY` local sample specifications.
- Produces: upload, quality, coverage, chunks, recall, duplicate and delete/re-upload results.

- [x] Run the existing verifier with every successfully materialized sample.
- [x] Poll image/PDF OCR tasks to a terminal state.
- [x] Require `high` plus anchor recall for readable samples.
- [x] Require zero chunks for every `review_required` conditional pass.
- [x] Preserve initial diagnostics before any repair.

### Task 3: Failure diagnosis and repair

**Files:**
- Modify only when a reproducible PKA defect is found: `engine/*`, `server.py`, `tests/*`.

**Interfaces:**
- Produces: smallest failing regression and minimal behavior-preserving fix.

- [x] Classify each failure before changing code.
- [x] For a PKA defect, write and run the smallest failing test.
- [x] Implement the minimal fix and rerun the affected sample plus regression test.
- [x] Do not change product quality thresholds merely to make a difficult source pass.

### Task 4: Final verification

**Files:**
- Create: final JSON/Markdown report under `diagnostics/`.

**Interfaces:**
- Produces: final per-format disposition and residual limitations.

- [x] Rerun the complete successfully downloaded corpus.
- [x] Run `python3 -m pytest -q`.
- [x] Run `node --check static/app.js`, Python compile checks and `git diff --check`.
- [x] Verify `git status` and report any files awaiting Agent08 integration.
