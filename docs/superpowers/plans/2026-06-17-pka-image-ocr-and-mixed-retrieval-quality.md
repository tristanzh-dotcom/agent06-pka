# PKA Image OCR And Mixed Retrieval Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise quality confidence for image OCR and mixed-corpus retrieval while deferring low-frequency oversized PDF ingestion.

**Architecture:** Keep external upload and query APIs unchanged. Add internal image OCR quality assessment through `ParseQuality`, then expand mixed-corpus retrieval gates using the current clean-room corpus categories: image, OCR PDF, ordinary PDF, PPTX, and org-chart projections.

**Tech Stack:** FastAPI upload path, existing parser/retriever modules, pytest, FTS5/Chroma-backed clean-room corpus.

---

### Task 1: Image OCR Quality Signal

**Files:**
- Modify: `engine/quality.py`
- Modify: `engine/parser.py`
- Test: `tests/test_parser.py`

- [x] **Step 1: Write RED tests**

Add tests proving image OCR parse results include `quality.action == "image_ocr"` for useful OCR text and `quality.status == "low"` for very short OCR text.

- [x] **Step 2: Verify RED**

Run:
`python3 -m pytest -q tests/test_parser.py::test_parse_image_marks_useful_ocr_quality tests/test_parser.py::test_parse_image_marks_short_ocr_as_low_quality`

Expected: fail because image parse currently returns `quality=None`.

- [x] **Step 3: Implement image OCR quality assessment**

Add `assess_image_ocr_quality(text: str) -> ParseQuality` and call it from the image branch in `parse_file()`.

- [x] **Step 4: Verify GREEN**

Run the two target tests, then parser tests.

### Task 2: Mixed Corpus Retrieval Gate Expansion

**Files:**
- Modify: `tests/test_retrieval_quality_gate.py`

- [x] **Step 1: Add current clean-room corpus cases**

Add cases for screenshot one-liner, screenshot warranty risk, GEO OCR report, Doubao vision PDF, EGO milestone PDF, travel route PDF, wart PPTX, and VCC poster PPTX.

- [x] **Step 2: Verify cases pass or expose root cause**

Run:
`python3 -m pytest -q tests/test_retrieval_quality_gate.py`

Expected: pass for current clean-room corpus after recent org-chart bias fix; if not, debug before changing production logic.

### Task 3: Final Verification

**Files:**
- No production changes unless Task 2 exposes a real regression.

- [x] **Step 1: Run targeted tests**

Run:
`python3 -m pytest -q tests/test_parser.py tests/test_retrieval_quality_gate.py tests/test_indexer_retriever.py`

- [x] **Step 2: Run full regression**

Run:
`python3 -m pytest -q`

- [x] **Step 3: Confirm 8086 remains ready**

### Verification Notes

- Target regression: `112 passed, 1 warning`.
- Full regression: `257 passed, 15 warnings`.
- Mixed retrieval gate now covers 18 questions across `org_chart`, `pdf`, `pptx`, and `image`.
- Runtime verification: `http://127.0.0.1:8086/api/stats` returned `indexed_files=12,total_chunks=281`.
- Real image verification: `391.jpeg` parsed with `quality.status=high`, `quality.action=image_ocr`, and `611` OCR characters.

Run:
`curl -fsS http://127.0.0.1:8086/api/stats`
