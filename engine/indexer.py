import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.request

from engine.models import Chunk


class OllamaEmbeddingClient:
    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "bge-m3",
        query_prefix: str = "",
    ):
        self.host = host
        self.model = model
        self.query_prefix = query_prefix

    def embed(self, texts: List[str]) -> List[List[float]]:
        vectors = []
        for text in texts:
            vectors.append(self._embed_one(text))
        return vectors

    def embed_query(self, query: str) -> List[float]:
        prompt = f"{self.query_prefix}{query}" if self.query_prefix else query
        return self._embed_one(prompt)

    def _embed_one(self, text: str) -> List[float]:
        request = urllib.request.Request(
            url=f"{self.host.rstrip('/')}/api/embeddings",
            data=json.dumps({"model": self.model, "prompt": text}, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Ollama embedding failed for model {self.model}: {exc}") from exc

        embedding = payload.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            raise RuntimeError(f"Ollama embedding returned no vector for model {self.model}")
        return [float(value) for value in embedding]


class HybridIndexer:
    def __init__(
        self,
        fts_db_path: str,
        vector_dir: str,
        collection_name: str,
        embedding_client: Optional[Any] = None,
    ):
        self.fts_db_path = Path(fts_db_path)
        self.vector_dir = Path(vector_dir)
        self.collection_name = collection_name
        self.embedding_client = embedding_client or OllamaEmbeddingClient()
        self.fts_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.vector_dir.mkdir(parents=True, exist_ok=True)
        self.client, self.collection = self._build_collection()
        self._init_fts()

    def _build_collection(self):
        import chromadb
        from chromadb.config import Settings

        client = chromadb.PersistentClient(
            path=str(self.vector_dir),
            settings=Settings(anonymized_telemetry=False),
        )
        collection = client.get_or_create_collection(name=self.collection_name)
        return client, collection

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.fts_db_path))

    def _init_fts(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    chunk_id UNINDEXED,
                    text UNINDEXED,
                    tokens,
                    source_name UNINDEXED,
                    source_type UNINDEXED,
                    chunk_index UNINDEXED,
                    created_at UNINDEXED
                )
                """
            )

    def upsert(self, chunks: List[Chunk], raw_file_paths: Optional[List[str]] = None) -> int:
        if not chunks:
            return 0
        if raw_file_paths is not None and len(raw_file_paths) != len(chunks):
            raise ValueError("raw_file_paths length must match chunks length")
        vectors = self.embedding_client.embed([chunk.embedding_text or chunk.text for chunk in chunks])
        with self._connect() as connection:
            for chunk in chunks:
                connection.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (chunk.id,))
                connection.execute(
                    """
                    INSERT INTO chunks_fts(chunk_id, text, tokens, source_name, source_type, chunk_index, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk.id,
                        chunk.text,
                        _tokenize(chunk.text),
                        chunk.source_name,
                        chunk.source_type,
                        chunk.chunk_index,
                        chunk.created_at,
                    ),
                )
        self.collection.upsert(
            ids=[chunk.id for chunk in chunks],
            embeddings=vectors,
            metadatas=[
                {
                    "source_name": chunk.source_name,
                    "source_type": chunk.source_type,
                    "chunk_index": chunk.chunk_index,
                    "created_at": chunk.created_at,
                    "raw_file_path": raw_file_paths[index] if raw_file_paths else "",
                }
                for index, chunk in enumerate(chunks)
            ],
            documents=[chunk.text for chunk in chunks],
        )
        return len(chunks)

    def clear_all(self) -> None:
        result = self.collection.get()
        ids = result.get("ids", [])
        if ids:
            self.collection.delete(ids=ids)
        with self._connect() as connection:
            connection.execute("DELETE FROM chunks_fts")

    def search_fts(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        tokens = _safe_fts_query(_tokenize(query))
        if not tokens:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT chunk_id, text, source_name, source_type, chunk_index, bm25(chunks_fts) AS rank
                FROM chunks_fts
                WHERE tokens MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (tokens, top_k),
            ).fetchall()
        path_map = self._metadata_path_map([row[0] for row in rows])
        return [
            {
                "chunk_id": row[0],
                "text": row[1],
                "source_name": row[2],
                "source_type": row[3],
                "chunk_index": int(row[4]),
                "score": float(row[5]),
                "raw_file_path": path_map.get(row[0], ""),
            }
            for row in rows
        ]

    def search_vector(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        if self.collection.count() == 0:
            return []
        if hasattr(self.embedding_client, "embed_query"):
            query_vector = self.embedding_client.embed_query(query)
        else:
            query_vector = self.embedding_client.embed([query])[0]
        results = self.collection.query(
            query_embeddings=[query_vector],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        return [
            {
                "chunk_id": chunk_id,
                "text": document,
                "source_name": metadata["source_name"],
                "source_type": metadata["source_type"],
                "chunk_index": int(metadata["chunk_index"]),
                "score": _distance_to_score(distance),
                "raw_file_path": metadata.get("raw_file_path", ""),
            }
            for chunk_id, document, metadata, distance in zip(ids, documents, metadatas, distances)
        ]

    def get_chunk(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        result = self.collection.get(
            ids=[chunk_id],
            include=["documents", "metadatas", "embeddings"],
        )
        if not result.get("ids"):
            return None
        metadata = result["metadatas"][0]
        return {
            "chunk_id": chunk_id,
            "vector": result["embeddings"][0],
            "text": result["documents"][0],
            "source_name": metadata["source_name"],
            "source_type": metadata["source_type"],
            "chunk_index": metadata["chunk_index"],
            "created_at": metadata["created_at"],
            "raw_file_path": metadata.get("raw_file_path", ""),
        }

    def count_chunks(self) -> int:
        return self.collection.count()

    def count_sources(self) -> int:
        result = self.collection.get(include=["metadatas"])
        return len({metadata["source_name"] for metadata in result.get("metadatas", [])})

    def _metadata_path_map(self, chunk_ids: List[str]) -> Dict[str, str]:
        if not chunk_ids:
            return {}
        result = self.collection.get(ids=chunk_ids, include=["metadatas"])
        return {
            chunk_id: (metadata or {}).get("raw_file_path", "")
            for chunk_id, metadata in zip(result.get("ids", []), result.get("metadatas", []))
        }


def _tokenize(text: str) -> str:
    try:
        import jieba

        tokens = [token.strip() for token in jieba.cut(text) if token.strip()]
    except Exception:
        tokens = [text]
    return " ".join(tokens)


def _safe_fts_query(tokens: str) -> str:
    """Remove FTS5 syntax characters and quote terms before MATCH."""
    safe = re.sub(r"[、，,;；:：\-\(\)\[\]{}]", " ", tokens)
    terms = [term.strip() for term in safe.split() if term.strip()]
    if not terms:
        return ""
    return " OR ".join(f'"{term}"' for term in terms[:10])


def _distance_to_score(distance: float) -> float:
    return 1.0 / (1.0 + float(distance))
