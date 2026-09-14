"""Behavioral regressions reproduced during the 2026-09-05 architecture audit."""
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from multi_search_mcp.src import service
from multi_search_mcp.src.search.search_runner import ProviderSpec
from multi_search_mcp.src.state.content_store import ContentStore, ContentStoreError, DEFAULT_MAX_OBJECT_BYTES
from multi_search_mcp.src.state.source_registry import SourceRegistry
from multi_search_mcp.src.state.state_store import StateStore


class ContentFlowRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = StateStore(Path(self.temp.name) / "state.sqlite")
        self.fetch_options = dict(
            state_store=self.store, keys={}, config={},
            url_resolver=lambda _host: ["93.184.216.34"],
        )

    def search(self, row):
        name = row["source"]
        provider = ProviderSpec(name=name, public_name=name, call=lambda *_args: [row])
        return service._run_search_candidates(
            service.SearchWebRequest("evidence", sources=[name], count=1),
            providers={name: provider}, keys={}, config={}, state_store=self.store,
        )["results"][0]

    def test_short_preview_preserves_body_for_larger_fetch_and_read(self):
        body = "x" * 1000
        calls = []

        def scraper(url, **_kwargs):
            calls.append(url)
            return {"url": url, "markdown": body, "length": len(body), "via": "fake"}

        first = service.run_fetch_source(
            service.FetchSourceRequest(url="https://evidence.example/article", max_chars=10),
            scraper=scraper, **self.fetch_options,
        )
        second = service.run_fetch_source(
            service.FetchSourceRequest(source_id=first["source_id"], max_chars=1000),
            scraper=scraper, **self.fetch_options,
        )
        rest = service.run_read_source(
            service.ReadSourceRequest(first["source_id"], offset=10, limit=1000),
            state_store=self.store,
        )
        self.assertEqual(first["body"], body[:10])
        self.assertTrue(first["truncated"])
        self.assertEqual(second["body"], body)
        self.assertTrue(second["cache_hit"])
        self.assertFalse(second["truncated"])
        self.assertEqual(rest["content"], body[10:])
        self.assertEqual(rest["content_length"], 1000)
        self.assertEqual(len(calls), 1)

    def test_short_preview_does_not_bypass_content_store_capacity(self):
        def scraper(url, **_kwargs):
            return {"url": url, "markdown": "x" * (DEFAULT_MAX_OBJECT_BYTES + 1), "via": "fake"}

        with self.assertRaises(ContentStoreError):
            service.run_fetch_source(
                service.FetchSourceRequest(url="https://evidence.example/large", max_chars=10),
                scraper=scraper, **self.fetch_options,
            )
        self.assertEqual(self.store.rows("SELECT * FROM content_objects"), [])

    def test_backend_acquisition_limit_is_independent_of_preview_size(self):
        body = "complete acquired body" * 100

        def scraper(url, **kwargs):
            acquired = body[:kwargs["scrape_chars"]]
            return {"url": url, "markdown": acquired, "via": "bounded-backend"}

        first = service.run_fetch_source(
            service.FetchSourceRequest(url="https://evidence.example/bounded", max_chars=10),
            scraper=scraper, **self.fetch_options,
        )
        cached = ContentStore(self.store).get(first["source_id"])
        self.assertEqual(cached["content"], body)
        self.assertEqual(first["body"], body[:10])
        self.assertTrue(first["truncated"])

    def test_twitter_search_excerpt_is_not_cached_as_body(self):
        body = "Full post and replies"
        hit = self.search({
            "source": "twitter", "title": "Post", "url": "https://x.com/example/status/1",
            "description": "Post excerpt", "scraped_content": "",
            "content_kind": "excerpt",
        })
        self.assertFalse(hit["body_available"])
        self.assertNotIn(body, hit["content"])
        self.assertNotIn("body", hit)
        fetched = service.run_fetch_source(
            service.FetchSourceRequest(source_id=hit["source_id"]),
            scraper=lambda url, **_kwargs: {"url": url, "markdown": body, "via": "twitter"},
            **self.fetch_options,
        )
        self.assertEqual(fetched["body"], body)
        self.assertFalse(fetched["cache_hit"])
        self.assertEqual(ContentStore(self.store).get(hit["source_id"])["content"], body)

    def test_body_row_preserves_its_independent_excerpt(self):
        hit = self.search({
            "source": "baidu", "title": "Page", "url": "https://evidence.example/baidu",
            "description": "Useful excerpt", "scraped_content": "Full page body", "content_kind": "body",
        })
        self.assertEqual(hit["content"], "Useful excerpt")
        self.assertEqual(hit["content_kind"], "excerpt")
        self.assertTrue(hit["body_available"])
        self.assertEqual(ContentStore(self.store).get(hit["source_id"])["content"], "Full page body")

    def test_exa_highlights_are_not_cached_as_body(self):
        hit = self.search({
            "source": "exa", "title": "Page", "url": "https://evidence.example/excerpt",
            "description": "Only highlights", "scraped_content": "Only highlights", "content_kind": "excerpt",
        })
        self.assertEqual(hit["content"], "Only highlights")
        self.assertFalse(hit["body_available"])
        self.assertIsNone(ContentStore(self.store).get(hit["source_id"]))


class SourceRegistryLifecycleRegressionTests(unittest.TestCase):
    def test_register_purges_expired_rows_without_deleting_live_sources(self):
        with TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.sqlite")
            start = datetime(2026, 9, 5, tzinfo=timezone.utc)
            expired = SourceRegistry(store, ttl_seconds=10, clock=lambda: start)
            live = SourceRegistry(store, ttl_seconds=100, clock=lambda: start)
            expired.register("old", [{"source_id": "expired", "url": "https://evidence.example/expired"}])
            live.register("live", [{"source_id": "live", "url": "https://evidence.example/live"}])

            current = SourceRegistry(store, clock=lambda: start + timedelta(seconds=10))
            current.register("new", [{"source_id": "new", "url": "https://evidence.example/new"}])
            rows = store.rows("SELECT source_id FROM search_sources ORDER BY source_id")
            self.assertEqual([row["source_id"] for row in rows], ["live", "new"])


if __name__ == "__main__":
    unittest.main()
