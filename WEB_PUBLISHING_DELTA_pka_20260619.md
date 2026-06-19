# Agent06 PKA Web Publishing Delta - 2026-06-19

## Purpose

This archive records the web-publishing-relevant changes made in the current Agent06 PKA workflow so the separate web publishing workflow can preserve platform state correctly.

## Scope Classification

- Classification: feature-required Agent06 project delta.
- Shared web visual system: not changed.
- `/Users/tristanzh/agent/web`: not modified by this workflow.
- PKA repo commit containing these changes: `dd2713e chore(agent06-pka): commit selected repo changes`.

The current `/Users/tristanzh/agent/web` working tree has unrelated dirty changes from another workflow. Do not attribute those files to this PKA workflow and do not revert them for this handoff.

## Web-Publishing-Relevant Files Changed In PKA

### `static/app.js`

Added `resetAskStateForKnowledgeUpdate()` and call it at the start of `notifyKnowledgeUpdated(action)`.

Behavioral effect:

- When PKA content is ingested, uploaded, OCR-completed, or cleared, the embedded app clears stale Ask state before publishing the next embedded snapshot.
- This prevents an old no-answer transcript from being restored by the platform shell after the knowledge base has changed.
- The event contract remains unchanged:
  - `agent06:knowledge-updated`
  - `web-publishing:embedded-state:snapshot`
  - `web-publishing:embedded-state:restore`

Effective snapshot change after knowledge update:

```json
{
  "ask": {
    "question": "",
    "language": "zh",
    "answer": "",
    "sources": [],
    "messages": []
  }
}
```

### `static/index.html`

Updated the PKA app JS cache-busting query string:

```html
<script src="static/app.js?v=20260619-ask-state"></script>
```

### `static/ask.html`

Updated the PKA app JS cache-busting query string:

```html
<script src="static/app.js?v=20260619-ask-state"></script>
```

### `static/settings.html`

Updated the PKA app JS cache-busting query string:

```html
<script src="static/app.js?v=20260619-ask-state"></script>
```

### `tests/test_project_files.py`

Added coverage that knowledge updates clear stale Ask transcripts before the embedded snapshot is published.

## Related Non-UI Behavior That Affects Published Ask Results

### `engine/generator.py`

Added a guarded fallback for Chinese answers:

- If the external model returns the no-answer phrase,
- but the retrieved chunks directly contain at least two meaningful query terms,
- PKA now returns a grounded fallback answer and keeps sources instead of reporting `source_status: "no_answer"`.

This matters to the web workflow because the Ask UI now receives `source_status: "grounded"` for the JLR onboarding question when direct evidence is present.

Observed HTTP verification for:

```text
目前我的JLR入职是什么状态？
```

Returned:

- grounded answer
- sources including `manual_20260619_121722`
- sources including `Offer_Negotiation_Strategy_Session.md`

## Web Repo Files Read But Not Modified

The PKA workflow read these files for boundary diagnosis only:

- `/Users/tristanzh/agent/web/app/agent06.js`
- `/Users/tristanzh/agent/web/tests/result-state-persistence-browser.test.mjs`
- `/Users/tristanzh/agent/web/tests/agent06-service.test.mjs`

No edits were made to `/Users/tristanzh/agent/web` by this workflow.

## Platform Expectations For Web Workflow

The web workflow should preserve these assumptions:

- The outer shell can continue listening for `agent06:knowledge-updated` and refreshing Agent06 status.
- The outer shell should not treat a post-ingest empty Ask transcript as data loss. It is intentional invalidation of stale answers after corpus mutation.
- Existing transcript persistence is still valid across ordinary route switches when the knowledge base has not changed.
- If web tests assert Ask transcript persistence after an ingest/clear event, those expectations should be updated to allow invalidation after `agent06:knowledge-updated`.

## Verification Already Run In PKA

Focused regression:

```bash
python3 -m pytest -q \
  tests/test_generator_api.py::test_generate_answer_falls_back_when_no_answer_conflicts_with_direct_evidence \
  tests/test_generator_api.py::test_generate_answer_hides_sources_when_deepseek_returns_no_answer \
  tests/test_generator_api.py::test_generate_answer_marks_directly_unrelated_material_as_no_answer \
  tests/test_generator_api.py::test_generate_answer_marks_irrelevant_material_language_as_no_answer \
  tests/test_project_files.py::test_knowledge_update_clears_stale_ask_transcript_before_snapshot \
  tests/test_project_files.py::test_frontend_assets_are_cache_busted_after_ui_contract_changes \
  tests/test_project_files.py::test_ask_embedded_state_preserves_answer_transcript_across_shell_switches \
  tests/test_project_files.py::test_frontend_uses_relative_paths_for_agent06_prefix_proxy \
  tests/test_indexer_retriever.py::test_named_under_anchor_prefers_anchor_page_before_matching_detail_page
```

Result:

```text
9 passed, 1 warning
```

Broader PKA slice:

```bash
python3 -m pytest -q tests/test_generator_api.py tests/test_project_files.py tests/test_indexer_retriever.py
```

Result:

```text
121 passed, 15 warnings
```

Full PKA baseline, excluding the live retrieval quality gate:

```bash
python3 -m pytest -q --ignore=tests/test_retrieval_quality_gate.py
```

Result:

```text
251 passed, 15 warnings
```

## Operational Note

The PKA service was restarted on:

```text
http://127.0.0.1:8086
```

Health check at completion:

```json
{"indexed_files":6,"total_chunks":76,"last_updated":null}
```
