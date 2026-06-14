# PKA Six Slot Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Agent06/PKA's open-ended upload list with a fixed six-slot file upload board.

**Architecture:** Keep the existing backend and `selectedFiles`/`fileUploadResults` state. Change only the ingest page HTML contract, CSS slot board, and frontend rendering/event handling.

**Tech Stack:** Static HTML/CSS/JavaScript, FastAPI static files, pytest file-contract tests.

---

### Task 1: Lock The UI Contract

**Files:**
- Modify: `/Users/tristanzh/agent/Personal-Asset/tests/test_project_files.py`
- Modify: `/Users/tristanzh/agent/Personal-Asset/static/index.html`
- Modify: `/Users/tristanzh/agent/Personal-Asset/static/style.css`
- Modify: `/Users/tristanzh/agent/Personal-Asset/static/app.js`

- [ ] **Step 1: Write failing tests**

Add tests that assert the ingest page declares a six-slot upload board, JS enforces `MAX_UPLOAD_FILES = 6`, and CSS defines the slot states.

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
python3 -m pytest -q tests/test_project_files.py -k "six_slot_upload or ingest_upload_supports_multi_file_queue"
```

Expected: fail because the current page still uses `upload-picker` and does not render fixed slots.

- [ ] **Step 3: Implement the minimal slot board**

Change `static/index.html` to use a hidden native input and an empty `data-upload-slot-board` container. Update `static/app.js` to render six slots from `selectedFiles` and `fileUploadResults`.

- [ ] **Step 4: Style the slot board**

Add `.upload-slot-board`, `.upload-slot`, `.upload-slot.is-empty`, `.upload-slot.is-filled`, `.upload-slot.is-complete`, and `.upload-slot.is-error` rules. Keep slot dimensions stable and feedback separated from the upload button.

- [ ] **Step 5: Verify GREEN**

Run:

```bash
python3 -m pytest -q tests/test_project_files.py -k "six_slot_upload or ingest_upload_supports_multi_file_queue"
python3 -m pytest -q
```

Expected: all selected tests and full PKA tests pass.

- [ ] **Step 6: Browser verify**

Open `http://127.0.0.1:3000/agent06/` and confirm six slots render, the upload button and feedback do not overlap, and selected slots stay inside the board.
