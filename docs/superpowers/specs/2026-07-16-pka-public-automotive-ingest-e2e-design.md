# PKA Public Automotive Ingest E2E Test Design

## Goal

Use publicly downloadable automotive-industry documents to verify the complete PKA ingestion path in an isolated runtime: HTTP upload, parsing or local OCR, quality and coverage reporting, chunk/index writes, source lifecycle, and retrieval back-read.

## Scope and Isolation

- Create a temporary test root outside `PKA_Data`; use separate raw-file, SQLite/FTS, Chroma, source-registry, and task-store paths.
- Start a disposable local PKA process on a non-default loopback port. The current user knowledge base and its index are never opened or modified.
- Use the production upload APIs and browser upload surface for one smoke test. The remainder of the matrix uses real multipart HTTP uploads for deterministic automation.
- Use only downloaded public documents. Record origin URL, retrieval timestamp, SHA-256, content type, byte size, upload response, coverage, quality result, indexed chunk count, and retrieval result.
- Use local Ollama `bge-m3` for embeddings and local PaddleOCR when an image OCR branch is exercised. Cloud/Volcengine OCR is disabled for this run; no private PKA data is sent outside the machine.
- The run does not change product code unless an observed reproducible failure requires a separately approved repair.

## Public Sample Matrix

| Format | Source | Purpose | Required evidence |
|---|---|---|---|
| DOCX | UNECE WP.29 R154 base document: `https://wiki.unece.org/download/attachments/265978083/Base%20Document%20for%20R154_04_200625.docx?api=v2` | Real vehicle-regulation Word structure | non-empty text, paragraph/table coverage, vehicle-regulation anchor recall |
| PPTX | UNECE EVE IWG: `https://unece.org/sites/default/files/2025-03/GRPE-92-49r1e.pptx` | Real automotive EV presentation | slide coverage and EV/battery anchor recall |
| XLSX | ONS new vehicle registrations: `https://www.ons.gov.uk/file?uri=%2Feconomy%2Feconomicoutputandproductivity%2Foutput%2Fdatasets%2Fuknewvehicleregistrationsandproduction%2F2026%2Fsmmtvehicleregandproddataset090726.xlsx` | Real multi-sheet automotive statistics workbook | sheet/row coverage and registration/production anchor recall |
| PDF | NHTSA tire-safety infographic: `https://www.nhtsa.gov/sites/nhtsa.gov/files/2021-11/Tires_InTheGarage_Infographic_102621_v1_-eng-tag.pdf` | Real automotive PDF with visual layout | page coverage, quality gate result, and tire/TPMS anchor recall if indexed |
| PNG | NHTSA blind-spot illustration: `https://www.nhtsa.gov/sites/nhtsa.gov/files/styles/large/public/lane_changing-blindspotdetection.png?itok=ZA5351jD` | Real automotive safety image | local OCR outcome; either meaningful indexed text or an explicit low-quality/review-required decision with zero chunks |
| Markdown | nuScenes CAN-bus README: `https://raw.githubusercontent.com/nutonomy/nuscenes-devkit/refs/heads/master/python-sdk/nuscenes/can_bus/README.md` | Real automotive technical Markdown | text/line coverage and CAN-bus/vehicle-monitor anchor recall |
| TXT | A public automotive plain-text data file selected during download validation, or a documented exclusion if no stable direct TXT artifact is available | Exercise the TXT decoder separately from Markdown | text/line coverage and source-specific anchor recall |

## Test Flow

1. Download only candidates whose response is the expected file type and within the configured upload size limit. Hash and retain them under the isolated test root.
2. Upload each retained sample through `POST /api/ingest/file` with the production multipart shape.
3. For accepted OCR tasks, poll until terminal status. Do not silently accept a low-quality or partial result; submit `quality_policy=accept` only when the matrix explicitly records that the source is expected to require manual acceptance.
4. Capture parse quality and coverage. A supposedly complete structured document with empty extraction is a failure; a difficult visual document may validly result in `review_required`, provided it has zero indexed chunks and a clear reason.
5. Verify FTS and vector retrieval against an anchor query for every indexed source. The expected source must appear in the result set; exact rank is recorded, not hard-coded, because the corpus is multi-document.
6. Re-upload each indexed file unchanged and verify exact-duplicate blocking before parsing/indexing.
7. Delete one indexed source with `DELETE /api/ingest/sources/{source_id}`, verify its raw file and retrieval hits disappear, then re-upload it successfully.
8. Use the browser once to upload a representative document and verify visible status, coverage/quality details, and source-list entry. Delete it through the visible source-management control.

## Pass/Fail Rules

- **Pass:** expected parser path runs, response status follows the quality policy, metadata is persisted, and source lifecycle/retrieval checks succeed.
- **Conditional pass:** a genuinely image-dominant/scanned document returns `review_required` or OCR failure without index pollution, with sufficient diagnostic metadata.
- **Failure:** unexpected parser exception; complete status with empty/obviously missing required extraction; incorrect coverage; chunks indexed after a rejected quality gate; source deletion leaves index/raw-file residue; duplicate creates another source; or an indexed source cannot be recalled by its documented anchor query.

## Report

The report will list every source and URL, local checksum, parser/quality/coverage output, chunk count, FTS/vector recall result, duplicate/delete result, elapsed time, and a classification of any failure as code defect, environment/provider limitation, source-download issue, or source-document limitation.
