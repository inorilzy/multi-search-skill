import unittest
import threading
import time

from multi_search_mcp.src.search.search_runner import ProviderSpec
from multi_search_mcp.src.service import SearchWebRequest, _run_search_candidates


def stable_hits(response):
    return [
        {key: value for key, value in hit.items() if key not in {"source_id", "content_ref"}}
        for hit in response["results"]
    ]


class QueryIdentityTests(unittest.TestCase):
    def search(self, *, query="primary", expand=(), config=None, count=10, call=None,
               query_runs_observer=None):
        calls = []

        def provider(query, _config, _context, _key):
            calls.append(query)
            if call:
                return call(query)
            return [{
                "source": "brave", "title": "Shared", "url": "https://example.com/shared",
            }, {
                "source": "brave", "title": "Second", "url": "https://example.com/second",
            }]

        response = _run_search_candidates(
            SearchWebRequest(query=query, expand=list(expand), sources=["brave"],
                             count=count, use_state=False),
            providers={"brave": ProviderSpec("brave", "brave", provider)},
            keys={}, config={} if config is None else config,
            **({"query_runs_observer": query_runs_observer} if query_runs_observer else {}),
        )
        return response, calls

    def test_duplicate_primary_does_not_request_or_change_single_query_scores(self):
        single, _ = self.search(count=1)
        duplicate, calls = self.search(expand=["primary", "primary"], count=1)

        self.assertEqual(calls, ["primary"])
        self.assertEqual(stable_hits(duplicate), stable_hits(single))
        self.assertAlmostEqual(duplicate["results"][0]["rrf_score"], 0.024390243902439025)
        self.assertNotIn("query_ranks", duplicate["results"][0])

    def test_blank_and_outer_whitespace_variants_are_excluded_and_inspectable(self):
        response, calls = self.search(
            query=" primary ", expand=["", " \t\n", "primary", " angle ", "angle"],
        )

        self.assertCountEqual(calls, [" primary ", "angle"])
        self.assertEqual(response["diagnostics"]["primary_query"], " primary ")
        self.assertEqual(response["diagnostics"]["queries"], [" primary ", "angle"])
        self.assertEqual(response["diagnostics"]["duplicate_query_count"], 2)
        self.assertEqual(response["diagnostics"]["discarded_blank_query_count"], 2)

    def test_meaningful_query_differences_survive(self):
        variants = [
            '"exact  phrase"', '"exact phrase"', "Widget", "widget", "v1.2", "v1.20",
            "https://example.com/A?x=1", "https://example.com/a?x=1", "part-A", "part_a",
        ]
        response, calls = self.search(expand=variants)

        self.assertCountEqual(calls, ["primary", *variants])
        self.assertEqual(len(response["results"][0]["query_ranks"]), 11)

    def test_variant_permutation_and_completion_order_keep_scores_and_ties_stable(self):
        def search_with_delays(expand, delays):
            barrier = threading.Barrier(3)
            completed = []

            def call(query):
                barrier.wait(timeout=2)
                time.sleep(delays[query])
                completed.append(query)
                return [{"source": "brave", "url": "https://example.com/" + query,
                         "title": query}]

            response, _ = self.search(expand=expand, call=call)
            return response, completed

        forward, first_order = search_with_delays(
            ["z-angle", "a-angle"], {"primary": 0.04, "z-angle": 0.02, "a-angle": 0},
        )
        reverse, second_order = search_with_delays(
            ["a-angle", "z-angle", "z-angle"], {"primary": 0, "z-angle": 0.02, "a-angle": 0.04},
        )
        self.assertNotEqual(first_order, second_order)
        self.assertEqual(stable_hits(forward), stable_hits(reverse))
        self.assertEqual(forward["diagnostics"]["primary_query"], "primary")
        self.assertEqual([hit["title"] for hit in forward["results"]],
                         ["a-angle", "primary", "z-angle"])

    def test_request_expand_and_config_alias_priority_are_preserved(self):
        config = {"expand": ["config-angle", "config-angle"],
                  "expand_queries": ["alias-angle"]}
        _, explicit = self.search(expand=["request-angle"], config=config)
        _, configured = self.search(config=config)
        _, alias = self.search(config={"expand_queries": ["alias-angle", "alias-angle"]})

        self.assertCountEqual(explicit, ["primary", "request-angle"])
        self.assertCountEqual(configured, ["primary", "config-angle"])
        self.assertCountEqual(alias, ["primary", "alias-angle"])

    def test_observer_receives_each_executed_query_once_with_provider_ranks(self):
        observed = []
        response, _ = self.search(
            expand=["angle", "primary", "angle"], query_runs_observer=observed.append,
        )
        self.assertEqual(len(observed), 1)
        self.assertEqual([query for query, _rows in observed[0]], ["primary", "angle"])
        self.assertEqual([row["provider_rank"] for row in observed[0][0][1]], [1, 2])
        self.assertEqual(response["diagnostics"]["queries"], ["primary", "angle"])

    def test_duplicate_provider_rows_and_key_retries_do_not_add_query_support(self):
        attempts = []

        def provider(query, _config, _context, key):
            attempts.append((query, key))
            shared = {"source": "brave", "title": "Shared",
                      "url": "https://example.com/shared"}
            if key == "test-key-one":
                return [shared, {"source": "brave", "error": "429 quota exceeded"}]
            return [shared, dict(shared), {"source": "brave", "error": "upstream failed"}]

        response = _run_search_candidates(
            SearchWebRequest(query="primary", expand=["primary", "angle", "angle"],
                             sources=["brave"], use_state=False),
            providers={"brave": ProviderSpec("brave", "brave", provider, key_name="brave")},
            keys={"brave": ["test-key-one", "test-key-two"]}, config={},
        )

        self.assertCountEqual(attempts, [
            ("primary", "test-key-one"), ("primary", "test-key-two"),
            ("angle", "test-key-one"), ("angle", "test-key-two"),
        ])
        hit = response["results"][0]
        self.assertEqual(hit["query_ranks"], [
            {"query": "primary", "rank": 1}, {"query": "angle", "rank": 1},
        ])
        self.assertEqual(len(hit["provider_ranks"]), 2)
        self.assertAlmostEqual(hit["rrf_score"], 0.04878048780487805)


if __name__ == "__main__":
    unittest.main()
