# PKA Agent05 PPT Export And Workflow Tab Design

## Scope

This change covers two confirmed Agent06/PKA improvements:

1. The Agent06 shell workflow switch for `录入 / 问答 / 设置` must visually behave like Agent04's function switch: a labeled switch block with a clear selected state.
2. PKA `导出 PPT` must keep returning a `.pptx`, and should try Agent05/PPT-maker for a higher-quality template deck before falling back to the current simple `python-pptx` export.

## Boundary

- Agent06 owns the PKA shell route, workflow switch, PKA export request, and fallback behavior.
- Agent05/PPT-maker owns Gorden template selection, template preservation, rendering, and PPT quality checks.
- PKA must not copy Agent05's Gorden orchestration into its own backend.
- PKA must not require Agent05 availability to produce a downloadable PPTX.

## Interface

PKA sends Agent05 a `prompt_to_ppt` WebSocket generation payload:

```json
{
  "type": "generate",
  "payload": {
    "mode": "prompt_to_ppt",
    "prompt": "PKA structured report prompt",
    "page_count": 5,
    "style": "business-summary",
    "purpose": "personal-knowledge-report"
  }
}
```

When Agent05 sends `template_candidates`, PKA selects the first candidate automatically. When Agent05 sends `complete`, PKA downloads the returned `file_id` from `/api/files/{file_id}/download` and returns those bytes to the browser as the `/api/export/ppt` attachment.

If Agent05 is unreachable, returns an error, has missing dependencies, or the WebSocket client is unavailable, PKA falls back to `engine.exporter.export_to_ppt()`.

## UX

- The visible `导出 PPT` button remains stable.
- A failed Agent05 quality path must not surface as a failed download when simple PPTX fallback can succeed.
- The shell switch keeps the same three routes and embedded-state behavior, but its visual structure becomes:
  - a `功能切换` label;
  - a segmented switch container;
  - active segment with stronger fill and text color.

## Tests

- Backend API test: `/api/export/ppt` uses Agent05 adapter output when available and still returns PPTX.
- Backend API test: `/api/export/ppt` falls back to local PPTX when Agent05 adapter raises.
- File contract test: Agent06 shell has a `功能切换` label and scoped tab switch classes.
- Web platform test: Agent06 CSS contains Agent04-like segmented active styling and keeps constrained-height rules.

