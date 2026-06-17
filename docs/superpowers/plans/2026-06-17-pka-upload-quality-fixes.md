# PKA Upload Quality Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two upload-quality regressions found in live testing: image OCR empty output is silent, and ordinary PDF table/code pages are misclassified as org charts.

**Architecture:** Keep parser boundaries intact. Tighten `engine/parser.py` only: image parsing must raise a clear `ValueError` when OCR returns no usable text; PDF org-chart detection must reject table-of-contents, code, parameter-table, itinerary, travel-prep, and milestone-table pages before applying layout fallback.

**Tech Stack:** FastAPI upload path, PyMuPDF PDF text extraction, existing parser/unit tests, pytest.

---

### Task 1: Image OCR Empty Output

**Files:**
- Modify: `engine/parser.py`
- Test: `tests/test_parser.py`

- [x] **Step 1: Write RED test**

Add `test_parse_image_rejects_empty_ocr_text` in `tests/test_parser.py`.

- [x] **Step 2: Verify RED**

Run: `python3 -m pytest -q tests/test_parser.py::test_parse_image_rejects_empty_ocr_text`
Expected: fail because current parser returns `ParseResult(source_type="image", text="")`.

- [x] **Step 3: Implement minimal parser guard**

After `ocr_client.extract(...)`, reject blank text with `ValueError("OCR produced no usable text for image")`.

- [x] **Step 4: Verify GREEN**

Run: `python3 -m pytest -q tests/test_parser.py::test_parse_image_rejects_empty_ocr_text`
Expected: pass.

### Task 2: PDF Org-Chart False Positives

**Files:**
- Modify: `engine/parser.py`
- Test: `tests/test_parser.py`

- [x] **Step 1: Write RED tests**

Add tests proving parameter-table/code pages, table-of-contents pages, itinerary pages, travel-preparation pages, and milestone-table pages are not treated as org charts.

- [x] **Step 2: Verify RED**

Run the two new tests; expected failure is non-empty `parsed.pre_chunks`.

- [x] **Step 3: Implement negative heuristics**

Reject org-chart fallback when a page is dominated by table/code/list/document-control markers such as `参数名称`, `默认值`, `描述`, `Python`, `目录`, itinerary headers, travel-prep checklist fields, milestone-table fields, dense bullets, or dotted/table row patterns.

- [x] **Step 4: Verify GREEN**

Run targeted parser tests and then full pytest.

### Verification Notes

- Target parser tests: `20 passed`.
- Ingest quality tests: `14 passed`.
- Full regression: `245 passed, 15 warnings`.
- Live sample replay: `391.jpeg` now raises `ValueError: OCR produced no usable text for image`; the three ordinary PDFs observed during upload testing now parse with `org_chart_chunks=0`.
