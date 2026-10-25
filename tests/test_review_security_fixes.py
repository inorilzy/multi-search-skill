"""Regression tests for the Python review fixes (security and behaviour)."""
import io
import os
import ssl
import tempfile
import threading
import time
import unittest
import urllib.request
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.state.key_state import KeyOutcome, SQLiteKeyManager
from multi_search_mcp.src.state.site_memory import SiteScraperMemory, ScrapeAttempt
from multi_search_mcp.src.state.state_store import StateStore
from multi_search_mcp.src.support import http, url_security
from multi_search_mcp.src.support.concurrency import BoundedDaemonExecutor
from multi_search_mcp.src.scrape.stage import run_ranked_fetch_stage
from multi_search_mcp.src.support.url_security import (
    UrlSecurityError,
    validate_public_http_url,
)


def _process_worker(args):
    path, iterations = args
    manager = SQLiteKeyManager(StateStore(Path(path)))
    candidate = manager.candidates("exa", "process-key")[0]
    for _ in range(iterations):
        manager.record_use("exa", candidate)
        manager.record_result("exa", candidate, KeyOutcome(True, False))
    return True


class EmbeddedAddressTests(unittest.TestCase):
    def _resolver(self, mapping):
        return lambda host: list(mapping.get(host, []))

    def test_nat64_embedded_private_ipv4_is_rejected(self):
        with self.assertRaises(UrlSecurityError) as ctx:
            validate_public_http_url("https://[64:ff9b::a00:1]/", resolver=self._resolver({}))
        self.assertIn("private", str(ctx.exception))

    def test_6to4_embedded_private_ipv4_is_rejected(self):
        for address in ("2002:0a00:0001::", "2002:c0a8:0101::"):
            with self.subTest(address=address), self.assertRaises(UrlSecurityError):
                validate_public_http_url(f"https://[{address}]/", resolver=self._resolver({}))

    def test_nat64_embedded_public_ipv4_is_allowed(self):
        self.assertEqual(
            validate_public_http_url("https://[64:ff9b::5db8:d822]/", resolver=self._resolver({})),
            "https://[64:ff9b::5db8:d822]/",
        )

    def test_dns_answers_with_embedded_private_ipv4_are_rejected(self):
        resolver = self._resolver({"nat64.example": ["64:ff9b::a00:1"]})
        with self.assertRaises(UrlSecurityError):
            validate_public_http_url("https://nat64.example/", resolver=resolver)


class FakeIpCompatibilityTests(unittest.TestCase):
    """Clash/TUN fake-IP answers are accepted only behind an explicit opt-in."""

    FAKE_IP = "198.18.7.7"

    def setUp(self):
        self.resolver = lambda _host: [self.FAKE_IP]

    def test_fake_ip_is_rejected_by_default(self):
        with mock.patch.dict(os.environ, {url_security.FAKE_IP_ENV: ""}):
            with self.assertRaises(UrlSecurityError):
                validate_public_http_url("https://clash.example/page", resolver=self.resolver)

    def test_fake_ip_is_allowed_when_opted_in(self):
        with mock.patch.dict(os.environ, {url_security.FAKE_IP_ENV: "1"}):
            self.assertEqual(
                validate_public_http_url("https://clash.example/page", resolver=self.resolver),
                "https://clash.example/page",
            )

    def test_fake_ip_opt_in_never_allows_a_literal_ip(self):
        with mock.patch.dict(os.environ, {url_security.FAKE_IP_ENV: "1"}):
            with self.assertRaises(UrlSecurityError):
                validate_public_http_url(f"https://{self.FAKE_IP}/page")

    def test_connect_address_check_accepts_fake_ip_only_when_opted_in(self):
        with mock.patch.object(http, "_configured_proxy_addresses", return_value=set()):
            with mock.patch.dict(os.environ, {url_security.FAKE_IP_ENV: ""}):
                with self.assertRaises(UrlSecurityError):
                    http._ensure_connect_address(self.FAKE_IP, resolved=True)
            with mock.patch.dict(os.environ, {url_security.FAKE_IP_ENV: "1"}):
                http._ensure_connect_address(self.FAKE_IP, resolved=True)


class HttpHardeningTests(unittest.TestCase):
    def test_post_is_not_retried_after_ssl_eof(self):
        request = urllib.request.Request(
            "https://api.example/charge", data=b"{}", method="POST",
        )
        with mock.patch.object(
            http._shared_opener, "open", side_effect=ssl.SSLEOFError("synthetic EOF"),
        ) as opened:
            with self.assertRaises(ssl.SSLEOFError):
                http.urlopen_retry(request, timeout=2)
        self.assertEqual(opened.call_count, 1)

    def test_get_still_retries_after_ssl_eof(self):
        with mock.patch.object(
            http._shared_opener, "open", side_effect=ssl.SSLEOFError("synthetic EOF"),
        ) as opened:
            with self.assertRaises(ssl.SSLEOFError):
                http.urlopen_retry("https://93.184.216.34/", timeout=2)
        self.assertEqual(opened.call_count, 3)

    def test_read_limited_rejects_oversized_body(self):
        response = io.BytesIO(b"x" * 11)
        with self.assertRaisesRegex(ValueError, "10-byte size cap"):
            http.read_limited(response, max_bytes=10)

    def test_gunzip_limited_rejects_compression_bomb(self):
        import gzip
        payload = gzip.compress(b"x" * 1000)
        with self.assertRaisesRegex(ValueError, "100-byte size cap"):
            http.decompress_limited(payload, "gzip", max_bytes=100)


