import unittest
import warnings
from pathlib import Path

from multi_search_mcp.src.search.resolve import SearchPlanRequest, resolve_search_plan
from multi_search_mcp.src.support.config import load_config


ROOT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "multi-search-config.json"


def make_request(*, route="default"):
    return SearchPlanRequest(query="route defaults", route=route)


class RouteDefaultTests(unittest.TestCase):
    def test_repo_config_keeps_live_route_defaults(self):
        config = load_config(str(ROOT_CONFIG_PATH))

        for route in ("default", "fast", "social", "dev", "all"):
            with self.subTest(route=route):
                plan = resolve_search_plan(make_request(route=route), config)
                self.assertEqual(plan.route_defaults["count"], 10)
                self.assertEqual(plan.timeout, 60, "repo config timeout wins over route defaults")
                self.assertEqual(plan.scrape_chars, 1200)
                self.assertEqual(plan.scrape_timeout, 60)
                self.assertEqual(plan.scrape_concurrency, 5)

    def test_route_meta_defaults_apply_without_config_override(self):
        for route, count, timeout in (
            ("default", 10, 60), ("fast", 10, 45), ("social", 10, 60),
            ("dev", 10, 60), ("all", 10, 90),
        ):
            with self.subTest(route=route):
                plan = resolve_search_plan(make_request(route=route), {})
                self.assertEqual(plan.route_defaults["count"], count)
                self.assertEqual(plan.timeout, timeout)

    def test_removed_video_route_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown route: video"):
            resolve_search_plan(make_request(route="video"), {})

    def test_removed_video_sources_are_rejected(self):
        for source in ("youtube", "bilibili"):
            with self.subTest(source=source):
                request = make_request()
                request.sources = [source]
                with self.assertRaisesRegex(ValueError, "unknown source"):
                    resolve_search_plan(request, {})

    def test_request_scrape_chars_beats_config_value(self):
        plan = resolve_search_plan(
            SearchPlanRequest(route="fast", scrape_chars=2400),
            {"scrape_chars": 3600},
        )
        self.assertEqual(plan.scrape_chars, 2400)

    def test_config_scrape_chars_beats_default(self):
        plan = resolve_search_plan(make_request(route="fast"), {"scrape_chars": 3600})
        self.assertEqual(plan.scrape_chars, 3600)

    def test_dead_route_keys_are_ignored_with_deprecation_warning(self):
        config = {
            "scrape_top": 3, "no_scrape": True, "scrape_per_source": 1,
            "brief": True, "verbose": True, "title_url_only": True,
            "want_content": True,
        }
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            plan = resolve_search_plan(make_request(), config)
        self.assertTrue(any(issubclass(item.category, FutureWarning) for item in caught))
        self.assertIn("scrape_top", str(caught[-1].message))
        self.assertIn("want_content", str(caught[-1].message))
        for dead in ("scrape_top", "scrape_per_source", "title_url_only", "want_content"):
            self.assertFalse(hasattr(plan, dead))
            self.assertNotIn(dead, plan.route_defaults)


if __name__ == "__main__":
    unittest.main()
