# PKA Answer Destinations Function Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to execute this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the three confirmed PKA answer destinations truthful, idempotent, local-first operations with governed Obsidian publication and explicit PKA retrieval promotion.

**Architecture:** Agent06 stores and reuses one AnswerAsset per answer snapshot. Its local promotion service writes deterministic generated-secondary Markdown and indexes it into FTS/vector retrieval. Agent10 remains the only Obsidian writer. The final publish step records the indexed status in the one Obsidian asset; partial states stay in the local manifest and are returned to the browser.

**Tech Stack:** FastAPI, Python stdlib JSON/filesystem, existing HybridIndexer/Chroma/FTS, Agent10 localhost HTTP API, vanilla JavaScript, pytest.

## Global Constraints

- `保存到本地资料` has no Obsidian or RAG side effect.
- `发布到 Obsidian` has no RAG indexing side effect.
- `加入 PKA 问答检索` rejects `source_status=no_answer`, indexes as generated secondary context, then publishes to Agent10.
- Generated output is never primary evidence and never invokes an LLM in these actions.
- Repeated clicks reuse the same local asset and Agent10 asset; notes are never updated for an idempotent reuse.
- The Agent10 token is read only from its runtime file and never exposed to browser code or response payloads.
- Agent05 is excluded. No shared Web visual changes are in scope.
- Git submission belongs to Agent08.

---

### Task 1: Add idempotent local destination state

**Files:** `engine/answer_assets.py`, `server.py`, `tests/test_answer_result_operations.py`

- [ ] Write failing tests for stable `operation_key`, repeat-save reuse, and local-only response state.
- [ ] Implement AnswerAsset operation-key lookup, atomic manifest state updates, and `POST /api/answer-assets/save-local`.
- [ ] Verify focused tests pass.

### Task 2: Add governed Obsidian publication

**Files:** `server.py`, `web/config/platform-backend-processes.json`, `tests/test_answer_result_operations.py`

- [ ] Write failing tests for a saved-then-published response and a local-only partial response when Agent10 is unavailable.
- [ ] Implement `POST /api/answer-assets/publish-obsidian`, reuse the local operation asset, call Agent10 without logging its token, and persist publication state.
- [ ] Add Agent06 runtime `AGENT10_BASE_URL` and `AGENT10_CONTROL_TOKEN_FILE` placeholders/paths to the managed backend spec.
- [ ] Verify focused tests pass.

### Task 3: Add generated-secondary RAG promotion

**Files:** `engine/generated_knowledge.py`, `engine/indexer.py`, `engine/models.py`, `engine/generator.py`, `server.py`, `tests/test_generated_knowledge.py`, `tests/test_answer_result_operations.py`

- [ ] Write failing tests for generated Markdown metadata, deterministic chunk IDs, FTS/vector metadata, no-answer rejection, and explicit partial completion.
- [ ] Implement generated source writer and indexer metadata propagation.
- [ ] Label generated chunks as secondary context in the generator prompt.
- [ ] Implement `POST /api/answer-assets/add-pka-retrieval`: local save, local index, Agent10 publish, explicit state response.
- [ ] Verify focused tests pass.

### Task 4: Wire the published controls

**Files:** `static/ask.html`, `static/app.js`, `tests/test_project_files.py`, `tests/test_answer_result_operations.py`

- [ ] Write failing static and API feedback tests for the three explicit actions.
- [ ] Enable controls only after a completed answer; keep PKA retrieval disabled for `no_answer`.
- [ ] Wire each button only to its corresponding endpoint and render exact local/Obsidian/index states.
- [ ] Verify focused tests pass.

### Task 5: End-to-end verification

**Files:** `docs/OBSIDIAN_PHASE1_IMPLEMENTATION_STATUS_20260704.md`, `docs/pka-answer-result-operations-sdd.md`

- [ ] Run Agent06 focused and non-live regression suites, Agent10 full suite, syntax checks, and diff checks.
- [ ] Restart the managed Agent06 backend with its runtime token-file configuration.
- [ ] Use a non-sensitive local answer asset to verify local save, Obsidian publication, retrieval promotion, idempotent reuse, governance mirror state, and secret-free Web responses.
- [ ] Record verified outcomes without storing answer bodies or credentials.
