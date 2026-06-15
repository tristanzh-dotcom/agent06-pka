import hashlib
import re


def _load_org_chart_api():
    from engine.org_chart import (  # noqa: PLC0415
        OrgChartNode,
        OrgChartTree,
        PdfTextBlock,
        PreChunkedRecord,
        chunk_prepared_records,
        generate_canonical_text,
        generate_projection_text,
        infer_layout_hierarchy,
        merge_pdf_blocks,
        normalize_org_chart_heading,
        split_large_tree_by_subdomain,
    )

    return {
        "OrgChartNode": OrgChartNode,
        "OrgChartTree": OrgChartTree,
        "PdfTextBlock": PdfTextBlock,
        "PreChunkedRecord": PreChunkedRecord,
        "chunk_prepared_records": chunk_prepared_records,
        "generate_canonical_text": generate_canonical_text,
        "generate_projection_text": generate_projection_text,
        "infer_layout_hierarchy": infer_layout_hierarchy,
        "merge_pdf_blocks": merge_pdf_blocks,
        "normalize_org_chart_heading": normalize_org_chart_heading,
        "split_large_tree_by_subdomain": split_large_tree_by_subdomain,
    }


def _block(api, text, x0, y0, x1, y1, font_size=10):
    return api["PdfTextBlock"](
        text=text,
        x0=x0,
        y0=y0,
        x1=x1,
        y1=y1,
        font_size=font_size,
        page=7,
    )


def _layout_node(api, node_id, label, x_center, y_center, line_2=None):
    return api["OrgChartNode"](
        node_id=node_id,
        line_1=label,
        line_2=line_2,
        semantic_binding="resolved" if line_2 else "unresolved",
        bbox=(x_center - 50, y_center - 10, x_center + 50, y_center + 10),
        page=7,
        children=[],
    )


def _edge_pairs(edges):
    return {(edge.parent_node_id, edge.child_node_id) for edge in edges}


def _trigger_lines(text):
    match = re.search(
        r"Semantic Search Triggers:\n(?P<body>.*?)(?:\n\n|\nNotes:|\[/ORG_CHART\]|\Z)",
        text,
        flags=re.S,
    )
    assert match, "Canonical text must contain a Semantic Search Triggers section"
    return [
        line.strip()
        for line in match.group("body").splitlines()
        if line.strip().startswith("- ")
    ]


def test_merge_pdf_blocks_merges_standard_aligned_node_without_semantic_labels():
    api = _load_org_chart_api()
    blocks = [
        _block(api, "Nico Reimel", 100, 100, 200, 110),
        _block(api, "Off Cycle", 102, 120, 198, 130),
    ]

    nodes = api["merge_pdf_blocks"](blocks)

    assert len(nodes) == 1
    node = nodes[0]
    assert node.node_id
    assert node.line_1 == "Nico Reimel"
    assert node.line_2 == "Off Cycle"
    assert node.semantic_binding == "unresolved"
    assert not getattr(node, "name", None)
    assert not getattr(node, "role", None)


def test_merge_pdf_blocks_rejects_y_axis_distance_above_threshold():
    api = _load_org_chart_api()
    blocks = [
        _block(api, "Nico Reimel", 100, 100, 200, 110),
        _block(api, "James Vallance", 100, 130, 200, 140),
    ]

    nodes = api["merge_pdf_blocks"](blocks)

    assert len(nodes) == 2
    assert nodes[0].node_id != nodes[1].node_id
    assert [node.line_1 for node in nodes] == ["Nico Reimel", "James Vallance"]
    assert all(getattr(node, "line_2", None) in (None, "") for node in nodes)


def test_merge_pdf_blocks_rejects_x_axis_misalignment_for_side_by_side_blocks():
    api = _load_org_chart_api()
    blocks = [
        _block(api, "Nico Reimel", 50, 100, 150, 110),
        _block(api, "James Vallance", 350, 100, 450, 110),
    ]

    nodes = api["merge_pdf_blocks"](blocks)

    assert len(nodes) == 2
    assert nodes[0].node_id != nodes[1].node_id
    assert [node.line_1 for node in nodes] == ["Nico Reimel", "James Vallance"]
    assert all(getattr(node, "line_2", None) in (None, "") for node in nodes)


