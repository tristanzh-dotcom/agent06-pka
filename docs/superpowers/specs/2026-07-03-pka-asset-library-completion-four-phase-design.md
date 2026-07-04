# PKA Asset Library Completion Four-Phase Design

> Date: 2026-07-03
> Status: implemented with default decisions
> Scope: 资料库完整体验闭环 after `保存到资料库` V1

## 1. Design Boundary

This document designs the remaining work required to complete the local answer-result asset library.

It is not the PKA mainline knowledge-base workflow. It is not `加入知识库`. It is not MCHT. The target is the generated-answer asset library created from completed `AnswerResult` objects.

Already completed baseline:

- `POST /api/assets/answers` saves an answer asset.
- `GET /api/assets/answers` lists saved assets.
- `GET /api/assets/answers/{asset_id}` reads one saved asset.
- Saved assets are written under `data_dir/assets/answers/YYYY-MM-DD/{asset_id}/`.
- Each asset has `manifest.json` and `answer.md`.
- Each asset has `rag_status="not_indexed"`.
- Saving does not call LLMs, embeddings, FTS5, or ChromaDB.
- Ask page has a `保存到资料库` action.

The remaining work is a four-phase product and engineering completion path:

1. 资料库列表页
2. 资料详情页
3. 从资料库导出
4. 质量/交付收口

## 2. First-Principles Product Goal

The asset library should make generated answer results durable and reusable without confusing them with primary knowledge sources.

The user should be able to:

- save a completed answer;
- browse saved assets;
- open an asset and inspect its question, answer, sources, and metadata;
- export a saved asset into document formats;
- keep the saved asset out of RAG until an explicit future promotion action exists.

## 3. Non-Negotiable Constraints

1. Saved assets remain `rag_status="not_indexed"` throughout this four-phase scope.
2. No phase may call `/api/knowledge/add-generated`.
3. No phase may write saved asset content into FTS5 or ChromaDB.
4. No phase may call DeepSeek, codex-base, embeddings, or any LLM during save, list, read, or export metadata updates.
5. Export may use deterministic document generators only.
6. Source references are preserved as references, not copied as full source excerpts.
7. Full asset editing, folders, complex tagging, full-text asset search, and knowledge promotion remain non-goals.
8. Git write operations remain outside this repo workflow.

## 4. Current Data Contract

`AnswerAsset` is the canonical asset object.

Required fields:

```json
{
  "asset_id": "ans_20260703_153012_ab12cd",
  "asset_type": "answer_result",
  "title": "JLR 面试复盘总结",
  "question": "original user question",
  "answer": "final rendered model answer",
  "sources": [],
  "source_status": "grounded|thin|no_answer",
  "evidence": {},
  "language": "zh|en",
  "answer_mode": "answer|interview_story|retrospective|english_report|ppt_outline|decision_memo",
  "model_route": "deepseek|codex-base|dual|local_fallback",
  "created_at": "ISO timestamp",
  "updated_at": "ISO timestamp",
  "tags": [],
  "status": "saved",
  "rag_status": "not_indexed",
  "exports": []
}
```

The four remaining phases must preserve this contract. They may add optional fields only if older manifests still read correctly.

## 5. Phase 1: 资料库列表页

### Goal

Give the user a durable place to browse saved answer assets.

### User Experience

Add a lightweight asset library page reachable from the PKA UI. The page should show a dense, work-focused list of saved answer assets:

- title;
- saved time;
- original question preview;
- language;
- answer mode;
- source status;
- RAG status;
- source count;
- export count if available.

Clicking a row opens the asset detail page.

### Frontend Route

Recommended page:

```text
/assets
```

Static file:

```text
static/assets.html
```

Phase 1 decision: add a visible entry from the ask page operation area and keep `/assets` directly reachable. This gives the user a discoverable path without changing the shared shell or unrelated PKA pages.

### Backend API

Use existing:

```http
GET /api/assets/answers?limit=50
```

