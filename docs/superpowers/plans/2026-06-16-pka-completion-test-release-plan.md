# PKA Completion Test Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the PKA trusted ingest project by validating backend/frontend contracts end to end, recording release evidence, and sealing a stable version.

**Architecture:** The backend is now a unified ingest pipeline: every indexable `ParseResult` flows through `_ingest_parsed_result`, then chunk/pre_chunk merge, sync chunk fuse, and Chroma/FTS5 upsert. The frontend consumes the same contracts through upload quality badges, source-type badges, and raw-file truthiness guards.

**Tech Stack:** FastAPI, static HTML/CSS/JavaScript, pytest, ChromaDB, FTS5, Ollama bge-m3, DeepSeek generation route.

---

### Task 1: Freeze Current Baseline Evidence

**Files:**
- Read: `/Users/tristanzh/agent/Personal-Asset/server.py`
- Read: `/Users/tristanzh/agent/Personal-Asset/static/app.js`
- Read: `/Users/tristanzh/agent/Personal-Asset/tests/test_project_files.py`

- [ ] **Step 1: Confirm branch and latest commit**

Run:

```bash
cd /Users/tristanzh/agent/Personal-Asset
git branch --show-current
git log -1 --oneline
```

Expected: branch is `main`; latest commit includes the latest frontend/client badge work.

- [ ] **Step 2: Confirm target files are clean**

Run:

```bash
cd /Users/tristanzh/agent/Personal-Asset
git status --short -- server.py engine static tests docs
```

Expected: no output, unless this plan file is intentionally being committed.

- [ ] **Step 3: Run full test suite**

Run:

```bash
cd /Users/tristanzh/agent/Personal-Asset
python3 -m pytest -q
```

Expected: all tests pass. Current baseline is `213 passed, 15 warnings`.

- [ ] **Step 4: Check JavaScript syntax**

Run:

```bash
cd /Users/tristanzh/agent/Personal-Asset
node --check static/app.js
```

Expected: exit code 0 and no syntax errors.

---

### Task 2: Validate Frontend Runtime Contracts

**Files:**
- Read: `/Users/tristanzh/agent/Personal-Asset/static/index.html`
- Read: `/Users/tristanzh/agent/Personal-Asset/static/ask.html`
- Read: `/Users/tristanzh/agent/Personal-Asset/static/app.js`
- Read: `/Users/tristanzh/agent/Personal-Asset/static/style.css`

- [ ] **Step 1: Verify local service is reachable**

Run:

```bash
curl -s -o /tmp/pka-index.html -w '%{http_code}\n' http://127.0.0.1:8086/
curl -s -o /tmp/pka-ask.html -w '%{http_code}\n' http://127.0.0.1:8086/ask
curl -s -o /tmp/pka-app.js -w '%{http_code}\n' 'http://127.0.0.1:8086/static/app.js?v=20260616-source-type-ui'
```

Expected: each command prints `200`.

- [ ] **Step 2: Verify cache-bust version is live**

Run:

```bash
curl -s http://127.0.0.1:8086/ | rg '20260616-source-type-ui'
curl -s http://127.0.0.1:8086/ask | rg '20260616-source-type-ui'
curl -s 'http://127.0.0.1:8086/static/app.js?v=20260616-source-type-ui' | rg 'formatUpload413Error|sourceTypeBadge|orgChartBadge'
```

Expected: all three commands match content.

- [ ] **Step 3: Browser smoke test when Browser tool is available**

Open:

```text
http://127.0.0.1:8086/
http://127.0.0.1:8086/ask
```

Expected: upload grid renders without overlap; ask page sources render compact chips; no console syntax error.

---

### Task 3: Run End-to-End Ingest Matrix

**Files:**
- Read: `/Users/tristanzh/agent/Personal-Asset/server.py`
- Read: `/Users/tristanzh/agent/Personal-Asset/engine/indexer.py`
- Read: `/Users/tristanzh/agent/Personal-Asset/engine/retriever.py`

- [ ] **Step 1: Clear knowledge base**

Run:

```bash
curl -s -X POST http://127.0.0.1:8086/api/ingest/clear
curl -s http://127.0.0.1:8086/api/stats
```

Expected: stats show `indexed_files: 0` and `total_chunks: 0`.

- [ ] **Step 2: Ingest manual text**

Run a browser or API text ingest with a concise manual note.

Expected:
- response has `status: ok`
- response has `source_type: text`
- response has `quality.action: direct`
- source lookup has `raw_file_path: ""`
- UI does not show a raw-file link for that source.

- [ ] **Step 3: Upload JLR org chart PDF**

Upload `JLR_Corporate_Deck_Template_MASTER_25_.pptx.pdf`.

Expected:
- approximately `105` chunks
- `org_chart` chunks present
- upload slot shows main quality badge plus `Org Chart`
- Chroma and FTS5 counts match.

