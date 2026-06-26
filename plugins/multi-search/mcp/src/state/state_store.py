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
            for statement in SCHEMA:
                conn.execute(statement)
            self._ensure_columns(conn, "key_state", {
                "use_count": "INTEGER NOT NULL DEFAULT 0",
                "last_used_at": "TEXT",
                "invalid_strikes": "INTEGER NOT NULL DEFAULT 0",
            })

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
