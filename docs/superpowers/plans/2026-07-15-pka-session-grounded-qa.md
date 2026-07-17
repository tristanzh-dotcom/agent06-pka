# PKA Session-Grounded QA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PKA refuse unsupported or context-free follow-ups deterministically and replace the unbounded transcript with a bounded active conversation.

**Architecture:** A new deterministic query-context module resolves eligible follow-ups and classifies retrieval evidence before `generate_answer`. The FastAPI route preserves its existing request shape while accepting optional session context. The browser maintains bounded local conversation sessions and sends only the immediately preceding user question.

**Tech Stack:** FastAPI/Pydantic, Python pytest, vanilla browser JavaScript, existing SSE protocol.

## Global Constraints

- Preserve `/api/query` compatibility for callers that send only `question` and `language`.
- Do not invoke an LLM for query rewriting, relevance assessment, or clarification.
- Do not send full prior answers or raw history to the model.
- Do not modify Agent06’s shared Web shell except its existing embedded-state payload.
- Git writes are routed through Agent08; do not commit from this repository.

---

### Task 1: Deterministic context and evidence gate

**Files:**
- Create: `engine/query_context.py`
- Modify: `server.py`
- Modify: `tests/test_generator_api.py`
- Create: `tests/test_query_context.py`

- [ ] Write failing tests for a context-free follow-up clarification, a resolved same-session follow-up, and generic-term evidence rejection.
- [ ] Run those tests and verify the missing module/contract fails.
- [ ] Implement `QueryResolution`, `resolve_query(question, previous_question)`, and `filter_supported_chunks(question, chunks)`.
- [ ] Route `clarification_required` and unsupported evidence directly to SSE terminal events without invoking `generate_answer`.
- [ ] Run the new tests and the focused generator API regression set.

### Task 2: No-answer and generated-source safety

**Files:**
- Modify: `engine/generator.py`
- Modify: `engine/topic_aggregator.py`
- Modify: `tests/test_generator_api.py`
- Modify: `tests/test_topic_aggregator.py`

- [ ] Write failing tests proving generic words cannot trigger a fallback dump and generated chunks sort behind primary chunks.
- [ ] Verify the tests fail against current behavior.
- [ ] Remove the no-answer reversal and rank primary source groups before generated groups.
- [ ] Run the focused generator/topic regression tests.

### Task 3: Bounded active session UI

**Files:**
- Modify: `static/ask.html`
- Modify: `static/app.js`
- Modify: `tests/test_project_files.py`

- [ ] Write failing static-contract tests for New Conversation, bounded sessions, request context, disabled Send, and auto-scroll.
- [ ] Verify RED.
- [ ] Implement browser-local session state, legacy-state migration, active session switching, and optional `previous_question` query payload.
- [ ] Implement New Conversation, stream locking, and auto-scroll.
- [ ] Run frontend/static and backend API regressions.

### Task 4: End-to-end verification and documentation

**Files:**
- Modify: `docs/pka-answer-result-operations-sdd.md`
- Test: focused pytest suite and local browser smoke

- [ ] Record the approved session and source-status contract.
- [ ] Run the complete directly affected pytest suite.
- [ ] Run a local browser smoke: relevant initial question, explicit unsupported question, context-free follow-up, same-session follow-up, New Conversation, and reload.
- [ ] Inspect diff and report only verified results.
