# PKA General Local Office E2E Design

## Decision

The verifier is a general-content E2E tool, not an automotive-only acceptance gate. Keep the existing public sample matrix for reproducible public coverage, and add an explicit local-file invocation path for user-supplied documents.

## Scope

- Accept repeatable `--local-sample PATH::QUERY` arguments.
- Derive the upload file name and MIME type from the local file; retain the user-provided query as the server-query anchor.
- Copy each local source only into the verifier's fresh temporary runtime. Do not write it to the current PKA knowledge base or retain a copy after cleanup.
- Record the absolute local origin as `local_path` in the evidence report without treating it as a public URL.
- Use the normal multipart upload, parser, indexing, server-owned hybrid query, duplicate block, source deletion, and re-upload flow.

## Privacy and Runtime

- The supplied DOCX and PPTX remain on the local machine and are only read into the disposable local PKA process.
- Ollama `bge-m3` and PaddleOCR remain local. Cloud OCR and generation endpoints remain disabled in the isolated config.
- No product API, source lifecycle rule, model route, or persistent data directory changes.

## Acceptance

- A local DOCX and a local PPTX can each be exercised with their own Chinese anchor query.
- Their report rows show SHA-256, local path, upload status, coverage, chunks, server-query match, duplicate rejection, deletion, and successful re-upload.
- The deterministic test suite verifies local-spec parsing and rejects missing paths or malformed `PATH::QUERY` arguments without reading user documents.
