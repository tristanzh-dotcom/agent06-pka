# PKA Ingest Quality and Source Lifecycle Design

## Goal

Improve PKA ingestion for a normal single-user workflow so that supported documents are extracted completely enough to trust, questionable content does not silently enter the main index, and an accidental or outdated source can be removed or replaced without clearing the whole knowledge base.

## Scope

This design covers the ingest surface only:

- manual text and file upload;
- DOCX, PPTX, XLSX, PDF and image parsing;
- quality and extraction-coverage decisions;
- chunk/index metadata;
- exact duplicate handling;
- source listing, deletion and immediate undo;
- same-name version handling.

Question answering, retrieval ranking and answer generation are out of scope except that they consume the resulting index metadata unchanged.

## Product Rules

1. Exact duplicate content remains blocked before parsing, OCR, embedding or index writes.
2. A supported structured document must not claim ordinary success when known tables, notes or formulas were silently omitted.
3. DOCX tables, PPTX tables and notes, and XLSX formulas must be represented in extracted text.
4. Every indexed chunk must persist its ingest identity, original display name, parser coverage and quality state.
5. Low-quality PDF/image OCR and structurally partial content return `review_required` with zero indexed chunks by default.
6. `quality_policy=accept` explicitly permits the reviewed content to enter the main index and preserves its low/partial quality metadata.
7. Uploading different content with the same original filename returns `version_conflict` before parsing by default.
8. `version_policy=replace` indexes the new source first and deletes the prior active version only after the new index write succeeds.
9. `version_policy=keep` retains both versions with distinct stored source names and source IDs.
10. The user can list and delete one indexed source. Deletion removes that source's vector chunks, FTS chunks, content-identity record, source record and owned raw file.
11. A successful upload exposes an immediate undo action that uses the same single-source delete contract.
12. Existing historical sources are lazily represented from current index metadata; missing new metadata is reported as unknown rather than invented.

## Architecture

### Parser coverage

`engine/parser.py` emits `ParseResult.metadata["coverage"]` with:

- `format`;
- extracted counts such as paragraphs, tables, slides, notes, sheets and formulas;
- `warnings` for known omissions or missing cached values;
- `status`: `complete` or `partial`.

DOCX extraction walks paragraphs and tables in document order. PPTX extraction walks text frames, tables and notes by slide. XLSX extraction loads formula and cached-value views, preserves formula expressions, and includes cached results when present.

### Structured-text extraction quality

TXT, Markdown, DOCX, PPTX and XLSX extraction also receives a deterministic
`ParseQuality` assessment. This assessment is deliberately conservative: it
does not judge writing quality, factual correctness or domain meaning. It marks
content `low` only when extraction produced no usable text, a material ratio of
replacement/control characters, highly repeated lines, or effectively
unreadable non-text output. Short but readable content remains `high`.

Low structured-text quality follows the existing `review_required` contract and
produces zero indexed chunks unless the user explicitly resubmits with
`quality_policy=accept`.

### Durable source records

`engine/source_registry.py` owns a local SQLite source table keyed by `source_id`. A record stores:

- `source_id`, `content_hash` and `content_kind`;
- `original_name` and indexed `source_name`;
- `raw_file_path`;
- `status`, `chunk_count`, `quality` and `coverage`;
- timestamps.

The source registry is the lifecycle owner for list, version conflict lookup and delete. The existing content registry remains the exact-content reservation owner.

### Chunk identity and metadata

New file and manual-text ingests receive a UUID-based `source_id`. Chunk IDs use `source_id#chunk_index`; the user-facing `source_name` remains the filename or manual label. Chunk metadata carries source ID, original name, raw path, quality and coverage. Existing chunk IDs remain readable and do not require migration.

### Review flow

The browser retains the selected `File` object. A first upload that returns `review_required` or `version_conflict` performs no index write. The upload slot displays explicit actions:

- low/partial quality: `仍然入库` or `取消`;
- same-name version: `替换旧版本`, `同时保留` or `取消`.

Choosing an action resubmits that one file with the corresponding policy. No modal confirmation is required.

### Source management

The ingest page includes an `已录入资料` section populated from `GET /api/ingest/sources`. Each source shows name, type, ingest time, quality, extraction coverage and chunk count. `DELETE /api/ingest/sources/{source_id}` removes exactly one source. Upload success displays `撤销本次录入`, which calls the same endpoint.

## Error Handling

- New-source index failure leaves an existing version untouched.
- Review-required and version-conflict responses contain zero chunks and are not counted as successful uploads.
- Source deletion validates that any raw path is inside `data_dir` before deleting it.
- A missing raw file does not prevent index and registry deletion.
- Partial deletion returns an error and keeps the source record marked `delete_failed`; it must not claim success.
- Historical sources without a source ID receive a deterministic legacy ID derived from source name and raw path when listed.

## API Contract

File endpoints accept optional form fields:

- `quality_policy`: `review` or `accept`;
- `version_policy`: `review`, `replace` or `keep`.

New response states:

- `review_required` with `quality`, `coverage`, `chunks=0`;
- `version_conflict` with `existing_source`, `chunks=0`.

Source management:

- `GET /api/ingest/sources` returns `{status, sources}`;
- `DELETE /api/ingest/sources/{source_id}` returns the deleted source identity and chunk count.

## Testing

Strict TDD applies to every deterministic behavior:

- DOCX table, PPTX table/notes and XLSX formula extraction;
- coverage and quality metadata propagation to vector/FTS records;
- low-quality review gate and explicit acceptance;
- same-name conflict, replace-after-success and keep-both behavior;
- source list, single-source deletion, raw-file cleanup and undo contract;
- batch counts and browser rendering for review/conflict states;
- compatibility with exact duplicate, OCR and existing ingest tests.

## Non-Goals

- multi-user locking or permission design;
- storage-quota enforcement;
- background migration of every historical raw file;
- source editing in place;
- changes to question-session or answer-generation behavior.
