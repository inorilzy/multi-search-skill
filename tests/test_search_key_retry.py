import json
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
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
from multi_search_mcp.src.service import SearchWebRequest, run_search_candidates
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

    def test_quota_error_on_first_key_rotates_to_the_next_key(self):
        # SerpAPI fetches one page; a 429 "run out of searches" on the first
        # key is a quota signal, so the runner retries with the next key.
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
                    calls.append((key, int(query.get("start", [0])[0])))
                    if key == "fixture-serp-1":
                        return _response({"error": "Your account has run out of searches."})
                    return _response(_page(0))

                with mock.patch.object(serpapi, "urlopen_retry", side_effect=http):
                    rows = self._runner(manager).run("fixture")

                hits = [row for row in rows if row.get("url")]
                self.assertEqual(calls, [("fixture-serp-1", 0), ("fixture-serp-2", 0)])
                self.assertEqual([row["url"] for row in hits],
                                 [f"https://example.com/{index}" for index in range(10)])
                self.assertEqual([row["provider_rank"] for row in hits], list(range(1, 11)))
                self.assertFalse(any(row.get("error") for row in rows))

    def test_later_key_failure_and_deadline_keep_partial_candidates(self):
        candidate = {
            "source": "serpapi",
            "title": "partial",
            "url": "https://example.com/partial",
        }
        calls = []
        clock = SimpleNamespace(now=100.0)
        clock.monotonic = lambda: clock.now

        def call_with_key(key):
            calls.append(key)
            if key == "fixture-serp-1":
                clock.now += 0.02  # the first key call outlives the deadline
                return [candidate, {"source": "serpapi", "error": "quota exhausted"}]
            return [{"source": "serpapi", "error": "quota exhausted"}]

        with mock.patch.object(search_runner, "time", clock):
            rows = run_keyed_source(
                "serpapi",
                ["fixture-serp-1", "fixture-serp-2"],
                call_with_key,
                deadline=clock.now + 0.005,
                key_manager=BasicKeyManager(),
            )

        self.assertEqual(calls, ["fixture-serp-1"])
        self.assertEqual(
            [row["url"] for row in rows if row.get("url")],
            [candidate["url"]],
        )
        self.assertTrue(any(row.get("error") for row in rows))

    def test_provider_diagnostics_count_the_single_page_of_candidates(self):
        def http(url, **_kwargs):
            return _response(_page(0))

        request = SearchWebRequest(query="fixture", sources=["serpapi"], count=20, use_state=False)
        with mock.patch.object(serpapi, "urlopen_retry", side_effect=http):
            response = run_search_candidates(
                request, keys={"serpapi": ["fixture-serp-1", "fixture-serp-2"]}, config={},
            )

        self.assertEqual(len(response["results"]), 10)
        self.assertEqual(response["diagnostics"]["raw_result_count"], 10)
        self.assertEqual(response["provider_status"], [{
            "source": "serpapi", "status": "ok", "raw_hits": 10, "errors": [],
        }])
        self.assertEqual(response["errors"], [])


if __name__ == "__main__":
    unittest.main()
