from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ParseResult:
    text: str
    source_name: str
    source_type: str
    metadata: Dict[str, Any]


@dataclass(frozen=True)
class Chunk:
    id: str
    text: str
    source_name: str
    source_type: str
    chunk_index: int
    created_at: str


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
