from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class RerankResult:
    chunk_id: str
    score: float


class RerankerClient:
    def rerank(self, query: str, candidates: List[Dict[str, Any]]) -> List[RerankResult]:
        raise NotImplementedError
