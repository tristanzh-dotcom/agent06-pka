# PKA Random Multi-Format Ingest E2E Design

## Goal

Validate PKA ingestion quality against a new, unrelated batch of public files
instead of relying on one known source per format.

## Matrix

The batch contains about eighteen files and covers every currently supported
extension: DOCX, PPTX, XLSX, PDF, PNG, JPG/JPEG, WebP, TXT and Markdown. Each
format family receives at least two materially different samples where public
availability permits:

- text-rich and layout-rich Office documents;
- tabular and formula/multi-sheet spreadsheets;
- native-text and scanned/image-dominant PDFs;
- text-bearing and natural-photo images;
- narrative and structured plain-text/Markdown files.

Samples come from multiple public domains and do not reuse the files from the
2026-07-15/16 verification runs.

## Isolation and Data Boundary

- Download into a fresh temporary directory.
- Run the existing production upload API in a disposable PKA runtime with its
  own raw files, FTS, Chroma, registries and task store.
- Never open or mutate the configured user knowledge base.
- Use local Ollama embeddings and local PaddleOCR. Disable cloud OCR.
- Do not send downloaded documents, extracted text or images to DeepSeek.
- Record source URL, retrieval time, SHA-256, detected MIME and byte size.

## Acceptance

For readable sources, require:

- valid file signature and expected extension;
- non-empty extraction without obvious replacement/control-character damage;
- `quality=high` and structurally plausible coverage;
- at least one indexed chunk and source-scoped anchor recall;
- exact duplicate rejection;
- successful delete and re-upload.

For image-dominant/scanned or natural-photo sources, a fail-closed
`review_required` outcome is a conditional pass only when it creates zero
chunks, exposes a quality reason and leaves no index pollution.

Each sample is classified as pass, conditional pass or fail. Failures are
separated into source-download, source-document, environment/provider or PKA
code defects. A batch cannot be called fully passed while a PKA code defect
remains.

## Report

Produce JSON and Markdown diagnostics with the complete matrix, provenance,
quality, coverage, chunks, recall, duplicate and source-lifecycle evidence.
Retain both initial failure evidence and the final rerun when a repair is
required.
