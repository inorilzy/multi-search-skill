import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
