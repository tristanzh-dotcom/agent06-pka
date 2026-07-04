# PKA Save Answer Asset Library V1 Design

> Date: 2026-07-03
> Status: design draft
> Scope: 保存到资料库 / Save Asset for completed PKA answer results

## 1. Corrected Workflow Boundary

This workflow is about `保存到资料库`, not `加入知识库`.

PKA has three post-answer actions:

| Action | Chinese label | Purpose | Persistent output | RAG impact |
|---|---|---|---|---|
| Export | 导出 | Produce a one-time file such as Word, PDF, or PPT | export file | none |
| Save Asset | 保存到资料库 | Save the completed answer as a reusable generated asset | asset record in the local asset library | none by default |
| Add to Knowledge | 加入知识库 | Promote a reviewed generated answer into RAG retrieval | generated knowledge source plus indexed chunks | yes |

V1 designs and later implements only `Save Asset`.

`Add to Knowledge` remains a future promotion action. It must not be silently bundled into saving an asset.

## 2. Product Goal

After PKA finishes a RAG answer, TZ should be able to save that result into a local generated-asset library.

The saved asset should preserve:

- the original question;
- the final answer;
- source chunk references;
- evidence or source status available from the answer stream;
- answer language;
- answer mode;
- model route;
- created timestamp;
- future export and promotion status.

The asset should be durable, inspectable, and reusable. It should not automatically affect future retrieval.

## 3. First-Principles Constraints

1. A saved asset is not a primary source.
2. A saved asset is not automatically part of the RAG knowledge base.
3. Saving an asset must not call DeepSeek, codex-base, or any other LLM.
4. The original user question must be preserved exactly.
5. Query expansion variants must not replace the original question.
6. The asset library must be local-first and fit PKA's current file-backed data ownership model.
7. V1 should avoid introducing a large external document-management platform dependency.

## 4. V1 User Experience

On the ask page, after an answer completes, the operation bar should show:

- `导出 Word`
- `导出 PDF` if PDF export is added in the export slice, otherwise keep existing export buttons unchanged
- `导出 PPT` if still supported by the current page
- `保存到资料库`

When the user clicks `保存到资料库`:

1. The frontend builds an `AnswerResult` snapshot from the completed answer.
2. The frontend posts it to the asset API.
3. The backend writes a local asset record.
4. The UI shows a saved state with the asset title and creation time.
5. The same answer can be saved more than once; each click creates a separate asset version.

V1 must include a minimal way to verify saved assets:

- a list API for recent answer assets;
- preferably a small `资料库` page if the implementation stays thin.

Recommendation: include the list API in V1 as mandatory, and add a simple list page if implementation cost stays small. Without any list or detail surface, `保存到资料库` is hard to validate as a user feature.

## 5. Data Model

The canonical saved object is `AnswerAsset`.

```json
{
  "asset_id": "ans_20260703_153012_ab12cd",
  "asset_type": "answer_result",
  "title": "JLR 面试复盘总结",
  "question": "original user question",
  "answer": "final rendered model answer",
  "sources": [
    {
      "source_name": "source.md",
      "source_type": "md",
      "chunk_index": 0,
      "chunk_id": "source.md#0",
      "relevance": 0.91,
      "raw_file_path": "raw/2026-06-04/source.md"
    }
  ],
  "source_status": "grounded|thin|no_answer",
  "evidence": {},
  "language": "zh|en",
  "answer_mode": "answer|interview_story|retrospective|english_report|ppt_outline|decision_memo",
  "model_route": "deepseek|codex-base|dual|local_fallback",
  "created_at": "2026-07-03T15:30:12+08:00",
  "updated_at": "2026-07-03T15:30:12+08:00",
  "tags": [],
  "status": "saved",
  "rag_status": "not_indexed",
  "exports": []
}
```

Rules:

- `asset_id` is backend-assigned.
- `title` defaults to a short derivation from the question, without LLM generation.
- `rag_status` is `not_indexed` in V1.
- `exports` records generated file derivatives only when an export is created or attached.
- `sources` should store references and metadata, not full source excerpts.

## 6. Storage Design

Use file-first local storage under `data_dir`.

Recommended path:

```text
{data_dir}/assets/answers/YYYY-MM-DD/{asset_id}/
  manifest.json
  answer.md
```

