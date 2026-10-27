"""Regression guard for removed dead config/route metadata (issue 23).

Dead keys are either gone from requests/routes or explicitly deprecated in
config with a warning; the formatter must never rerank RRF rows.
"""
from __future__ import annotations

import inspect
import json
import unittest
import warnings
from pathlib import Path

from multi_search_mcp.src import service
from multi_search_mcp.src.search.candidate import SEARCH_RESULT_LIMIT
from multi_search_mcp.src.search.resolve import (
    DEPRECATED_CONFIG_KEYS,
    SearchPlanRequest,
    resolve_search_plan,
)
from multi_search_mcp.src.search.search_runner import (
    ROUTE_META,
    ProviderSpec,
    SearchRunnerConfig,
    route_meta,
)
from multi_search_mcp.src.support import dedup
from multi_search_mcp.src.support.format import format_results
from multi_search_mcp.src.support.requests import MultiSearchRequest

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "multi-search-config.json"

# Keys the runtime actually reads. Keep this list explicit so a removed key or a
# newly invented one fails the example-config test.
LIVE_CONFIG_KEYS = {
    "type", "disabled_sources", "count", "counts", "serpapi_engine", "timeout",
    "scrape_chars", "scrape_timeout", "scrape_url_timeout", "scrape_concurrency",
    "expand", "expand_queries", "twitter_cookies_path", "query_fusion",
}
DEAD_KEYS = {
    "scrape_top", "no_scrape", "scrape_per_source", "brief", "verbose",
    "title_url_only", "want_content",
}

class ExampleConfigTests(unittest.TestCase):
    def test_example_config_contains_only_live_keys(self):
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertLessEqual(set(config), LIVE_CONFIG_KEYS)
        self.assertEqual(set(config) & DEAD_KEYS, set())

    def test_dead_keys_are_explicitly_deprecated(self):
        self.assertEqual(set(DEPRECATED_CONFIG_KEYS), DEAD_KEYS)

class RequestSurfaceTests(unittest.TestCase):
    def test_request_dtos_no_longer_expose_dead_fields(self):
        for cls in (MultiSearchRequest, SearchPlanRequest):
            fields = set(inspect.signature(cls).parameters)
            self.assertEqual(fields & DEAD_KEYS, set(), cls.__name__)
        self.assertNotIn("want_content", set(SearchRunnerConfig.__dataclass_fields__))
        params = inspect.signature(format_results).parameters
        for dead in ("brief", "verbose", "title_url_only"):
            self.assertNotIn(dead, params)

    def test_route_meta_only_carries_live_keys(self):
        for route, meta in ROUTE_META.items():
            self.assertEqual(set(meta) & DEAD_KEYS, set(), route)
        for route in ("default", "fast", "social", "dev", "all"):
            meta = route_meta(route)
            self.assertEqual(set(meta) & DEAD_KEYS, set(), route)

    def test_fast_route_still_fetches_the_shared_body_stage(self):
        url = "https://example.com/fast"
        providers = {"baidu": ProviderSpec(
            name="baidu", public_name="baidu",
            call=lambda *_args: [{
                "source": "baidu", "title": "Fast doc", "url": url,
                "description": "excerpt", "content_kind": "excerpt",
            }],
        )}
        response = service.run_search_web(
            service.SearchWebRequest(query="fast", route="fast", sources=["baidu"], use_state=False),
            providers=providers, keys={}, config={},
            scraper=lambda target, **_kwargs: {"url": target, "markdown": "body", "via": "fixture"},

        )
        self.assertEqual(response["diagnostics"]["body_fetch_count"], 1)
        self.assertEqual(response["diagnostics"]["body_success_count"], 1)
        self.assertLessEqual(len(response["results"]), SEARCH_RESULT_LIMIT)

class DeprecationTests(unittest.TestCase):
    def test_every_dead_config_key_warns_and_has_no_effect(self):
        for key in sorted(DEAD_KEYS):
            with self.subTest(key=key):
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    plan = resolve_search_plan(SearchPlanRequest(), {key: True})
                messages = [str(item.message) for item in caught
                            if issubclass(item.category, FutureWarning)]
                self.assertTrue(messages, f"{key} must emit a deprecation warning")
                self.assertIn(key, messages[0])
                for dead_attr in ("scrape_top", "scrape_per_source", "title_url_only", "want_content"):
                    self.assertFalse(hasattr(plan, dead_attr))

    def test_live_config_does_not_warn(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            resolve_search_plan(SearchPlanRequest(), {
                "type": "fast", "timeout": 30, "scrape_chars": 800,
                "scrape_timeout": 20, "scrape_concurrency": 2,
            })
        self.assertEqual([item for item in caught if issubclass(item.category, FutureWarning)], [])

class NoLegacyRerankTests(unittest.TestCase):
    def test_rank_results_helper_is_removed(self):
        self.assertFalse(hasattr(dedup, "rank_results"))

    def test_formatter_keeps_input_rrf_order(self):
        rows = [
            {"source": "brave", "title": "First", "url": "https://example.com/first",
             "rrf_score": 0.1, "scraped_content": "long " * 100},
            {"source": "exa", "title": "Second", "url": "https://example.com/second",
             "rrf_score": 0.9},
        ]
        output = format_results(rows, "q")
        self.assertLess(
            output.index("https://example.com/first"),
            output.index("https://example.com/second"),
            "RRF order must not be reranked by body length or consensus",
        )

if __name__ == "__main__":
    unittest.main()