def test_projection_keeps_unresolved_merged_nodes_semantically_neutral():
    api = _load_org_chart_api()
    blocks = [
        _block(api, "Digital Platform", 100, 100, 220, 110),
        _block(api, "Pending Assignment", 102, 120, 218, 130),
    ]
    nodes = api["merge_pdf_blocks"](blocks)

    projection = api["generate_projection_text"](
        source_name="JLR_Corporate_Deck_Template_MASTER_25_.pptx.pdf",
        source_page=7,
        title="DIGITAL PLATFORM",
        extraction_mode="pdf_layout_fallback",
        confidence="medium",
        nodes=nodes,
        edges=[],
        warnings=["connector_not_available_pdf_fallback"],
    )

    assert "- Field 1: Digital Platform (Field 2: Pending Assignment)" in projection
    assert "Role:" not in projection
    assert "Name:" not in projection
    assert "Reports to:" not in projection


def test_pre_chunked_org_chart_bypasses_paragraph_and_window_splitters():
    api = _load_org_chart_api()
    structure_lines = "\n".join(
        f"  - Report {idx:03d} (Role: Capability {idx:03d})"
        for idx in range(80)
    )
    trigger_lines = "\n".join(
        f"- Nico Reimel manages Report {idx:03d}."
        for idx in range(80)
    )
    text = (
        "[ORG_CHART]\n"
        "Source: JLR_Corporate_Deck_Template_MASTER_25_.pptx.pdf\n"
        "Page: 7\n"
        "Title: OFF-CYCLE, CONCEPTS & SMART CABIN\n"
        "Extraction mode: pdf_layout_fallback\n"
        "Confidence: medium\n\n"
        "Structure:\n"
        "- Nico Reimel (Role: Off Cycle)\n"
        f"{structure_lines}\n\n"
        "Semantic Search Triggers:\n"
        f"{trigger_lines}\n\n"
        "Notes:\n"
        "- Relationships are layout-inferred from a single page.\n"
        "[/ORG_CHART]"
    )
    assert len(text) > 2000
    record = api["PreChunkedRecord"](
        text=text,
        source_name="JLR_Corporate_Deck_Template_MASTER_25_.pptx.pdf",
        source_type="org_chart",
        is_pre_chunked=True,
        metadata={"page": 7, "chart_id": "deck.pdf#page_7#chart_1"},
    )

    chunks = api["chunk_prepared_records"]([record], max_chunk_size=1000)

    assert len(chunks) == 1
    assert chunks[0].text == text
    assert chunks[0].source_type == "org_chart"
    assert chunks[0].metadata["chart_id"] == "deck.pdf#page_7#chart_1"


def test_pre_chunked_org_chart_preserves_short_lines_through_noise_filters():
    api = _load_org_chart_api()
    short_lines = [
        "Nico",
        "Jai",
        "Pending",
        "Off Cycle",
        "Concepts",
        "Cabin",
        "AI",
        "Safety",
        "Cyber",
        "UX",
        "HMI",
        "Data",
        "Core",
        "Ops",
        "China",
        "India",
        "UK",
        "EU",
        "TBD",
        "ADAS",
    ]
    text = (
        "[ORG_CHART]\n"
        "Source: deck.pdf\n"
        "Page: 7\n\n"
        "Structure:\n"
        + "\n".join(f"- {line}" for line in short_lines)
        + "\n\nSemantic Search Triggers:\n"
        "- Nico manages Jai.\n"
        "[/ORG_CHART]"
    )
    before_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    record = api["PreChunkedRecord"](
        text=text,
        source_name="deck.pdf",
        source_type="org_chart",
        is_pre_chunked=True,
        metadata={"page": 7},
    )

    chunks = api["chunk_prepared_records"]([record], max_chunk_size=1000)
    after_text = chunks[0].text
    after_hash = hashlib.sha256(after_text.encode("utf-8")).hexdigest()

    assert len(chunks) == 1
    assert after_hash == before_hash
    for line in short_lines:
        assert f"- {line}" in after_text


