"""SQLite-backed short-lived content cache keyed by source id."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Callable

from .state_store import StateStore


DEFAULT_CONTENT_TTL_SECONDS = 60 * 60
DEFAULT_MAX_OBJECT_BYTES = 256 * 1024
DEFAULT_MAX_TOTAL_BYTES = 5 * 1024 * 1024


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ContentStoreError(ValueError):
    """Raised when content cannot be stored safely."""


class ContentStore:
    def __init__(
        self,
        store: StateStore,
        *,
        ttl_seconds: int = DEFAULT_CONTENT_TTL_SECONDS,
        max_object_bytes: int = DEFAULT_MAX_OBJECT_BYTES,
        max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
        clock: Callable[[], datetime] = _utc_now,
    ):
        self.store = store
        self.ttl_seconds = max(1, int(ttl_seconds))
        self.max_object_bytes = max(1, int(max_object_bytes))
        self.max_total_bytes = max(1, int(max_total_bytes))
        self.clock = clock

    def put(self, source_id: str, content: str) -> dict:
        if not source_id:
            raise ContentStoreError("source_id is required")
        if not isinstance(content, str):
            raise ContentStoreError("content must be a string")

        payload = content.encode("utf-8")
        content_bytes = len(payload)
        if content_bytes > self.max_object_bytes:
            raise ContentStoreError(
                f"content size {content_bytes} exceeds max object bytes {self.max_object_bytes}"
            )
        if content_bytes > self.max_total_bytes:
            raise ContentStoreError(
                f"content size {content_bytes} exceeds max total bytes {self.max_total_bytes}"
            )

        now = self.clock()
        now_iso = now.isoformat()
        expires_at = (now + timedelta(seconds=self.ttl_seconds)).isoformat()
        content_hash = hashlib.sha256(payload).hexdigest()

        with self.store.connect() as conn:
            self._purge_expired_conn(conn, now)
            previous = conn.execute(
                "SELECT content_hash FROM content_sources WHERE source_id = ?",
                (source_id,),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO content_objects (
                  content_hash, content, content_bytes, created_at, last_access_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(content_hash) DO UPDATE SET
                  last_access_at = excluded.last_access_at
                """,
                (content_hash, content, content_bytes, now_iso, now_iso),
            )
            conn.execute(
                """
                INSERT INTO content_sources (
                  source_id, content_hash, created_at, expires_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                  content_hash = excluded.content_hash,
                  created_at = excluded.created_at,
                  expires_at = excluded.expires_at
                """,
                (source_id, content_hash, now_iso, expires_at),
            )
            if previous and previous["content_hash"] != content_hash:
                self._drop_unreferenced_object(conn, str(previous["content_hash"]))
            self._evict_lru(conn, protected_hash=content_hash)
            row = self._lookup_conn(conn, source_id)
            if row is None:
                raise ContentStoreError("content was evicted before it could be stored")
            return row

    def get(self, source_id: str) -> dict | None:
        now = self.clock()
        now_iso = now.isoformat()
        with self.store.connect() as conn:
            self._purge_expired_conn(conn, now)
            row = self._lookup_conn(conn, source_id)
            if row is None:
                return None
            conn.execute(
                "UPDATE content_objects SET last_access_at = ? WHERE content_hash = ?",
                (now_iso, row["content_hash"]),
            )
            row["last_access_at"] = now_iso
            return row

    def delete_source(self, source_id: str) -> int:
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT content_hash FROM content_sources WHERE source_id = ?",
                (source_id,),
            ).fetchone()
            if row is None:
                return 0
            conn.execute("DELETE FROM content_sources WHERE source_id = ?", (source_id,))
            self._drop_unreferenced_object(conn, str(row["content_hash"]))
            return 1

    def purge_expired(self) -> int:
        with self.store.connect() as conn:
            return self._purge_expired_conn(conn, self.clock())

    def _lookup_conn(self, conn, source_id: str) -> dict | None:
        row = conn.execute(
            """
            SELECT
              s.source_id,
              s.expires_at,
              o.content_hash,
              o.content,
              o.content_bytes,
              o.created_at,
              o.last_access_at
            FROM content_sources AS s
            JOIN content_objects AS o ON o.content_hash = s.content_hash
            WHERE s.source_id = ?
            """,
            (source_id,),
        ).fetchone()
        return dict(row) if row else None

    def _purge_expired_conn(self, conn, now: datetime) -> int:
        expired_rows = conn.execute(
            "SELECT source_id, content_hash FROM content_sources WHERE expires_at <= ?",
            (now.isoformat(),),
        ).fetchall()
        if not expired_rows:
            return 0
        conn.execute("DELETE FROM content_sources WHERE expires_at <= ?", (now.isoformat(),))
        for row in expired_rows:
            self._drop_unreferenced_object(conn, str(row["content_hash"]))
        return len(expired_rows)

    def _drop_unreferenced_object(self, conn, content_hash: str) -> None:
        row = conn.execute(
            "SELECT 1 FROM content_sources WHERE content_hash = ? LIMIT 1",
            (content_hash,),
        ).fetchone()
        if row is None:
            conn.execute(
                "DELETE FROM content_objects WHERE content_hash = ?",
                (content_hash,),
            )

    def _evict_lru(self, conn, *, protected_hash: str) -> None:
        while self._total_bytes(conn) > self.max_total_bytes:
            row = conn.execute(
                """
                SELECT content_hash
                FROM content_objects
                WHERE content_hash <> ?
                ORDER BY last_access_at ASC, created_at ASC, content_hash ASC
                LIMIT 1
                """,
                (protected_hash,),
            ).fetchone()
            if row is None:
                raise ContentStoreError(
                    f"content size exceeds max total bytes {self.max_total_bytes}"
                )
            content_hash = str(row["content_hash"])
            conn.execute(
                "DELETE FROM content_sources WHERE content_hash = ?",
                (content_hash,),
            )
            conn.execute(
                "DELETE FROM content_objects WHERE content_hash = ?",
                (content_hash,),
            )

    def _total_bytes(self, conn) -> int:
        row = conn.execute(
            "SELECT COALESCE(SUM(content_bytes), 0) AS total_bytes FROM content_objects"
        ).fetchone()
        return int(row["total_bytes"] or 0)
