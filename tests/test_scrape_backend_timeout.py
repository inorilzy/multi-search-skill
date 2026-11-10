"""One hung scrape backend must not spend the whole page budget (scrape_backend_timeout)."""
import threading
import time
import unittest
from unittest import mock

from multi_search_mcp.src import log_viewer
from multi_search_mcp.src.scrape import scrape
from multi_search_mcp.src.scrape.service import run_scrape_raw
from multi_search_mcp.src.search.resolve import SearchPlanRequest, resolve_search_plan
from multi_search_mcp.src.support.config import ConfigError, resolve_backend_timeout
from multi_search_mcp.src.support.requests import ScrapeRequest

URL = "https://example.com/article"


class BackendTimeoutTests(unittest.TestCase):
    def _scrape(self, config, *, jina_sleep_cap):
        calls = []
        never_answers = threading.Event()

        def jina(url, key="", timeout=0, **kwargs):
            # A stuck upstream: it only gives up when its own timeout expires.
            calls.append(("jina", round(float(timeout), 2)))
            never_answers.wait(min(float(timeout), jina_sleep_cap))
            return {"url": url, "error": "Jina: The read operation timed out"}

        def firecrawl(url, key="", timeout=0, deadline=None):
            calls.append(("firecrawl", round(float(timeout), 2)))
            return {"url": url, "markdown": "fallback body"}

        with (
            mock.patch.object(scrape, "_jina_anonymous_cooling_down", return_value=False),
            mock.patch.object(scrape, "scrape_url_jina", side_effect=jina),
            mock.patch.object(scrape, "scrape_url_firecrawl", side_effect=firecrawl),
        ):
            started = time.monotonic()
            result, _updates, _chars = run_scrape_raw(
                ScrapeRequest(url=URL, timeout=30, use_state=False),
                keys={}, config={"scrape_backends": ["jina", "firecrawl"], **config},
            )
        return result, calls, time.monotonic() - started

    def test_a_hung_backend_is_cut_off_and_the_next_backend_runs(self):
        result, calls, elapsed = self._scrape({"scrape_backend_timeout": 1}, jina_sleep_cap=5)
        self.assertEqual(result.get("markdown"), "fallback body")
        self.assertEqual([name for name, _ in calls], ["jina", "firecrawl"])
        self.assertLessEqual(calls[0][1], 1.0)
        self.assertLess(elapsed, 3.0)
        self.assertLessEqual(calls[1][1], 1.0, "every backend gets the same cap")

    def test_default_cap_is_ten_seconds(self):
        _result, calls, _elapsed = self._scrape({}, jina_sleep_cap=0)
        self.assertLessEqual(calls[0][1], 10.0)
        self.assertEqual(resolve_backend_timeout({}), 10)

    def test_invalid_values_fail_before_any_search(self):
        for bad in (0, 61, -3, True, "abc"):
            with self.subTest(value=bad):
                with self.assertRaises(ConfigError):
                    resolve_backend_timeout({"scrape_backend_timeout": bad})
                with self.assertRaises((ConfigError, ValueError)):
                    resolve_search_plan(SearchPlanRequest(), {"scrape_backend_timeout": bad})
        self.assertEqual(resolve_backend_timeout({"scrape_backend_timeout": 60}), 60)


class ViewerTimeoutLabelTests(unittest.TestCase):
    def test_a_timed_out_backend_is_shown_as_timeout(self):
        run = "run_000000000001"
        events = [
            {"run_id": run, "event": "scrape_chain", "url": URL, "t_ms": 0, "order": ["jina", "exa"]},
            {"run_id": run, "event": "scrape_attempt", "url": URL, "backend": "jina", "status": "error",
             "elapsed_ms": 10_000, "error": "Jina: The read operation timed out"},
            {"run_id": run, "event": "scrape_attempt", "url": URL, "backend": "exa", "status": "ok",
             "elapsed_ms": 400},
        ]
        page = log_viewer.build_detail(run, events)["fetches"][0]
        self.assertEqual([(a["backend"], a["status"]) for a in page["attempts"]],
                         [("jina", "timeout"), ("exa", "ok")])


if __name__ == "__main__":
    unittest.main()
