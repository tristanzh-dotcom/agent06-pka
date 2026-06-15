from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class PdfTextBlock:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    font_size: float
    page: int

    @property
    def x_center(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def y_center(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class OrgChartNode:
    node_id: str
    line_1: str
    line_2: Optional[str] = None
    semantic_binding: str = "unresolved"
    bbox: Optional[Tuple[float, float, float, float]] = None
    page: Optional[int] = None
    children: List["OrgChartNode"] = field(default_factory=list)

    @property
    def x_center(self) -> float:
        if not self.bbox:
            return 0
        return (self.bbox[0] + self.bbox[2]) / 2

    @property
    def y_center(self) -> float:
        if not self.bbox:
            return 0
        return (self.bbox[1] + self.bbox[3]) / 2


@dataclass(frozen=True)
class OrgChartEdge:
    parent_node_id: str
    child_node_id: str
    relation: str
    confidence: str
    evidence: str


@dataclass(frozen=True)
class OrgChartTree:
    source_name: str
    source_page: int
    title: str
    extraction_mode: str
    confidence: str
    roots: List[OrgChartNode]


@dataclass(frozen=True)
class PreChunkedRecord:
    text: str
    source_name: str
    source_type: str
    is_pre_chunked: bool
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrgChartChunk:
    id: str
    text: str
    source_name: str
    source_type: str
    chunk_index: int
    created_at: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding_text: str = ""


def normalize_org_chart_block_text(text: str) -> str:
    normalized = re.sub(r"[\r\n]+", " ", text).strip()
    if not normalized:
        return ""
    parts = [part for part in re.split(r"\s{2,}", normalized) if part.strip()]
    if not parts:
        return ""
    return " ".join(_normalize_split_character_part(part) for part in parts).strip()


def clean_org_chart_blocks(
    blocks: Sequence[PdfTextBlock], page_height: float
) -> List[PdfTextBlock]:
    cleaned: List[PdfTextBlock] = []
    for block in blocks:
        text = normalize_org_chart_block_text(block.text)
        if not text:
            continue
        normalized_block = replace(block, text=text)
        if _is_noise_block(normalized_block, page_height):
            continue
        cleaned.append(normalized_block)
    return cleaned


def select_org_chart_title(
    blocks: Sequence[PdfTextBlock], page_height: float
) -> Tuple[str, List[PdfTextBlock]]:
    cleaned = clean_org_chart_blocks(blocks, page_height)
    if not cleaned:
        return "ORG CHART", []
    title_block = _best_title_block(cleaned, page_height)
    title = title_block.text if title_block else cleaned[0].text
    remaining = list(cleaned)
    if title_block is not None:
        matching_blocks = [
            block
            for block in cleaned
            if block is not title_block and _same_title_text(block.text, title_block.text)
        ]
        if matching_blocks:
            remaining = [block for block in cleaned if block is not title_block]
        else:
            remaining = [block for block in cleaned if block is not title_block]
    return title, remaining


def merge_pdf_blocks(blocks: Sequence[PdfTextBlock]) -> List[OrgChartNode]:
    sorted_blocks = sorted(blocks, key=lambda block: (block.page, block.y0, block.x0))
    nodes: List[OrgChartNode] = []
    index = 0
    while index < len(sorted_blocks):
        current = sorted_blocks[index]
        if index + 1 < len(sorted_blocks) and _should_merge_blocks(
            current, sorted_blocks[index + 1]
        ):
            next_block = sorted_blocks[index + 1]
            nodes.append(_merged_node(len(nodes), current, next_block))
            index += 2
            continue
        nodes.append(_single_line_node(len(nodes), current))
        index += 1
    return nodes


def infer_layout_hierarchy(nodes: Sequence[OrgChartNode]) -> List[OrgChartEdge]:
    bands = _y_bands(nodes)
    if len(bands) < 2:
        return []

    edges: List[OrgChartEdge] = []
    for band_index in range(1, len(bands)):
        parent_band = bands[band_index - 1]
        child_band = bands[band_index]
        for child in child_band:
            parent = _nearest_x_parent(child, parent_band)
            if parent is None:
                continue
            edges.append(
                OrgChartEdge(
                    parent_node_id=parent.node_id,
                    child_node_id=child.node_id,
                    relation="inferred_reports_to",
                    confidence="medium",
                    evidence="y_axis_band + x_alignment",
                )
            )
    return edges


def generate_projection_text(
    *,
    source_name: str,
    source_page: int,
    title: str,
    extraction_mode: str,
    confidence: str,
    nodes: Sequence[OrgChartNode],
    edges: Sequence[OrgChartEdge],
    warnings: Optional[Sequence[str]] = None,
) -> str:
    tree = OrgChartTree(
        source_name=source_name,
        source_page=source_page,
        title=title,
        extraction_mode=extraction_mode,
        confidence=confidence,
        roots=_attach_edges(nodes, edges),
    )
    return generate_canonical_text(tree, warnings=warnings)


def generate_canonical_text(
    tree: OrgChartTree, warnings: Optional[Sequence[str]] = None
) -> str:
    lines = [
        "[ORG_CHART]",
        f"Source: {tree.source_name}",
        f"Page: {tree.source_page}",
        f"Title: {normalize_org_chart_heading(tree.title)}",
        f"Extraction mode: {tree.extraction_mode}",
        f"Confidence: {tree.confidence}",
        "",
        "Structure:",
    ]
    for root in tree.roots:
        lines.extend(_structure_lines(root))
    lines.extend(["", "Semantic Search Triggers:"])
    lines.extend(_semantic_triggers(tree.roots))
    if warnings:
        lines.extend(["", "Notes:"])
        lines.extend(f"- {warning}" for warning in warnings)
    lines.append("[/ORG_CHART]")
    return "\n".join(lines)


def chunk_prepared_records(
    records: Sequence[PreChunkedRecord], max_chunk_size: int = 1024
) -> List[OrgChartChunk]:
    chunks: List[OrgChartChunk] = []
    created_at = datetime.now(timezone.utc).astimezone().isoformat()
    for record in records:
        if record.source_type == "org_chart" and record.is_pre_chunked:
            chunks.append(
                OrgChartChunk(
                    id=f"{record.source_name}#{len(chunks)}",
                    text=record.text,
                    source_name=record.source_name,
                    source_type=record.source_type,
                    chunk_index=len(chunks),
                    created_at=created_at,
                    metadata=dict(record.metadata),
                    embedding_text=record.text,
                )
            )
            continue
        for part in _window_text(record.text, max_chunk_size):
            chunks.append(
                OrgChartChunk(
                    id=f"{record.source_name}#{len(chunks)}",
                    text=part,
                    source_name=record.source_name,
                    source_type=record.source_type,
                    chunk_index=len(chunks),
                    created_at=created_at,
                    metadata=dict(record.metadata),
                    embedding_text=part,
                )
            )
    return chunks


def split_large_tree_by_subdomain(
    tree: OrgChartTree, max_nodes_per_chunk: int
) -> List[OrgChartChunk]:
    full_text = generate_canonical_text(tree)
    if _count_nodes(tree.roots) <= max_nodes_per_chunk:
        return [
            _org_chart_chunk(
                text=full_text,
                source_name=tree.source_name,
                index=0,
                metadata={"page": tree.source_page},
            )
        ]

    chunks = [
        _org_chart_chunk(
            text=full_text,
            source_name=tree.source_name,
            index=0,
            metadata={"page": tree.source_page},
        )
    ]
    for root in tree.roots:
        for child in root.children:
            if _count_nodes([child]) >= max_nodes_per_chunk:
                chunks.append(
                    _org_chart_chunk(
                        text=_subtree_text(tree, [root, child], child),
                        source_name=tree.source_name,
                        index=len(chunks),
                        metadata={"page": tree.source_page},
                    )
                )
    return chunks


def normalize_org_chart_heading(text: str) -> str:
    return normalize_org_chart_block_text(text)


def _normalize_split_character_part(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text.strip())
    tokens = collapsed.split(" ")
    if len(tokens) >= 3 and all(re.fullmatch(r"[A-Za-z0-9&/(),.-]", token) for token in tokens):
        return "".join(tokens)
    return collapsed


def _is_noise_block(block: PdfTextBlock, page_height: float) -> bool:
    text = block.text.strip()
    if not _is_page_edge_block(block, page_height):
        return False
    if re.fullmatch(r"\d+(?:\s*/\s*\d+)?", text):
        return True
    if re.fullmatch(r"(?i)slide\s+\d+", text):
        return True
    return bool(
        re.fullmatch(
            r"(?i)(?:JLR\s+Confidential\s*)?(?:©\s*202\d|strictly confidential|internal use only|JLR\s+Confidential\s*©?\s*202\d?)",
            text,
        )
    )


def _is_page_edge_block(block: PdfTextBlock, page_height: float) -> bool:
    if page_height <= 0:
        return False
    return block.y1 <= page_height * 0.15 or block.y0 >= page_height * 0.85


def _best_title_block(
    blocks: Sequence[PdfTextBlock], page_height: float
) -> Optional[PdfTextBlock]:
    structural = [block for block in blocks if _is_title_signal(block.text)]
    if structural:
        return min(structural, key=lambda block: (block.y0, -block.font_size))
    top_limit = page_height * 0.15 if page_height > 0 else max(block.y1 for block in blocks)
    top_blocks = [block for block in blocks if block.y0 <= top_limit]
    candidates = top_blocks or list(blocks)
    return max(candidates, key=lambda block: (block.font_size, (block.x1 - block.x0) * (block.y1 - block.y0)))


def _is_title_signal(text: str) -> bool:
    normalized = text.upper()
    return bool(
        re.search(r"\bORG(?:ANISATION|ANIZATION)?\s+CHART\b", normalized)
        or "FIRST LINE STRUCTURE" in normalized
    )


def _same_title_text(first: str, second: str) -> bool:
    return re.sub(r"\W+", "", first).upper() == re.sub(r"\W+", "", second).upper()


def _should_merge_blocks(first: PdfTextBlock, second: PdfTextBlock) -> bool:
    if first.page != second.page:
        return False
    avg_font = max((first.font_size + second.font_size) / 2, 1)
    vertical_gap = max(0.0, second.y0 - first.y1)
    if vertical_gap > 1.5 * avg_font:
        return False
    return abs(first.x_center - second.x_center) < 5 or _x_overlap_ratio(first, second) >= 0.7


def _x_overlap_ratio(first: PdfTextBlock, second: PdfTextBlock) -> float:
    overlap = max(0.0, min(first.x1, second.x1) - max(first.x0, second.x0))
    width = max(1.0, min(first.x1 - first.x0, second.x1 - second.x0))
    return overlap / width


def _merged_node(index: int, first: PdfTextBlock, second: PdfTextBlock) -> OrgChartNode:
    return OrgChartNode(
        node_id=f"n{index + 1}",
        line_1=first.text,
        line_2=second.text,
        semantic_binding="unresolved",
        bbox=(
            min(first.x0, second.x0),
            min(first.y0, second.y0),
            max(first.x1, second.x1),
            max(first.y1, second.y1),
        ),
        page=first.page,
    )


def _single_line_node(index: int, block: PdfTextBlock) -> OrgChartNode:
    return OrgChartNode(
        node_id=f"n{index + 1}",
        line_1=block.text,
        semantic_binding="unresolved",
        bbox=(block.x0, block.y0, block.x1, block.y1),
        page=block.page,
    )


def _y_bands(nodes: Sequence[OrgChartNode], tolerance: float = 8.0) -> List[List[OrgChartNode]]:
    bands: List[List[OrgChartNode]] = []
    for node in sorted(nodes, key=lambda item: (item.y_center, item.x_center)):
        for band in bands:
            center = sum(item.y_center for item in band) / len(band)
            if abs(node.y_center - center) <= tolerance:
                band.append(node)
                break
        else:
            bands.append([node])
    return [sorted(band, key=lambda item: item.x_center) for band in bands]


def _nearest_x_parent(
    child: OrgChartNode, candidates: Sequence[OrgChartNode], max_x_distance: float = 500.0
) -> Optional[OrgChartNode]:
    if not candidates:
        return None
    parent = min(candidates, key=lambda item: abs(item.x_center - child.x_center))
    if abs(parent.x_center - child.x_center) > max_x_distance:
        return None
    return parent


def _attach_edges(
    nodes: Sequence[OrgChartNode], edges: Sequence[OrgChartEdge]
) -> List[OrgChartNode]:
    by_id = {node.node_id: node for node in nodes}
    child_ids = {edge.child_node_id for edge in edges}
    for node in by_id.values():
        node.children = []
    for edge in edges:
        parent = by_id.get(edge.parent_node_id)
        child = by_id.get(edge.child_node_id)
        if parent and child:
            parent.children.append(child)
    return [node for node in nodes if node.node_id not in child_ids]


def _structure_lines(node: OrgChartNode, depth: int = 0) -> List[str]:
    lines = [f"{'  ' * depth}- {_node_label(node, role_style=True)}"]
    for child in node.children:
        lines.extend(_structure_lines(child, depth + 1))
    return lines


def _semantic_triggers(roots: Sequence[OrgChartNode]) -> List[str]:
    triggers: List[str] = []
    for parent in _walk_nodes(roots):
        for child in parent.children:
            if parent.semantic_binding == "resolved" and child.semantic_binding == "resolved":
                triggers.append(f"- {_plain_label(parent)} manages {_plain_label(child)}.")
            else:
                triggers.append(
                    f"- {_node_label(child, role_style=False)} is structurally under {_node_label(parent, role_style=False)}."
                )
    return triggers


def _walk_nodes(roots: Iterable[OrgChartNode]) -> Iterable[OrgChartNode]:
    for root in roots:
        yield root
        yield from _walk_nodes(root.children)


def _node_label(node: OrgChartNode, *, role_style: bool) -> str:
    if not node.line_2:
        return f"Field 1: {node.line_1}" if node.semantic_binding != "resolved" else node.line_1
    if node.semantic_binding == "resolved" and role_style:
        return f"{node.line_1} (Role: {node.line_2})"
    if node.semantic_binding == "resolved":
        return f"{node.line_1} ({node.line_2})"
    return f"Field 1: {node.line_1} (Field 2: {node.line_2})"


def _plain_label(node: OrgChartNode) -> str:
    return node.line_1


def _count_nodes(nodes: Iterable[OrgChartNode]) -> int:
    return sum(1 for _ in _walk_nodes(nodes))


def _subtree_text(
    tree: OrgChartTree, path: Sequence[OrgChartNode], subtree_root: OrgChartNode
) -> str:
    context = " -> ".join(_node_label(node, role_style=False) for node in path)
    lines = [
        "[ORG_CHART_SUBTREE]",
        f"Source: {tree.source_name}",
        f"Page: {tree.source_page}",
        f"Context Root: {context}",
        f"Confidence: {tree.confidence}",
        "",
        "Structure:",
    ]
    for child in subtree_root.children:
        lines.extend(_structure_lines(child))
    lines.extend(["", "Semantic Search Triggers:"])
    if len(path) >= 2:
        lines.append(f"- {_plain_label(path[0])} manages {_plain_label(path[1])}.")
    lines.extend(_semantic_triggers([subtree_root]))
    lines.append("[/ORG_CHART_SUBTREE]")
    return "\n".join(lines)


def _org_chart_chunk(
    *, text: str, source_name: str, index: int, metadata: Dict[str, Any]
) -> OrgChartChunk:
    created_at = datetime.now(timezone.utc).astimezone().isoformat()
    return OrgChartChunk(
        id=f"{source_name}#{index}",
        text=text,
        source_name=source_name,
        source_type="org_chart",
        chunk_index=index,
        created_at=created_at,
        metadata=metadata,
        embedding_text=text,
    )


def _window_text(text: str, max_chunk_size: int) -> Iterable[str]:
    stripped = text.strip()
    if len(stripped) <= max_chunk_size:
        yield stripped
        return
    for start in range(0, len(stripped), max_chunk_size):
        yield stripped[start : start + max_chunk_size]
