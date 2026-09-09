"""Short-lived lookup from compact SearchHit ids to their source URLs."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Callable

from .state_store import StateStore


DEFAULT_SOURCE_TTL_SECONDS = 24 * 60 * 60


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SourceRegistry:
    def __init__(
        self,
        store: StateStore,
        *,
        ttl_seconds: int = DEFAULT_SOURCE_TTL_SECONDS,
        clock: Callable[[], datetime] = _utc_now,
    ):
        self.store = store
        self.ttl_seconds = max(1, int(ttl_seconds))
        self.clock = clock

    def register(self, response_id: str, hits: list[dict]) -> None:
        now = self.clock()
        expires_at = now + timedelta(seconds=self.ttl_seconds)
        with self.store.connect() as conn:
            self._purge_expired_conn(conn, now.isoformat())
            for hit in hits:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO search_sources (
                      source_id, response_id, title, url, canonical_url,
                      content, content_kind, providers_json, body_available,
                      created_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(hit["source_id"]),
                        response_id,
                        str(hit.get("title") or ""),
                        str(hit.get("url") or ""),
                        str(hit.get("canonical_url") or ""),
                        str(hit.get("content") or ""),
                        str(hit.get("content_kind") or "content"),
                        json.dumps(hit.get("providers") or [], sort_keys=True),
                        1 if hit.get("body_available") else 0,
                        now.isoformat(),
                        expires_at.isoformat(),
                    ),
                )

    def get(self, source_id: str) -> dict | None:
        rows = self.store.rows(
            "SELECT * FROM search_sources WHERE source_id = ?", (source_id,)
        )
        if not rows:
            return None
        row = rows[0]
        expires_at = datetime.fromisoformat(str(row["expires_at"]))
        if expires_at <= self.clock():
            self.delete(source_id)
            return None
        row["providers"] = json.loads(row.pop("providers_json") or "[]")
        row["body_available"] = bool(row["body_available"])
        return row

    def delete(self, source_id: str) -> None:
        self.store.execute(
            "DELETE FROM search_sources WHERE source_id = ?", (source_id,)
        )

    def purge_expired(self) -> int:
        now = self.clock().isoformat()
        with self.store.connect() as conn:
            return self._purge_expired_conn(conn, now)

    @staticmethod
    def _purge_expired_conn(conn, now: str) -> int:
        cursor = conn.execute(
            "DELETE FROM search_sources WHERE expires_at <= ?", (now,)
        )
        return int(cursor.rowcount or 0)
