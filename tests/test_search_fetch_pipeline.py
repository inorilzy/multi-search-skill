import threading
import time
import unittest
from contextlib import ExitStack
from dataclasses import replace
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from multi_search_mcp.src import service
from multi_search_mcp.src.search.search_runner import ProviderSpec
from multi_search_mcp.src.search import capabilities
from multi_search_mcp.src.state import state_store
from multi_search_mcp.src.state.content_store import ContentStore
from multi_search_mcp.src.state.source_registry import SourceRegistry
from multi_search_mcp.src.state.state_store import StateStore


def _resolver(_host):
    return ["93.184.216.34"]


def _row(source, name):
    return {
        "source": source,
        "title": name,
        "url": f"https://evidence.example/{name}",
        "description": f"Search excerpt for {name}",
        "content_kind": "excerpt",
    }


def _provider(source, query_rows):
    def search(query, config, context, key):
        return [dict(row) for row in query_rows[query]]

    return ProviderSpec(name=source, public_name=source, call=search)


def _late_shared_rows(source, prefix):
    return [
        *[_row(source, f"{prefix}-{rank}") for rank in range(1, 16)],
        _row(source, "shared"),
        _row(source, f"{prefix}-tail"),
    ]


class SearchFetchPipelineTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        temp = self.stack.enter_context(TemporaryDirectory(prefix="search-fetch-pipeline-"))
        self.state_path = Path(temp) / "state.sqlite"
        self.stack.enter_context(mock.patch.object(state_store, "DEFAULT_STATE_PATH", self.state_path))
        self.stack.enter_context(mock.patch.object(service, "load_config", return_value={}))
        self.stack.enter_context(mock.patch.object(service, "load_keys", return_value={}))
        # A missing fake boundary must fail rather than reach the network.
        self.stack.enter_context(mock.patch("socket.getaddrinfo", side_effect=AssertionError("unexpected DNS")))
        self.stack.enter_context(mock.patch("socket.socket.connect", side_effect=AssertionError("unexpected connection")))

    def _search(self, providers, scraper, *, expand=None, use_state=False, **options):
        return service.run_search_web(
            service.SearchWebRequest(
                query="primary", sources=list(providers), count=30,
                expand=expand or [], use_state=use_state,
            ),
            providers=providers, keys={}, config={}, scraper=scraper,
            url_resolver=_resolver, **options,
        )

    def test_fuses_all_provider_ranks_then_fetches_only_final_fifteen(self):
        providers = {
            source: _provider(source, {"primary": _late_shared_rows(source, source)})
            for source in ("brave", "tavily")
        }
        fetched_urls = []

        def scraper(url, **kwargs):
            fetched_urls.append(url)
            return {"url": url, "markdown": f"Body for {url}", "via": "fake"}

        response = self._search(providers, scraper)
        hits = response["results"]
        self.assertEqual(response["errors"], [])
        self.assertEqual(response["diagnostics"]["raw_result_count"], 34)
        self.assertEqual(len(hits), 15)
        self.assertEqual(hits[0]["url"], "https://evidence.example/shared")
        self.assertEqual([rank["rank"] for rank in hits[0]["provider_ranks"]], [16, 16])
        self.assertAlmostEqual(hits[0]["rrf_score"], 2 / 56)
        self.assertCountEqual(fetched_urls, [hit["url"] for hit in hits])
        self.assertEqual(len(fetched_urls), 15)
        self.assertTrue(all(hit["body_available"] and "body" not in hit for hit in hits))
        self.assertTrue(all(row["markdown"] for row in response["scrapes"]))

    def test_query_rank_sixteen_can_reach_final_fetch_set(self):
        provider = _provider("brave", {
            query: _late_shared_rows("brave", query)
            for query in ("primary", "variant")
        })
        fetched_urls = []

        def scraper(url, **kwargs):
            fetched_urls.append(url)
            return {"url": url, "markdown": "body", "via": "fake"}

        response = self._search({"brave": provider}, scraper, expand=["variant"])
        first = response["results"][0]
        self.assertEqual(response["errors"], [])
        self.assertEqual(first["url"], "https://evidence.example/shared")
        self.assertEqual(first["query_ranks"], [
            {"query": "primary", "rank": 16}, {"query": "variant", "rank": 16},
        ])
        self.assertAlmostEqual(first["rrf_score"], 2 / 56)
        self.assertEqual(len(fetched_urls), 15)
        self.assertCountEqual(fetched_urls, [hit["url"] for hit in response["results"]])

    def test_fusion_keeps_business_urls_distinct_and_merges_tracking_aliases(self):
        first = {**_row("brave", "shared"), "url": "https://evidence.example/shared?ref_id=1"}
        duplicate = {**first, "source": "tavily", "url": first["url"] + "&utm_source=fixture",
                     "description": "A longer independent snippet"}
        second = {**first, "url": "https://evidence.example/shared?ref_id=2"}
        providers = {
            "brave": _provider("brave", {"primary": [first, second]}),
            "tavily": _provider("tavily", {"primary": [duplicate]}),
        }
        scraper = mock.Mock(side_effect=lambda url, **kwargs: {
            "url": url, "markdown": "Fetched body", "via": "fake",
        })
        response = self._search(providers, scraper)
        self.assertEqual(response["errors"], [])
        self.assertEqual(len(response["results"]), 2)
        shared = response["results"][0]
        self.assertEqual(shared["providers"], ["brave", "tavily"])
        self.assertEqual(shared["content"], duplicate["description"])
        self.assertEqual({hit["canonical_url"] for hit in response["results"]},
                         {first["url"], second["url"]})
        self.assertEqual(scraper.call_count, 2)

    def test_fetch_uses_search_title_and_configured_timeout(self):
        row = {**_row("brave", "article"), "title": "Real Article Title"}
        provider = _provider("brave", {"primary": [row]})
        for backend_title in (None, row["url"], "Backend Title"):
            with self.subTest(backend_title=backend_title):
                scraper = mock.Mock(return_value={
                    "url": row["url"], "title": backend_title, "markdown": "body", "via": "fake",
                })
                response = self._search({"brave": provider}, scraper, scrape_timeout=7)
                self.assertEqual(response["errors"], [])
                self.assertEqual(response["scrapes"][0]["title"], row["title"])
                self.assertEqual(response["results"][0]["title"], row["title"])
                self.assertGreater(scraper.call_args.kwargs["timeout"], 0)
                self.assertLessEqual(scraper.call_args.kwargs["timeout"], 7)

    def test_provider_answer_does_not_skip_its_url_or_video_results(self):
        rows = [
            {"source": "tavily_answer", "answer": "Synthesized answer"},
            _row("tavily", "article"),
            {**_row("tavily", "video"), "url": "https://youtube.com/watch?v=fixture"},
        ]
        scraper = mock.Mock(side_effect=lambda url, **kwargs: {
            "url": url, "markdown": "Fetched body", "via": "fake",
        })
        response = self._search({"tavily": _provider("tavily", {"primary": rows})}, scraper)
        self.assertEqual(response["errors"], [])
        self.assertEqual(len(response["results"]), 2)
        self.assertCountEqual([call.args[0] for call in scraper.call_args_list],
                              [row["url"] for row in rows[1:]])

    def test_keyless_fetch_tries_jina_before_anonymous_firecrawl(self):
        from multi_search_mcp.src.scrape import scrape

        calls = []

        def jina(url, *args, **kwargs):
            calls.append("jina")
            return {"url": url, "error": "fixture target unavailable"}

        def firecrawl(url, key, **kwargs):
            calls.append("firecrawl")
            self.assertFalse(key)
            return {"url": url, "markdown": "Anonymous body", "via": "firecrawl"}

        with (
            mock.patch.object(scrape, "_jina_anonymous_cooling_down", return_value=False),
            mock.patch.object(scrape, "scrape_url_jina", side_effect=jina),
            mock.patch.object(scrape, "scrape_url_firecrawl", side_effect=firecrawl),
            mock.patch.object(scrape, "scrape_url_exa", side_effect=AssertionError("unexpected Exa")),
            mock.patch.object(scrape, "scrape_url_tavily", side_effect=AssertionError("unexpected Tavily")),
        ):
            response = self._search(
                {"brave": _provider("brave", {"primary": [_row("brave", "anonymous")]})},
                scrape.scrape_url_smart,
            )
        self.assertEqual(response["errors"], [])
        self.assertEqual(calls, ["jina", "firecrawl"])
        self.assertEqual(response["scrapes"][0]["markdown"], "Anonymous body")

    def test_fetch_failure_keeps_position_and_explicit_diagnostics(self):
        rows = [_row("brave", name) for name in ("first", "broken", "third")]
        provider = _provider("brave", {"primary": rows})

        def scraper(url, **kwargs):
            if url.endswith("/broken"):
                return {"url": url, "error": "backend refused this URL"}
            return {"url": url, "markdown": f"Body for {url}", "via": "fake"}

        response = self._search({"brave": provider}, scraper)
        hits = response["results"]
        self.assertEqual([hit["url"] for hit in hits], [row["url"] for row in rows])
        self.assertTrue(response["scrapes"][0]["markdown"])
        self.assertTrue(response["scrapes"][2]["markdown"])
        self.assertNotIn("body", hits[1])
        self.assertIn("backend refused", hits[1]["body_error"])
        self.assertEqual(len(response["errors"]), 1)
        error = response["errors"][0]
        self.assertEqual(error["stage"], "fetch")
        self.assertEqual(error["source_id"], hits[1]["source_id"])
        self.assertEqual(error["url"], hits[1]["url"])
        self.assertEqual(response["diagnostics"]["body_success_count"], 2)
        self.assertEqual(response["scrapes"][1]["error"], hits[1]["body_error"])

    def test_body_length_and_fetch_completion_order_do_not_change_ranking(self):
        rows = [_row("brave", name) for name in ("short-first", "long-second", "third")]
        provider = _provider("brave", {"primary": rows})
        second_finished = threading.Event()
        completed = []

        def scraper(url, **kwargs):
            if url.endswith("/short-first"):
                if not second_finished.wait(timeout=2):
                    raise AssertionError("second fetch did not run concurrently")
                body = "tiny"
            elif url.endswith("/long-second"):
                body = "large body " * 2000
            else:
                body = "third body"
            completed.append(url)
            if url.endswith("/long-second"):
                second_finished.set()
            return {"url": url, "markdown": body, "via": "fake"}

        response = self._search({"brave": provider}, scraper, scrape_concurrency=3)
        hits = response["results"]
        self.assertEqual(response["errors"], [])
        self.assertEqual([hit["url"] for hit in hits], [row["url"] for row in rows])
        self.assertLess(completed.index(rows[1]["url"]), completed.index(rows[0]["url"]))
        self.assertGreater(len(response["scrapes"][1]["markdown"]), len(response["scrapes"][0]["markdown"]))
        self.assertGreater(hits[0]["rrf_score"], hits[1]["rrf_score"])

    def test_search_body_cache_keeps_full_text_beyond_preview(self):
        provider = _provider("brave", {"primary": [_row("brave", "long-document")]})
        body = "preview text " * 1000 + "NEEDLE beyond preview and still cached"
        scraper = mock.Mock(side_effect=lambda url, **kwargs: {
            "url": url, "markdown": body, "via": "fake",
        })
        response = self._search({"brave": provider}, scraper, use_state=True, scrape_chars=32)
        hit = response["results"][0]
        self.assertEqual(response["errors"], [])
        self.assertEqual(response["scrapes"][0]["markdown"], body[:32])
        self.assertTrue(hit["body_truncated"])
        self.assertEqual(scraper.call_count, 1)
        self.assertGreater(scraper.call_args.kwargs["scrape_chars"], len(body))
        store = StateStore(self.state_path)
        self.assertEqual(SourceRegistry(store).get(hit["source_id"])["url"], hit["url"])
        excerpt = service.run_read_source(
            service.ReadSourceRequest(source_id=hit["source_id"], keyword="NEEDLE", limit=100),
            state_store=store,
        )
        self.assertEqual(excerpt["content"], "NEEDLE beyond preview and still cached")
        self.assertEqual(excerpt["content_length"], len(body))
        cached = service.run_fetch_source(
            service.FetchSourceRequest(source_id=hit["source_id"], max_chars=100),
            state_store=store, scraper=scraper, keys={}, config={}, url_resolver=_resolver,
        )
        self.assertTrue(cached["cache_hit"])
        self.assertEqual(cached["body"], body[:100])
        self.assertEqual(scraper.call_count, 1)

    def test_legacy_entrypoint_uses_the_same_ranked_fetch_flow(self):
        providers = {
            source: _provider(source, {"primary": _late_shared_rows(source, source)})
            for source in ("brave", "tavily")
        }
        scraper = mock.Mock(side_effect=lambda url, **kwargs: {
            "url": url, "markdown": "body " + url, "via": "fake",
        })
        current = self._search(providers, scraper)
        self.assertEqual(current["errors"], [])
        scraper.reset_mock()
        with (
            mock.patch("multi_search_mcp.src.search.registry.build_provider_registry", return_value=providers),
            mock.patch.object(service, "scrape_url_smart", scraper),
            mock.patch("multi_search_mcp.src.support.url_security._resolve_host_ips", side_effect=_resolver),
        ):
            legacy = service.run_multi_search(service.MultiSearchRequest(
                query="primary", sources=list(providers), count=30, use_state=False,
                scrape_top=0, scrape_per_source=1, output="both",
            ))
        self.assertEqual(legacy["errors"], [])
        for field in ("url", "rrf_score", "body_available"):
            self.assertEqual(
                [hit[field] for hit in legacy["results"]],
                [hit[field] for hit in current["results"]],
            )
        self.assertEqual([row["url"] for row in legacy["display_results"]],
                         [row["url"] for row in current["results"]])
        self.assertEqual(scraper.call_count, 15)
        self.assertEqual(len(legacy["scrapes"]), 15)
        self.assertIn("markdown", legacy)
        for row in current["scrapes"]:
            self.assertEqual(legacy["markdown"].count(row["markdown"]), 1)
        self.assertTrue(all("markdown" not in row for row in legacy["scrapes"]))
        self.assertIn("legacy_scrape_limits", legacy["diagnostics"])

    def test_direct_url_fetch_never_invokes_search(self):
        scraper = mock.Mock(side_effect=lambda url, **kwargs: {
            "url": url, "markdown": "Direct body", "via": "fake",
        })
        with (
            mock.patch.object(service, "run_search_web", side_effect=AssertionError("unexpected search")) as search,
            mock.patch("multi_search_mcp.src.search.registry.build_provider_registry",
                       side_effect=AssertionError("unexpected providers")) as registry,
        ):
            result = service.run_fetch_source(
                service.FetchSourceRequest(url="https://evidence.example/direct"),
                state_store=StateStore(self.state_path), scraper=scraper,
                keys={}, config={}, url_resolver=_resolver,
            )
        search.assert_not_called()
        registry.assert_not_called()
        self.assertEqual(result["body"], "Direct body")
        self.assertTrue(result["persisted"])
        self.assertEqual(scraper.call_count, 1)

    def test_cli_human_and_markdown_include_fetched_body_and_failures(self):
        from multi_search_mcp import cli

        rows = [_row("brave", "good"), _row("brave", "broken")]
        providers = {"brave": _provider("brave", {"primary": rows})}

        def scraper(url, **kwargs):
            if url.endswith("/broken"):
                return {"url": url, "error": "BODY_FETCH_FAILED"}
            return {"url": url, "markdown": "FETCHED_BODY_MARKER", "via": "fake"}

        with (
            mock.patch("multi_search_mcp.src.search.registry.build_provider_registry", return_value=providers),
            mock.patch.object(service, "scrape_url_smart", side_effect=scraper),
            mock.patch("multi_search_mcp.src.support.url_security._resolve_host_ips", side_effect=_resolver),
        ):
            for output_format in ("human", "markdown"):
                with self.subTest(output_format=output_format):
                    output, errors = StringIO(), StringIO()
                    code = cli.main(
                        ["search", "primary", "--source", "brave", "--format", output_format],
                        stdout=output, stderr=errors,
                    )
                    self.assertEqual(code, 0, errors.getvalue())
                    self.assertIn("FETCHED_BODY_MARKER", output.getvalue())
                    self.assertIn("BODY_FETCH_FAILED", output.getvalue())

    def test_cli_marks_body_preview_truncation(self):
        from multi_search_mcp import cli

        providers = {"brave": _provider("brave", {"primary": [_row("brave", "document")]})}
        with (
            mock.patch.object(service, "load_config", return_value={"scrape_chars": 8}),
            mock.patch("multi_search_mcp.src.search.registry.build_provider_registry", return_value=providers),
            mock.patch.object(service, "scrape_url_smart", side_effect=lambda url, **kwargs: {
                "url": url, "markdown": "VISIBLE hidden tail beyond preview", "via": "fake",
            }),
            mock.patch("multi_search_mcp.src.support.url_security._resolve_host_ips", side_effect=_resolver),
        ):
            for output_format in ("human", "markdown"):
                with self.subTest(output_format=output_format):
                    output, errors = StringIO(), StringIO()
                    code = cli.main(
                        ["search", "primary", "--source", "brave", "--format", output_format],
                        stdout=output, stderr=errors,
                    )
                    self.assertEqual(code, 0, errors.getvalue())
                    self.assertIn("VISIBLE", output.getvalue())
                    self.assertNotIn("hidden tail beyond preview", output.getvalue())
                    self.assertIn("truncated", output.getvalue())

    def test_mcp_tools_return_fetched_body_without_reordering(self):
        from multi_search_mcp import tools

        rows = [_row("brave", "first"), _row("brave", "second")]
        providers = {"brave": _provider("brave", {"primary": rows})}
        with (
            mock.patch("multi_search_mcp.src.search.registry.build_provider_registry", return_value=providers),
            mock.patch.object(service, "scrape_url_smart", side_effect=lambda url, **kwargs: {
                "url": url, "markdown": f"MCP_BODY:{url}", "via": "fake",
            }),
            mock.patch("multi_search_mcp.src.support.url_security._resolve_host_ips", side_effect=_resolver),
        ):
            for call in (tools.search_web_tool, tools.multi_search_tool):
                with self.subTest(tool=call.__name__):
                    response = call(query="primary", sources=["brave"], use_state=False)
                    self.assertEqual(response["errors"], [])
                    self.assertEqual([hit["url"] for hit in response["results"]], [row["url"] for row in rows])
                    self.assertTrue(all("body" not in hit for hit in response["results"]))
                    if "markdown" in response:
                        for row in rows:
                            self.assertEqual(response["markdown"].count(f"MCP_BODY:{row['url']}"), 1)
                    else:
                        self.assertTrue(all(row["markdown"].startswith("MCP_BODY:") for row in response["scrapes"]))

    def test_batch_timeout_prevents_starting_another_scrape_backend(self):
        from multi_search_mcp.src.scrape import scrape

        provider = _provider("brave", {"primary": [_row("brave", "slow")]})
        finished = threading.Event()
        started = threading.Event()
        batch_deadline = None

        def slow_jina(url, *args, **kwargs):
            started.set()
            while time.monotonic() <= batch_deadline:
                time.sleep(0.005)
            return {"url": url, "error": "Jina did not finish in time"}

        def real_scraper(url, **kwargs):
            nonlocal batch_deadline
            batch_deadline = kwargs["deadline"]
            try:
                return scrape.scrape_url_smart(url, **kwargs)
            finally:
                finished.set()

        with (
            mock.patch.object(scrape, "_jina_anonymous_cooling_down", return_value=False),
            mock.patch.object(scrape, "scrape_url_jina", side_effect=slow_jina),
            mock.patch.object(scrape, "scrape_url_exa", return_value={
                "markdown": "Too late", "via": "fake-exa",
            }) as exa,
            mock.patch.object(scrape, "scrape_url_tavily", side_effect=AssertionError("unexpected Tavily")),
            mock.patch.object(scrape, "scrape_url_firecrawl", side_effect=AssertionError("unexpected Firecrawl")),
        ):
            response = service.run_search_web(
                service.SearchWebRequest(query="primary", sources=["brave"], use_state=False),
                providers={"brave": provider}, keys={"exa": "fake-exa-key"}, config={},
                scraper=real_scraper, url_resolver=_resolver, scrape_timeout=2,
            )
            self.assertTrue(started.is_set())
            self.assertIn("timeout", response["results"][0]["body_error"])
            self.assertTrue(finished.wait(timeout=2))
            exa.assert_not_called()

    def test_mixed_provider_retention_is_not_bypassed_by_prefetched_body(self):
        restricted = replace(
            capabilities.PROVIDER_CAPABILITIES["brave"],
            retention=capabilities.RetentionPolicy(
                persist_search_result=False, persist_content=False, persist_body=False,
            ),
        )
        prefetched = {
            **_row("tavily", "shared"), "scraped_content": "provider body",
            "content_kind": "body",
        }
        providers = {
            "brave": _provider("brave", {"primary": [_row("brave", "shared")]}),
            "tavily": _provider("tavily", {"primary": [prefetched]}),
        }
        scraper = mock.Mock(side_effect=lambda url, **kwargs: {
            "url": url, "markdown": "fresh body for this response", "via": "fake",
        })
        with mock.patch.dict(capabilities.PROVIDER_CAPABILITIES, {"brave": restricted}):
            response = self._search(providers, scraper, use_state=True)
        hit = response["results"][0]
        self.assertEqual(response["errors"], [])
        self.assertEqual(hit["providers"], ["brave", "tavily"])
        self.assertEqual(response["scrapes"][0]["markdown"], "provider body")
        scraper.assert_not_called()
        store = StateStore(self.state_path)
        self.assertIsNone(SourceRegistry(store).get(hit["source_id"]))
        self.assertIsNone(ContentStore(store).get(hit["source_id"]))
        with self.assertRaisesRegex(ValueError, "missing or expired"):
            service.run_read_source(
                service.ReadSourceRequest(source_id=hit["source_id"]), state_store=store,
            )


if __name__ == "__main__":
    unittest.main()
