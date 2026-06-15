# PKA Org Chart 结构化入库 TDD 验收边界

Status: acceptance boundary draft
Date: 2026-06-15
Related SDD: `docs/pka-org-chart-structured-ingest-sdd.md`

This document converts the defensive rules in the SDD into executable acceptance boundaries. It intentionally avoids concrete `pytest` or `jest` syntax. Implementation tests must preserve the Arrange / Act / Assert semantics below.

## Module 1: Intra-Node Merging

Goal: Verify that PDF bounding boxes can merge text blocks that belong to the same visual org-chart node, without merging adjacent columns, siblings, or parent/child layers.

### Test 1.1: Standard Alignment Merge

Arrange:

- Provide two text blocks:
  - A: `Nico Reimel`
  - B: `Off Cycle`
- A and B have the same visual node region.
- Y-axis distance is `1.0 * font_height`.
- X-axis center delta is less than `5px`.

Act:

- Execute `merge_pdf_blocks()`.

Assert:

- The result contains one merged node.
- The merged node has one `node_id`.
- The node preserves:
  - `line_1 = "Nico Reimel"`
  - `line_2 = "Off Cycle"`
  - `semantic_binding = "unresolved"`
- The merge step does not label either line as `name` or `role` unless deterministic evidence exists outside this test.

### Test 1.2: Y-Axis Threshold Rejection

Arrange:

- Provide two text blocks:
  - A: `Nico Reimel`
  - B: `James Vallance`
- X-axis centers are perfectly aligned.
- Y-axis distance is `2.0 * font_height`.

Act:

- Execute `merge_pdf_blocks()`.

Assert:

- The result contains two independent nodes.
- The two text blocks have different `node_id` values.
- No merge occurs.
- This prevents a parent and child, or two vertically stacked roles, from being collapsed into one entity.

### Test 1.3: X-Axis Misalignment Rejection

Arrange:

- Provide two text blocks with Y-axis distance `0`.
- A is on the left side of the page, for example centered near `x=100`.
- B is on the right side of the page, for example centered near `x=400`.
- The X-axis center delta is beyond the merge threshold.

Act:

- Execute `merge_pdf_blocks()`.

Assert:

- The result contains two independent nodes.
- No merge occurs.
- This prevents side-by-side sibling owners or teams from being collapsed into one entity.

### Test 1.4: Semantic Neutrality Gate

Arrange:

- Provide two visually mergeable text blocks:
  - A: `Digital Platform`
  - B: `Pending Assignment`
- The bbox evidence is strong enough to merge them into one node.
- The text content itself is semantically ambiguous.

Act:

- Execute `merge_pdf_blocks()`.
- Execute `generate_projection_text()` on the merged node.

Assert:

- The projection contains:

```markdown
- Field 1: Digital Platform (Field 2: Pending Assignment)
```

- The projection does not contain strong semantic labels such as:
  - `Role:`
  - `Name:`
  - `Reports to:`
- The ingest layer remains structurally neutral when semantic binding is unresolved.

## Module 2: Chunking Bypass

Goal: Verify that `is_pre_chunked=true` org-chart projections pass through the existing cleaning and chunking pipeline without damage.

### Test 2.1: Bypass Paragraph Splitter

Arrange:

- Construct one complete `[ORG_CHART]` projection longer than `2000` characters.
- Include multiple indentation levels, many line breaks, `Structure`, `Semantic Search Triggers`, and `Notes`.
- Wrap it in a record with:

```json
{
  "source_type": "org_chart",
  "is_pre_chunked": true
}
```

- The normal splitter threshold is lower than the projection length, for example `1000` characters.

Act:

- Pass the record into the chunking boundary used before indexing.

Assert:

- The returned chunk list has length `1`.
- `chunk.text` is exactly equal to the input projection text.
- No character is inserted, removed, reordered, or split.
- The output chunk keeps `source_type = "org_chart"`.

### Test 2.2: Immunity To Short-Line Noise Filtering

Arrange:

- Construct an org-chart projection containing at least 20 short person or role lines, each shorter than 15 characters.
- Examples:
  - `Nico`
  - `Jai`
  - `Pending`
  - `Off Cycle`
- Wrap it in a record with:

```json
{
  "source_type": "org_chart",
  "is_pre_chunked": true
}
```

Act:

- Pass the record through the pre-index text preparation boundary, including any noise-filtering stage that would normally affect PDF chunks.

Assert:

- All short lines are preserved.
- The text hash before and after the boundary is identical.
- PDF-only short chunk filters do not apply to `source_type = "org_chart"`.
- This test targets the effective pipeline behavior, even though the current `<30 chars` filter lives in `chunk_text()` rather than `clean_pdf_text()`.

### Test 2.3: Breadcrumb Inheritance On Subtree Split

Arrange:

- Construct a giant single-page org chart whose node count exceeds the business maximum for one projection chunk.
- The tree has at least three levels:

```text
Nico Reimel (Off Cycle)
  -> James Vallance (Concepts)
    -> Sub-report Name (Sub-role)
```

Act:

- Execute `split_large_tree_by_subdomain()`.
- This split happens inside the org-chart-specific pipeline before `is_pre_chunked` records are emitted.

Assert:

- More than one projection chunk is produced.
- The second or later subtree chunk begins with an explicit ancestor path:

```markdown
Context Root: Nico Reimel (Off Cycle) -> James Vallance (Concepts)
```

- The subtree chunk contains its local `Structure` section.
- The subtree chunk contains deterministic `Semantic Search Triggers` corresponding to the inherited path and local subtree edges.
- No subtree chunk is orphaned from its root context.

## Global Acceptance Rules

- No test may rely on an LLM to decide whether a node is a person or a role.
- No test may accept an org-chart projection that was split by raw character count.
- No test may accept a subtree projection that lacks ancestor context.
- No test may accept lossy transformation for `is_pre_chunked=true` records.
- The tests should prove that normal PDF text handling remains separate from org-chart projection handling.
