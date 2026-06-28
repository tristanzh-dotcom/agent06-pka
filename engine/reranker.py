from dataclasses import dataclass
import json
from typing import Any, Dict, List
import urllib.error
import urllib.request


@dataclass(frozen=True)
class RerankResult:
    chunk_id: str
    score: float


class RerankerClient:
    def __init__(
        self,
        host: str,
        model: str,
        query_prefix: str = "",
        timeout_seconds: float = 30.0,
    ):
        self.host = host
        self.model = model
        self.query_prefix = query_prefix
        self.timeout_seconds = float(timeout_seconds or 30.0)

    def rerank(self, query: str, candidates: List[Dict[str, Any]]) -> List[RerankResult]:
        if not candidates:
            return []
        payload = {
            "model": self.model,
            "query": f"{self.query_prefix}{query}" if self.query_prefix else query,
            "documents": [str(candidate.get("text", "")) for candidate in candidates],
        }
        request = urllib.request.Request(
            url=f"{self.host.rstrip('/')}/api/rerank",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Reranker request failed for model {self.model}: {exc}") from exc

        scores = _extract_scores(body)
        return [
            RerankResult(chunk_id=str(candidate["chunk_id"]), score=float(score))
            for candidate, score in zip(candidates, scores)
        ]


def _extract_scores(body: Dict[str, Any]) -> List[float]:
    if isinstance(body.get("scores"), list):
        return [float(score) for score in body["scores"]]
    for key in ("results", "data"):
        items = body.get(key)
        if isinstance(items, list):
            scores = []
            for item in items:
                if isinstance(item, dict):
                    score = item.get("score", item.get("relevance_score", item.get("probability")))
                else:
                    score = item
                scores.append(float(score))
            return scores
    raise RuntimeError("Reranker response did not include scores")
