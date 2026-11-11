"""Scrape-stage key rotation, causal recording, and channel fallbacks (ticket 09)."""
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from multi_search_mcp.src import service
from multi_search_mcp.src.scrape import scrape
from multi_search_mcp.src.scrape.scrape import (
    ScrapeContext,
    keys_for_backend,
    scrape_url_smart,
)
from multi_search_mcp.src.state import key_state
from multi_search_mcp.src.state.key_state import (
    INVALID,
    QUOTA_EXHAUSTED,
    KeyOutcome,
    SQLiteKeyManager,
    key_id_for,
)
from multi_search_mcp.src.state.state_store import StateStore
from multi_search_mcp.src.support.requests import ScrapeRequest


URL = "https://example.com/article"
BASE = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)
QUOTA = KeyOutcome(False, True, "quota_exhausted", "fixture quota exhausted")
INVALID_OUTCOME = KeyOutcome(False, True, "invalid", "fixture HTTP 401 unauthorized")


class _StateTestCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="scrape-key-rotation-")
        self.addCleanup(temp.cleanup)
        self.store = StateStore(Path(temp.name) / "state.sqlite")
        self.manager = SQLiteKeyManager(self.store)


class ConcurrentKeyDistributionTests(_StateTestCase):
    def test_five_concurrent_scrapes_use_five_distinct_keys(self):
        keys = [f"firecrawl-key-{index}" for index in range(5)]
        candidates = self.manager.candidates("firecrawl", keys)
        started_together = threading.Barrier(5)
        used = []
        used_lock = threading.Lock()

        def fake_firecrawl(url, key="", timeout=0):
            with used_lock:
                used.append(key)
            # Hold every worker until all five attempts have reserved a key.
            started_together.wait(timeout=5)
            return {"url": url, "markdown": f"body for {key}", "via": "firecrawl"}

        context = ScrapeContext(
            keys_by_backend={"firecrawl": candidates},
            key_manager=self.manager,
            backends=("firecrawl",),
        )
        with mock.patch.object(scrape, "scrape_url_firecrawl", side_effect=fake_firecrawl):
            with ThreadPoolExecutor(max_workers=5) as pool:
                results = list(pool.map(lambda _index: scrape_url_smart(URL, ctx=context), range(5)))

        self.assertTrue(all("error" not in result for result in results))
        self.assertEqual(sorted(used), sorted(keys))
        rows = {row["key_id"]: row for row in self.manager.status_rows("firecrawl")}
        self.assertEqual(
            [rows[key_id_for("firecrawl", key)]["use_count"] for key in keys],
            [1, 1, 1, 1, 1],
        )


class LeastRecentlyUsedTests(_StateTestCase):
    def test_successive_scrapes_use_the_least_recently_used_key(self):
        keys = ["firecrawl-key-a", "firecrawl-key-b"]
        used = []

        def fake_firecrawl(url, key="", timeout=0):
            used.append(key)
            return {"url": url, "markdown": f"body for {key}", "via": "firecrawl"}

        def run_once():
            result, _updates, _chars = service.run_scrape_raw(
                ScrapeRequest(url=URL),
                state_store=self.store,
                keys={"firecrawl": keys},
                config={"scrape_backends": ["firecrawl"]},
            )
            self.assertNotIn("error", result)

        with mock.patch.object(scrape, "scrape_url_firecrawl", side_effect=fake_firecrawl):
            run_once()
            run_once()

        self.assertEqual(used, keys)


class RemovedDeadOptionTests(unittest.TestCase):
    def test_jina_prefer_keyed_keyword_is_no_longer_accepted(self):
        with self.assertRaises(TypeError):
            scrape_url_smart(URL, jina_prefer_keyed=True)


class LateSuccessTests(_StateTestCase):
    def _scrape_while_recording(self, record_failure):
        candidate = self.manager.candidates("firecrawl", ["firecrawl-key"])[0]
        clock = {"now": BASE}

        def fake_firecrawl(url, key="", timeout=0):
            record_failure(clock)
            return {"url": url, "markdown": "late success", "via": "firecrawl"}

        context = ScrapeContext(
            keys_by_backend={"firecrawl": [candidate]},
            key_manager=self.manager,
            backends=("firecrawl",),
        )
        with (
            mock.patch.object(key_state, "_now", side_effect=lambda: clock["now"]),
            mock.patch.object(scrape, "_now", side_effect=lambda: clock["now"]),
            mock.patch.object(scrape, "scrape_url_firecrawl", side_effect=fake_firecrawl),
        ):
            result = scrape_url_smart(URL, ctx=context)
        self.assertNotIn("error", result)
        return self.manager.status_rows("firecrawl")[0]

    def test_late_success_keeps_quota_exhausted_recorded_during_the_request(self):
        def record_quota(clock):
            clock["now"] = BASE + timedelta(seconds=2)
            self.manager.record_result(
                "firecrawl", self.manager.candidates("firecrawl", ["firecrawl-key"])[0], QUOTA,
            )
            clock["now"] = BASE + timedelta(seconds=3)

        row = self._scrape_while_recording(record_quota)

        self.assertEqual(row["status"], QUOTA_EXHAUSTED)
        self.assertIsNotNone(row["exhausted_until"])
        self.assertEqual(row["success_count"], 1)

    def test_late_success_keeps_invalid_status_recorded_during_the_request(self):
        def record_invalid(clock):
            candidate = self.manager.candidates("firecrawl", ["firecrawl-key"])[0]
            for offset in range(3):
                clock["now"] = BASE + timedelta(seconds=offset + 1)
                self.manager.record_result("firecrawl", candidate, INVALID_OUTCOME)
            clock["now"] = BASE + timedelta(seconds=5)

        row = self._scrape_while_recording(record_invalid)

        self.assertEqual(row["status"], INVALID)
        self.assertEqual(row["invalid_strikes"], 3)


