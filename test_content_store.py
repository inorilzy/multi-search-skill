import tempfile
import threading
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.state.content_store import ContentStore, ContentStoreError
from multi_search_mcp.src.state.state_store import StateStore


class _FakeClock:
    def __init__(self, start: datetime):
        self.current = start

    def now(self) -> datetime:
        return self.current

    def advance(self, *, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


class ContentStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.db_path = Path(self.tmpdir.name) / "state.sqlite"
        self.store = StateStore(self.db_path)
        self.clock = _FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))

    def make_store(
        self,
        *,
        ttl_seconds: int = 60,
        max_object_bytes: int = 1024,
        max_total_bytes: int = 4096,
    ) -> ContentStore:
        return ContentStore(
            self.store,
            ttl_seconds=ttl_seconds,
            max_object_bytes=max_object_bytes,
            max_total_bytes=max_total_bytes,
            clock=self.clock.now,
        )

    def test_put_get_round_trip_and_touch_last_access(self):
        cache = self.make_store()

        cache.put("source-1", "hello")
        before = self.store.rows("SELECT last_access_at FROM content_objects")[0]["last_access_at"]
        self.clock.advance(seconds=5)

        row = cache.get("source-1")
        after = self.store.rows("SELECT last_access_at FROM content_objects")[0]["last_access_at"]

        self.assertEqual(row["source_id"], "source-1")
        self.assertEqual(row["content"], "hello")
        self.assertEqual(row["content_bytes"], 5)
        self.assertGreater(after, before)

    def test_get_drops_expired_source(self):
        cache = self.make_store(ttl_seconds=10)
        cache.put("source-1", "hello")

        self.clock.advance(seconds=11)

        self.assertIsNone(cache.get("source-1"))
        self.assertEqual(self.store.rows("SELECT * FROM content_sources"), [])
        self.assertEqual(self.store.rows("SELECT * FROM content_objects"), [])

    def test_put_rejects_oversized_object(self):
        cache = self.make_store(max_object_bytes=4, max_total_bytes=10)

        with self.assertRaises(ContentStoreError):
            cache.put("source-1", "hello")

        self.assertEqual(self.store.rows("SELECT * FROM content_sources"), [])
        self.assertEqual(self.store.rows("SELECT * FROM content_objects"), [])

    def test_total_capacity_evicts_lru_object_and_sources(self):
        cache = self.make_store(max_object_bytes=10, max_total_bytes=8)

        cache.put("source-1", "1111")
        self.clock.advance(seconds=1)
        cache.put("source-2", "2222")
        self.clock.advance(seconds=1)
        self.assertEqual(cache.get("source-1")["content"], "1111")
        self.clock.advance(seconds=1)

        cache.put("source-3", "3333")

        self.assertIsNotNone(cache.get("source-1"))
        self.assertIsNone(cache.get("source-2"))
        self.assertIsNotNone(cache.get("source-3"))
        self.assertEqual(len(self.store.rows("SELECT * FROM content_objects")), 2)

    def test_shared_content_is_deduplicated_and_deleted_on_last_source(self):
        cache = self.make_store()

        first = cache.put("source-1", "shared")
        second = cache.put("source-2", "shared")

        self.assertEqual(first["content_hash"], second["content_hash"])
        self.assertEqual(len(self.store.rows("SELECT * FROM content_objects")), 1)
        self.assertEqual(len(self.store.rows("SELECT * FROM content_sources")), 2)

        self.assertEqual(cache.delete_source("source-1"), 1)
        self.assertEqual(len(self.store.rows("SELECT * FROM content_objects")), 1)
        self.assertEqual(cache.get("source-2")["content"], "shared")

        self.assertEqual(cache.delete_source("source-2"), 1)
        self.assertEqual(self.store.rows("SELECT * FROM content_objects"), [])

    def test_purge_expired_keeps_shared_object_until_last_live_source_expires(self):
        cache = self.make_store(ttl_seconds=60)

        cache.put("source-1", "shared")
        self.clock.advance(seconds=30)
        cache.put("source-2", "shared")
        self.clock.advance(seconds=31)

        removed = cache.purge_expired()

        self.assertEqual(removed, 1)
        self.assertIsNone(cache.get("source-1"))
        self.assertEqual(cache.get("source-2")["content"], "shared")
        self.assertEqual(len(self.store.rows("SELECT * FROM content_objects")), 1)

        self.clock.advance(seconds=30)

        self.assertEqual(cache.purge_expired(), 1)
        self.assertEqual(self.store.rows("SELECT * FROM content_objects"), [])

    def _run_competing_mutations(self, first, second):
        """Let another writer finish between an unprotected read and write."""
        original_connect = self.store.connect
        second_started = threading.Event()
        second_finished = threading.Event()
        errors = []
        workers = []
        launched = False

        def run_second():
            second_started.set()
            try:
                second()
            except Exception as exc:
                errors.append(exc)
            finally:
                second_finished.set()

        class ConnectionProxy:
            def __init__(inner, conn):
                inner.conn = conn

            def execute(inner, sql, parameters=()):
                cursor = inner.conn.execute(sql, parameters)
                if "SELECT content_hash FROM content_sources WHERE source_id = ?" not in sql:
                    return cursor

                class CursorProxy:
                    def fetchone(cursor_self):
                        nonlocal launched
                        row = cursor.fetchone()
                        if not launched:
                            launched = True
                            worker = threading.Thread(target=run_second)
                            workers.append(worker)
                            worker.start()
                            self.assertTrue(second_started.wait(2))
                            # A transaction serializes the second mutation. Without
                            # one, force its commit before the first mutation resumes.
                            if not inner.conn.in_transaction:
                                self.assertTrue(second_finished.wait(2))
                        return row

                return CursorProxy()

        @contextmanager
        def competing_connect():
            with original_connect() as conn:
                yield ConnectionProxy(conn)

        with mock.patch.object(self.store, "connect", competing_connect):
            try:
                first()
            finally:
                for worker in workers:
                    worker.join(3)
                    self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(launched)

    def assert_no_orphaned_objects(self):
        self.assertEqual(self.store.rows(
            "SELECT content_hash FROM content_objects WHERE content_hash NOT IN "
            "(SELECT content_hash FROM content_sources)"
        ), [])

    def test_competing_writes_keep_only_referenced_content(self):
        cache = self.make_store()
        self._run_competing_mutations(
            lambda: cache.put("source-1", "first"),
            lambda: cache.put("source-1", "second"),
        )

        self.assert_no_orphaned_objects()
        self.assertEqual(len(self.store.rows("SELECT * FROM content_sources")), 1)
        cache.delete_source("source-1")
        self.assertEqual(self.store.rows("SELECT * FROM content_objects"), [])

    def test_delete_competing_with_replacement_leaves_no_orphan(self):
        cache = self.make_store()
        cache.put("source-1", "original")
        self._run_competing_mutations(
            lambda: cache.delete_source("source-1"),
            lambda: cache.put("source-1", "replacement"),
        )

        self.assert_no_orphaned_objects()
        self.clock.advance(seconds=61)
        cache.purge_expired()
        self.assertEqual(self.store.rows("SELECT * FROM content_sources"), [])
        self.assertEqual(self.store.rows("SELECT * FROM content_objects"), [])

    def test_url_reuse_binds_new_source_without_extending_original_ttl(self):
        cache = self.make_store(ttl_seconds=60)
        first = cache.put("source-1", "body", canonical_url="https://example.com/a", cache_scope="direct:jina")
        self.clock.advance(seconds=20)

        reused = cache.reuse_for_url("source-2", canonical_url="https://example.com/a", cache_scope="direct:jina")

        self.assertEqual(reused["source_id"], "source-2")
        self.assertEqual(reused["content"], "body")
        self.assertEqual(reused["expires_at"], first["expires_at"])
        self.assertEqual(len(self.store.rows("SELECT * FROM content_objects")), 1)
        self.assertEqual(cache.get("source-2")["content_hash"], first["content_hash"])
        self.clock.advance(seconds=41)
        self.assertIsNone(cache.reuse_for_url("source-3", canonical_url="https://example.com/a", cache_scope="direct:jina"))
        self.assertEqual(self.store.rows("SELECT * FROM content_objects"), [])

    def test_url_reuse_respects_current_shorter_ttl_and_exact_scope(self):
        cache = self.make_store(ttl_seconds=60)
        cache.put("source-1", "body", canonical_url="https://example.com/a", cache_scope="direct:jina")
        self.clock.advance(seconds=10)
        short_cache = self.make_store(ttl_seconds=5)

        self.assertIsNone(short_cache.reuse_for_url("different-url", canonical_url="https://example.com/b", cache_scope="direct:jina"))
        self.assertIsNone(short_cache.reuse_for_url("different-scope", canonical_url="https://example.com/a", cache_scope="direct:exa"))
        reused = short_cache.reuse_for_url("source-2", canonical_url="https://example.com/a", cache_scope="direct:jina")
        self.assertEqual(reused["expires_at"], (self.clock.now() + timedelta(seconds=5)).isoformat())
        self.clock.advance(seconds=6)
        self.assertIsNone(cache.get("source-2"))
        self.assertIsNotNone(cache.get("source-1"))

    def test_url_reuse_replaces_existing_source_and_cleans_old_object(self):
        cache = self.make_store()
        cache.put("target", "old")
        cache.put("origin", "new", canonical_url="https://example.com/a", cache_scope="scope")

        cache.reuse_for_url("target", canonical_url="https://example.com/a", cache_scope="scope")

        self.assertEqual(cache.get("target")["content"], "new")
        self.assert_no_orphaned_objects()
        self.assertEqual(len(self.store.rows("SELECT * FROM content_objects")), 1)

    def test_unscoped_content_remains_readable_without_url_reuse(self):
        cache = self.make_store()
        cache.put("source-1", "legacy body")

        self.assertEqual(cache.get("source-1")["content"], "legacy body")
        self.assertIsNone(cache.reuse_for_url("source-2", canonical_url="https://example.com/a", cache_scope="scope"))

    def test_old_schema_migration_preserves_content_and_allows_scoped_writes(self):
        legacy_row = self.make_store().put("legacy", "existing body")
        with self.store.connect() as conn:
            conn.execute("DROP TABLE content_sources")
            conn.execute("CREATE TABLE content_sources (source_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL)")
            conn.execute(
                "INSERT INTO content_sources VALUES (?, ?, ?, ?)",
                ("legacy", legacy_row["content_hash"], self.clock.now().isoformat(), legacy_row["expires_at"]),
            )

        migrated = StateStore(self.db_path)
        cache = ContentStore(migrated, clock=self.clock.now)

        self.assertEqual(cache.get("legacy")["content"], "existing body")
        self.assertIsNone(cache.reuse_for_url("other", canonical_url="https://example.com/a", cache_scope="scope"))
        cache.put("fresh", "new body", canonical_url="https://example.com/a", cache_scope="scope")
        self.assertEqual(cache.reuse_for_url("reused", canonical_url="https://example.com/a", cache_scope="scope")["content"], "new body")

    def test_concurrent_old_schema_migrations_both_succeed(self):
        with self.store.connect() as conn:
            conn.execute("DROP TABLE content_sources")
            conn.execute("CREATE TABLE content_sources (source_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL)")
        original_connect = StateStore.connect
        started = threading.Event()
        finished = threading.Event()
        workers = []
        errors = []

        def migrate_second():
            started.set()
            try:
                StateStore(self.db_path)
            except Exception as exc:
                errors.append(exc)
            finally:
                finished.set()

        class ConnectionProxy:
            def __init__(inner, conn):
                inner.conn = conn

            def execute(inner, sql, parameters=()):
                cursor = inner.conn.execute(sql, parameters)
                if sql != "PRAGMA table_info(content_sources)":
                    return cursor

                class CursorProxy:
                    def fetchall(cursor_self):
                        rows = cursor.fetchall()
                        if not workers:
                            worker = threading.Thread(target=migrate_second)
                            workers.append(worker)
                            worker.start()
                            self.assertTrue(started.wait(2))
                            if not inner.conn.in_transaction:
                                self.assertTrue(finished.wait(2))
                        return rows

                return CursorProxy()

        @contextmanager
        def competing_connect(store):
            with original_connect(store) as conn:
                yield ConnectionProxy(conn)

        with mock.patch.object(StateStore, "connect", competing_connect):
            try:
                StateStore(self.db_path)
            finally:
                for worker in workers:
                    worker.join(3)
                    self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(workers)


if __name__ == "__main__":
    unittest.main()