- [ ] **Step 4: Upload scanned GEO PDF**

Upload `2026中国新能源汽车品牌GEO现状研究报告-亿欧智库.pdf`.

Expected:
- file is skipped or errored as OCR timeout / needs OCR
- `chunks: 0`
- no Chroma/FTS5 pollution
- UI explains the document did not enter the main knowledge base.

- [ ] **Step 5: Upload oversized Turtle PDF**

Upload `Turtle of the world 2010.pdf`.

Expected:
- HTTP 413 or batch per-file error
- frontend shows `文件过大，未入库`
- message includes actual `chunks` and configured `limit`
- service remains responsive immediately after rejection.

---

### Task 4: Run Retrieval and Answer Quality Gate

**Files:**
- Read: `/Users/tristanzh/agent/Personal-Asset/tests/test_retrieval_quality_gate.py`
- Read: `/Users/tristanzh/agent/Personal-Asset/engine/generator.py`

- [ ] **Step 1: Run retrieval quality gate**

Run:

```bash
cd /Users/tristanzh/agent/Personal-Asset
python3 -m pytest -q tests/test_retrieval_quality_gate.py
```

Expected: `10 passed`.

- [ ] **Step 2: Ask org chart question**

Question:

```text
Who reports to Nico Reimel?
```

Expected:
- answer cites JLR source
- sources array includes `source_type: org_chart`
- frontend source chip shows `Org Chart`.

- [ ] **Step 3: Ask ordinary PDF question**

Question:

```text
How should the organisation charts be read?
```

Expected:
- answer cites JLR source
- top source may be `pdf`
- frontend source chip shows `PDF`.

- [ ] **Step 4: Ask manual text question**

Ask a question that can only be answered from the manual note created in Task 3.

Expected:
- answer uses manual source
- source chip shows `Text`
- no raw-file link appears.

- [ ] **Step 5: Ask no-answer question**

Question:

```text
宠物医疗保险理赔流程有哪些？
```

Expected:
- `source_status: no_answer`
- `sources: []`
- frontend shows no fake source chips.

---

### Task 5: Document Release State

**Files:**
- Modify: `/Users/tristanzh/agent/Personal-Asset/HANDOVER_pka_trusted_ingest_20260614.md`

- [ ] **Step 1: Add current architecture summary**

Append a short section with:

```markdown
## 2026-06-16 Release State

- Unified ingest pipeline is active through `_ingest_parsed_result`.
- Text and file inputs share chunking, pre_chunk merge, sync chunk fuse, and Chroma/FTS5 upsert.
- Frontend shows 413 detail, upload quality badges, Org Chart auxiliary badges, source_type badges, and raw_file_path truthiness behavior.
- Current verified baseline: `python3 -m pytest -q` passes.
```

- [ ] **Step 2: Record known non-blocking warnings**

Append:

```markdown
Known non-blocking warnings:
- urllib3 LibreSSL warning from local Python runtime.
- matplotlib pyparsing deprecation warnings from nested Volcengine OCR config test path.
```

- [ ] **Step 3: Commit handover update**

Run:

```bash
git add HANDOVER_pka_trusted_ingest_20260614.md
git commit -m "docs(pka): record trusted ingest release state"
git push
```

Expected: commit and push succeed.

---

### Task 6: Seal Release Candidate

**Files:**
- Read: `/Users/tristanzh/agent/Personal-Asset`

- [ ] **Step 1: Run final tests**

Run:

```bash
cd /Users/tristanzh/agent/Personal-Asset
python3 -m pytest -q
node --check static/app.js
```

Expected: all tests pass; JS syntax check exits 0.

- [ ] **Step 2: Check git state**

Run:

```bash
git status --short
git log -3 --oneline
```

Expected: only unrelated parent-directory dirty files may appear; Personal-Asset release files are clean.

- [ ] **Step 3: Create release tag after TZ approval**

Run only after approval:

```bash
git tag pka-trusted-ingest-v1
git push origin pka-trusted-ingest-v1
```

Expected: tag is pushed to origin.

---

### Task 7: Post-Release Backlog, Not Part of v1 Seal

**Files:**
- Create only if TZ asks: `/Users/tristanzh/agent/Personal-Asset/docs/pka-post-release-backlog.md`

- [ ] **Step 1: Keep async OCR out of v1**

Record:

```markdown
Async OCR and large scanned-PDF ingestion are postponed. Current behavior intentionally skips OCR timeout files to protect retrieval quality.
```

- [ ] **Step 2: Keep global split-character normalization out of v1**

Record:

```markdown
Global split-character normalization for ordinary PDF chunks is a future improvement. Org Chart fallback already normalizes its own projection path.
```

- [ ] **Step 3: Keep visual Org Chart explorer out of v1**

Record:

```markdown
Org Chart v1 exposes structured text and source_type badges. A visual tree viewer is a future product layer and should start with SDD/TDD.
```

