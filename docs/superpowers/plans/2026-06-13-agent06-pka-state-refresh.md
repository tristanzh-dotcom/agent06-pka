# Agent06 PKA State Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refresh Agent06 header stats after PKA ingest actions and preserve PKA iframe input state across shell refreshes.

**Architecture:** PKA iframe pages emit same-origin `postMessage` events after successful knowledge mutations and implement the existing embedded-state snapshot/restore protocol. The Agent06 platform shell listens for `agent06:knowledge-updated`, fetches `/api/agent06/status`, and updates only the header stat/status lines.

**Tech Stack:** FastAPI-served static HTML/JS, Node `server.mjs` platform shell, browser `postMessage`, localStorage-backed embedded-state bridge, Node/Python/Puppeteer tests.

---

### Task 1: PKA iframe event and state bridge

**Files:**
- Modify: `/Users/tristanzh/agent/Personal-Asset/static/app.js`
- Test: `/Users/tristanzh/agent/Personal-Asset/tests/test_project_files.py`

- [ ] **Step 1: Write failing tests**

Add assertions that `static/app.js` contains `agent06:knowledge-updated`, `web-publishing:embedded-state:snapshot`, `web-publishing:embedded-state:restore`, and does not attempt to restore file input values.

- [ ] **Step 2: Run red test**

Run: `python3 -m pytest -q tests/test_project_files.py`
Expected: FAIL because the bridge strings are not present.

- [ ] **Step 3: Implement minimal PKA bridge**

Add helpers in `static/app.js`:
- `notifyKnowledgeUpdated(action)`
- `collectEmbeddedState()`
- `restoreEmbeddedState(payload)`
- `publishEmbeddedSnapshot()`
- `setupEmbeddedStateBridge()`

Call `notifyKnowledgeUpdated()` after text ingest, file ingest, and clear success. Do not restore file input values.

- [ ] **Step 4: Run green test**

Run: `python3 -m pytest -q tests/test_project_files.py`
Expected: PASS.

### Task 2: Agent06 shell header refresh

**Files:**
- Modify: `/Users/tristanzh/agent/web/app/agent06.js`
- Modify: `/Users/tristanzh/agent/web/server.mjs`
- Test: `/Users/tristanzh/agent/web/tests/agent06-service.test.mjs`

- [ ] **Step 1: Write failing tests**

Add assertions that the rendered Agent06 header has stable `[data-agent06-stat-line]` and `[data-agent06-status-line]` hooks, and that `agent06.js` listens for `agent06:knowledge-updated`, fetches `/api/agent06/status`, and updates those hooks.

- [ ] **Step 2: Run red test**

Run: `cd /Users/tristanzh/agent/web && node --test tests/agent06-service.test.mjs`
Expected: FAIL because hooks and refresh code are missing.

- [ ] **Step 3: Implement minimal shell refresh**

Add data hooks in `renderAgent06Page()`. Add same-origin `message` listener in `agent06.js`, with `refreshAgent06Status()` that fetches status and updates stat/status lines without reloading iframe.

- [ ] **Step 4: Run green test**

Run: `cd /Users/tristanzh/agent/web && node --test tests/agent06-service.test.mjs`
Expected: PASS.

### Task 3: Browser persistence and integration

**Files:**
- Modify: `/Users/tristanzh/agent/web/tests/result-state-persistence-browser.test.mjs`

- [ ] **Step 1: Write failing browser test**

Extend the Agent06 persistence fixture so the iframe implements PKA-like bridge behavior, then assert that after shell reload the ingest input and feedback restore.

- [ ] **Step 2: Run red test**

Run: `cd /Users/tristanzh/agent/web && node --test tests/result-state-persistence-browser.test.mjs`
Expected: FAIL before implementation, PASS after Task 1/2.

- [ ] **Step 3: Verify**

Run:
- `python3 -m pytest -q`
- `cd /Users/tristanzh/agent/web && node --check server.mjs`
- `cd /Users/tristanzh/agent/web && node --test tests/agent06-service.test.mjs`
- `cd /Users/tristanzh/agent/web && node --test tests/result-state-persistence-browser.test.mjs`
- Browser check `http://127.0.0.1:3000/agent06?view=ingest`
