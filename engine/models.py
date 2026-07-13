from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ParseQuality:
    status: str
    action: str
    valid_ratio: float
    short_line_ratio: float
    watermark_ratio: float
    unique_line_ratio: float
    non_empty_pages: int
    page_count: int
    non_empty_page_ratio: float
    effective_chars_per_page: float
    cleaned_chars_ratio: float
    reasons: List[str]


@dataclass(frozen=True)
class PreChunkedParseRecord:
    text: str
    source_name: str
    source_type: str
    is_pre_chunked: bool
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParseResult:
    text: str
    source_name: str
    source_type: str
    metadata: Dict[str, Any]
    quality: Optional[ParseQuality] = None
    pre_chunks: List[PreChunkedParseRecord] = field(default_factory=list)


@dataclass(frozen=True)
class Chunk:
    id: str
    text: str
    source_name: str
    source_type: str
    chunk_index: int
    created_at: str
    embedding_text: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    text: str
    source_name: str
    source_type: str
    chunk_index: int
    score: float
    rank_fts5: Optional[int]
    rank_vector: Optional[int]
    raw_file_path: str = ""