Optional query parameters:

```text
limit: integer, default 50, max 200
before: optional ISO timestamp cursor; returns assets with created_at < before
source_status: optional grounded|thin|no_answer
language: optional zh|en
```

Pagination boundary:

- the backend API must support `before` from this phase onward, even if the first frontend page only shows a "加载更多" button later;
- `limit` must be capped at 200 to prevent large filesystem scans from producing large responses;
- list results remain newest-first;
- frontend may start with one page of 50, but it must not rely on "all assets fit in one response" as a product invariant.

Filtering can be deferred if implementation risk rises. The hard requirements are newest-first list, `limit`, and `before` cursor support.

### UI State

States:

- loading;
- empty;
- loaded;
- failed.

Empty copy:

```text
暂无资料。完成一次问答后点击“保存到资料库”。
```

Failure copy:

```text
资料库加载失败。
```

### Acceptance Criteria

1. `/assets` loads without needing a completed current answer.
2. It calls `GET /api/assets/answers`.
3. It shows newest saved assets first.
4. It shows `rag_status="not_indexed"` visibly or through a stable badge.
5. It does not expose `加入知识库`.
6. It does not call any query or generation endpoint.

### Tests

Backend:

- existing list API returns newest first;
- list API handles empty library.
- list API caps `limit` at 200.
- list API supports `before` cursor pagination.

Frontend/static:

- `static/assets.html` exists;
- page includes an asset list container;
- `static/app.js` or a scoped assets script calls `api/assets/answers`;
- no `/api/query`;
- no `/api/knowledge/add-generated`.

## 6. Phase 2: 资料详情页

### Goal

Let the user inspect one saved asset in full.

### User Experience

Asset detail should be read-only in this phase.

The page should show:

- title;
- created time;
- source status badge;
- `rag_status="not_indexed"` badge;
- original question;
- answer body;
- source references;
- metadata block;
- export actions for Phase 3 when implemented.

The detail view should prioritize reading the answer, not editing metadata.

### Frontend Route

Recommended route shape:

```text
/assets?asset_id=ans_...
```

This avoids adding backend HTML routing complexity if static file routing is constrained.

Optional later route:

```text
/assets/{asset_id}
```

### Backend API

Use existing:

```http
GET /api/assets/answers/{asset_id}
```

Expected response:

```json
{
  "status": "ok",
  "asset": {
    "asset_id": "ans_...",
    "manifest": {},
    "answer_markdown": "..."
  }
}
```

### Markdown Rendering Policy

Phase 2 decision: render Markdown as plain structured text, preserving line breaks. Do not introduce a Markdown library in this scope.

Rationale:

- avoids new dependency;
- prevents HTML injection risk from generated answer content;
- keeps the detail page deterministic.

If rendered Markdown is later required, sanitize output explicitly.

### Error Handling

Asset not found:

```text
资料不存在或已移动。
```

Malformed manifest:

```text
资料文件损坏，无法读取。
```

### Acceptance Criteria

1. Clicking a list row opens detail for that asset.
2. Detail page reads `GET /api/assets/answers/{asset_id}`.
3. Detail displays question, answer, source references, and metadata.
4. Detail displays `not_indexed`.
5. Detail is read-only.
6. Detail does not write to asset files.
7. Detail does not call generation or retrieval APIs.

### Tests

Backend:

- read API returns manifest and answer markdown;
- read API returns 404 for unknown safe-looking asset id;
- read API rejects unsafe asset ids by returning 404.

Frontend/static:

- detail mode parses `asset_id`;
- detail mode calls `api/assets/answers/${asset_id}`;
- detail includes containers for question, answer, sources, metadata;
- no contenteditable/editor controls.

## 7. Phase 3: 从资料库导出

### Goal

Let saved assets produce deterministic document exports after they have been saved.

This phase closes the loop between:

- current answer export;
- saved asset persistence;
- later asset reuse.

### Export Formats