class RunAllBeforeDeadlineTests(unittest.TestCase):
    def test_deadline_returns_timeout_rows_without_waiting_for_slow_tasks(self):
        pool = BoundedDaemonExecutor(max_workers=1, thread_name_prefix="test-deadline")
        release = threading.Event()
        started = time.monotonic()
        try:
            result = run_ranked_fetch_stage(
                [{"source_id": "a"}, {"source_id": "b"}],
                timeout=0.05, concurrency=1, executor=pool,
                fetch=lambda hit, remaining: (release.wait(1), hit)[1],
            )
        finally:
            elapsed = time.monotonic() - started
            release.set()
            pool.shutdown(wait=False, cancel_futures=True)
        self.assertLess(elapsed, 0.18)
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual([row["source_id"] for row in result["errors"]], ["a", "b"])
        for row in result["errors"]:
            self.assertIn("timeout", row["error"])



class SiteMemoryPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = StateStore(Path(self.temp.name) / "state.sqlite")
        self.memory = SiteScraperMemory(self.store)

    def test_query_tokens_are_not_persisted(self):
        self.memory.record_attempt(ScrapeAttempt(
            url="https://example.com/article?token=super-secret#frag",
            scraper="jina", success=True, content_length=900,
            error_message="request failed: api_key=super-secret",
        ))
        attempts = self.store.rows("SELECT * FROM scrape_attempts")
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["url"], "https://example.com/")
        stats = self.store.rows("SELECT * FROM site_scraper_stats")
        self.assertEqual(stats[0]["sample_url"], "https://example.com/")

    def test_error_message_is_scrubbed(self):
        self.memory.record_attempt(ScrapeAttempt(
            url="https://example.com/a", scraper="jina", success=False,
            error_message="HTTP 401: Authorization: Bearer secret-token-value",
        ))
        stored = self.store.rows("SELECT * FROM scrape_attempts")[0]
        self.assertNotIn("secret-token-value", stored["error_message"])

    def test_attempt_history_is_bounded_per_site(self):
        from multi_search_mcp.src.state import site_memory as module
        with mock.patch.object(module, "MAX_ATTEMPTS_PER_SITE", 5):
            for index in range(12):
                self.memory.record_attempt(ScrapeAttempt(
                    url=f"https://example.com/{index}", scraper="jina",
                    success=True, content_length=900,
                ))
        self.assertEqual(len(self.store.rows("SELECT * FROM scrape_attempts")), 5)

    def test_old_attempts_are_purged(self):
        self.memory.record_attempt(ScrapeAttempt(
            url="https://example.com/old", scraper="jina", success=True,
            content_length=900,
        ))
        self.store.execute(
            "UPDATE scrape_attempts SET created_at = '2000-01-01T00:00:00+00:00'"
        )
        self.memory.record_attempt(ScrapeAttempt(
            url="https://example.com/new", scraper="jina", success=True,
            content_length=900,
        ))
        urls = [row["url"] for row in self.store.rows("SELECT * FROM scrape_attempts")]
        self.assertEqual(urls, ["https://example.com/"])


class MultiProcessStateStoreTests(unittest.TestCase):
    def test_concurrent_processes_share_key_state_without_lock_errors(self):
        workers, iterations = 4, 10
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state.sqlite"
            StateStore(path)  # create schema once
            with ProcessPoolExecutor(max_workers=workers) as pool:
                list(pool.map(
                    _process_worker,
                    [(str(path), iterations)] * workers,
                    chunksize=1,
                ))
            manager = SQLiteKeyManager(StateStore(path))
            row = manager.status_rows("exa")[0]
            self.assertEqual(row["use_count"], workers * iterations)
            self.assertEqual(row["success_count"], workers * iterations)
            self.assertEqual(row["failure_count"], 0)


class KeyStatePreservationTests(unittest.TestCase):
    def test_neutral_failure_does_not_downgrade_quota_state(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        manager = SQLiteKeyManager(StateStore(Path(temp.name) / "state.sqlite"))
        candidate = manager.candidates("exa", "k")[0]
        manager.record_result("exa", candidate, KeyOutcome(False, True, "quota_exhausted", "quota"))
        before = manager.status_rows("exa")[0]
        manager.record_result("exa", candidate, KeyOutcome(False, False, "timeout", "timed out"))
        after = manager.status_rows("exa")[0]
        self.assertEqual(after["status"], "quota_exhausted")
        self.assertEqual(after["exhausted_until"], before["exhausted_until"])
        self.assertEqual(after["failure_count"], before["failure_count"] + 1)


if __name__ == "__main__":
    unittest.main()
