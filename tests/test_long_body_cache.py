"""Regression tests for long-body persistence and body-cache identity."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from multi_search_mcp.src import service
from multi_search_mcp.src.search.search_runner import ProviderSpec
from multi_search_mcp.src.state.content_store import (
    DEFAULT_MAX_OBJECT_BYTES,
    DEFAULT_MAX_TOTAL_BYTES,
    ContentStore,
    max_acquisition_chars,
)
from multi_search_mcp.src.state.state_store import StateStore

URL = "https://evidence.example/long-cjk"
# 90,000 CJK characters: 270,000 UTF-8 bytes, above the old 256 KiB object cap.
LONG_BODY = "# 长正文\n" + "中文正文" * 22_500 + "\n结尾"


class LongBodyCacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="long-body-cache-")
        self.addCleanup(temporary.cleanup)
        self.store = StateStore(Path(temporary.name) / "state.sqlite")
        self.scraper = mock.Mock(side_effect=self.scrape)

    @staticmethod
    def scrape(url, **kwargs):
        return {"url": url, "markdown": LONG_BODY[:kwargs["scrape_chars"]], "via": "fixture"}

    def search(self, keys):
        provider = ProviderSpec(name="brave", public_name="brave", call=lambda *_args: [{
            "source": "brave", "title": "长正文页面", "url": URL,
            "description": "中文摘要", "content_kind": "excerpt",
        }])
        return service.run_search_web(
            service.SearchWebRequest(query="长正文", sources=["brave"], count=1),
            providers={"brave": provider}, keys=keys, config={}, state_store=self.store,
            scraper=self.scraper,
        )

    def test_ninety_thousand_cjk_characters_persist_and_fetch_and_read_reuse_them(self):
        self.assertGreater(len(LONG_BODY.encode("utf-8")), 256 * 1024)
        self.assertLessEqual(len(LONG_BODY.encode("utf-8")), DEFAULT_MAX_OBJECT_BYTES)
        response = self.search({})
        self.assertEqual(response["errors"], [])
        page, hit = response["scrapes"][0], response["results"][0]
        self.assertTrue(page["persisted"])
        self.assertTrue(hit["body_persisted"])
        self.assertEqual(page["length"], len(LONG_BODY))

        fetched = service.run_fetch_source(
            service.FetchSourceRequest(source_id=hit["source_id"], full_content=True),
            state_store=self.store, scraper=self.scraper, keys={}, config={},
        )
        self.assertTrue(fetched["cache_hit"])
        self.assertTrue(fetched["persisted"])
        self.assertEqual(fetched["body"], LONG_BODY)

        read = service.run_read_source(
            service.ReadSourceRequest(source_id=hit["source_id"], offset=90_000, limit=100),
            state_store=self.store,
        )
        self.assertEqual(read["content"], LONG_BODY[90_000:90_100])
        self.assertEqual(read["content_length"], len(LONG_BODY))
        self.assertEqual(self.scraper.call_count, 1)

    def test_rotating_only_the_search_provider_key_keeps_the_body_reusable(self):
        first = self.search({"brave": "synthetic-search-key-a"})
        second = self.search({"brave": "synthetic-search-key-b"})

        self.assertEqual(first["errors"], [])
        self.assertEqual(second["errors"], [])
        self.assertNotEqual(first["results"][0]["source_id"], second["results"][0]["source_id"])
        self.assertEqual(second["scrapes"][0]["via"], "content-store")
        self.assertTrue(second["scrapes"][0]["persisted"])
        self.assertEqual(self.scraper.call_count, 1)

    def test_default_cache_total_accommodates_several_max_size_objects(self):
        cache = ContentStore(self.store)
        bodies = [f"{index}" + "x" * (DEFAULT_MAX_OBJECT_BYTES - 1) for index in range(3)]
        for index, body in enumerate(bodies):
            cache.put(f"source-{index}", body)

        self.assertGreaterEqual(DEFAULT_MAX_TOTAL_BYTES, DEFAULT_MAX_OBJECT_BYTES * 20)
        self.assertEqual(len(self.store.rows("SELECT * FROM content_objects")), 3)
        for index, body in enumerate(bodies):
            self.assertEqual(cache.get(f"source-{index}")["content"], body)

    def test_character_acquisition_bound_always_fits_the_byte_budget(self):
        self.assertEqual(max_acquisition_chars(), DEFAULT_MAX_OBJECT_BYTES // 4)
        self.assertLessEqual(max_acquisition_chars(1000), 250)
