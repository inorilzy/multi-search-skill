"""state.sqlite schema compatibility across the baseline and the source branch.

Version contract (``PRAGMA user_version``):

- version 0: the review-fixes baseline, which never stamped a version. It may
  predate the ``canonical_url``/``cache_scope`` columns and store plaintext key
  fingerprints.
- version 1: the source branch's first versioned schema. It has the content
  columns but not ``content_sources.truncated``.
- version 2: current. The only thing it adds over version 1 is
  ``content_sources.truncated``, a per-acquisition metadata flag. Legacy v1
  bindings default to False; existing v2 flags must reach cache/fetch/read
  callers without changing the stored body or weakening cache byte limits.
- anything newer: refused. A database written by a future release is never
  migrated, even when its layout happens to match; opening it raises
  ``StateSchemaVersionError`` and leaves the file unchanged.

The desktop's scrape-memory views accept versions 1 and 2 only, so this stays
at 2.
"""
import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from multi_search_mcp.src.state.content_store import ContentStore
from multi_search_mcp.src.state.key_state import key_fingerprint, key_id_for
from multi_search_mcp.src.state.site_memory import SiteScraperMemory
from multi_search_mcp.src.state.state_store import (
    STATE_SCHEMA_VERSION,
    SCHEMA,
    StateSchemaVersionError,
    StateStore,
)


BODY = "完整正文，没有被截断 stored in full"
FINGERPRINT_KEY = "synthetic-legacy-key"


def _connect(path):
    return closing(sqlite3.connect(path))


def _columns(path, table):
    with _connect(path) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _version(path):
    with _connect(path) as conn:
        return conn.execute("PRAGMA user_version").fetchone()[0]


class SchemaCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="state-schema-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state.sqlite"

    def _baseline_database(self):
        """A review-fixes database: version 0 and the pre-column content table."""
        legacy_content_sources = "\n".join(
            line for line in SCHEMA[6].splitlines()
            if "canonical_url" not in line and "cache_scope" not in line and "truncated" not in line
        )
        statements = list(SCHEMA)
        statements[6] = legacy_content_sources
        with _connect(self.path) as conn, conn:
            for statement in statements:
                conn.execute(statement)
            conn.execute(
                "INSERT INTO content_objects(content_hash, content, content_bytes, created_at, last_access_at) "
                "VALUES('hash-1', ?, 4, 't0', 't0')",
                (BODY,),
            )
            conn.execute(
                "INSERT INTO content_sources(source_id, content_hash, created_at, expires_at) "
                "VALUES('src-1', 'hash-1', 't0', '2999-01-01T00:00:00+00:00')"
            )
            conn.execute(
                "INSERT INTO key_state(provider, key_id, key_fingerprint, status, created_at, updated_at) "
                "VALUES('exa', ?, '前4...后4 (deadbeef)', 'active', 't0', 't0')",
                (key_id_for("exa", FINGERPRINT_KEY),),
            )
            conn.execute(
                "INSERT INTO site_scraper_stats(site, scraper, success_count, manually_pinned, "
                "manual_priority, created_at, updated_at) VALUES('example.com', 'jina', 3, 1, 0, 't0', 't0')"
            )

    def test_baseline_database_migrates_without_losing_data(self):
        self._baseline_database()
        store = StateStore(self.path)

        self.assertEqual(_version(self.path), STATE_SCHEMA_VERSION)
        cached = ContentStore(store).get("src-1")
        self.assertEqual(cached["content"], BODY)
        self.assertEqual(cached["content_hash"], "hash-1")

        with store.connect() as conn:
            row = conn.execute("SELECT * FROM key_state").fetchone()
        self.assertEqual(row["key_fingerprint"], key_fingerprint(FINGERPRINT_KEY))
        self.assertNotIn("前4", row["key_fingerprint"])

        stats = SiteScraperMemory(store).stats("example.com")
        self.assertEqual([(row["scraper"], row["success_count"], row["manually_pinned"]) for row in stats],
                         [("jina", 3, 1)])

    def test_source_branch_v1_database_gains_only_the_truncated_column(self):
        StateStore(self.path)
        with _connect(self.path) as conn, conn:
            conn.execute("ALTER TABLE content_sources DROP COLUMN truncated")
            conn.execute("PRAGMA user_version=1")
            conn.execute(
                "INSERT INTO content_objects(content_hash, content, content_bytes, created_at, last_access_at) "
                "VALUES('hash-1', ?, 4, 't0', 't0')",
                (BODY,),
            )
            conn.execute(
                "INSERT INTO content_sources(source_id, content_hash, created_at, expires_at, canonical_url, cache_scope) "
                "VALUES('src-1', 'hash-1', 't0', '2999-01-01T00:00:00+00:00', 'https://example.com', 'scope')"
            )
        self.assertNotIn("truncated", _columns(self.path, "content_sources"))

        StateStore(self.path)

        self.assertEqual(_version(self.path), 2)
        self.assertIn("truncated", _columns(self.path, "content_sources"))
        cached = ContentStore(StateStore(self.path)).get("src-1")
        self.assertEqual(cached["content"], BODY)
        with _connect(self.path) as conn:
            stored = conn.execute("SELECT truncated FROM content_sources WHERE source_id='src-1'").fetchone()[0]
        # Legacy v1 rows carry no evidence of acquisition truncation. The new
        # metadata defaults to False and is exposed without changing the body.
        self.assertEqual(stored, 0)
        self.assertFalse(cached["truncated"])

    def test_source_branch_v2_database_opens_unchanged(self):
        StateStore(self.path)
        with _connect(self.path) as conn, conn:
            conn.execute(
                "INSERT INTO content_objects(content_hash, content, content_bytes, created_at, last_access_at) "
                "VALUES('hash-1', ?, 4, 't0', 't0')",
                (BODY,),
            )
            conn.execute(
                "INSERT INTO content_sources(source_id, content_hash, created_at, expires_at, truncated) "
                "VALUES('src-1', 'hash-1', 't0', '2999-01-01T00:00:00+00:00', 1)"
            )
        before = _snapshot(self.path)

        StateStore(self.path)

        self.assertEqual(_version(self.path), 2)
        self.assertEqual(_snapshot(self.path), before)

    def test_reopening_is_idempotent(self):
        StateStore(self.path)
        self._write_marker()
        first = _snapshot(self.path)

        StateStore(self.path)
        StateStore(self.path)

        self.assertEqual(_snapshot(self.path), first)

    def test_future_version_with_current_layout_is_refused_unchanged(self):
        self._assert_future_version_refused()

    def test_future_version_missing_truncated_is_refused_not_repaired(self):
        # The reported hole: a future version whose layout is not a superset of
        # ours used to fall through the fast path and be migrated anyway.
        self._assert_future_version_refused(drop_truncated=True)

    def test_future_version_with_other_incompatible_layout_is_refused(self):
        self._assert_future_version_refused(extra_ddl="ALTER TABLE key_state DROP COLUMN invalid_strikes")

    def test_future_version_in_delete_mode_is_not_switched_to_wal(self):
        self._assert_future_delete_mode_untouched()

    def test_future_version_missing_column_in_delete_mode_is_not_switched_to_wal(self):
        self._assert_future_delete_mode_untouched(drop_truncated=True)

    def _assert_future_delete_mode_untouched(self, *, drop_truncated=False):
        """A future version is refused before the persistent journal-mode change.

        ``PRAGMA journal_mode`` writes the file immediately and cannot run
        inside a transaction, so it must not precede the locked version check.
        """
        StateStore(self.path)
        self._write_marker()
        with _connect(self.path) as conn, conn:
            conn.execute("PRAGMA journal_mode=DELETE")
            if drop_truncated:
                conn.execute("ALTER TABLE content_sources DROP COLUMN truncated")
            conn.execute("PRAGMA user_version=99")
        before = _snapshot(self.path)
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()

        with self.assertRaises(StateSchemaVersionError):
            StateStore(self.path)

        self.assertEqual(_snapshot(self.path), before)
        self.assertEqual(_version(self.path), 99)
        with _connect(self.path) as conn:
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "delete")
        # Every connection is closed, and nothing else writes this temp file.
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), digest)

    def _assert_future_version_refused(self, *, drop_truncated=False, extra_ddl=None):
        StateStore(self.path)
        self._write_marker()
        with _connect(self.path) as conn, conn:
            if drop_truncated:
                conn.execute("ALTER TABLE content_sources DROP COLUMN truncated")
            if extra_ddl:
                conn.execute(extra_ddl)
            conn.execute("PRAGMA user_version=99")
        before = _snapshot(self.path)

        with self.assertRaises(StateSchemaVersionError):
            StateStore(self.path)

        self.assertEqual(_snapshot(self.path), before)
        self.assertEqual(_version(self.path), 99)

    def _write_marker(self):
        with _connect(self.path) as conn, conn:
            conn.execute(
                "INSERT INTO content_objects(content_hash, content, content_bytes, created_at, last_access_at) "
                "VALUES('hash-1', 'marker', 6, 't0', 't0')"
            )


def _snapshot(path):
    """Schema shape plus stored rows, so a rewrite shows up as a difference."""
    with _connect(path) as conn:
        conn.row_factory = sqlite3.Row
        tables = [
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        schema = {
            table: [
                (row[1], row[2]) for row in conn.execute(f"PRAGMA table_info({table})")
            ]
            for table in tables
        }
        rows = {
            table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1")]
            for table in tables
        }
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    return version, schema, rows


if __name__ == "__main__":
    unittest.main()
