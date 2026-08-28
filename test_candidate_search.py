import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from multi_search_mcp.src.search.search_runner import ProviderSpec


class CanonicalUrlTests(unittest.TestCase):
    def test_canonicalization_is_conservative_and_deterministic(self):
        from multi_search_mcp.src.search.candidate import canonicalize_url

        self.assertEqual(
            canonicalize_url(
                "HTTP://Example.COM:80/path?b=2&utm_source=campaign&a=1#fragment"
            ),
            "http://example.com/path?a=1&b=2",
        )
        self.assertEqual(
            canonicalize_url("https://example.com/path?source_id=7&ref_id=9"),
            "https://example.com/path?ref_id=9&source_id=7",
        )
        self.assertNotEqual(
            canonicalize_url("http://example.com/resource"),
            canonicalize_url("https://example.com/resource"),
        )


class CandidateFusionTests(unittest.TestCase):
    def test_compact_hit_uses_the_richest_non_body_candidate_text(self):
        from multi_search_mcp.src.search.candidate import fuse_search_results

        hits = fuse_search_results(
            [("query", [
                {
                    "source": "brave",
                    "title": "Metadata winner",
                    "url": "https://example.com/shared",
                    "content_kind": "metadata",
                    "provider_rank": 1,
                },
                {
                    "source": "exa",
                    "title": "Excerpt contribution",
                    "url": "https://example.com/shared",
                    "description": "useful candidate excerpt",
                    "content_kind": "excerpt",
                    "provider_rank": 2,
                },
            ])],
            response_id="response-content",
            limit=10,
        )

        self.assertEqual(hits[0]["content"], "useful candidate excerpt")
        self.assertEqual(hits[0]["content_kind"], "excerpt")

    def test_single_query_rrf_is_deterministic_compact_and_deduplicated(self):
        from multi_search_mcp.src.search.candidate import fuse_search_results

        rows = [
            {
                "source": "tavily",
                "title": "Only Tavily",
                "url": "https://example.com/tavily",
                "description": "tavily result",
                "provider_rank": 1,
                "score": 0.99,
            },
            {
                "source": "tavily",
                "title": "Common from Tavily",
                "url": "https://example.com/common?utm_source=x",
                "description": "short candidate summary",
                "scraped_content": "PRIVATE BODY MUST NOT LEAK",
                "content_kind": "body",
                "provider_rank": 2,
                "score": 0.01,
            },
            {
                "source": "brave",
                "title": "Common from Brave",
                "url": "https://EXAMPLE.com/common#fragment",
                "description": "common result",
                "content_kind": "excerpt",
                "provider_rank": 1,
            },
            {
                "source": "brave",
                "title": "Duplicate from Brave",
                "url": "https://example.com/common",
                "description": "must not cast a second Brave vote",
                "provider_rank": 3,
            },
            {
                "source": "brave",
                "title": "Only Brave",
                "url": "https://example.com/brave",
                "description": "brave result",
                "provider_rank": 2,
            },
        ]

        forward = fuse_search_results(
            [("query", rows)], response_id="response-fixed", limit=10
        )
        reversed_completion = fuse_search_results(
            [("query", list(reversed(rows)))],
            response_id="response-fixed",
            limit=10,
        )

        self.assertEqual(
            [row["canonical_url"] for row in forward],
            [row["canonical_url"] for row in reversed_completion],
        )
        self.assertEqual(forward[0]["canonical_url"], "https://example.com/common")
        self.assertAlmostEqual(forward[0]["rrf_score"], 0.04819976771196284)
        self.assertEqual(
            forward[0]["provider_ranks"],
            [
                {"provider": "brave", "query": "query", "rank": 1},
                {
                    "native_score": 0.01,
                    "provider": "tavily",
                    "query": "query",
                    "rank": 2,
                },
            ],
        )
        self.assertTrue(forward[0]["body_available"])
        self.assertEqual(forward[0]["source_id"], reversed_completion[0]["source_id"])
        for forbidden in ("body", "full_content", "scraped_content"):
            self.assertNotIn(forbidden, forward[0])

    def test_expanded_queries_use_two_level_rrf(self):
        from multi_search_mcp.src.search.candidate import fuse_search_results

        query_one = [
            {
                "source": "brave",
                "title": "Common",
                "url": "https://example.com/common",
                "provider_rank": 1,
            },
            {
                "source": "tavily",
                "title": "Common",
                "url": "https://example.com/common",
                "provider_rank": 1,
            },
            {
                "source": "brave",
                "title": "Query one only",
                "url": "https://example.com/query-one",
                "provider_rank": 2,
            },
        ]
        query_two = [
            {
                "source": "brave",
                "title": "Query two only",
                "url": "https://example.com/query-two",
                "provider_rank": 1,
            },
            {
                "source": "tavily",
                "title": "Query two only",
                "url": "https://example.com/query-two",
                "provider_rank": 1,
            },
            {
                "source": "brave",
                "title": "Common",
                "url": "https://example.com/common",
                "provider_rank": 2,
            },
        ]

        hits = fuse_search_results(
            [("angle one", query_one), ("angle two", query_two)],
            response_id="response-expanded",
            limit=10,
        )

        self.assertEqual(
            [row["canonical_url"] for row in hits],
            [
                "https://example.com/common",
                "https://example.com/query-two",
                "https://example.com/query-one",
            ],
        )
        self.assertAlmostEqual(hits[0]["rrf_score"], 0.04819976771196284)
        self.assertEqual(
            hits[0]["query_ranks"],
            [
                {"query": "angle one", "rank": 1},
                {"query": "angle two", "rank": 2},
            ],
        )


