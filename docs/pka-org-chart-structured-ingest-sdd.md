# PKA Org Chart 结构化入库 SDD

Status: sealed design v1.2
Date: 2026-06-15
Scope: Personal Knowledge Assistant trusted ingest pipeline

## 1. Goal

PKA needs to ingest organisation charts from PowerPoint decks and PPT-converted PDFs without flattening org relationships into unreliable one-dimensional text. The goal is to convert org chart pages into deterministic, source-derived structured records and pre-chunked projection text that can support questions such as:

- Who reports to whom?
- Which teams sit under a given leader?
- Who owns a team or capability?
- Which first-line, sub-domain, global site, or matrix roles appear in a chart?

The main corpus must remain faithful source text. LLMs may help with final answer wording, but they must not generate org chart facts for ingestion.

## 2. Non-Goals

V1 does not support cross-page org chart linking. Every extracted tree is page-bound.

V1 does not use visual models to create facts for the main Chroma or FTS5 corpus.

V1 does not guarantee exact connector recovery from PPT-converted PDFs.

V1 does not infer manager/reporting relationships from simple adjacent text alone.

## 3. Input Modes

The parser supports two confidence tiers:

```text
.pptx
  -> native shape / group / connector extraction
  -> confidence: high

.pdf / .pptx.pdf
  -> PyMuPDF text blocks / words / coordinates
  -> confidence: medium or low
```

When the source is a PPT-converted PDF, the output metadata must state the limitation:

```json
{
  "org_chart_mode": "pdf_layout_fallback",
  "confidence": "medium",
  "warnings": [
    "native_pptx_unavailable",
    "connector_relationships_inferred",
    "cross_page_links_not_supported_v1"
  ]
}
```

## 4. Structured Record

Each detected org chart produces a structured record before text projection.

```json
{
  "chart_id": "JLR_Corporate_Deck_Template_MASTER_25_.pptx.pdf#page_7#chart_1",
  "source_name": "JLR_Corporate_Deck_Template_MASTER_25_.pptx.pdf",
  "source_page": 7,
  "title": "OFF-CYCLE, CONCEPTS & SMART CABIN",
  "chart_type": "org_chart",
  "extraction_mode": "pptx_native | pdf_layout_fallback",
  "confidence": "high | medium | low",
  "page_bound": true,
  "nodes": [
    {
      "node_id": "n1",
      "line_1": "Nico Reimel",
      "line_2": "Off Cycle",
      "name": "Nico Reimel",
      "role": "Off Cycle",
      "node_kind": "person_role | team | site | assistant | merged_text_block | unknown",
      "semantic_binding": "resolved | unresolved",
      "bbox": [120.5, 240.0, 260.0, 290.0],
      "page": 7
    }
  ],
  "edges": [
    {
      "parent_node_id": "n1",
      "child_node_id": "n2",
      "relation": "reports_to | inferred_reports_to | owns_team | matrix_alignment",
      "confidence": "high | medium | low",
      "evidence": "connector | grouped_shape | y_axis_band | x_alignment"
    }
  ],
  "warnings": [
    "connector_not_available_pdf_fallback",
    "single_letter_spaced_heading_normalized"
  ]
}
```

## 5. Detection

An org chart page is a candidate when one or more of these signals appear:

- The page contains `ORG CHART`, `ORGANISATION CHART`, or similar headings.
- The page contains many short text boxes that resemble role/person nodes.
- The title contains page-local chart markers such as `(1 / 1)`, `(2 / 3)`, or domain-specific org chart labels.
- The page contains repeated person/role short lines arranged in visible coordinate bands.

Detection must be conservative. If the parser cannot identify an org chart page, the page remains in the normal text pipeline.

## 6. Cleaning

Org chart cleaning is separate from normal PDF text cleaning.

The parser should normalize single-letter spaced headings:

```text
O F F - C Y C L E -> OFF-CYCLE
D I G I T A L  P L A T F O R M -> DIGITAL PLATFORM
O R G A N I S A T I O N -> ORGANISATION
```

It should remove repeated slide dates, deck titles, and obvious presentation footers when they are not part of a node.

It must preserve short person names, team names, and role names. Existing PDF `<30 chars` chunk filtering must not be applied to org chart nodes.

## 7. Intra-Node Merging

PDF fallback must merge node-internal text before parent-child inference.

Consecutive text boxes should be merged into one entity node when:

- the Y-axis distance is less than roughly `1.5 * font_height`;
- and the X-axis centers are aligned within a small tolerance;
- or the horizontal bbox overlap ratio is high enough to indicate the same visual node.

The merge step must not rely on cross-cultural name recognition. JLR-style decks can include English, Germanic, Indian, Chinese pinyin, or other naming patterns. If line order cannot be resolved deterministically, the parser keeps neutral fields:

```json
{
  "node_id": "n1",
  "line_1": "Off Cycle",
  "line_2": "Nico Reimel",
  "node_kind": "merged_text_block",
  "semantic_binding": "unresolved",
  "confidence": "medium"
}
```

The projection for unresolved nodes should remain explicit:

```markdown
- Field 1: Off Cycle (Field 2: Nico Reimel)
```

Only high-confidence native connector/group/label evidence, or very strong deterministic layout evidence, may produce:

```markdown
- Nico Reimel (Role: Off Cycle)
```

## 8. Relationship Inference

PPTX native mode uses connector and group evidence first:

- grouped shapes define node boundaries;
- connectors define parent-child relations;
- grouped containers or swimlanes may define team ownership.

PDF fallback mode is page-bound and conservative:

