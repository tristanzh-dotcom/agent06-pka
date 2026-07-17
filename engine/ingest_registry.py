from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import sqlite3
from typing import Optional


@dataclass(frozen=True)
class ContentReservation:
    status: str
    content_hash: str
    source_name: str = ""
    raw_file_path: str = ""
    task_id: str = ""
    chunk_count: int = 0
    error: str = ""


class ContentRegistry:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def reserve(
        self,
        *,
        content_hash: str,
        source_name: str,
        raw_file_path: str,
        content_kind: str,
        allow_review_retry: bool = False,
        allow_version_retry: bool = False,
    ) -> ContentReservation:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT status, source_name, raw_file_path, task_id, chunk_count, error
                FROM content_registry WHERE content_hash = ?
                """,
                (content_hash,),
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO content_registry(
                        content_hash, content_kind, status, source_name, raw_file_path, task_id, chunk_count, error
                    ) VALUES (?, ?, 'processing', ?, ?, '', 0, '')
                    """,
                    (content_hash, content_kind, source_name, raw_file_path),
                )
                return ContentReservation(status="reserved", content_hash=content_hash)

            status, existing_source, existing_path, task_id, chunk_count, error = row
            if status == "indexed":
                return ContentReservation(
                    status="duplicate",
                    content_hash=content_hash,
                    source_name=existing_source,
                    raw_file_path=existing_path,
                    task_id=task_id or "",
                    chunk_count=int(chunk_count or 0),
                )
            if status == "processing":
                return ContentReservation(
                    status="duplicate_pending",
                    content_hash=content_hash,
                    source_name=existing_source,
                    raw_file_path=existing_path,
                    task_id=task_id or "",
                    chunk_count=int(chunk_count or 0),
                )
            if status == "review_required" and not allow_review_retry:
                return ContentReservation(
                    status="review_required",
                    content_hash=content_hash,
                    source_name=existing_source,
                    raw_file_path=existing_path,
                    error=error or "",
                )
            if status == "version_conflict" and not allow_version_retry:
                return ContentReservation(
                    status="version_conflict",
                    content_hash=content_hash,
                    source_name=existing_source,
                    raw_file_path=existing_path,
                    error=error or "",
                )

            connection.execute(
                """
                UPDATE content_registry
                SET content_kind = ?, status = 'processing', source_name = ?, raw_file_path = ?, task_id = '', chunk_count = 0, error = ''
                WHERE content_hash = ?
                """,
                (content_kind, source_name, raw_file_path, content_hash),
            )
            return ContentReservation(status="reserved", content_hash=content_hash, error=error or "")

    def mark_indexed(self, content_hash: str, *, chunk_count: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE content_registry SET status = 'indexed', chunk_count = ?, task_id = '', error = '' WHERE content_hash = ?",
                (chunk_count, content_hash),
            )

    def mark_pending(self, content_hash: str, *, task_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE content_registry SET status = 'processing', task_id = ? WHERE content_hash = ?",
                (task_id, content_hash),
            )

    def mark_failed(self, content_hash: str, error: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE content_registry SET status = 'failed', error = ?, task_id = '' WHERE content_hash = ?",
                (str(error), content_hash),
            )

    def mark_review_required(self, content_hash: str, reason: str = "") -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE content_registry SET status = 'review_required', error = ?, task_id = '' WHERE content_hash = ?",
                (str(reason), content_hash),
            )

    def mark_version_conflict(self, content_hash: str, reason: str = "") -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE content_registry SET status = 'version_conflict', error = ?, task_id = '' WHERE content_hash = ?",
                (str(reason), content_hash),
            )

    def lookup(self, content_hash: str) -> Optional[ContentReservation]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT status, source_name, raw_file_path, task_id, chunk_count, error
                FROM content_registry WHERE content_hash = ?
                """,
                (content_hash,),
            ).fetchone()
        if row is None:
            return None
        status, source_name, raw_file_path, task_id, chunk_count, error = row
        return ContentReservation(
            status=str(status),
            content_hash=content_hash,
            source_name=str(source_name or ""),
            raw_file_path=str(raw_file_path or ""),
            task_id=str(task_id or ""),
            chunk_count=int(chunk_count or 0),
            error=str(error or ""),
        )

    def register_indexed_existing(
        self,
        *,
        content_hash: str,
        source_name: str,
        raw_file_path: str,
        content_kind: str,
        chunk_count: int = 0,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO content_registry(
                    content_hash, content_kind, status, source_name, raw_file_path, task_id, chunk_count, error
                ) VALUES (?, ?, 'indexed', ?, ?, '', ?, '')
                """,
                (content_hash, content_kind, source_name, raw_file_path, chunk_count),
            )

    def needs_index_backfill(self) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM content_registry_meta WHERE key = 'indexed_raw_backfill_v1'").fetchone()
        return row is None

    def mark_index_backfill_complete(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO content_registry_meta(key, value) VALUES ('indexed_raw_backfill_v1', 'complete')"
            )

    def clear(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM content_registry")
            connection.execute("DELETE FROM content_registry_meta")

    def delete(self, content_hash: str) -> None:
        if not content_hash:
            return
        with self._connect() as connection:
            connection.execute("DELETE FROM content_registry WHERE content_hash = ?", (content_hash,))

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS content_registry (
                    content_hash TEXT PRIMARY KEY,
                    content_kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    raw_file_path TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS content_registry_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.path))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    normalized = "\n".join(str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip().split("\n"))
    return sha256_bytes(normalized.encode("utf-8"))