class SearchWebCoreTests(unittest.TestCase):
    @staticmethod
    def _providers():
        return {
            "brave": ProviderSpec(
                name="brave",
                public_name="brave",
                call=lambda _query, _config, _context, _key: [
                    {
                        "source": "brave",
                        "title": "Common",
                        "url": "https://example.com/z-common",
                        "description": "Brave common",
                        "content_kind": "excerpt",
                    },
                    {
                        "source": "brave",
                        "title": "Only Brave",
                        "url": "https://example.com/a-only",
                        "description": "Brave only",
                        "content_kind": "excerpt",
                    },
                ],
            ),
            "tavily": ProviderSpec(
                name="tavily",
                public_name="tavily",
                call=lambda _query, _config, _context, _key: [
                    {
                        "source": "tavily",
                        "title": "Common from Tavily",
                        "url": "https://example.com/z-common",
                        "description": "Tavily common",
                        "scraped_content": "prefetched body",
                        "content_kind": "body",
                    }
                ],
            ),
        }

    def test_core_returns_compact_ranked_candidates_without_scraping(self):
        from multi_search_mcp.src.service import SearchWebRequest, run_search_web

        response = run_search_web(
            SearchWebRequest(
                query="compact search",
                sources=["brave", "tavily"],
                count=5,
                use_state=False,
            ),
            providers=self._providers(),
            keys={},
            config={},
        )

        self.assertTrue(response["response_id"].startswith("resp_"))
        self.assertEqual(response["query"], "compact search")
        self.assertEqual(response["results"][0]["canonical_url"], "https://example.com/z-common")
        self.assertEqual(
            response["results"][0]["provider_ranks"],
            [
                {"provider": "brave", "query": "compact search", "rank": 1},
                {"provider": "tavily", "query": "compact search", "rank": 1},
            ],
        )
        self.assertEqual(response["diagnostics"]["raw_result_count"], 3)
        self.assertEqual(
            {row["source"]: row["status"] for row in response["provider_status"]},
            {"brave": "ok", "tavily": "ok"},
        )
        self.assertNotIn("scrapes", response)
        self.assertNotIn("scraped_content", response["results"][0])

    def test_core_registers_source_ids_in_the_shared_state_store(self):
        from multi_search_mcp.src.service import SearchWebRequest, run_search_web
        from multi_search_mcp.src.state.source_registry import SourceRegistry
        from multi_search_mcp.src.state.state_store import StateStore

        with TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.sqlite")
            response = run_search_web(
                SearchWebRequest(
                    query="registered search",
                    sources=["brave", "tavily"],
                    count=5,
                ),
                providers=self._providers(),
                keys={},
                config={},
                state_store=store,
            )

            saved = SourceRegistry(store).get(response["results"][0]["source_id"])

        self.assertIsNotNone(saved)
        self.assertEqual(saved["response_id"], response["response_id"])
        self.assertEqual(saved["canonical_url"], "https://example.com/z-common")
        self.assertEqual(saved["providers"], ["brave", "tavily"])

    def test_expanded_search_keeps_partial_provider_failures_in_diagnostics(self):
        from multi_search_mcp.src.service import SearchWebRequest, run_search_web

        def brave(query, _config, _context, _key):
            suffix = "main" if query == "main angle" else "expanded"
            return [
                {
                    "source": "brave",
                    "title": suffix,
                    "url": f"https://example.com/{suffix}",
                    "description": suffix,
                    "content_kind": "excerpt",
                }
            ]

        def tavily(query, _config, _context, _key):
            if query == "expanded angle":
                raise RuntimeError("provider unavailable")
            return [
                {
                    "source": "tavily",
                    "title": "main",
                    "url": "https://example.com/main",
                    "description": "main",
                    "content_kind": "excerpt",
                }
            ]

        response = run_search_web(
            SearchWebRequest(
                query="main angle",
                expand=["expanded angle"],
                sources=["brave", "tavily"],
                count=10,
                use_state=False,
            ),
            providers={
                "brave": ProviderSpec("brave", "brave", brave),
                "tavily": ProviderSpec("tavily", "tavily", tavily),
            },
            keys={},
            config={},
        )

        self.assertEqual(
            response["diagnostics"]["queries"],
            ["main angle", "expanded angle"],
        )
        self.assertEqual(
            {row["source"]: row["status"] for row in response["provider_status"]},
            {"brave": "ok", "tavily": "partial"},
        )
        self.assertEqual(
            response["diagnostics"]["provider_failures"],
            [
                {
                    "error": "provider unavailable",
                    "query": "expanded angle",
                    "source": "tavily",
                }
            ],
        )
        self.assertEqual(len(response["results"]), 2)

    def test_expanded_search_reports_query_failures_when_an_angle_has_no_candidates(self):
        from multi_search_mcp.src.service import SearchWebRequest, run_search_web

        def brave(query, _config, _context, _key):
            if query == "main angle":
                return [
                    {
                        "source": "brave",
                        "title": "main",
                        "url": "https://example.com/main",
                        "description": "main",
                        "content_kind": "excerpt",
                    }
                ]
            return []

        def tavily(query, _config, _context, _key):
            if query == "expanded angle":
                raise RuntimeError("provider unavailable")
            return [
                {
                    "source": "tavily",
                    "title": "main",
                    "url": "https://example.com/main",
                    "description": "main",
                    "content_kind": "excerpt",
                }
            ]

        response = run_search_web(
            SearchWebRequest(
                query="main angle",
                expand=["expanded angle"],
                sources=["brave", "tavily"],
                count=10,
                use_state=False,
            ),
            providers={
                "brave": ProviderSpec("brave", "brave", brave),
                "tavily": ProviderSpec("tavily", "tavily", tavily),
            },
            keys={},
            config={},
        )

        self.assertEqual(
            response["diagnostics"]["query_failures"],
            [
                {
                    "errors": [
                        {
                            "error": "provider unavailable",
                            "source": "tavily",
                        }
                    ],
                    "query": "expanded angle",
                }
            ],
        )
        self.assertEqual(len(response["results"]), 1)

    def test_expanded_search_reports_all_failed_queries_separately(self):
        from multi_search_mcp.src.service import SearchWebRequest, run_search_web

        def failing(_query, _config, _context, _key):
            raise RuntimeError("provider unavailable")

        response = run_search_web(
            SearchWebRequest(
                query="main angle",
                expand=["expanded angle"],
                sources=["brave", "tavily"],
                count=10,
                use_state=False,
            ),
            providers={
                "brave": ProviderSpec("brave", "brave", failing),
                "tavily": ProviderSpec("tavily", "tavily", failing),
            },
            keys={},
            config={},
        )

        self.assertEqual(response["results"], [])
        self.assertEqual(
            response["diagnostics"]["query_failures"],
            [
                {
                    "errors": [
                        {
                            "error": "provider unavailable",
                            "source": "brave",
                        },
                        {
                            "error": "provider unavailable",
                            "source": "tavily",
                        },
                    ],
                    "query": "main angle",
                },
                {
                    "errors": [
                        {
                            "error": "provider unavailable",
                            "source": "brave",
                        },
                        {
                            "error": "provider unavailable",
                            "source": "tavily",
                        },
                    ],
                    "query": "expanded angle",
                },
            ],
        )