Optional future derivatives:

```text
{data_dir}/assets/answers/YYYY-MM-DD/{asset_id}/exports/
  answer.docx
  answer.pdf
  answer.pptx
```

`manifest.json` contains machine-readable metadata.

`answer.md` contains human-readable content:

```markdown
# Asset Title

## Question

...

## Answer

...

## Sources

- source.md#0
- source.pdf#3

## Metadata

- asset_id: ans_...
- asset_type: answer_result
- source_status: grounded
- language: zh
- answer_mode: retrospective
- model_route: deepseek
- rag_status: not_indexed
- created_at: ...
```

Why file-first:

- local ownership and easy backup;
- no invisible database-only record;
- simple inspection when debugging;
- compatible with later import into a larger asset manager;
- avoids premature dependency on a third-party document platform.

## 7. Backend API Contract

### Save Asset

```http
POST /api/assets/answers
```

Request:

```json
{
  "question": "...",
  "answer": "...",
  "sources": [],
  "source_status": "grounded",
  "evidence": {},
  "language": "zh",
  "answer_mode": "answer",
  "model_route": "deepseek",
  "title": ""
}
```

Response:

```json
{
  "status": "ok",
  "asset_id": "ans_20260703_153012_ab12cd",
  "asset_type": "answer_result",
  "title": "JLR 面试复盘总结",
  "asset_path": "assets/answers/2026-07-03/ans_20260703_153012_ab12cd",
  "manifest_path": "assets/answers/2026-07-03/ans_20260703_153012_ab12cd/manifest.json",
  "answer_path": "assets/answers/2026-07-03/ans_20260703_153012_ab12cd/answer.md",
  "rag_status": "not_indexed",
  "created_at": "2026-07-03T15:30:12+08:00"
}
```

Validation:

- empty `question` returns 400;
- empty `answer` returns 400;
- malformed `sources` returns 400;
- `source_status="no_answer"` may still be saved as an asset, because the asset library records user-visible outputs, not only grounded knowledge;
- the endpoint must not call any LLM or embedding service;
- the endpoint must not write to FTS5 or ChromaDB.

### List Assets

```http
GET /api/assets/answers?limit=50
```

Response:

```json
{
  "status": "ok",
  "assets": [
    {
      "asset_id": "ans_20260703_153012_ab12cd",
      "title": "JLR 面试复盘总结",
      "question": "original user question",
      "language": "zh",
      "answer_mode": "retrospective",
      "source_status": "grounded",
      "rag_status": "not_indexed",
      "created_at": "2026-07-03T15:30:12+08:00",
      "asset_path": "assets/answers/2026-07-03/ans_20260703_153012_ab12cd"
    }
  ]
}
```

### Read Asset

```http
GET /api/assets/answers/{asset_id}
```

Response:

```json
{
  "status": "ok",
  "asset": {
    "asset_id": "ans_20260703_153012_ab12cd",
    "manifest": {},
    "answer_markdown": "..."
  }
}
```

## 8. Frontend State Contract

The existing ask page already tracks:

- `askState.question`;
- `askState.answer`;
- `askState.sources`;
- `askState.language`;
- `askState.messages`.

V1 should add one helper:

```text
buildAnswerResultSnapshot()
```

It returns the request body for `POST /api/assets/answers`.

Availability rules:

- disabled while the answer is streaming;
- enabled after `done` if `question` and `answer` are non-empty;
- remains enabled for `source_status="no_answer"` because saving an asset is not knowledge promotion;
- does not automatically call export;
- does not automatically call add-to-knowledge.

UI copy:

- button: `保存到资料库`
- saving: `保存中...`
- success: `已保存到资料库`
- failure: `保存失败`

## 9. Relationship With Export

Export remains an independent one-time action.

The asset library should store the source answer in Markdown plus metadata. It should not require Word/PDF generation at save time.

Future behavior can attach exported derivatives to an asset:

1. User saves answer to asset library.
2. User opens asset detail.
3. User exports Word/PDF/PPT from that asset.
4. The generated export file path is added to `manifest.exports`.

This avoids making every save slow or dependent on document-generation libraries.

## 10. Relationship With Add To Knowledge

`保存到资料库` and `加入知识库` share the same input object, but they have different effects.

Save Asset:

