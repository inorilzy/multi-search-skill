"""SQLite-backed runtime state for multi-search MCP/service use."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


DEFAULT_STATE_PATH = Path.home() / ".multi-search" / "state.sqlite"
# How long a writer waits for another process' lock. WAL makes writer/writer
# contention the only blocking case, so this is a safety net, not the normal path.
BUSY_TIMEOUT_SECONDS = 10

# Bump when changing SCHEMA or adding a one-shot data rewrite. Schema creation
# and data rewrites are guarded by ``PRAGMA user_version`` so a second process
# does not take the write lock on every start. The desktop's read-only views of
# ``state.sqlite`` accept versions 1 and 2 only.
STATE_SCHEMA_VERSION = 2


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
    """Small SQLite helper with lazy schema migration.

    Connections are opened per outermost ``connect()`` call and reused by nested
    calls on the same thread, so a composed read-modify-write runs on one
    connection and inside one transaction. They are closed at the end (WAL keeps
    the file usable by other processes meanwhile), which matters on Windows where
    an open handle blocks deleting a temporary database.
    """

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path).expanduser() if path else DEFAULT_STATE_PATH
        self._local = threading.local()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=BUSY_TIMEOUT_SECONDS)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {int(BUSY_TIMEOUT_SECONDS * 1000)}")
        return conn

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection. Nested calls share the outer connection/transaction."""
        depth = getattr(self._local, "depth", 0)
        if depth:
            self._local.depth = depth + 1
            try:
                yield self._local.conn
            finally:
                self._local.depth -= 1
            return
        conn = self._open()
        self._local.conn, self._local.depth = conn, 1
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._local.conn, self._local.depth = None, 0
            conn.close()

    @contextmanager
    def transaction(self, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        """One connection and one explicit transaction, committed or rolled back as a unit.

        ``immediate`` takes the write lock up front, which is what a
        read-modify-write needs to stay correct across processes.
        """
        with self.connect() as conn:
            own_transaction = not conn.in_transaction
            if own_transaction:
                conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            try:
                yield conn
            except Exception:
                if own_transaction and conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise

    def migrate(self) -> None:
        if self._schema_is_current():
            # Fast path: no write lock needed when the schema is already at
            # the expected version and every required column exists.
            return
        with self.connect() as conn:
            # WAL is persistent in the database file: after this, every connection
            # (including other processes) reads without blocking on a writer.
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("BEGIN IMMEDIATE")
            # Re-check under the write lock: another process may have migrated
            # while this one waited.
            if self._schema_is_current_conn(conn):
                return
            for statement in SCHEMA:
                conn.execute(statement)
            self._ensure_columns(conn, "key_state", {
                "use_count": "INTEGER NOT NULL DEFAULT 0",
                "last_used_at": "TEXT",
                "invalid_strikes": "INTEGER NOT NULL DEFAULT 0",
            })
            self._scrub_key_fingerprints(conn)
            self._ensure_columns(conn, "content_sources", {
                "canonical_url": "TEXT NOT NULL DEFAULT ''",
                "cache_scope": "TEXT NOT NULL DEFAULT ''",
            })
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_content_sources_url_scope "
                "ON content_sources (canonical_url, cache_scope, expires_at)"
            )
            self._migrate_data(conn)

    def _schema_is_current(self) -> bool:
        if not self.path.exists():
            return False
        try:
            with self.connect() as conn:
                return self._schema_is_current_conn(conn)
        except sqlite3.Error:
            return False

    @staticmethod
    def _schema_is_current_conn(conn: sqlite3.Connection) -> bool:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version < STATE_SCHEMA_VERSION:
            return False
        required = {
            "key_state": {"use_count", "last_used_at", "invalid_strikes"},
            "content_sources": {"canonical_url", "cache_scope"},
        }
        for table, columns in required.items():
            existing = {
                row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if not columns.issubset(existing):
                return False
        return True

    def _migrate_data(self, conn: sqlite3.Connection) -> None:
        """Stamp the schema version once every migration step has run.

        The one-shot data rewrite (legacy display-mask fingerprints) is done by
        ``_scrub_key_fingerprints`` above; the version stamp keeps later opens on
        the lock-free fast path. The desktop reads ``state.sqlite`` only at a
        version it knows (1 or 2), so bump this together with the desktop.
        """
        from_version = conn.execute("PRAGMA user_version").fetchone()[0]
        if from_version < STATE_SCHEMA_VERSION:
            conn.execute(f"PRAGMA user_version={STATE_SCHEMA_VERSION}")

    @staticmethod
    def _scrub_key_fingerprints(conn: sqlite3.Connection) -> None:
        """Rewrite legacy plaintext fingerprints (``前4...后4 (sha8)``) in place.

        ``key_id`` is ``<provider>:<sha256(key)[:16]>`` and the current fingerprint is
        ``sha256:<sha256(key)[:8]>``, so the new value is derived from ``key_id``
        without the key itself. Idempotent: already-current rows are untouched.
        """
        conn.execute(
            """
            UPDATE key_state
            SET key_fingerprint = 'sha256:' || substr(key_id, -16, 8)
            WHERE length(key_id) >= 17
              AND key_fingerprint IS NOT 'sha256:' || substr(key_id, -16, 8)
            """
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
