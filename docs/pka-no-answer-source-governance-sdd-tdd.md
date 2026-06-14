# PKA 拒答来源展示治理 — SDD/TDD

> Date: 2026-06-14

## 1. Problem

The retriever always returns ranked chunks when the knowledge base is non-empty. The generator can correctly say that the knowledge base lacks enough information, but the SSE stream still sends normal `sources`, so the UI displays source chips that look like factual evidence.

This creates a misleading mixed state: correct refusal plus unrelated references.

## 2. SDD: Generator Contract

When the final answer is a no-answer/refusal caused by missing knowledge-base evidence, the SSE stream must emit:

```json
{
  "type": "sources",
  "source_status": "no_answer",
  "sources": []
}
```

Normal grounded answers keep the existing contract:

```json
{
  "type": "sources",
  "source_status": "grounded",
  "sources": [...]
}
```

The detection is conservative and only applies to full refusal patterns such as `无法回答`, `知识库缺少`, `没有涉及`, `无匹配来源`, or `暂无相关内容`. Partial answers that say one aspect is missing can still show sources.

## 3. SDD: Frontend Contract

When `payload.type === "sources"` and `payload.source_status === "no_answer"`:

- store an empty source list;
- do not render normal source chips;
- append a muted source notice: `知识库缺失，未使用参考来源`;
- preserve this notice when embedded state is restored.

## 4. TDD Cases

1. A generated Chinese no-answer with retrieved chunks emits empty sources and `source_status: "no_answer"`.
2. A normal grounded answer still emits sources and `source_status: "grounded"`.
3. Frontend static contract contains `appendSourceNotice`, `source_status === "no_answer"`, and the no-answer notice text.
