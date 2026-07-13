# PKA Answer Destinations Function Design

Date: 2026-07-13

Status: Approved by TZ to implement after destination-control visual confirmation.

## Product Contract

The completed-answer rail has three independent, explicit destinations:

| Button | Durable result | Failure contract |
|---|---|---|
| 保存到本地资料 | One idempotent Agent06 AnswerAsset under `PKA_Data/assets/answers`. | No external side effect; show local save failure. |
| 发布到 Obsidian | The local AnswerAsset plus one governed Agent10/Obsidian asset. | If local save succeeds but publication fails, show `本地已保存，Obsidian 待发布`. |
| 加入 PKA 问答检索 | Local AnswerAsset, generated-secondary FTS/vector entries, then one Agent10/Obsidian asset marked indexed. | If indexing succeeds but publication fails, show `已加入 PKA 检索，Obsidian 待发布`; retry only publishes. |

## Consistency Decision

Agent10 idempotency deliberately never rewrites an existing note. Therefore retrieval promotion indexes the generated-secondary source before Agent10 publication. This ensures the one published Obsidian note represents its final `knowledge_status=indexed` state. Each partial state remains explicit in the local AnswerAsset manifest and response; no action claims completion before all of its required steps finish.

## Local AnswerAsset State

`manifest.json` gains deterministic operation state:

```json
{
  "operation_key": "sha256:<answer snapshot hash>",
  "publication_status": "local_only|published|pending_obsidian",
  "rag_status": "not_indexed|indexed",
  "agent10_asset": {"asset_id": "...", "path": "..."},
  "generated_knowledge": {"source_name": "generated-<asset-id>.md", "chunk_ids": ["..."]}
}
```

Repeated clicks reuse the same local AnswerAsset by `operation_key`; Agent10 then receives the same source path and obtains its own no-update idempotent reuse.

## Generated-Secondary Retrieval Policy

- Generated Markdown is written under `PKA_Data/generated/knowledge/YYYY-MM-DD/`.
- It contains question, answer, source chunk IDs/names, evidence status, language, model route, timestamp, and `generated=true`, `not_primary_source=true` metadata.
- FTS and Chroma metadata preserve the generated flags and provenance.
- Retrieved generated chunks remain `source_type="generated_asset"` and are labeled as secondary context in the answer prompt. Primary chunks remain the factual basis.
- The promotion path invokes no LLM. It uses the configured local Ollama embedding runtime only, as ordinary indexing already does.
- `source_status="no_answer"` cannot be promoted.

## Runtime Authentication

The managed Agent06 backend receives only:

```text
AGENT10_BASE_URL=http://127.0.0.1:8010
AGENT10_CONTROL_TOKEN_FILE=/Users/tristanzh/agent/AgentAssetVault/99_System/audit/.agent10-control.token
```

The token never enters Web HTML, JavaScript, logs, source-controlled configuration values, or API responses.

## Scope

- Agent06 owns button APIs, idempotent local saves, generated source writing/indexing, user feedback, and retries.
- Agent10 remains the only Obsidian writer and the only cross-Agent asset-governance owner.
- Shared Web changes only the Agent06 backend runtime environment; no Web visual-system change is needed.
- Agent05 remains excluded.
