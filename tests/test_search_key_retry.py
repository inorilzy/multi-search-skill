import json
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from multi_search_mcp.src.search.registry import build_provider_registry
from multi_search_mcp.src.search import search_runner
from multi_search_mcp.src.search.search_runner import (
    SearchRunner,
    SearchRunnerConfig,
    run_keyed_source,
)
from multi_search_mcp.src.search.searchers import serpapi
from multi_search_mcp.src.service import SearchWebRequest, _run_search_candidates
from multi_search_mcp.src.state.key_state import BasicKeyManager, SQLiteKeyManager
from multi_search_mcp.src.state.state_store import StateStore


def _response(payload):
    response = mock.MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = json.dumps(payload).encode()
    return response


def _page(start: int, count: int = 10):
    return {
        "organic_results": [
            {"title": f"hit {index}", "link": f"https://example.com/{index}"}
            for index in range(start, start + count)
        ]
    }


def _page_for(indices):
    return {
        "organic_results": [
            {"title": f"hit {index}", "link": f"https://example.com/{index}"}
            for index in indices
        ]
    }


class SearchKeyRetryTests(unittest.TestCase):
    def _runner(self, manager):
        config = SearchRunnerConfig(
            route="default",
            counts={"serpapi": 20},
            timeout=10,
            serpapi_engine="google",
            keys={"serpapi": ["fixture-serp-1", "fixture-serp-2"]},
        )
        return SearchRunner(
            config,
            build_provider_registry(),
            route_resolver=lambda _route: {"serpapi"},
            key_manager=manager,
        )

    def test_partial_candidates_survive_successful_empty_retry(self):
        for stateful in (False, True):
            with self.subTest(stateful=stateful), TemporaryDirectory() as temp:
                manager = (
                    SQLiteKeyManager(StateStore(Path(temp) / "state.sqlite"))
                    if stateful else BasicKeyManager()
                )
                calls = []

                def http(url, **_kwargs):
                    query = parse_qs(urlsplit(url).query)
                    key = query["api_key"][0]
                    start = int(query.get("start", [0])[0])
                    calls.append((key, start))
                    if key == "fixture-serp-1" and start == 0:
                        return _response(_page(0))
                    if key == "fixture-serp-1":
                        return _response({"error": "quota exhausted"})
                    return _response({"organic_results": []})

                with mock.patch.object(serpapi, "urlopen_retry", side_effect=http):
                    rows = self._runner(manager).run("fixture")

                hits = [row for row in rows if row.get("url")]
                self.assertEqual(calls, [
                    ("fixture-serp-1", 0),
                    ("fixture-serp-1", 10),
                    ("fixture-serp-2", 0),
                ])
                self.assertEqual([row["url"] for row in hits], [
                    f"https://example.com/{index}" for index in range(10)
                ])
                self.assertEqual(
                    [row["provider_rank"] for row in hits], list(range(1, 11))
                )
                self.assertFalse(any(row.get("_empty") for row in rows))

    def test_retry_candidates_are_deduplicated_without_extra_provider_weight(self):
        scenarios = {
            "overlap": {
                0: _page_for([10, 11, 12, 13, 14, 0, 1, 2, 3, 4]),
                10: {"organic_results": []},
            },
            "complete": {
                0: _page(0),
                10: _page(10),
            },
        }
        for name, second_key_pages in scenarios.items():
            with self.subTest(name=name):
                calls = []

                def http(url, **_kwargs):
                    query = parse_qs(urlsplit(url).query)
                    key = query["api_key"][0]
                    start = int(query.get("start", [0])[0])
                    calls.append((key, start))
                    if key == "fixture-serp-1" and start == 0:
                        return _response(_page(0))
                    if key == "fixture-serp-1":
                        return _response({"error": "quota exhausted"})
                    return _response(second_key_pages[start])

                with mock.patch.object(serpapi, "urlopen_retry", side_effect=http):
                    rows = self._runner(BasicKeyManager()).run("fixture")

                hits = [row for row in rows if row.get("url")]
                expected_count = 15 if name == "overlap" else 20
                expected_ranks = (
                    list(range(1, 11)) + list(range(1, 6))
                    if name == "overlap"
                    else list(range(1, expected_count + 1))
                )
                self.assertEqual(len(hits), expected_count)
                self.assertEqual(
                    [row["url"] for row in hits],
                    [f"https://example.com/{index}" for index in range(expected_count)],
                )
                self.assertEqual(
                    [row["provider_rank"] for row in hits],
                    expected_ranks,
                )
                self.assertEqual(
                    len({row["url"] for row in hits}), expected_count
                )
                self.assertEqual(calls[0:2], [
                    ("fixture-serp-1", 0),
                    ("fixture-serp-1", 10),
                ])

    def test_later_key_failure_and_deadline_keep_partial_candidates(self):
        candidate = {
            "source": "serpapi",
            "title": "partial",
            "url": "https://example.com/partial",
        }
        calls = []

        def call_with_key(key):
            calls.append(key)
            if key == "fixture-serp-1":
                time.sleep(0.02)
                return [candidate, {"source": "serpapi", "error": "quota exhausted"}]
            return [{"source": "serpapi", "error": "quota exhausted"}]

        rows = run_keyed_source(
            "serpapi",
            ["fixture-serp-1", "fixture-serp-2"],
            call_with_key,
            deadline=time.monotonic() + 0.005,
            key_manager=BasicKeyManager(),
        )

        self.assertEqual(calls, ["fixture-serp-1"])
        self.assertEqual(
            [row["url"] for row in rows if row.get("url")],
            [candidate["url"]],
        )
        self.assertTrue(any(row.get("error") for row in rows))

    def test_provider_diagnostics_count_preserved_candidates_not_empty_retry(self):
        def http(url, **_kwargs):
            query = parse_qs(urlsplit(url).query)
            key = query["api_key"][0]
            start = int(query.get("start", [0])[0])
            if key == "fixture-serp-1" and start == 0:
                return _response(_page(0))
            if key == "fixture-serp-1":
                return _response({"error": "quota exhausted"})
            return _response({"organic_results": []})

        request = SearchWebRequest(
            query="fixture",
            sources=["serpapi"],
            count=20,
            use_state=False,
        )
        with mock.patch.object(serpapi, "urlopen_retry", side_effect=http):
            response = _run_search_candidates(
                request,
                keys={"serpapi": ["fixture-serp-1", "fixture-serp-2"]},
                config={},
            )

        self.assertEqual(len(response["results"]), 10)
        self.assertEqual(response["diagnostics"]["raw_result_count"], 10)
        self.assertEqual(response["diagnostics"]["candidate_count"], 10)
        self.assertEqual(response["provider_status"], [{
            "source": "serpapi",
            "status": "ok",
            "raw_hits": 10,
            "errors": [],
        }])
        self.assertEqual(response["errors"], [])

    def test_deadline_snapshot_merges_candidates_published_by_each_key(self):
        started = threading.Event()
        pool = search_runner.BoundedDaemonExecutor(
            max_workers=1, thread_name_prefix="test-serpapi-key-deadline"
        )

        def http(url, **_kwargs):
            query = parse_qs(urlsplit(url).query)
            key = query["api_key"][0]
            start = int(query.get("start", [0])[0])
            if key == "fixture-serp-1" and start == 0:
                return _response(_page(0))
            if key == "fixture-serp-1":
                return _response({"error": "quota exhausted"})
            if start == 0:
                return _response(_page(10))
            started.set()
            time.sleep(0.2)
            return _response({"organic_results": []})

        runner = self._runner(BasicKeyManager())
        runner.config.timeout = 0.1
        with mock.patch.object(search_runner, "_SEARCH_POOL", pool), \
                mock.patch.object(serpapi, "urlopen_retry", side_effect=http):
            try:
                rows = runner.run("fixture")
                self.assertTrue(started.is_set())
            finally:
                pool.shutdown(wait=True)

        hits = [row for row in rows if row.get("url")]
        self.assertEqual(
            [row["url"] for row in hits],
            [f"https://example.com/{index}" for index in range(20)],
        )
        self.assertTrue(any(row.get("error") for row in rows))


if __name__ == "__main__":
    unittest.main()