def test_subtree_split_inherits_breadcrumb_and_local_semantic_triggers():
    api = _load_org_chart_api()
    sub_reports = [
        api["OrgChartNode"](
            node_id=f"sub_{idx}",
            line_1=f"Sub-report {idx:02d}",
            line_2=f"Sub-role {idx:02d}",
            semantic_binding="resolved",
            children=[],
        )
        for idx in range(12)
    ]
    james = api["OrgChartNode"](
        node_id="james",
        line_1="James Vallance",
        line_2="Concepts",
        semantic_binding="resolved",
        children=sub_reports,
    )
    nico = api["OrgChartNode"](
        node_id="nico",
        line_1="Nico Reimel",
        line_2="Off Cycle",
        semantic_binding="resolved",
        children=[james],
    )
    tree = api["OrgChartTree"](
        source_name="JLR_Corporate_Deck_Template_MASTER_25_.pptx.pdf",
        source_page=7,
        title="OFF-CYCLE, CONCEPTS & SMART CABIN",
        extraction_mode="pdf_layout_fallback",
        confidence="medium",
        roots=[nico],
    )

    chunks = api["split_large_tree_by_subdomain"](tree, max_nodes_per_chunk=5)

    assert len(chunks) > 1
    subtree_text = chunks[1].text
    assert subtree_text.startswith("[ORG_CHART_SUBTREE]")
    assert (
        "Context Root: Nico Reimel (Off Cycle) -> James Vallance (Concepts)"
        in subtree_text
    )
    assert "Structure:" in subtree_text
    assert "- Sub-report" in subtree_text
    assert "Semantic Search Triggers:" in subtree_text
    assert "- Nico Reimel manages James Vallance." in subtree_text
    assert "- James Vallance manages Sub-report" in subtree_text


def test_infer_layout_hierarchy_assigns_lower_y_band_children_to_parent():
    api = _load_org_chart_api()
    parent = _layout_node(api, "a", "Node A", x_center=500, y_center=100)
    left_child = _layout_node(api, "b", "Node B", x_center=300, y_center=250)
    right_child = _layout_node(api, "c", "Node C", x_center=700, y_center=250)

    edges = api["infer_layout_hierarchy"]([parent, left_child, right_child])

    assert _edge_pairs(edges) == {("a", "b"), ("a", "c")}
    for edge in edges:
        assert edge.relation == "inferred_reports_to"
        assert edge.confidence == "medium"
        assert edge.evidence == "y_axis_band + x_alignment"


def test_infer_layout_hierarchy_groups_nearby_siblings_in_same_y_band():
    api = _load_org_chart_api()
    parent = _layout_node(api, "a", "Node A", x_center=500, y_center=100)
    children = [
        _layout_node(api, "b", "Node B", x_center=300, y_center=250),
        _layout_node(api, "c", "Node C", x_center=500, y_center=254),
        _layout_node(api, "d", "Node D", x_center=700, y_center=248),
    ]

    edges = api["infer_layout_hierarchy"]([parent, *children])

    assert _edge_pairs(edges) == {("a", "b"), ("a", "c"), ("a", "d")}
    sibling_ids = {"b", "c", "d"}
    assert not any(
        edge.parent_node_id in sibling_ids and edge.child_node_id in sibling_ids
        for edge in edges
    )


def test_infer_layout_hierarchy_prevents_skip_level_orphan_edges():
    api = _load_org_chart_api()
    grandparent = _layout_node(api, "a", "Node A", x_center=500, y_center=100)
    parent = _layout_node(api, "b", "Node B", x_center=500, y_center=200)
    child = _layout_node(api, "c", "Node C", x_center=500, y_center=300)

    edges = api["infer_layout_hierarchy"]([grandparent, parent, child])
    pairs = _edge_pairs(edges)

    assert ("b", "c") in pairs
    assert ("a", "c") not in pairs
    assert all(
        not (edge.parent_node_id == "a" and edge.child_node_id == "c")
        for edge in edges
    )


