"""Regression tests for removed search providers and configuration inputs."""
import tempfile
import unittest
from pathlib import Path

from multi_search_mcp.src.search.capabilities import PROVIDER_CAPABILITIES
from multi_search_mcp.src.search.registry import build_provider_registry
from multi_search_mcp.src.search.resolve import _resolve_sources, resolve_disabled_sources
from multi_search_mcp.src.search.search_runner import (
    ALL_SOURCE_NAMES,
    available_routes,
    resolve_route,
)
from multi_search_mcp.src.service import list_sources
from multi_search_mcp.src.state.keys import load_keys


class RemovedRedditTests(unittest.TestCase):
    def test_reddit_and_vertical_route_are_not_advertised(self):
        self.assertNotIn("reddit_browser", build_provider_registry())
        self.assertNotIn("reddit_browser", PROVIDER_CAPABILITIES)
        self.assertNotIn("reddit_browser", ALL_SOURCE_NAMES)
        self.assertNotIn("vertical", available_routes())

    def test_removed_source_names_are_rejected(self):
        for name in ("reddit", "reddit_browser", "reddit-browser"):
            with self.subTest(source=name):
                with self.assertRaisesRegex(ValueError, "unknown source"):
                    _resolve_sources("default", [name])
                with self.assertRaisesRegex(ValueError, "unknown disabled source"):
                    resolve_disabled_sources({"disabled_sources": [name]})

    def test_removed_vertical_route_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown route: vertical"):
            _resolve_sources("vertical", None)

    def test_reddit_environment_variables_are_no_longer_loaded(self):
        with tempfile.TemporaryDirectory() as temp:
            keys = load_keys(
                Path(temp) / "missing-keys.json",
                environ={
                    "REDDIT_COOKIE_EXPORT": "unused-cookie-export.json",
                    "REDDIT_BROWSER_PROFILE": "unused-profile",
                },
            )
        self.assertEqual(keys, {})


class RemovedFilteredSourceTests(unittest.TestCase):
    SEARCH_SOURCES = {
        "baidu", "brave", "exa", "firecrawl", "parallel", "serpapi", "tavily",
        "github_repos", "hackernews", "stackoverflow", "twitter", "v2ex",
    }

    def test_registry_and_advertised_sources_match_current_twelve(self):
        self.assertEqual(set(build_provider_registry()), self.SEARCH_SOURCES)
        self.assertEqual(ALL_SOURCE_NAMES, self.SEARCH_SOURCES)
        searchable = {
            name for name, capability in PROVIDER_CAPABILITIES.items()
            if capability.search.can_search
        }
        self.assertEqual(searchable, self.SEARCH_SOURCES)
        advertised = list_sources()
        self.assertEqual(set(advertised["sources"]), self.SEARCH_SOURCES)
        self.assertNotIn("cn-community", advertised["routes"])
        self.assertEqual(resolve_route("all"), self.SEARCH_SOURCES)

    def test_removed_source_names_and_aliases_are_rejected(self):
        for name in ("linuxdo", "linux-do", "linuxdo_api", "linuxdo-api", "zhihu"):
            with self.subTest(source=name):
                with self.assertRaisesRegex(ValueError, "unknown source"):
                    _resolve_sources("default", [name])
                with self.assertRaisesRegex(ValueError, "unknown disabled source"):
                    resolve_disabled_sources({"disabled_sources": [name]})

    def test_removed_community_route_is_rejected(self):
        self.assertNotIn("cn-community", available_routes())
        with self.assertRaisesRegex(ValueError, "unknown route: cn-community"):
            _resolve_sources("cn-community", None)

    def test_zhihu_environment_variable_is_no_longer_loaded(self):
        with tempfile.TemporaryDirectory() as temp:
            keys = load_keys(
                Path(temp) / "missing-keys.json",
                environ={"ZHIHU_ACCESS_SECRET": "unused-secret"},
            )
        self.assertEqual(keys, {})


if __name__ == "__main__":
    unittest.main()
