# PKA Answer Result Operations SDD

> Date: 2026-07-03
> Status: design draft
> Scope: post-answer operation layer for PKA RAG answers

## 1. Problem

PKA already behaves as a RAG question-answering system:

1. the user asks an original question;
2. PKA retrieves personal knowledge chunks;
3. the configured model route generates an answer from the question plus retrieved chunks;
4. the ask page displays the answer and sources;
5. the user may export the answer.

The missing layer is a formal product and API contract for the object that exists after step 4. That object is an `AnswerResult`: a completed model answer plus the question, sources, evidence metadata, language, route, and inferred answer mode.

Without this layer, post-answer actions are ambiguous. `Export`, `Save Asset`, and `Add to Knowledge` can be confused even though they have different persistence and RAG impact.

## 2. Current Boundary

This workflow does not design the full knowledge-base ingestion system and does not build a generated asset library. It only defines the operation layer that appears after a model answer is complete.

The three operation names are fixed:

- `Export / 导出`: create a one-time document artifact such as Word or PPT. It does not affect RAG.
- `Save Asset / 保存资产`: save the answer as a managed generated asset for later browsing, editing, reuse, or promotion. This is a later product surface and is not part of v1.
- `Add to Knowledge / 加入知识库`: deliberately insert a reviewed generated answer into RAG as generated secondary knowledge. This affects future retrieval and must preserve provenance.

## 3. AnswerResult Contract

`AnswerResult` is the canonical post-answer snapshot. It is not a knowledge-base entry and not a generated asset library record.

Minimum shape:

```json
{
  "question": "original user question",
  "answer": "final rendered model answer",
  "sources": [
    {
      "source_name": "source.md",
      "source_type": "md",
      "chunk_index": 0,
      "relevance": 0.91,
      "chunk_id": "source.md#0",
      "raw_file_path": "raw/2026-06-04/source.md"
    }
  ],
  "source_status": "grounded",
  "evidence": {
    "coverage": {
      "source_count": 2,
      "chunk_count": 5,
      "source_types": {"md": 2},
      "coverage_status": "grounded",
      "low_evidence": false,
      "query_variants": ["..."]
    },
    "top_sources": [{"source_name": "source.md", "chunk_count": 2}],
    "missing_evidence": [],
    "input_fidelity": {},
    "answer_mode": {"mode": "answer", "reason": "default"}
  },
  "language": "zh",
  "created_at": "2026-07-03T12:00:00+08:00",
  "model_route": "deepseek|codex-base|dual|local_fallback",
  "answer_mode": "answer"
}
```

Required rules:

- `question` is always the original user question, not a query-expansion variant.
- `answer` is captured only after generation completes or fails into a final user-visible message.
- `sources` is the source list from the final SSE `sources` event.
- `source_status="no_answer"` means `sources` must be empty for the operation layer.
- `evidence` should be present when the backend can provide it. v1 should make this available without requiring debug-only behavior for operation consumers.
- `answer_mode` is the internal mode from `engine.answer_planner.infer_answer_mode()`.
- `model_route` is route metadata for audit and future persistence. It must not expose API keys.

## 4. Operation Matrix

| Operation | User intent | Persistent output | RAG impact | v1 status |
|---|---|---|---|---|
| Export Word | Make a document copy | `.docx` under exports | none | existing, keep compatible |
| Export PPT | Make a slide deck copy | `.pptx` under exports | none | existing, keep compatible |
| Save Asset | Manage generated work product | generated asset record | none by default | non-goal |
| Add to Knowledge | Make reviewed answer searchable | generated Markdown knowledge source plus indexed chunks | yes | design interface now; implement in next slice |

## 5. Frontend State Contract

The ask page currently maintains `askState.question`, `askState.answer`, `askState.sources`, and `askState.messages`.

v1 should promote that state into a helper-level `AnswerResult` snapshot when generation reaches a terminal state:

- on new question: clear the current `AnswerResult`;
- on token events: keep appending to the draft answer;
- on final `sources` event: store `source_status`, normalized `sources`, and optional `evidence`;
- on done: mark the `AnswerResult` as complete and enable post-answer actions;
- on no-answer: allow export only if there is a final visible answer, but keep `Add to Knowledge` disabled unless a later explicit force path exists.

The frontend does not need a generated asset list, asset detail page, or asset editor in this slice.

## 6. Backend API Contract

Existing export endpoints should remain backward-compatible:

```http
POST /api/export/word
POST /api/export/ppt
```

