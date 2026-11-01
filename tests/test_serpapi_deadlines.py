import json
import threading
import unittest
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from multi_search_mcp.src.search import search_runner
from multi_search_mcp.src.search.registry import build_provider_registry
from multi_search_mcp.src.search.search_runner import SearchContext, SearchRunner, SearchRunnerConfig
from multi_search_mcp.src.search.searchers import serpapi
from multi_search_mcp.src.support.concurrency import BoundedDaemonExecutor


def page(start=0):
    return json.dumps({"organic_results": [
        {"title": str(index), "link": f"https://example.com/{index}"}
        for index in range(start, start + 10)
    ]}).encode()


def response(body):
    result = mock.MagicMock()
    result.__enter__.return_value = result
    result.read.return_value = body
    return result


class SerpAPIDeadlineTests(unittest.TestCase):
    """SerpAPI fetches one page (Google Light returns 10 results per page)."""

    def test_registry_call_sends_one_request_within_the_shared_deadline(self):
        now = 100.0
        budgets = []
        snapshots = []

        def http(url, timeout):
            nonlocal now
            budgets.append(timeout)
            now += 6
            return response(page(0))

        config = SearchRunnerConfig("default", {"serpapi": 40}, 10, "google_light", {})
        context = SearchContext("serpapi", 20, 110, {}, publish_partial=snapshots.append)
        with mock.patch.object(serpapi, "time", SimpleNamespace(monotonic=lambda: now)), \
                mock.patch.object(serpapi, "urlopen_retry", side_effect=http):
            rows = build_provider_registry()["serpapi"].call("query", config, context, "fixture-key")

        self.assertEqual(budgets, [10])
        self.assertEqual(len(snapshots[-1]), 10)
        self.assertEqual(len([row for row in rows if row.get("url")]), 10)
        self.assertFalse(any(row.get("error") for row in rows))

    def test_standalone_call_caps_the_request_at_timeout(self):
        budgets = []

        def http(url, timeout):
            budgets.append(timeout)
            return response(page())

        with mock.patch.object(serpapi, "time", SimpleNamespace(monotonic=lambda: 100.0)), \
                mock.patch.object(serpapi, "urlopen_retry", side_effect=http):
            rows = serpapi.search_serpapi("query", "fixture-key", count=40, timeout=10)

        self.assertEqual(budgets, [10])
        self.assertEqual(len(rows), 10)

    def test_count_above_one_page_still_sends_the_documented_first_page_query(self):
        queries = []

        def http(url, timeout):
            queries.append(parse_qs(urlsplit(url).query))
            return response(page(0))

        config = SearchRunnerConfig("default", {"serpapi": 25}, 60, "google_light", {})
        context = SearchContext("serpapi", 20, 160, {})
        with mock.patch.object(serpapi, "time", SimpleNamespace(monotonic=lambda: 100.0)), \
                mock.patch.object(serpapi, "urlopen_retry", side_effect=http):
            rows = build_provider_registry()["serpapi"].call("query", config, context, "fixture-key")

        self.assertEqual(len(rows), 10)
        self.assertEqual(queries, [{
            "engine": ["google_light"], "q": ["query"], "output": ["json"],
            "api_key": ["fixture-key"], "hl": ["en"], "gl": ["us"],
        }])

    def test_expired_deadline_sends_nothing(self):
        with mock.patch.object(serpapi, "time", SimpleNamespace(monotonic=lambda: 200.0)), \
                mock.patch.object(serpapi, "urlopen_retry", side_effect=AssertionError("no call")):
            rows = serpapi.search_serpapi("query", "fixture-key", deadline=150.0)
        self.assertIn("deadline", rows[-1]["error"])


if __name__ == "__main__":
    unittest.main()