def test_infer_layout_hierarchy_rejects_extreme_x_axis_outliers():
    api = _load_org_chart_api()
    left_header = _layout_node(api, "a", "Node A", x_center=100, y_center=100)
    far_right_text = _layout_node(api, "b", "Node B", x_center=900, y_center=200)

    edges = api["infer_layout_hierarchy"]([left_header, far_right_text])

    assert edges == []


def test_generate_canonical_text_preserves_markdown_indentation_depth():
    api = _load_org_chart_api()
    child = api["OrgChartNode"](
        node_id="c",
        line_1="Node C",
        semantic_binding="unresolved",
        children=[],
    )
    parent = api["OrgChartNode"](
        node_id="b",
        line_1="Node B",
        semantic_binding="unresolved",
        children=[child],
    )
    root = api["OrgChartNode"](
        node_id="a",
        line_1="Node A",
        semantic_binding="unresolved",
        children=[parent],
    )
    tree = api["OrgChartTree"](
        source_name="deck.pdf",
        source_page=7,
        title="ORG CHART",
        extraction_mode="pdf_layout_fallback",
        confidence="medium",
        roots=[root],
    )

    text = api["generate_canonical_text"](tree)

    assert re.search(r"(?m)^- Field 1: Node A$", text)
    assert re.search(r"(?m)^  - Field 1: Node B$", text)
    assert re.search(r"(?m)^    - Field 1: Node C$", text)
    assert "Node A - Node B - Node C" not in text


def test_generate_canonical_text_uses_neutral_triggers_for_unresolved_nodes():
    api = _load_org_chart_api()
    child = api["OrgChartNode"](
        node_id="child",
        line_1="Concepts",
        line_2="James Vallance",
        semantic_binding="unresolved",
        children=[],
    )
    parent = api["OrgChartNode"](
        node_id="parent",
        line_1="Off Cycle",
        line_2="Nico Reimel",
        semantic_binding="unresolved",
        children=[child],
    )
    tree = api["OrgChartTree"](
        source_name="deck.pdf",
        source_page=7,
        title="ORG CHART",
        extraction_mode="pdf_layout_fallback",
        confidence="medium",
        roots=[parent],
    )

    text = api["generate_canonical_text"](tree)
    triggers = _trigger_lines(text)

    assert triggers == [
        "- Field 1: Concepts (Field 2: James Vallance) is structurally under Field 1: Off Cycle (Field 2: Nico Reimel)."
    ]
    trigger_section = "\n".join(triggers).lower()
    assert "manages" not in trigger_section
    assert "reports to" not in trigger_section


def test_generate_canonical_text_emits_one_trigger_per_edge_without_expansion():
    api = _load_org_chart_api()
    children = [
        api["OrgChartNode"](
            node_id=f"child_{idx}",
            line_1=f"Child {idx}",
            semantic_binding="unresolved",
            children=[],
        )
        for idx in range(5)
    ]
    root = api["OrgChartNode"](
        node_id="root",
        line_1="Root",
        semantic_binding="unresolved",
        children=children,
    )
    tree = api["OrgChartTree"](
        source_name="deck.pdf",
        source_page=7,
        title="ORG CHART",
        extraction_mode="pdf_layout_fallback",
        confidence="medium",
        roots=[root],
    )

    text = api["generate_canonical_text"](tree)

    assert len(_trigger_lines(text)) == 5


def test_generate_canonical_text_normalizes_single_letter_spaced_heading():
    api = _load_org_chart_api()
    root = api["OrgChartNode"](
        node_id="root",
        line_1="Root",
        semantic_binding="unresolved",
        children=[],
    )
    tree = api["OrgChartTree"](
        source_name="deck.pdf",
        source_page=7,
        title=api["normalize_org_chart_heading"]("S M A R T  C A B I N"),
        extraction_mode="pdf_layout_fallback",
        confidence="medium",
        roots=[root],
    )

    text = api["generate_canonical_text"](tree)

    assert re.search(r"(?m)^Title: SMART CABIN$", text)
