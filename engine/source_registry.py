from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from typing import Any, Optional


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    content_hash: str
    content_kind: str
    original_name: str
    source_name: str
    raw_file_path: str
    status: str
    chunk_count: int
    quality: dict[str, Any]
    coverage: dict[str, Any]
    created_at: str
    updated_at: str
    error: str = ""


class SourceRegistry:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def create_indexed(
        self,
        *,
        source_id: str,
        content_hash: str,
        content_kind: str,
        original_name: str,
        source_name: str,
        raw_file_path: str,
        chunk_count: int,
        quality: Optional[dict] = None,
        coverage: Optional[dict] = None,
    ) -> SourceRecord:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO source_registry(
                    source_id, content_hash, content_kind, original_name, source_name,
                    raw_file_path, status, chunk_count, quality_json, coverage_json,
                    error, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, 'indexed', ?, ?, ?, '',
                    COALESCE((SELECT created_at FROM source_registry WHERE source_id = ?), CURRENT_TIMESTAMP),
                    CURRENT_TIMESTAMP
                )
                """,
                (
                    source_id,
                    content_hash,
                    content_kind,
                    original_name,
                    source_name,
                    raw_file_path,
                    int(chunk_count),
                    _json(quality),
                    _json(coverage),
                    source_id,
                ),
            )
        record = self.get(source_id)
        if record is None:
            raise RuntimeError("source registry write failed")
        return record

    def get(self, source_id: str) -> Optional[SourceRecord]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM source_registry WHERE source_id = ?",
                (source_id,),
            ).fetchone()
        return _record(row)

    def find_active_by_original_name(self, original_name: str) -> Optional[SourceRecord]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM source_registry
                WHERE original_name = ? AND status = 'indexed'
                ORDER BY created_at DESC, source_id DESC LIMIT 1
                """,
                (original_name,),
            ).fetchone()
        return _record(row)

    def list_sources(self) -> list[SourceRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM source_registry WHERE status IN ('indexed', 'delete_failed') ORDER BY created_at DESC, source_id DESC"
            ).fetchall()
        return [record for row in rows if (record := _record(row)) is not None]

    def mark_delete_failed(self, source_id: str, error: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE source_registry SET status = 'delete_failed', error = ?, updated_at = CURRENT_TIMESTAMP WHERE source_id = ?",
                (str(error), source_id),
            )

    def delete(self, source_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM source_registry WHERE source_id = ?", (source_id,))

    def clear(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM source_registry")

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS source_registry (
                    source_id TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    content_kind TEXT NOT NULL,
                    original_name TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    raw_file_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    quality_json TEXT NOT NULL DEFAULT '{}',
                    coverage_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS source_registry_original_name ON source_registry(original_name, status)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path))
        connection.row_factory = sqlite3.Row
        return connection


def _json(value: Optional[dict]) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def _record(row: Optional[sqlite3.Row]) -> Optional[SourceRecord]:
    if row is None:
        return None
    return SourceRecord(
        source_id=str(row["source_id"]),
        content_hash=str(row["content_hash"]),
        content_kind=str(row["content_kind"]),
        original_name=str(row["original_name"]),
        source_name=str(row["source_name"]),
        raw_file_path=str(row["raw_file_path"]),
        status=str(row["status"]),
        chunk_count=int(row["chunk_count"] or 0),
        quality=json.loads(row["quality_json"] or "{}"),
        coverage=json.loads(row["coverage_json"] or "{}"),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        error=str(row["error"] or ""),
    )
