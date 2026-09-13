import json
import threading
import time
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
    def test_registry_pages_share_deadline_and_publish_completed_results(self):
        now = 100.0
        budgets = []
        snapshots = []

        def http(url, timeout):
            nonlocal now
            budgets.append(timeout)
            start = int(parse_qs(urlsplit(url).query).get("start", ["0"])[0])
            now += 6
            return response(page(start))

        config = SearchRunnerConfig("default", {"serpapi": 40}, 10, "google_light", {})
        context = SearchContext("serpapi", 20, 110, {}, publish_partial=snapshots.append)
        with mock.patch.object(serpapi, "time", SimpleNamespace(monotonic=lambda: now)), \
                mock.patch.object(serpapi, "urlopen_retry", side_effect=http):
            rows = build_provider_registry()["serpapi"].call("query", config, context, "fixture-key")

        self.assertEqual(budgets, [10, 4])
        self.assertEqual(len(snapshots[0]), 10)
        self.assertEqual(len(snapshots[-1]), 20)
        self.assertEqual(len([row for row in rows if row.get("url")]), 20)
        self.assertIn("deadline", rows[-1]["error"])

    def test_standalone_call_does_not_reset_timeout_for_each_page(self):
        now = 100.0
        budgets = []

        def http(url, timeout):
            nonlocal now
            budgets.append(timeout)
            now += 6
            return response(page())

        with mock.patch.object(serpapi, "time", SimpleNamespace(monotonic=lambda: now)), \
                mock.patch.object(serpapi, "urlopen_retry", side_effect=http):
            rows = serpapi.search_serpapi("query", "fixture-key", count=40, timeout=10)

        self.assertEqual(budgets, [10, 4])
        self.assertIn("deadline", rows[-1]["error"])

    def test_per_request_cap_and_last_page_success_are_preserved(self):
        now = 100.0
        budgets = []
        queries = []

        def http(url, timeout):
            nonlocal now
            budgets.append(timeout)
            query = parse_qs(urlsplit(url).query)
            queries.append(query)
            now += 15
            return response(page(int(query.get("start", ["0"])[0])))

        config = SearchRunnerConfig("default", {"serpapi": 25}, 60, "google_light", {})
        context = SearchContext("serpapi", 20, 160, {})
        with mock.patch.object(serpapi, "time", SimpleNamespace(monotonic=lambda: now)), \
                mock.patch.object(serpapi, "urlopen_retry", side_effect=http):
            rows = build_provider_registry()["serpapi"].call("query", config, context, "fixture-key")

        self.assertEqual(budgets, [20, 20, 20])
        self.assertEqual(len(rows), 25)
        self.assertFalse(any(row.get("error") for row in rows))
        self.assertEqual([q.get("start", ["0"])[0] for q in queries], ["0", "10", "20"])
        self.assertEqual(queries[0], {
            "engine": ["google_light"], "q": ["query"], "output": ["json"],
            "api_key": ["fixture-key"], "hl": ["en"], "gl": ["us"],
        })

    def test_runner_timeout_keeps_first_page_and_stops_late_worker_pagination(self):
        second_started = threading.Event()
        starts = []
        pool = BoundedDaemonExecutor(max_workers=1, thread_name_prefix="test-serpapi-deadline")

        def http(url, timeout):
            start = int(parse_qs(urlsplit(url).query).get("start", ["0"])[0])
            starts.append(start)
            if start:
                second_started.set()
                time.sleep(float(timeout) + 0.05)
            return response(page(start))

        runner = SearchRunner(
            SearchRunnerConfig("default", {"serpapi": 40}, 0.3, "google_light", {"serpapi": "fixture-key"}),
            build_provider_registry(), route_resolver=lambda _: {"serpapi"},
        )
        with mock.patch.object(search_runner, "_SEARCH_POOL", pool), \
                mock.patch.object(serpapi, "urlopen_retry", side_effect=http):
            try:
                rows = runner.run("query")
                self.assertTrue(second_started.is_set())
                hits = [row for row in rows if row.get("url")]
                self.assertEqual([row["provider_rank"] for row in hits], list(range(1, 11)))
                self.assertIn("timeout", rows[-1]["error"])
            finally:
                pool.shutdown(wait=True)
        self.assertEqual(starts, [0, 10])


if __name__ == "__main__":
    unittest.main()
