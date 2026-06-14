# PKA Agent05 PPT Export And Workflow Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Agent04-like Agent06 workflow switch and make PKA PPT export try Agent05/PPT-maker before falling back to local PPTX.

**Architecture:** Agent06 shell markup and CSS receive a scoped switch wrapper. PKA backend adds a small Agent05 adapter that speaks Agent05's WebSocket generation protocol, auto-selects the first candidate, downloads the PPTX result, and falls back to `python-pptx` on failure.

**Tech Stack:** FastAPI, httpx, optional websockets, python-pptx, vanilla JS/CSS, Node platform tests, pytest/TestClient.

---

### Task 1: Write Failing Tests

**Files:**
- Modify: `/Users/tristanzh/agent/Personal-Asset/tests/test_export_api.py`
- Modify: `/Users/tristanzh/agent/Personal-Asset/tests/test_project_files.py`
- Modify: `/Users/tristanzh/agent/web/tests/agent06-service.test.mjs`

- [ ] Add a test that monkeypatches `server.export_to_quality_ppt` to return a generated `.pptx` and asserts `/api/export/ppt` returns those bytes.
- [ ] Add a test that monkeypatches `server.export_to_quality_ppt` to raise and asserts `/api/export/ppt` still returns fallback PPTX bytes.
- [ ] Add a file contract test asserting Agent06 shell markup includes `agent06-info-switch`, `agent06-tab-switch`, `agent06-tab-switch__button`, and `功能切换`.
- [ ] Update Agent06 CSS test to require segmented switch fill and active styling.
- [ ] Run the specific tests and confirm they fail because the implementation does not exist yet.

### Task 2: Implement PPT Adapter

**Files:**
- Create: `/Users/tristanzh/agent/Personal-Asset/engine/ppt_maker_adapter.py`
- Modify: `/Users/tristanzh/agent/Personal-Asset/engine/config.py`
- Modify: `/Users/tristanzh/agent/Personal-Asset/config.yaml`
- Modify: `/Users/tristanzh/agent/Personal-Asset/server.py`
- Modify: `/Users/tristanzh/agent/Personal-Asset/requirements.txt`

- [ ] Add default config `ppt_maker.enabled`, `http_base_url`, `ws_base_url`, `timeout_seconds`, `page_count`, and `style`.
- [ ] Build a structured PKA prompt from question, answer, and sources.
- [ ] Connect to Agent05 WebSocket, send `generate`, auto-select the first candidate, wait for `complete`, and download the returned PPTX.
- [ ] Treat all adapter exceptions as fallback triggers in `/api/export/ppt`.
- [ ] Keep response MIME and filename as `.pptx`.

### Task 3: Implement Agent06 Tab Visual

**Files:**
- Modify: `/Users/tristanzh/agent/web/server.mjs`
- Modify: `/Users/tristanzh/agent/web/app/agent06.css`

- [ ] Wrap workflow navigation in an `agent06-info-switch` section.
- [ ] Add a `功能切换` small label.
- [ ] Change nav class to `agent06-tab-switch` while keeping `agent06-workflow-nav` for existing JS/test compatibility.
- [ ] Change nav links to include `agent06-tab-switch__button`.
- [ ] Style active state with a filled segment and stable button dimensions.

### Task 4: Verify

**Files:**
- Read-only verification across Personal-Asset and web.

- [ ] Run `python3 -m pytest tests/test_export_api.py tests/test_exporter.py tests/test_project_files.py -q`.
- [ ] Run `cd /Users/tristanzh/agent/web && node --test tests/agent06-service.test.mjs`.
- [ ] Run `cd /Users/tristanzh/agent/web && node --check server.mjs`.
- [ ] If services are available, smoke test `/agent06` and `/agent06/api/export/ppt`.