- build Y-axis bands;
- locate likely parent nodes above child bands;
- use X-axis center alignment and horizontal proximity as supporting evidence;
- label inferred relations as `inferred_reports_to` or low/medium confidence.

PDF fallback must never upgrade layout-only relations to high-confidence connector facts.

## 9. Canonical Projection Text

Structured records are projected into readable Markdown that is suitable for both retrieval and generation. The projection must preserve hierarchy depth.

```markdown
[ORG_CHART]
Source: JLR_Corporate_Deck_Template_MASTER_25_.pptx.pdf
Page: 7
Title: OFF-CYCLE, CONCEPTS & SMART CABIN
Extraction mode: pdf_layout_fallback
Confidence: medium

Structure:
- Nico Reimel (Role: Off Cycle)
  - James Vallance (Role: Concepts)
    - [Sub-report Name] (Role: [Sub-role])
  - Paula Palade (Role: AI Ethics & Safety)
  - Aliasgar Lokhandwala (Role: Cyber Security)

Semantic Search Triggers:
- Nico Reimel manages James Vallance.
- James Vallance manages [Sub-report Name].
- Nico Reimel is responsible for Off-cycle Concepts and Smart Cabin.
- Off-cycle Concepts and Smart Cabin includes James Vallance and Paula Palade.

Notes:
- Relationships are layout-inferred from a single page.
- Native PPTX connectors were unavailable.
[/ORG_CHART]
```

The Markdown tree is for the answer-generation reader. The semantic search triggers are for the embedding engine. Search triggers must be generated deterministically from node and edge records; they cannot be written or expanded by an LLM.

## 10. Chunking Bypass

Org chart projection chunks must bypass normal paragraph/window splitting.

Internal chunk contract:

```json
{
  "text": "[ORG_CHART] canonical projection text [/ORG_CHART]",
  "source_name": "JLR_Corporate_Deck_Template_MASTER_25_.pptx.pdf",
  "source_type": "org_chart",
  "is_pre_chunked": true,
  "metadata": {
    "page": 7,
    "chart_id": "JLR_Corporate_Deck_Template_MASTER_25_.pptx.pdf#page_7#chart_1",
    "confidence": "medium"
  }
}
```

`is_pre_chunked=true` means:

- do not run `_window_text`;
- do not run paragraph splitting;
- do not run PDF short-chunk noise filtering;
- index the projection as an intact chunk.

Large org charts must be split by explicit subtree, not by character count.

## 11. Subtree Splitting And Breadcrumb Inheritance

If an org chart projection is too large for one chunk, each subtree chunk must inherit its full ancestor path.

```markdown
[ORG_CHART_SUBTREE]
Source: JLR_Corporate_Deck_Template_MASTER_25_.pptx.pdf
Page: 7
Context Root: Nico Reimel (Off Cycle) -> James Vallance (Concepts)
Confidence: medium

Structure:
- [Sub-report Name] (Role: [Sub-role])

Semantic Search Triggers:
- Nico Reimel manages James Vallance.
- James Vallance manages [Sub-report Name].
[/ORG_CHART_SUBTREE]
```

No subtree chunk may be orphaned from its root context. The inherited breadcrumb must appear in the display text and embedding text, not only metadata.

## 12. Pipeline Integration

Current pipeline:

```text
parse_file -> clean_pdf_text -> assess_pdf_quality -> chunk_text -> indexer
```

V1 target pipeline:

```text
parse_file
  -> normal parsed text
  -> detect_org_chart_pages
  -> org_chart_records
  -> org_chart_projection_chunks(is_pre_chunked=true)
  -> indexer.upsert(normal_chunks + pre_chunked_org_chart_chunks)
```

The first implementation should avoid changing the Chroma schema. Org chart projections enter the same main collection as faithful source-derived text, with `source_type="org_chart"` and explicit confidence metadata.

## 13. Upload Quality Metadata

Upload responses should include org chart diagnostics:

```json
{
  "org_chart": {
    "detected": true,
    "charts": 18,
    "mode": "pdf_layout_fallback",
    "confidence": "medium",
    "page_bound": true,
    "warnings": [
      "native_pptx_unavailable",
      "connector_relationships_inferred",
      "cross_page_links_not_supported_v1"
    ]
  }
}
```

The front end can initially display these fields only in the existing quality details panel. A new visual badge is not required for V1.

## 14. TDD Acceptance Criteria

Minimum tests:

- PDF single-letter headings normalize into readable titles.
- `Nico Reimel` plus `Off Cycle` can merge into one deterministic node when bbox evidence is strong.
- Ambiguous line order remains `line_1` / `line_2` with `semantic_binding="unresolved"`.
- Single-page org charts generate Markdown indentation trees.
- Projection text includes deterministic semantic search triggers.
- `is_pre_chunked=true` projection chunks are not split by `chunk_text`.
- Org chart short person/role lines are not filtered by PDF short-chunk rules.
- Large org charts split by subtree with inherited ancestor context.
- Non-org-chart PDFs continue through the normal text pipeline unchanged.
- Queries such as `Who is responsible for Off-cycle Concepts and Smart Cabin?` and `What teams report under Nico Reimel?` retrieve org chart projection chunks.

## 15. V1 Delivery Scope

V1 should implement:

```text
PDF fallback
+ heading normalization
+ intra-node merge
+ page-bound inferred tree
+ pre-chunked projection chunks
+ breadcrumb inheritance
+ semantic search triggers
+ no name/role semantic guessing
```

PPTX native extraction remains the V2 high-confidence path, but V1 data structures must be compatible with it.
