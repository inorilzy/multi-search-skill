"""SQLite-backed runtime state for multi-search MCP/service use."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


DEFAULT_STATE_PATH = Path.home() / ".multi-search" / "state.sqlite"


SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS key_state (
      provider TEXT NOT NULL,
      key_id TEXT NOT NULL,
      key_fingerprint TEXT NOT NULL,
      status TEXT NOT NULL,
      success_count INTEGER NOT NULL DEFAULT 0,
      failure_count INTEGER NOT NULL DEFAULT 0,
      rate_limit_count INTEGER NOT NULL DEFAULT 0,
      quota_error_count INTEGER NOT NULL DEFAULT 0,
      use_count INTEGER NOT NULL DEFAULT 0,
      invalid_strikes INTEGER NOT NULL DEFAULT 0,
      last_used_at TEXT,
      last_success_at TEXT,
      last_failure_at TEXT,
      last_error_type TEXT,
      last_error_message TEXT,
      cooldown_until TEXT,
      exhausted_until TEXT,
      manually_disabled INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY (provider, key_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS site_scraper_stats (
      site TEXT NOT NULL,
      scraper TEXT NOT NULL,
      success_count INTEGER NOT NULL DEFAULT 0,
      failure_count INTEGER NOT NULL DEFAULT 0,
      blocked_count INTEGER NOT NULL DEFAULT 0,
      timeout_count INTEGER NOT NULL DEFAULT 0,
      avg_content_length INTEGER,
      last_success_at TEXT,
      last_failure_at TEXT,
      last_error_type TEXT,
      last_error_message TEXT,
      cooldown_until TEXT,
      sample_url TEXT,
      manually_pinned INTEGER NOT NULL DEFAULT 0,
      manual_priority INTEGER,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY (site, scraper)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scrape_attempts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      url TEXT NOT NULL,
      site TEXT NOT NULL,
      scraper TEXT NOT NULL,
      success INTEGER NOT NULL,
      content_length INTEGER,
      error_type TEXT,
      error_message TEXT,
      elapsed_ms INTEGER,
      created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS provider_runs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      provider TEXT NOT NULL,
      operation TEXT NOT NULL,
      success INTEGER NOT NULL,
      raw_hits INTEGER,
      error_type TEXT,
      error_message TEXT,
      elapsed_ms INTEGER,
      created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS search_sources (
      source_id TEXT PRIMARY KEY,
      response_id TEXT NOT NULL,
      title TEXT NOT NULL,
      url TEXT NOT NULL,
      canonical_url TEXT NOT NULL,
      content TEXT NOT NULL,
      content_kind TEXT NOT NULL,
      providers_json TEXT NOT NULL,
      body_available INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL,
      expires_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_search_sources_expires
    ON search_sources (expires_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS content_objects (
      content_hash TEXT PRIMARY KEY,
      content TEXT NOT NULL,
      content_bytes INTEGER NOT NULL,
      created_at TEXT NOT NULL,
      last_access_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_content_objects_last_access
    ON content_objects (last_access_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS content_sources (
      source_id TEXT PRIMARY KEY,
      content_hash TEXT NOT NULL,
      created_at TEXT NOT NULL,
      expires_at TEXT NOT NULL,
      canonical_url TEXT NOT NULL DEFAULT '',
      cache_scope TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_content_sources_hash
    ON content_sources (content_hash)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_content_sources_expires
    ON content_sources (expires_at)
    """,
)


class StateStore:
    """Small SQLite helper with lazy schema migration."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path).expanduser() if path else DEFAULT_STATE_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path), timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def migrate(self) -> None:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for statement in SCHEMA:
                conn.execute(statement)
            self._ensure_columns(conn, "key_state", {
                "use_count": "INTEGER NOT NULL DEFAULT 0",
                "last_used_at": "TEXT",
                "invalid_strikes": "INTEGER NOT NULL DEFAULT 0",
            })
            self._ensure_columns(conn, "content_sources", {
                "canonical_url": "TEXT NOT NULL DEFAULT ''",
                "cache_scope": "TEXT NOT NULL DEFAULT ''",
            })
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_content_sources_url_scope "
                "ON content_sources (canonical_url, cache_scope, expires_at)"
            )

    def _ensure_columns(self, conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, definition in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def rows(self, query: str, params: tuple = ()) -> list[dict]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(query, params).fetchall()]

    def execute(self, query: str, params: tuple = ()) -> None:
        with self.connect() as conn:
            conn.execute(query, params)
