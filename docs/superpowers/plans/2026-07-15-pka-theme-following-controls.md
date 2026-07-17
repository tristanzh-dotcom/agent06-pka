# PKA Theme-following Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PKA Ask controls and source metadata fully follow semantic theme variables.

**Architecture:** Add a small semantic token layer in `static/style.css`. The Ask header action buttons and source metadata consume only those tokens, preserving their current layout and behavior. A static test rejects fixed color literals in the covered selector block.

**Tech Stack:** CSS custom properties, pytest static-file contract tests.

## Global Constraints

- Do not change Ask DOM, API payloads, or operation enablement logic.
- Covered Ask-control selectors must not contain fixed color literals.
- Do not perform Git staging, commits, or pushes.

---

### Task 1: Theme semantic tokens and Ask-control contract

**Files:**
- Modify: `static/style.css:1-25`, `static/style.css:545-600`, `static/style.css:879-960`
- Modify: `tests/test_project_files.py`

**Interfaces:**
- Consumes: existing `:root` theme variables and Ask-control selectors.
- Produces: `--ask-*` semantic CSS variables used by operation buttons and source metadata.

- [x] **Step 1: Write the failing test**

```python
def test_ask_controls_use_theme_semantic_variables_without_fixed_colors():
    css = (root / "static/style.css").read_text(encoding="utf-8")
    assert "--ask-operation-fg" in css
    assert "--ask-source-link-fg" in css
    covered = css[css.index(".exportbar button[type") : css.index(".ask-input-bar")]
    assert "#155f66" not in covered
    assert "#f3fbfc" not in covered
    assert "rgba(" not in covered
```

- [x] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest -q tests/test_project_files.py -k theme_semantic_variables`

Expected: FAIL because the semantic variables do not exist and covered selectors include fixed colors.

- [x] **Step 3: Write minimal implementation**

```css
:root {
  --ask-operation-fg: var(--accent);
  --ask-operation-bg: var(--panel);
  --ask-operation-border: var(--line);
  --ask-source-link-fg: var(--accent);
}

.exportbar .answer-destination {
  color: var(--ask-destination-fg);
  border-color: var(--ask-destination-border);
  background: var(--ask-destination-bg);
}
```

Replace all fixed foreground, background, and border colors for the covered Ask controls and source badges with semantic variables.

- [x] **Step 4: Run tests to verify green**

Run: `python3 -m pytest -q tests/test_project_files.py -k 'theme_semantic_variables or ask_page'`

Expected: PASS.

- [x] **Step 5: Verify syntax and diff**

Run: `node --check static/app.js && git diff --check`

Expected: exit 0.
