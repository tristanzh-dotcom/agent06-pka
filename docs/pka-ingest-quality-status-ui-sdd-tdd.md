# PKA 入库质量状态展示 — SDD/TDD

> Date: 2026-06-14

## 1. Problem

PKA already blocks untrusted `needs_ocr` content from ChromaDB and FTS5. The remaining gap is user visibility: after upload, the UI must make it obvious whether a file was fully indexed, partially OCR-indexed, low-quality indexed, skipped, or failed.

## 2. SDD: Upload Response Contract

The backend keeps the existing machine contract:

- `status`: `ok | skipped | error`
- `chunks`: indexed chunk count
- `quality.status`: source text quality, `high | low | needs_ocr`
- `quality.action`: processing action
- `quality.ocr_partial`: `true` when OCR indexed only part of the source
- `quality.ocr_pages_processed`: processed page count
- `quality.source_page_count`: source PDF page count
- `quality.ocr_page_limit_reached`: `true` when the configured OCR page cap stopped processing

No user-facing copy is stored in the index contract. The frontend derives display text from the fields above.

## 3. SDD: Frontend Status Mapping

`static/app.js` must map these actions:

| Backend action | Slot state | User text |
|---|---|---|
| `direct` | complete | `已全文入库` |
| `cleaned` | complete | `已清洗入库` |
| `low_indexed` | low | `低质量入库` |
| `ocr` + `ocr_partial=false` | ocr | `OCR 入库` |
| `ocr` + `ocr_partial=true` | ocr | `部分 OCR 入库 · 仅 OCR 前 N 页 / 共 M 页` |
| `needs_ocr_skipped` | skipped | `需 OCR 未入库 · 未进入主知识库，避免污染检索` |
| `ocr_failed_skipped` | skipped | `OCR 失败未入库 · 未进入主知识库，避免污染检索` |
| `ocr_timeout_skipped` | skipped | `OCR 超时未入库 · 未进入主知识库，避免污染检索` |

Batch feedback must preserve the aggregate counts and append per-file skipped/failure details. Skipped details must state that the file did not enter the main knowledge base.

## 4. SDD: Refresh Behavior

After successful text ingest, file ingest, or clear, the embedded page continues to post `agent06:knowledge-updated` so the shell can refresh stats. A skipped-only upload still sends the event because the user action completed and shell state should be refreshed from the authoritative stats endpoint.

## 5. TDD Cases

1. Static frontend contract requires partial OCR copy, skipped copy, timeout copy, and `ocr_partial` handling.
2. Static frontend contract requires skipped batch detail to include `未进入主知识库，避免污染检索`.
3. Existing backend tests continue to prove `needs_ocr` failures return `chunks: 0` and do not index.
4. Existing state-refresh tests continue to prove ingest and clear notify the shell.
