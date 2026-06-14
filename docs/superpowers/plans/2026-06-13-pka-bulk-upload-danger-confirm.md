# PKA Bulk Upload And Danger Confirm Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add multi-file knowledge ingestion with a visible upload queue, and harden the clear-knowledge action with typed confirmation.

**Architecture:** Keep the existing single-file endpoint for compatibility, but add `POST /api/ingest/files` for batch uploads. The ingest page owns client-side file queue display and batch submission; settings owns typed confirmation before calling the existing clear API.

**Tech Stack:** FastAPI, vanilla HTML/CSS/JS, pytest/TestClient, existing static contract tests.

---

### Task 1: Batch Upload API Contract

**Files:**
- Modify: `/Users/tristanzh/agent/Personal-Asset/tests/test_generator_api.py`
- Modify: `/Users/tristanzh/agent/Personal-Asset/server.py`

- [ ] Write a failing API test for `POST /api/ingest/files` that sends multiple files and expects per-file results, total chunk count, and raw file preservation.
- [ ] Run the single failing test and verify it fails because the endpoint does not exist.
- [ ] Extract the existing single-file ingest logic into a helper and wire both `/api/ingest/file` and `/api/ingest/files` through it.
- [ ] Run the API test and verify it passes.

### Task 2: Upload Queue UI Contract

**Files:**
- Modify: `/Users/tristanzh/agent/Personal-Asset/tests/test_project_files.py`
- Modify: `/Users/tristanzh/agent/Personal-Asset/static/index.html`
- Modify: `/Users/tristanzh/agent/Personal-Asset/static/app.js`
- Modify: `/Users/tristanzh/agent/Personal-Asset/static/style.css`

- [ ] Write a failing static contract test requiring `multiple`, hidden native input, queue container, summary, clear button, and batch endpoint usage.
- [ ] Run the failing test and verify the current single-file layout fails it.
- [ ] Replace the raw file input layout with a compact upload panel and selected-file list.
- [ ] Implement client-side selected file rendering, removal, clear, and one batch submit to `api/ingest/files`.
- [ ] Run the frontend contract test and verify it passes.

### Task 3: Clear Knowledge Typed Confirmation

**Files:**
- Modify: `/Users/tristanzh/agent/Personal-Asset/tests/test_project_files.py`
- Modify: `/Users/tristanzh/agent/Personal-Asset/static/settings.html`
- Modify: `/Users/tristanzh/agent/Personal-Asset/static/app.js`
- Modify: `/Users/tristanzh/agent/Personal-Asset/static/style.css`

- [ ] Write a failing static contract test requiring a typed confirmation input with expected phrase `清空知识库`, disabled clear button by default, and no bare `confirm()`.
- [ ] Run the failing test and verify it fails on current settings UI.
- [ ] Add the typed confirmation input and button enablement logic.
- [ ] Run the contract test and verify it passes.

### Task 4: Verification

**Files:**
- Verify all files above.

- [ ] Run `/Users/tristanzh/agent/Personal-Asset` pytest.
- [ ] Run browser or DOM verification for the upload panel if the local service is healthy.
- [ ] Report any unrelated failures separately.