Minimum:

- Word: `.docx`
- PPT: `.pptx` if current deterministic fallback remains available

Optional:

- PDF only if a deterministic PDF export path is already available or separately designed.

Phase 3 decision: defer PDF export. Do not add PDF as a hidden dependency because the current project already has stable Word/PPT paths but no equally established asset PDF export path.

### Backend API

Recommended endpoints:

```http
POST /api/assets/answers/{asset_id}/export/word
POST /api/assets/answers/{asset_id}/export/ppt
```

Responses return file attachments, same as current export endpoints.

### Manifest Export Recording

When an asset export succeeds, append an export record to `manifest.exports`:

```json
{
  "format": "word",
  "path": "assets/answers/2026-07-03/ans_.../exports/answer_20260703_153012.docx",
  "created_at": "ISO timestamp"
}
```

Rules:

- export files live under the asset directory `exports/`;
- repeated exports create new timestamped files;
- each asset keeps at most the latest 5 export records total;
- when export history pruning removes an old record, the corresponding local export file must be deleted if it is still under that asset's `exports/` directory;
- failed exports do not mutate `manifest.exports`;
- export uses saved manifest data, not current `askState`.

### Relationship With Existing Export API

Existing endpoints stay unchanged:

```http
POST /api/export/word
POST /api/export/ppt
```

Asset export endpoints should reuse the deterministic export functions:

- `export_to_word(question, answer, sources, output_path)`
- `export_to_quality_ppt(...)` with fallback to `export_to_ppt(...)`

No asset export endpoint should call an LLM.

### Frontend UX

On detail page:

- `导出 Word`
- `导出 PPT`

After success:

```text
导出完成
```

If `manifest.exports` has records, show a compact export history:

- format;
- created time;
- file path or download link if safe.

### Acceptance Criteria

1. Asset detail can export Word from saved asset content.
2. Asset detail can export PPT if current PPT export capability is available.
3. Exported files are stored under the asset directory.
4. `manifest.exports` is updated only after successful export.
5. Existing current-answer export still works.
6. Export does not change `rag_status`.
7. Export does not call generation, retrieval, or indexing.

### Tests

Backend:

- asset Word export returns `.docx`;
- asset PPT export returns `.pptx` with current Agent05-quality fallback behavior preserved;
- export appends to `manifest.exports`;
- export history keeps at most 5 records per asset and deletes pruned local export files;
- export failure does not append to `manifest.exports`;
- unknown asset returns 404.

Frontend/static:

- detail page has asset export buttons;
- export buttons call `/api/assets/answers/{asset_id}/export/...`;
- current ask export still calls `/api/export/...`.

## 8. Phase 4: 质量与交付收口

### Goal

Make the asset library shippable by closing verification, documentation, and operational boundaries.

### Required Verification

Focused tests:

```bash
python3 -m pytest tests/test_answer_assets_api.py -q
python3 -m pytest tests/test_export_api.py tests/test_answer_assets_api.py -q
python3 -m pytest tests/test_project_files.py::test_ask_page_can_save_completed_answer_to_asset_library -q
```

Recommended non-live regression:

```bash
python3 -m pytest -q --ignore=tests/test_retrieval_quality_gate.py --ignore=tests/test_project_files.py
```

Static UI contract subset:

```bash
python3 -m pytest \
  tests/test_project_files.py::test_ask_page_exposes_language_switch_and_query_payload_uses_it \
  tests/test_project_files.py::test_ask_page_p0_layout_contract_keeps_input_in_first_viewport \
  tests/test_project_files.py::test_ask_page_p0_interactions_hide_export_and_clear_empty_state \
  tests/test_project_files.py::test_ask_export_buttons_use_neutral_publishing_theme_style \
  tests/test_project_files.py::test_ask_page_can_save_completed_answer_to_asset_library \
  tests/test_project_files.py::test_ask_embedded_state_preserves_answer_transcript_across_shell_switches \
  -q
```

