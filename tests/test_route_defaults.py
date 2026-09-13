import unittest
from pathlib import Path
from types import SimpleNamespace

from multi_search_mcp.src.search.resolve import resolve_search_plan
from multi_search_mcp.src.support.config import load_config


ROOT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "multi-search-config.json"


def make_request(*, route="default", scrape_top=None):
    return SimpleNamespace(
        query="route defaults",
        route=route,
        count=None,
        sources=None,
        scrape_top=scrape_top,
        scrape_chars=None,
        scrape_per_source=None,
        scrape_timeout=None,
        scrape_concurrency=None,
        timeout=None,
        output="both",
        title_url_only=False,
        verbose=False,
    )


class RouteScrapeDefaultTests(unittest.TestCase):
    def test_repo_config_keeps_route_owned_scrape_defaults_when_unset(self):
        config = load_config(str(ROOT_CONFIG_PATH))

        for route, expected in {"default": 20, "fast": 0, "social": 0}.items():
            with self.subTest(route=route):
                plan = resolve_search_plan(make_request(route=route), config)
                self.assertEqual(plan.scrape_top, expected)

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

    def test_request_scrape_top_beats_config_value(self):
        plan = resolve_search_plan(
            make_request(route="fast", scrape_top=7),
            {"scrape_top": 3, "no_scrape": False},
        )

        self.assertEqual(plan.scrape_top, 7)

    def test_config_scrape_top_beats_route_default_when_non_null(self):
        plan = resolve_search_plan(
            make_request(route="fast"),
            {"scrape_top": 4, "no_scrape": False},
        )

        self.assertEqual(plan.scrape_top, 4)

    def test_no_scrape_still_forces_zero_without_explicit_request_value(self):
        plan = resolve_search_plan(
            make_request(route="default"),
            {"scrape_top": 9, "no_scrape": True},
        )

        self.assertEqual(plan.scrape_top, 0)


if __name__ == "__main__":
    unittest.main()
