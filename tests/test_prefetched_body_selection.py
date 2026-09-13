import unittest
from contextlib import ExitStack
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from itertools import product
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from multi_search_mcp.src import service
from multi_search_mcp.src.search.capabilities import PROVIDER_CAPABILITIES, RetentionPolicy
from multi_search_mcp.src.search.search_runner import ProviderSpec
from multi_search_mcp.src.state.content_store import ContentStore
from multi_search_mcp.src.state.source_registry import SourceRegistry
from multi_search_mcp.src.state.state_store import StateStore


URL = "https://evidence.example/article"


def _row(source, body, *, url=URL):
    return {
        "source": source, "title": "Evidence", "url": url,
        "description": "search excerpt", "content_kind": "body",
        "scraped_content": body,
    }


def _providers(query_rows):
    def provider(source, rows):
        return ProviderSpec(
            name=source, public_name=source,
            call=lambda query, _config, _context, _key: [dict(row) for row in rows[query]],
        )

    return {source: provider(source, rows) for source, rows in query_rows.items()}


class PrefetchedBodySelectionTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        temp = self.stack.enter_context(TemporaryDirectory(prefix="prefetched-body-"))
        self.store = StateStore(Path(temp) / "state.sqlite")
        self.scraper = mock.Mock(side_effect=AssertionError("unexpected scrape"))
        self.stack.enter_context(mock.patch.object(service, "load_keys", side_effect=AssertionError("unexpected keys")))
        self.stack.enter_context(mock.patch("socket.getaddrinfo", side_effect=AssertionError("unexpected DNS")))
        self.stack.enter_context(mock.patch("socket.socket.connect", side_effect=AssertionError("unexpected connection")))

    def _search(self, query_rows, *, use_state, queries=("primary",), expected_errors=0, **options):
        response = service.run_search_web(
            service.SearchWebRequest(
                query=queries[0], expand=list(queries[1:]), sources=list(query_rows),
                use_state=use_state,
            ),
            providers=_providers(query_rows), keys={}, config={}, state_store=self.store,
            scraper=self.scraper, url_resolver=lambda _host: ["93.184.216.34"],
            **options,
        )
        self.assertEqual(len(response["errors"]), expected_errors, response["errors"])
        self.scraper.assert_not_called()
        return response

    def _fetch(self, source_id, **options):
        return service.run_fetch_source(
            service.FetchSourceRequest(source_id=source_id, full_content=True),
            state_store=self.store, keys={}, config={}, scraper=self.scraper,
            url_resolver=lambda _host: ["93.184.216.34"], **options,
        )

    def test_equal_bodies_across_queries_match_with_and_without_state(self):
        rows = {"twitter": {
            "primary": [_row("twitter", "Alpha")],
            "variant": [_row("twitter", "Omega")],
        }}
        without = self._search(rows, use_state=False, queries=("primary", "variant"))
        with_state = self._search(rows, use_state=True, queries=("primary", "variant"))
        self.assertEqual(without["scrapes"][0]["markdown"], with_state["scrapes"][0]["markdown"])
        self.assertEqual(with_state["scrapes"][0]["markdown"], "Alpha")

    def test_equal_bodies_across_providers_use_provider_then_body_order(self):
        rows = {
            "exa": {"primary": [_row("exa", "Alpha")]},
            "tavily": {"primary": [_row("tavily", "Omega")]},
        }
        without = self._search(rows, use_state=False)
        with_state = self._search(rows, use_state=True)
        self.assertEqual(without["scrapes"][0]["markdown"], with_state["scrapes"][0]["markdown"])
        self.assertEqual(with_state["scrapes"][0]["markdown"], "Alpha")

    def test_provider_order_precedes_body_text_for_equal_lengths(self):
        rows = {
            "exa": {"primary": [_row("exa", "Omega")]},
            "tavily": {"primary": [_row("tavily", "Alpha")]},
        }
        for use_state in (False, True):
            with self.subTest(use_state=use_state):
                response = self._search(rows, use_state=use_state)
                self.assertEqual(response["scrapes"][0]["markdown"], "Omega")

    def test_selection_is_independent_of_query_provider_and_duplicate_row_order(self):
        # Fragment variants identify the same canonical URL. Every source/query
        # votes for just this hit, so changing input order cannot change its RRF.
        baseline_score = None
        for use_state, reverse_queries, reverse_providers, reverse_rows in product((False, True), repeat=4):
            with self.subTest(state=use_state, queries=reverse_queries,
                              providers=reverse_providers, rows=reverse_rows):
                queries = ("primary", "variant")
                sources = ("exa", "tavily")
                bodies = ("Omega", "Alpha")
                if reverse_queries:
                    queries = queries[::-1]
                if reverse_providers:
                    sources = sources[::-1]
                if reverse_rows:
                    bodies = bodies[::-1]
                rows = {source: {query: [
                    _row(source, body, url=URL + "#" + body) for body in bodies
                ] for query in queries} for source in sources}
                response = self._search(rows, use_state=use_state, queries=queries)
                self.assertEqual(response["scrapes"][0]["markdown"], "Alpha")
                self.assertEqual(response["results"][0]["canonical_url"], URL)
                self.assertEqual(response["diagnostics"]["raw_result_count"], 8)
                score = response["results"][0]["rrf_score"]
                if baseline_score is None:
                    baseline_score = score
                self.assertEqual(score, baseline_score)

    def test_longest_body_wins_before_provider_and_text_ties(self):
        rows = {
            "exa": {"primary": [_row("exa", "Alpha")]},
            "tavily": {"primary": [_row("tavily", "longest body")]},
        }
        for use_state in (False, True):
            with self.subTest(use_state=use_state):
                response = self._search(rows, use_state=use_state)
                self.assertEqual(response["scrapes"][0]["markdown"], "longest body")

    def test_preview_cached_full_body_and_later_fetch_read_share_selection(self):
        body = "Alpha " + "full evidence " * 20 + "NEEDLE tail"
        rows = {"twitter": {
            "primary": [_row("twitter", body)],
            "variant": [_row("twitter", "Omega" + body[5:])],
        }}
        hashes = set()
        # A second response against the same DB sees the same full body; changing
        # preview size must neither replace it with Omega nor shorten storage.
        for preview_chars in (3, 100):
            with self.subTest(preview_chars=preview_chars):
                without = self._search(rows, use_state=False, queries=("primary", "variant"),
                                       scrape_chars=preview_chars)
                response = self._search(rows, use_state=True, queries=("primary", "variant"),
                                        scrape_chars=preview_chars)
                hit = response["results"][0]
                page = response["scrapes"][0]
                self.assertEqual(page["markdown"], body[:preview_chars])
                self.assertEqual(page["markdown"], without["scrapes"][0]["markdown"])
                self.assertTrue(page["truncated"])
                self.assertEqual(page["length"], len(body))
                self.assertEqual((page["preview_start"], page["preview_end"]), (0, preview_chars))
                self.assertNotIn("body", hit)
                self.assertEqual(hit["content"], "search excerpt")
                cached = ContentStore(self.store).get(hit["source_id"])
                self.assertEqual(cached["content"], body)
                hashes.add(cached["content_hash"])
                full = self._fetch(hit["source_id"])
                self.assertTrue(full["cache_hit"])
                self.assertEqual(full["body"], body)
                self.assertFalse(full["truncated"])
                read = service.run_read_source(
                    service.ReadSourceRequest(source_id=hit["source_id"], keyword="NEEDLE"),
                    state_store=self.store,
                )
                self.assertEqual(read["content"], "NEEDLE tail")
                self.assertEqual(read["content_hash"], full["content_hash"])
                self.assertEqual(read["content_length"], len(body))
        self.assertEqual(len(hashes), 1)

    def test_hot_source_cache_wins_until_its_original_expiry(self):
        now = datetime.now(timezone.utc)

        def cache(store, **options):
            return ContentStore(store, clock=lambda: now, **options)

        rows = {"twitter": {"primary": [_row("twitter", "Alpha")]}}
        with mock.patch.object(service, "ContentStore", side_effect=cache):
            response = self._search(rows, use_state=True)
            source_id = response["results"][0]["source_id"]
            stored = cache(self.store).get(source_id)
            now += timedelta(seconds=10)
            hot = self._fetch(source_id, prefetched_body="new upstream body")
            self.assertEqual(hot["body"], "Alpha")
            self.assertTrue(hot["cache_hit"])
            self.assertEqual(hot["expires_at"], stored["expires_at"])
            now = datetime.fromisoformat(stored["expires_at"]) + timedelta(seconds=1)
            fresh = self._fetch(source_id, prefetched_body="new upstream body")
            self.assertFalse(fresh["cache_hit"])
            self.assertEqual(fresh["body"], "new upstream body")

    def test_mixed_source_retention_does_not_change_the_selected_body(self):
        rows = {
            "exa": {"primary": [_row("exa", "Alpha")]},
            "tavily": {"primary": [_row("tavily", "Omega")]},
        }
        # Even the losing provider constrains persistence of the shared hit.
        for persist_search in (True, False):
            with self.subTest(persist_search=persist_search):
                restricted = replace(PROVIDER_CAPABILITIES["tavily"], retention=RetentionPolicy(
                    persist_search_result=persist_search, persist_content=False, persist_body=False,
                ))
                with mock.patch.dict(PROVIDER_CAPABILITIES, {"tavily": restricted}):
                    without = self._search(rows, use_state=False)
                    response = self._search(rows, use_state=True)
                    self.assertEqual(response["scrapes"][0]["markdown"], "Alpha")
                    self.assertEqual(response["scrapes"][0]["markdown"], without["scrapes"][0]["markdown"])
                    source_id = response["results"][0]["source_id"]
                    self.assertIsNone(ContentStore(self.store).get(source_id))
                    record = SourceRegistry(self.store).get(source_id)
                    if persist_search:
                        self.assertEqual(record["content"], "")
                    else:
                        self.assertIsNone(record)
                    with self.assertRaisesRegex(ValueError, "missing or expired"):
                        service.run_read_source(service.ReadSourceRequest(source_id=source_id),
                                                state_store=self.store)

    def test_mixed_source_ttl_uses_the_shortest_retention(self):
        rows = {
            "exa": {"primary": [_row("exa", "Alpha")]},
            "tavily": {"primary": [_row("tavily", "Omega")]},
        }
        restricted = replace(PROVIDER_CAPABILITIES["tavily"], retention=RetentionPolicy(max_ttl_seconds=30))
        before = datetime.now(timezone.utc)
        with mock.patch.dict(PROVIDER_CAPABILITIES, {"tavily": restricted}):
            response = self._search(rows, use_state=True)
        after = datetime.now(timezone.utc)
        source_id = response["results"][0]["source_id"]
        for record in (ContentStore(self.store).get(source_id), SourceRegistry(self.store).get(source_id)):
            expires = datetime.fromisoformat(record["expires_at"])
            self.assertGreaterEqual(expires, before + timedelta(seconds=30))
            self.assertLessEqual(expires, after + timedelta(seconds=30))

    def test_oversize_selected_body_is_rejected_without_storing_a_shorter_alternative(self):
        # Limits apply to UTF-8 bytes, not the one-character response preview.
        rows = {"twitter": {"primary": [
            _row("twitter", "证据" * 3), _row("twitter", "Alpha"),
        ]}}
        with mock.patch.object(service, "ContentStore", side_effect=lambda store, **options: ContentStore(
            store, max_object_bytes=10, **options,
        )):
            response = self._search(rows, use_state=True, scrape_chars=1, expected_errors=1)
        self.assertIn("exceeds max object bytes", response["errors"][0]["error"])
        self.assertEqual(len(response["diagnostics"]["content_store_errors"]), 1)
        self.assertIsNone(ContentStore(self.store).get(response["results"][0]["source_id"]))

    def test_total_capacity_keeps_eviction_without_changing_selection(self):
        rows = {"twitter": {"primary": [
            _row("twitter", "Alpha", url=URL + "/first"),
            _row("twitter", "Omega", url=URL + "/second"),
        ]}}
        with mock.patch.object(service, "ContentStore", side_effect=lambda store, **options: ContentStore(
            store, max_total_bytes=5, **options,
        )):
            response = self._search(rows, use_state=True, scrape_concurrency=1)
        self.assertEqual([page["markdown"] for page in response["scrapes"]], ["Alpha", "Omega"])
        self.assertEqual(len(response["results"]), 2)
        self.assertIsNone(ContentStore(self.store).get(response["results"][0]["source_id"]))
        self.assertEqual(ContentStore(self.store).get(response["results"][1]["source_id"])["content"], "Omega")
        with self.store.connect() as conn:
            total_bytes = conn.execute("SELECT SUM(content_bytes) FROM content_objects").fetchone()[0]
        self.assertEqual(total_bytes, 5)


if __name__ == "__main__":
    unittest.main()
