# PKA Save Answer Asset Library V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `保存到资料库` for completed PKA answer results without indexing saved assets into RAG.

**Architecture:** Add a file-first answer asset store under `data_dir/assets/answers/YYYY-MM-DD/{asset_id}` with `manifest.json` and `answer.md`. Expose save/list/read APIs, then wire the ask page operation bar to post the completed `AnswerResult` snapshot.

**Tech Stack:** FastAPI, Pydantic, local filesystem JSON/Markdown storage, static HTML/CSS/JS, pytest.

## Global Constraints

- Current workflow is `保存到资料库`, not `加入知识库`.
- Saved assets must keep `rag_status="not_indexed"` and must not write to FTS5 or ChromaDB.
- Saving must not call DeepSeek, codex-base, embeddings, or any other LLM route.
- Preserve original question, answer, sources, source status, language, answer mode, model route, and timestamps.
- Do not implement asset editing, search, external GitHub project integration, or promotion to knowledge.
- Do not run `git commit`, `git push`, `git pull`, `git stash`, or `git rebase` in this business repo.

---

## File Structure

- Create `engine/answer_assets.py`: asset id generation, manifest/Markdown rendering, save/list/read helpers.
- Modify `server.py`: Pydantic request models and `/api/assets/answers` save/list/read endpoints.
- Modify `static/ask.html`: add `保存到资料库` button in the completed-answer operation bar.
- Modify `static/app.js`: build answer snapshot, enable/disable save action, post save request, show status.
- Modify `static/style.css`: reuse export bar styling and add compact save status styling.
- Add `tests/test_answer_assets_api.py`: backend TDD for save/list/read and no indexer writes.
- Modify `tests/test_project_files.py`: static contract tests for the save button and JS behavior.

## Tasks

### Task 1: Backend Asset Store

**Files:**
- Create: `engine/answer_assets.py`
- Create: `tests/test_answer_assets_api.py`
- Modify: `server.py`

**Interfaces:**
- Produces: `save_answer_asset(data_dir: str, payload: dict, now: datetime | None = None) -> dict`
- Produces: `list_answer_assets(data_dir: str, limit: int = 50) -> list[dict]`
- Produces: `read_answer_asset(data_dir: str, asset_id: str) -> dict | None`
- Produces API: `POST /api/assets/answers`, `GET /api/assets/answers`, `GET /api/assets/answers/{asset_id}`

- [ ] Write failing backend tests for save validation, file writes, `rag_status`, no indexer upsert, list, and read.
- [ ] Run the focused tests and verify they fail for missing endpoints/module.
- [ ] Implement `engine/answer_assets.py` and server endpoints minimally.
- [ ] Run focused backend tests and verify they pass.

### Task 2: Frontend Save Action

**Files:**
- Modify: `static/ask.html`
- Modify: `static/app.js`
- Modify: `static/style.css`
- Modify: `tests/test_project_files.py`

**Interfaces:**
- Consumes API: `POST /api/assets/answers`
- Produces JS helper: `buildAnswerResultSnapshot()`
- Produces JS action: `saveAnswerAsset()`

- [ ] Write failing static contract tests for save button, snapshot helper, API path, completion gating, and no `/api/knowledge/add-generated` save call.
- [ ] Run focused static tests and verify they fail.
- [ ] Implement the button, snapshot helper, save action, and status copy.
- [ ] Run focused static tests and verify they pass.

### Task 3: Verification

**Files:**
- Existing tests only.

- [ ] Run `python3 -m pytest tests/test_answer_assets_api.py tests/test_project_files.py::test_ask_page_p0_layout_contract_keeps_input_in_first_viewport tests/test_project_files.py::test_ask_export_buttons_use_neutral_publishing_theme_style -q`.
- [ ] Run `python3 -m pytest tests/test_export_api.py tests/test_answer_assets_api.py -q`.
- [ ] Run broader non-live backend/static tests if focused tests pass.