- writes asset files;
- keeps `rag_status="not_indexed"`;
- does not affect future retrieval;
- may save no-answer outputs for record keeping.

Add to Knowledge:

- writes or promotes generated knowledge;
- indexes into RAG;
- must mark `generated=true` and `not_primary_source=true`;
- should reject default `no_answer` promotion;
- must update generator prompt behavior for generated secondary knowledge.

Future promotion path:

```http
POST /api/assets/answers/{asset_id}/promote-to-knowledge
```

This is not part of Save Asset V1.

## 11. GitHub Tool Evaluation

Prior discussion raised whether high-star GitHub projects or tools can help build the asset library.

V1 recommendation: do not integrate a third-party asset/document platform directly. Use local files and small PKA-native APIs first.

Reasons:

- current need is a narrow generated-answer asset store, not a full DMS;
- external platforms add deployment, auth, backup, migration, and license complexity;
- several strong projects are optimized for scanned document management or team wikis rather than PKA answer-result lifecycle;
- PKA needs tight control over RAG boundaries and promotion state.

Reference candidates for future evaluation:

| Project | Current signal checked on 2026-07-03 | Relevant strengths | V1 decision |
|---|---|---|---|
| [paperless-ngx](https://github.com/paperless-ngx/paperless-ngx) | GitHub shows about 42.7k stars; GPL-3.0; document-management and OCR focus | mature document archive, tags, OCR, local self-hosting pattern | reference for document-management concepts only |
| [Memos](https://github.com/usememos/memos) | GitHub shows about 61.2k stars; MIT; Markdown-native self-hosted notes | lightweight capture and Markdown asset style | reference for simple note capture UX |
| [Docmost](https://github.com/docmost/docmost) | GitHub shows about 20.8k stars; AGPL-3.0; wiki/documentation focus | spaces, pages, collaboration | too heavy for V1 |
| [BookStack](https://github.com/BookStackApp/BookStack) | GitHub mirror shows about 18.9k stars and is now managed on Codeberg; MIT | structured knowledge pages and shelves | useful conceptual reference, not a direct dependency |
| [TagSpaces](https://github.com/tagspaces/tagspaces) | GitHub shows about 5.2k stars; AGPL-3.0; offline local file tagging | local-first file organization and sidecar metadata | closest conceptual reference for local file-first assets |

Future evaluation criteria:

- license compatibility;
- offline/local-first behavior;
- whether raw private files leave the machine;
- whether integration can stay optional;
- import/export format stability;
- ability to represent generated assets separately from primary knowledge sources.

## 12. Non-Goals For V1

Do not implement:

- adding saved assets to RAG;
- generated-source retrieval policy;
- asset editing;
- folders, collections, or complex tagging UI;
- full-text search across asset library;
- external GitHub project integration;
- cloud sync;
- multi-user permissions;
- automatic background capture of every answer;
- automatic Word/PDF generation during save.

## 13. Acceptance Criteria

V1 is successful when:

1. A completed answer can be saved into the local asset library.
2. The saved asset has both `manifest.json` and `answer.md`.
3. The asset preserves question, answer, sources, source status, language, model route, answer mode, and timestamp.
4. Saving the asset does not call any LLM, embedding service, FTS5 write, or ChromaDB write.
5. Saved assets are listable through an API.
6. The ask page clearly separates export, save asset, and add-to-knowledge concepts.
7. The asset record marks `rag_status="not_indexed"`.
8. A saved no-answer result can be preserved as an asset but cannot be confused with knowledge promotion.

## 14. Implementation Notes For Later

When implementation begins, use TDD.

Suggested backend tests:

- save endpoint rejects empty question;
- save endpoint rejects empty answer;
- save endpoint writes `manifest.json`;
- save endpoint writes `answer.md`;
- save endpoint returns `rag_status="not_indexed"`;
- save endpoint does not call indexer upsert;
- list endpoint returns saved assets newest first;
- read endpoint returns manifest plus markdown.

Suggested frontend/static tests:

- ask page contains `保存到资料库` in the completed-answer operation area;
- button is hidden or disabled before answer completion;
- button posts the `AnswerResult` snapshot;
- export payload remains backward-compatible;
- no call to `/api/knowledge/add-generated` happens during save.

Git rule:

- do not run `git commit`, `git push`, `git pull`, `git stash`, or `git rebase` in this business repo.
