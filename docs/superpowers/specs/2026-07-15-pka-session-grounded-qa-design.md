# PKA 会话边界与有据问答设计

> Date: 2026-07-15
> Status: approved by TZ for P0/P1 implementation

## Goal

Prevent context-dependent follow-ups and unrelated queries from producing fabricated, irrelevant answers while making the Ask page an explicitly bounded conversation experience.

## Approved product rules

1. A question is answered only when deterministic retrieval evidence is relevant enough. A non-empty Top-K result is not evidence by itself.
2. A context-dependent follow-up without a usable preceding turn receives a clarification request and must not call the generation route.
3. A model no-answer is never replaced with a chunk-dump fallback based only on generic action words.
4. The active conversation persists across refresh and Agent06 view switches, but it is not an unlimited global transcript.
5. Users can start a new conversation. Only the active conversation is visible in the workbench; previous conversations remain browser-local history and are not added to retrieval automatically.
6. A follow-up uses only the immediately preceding user question as a deterministic retrieval anchor. Previous answer text and full history are not sent to the model.
7. Generated answer assets remain secondary retrieval context. They cannot by themselves establish grounded evidence and are ranked after primary chunks unless the user explicitly asks for a prior summary or judgement.
8. An answer must not assign a source character's identity, responsibility or
   experience to the user unless the user explicitly states that they are that
   person. Advice uses neutral source-grounded labels such as `该负责人`.

## P0: Grounded retrieval gate

Add a deterministic query-assessment layer before generation.

- Detect referential Chinese follow-ups such as `这个`, `那个`, `上述`, `继续`, `下一步`, and `怎么做`.
- Also treat conservative sentence-initial references such as `那负责人`,
  `那项目`, `那结果` and `那方案` as follow-ups. Do not use a broad `那*`
  match that would misclassify standalone proper nouns such as `那曲`.
- Build a resolved retrieval question from the previous user question only when the client provides a same-session predecessor. Otherwise return `clarification_required`.
- Remove generic Chinese stop words from FTS matching and require an anchor-term overlap before a chunk can support the answer.
- Treat vector-only nearest neighbours as candidates, not proof. At least one primary-source chunk must pass the deterministic anchor check. This avoids collection-specific hard-coded vector-distance thresholds while a labelled calibration set is not yet available.
- Emit `source_status` values `grounded`, `thin`, `no_answer`, or `clarification_required`. No-answer and clarification paths skip the LLM.
- Never use `_has_direct_query_evidence()` to reverse a no-answer response. Retain only an explicit model-failure fallback for already-grounded evidence.

## P1: Session-scoped Ask UI

- Extend `/api/query` compatibly with optional `previous_question` and `conversation_id` fields.
- The browser creates a local session id and stores a bounded list of sessions. A session holds at most 20 messages; the browser retains at most 30 sessions. The active session is restored on refresh/view switch.
- Add `新对话`. It creates an empty active session and does not delete old sessions.
- Disable Send while a stream is active. Scroll the conversation to the latest message during streaming.
- Keep answer operations attached to the current, completed answer only.
- Render a minimal Markdown subset safely as plain DOM elements is out of scope for this slice; preserve current text rendering to avoid changing output semantics.

## Non-goals

- No server-side persistence of chat history.
- No LLM query rewriting, history summarization, or new external model route.
- No migration of existing localStorage state; legacy transcript is restored once as the first bounded session.

## Acceptance criteria

1. A vague follow-up without `previous_question` streams a clarification and no sources.
2. The same follow-up with a prior question resolves the retrieval query deterministically.
3. A no-answer from deterministic gating never invokes DeepSeek and never returns unrelated source chips.
4. Generic terms such as `问题`, `具体`, and `应该` cannot cause a fallback chunk dump.
5. Generated-only results remain `generated_only`; mixed results prefer primary evidence.
6. New conversation clears the visible active transcript without deleting stored previous sessions.
7. A second Send cannot begin while the first response streams.
