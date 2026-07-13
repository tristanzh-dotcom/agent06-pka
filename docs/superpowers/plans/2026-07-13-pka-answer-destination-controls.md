# PKA Answer Destination Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to execute this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a truthful post-answer control strip that makes local storage, Obsidian publication, and future PKA retrieval distinct before their backend behavior is wired.

**Architecture:** `static/ask.html` owns the visible controls, `static/app.js` owns enablement and event binding, and `static/style.css` owns the scoped destination-strip layout. In this slice only Word export remains executable. The three destination controls are intentionally disabled and have no legacy click handler.

**Tech Stack:** Static HTML, vanilla JavaScript, CSS, pytest static-contract tests.

## Global Constraints

- Scope is only the Agent06 question page (`static/ask.html`, `static/app.js`, `static/style.css`) and its static-contract test.
- Do not change Agent06 backend APIs, Agent10 APIs, FTS, vector indexing, Obsidian writes, or shared Web shell styling.
- Remove the question-page `资料库` and `导出 PPT` controls.
- Keep `导出 Word` working after a completed answer.
- Show exactly `保存到本地资料`, `发布到 Obsidian`, and `加入 PKA 问答检索` as disabled destination controls.
- New labels must not invoke `/api/assets/answers`, `/api/knowledge/add-generated`, or `/api/export/ppt` in this slice.
- Do not commit, push, pull, stash, rebase, or otherwise perform Git write operations; Agent08 owns Git submission.

---

### Task 1: Lock the published control contract

**Files:**
- Modify: `tests/test_project_files.py:627-640`

**Interfaces:**
- Consumes: `static/ask.html` answer toolbar and `static/app.js` setup/enablement functions.
- Produces: a static contract proving the four approved controls and absence of the removed/legacy controls.

- [ ] **Step 1: Write the failing static contract test.**

  Replace the old save-button assertions with assertions for the exact HTML labels and IDs:

  ```python
  assert 'id="export-word">导出 Word</button>' in ask_html
  assert 'id="save-local-asset" disabled>保存到本地资料</button>' in ask_html
  assert 'id="publish-obsidian" disabled>发布到 Obsidian</button>' in ask_html
  assert 'id="add-pka-retrieval" disabled>加入 PKA 问答检索</button>' in ask_html
  assert 'id="export-ppt"' not in ask_html
  assert 'class="asset-header-link"' not in ask_html
  ```

  Assert JavaScript keeps Word export binding and contains no bindings or API calls for the three deferred controls:

  ```python
  assert 'document.getElementById("export-word")?.addEventListener("click", () => exportAnswer("word"))' in app_js
  assert 'saveAnswerAsset' not in app_js
  assert 'addAnswerResultToKnowledge' not in app_js
  assert 'api/knowledge/add-generated' not in app_js
  assert 'exportAnswer("ppt")' not in app_js
  ```

- [ ] **Step 2: Run the focused test and verify RED.**

  Run: `python3 -m pytest tests/test_project_files.py -k 'save_answer_asset' -q`

  Expected: FAIL because the old toolbar still contains `资料库`, `导出 PPT`, and legacy save/add controls.

### Task 2: Publish the destination strip without wiring behavior

**Files:**
- Modify: `static/ask.html:10-22`
- Modify: `static/app.js:861-884,1002-1048`
- Modify: `static/style.css:540-570`

**Interfaces:**
- Consumes: Task 1's exact element IDs and labels.
- Produces: one working Word export action plus three truthful disabled destination controls.

- [ ] **Step 1: Replace the answer toolbar markup.**

  Use this structure:

  ```html
  <div class="exportbar" id="export-bar" style="display:none">
    <button type="button" id="export-word">导出 Word</button>
    <span class="answer-destination-divider" aria-hidden="true"></span>
    <button type="button" id="save-local-asset" class="answer-destination" disabled>
      <span>保存到本地资料</span><small>仅保存在本机</small>
    </button>
    <button type="button" id="publish-obsidian" class="answer-destination" disabled>
      <span>发布到 Obsidian</span><small>写入本地 Vault</small>
    </button>
    <button type="button" id="add-pka-retrieval" class="answer-destination answer-destination--primary" disabled>
      <span>加入 PKA 问答检索</span><small>Obsidian + 未来问答可找回</small>
    </button>
  </div>
  ```

- [ ] **Step 2: Remove legacy JavaScript wiring and status handling.**

  Keep only:

  ```javascript
  document.getElementById("export-word")?.addEventListener("click", () => exportAnswer("word"));
  ```

  Delete `saveAnswerAsset`, `addAnswerResultToKnowledge`, their status nodes, their event listeners, and their enablement branches. Keep the existing asset-list/detail APIs used by the separate `/assets` page. Do not add event listeners for the three destination controls.

- [ ] **Step 3: Add scoped destination-strip CSS.**

  Preserve the existing panel and accent tokens. Ensure `.answer-destination` forms a compact two-line button, `.answer-destination-divider` separates export from persistence, disabled controls retain legible copy, and the strip wraps gracefully below `720px` without altering global buttons.

- [ ] **Step 4: Run the focused test and verify GREEN.**

  Run: `python3 -m pytest tests/test_project_files.py -k 'save_answer_asset' -q`

  Expected: PASS after the test has been renamed to reflect destination controls.

### Task 3: Regression-check the published question page

**Files:**
- Test: `tests/test_answer_result_operations.py`
- Test: `tests/test_project_files.py`

**Interfaces:**
- Consumes: Task 2 published static controls.
- Produces: proof that the question page keeps answer generation and Word export contracts while deferred controls have no backend side effect.

- [ ] **Step 1: Update test names and remove obsolete legacy API assumptions.**

  Rename the static test to `test_ask_page_publishes_explicit_destination_controls_without_legacy_side_effects`. Keep assertions for `buildAnswerResultSnapshot()` only if it remains used by answer rendering; remove any assertion requiring legacy save/add API calls.

- [ ] **Step 2: Run focused Agent06 tests.**

  Run: `python3 -m pytest tests/test_answer_result_operations.py tests/test_project_files.py -q`

  Expected: PASS.

- [ ] **Step 3: Run the current non-live Agent06 regression suite.**

  Run: `python3 -m pytest -q --ignore=tests/test_retrieval_quality_gate.py`

  Expected: PASS, or report any pre-existing external/live failure separately.

- [ ] **Step 4: Verify the static page and patch hygiene.**

  Run: `python3 -m compileall -q server.py engine static 2>/dev/null || true; git diff --check`

  Expected: no whitespace errors. Inspect `static/ask.html` to confirm no `资料库` or `导出 PPT` action remains.
