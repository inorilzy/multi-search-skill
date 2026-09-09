import unittest
import threading
from unittest import mock

from multi_search_mcp.src.search.search_runner import ProviderSpec
from multi_search_mcp.src.service import SearchWebRequest, _run_search_candidates


EXPERIMENT = {"mode": "weighted", "primary_weight": 1.0, "variant_budget": 0.9}


def hit(name):
    return {"source": "brave", "title": name, "url": "https://example.test/" + name}


def search(rows, expand, *, policy=EXPERIMENT, count=10):
    def call(query, config, _context, _key):
        if config.want_content:
            raise AssertionError("candidate search requested bodies")
        value = rows[query]
        if isinstance(value, Exception):
            raise value
        return value

    return _run_search_candidates(
        SearchWebRequest(query="primary", expand=expand, count=count,
                         sources=["brave"], use_state=False),
        providers={"brave": ProviderSpec("brave", "brave", call)},
        keys={}, config={} if policy is None else {"query_fusion": policy},
    )


def stable_results(response):
    return [{key: value for key, value in row.items() if key not in {"source_id", "content_ref"}}
            for row in response["results"]]


class QueryWeightingTests(unittest.TestCase):
    def test_primary_outweighs_one_variant_at_the_same_rank(self):
        response = search({"primary": [hit("z-main")], "angle": [hit("a-angle")]}, ["angle"])
        self.assertEqual([row["title"] for row in response["results"]], ["z-main", "a-angle"])
        self.assertAlmostEqual(response["results"][1]["rrf_score"], 0.02195121951219512)
        self.assertEqual(response["results"][0]["query_ranks"], [
            {"query": "primary", "rank": 1, "weight": 1.0,
             "contribution": 0.024390243902439025, "is_primary": True},
        ])

    def test_failed_and_empty_queries_keep_their_allocated_budget(self):
        response = search({"primary": RuntimeError("offline"), "a": [hit("found")],
                           "b": [], "c": RuntimeError("timeout")}, ["c", "a", "b", "a"])
        self.assertEqual(response["diagnostics"]["query_fusion"]["weights"],
                         {"primary": 1.0, "a": 0.3, "b": 0.3, "c": 0.3})
        self.assertAlmostEqual(response["results"][0]["rrf_score"], 0.007317073170731707)
        self.assertEqual(response["diagnostics"]["query_fusion"]["primary_status"], "failed")
        self.assertFalse(response["results"][0]["primary_query_hit"])
        self.assertEqual(response["results"][0]["variant_support_count"], 1)
        empty = search({"primary": [], "a": [hit("found")]}, ["a"])
        self.assertEqual(empty["diagnostics"]["query_fusion"]["primary_status"], "empty")

    def test_new_variants_share_a_fixed_budget_and_duplicates_add_no_votes(self):
        rows = {"primary": [hit("main")], "a": [hit("shared")],
                "b": [hit("shared")], "c": [hit("shared")]}
        two = search(rows, ["b", "a"])
        three = search(rows, ["c", "a", "b"])
        repeated = search(rows, ["b", "primary", "c", "b", "a", " "])
        self.assertEqual(stable_results(three), stable_results(repeated))
        self.assertEqual(two["results"][0]["rrf_score"], three["results"][0]["rrf_score"])
        self.assertAlmostEqual(two["results"][1]["rrf_score"], three["results"][1]["rrf_score"])
        self.assertAlmostEqual(three["results"][1]["rrf_score"], 0.02195121951219512)
        self.assertEqual(three["results"][1]["variant_support_count"], 3)

    def test_variant_original_material_can_enter_a_full_primary_result_window(self):
        # Fixture truth: 'original' directly supports the question but was absent
        # from the primary recall; these labels are not derived from URL votes.
        rows = {"primary": [hit(f"main-{i:02d}") for i in range(1, 16)],
                "a": [hit("original")], "b": [hit("original")]}
        response = search(rows, ["a", "b"], count=15)
        titles = [row["title"] for row in response["results"]]
        self.assertEqual(titles.index("original"), 5)
        self.assertEqual(len(titles), 15)
        self.assertNotIn("main-15", titles)
        overprotected = search(rows, ["a", "b"], count=15,
                               policy={"mode": "weighted", "primary_weight": 0.6, "variant_budget": 0.4})
        self.assertNotIn("original", [row["title"] for row in overprotected["results"]])

    def test_shared_off_topic_variants_can_still_outrank_low_primary_results(self):
        # Controlled negative case: every variant drifted to the wrong version.
        rows = {"primary": [hit(f"v3-{i:02d}") for i in range(1, 16)],
                "a": [hit("wrong-v2")], "b": [hit("wrong-v2")], "c": [hit("wrong-v2")]}
        response = search(rows, ["a", "b", "c"], count=15)
        self.assertEqual(response["results"][0]["title"], "v3-01")
        self.assertIn("wrong-v2", [row["title"] for row in response["results"]])

    def test_single_query_keeps_provider_scores_order_fields_and_truncation(self):
        rows = {"primary": [hit("z-first"), hit("a-second")]}
        legacy = search(rows, [], policy=None, count=1)
        weighted = search(rows, ["primary", " "], count=1)
        self.assertEqual(stable_results(legacy), stable_results(weighted))
        self.assertEqual(weighted["results"][0]["title"], "z-first")
        self.assertAlmostEqual(weighted["results"][0]["rrf_score"], 0.024390243902439025)
        self.assertEqual(weighted["diagnostics"]["query_fusion"]["applied_stage"], "provider")

    def test_invalid_policy_fails_before_any_provider_request(self):
        from multi_search_mcp.src.support.config import ConfigError

        invalid = [None, "weighted", {"mode": "typo"}, {"mode": "weighted"},
                   {**EXPERIMENT, "primary_weight": float("nan")},
                   {**EXPERIMENT, "variant_budget": float("inf")},
                   {**EXPERIMENT, "variant_budget": True},
                   {**EXPERIMENT, "variant_budget": -1},
                   {**EXPERIMENT, "variant_budget": 1.1},
                   {**EXPERIMENT, "weights": [1, 2]},
                   {"mode": "equal", "primary_weight": 1}]
        for policy in invalid:
            with self.subTest(policy=policy):
                provider = mock.Mock(return_value=[hit("found")])
                with self.assertRaises(ConfigError):
                    _run_search_candidates(
                        {"query": "primary", "expand": ["angle"], "sources": ["brave"], "use_state": False},
                        providers={"brave": ProviderSpec("brave", "brave", provider)},
                        keys={}, config={"query_fusion": policy},
                    )
                provider.assert_not_called()

    def test_default_policy_remains_equal(self):
        rows = {"primary": [hit("z-main")], "angle": [hit("a-angle")]}
        response = search(rows, ["angle"], policy=None)
        self.assertEqual([row["title"] for row in response["results"]], ["a-angle", "z-main"])
        self.assertEqual(response["diagnostics"]["query_fusion"]["mode"], "equal")

    def test_real_provider_deadline_does_not_transfer_the_primary_budget(self):
        release = threading.Event()

        def provider(query, _config, _context, _key):
            if query == "primary":
                release.wait(3)
            return [hit(query)]

        try:
            response = _run_search_candidates(
                {"query": "primary", "expand": ["angle"], "sources": ["brave"],
                 "timeout": 1, "use_state": False},
                providers={"brave": ProviderSpec("brave", "brave", provider)},
                keys={}, config={"query_fusion": EXPERIMENT},
            )
        finally:
            release.set()
        self.assertEqual([row["title"] for row in response["results"]], ["angle"])
        self.assertEqual(response["diagnostics"]["query_fusion"]["primary_status"], "failed")
        self.assertIn("timeout", response["errors"][0]["error"])
        self.assertAlmostEqual(response["results"][0]["rrf_score"], 0.02195121951219512)


if __name__ == "__main__":
    unittest.main()
