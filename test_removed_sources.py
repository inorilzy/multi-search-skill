"""Regression tests for removed search providers and configuration inputs."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.search.capabilities import PROVIDER_CAPABILITIES
from multi_search_mcp.src.search.registry import build_provider_registry
from multi_search_mcp.src.search.resolve import _resolve_sources, resolve_disabled_sources
from multi_search_mcp.src.search.search_runner import (
    ALL_SOURCE_NAMES,
    SearchContext,
    SearchRunnerConfig,
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
        "github_repos", "hackernews", "stackoverflow", "twitter", "linuxdo_api", "v2ex",
    }

    def test_registry_and_advertised_sources_match_current_thirteen(self):
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
        self.assertEqual(resolve_route("all"), self.SEARCH_SOURCES - {"linuxdo_api"})

    def test_removed_source_names_and_aliases_are_rejected(self):
        for name in ("linuxdo", "linux-do", "zhihu"):
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

    def test_linuxdo_api_alias_and_legacy_cookie_key_still_work(self):
        self.assertEqual(_resolve_sources("default", ["linuxdo_api"]), {"linuxdo_api"})
        self.assertEqual(_resolve_sources("default", ["linuxdo-api"]), {"linuxdo_api"})
        with tempfile.TemporaryDirectory() as temp:
            keys_path = Path(temp) / "keys.json"
            keys_path.write_text(json.dumps({"linuxdo": "session=test-cookie"}), encoding="utf-8")
            keys = load_keys(keys_path, environ={})
        self.assertEqual(keys, {"linuxdo": "session=test-cookie"})
        cfg = SearchRunnerConfig(
            route="default", counts={"linuxdo_api": 7}, timeout=10,
            serpapi_engine="google_light", keys=keys,
        )
        ctx = SearchContext(source="linuxdo-api", timeout=5, deadline=100, keys=keys)
        received = {}

        def fake_search(query, cookie, count, timeout):
            received.update(query=query, cookie=cookie, count=count, timeout=timeout)
            return [{"source": "linuxdo-api", "url": "https://linux.do/t/topic/123"}]

        with mock.patch("multi_search_mcp.src.search.registry.search_linuxdo_api", fake_search):
            spec = build_provider_registry()["linuxdo_api"]
            self.assertIsNone(spec.key_name)
            rows = spec.call("python asyncio", cfg, ctx, None)

        self.assertEqual(received, {
            "query": "python asyncio", "cookie": "session=test-cookie", "count": 7, "timeout": 5,
        })
        self.assertEqual(rows[0]["source"], "linuxdo-api")


if __name__ == "__main__":
    unittest.main()
