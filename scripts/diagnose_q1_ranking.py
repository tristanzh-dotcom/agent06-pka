import argparse
from collections import Counter
import sqlite3
from typing import Any, Dict, Iterable, List

from engine.config import load_config
from engine.indexer import HybridIndexer, OllamaEmbeddingClient, _safe_fts_query, _tokenize
from engine.retriever import reciprocal_rank_fusion


QUESTION = "座舱智能化的发展阶段和趋势是什么？"
SOURCE_KEYWORDS = {
    "智能座舱": "智能座舱",
    "自动驾驶": "自动驾驶",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose Q1 FTS5/vector/RRF ranking.")
    parser.add_argument("--question", default=QUESTION)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    config = load_config(args.config)
    indexer = _build_indexer(config)
    fts = indexer.search_fts(args.question, top_k=args.top_k)
    vector = indexer.search_vector(args.question, top_k=args.top_k)
    merged = reciprocal_rank_fusion(
        indexer.search_fts(args.question, top_k=config["retrieval"]["fts5_top_k"]),
        indexer.search_vector(args.question, top_k=config["retrieval"]["vector_top_k"]),
        config["retrieval"]["rrf_k"],
    )[: args.top_k]
    snippets = {
        label: search_fts_for_source(
            fts_db_path=config["fts5"]["db_path"],
            question=args.question,
            source_keyword=keyword,
            top_k=args.top_k,
        )
        for label, keyword in SOURCE_KEYWORDS.items()
    }

    print(f"# Q1 Ranking Diagnostic\n\nQuestion: {args.question}\n")
    print("## Per-PDF FTS5 Eligibility\n")
    print(build_source_snippet_table(snippets))
    print("\n## Channel Summary\n")
    print(build_channel_table({"FTS5": fts, "Vector": vector, "RRF merged": merged}))
    print("\n## RRF Rank Detail\n")
    print(build_rank_detail_table(merged))


def _build_indexer(config: Dict[str, Any]) -> HybridIndexer:
    embedding_config = config.get("embedding", {})
    return HybridIndexer(
        config["fts5"]["db_path"],
        config["chroma"]["persist_dir"],
        config["chroma"]["collection_name"],
        OllamaEmbeddingClient(
            host=embedding_config.get("host", "http://localhost:11434"),
            model=embedding_config.get("model", "bge-m3"),
            query_prefix=embedding_config.get("query_prefix", ""),
        ),
    )


def search_fts_for_source(
    fts_db_path: str,
    question: str,
    source_keyword: str,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    tokens = _safe_fts_query(_tokenize(question))
    if not tokens:
        return []
    with sqlite3.connect(fts_db_path) as connection:
        rows = connection.execute(
            """
            SELECT chunk_id, text, source_name, source_type, chunk_index, bm25(chunks_fts) AS rank
            FROM chunks_fts
            WHERE tokens MATCH ? AND source_name LIKE ?
            ORDER BY rank
            LIMIT ?
            """,
            (tokens, f"%{source_keyword}%", top_k),
        ).fetchall()
    return [
        {
            "chunk_id": row[0],
            "text": row[1],
            "source_name": row[2],
            "source_type": row[3],
            "chunk_index": int(row[4]),
            "score": float(row[5]),
        }
        for row in rows
    ]


def build_source_snippet_table(snippets: Dict[str, List[Dict[str, Any]]]) -> str:
    lines = [
        "| 来源 PDF | Rank | chunk_id | 文本片段 |",
        "|---|---:|---|---|",
    ]
    for label, results in snippets.items():
        for rank, result in enumerate(results[:5], start=1):
            lines.append(
                f"| {label} | {rank} | `{_short_chunk_id(result['chunk_id'])}` | "
                f"{_escape_table(_snippet(result.get('text', '')))} |"
            )
    return "\n".join(lines)


def build_channel_table(channels: Dict[str, List[Dict[str, Any]]]) -> str:
    tables = []
    for channel, results in channels.items():
        rows = [
            "| 通道 | Rank 1-5 chunk_id | 来源 PDF | 来源计数 |",
            "|---|---|---|---|",
            (
                f"| {channel} | `{', '.join(_short_chunk_id(item['chunk_id']) for item in results[:5])}` | "
                f"{', '.join(_source_label(item.get('source_name', '')) for item in results[:5])} | "
                f"{_source_counts(results[:5])} |"
            ),
        ]
        tables.append("\n".join(rows))
    return "\n\n".join(tables)


def build_rank_detail_table(results: Iterable[Dict[str, Any]]) -> str:
    lines = [
        "| Rank | chunk_id | 来源 PDF | RRF score | FTS5 rank | Vector rank |",
        "|---:|---|---|---:|---:|---:|",
    ]
    for rank, item in enumerate(list(results)[:5], start=1):
        lines.append(
            f"| {rank} | `{_short_chunk_id(item['chunk_id'])}` | {_source_label(item.get('source_name', ''))} | "
            f"{float(item.get('score', 0.0)):.6f} | {_rank_value(item.get('rank_fts5'))} | "
            f"{_rank_value(item.get('rank_vector'))} |"
        )
    return "\n".join(lines)


def _short_chunk_id(chunk_id: str) -> str:
    if "#" not in chunk_id:
        return chunk_id
    return "#" + chunk_id.rsplit("#", 1)[1]


def _source_label(source_name: str) -> str:
    if "智能座舱" in source_name:
        return "智能座舱"
    if "自动驾驶" in source_name:
        return "自动驾驶"
    return "其他"


def _source_counts(results: List[Dict[str, Any]]) -> str:
    counts = Counter(_source_label(item.get("source_name", "")) for item in results)
    return ", ".join(f"{label}={count}" for label, count in counts.items())


def _snippet(text: str, limit: int = 120) -> str:
    return " ".join(str(text).split())[:limit]


def _escape_table(text: str) -> str:
    return text.replace("|", "\\|")


def _rank_value(value: Any) -> str:
    if value is None:
        return "-"
    return str(value)


if __name__ == "__main__":
    main()