If full `tests/test_project_files.py` or `tests/test_retrieval_quality_gate.py` is not run, the final report must state why.

### Manual Acceptance Script

The final handoff should verify this flow manually or through HTTP checks:

1. Open ask page.
2. Generate or simulate an answer.
3. Click `保存到资料库`.
4. Confirm `manifest.json` and `answer.md` exist.
5. Open `/assets`.
6. Open saved asset detail.
7. Export Word from detail.
8. Confirm `manifest.exports` records the export.
9. Confirm asset still has `rag_status="not_indexed"`.

### Safety Audit Checklist

Before declaring complete:

- Search for `/api/knowledge/add-generated`; verify save/detail/export paths do not call it.
- Search for `runtime.indexer.upsert`; verify asset save/export paths do not call it.
- Search for `generate_answer`, `deepseek`, `generation`; verify asset save/list/read/export paths do not invoke model routes.
- Verify `manifest.json` does not store API keys or secrets.
- Verify unknown asset ids cannot path-traverse outside `data_dir`.
- Verify every asset id accepted by read/export endpoints matches the strict safe-id policy `^ans_[A-Za-z0-9_-]+$`, and reject any id containing `.`, `/`, `\`, URL-encoded traversal, or path separators.
- Verify malformed manifests do not crash list page.

### Documentation Updates

Update or add:

- design doc status: from draft to implemented for completed phases;
- implementation plan checkboxes;
- a short user-facing note on where assets live and what `not_indexed` means;
- end-of-day handover if TZ asks for handoff or closeout.

### Acceptance Criteria

1. All phase-specific tests pass.
2. Non-live regression passes or skipped tests are explicitly justified.
3. Local service can demonstrate save -> list -> detail -> export.
4. No accidental RAG ingestion occurs.
5. No external model call occurs during asset operations.
6. Final summary lists changed files, tests run, and residual risks.

## 9. Architecture Evolution Continuity

The four phases preserve continuity with the existing system:

- current answer export remains a one-time operation;
- save asset creates durable local records;
- list/detail turns records into a usable library;
- asset export reuses deterministic export functions;
- future knowledge promotion can be added later as an explicit separate workflow.

This avoids a premature full document-management system while keeping the storage shape compatible with future asset browsing, editing, tagging, search, and promotion.

## 10. Objective Audit Notes

### Engineering Feasibility

Score: 90 / 100.

The design is implementable with the current FastAPI/static app stack and the existing file-first asset store. The main risk is frontend route ergonomics because the current app uses static HTML pages rather than a client router.

### Architecture Continuity

Score: 92 / 100.

The phases extend the completed V1 save API without changing the RAG ingestion boundary. Export reuse avoids duplicating document-generation logic.

### Safety

Score: 88 / 100.

The key safety boundary is explicit: saved assets remain `not_indexed`. The main residual risk is future pressure to add promotion or search in the same slice; that must remain blocked until separately designed.

### Overall Static Audit Score

Score: 90 / 100.

Status: Implemented in the current workspace with the default decisions below.

Implemented decisions:

- Phase 1 includes a visible ask-page entry plus direct `/assets` page.
- Phase 3 defers PDF export and implements Word/PPT only.
- Asset detail renders Markdown as plain text in this scope.

Verification completed:

- `python3 -m pytest tests/test_answer_assets_api.py tests/test_export_api.py tests/test_project_files.py::test_asset_library_page_lists_reads_and_exports_assets_without_knowledge_promotion tests/test_project_files.py::test_ask_page_can_save_completed_answer_to_asset_library -q` -> 14 passed.
- `python3 -m pytest -q --ignore=tests/test_retrieval_quality_gate.py --ignore=tests/test_project_files.py` -> 236 passed.
- Full `tests/test_project_files.py` was also attempted: 49 passed, 1 unrelated shared web shell contract failure in `/Users/tristanzh/agent/web/server.mjs`.
