"""SOV2EX integration with source selection, RRF, and the body cache."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from multi_search_mcp.src.search.capabilities import PROVIDER_CAPABILITIES, ScrapePolicy
from multi_search_mcp.src.search.registry import build_provider_registry
from multi_search_mcp.src.search.resolve import _resolve_sources
from multi_search_mcp.src.search.search_runner import (
    SearchContext,
    SearchRunnerConfig,
    resolve_route,
)
from multi_search_mcp.src.service import (
    FetchSourceRequest,
    ReadSourceRequest,
    SearchWebRequest,
    _run_search_candidates,
    run_fetch_source,
    run_read_source,
    run_search_web,
)
from multi_search_mcp.src.state.content_store import ContentStore
from multi_search_mcp.src.state.state_store import StateStore


def topic(topic_id, body, *, score=1):
    return {
        "_id": str(topic_id),
        "_score": score,
        "_source": {
            "id": topic_id,
            "title": f"Python topic {topic_id}",
            "content": body,
            "created": "2026-09-07T07:40:48",
            "member": "test-member",
            "node": 90,
            "replies": 2,
        },
        "highlight": {"content": ["<em>Python</em> excerpt"]},
    }


def api_response(hits):
    return io.BytesIO(json.dumps({"took": 7, "total": len(hits), "hits": hits}).encode())


class V2EXIntegrationTests(unittest.TestCase):
    def test_v2ex_uses_an_independent_count_and_no_firecrawl_key(self):
        cfg = SearchRunnerConfig(
            route="default", counts={"v2ex": 7}, timeout=10,
            serpapi_engine="google_light", keys={},
        )
        ctx = SearchContext(source="v2ex", timeout=4, deadline=100, keys={})
        with mock.patch(
            "multi_search_mcp.src.search.registry.search_v2ex", autospec=True, return_value=[]
        ) as search, mock.patch(
            "multi_search_mcp.src.search.registry.search_firecrawl",
            side_effect=AssertionError("V2EX must not call Firecrawl"),
        ):
            spec = build_provider_registry()["v2ex"]
            self.assertIsNone(spec.key_name)
            self.assertEqual(spec.call("python", cfg, ctx, None), [])
        search.assert_called_once_with("python", 7, timeout=4)
        self.assertEqual(PROVIDER_CAPABILITIES["v2ex"].count_key, "v2ex")
        self.assertIsNone(PROVIDER_CAPABILITIES["v2ex"].operation.key_name)
        self.assertFalse(PROVIDER_CAPABILITIES["v2ex"].output.returns_content)
        self.assertEqual(PROVIDER_CAPABILITIES["v2ex"].scrape_policy, ScrapePolicy.CANDIDATE)

    def test_only_all_and_explicit_source_selection_include_v2ex(self):
        self.assertEqual(_resolve_sources("default", ["v2ex"]), {"v2ex"})
        self.assertIn("v2ex", resolve_route("all"))
        self.assertEqual(resolve_route("default"), {
            "brave", "parallel", "tavily", "exa", "serpapi", "firecrawl", "baidu",
        })
        self.assertEqual(resolve_route("fast"), {"baidu", "tavily", "firecrawl", "exa"})
        self.assertEqual(resolve_route("dev"), {"stackoverflow", "github_repos", "hackernews"})
        self.assertEqual(resolve_route("social"), {"twitter"})
        with self.assertRaisesRegex(ValueError, "unknown route: cn-community"):
            _resolve_sources("cn-community", None)

    def test_candidate_stage_discards_all_indexed_bodies_and_does_not_cache(self):
        hits = [topic(i, f"INDEXED BODY MUST NOT BE USED: {i}") for i in range(101, 121)]
        query_runs = []
        with tempfile.TemporaryDirectory() as temp, mock.patch(
            "multi_search_mcp.src.search.searchers.v2ex.urlopen_retry",
            return_value=api_response(hits),
        ), mock.patch(
            "multi_search_mcp.src.service.load_keys",
            side_effect=AssertionError("test must not read user keys"),
        ):
            store = StateStore(Path(temp) / "state.sqlite")
            response = _run_search_candidates(
                SearchWebRequest(query="python", sources=["v2ex"], count=20),
                keys={}, config={}, state_store=store,
                query_runs_observer=query_runs.extend,
            )
            self.assertEqual(response["errors"], [])
            self.assertEqual(len(query_runs[0][1]), 20)
            for row in query_runs[0][1]:
                self.assertNotIn("scraped_content", row)
                self.assertNotIn("body", row)
                self.assertEqual(row["content_kind"], "excerpt")
            self.assertEqual(len(response["results"]), 15)
            for row in response["results"]:
                self.assertEqual(row["content"], "Python excerpt")
                self.assertNotIn("body", row)
                self.assertIsNone(ContentStore(store).get(row["source_id"]))
            with store.connect() as connection:
                self.assertEqual(connection.execute("SELECT count(*) FROM content_objects").fetchone()[0], 0)

    def test_search_fetches_only_rrf_top_fifteen_and_caches_fetched_bodies(self):
        hits = [topic(i, f"INDEXED BODY MUST NOT BE USED: {i}", score=i) for i in range(101, 121)]
        expected_urls = [f"https://www.v2ex.com/t/{i}" for i in range(101, 116)]
        fetched_bodies = {url: f"# Fetched {url}\n\nFresh topic body with a needle at the end." for url in expected_urls}

        def scrape(url, **_kwargs):
            self.assertIn(url, expected_urls, "discarded candidates must not be fetched")
            return {"url": url, "markdown": fetched_bodies[url], "via": "fake"}

        scraper = mock.Mock(side_effect=scrape)
        with tempfile.TemporaryDirectory() as temp, mock.patch(
            "multi_search_mcp.src.search.searchers.v2ex.urlopen_retry",
            return_value=api_response(hits),
        ) as http, mock.patch(
            "multi_search_mcp.src.service.load_keys",
            side_effect=AssertionError("test must not read user keys"),
        ), mock.patch(
            "multi_search_mcp.src.search.registry.search_firecrawl",
            side_effect=AssertionError("V2EX search must not call Firecrawl"),
        ):
            store = StateStore(Path(temp) / "state.sqlite")
            response = run_search_web(
                SearchWebRequest(query="python", sources=["v2ex"], count=20),
                keys={}, config={}, state_store=store, scraper=scraper,
                url_resolver=lambda _host: ["93.184.216.34"], scrape_chars=12,
            )
            self.assertEqual(response["errors"], [])
            self.assertEqual(response["diagnostics"]["active_sources"], ["v2ex"])
            rows = response["results"]
            self.assertEqual([row["url"] for row in rows], expected_urls)
            self.assertEqual(scraper.call_count, 15)
            self.assertCountEqual([call.args[0] for call in scraper.call_args_list], expected_urls)
            for rank, row in enumerate(rows, start=1):
                body = fetched_bodies[row["url"]]
                self.assertAlmostEqual(row["rrf_score"], 1 / (40 + rank))
                self.assertEqual(row["content"], "Python excerpt")
                self.assertEqual(row["content_kind"], "excerpt")
                self.assertEqual(response["scrapes"][rank - 1]["markdown"], body[:12])
                self.assertNotIn("body", row)
                self.assertEqual(row["body_backend"], "fake")
                self.assertTrue(row["body_truncated"])
                self.assertEqual(ContentStore(store).get(row["source_id"])["content"], body)

            fetched = run_fetch_source(
                FetchSourceRequest(source_id=rows[0]["source_id"]),
                state_store=store, scraper=scraper, keys={}, config={},
                url_resolver=lambda _host: ["93.184.216.34"],
            )
            self.assertTrue(fetched["cache_hit"])
            self.assertEqual(fetched["body"], fetched_bodies[expected_urls[0]])
            self.assertEqual(scraper.call_count, 15)
            read = run_read_source(
                ReadSourceRequest(source_id=rows[0]["source_id"], keyword="needle", limit=6),
                state_store=store,
            )
            self.assertEqual(read["content"], "needle")

        http.assert_called_once()
        request = http.call_args.args[0]
        parsed = urlsplit(request.full_url)
        self.assertEqual(parsed.hostname, "www.sov2ex.com")
        self.assertEqual(parsed.path, "/api/search")
        params = parse_qs(parsed.query)
        self.assertEqual(params["q"], ["python"])
        self.assertEqual(params["size"], ["20"])

    def test_search_without_state_still_fetches_url_instead_of_indexed_body(self):
        body = "Freshly fetched body without SQLite state."
        scraper = mock.Mock(return_value={"markdown": body, "via": "fake"})
        with mock.patch(
            "multi_search_mcp.src.search.searchers.v2ex.urlopen_retry",
            return_value=api_response([topic(103, "INDEXED BODY MUST NOT BE USED")]),
        ):
            result = run_search_web(
                SearchWebRequest(query="python", sources=["v2ex"], use_state=False),
                keys={}, config={}, scraper=scraper,
                url_resolver=lambda _host: ["93.184.216.34"],
            )
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["scrapes"][0]["markdown"], body)
        self.assertEqual(result["results"][0]["body_backend"], "fake")
        scraper.assert_called_once()
        self.assertEqual(scraper.call_args.args[0], "https://www.v2ex.com/t/103")

    def test_missing_indexed_body_fetches_topic_url_after_rrf(self):
        scraper = mock.Mock(return_value={"markdown": "Fetched topic body", "via": "fake"})
        with mock.patch(
            "multi_search_mcp.src.search.searchers.v2ex.urlopen_retry",
            return_value=api_response([topic(104, "")]),
        ):
            result = run_search_web(
                SearchWebRequest(query="python", sources=["v2ex"], use_state=False),
                keys={}, config={}, scraper=scraper,
                url_resolver=lambda _host: ["93.184.216.34"],
            )
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["results"][0]["content"], "Python excerpt")
        self.assertEqual(result["scrapes"][0]["markdown"], "Fetched topic body")
        self.assertAlmostEqual(result["results"][0]["rrf_score"], 1 / 41)
        scraper.assert_called_once()
        self.assertEqual(scraper.call_args.args[0], "https://www.v2ex.com/t/104")


if __name__ == "__main__":
    unittest.main()
