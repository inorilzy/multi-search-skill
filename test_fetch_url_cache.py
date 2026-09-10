import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from multi_search_mcp.src import service
from multi_search_mcp.src.search.capabilities import PROVIDER_CAPABILITIES
from multi_search_mcp.src.search.search_runner import ProviderSpec
from multi_search_mcp.src.state.content_store import ContentStore
from multi_search_mcp.src.state.state_store import StateStore


class FetchUrlCacheTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = StateStore(Path(temp.name) / "state.sqlite")
        self.url = "https://example.com/article"
        self.calls = []

    def scrape(self, url, **_kwargs):
        self.calls.append(url)
        return {"url": url, "markdown": "complete body " * 100, "via": "fake"}

    def fetch(self, **kwargs):
        keys = kwargs.pop("keys", {})
        return service.run_fetch_source(
            service.FetchSourceRequest(url=self.url, **kwargs), state_store=self.store,
            scraper=self.scrape, keys=keys, config={}, url_resolver=lambda _: ["93.184.216.34"],
        )

    def test_direct_urls_reuse_body_with_new_source_ids_and_original_expiry(self):
        first = self.fetch(max_chars=10)
        second = self.fetch(full_content=True)
        self.assertEqual(len(self.calls), 1)
        self.assertNotEqual(first["source_id"], second["source_id"])
        self.assertTrue(second["cache_hit"])
        self.assertEqual(first["expires_at"], second["expires_at"])
        self.assertGreater(len(second["body"]), 10)
        self.assertEqual(service.run_read_source(
            service.ReadSourceRequest(source_id=second["source_id"]), state_store=self.store,
        )["content"], second["body"])

    def test_expired_body_is_fetched_again(self):
        self.fetch()
        with self.store.connect() as conn:
            conn.execute("UPDATE content_sources SET expires_at = '2000-01-01T00:00:00+00:00'")
        second = self.fetch()
        self.assertFalse(second["cache_hit"])
        self.assertEqual(len(self.calls), 2)

    def test_backend_and_credential_contexts_do_not_share(self):
        for options in (
            {"backends": ["jina"]}, {"backends": ["exa"]},
            {"backends": ["exa"], "keys": {"exa": "synthetic-a"}},
            {"backends": ["exa"], "keys": {"exa": "synthetic-b"}},
        ):
            self.assertFalse(self.fetch(**options)["cache_hit"])
        self.assertEqual(len(self.calls), 4)
        rows = str(self.store.rows("SELECT * FROM content_sources"))
        self.assertNotIn("synthetic-a", rows)
        self.assertNotIn("synthetic-b", rows)

    def test_distinct_urls_do_not_share(self):
        self.fetch()
        self.url += "/other"
        self.assertFalse(self.fetch()["cache_hit"])
        self.assertEqual(len(self.calls), 2)

    def test_searches_reuse_body_across_responses(self):
        provider = ProviderSpec(name="brave", public_name="brave", call=lambda *_: [{
            "source": "brave", "url": self.url, "title": "Evidence",
            "description": "excerpt", "content_kind": "excerpt",
        }])
        def search():
            return service.run_search_web(
                service.SearchWebRequest(query="evidence", sources=["brave"], count=1),
                providers={"brave": provider}, state_store=self.store, scraper=self.scrape,
                keys={}, config={}, url_resolver=lambda _: ["93.184.216.34"],
            )
        first, second = search(), search()
        self.assertEqual(len(self.calls), 1)
        self.assertNotEqual(first["results"][0]["source_id"], second["results"][0]["source_id"])
        self.assertEqual(second["scrapes"][0]["via"], "content-store")
        cap = PROVIDER_CAPABILITIES["brave"]
        restricted = replace(cap, retention=replace(cap.retention, persist_body=False))
        with mock.patch.dict(PROVIDER_CAPABILITIES, {"brave": restricted}):
            third = search()
        self.assertEqual(len(self.calls), 2)
        self.assertIsNone(ContentStore(self.store).get(third["results"][0]["source_id"]))


if __name__ == "__main__":
    unittest.main()