class AnonymousJinaKeyRetryTests(unittest.TestCase):
    def _scrape(self, anonymous_result):
        used = []

        def fake_jina(url, key="", timeout=0, **kwargs):
            used.append(key)
            if key == "":
                return {"url": url, **anonymous_result}
            return {"url": url, "markdown": "keyed body", "via": "jina"}

        context = ScrapeContext(
            keys_by_backend={"jina": keys_for_backend("jina", "jina-key")},
            backends=("jina",),
        )
        with (
            mock.patch.object(scrape, "_jina_anonymous_cooling_down", return_value=False),
            mock.patch.object(scrape, "scrape_url_jina", side_effect=fake_jina),
        ):
            result = scrape_url_smart(URL, ctx=context)
        return result, used

    def test_anonymous_403_retries_the_configured_key_once(self):
        result, used = self._scrape({"error": "Jina: HTTP 403: Forbidden"})
        self.assertEqual(used, ["", "jina-key"])
        self.assertEqual(result["markdown"], "keyed body")

    def test_anonymous_5xx_retries_the_configured_key_once(self):
        result, used = self._scrape({"error": "Jina: HTTP 503: Service Unavailable"})
        self.assertEqual(used, ["", "jina-key"])
        self.assertEqual(result["markdown"], "keyed body")

    def test_anonymous_timeout_retries_the_configured_key_once(self):
        result, used = self._scrape({"error": "Jina: The read operation timed out"})
        self.assertEqual(used, ["", "jina-key"])
        self.assertEqual(result["markdown"], "keyed body")

    def test_anonymous_security_block_retries_the_configured_key_once(self):
        result, used = self._scrape({
            "error": "Jina: blocked by website security verification",
        })
        self.assertEqual(used, ["", "jina-key"])
        self.assertEqual(result["markdown"], "keyed body")

    def test_anonymous_rate_limit_still_retries_the_configured_key(self):
        result, used = self._scrape({
            "error": "Jina: HTTP 429 rate limit", "rate_limited": True,
        })
        self.assertEqual(used, ["", "jina-key"])
        self.assertEqual(result["markdown"], "keyed body")

    def test_anonymous_ordinary_error_does_not_use_the_key(self):
        result, used = self._scrape({"error": "Jina: HTTP 404: Not Found"})
        self.assertEqual(used, [""])
        self.assertIn("error", result)


class FirecrawlKeyPoolTests(_StateTestCase):
    def _scrape(self, keys):
        calls = []

        def fake_firecrawl(url, key="", timeout=0):
            calls.append(key)
            return {"url": url, "markdown": f"body for {key}", "via": "firecrawl"}

        with mock.patch.object(scrape, "scrape_url_firecrawl", side_effect=fake_firecrawl):
            result = service.run_scrape(
                ScrapeRequest(url=URL, backends=["firecrawl"], output="json"),
                keys=keys,
                config={},
                state_store=self.store,
            )["result"]
        return result, calls

    def test_all_keys_quota_exhausted_reports_error_without_anonymous_request(self):
        candidate = self.manager.candidates("firecrawl", "firecrawl-key")[0]
        self.manager.record_result("firecrawl", candidate, QUOTA)

        result, calls = self._scrape({"firecrawl": ["firecrawl-key"]})

        self.assertEqual(calls, [])
        self.assertIn("all configured keys are unavailable", result["error"])

    def test_all_keys_invalid_reports_error_without_anonymous_request(self):
        candidate = self.manager.candidates("firecrawl", "firecrawl-key")[0]
        for _ in range(3):
            self.manager.record_result("firecrawl", candidate, INVALID_OUTCOME)

        result, calls = self._scrape({"firecrawl": ["firecrawl-key"]})

        self.assertEqual(calls, [])
        self.assertIn("all configured keys are unavailable", result["error"])

    def test_an_available_key_is_used_when_another_is_unavailable(self):
        candidates = self.manager.candidates(
            "firecrawl", ["firecrawl-exhausted", "firecrawl-healthy"],
        )
        self.manager.record_result("firecrawl", candidates[0], QUOTA)

        result, calls = self._scrape({
            "firecrawl": ["firecrawl-exhausted", "firecrawl-healthy"],
        })

        self.assertEqual(calls, ["firecrawl-healthy"])
        self.assertNotIn("error", result)

    def test_no_configured_key_still_uses_the_anonymous_channel(self):
        result, calls = self._scrape({})
        self.assertEqual(calls, [""])
        self.assertNotIn("error", result)


if __name__ == "__main__":
    unittest.main()