Their current body can remain:

```json
{
  "question": "...",
  "answer": "...",
  "sources": []
}
```

They may later accept optional `evidence`, `language`, `model_route`, and `answer_mode`, but exports must not require those fields.

The operation-layer contract should reserve the add-to-knowledge endpoint owned by the generated-knowledge slice:

```http
POST /api/knowledge/add-generated
```

Request:

```json
{
  "question": "...",
  "answer": "...",
  "sources": [],
  "evidence": {},
  "language": "zh",
  "model_route": "deepseek|codex-base|dual|local_fallback",
  "answer_mode": "answer"
}
```

Response:

```json
{
  "status": "ok",
  "source_name": "generated_answer_20260703_153012.md",
  "source_type": "generated_asset",
  "chunks": 1,
  "chunk_ids": ["generated_answer_20260703_153012.md#0"],
  "raw_file_path": "generated/knowledge/2026-07-03/generated_answer_20260703_153012.md"
}
```

This endpoint must be deterministic. It must not call DeepSeek, codex-base, or any other LLM.

## 7. Add-To-Knowledge Interface Boundary

The Answer Result operation layer owns:

- building the `AnswerResult` snapshot;
- deciding whether the UI action should be available;
- sending the reviewed snapshot to `/api/knowledge/add-generated`;
- showing success or failure state for the action.

The add-to-knowledge workflow owns:

- generated Markdown file format;
- metadata preservation;
- indexing mechanics;
- generated-source retrieval policy;
- prompt labeling when generated chunks are retrieved later.

The operation layer must pass enough data for that workflow:

- original question;
- final answer;
- source chunk identifiers and source names;
- evidence coverage status;
- language;
- model route;
- answer mode;
- timestamp, either supplied by the frontend or assigned by the backend.

## 8. Guardrails

Generated model output must not be treated as primary evidence.

For any future `Add to Knowledge` action:

- the user must trigger the action deliberately;
- no automatic answer write-back is allowed;
- empty `question` or empty `answer` must be rejected;
- `source_status="no_answer"` should disable the default action;
- `coverage_status="thin"` may warn in the UI but should not block backend v1;
- saved generated knowledge must use `source_type="generated_asset"`;
- saved generated knowledge must include `generated=true` and `not_primary_source=true` metadata;
- recursive automatic re-ingestion of generated answers is forbidden.

## 9. Non-Goals

Do not build these in this slice:

- full generated asset library;
- asset browsing or search UI;
- asset detail page;
- asset editing before indexing;
- asset-to-chat replay;
- automatic background answer capture;
- retrieval penalties or boosts for generated knowledge;
- global shared web visual-system changes.

## 10. TDD Plan For Implementation Slice

When implementation starts, write tests first.

Backend tests:

1. `POST /api/knowledge/add-generated` rejects empty question and answer.
2. The endpoint writes a generated Markdown file under `data_dir/generated/knowledge/YYYY-MM-DD/`.
3. The file and indexed chunks preserve `source_type="generated_asset"`, `generated=true`, and `not_primary_source=true`.
4. Metadata includes question, source chunk IDs, evidence coverage, language, model route, and answer mode.
5. The endpoint does not call any LLM client.
6. Future `/api/query` can retrieve a generated entry and exposes it as generated source metadata.

Frontend/static contract tests:

1. The ask page has a single helper that builds an `AnswerResult` from current state.
2. Export still sends the existing compatible payload.
3. `Add to Knowledge` is disabled before an answer is complete.
4. `Add to Knowledge` is disabled for `source_status="no_answer"`.
5. The action posts the full `AnswerResult` snapshot to `/api/knowledge/add-generated`.

Verification command for the current Agent06 backend path:

```bash
python3 -m pytest -q --ignore=tests/test_retrieval_quality_gate.py --ignore=tests/test_project_files.py
```

`tests/test_retrieval_quality_gate.py` and `tests/test_project_files.py` have known external/live workspace dependencies from prior handover notes.

## 11. Recommended V1 Implementation Order

1. Add backend generated-knowledge request/response models and failing API tests.
2. Implement generated Markdown writing with metadata.
3. Index generated Markdown while preserving generated metadata.
4. Update generator prompt/source labeling for `source_type="generated_asset"`.
5. Add frontend `AnswerResult` snapshot helper and action availability state.
6. Add the `Add to Knowledge` button only after backend tests pass.
7. Run focused backend and static contract tests.

This order keeps the operation layer grounded in data contracts before adding visible controls.