class SearchWebToolTests(unittest.TestCase):
    def test_mcp_tool_does_not_replace_an_omitted_timeout(self):
        from multi_search_mcp import tools

        captured = {}

        def fake_run(request):
            captured["request"] = request
            return {"query": request.query, "results": []}

        with mock.patch.object(tools, "run_search_web", side_effect=fake_run):
            response = tools.search_web_tool("tool query")

        self.assertEqual(response["query"], "tool query")
        self.assertIsNone(captured["request"].timeout)

    def test_mcp_tool_is_a_thin_contract_over_candidate_core(self):
        from multi_search_mcp.tools import search_web_tool

        provider = ProviderSpec(
            name="brave",
            public_name="brave",
            call=lambda _query, _config, _context, _key: [
                {
                    "source": "brave",
                    "title": "Candidate",
                    "url": "https://example.com/candidate",
                    "description": "compact",
                    "content_kind": "excerpt",
                }
            ],
        )
        with (
            mock.patch(
                "multi_search_mcp.src.search.registry.build_provider_registry",
                return_value={"brave": provider},
            ),
            mock.patch("multi_search_mcp.src.service.load_keys", return_value={}),
        ):
            response = search_web_tool(
                "tool query", sources=["brave"], count=1, use_state=False
            )

        self.assertEqual(response["query"], "tool query")
        self.assertEqual(response["results"][0]["source"], "brave")
        self.assertNotIn("scrapes", response)


if __name__ == "__main__":
    unittest.main()
