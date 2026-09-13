from concurrent.futures import ThreadPoolExecutor
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError

from multi_search_mcp.src import service
from multi_search_mcp.src.scrape.scrapers import firecrawl as firecrawl_scraper
from multi_search_mcp.src.state.key_state import (
    ACTIVE,
    COOLDOWN,
    INVALID,
    QUOTA_EXHAUSTED,
    TRANSIENT_INVALID,
    KeyOutcome,
    SQLiteKeyManager,
)
from multi_search_mcp.src.state.state_store import StateStore


URL = "https://example.com/article"
KEY = "fixture-firecrawl-key"


def response(payload: dict) -> io.BytesIO:
    return io.BytesIO(json.dumps(payload).encode())


class RecordingBody:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.read_sizes = []
        self.closed = False

    def read(self, size=-1):
        self.read_sizes.append(size)
        return self.payload if size < 0 else self.payload[:size]

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class FirecrawlTargetErrorTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="firecrawl-target-tests-")
        self.addCleanup(temp.cleanup)
        self.store = StateStore(Path(temp.name) / "state.sqlite")
        self.manager = SQLiteKeyManager(self.store)
        self.candidate = self.manager.candidates("firecrawl", [KEY])[0]
        self.keys = {"firecrawl": [KEY]}

    def test_ssl_target_error_preserves_in_flight_cooldown_and_reason(self):
        before = []

        def provider_response(*_args, **_kwargs):
            self.manager.record_result(
                "firecrawl",
                self.candidate,
                KeyOutcome(False, True, "rate_limit", "fixture HTTP 429"),
            )
            before.extend(self.manager.status_rows("firecrawl"))
            body = {
                "success": False,
                "code": "SCRAPE_SSL_ERROR",
                "error": "Page SSL certificate is invalid",
            }
            raise HTTPError(
                "https://api.firecrawl.dev/v2/scrape",
                500,
                "Internal Server Error",
                {},
                response(body),
            )

        with mock.patch.object(
            firecrawl_scraper, "urlopen_retry", side_effect=provider_response,
        ) as fetch:
            result = service.run_scrape(
                service.ScrapeRequest(url=URL, backends=["firecrawl"], output="json"),
                keys=self.keys,
                config={},
                state_store=self.store,
                url_resolver=lambda _host: ["93.184.216.34"],
            )["result"]

        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(result["error_origin"], "target")
        self.assertEqual(result["error_type"], "target")
        self.assertIn("SCRAPE_SSL_ERROR", result["error"])
        self.assertIn("Page SSL certificate is invalid", result["error"])
        self.assertEqual(self.manager.status_rows("firecrawl"), before)
        self.assertEqual(before[0]["status"], COOLDOWN)
        self.assertIsNotNone(before[0]["cooldown_until"])

    def test_known_target_error_in_success_envelope_is_neutral(self):
        payload = {
            "success": False,
            "code": "SCRAPE_SSL_ERROR",
            "error": "Page SSL certificate is invalid",
        }
        with mock.patch.object(
            firecrawl_scraper, "urlopen_retry", return_value=response(payload),
        ) as fetch:
            result = service.run_scrape(
                service.ScrapeRequest(url=URL, backends=["firecrawl"], output="json"),
                keys=self.keys,
                config={},
                state_store=self.store,
                url_resolver=lambda _host: ["93.184.216.34"],
            )["result"]

        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(result["error_origin"], "target")
        self.assertEqual(result["error_type"], "target")
        self.assertIn("Page SSL certificate is invalid", result["error"])
        self.assertEqual(self.manager.status_rows("firecrawl")[0]["status"], ACTIVE)
        self.assertEqual(self.manager.status_rows("firecrawl")[0]["failure_count"], 0)

    def test_target_error_does_not_overwrite_any_existing_key_state(self):
        cases = (
            (ACTIVE, KeyOutcome(False, False, "network", "fixture network"), 1),
            (TRANSIENT_INVALID, KeyOutcome(False, True, "invalid", "fixture invalid"), 1),
            (INVALID, KeyOutcome(False, True, "invalid", "fixture invalid"), 3),
            (COOLDOWN, KeyOutcome(False, True, "rate_limit", "fixture 429"), 1),
            (QUOTA_EXHAUSTED, KeyOutcome(False, True, "quota_exhausted", "fixture quota"), 1),
        )
        payload = {
            "success": False,
            "code": "SCRAPE_SSL_ERROR",
            "error": "Page SSL certificate is invalid",
        }
        for expected_status, outcome, repeats in cases:
            with self.subTest(expected_status=expected_status):
                self.manager.reset("firecrawl")
                before = []

                def provider_response(*_args, **_kwargs):
                    for _ in range(repeats):
                        self.manager.record_result("firecrawl", self.candidate, outcome)
                    before.extend(self.manager.status_rows("firecrawl"))
                    raise HTTPError(
                        "https://api.firecrawl.dev/v2/scrape",
                        500,
                        "Internal Server Error",
                        {},
                        response(payload),
                    )

                with mock.patch.object(
                    firecrawl_scraper, "urlopen_retry", side_effect=provider_response,
                ) as fetch:
                    result = service.run_scrape(
                        service.ScrapeRequest(url=URL, backends=["firecrawl"], output="json"),
                        keys=self.keys,
                        config={},
                        state_store=self.store,
                        url_resolver=lambda _host: ["93.184.216.34"],
                    )["result"]

                self.assertEqual(fetch.call_count, 1)
                self.assertEqual(result["error_origin"], "target")
                self.assertEqual(self.manager.status_rows("firecrawl"), before)
                self.assertEqual(before[0]["status"], expected_status)

    def test_provider_http_status_errors_rotate_and_keep_provider_classification(self):
        cases = (
            (401, "invalid", TRANSIENT_INVALID),
            (403, "invalid", TRANSIENT_INVALID),
            (402, "quota_exhausted", QUOTA_EXHAUSTED),
            (429, "rate_limit", COOLDOWN),
        )
        keys = [KEY, "fixture-firecrawl-second"]
        success = {"success": True, "data": {"markdown": "fixture body"}}
        for status_code, expected_type, expected_status in cases:
            with self.subTest(status_code=status_code):
                self.manager.reset("firecrawl")
                self.manager = SQLiteKeyManager(self.store)
                candidates = self.manager.candidates("firecrawl", keys)
                error = HTTPError(
                    "https://api.firecrawl.dev/v2/scrape",
                    status_code,
                    "provider failure",
                    {},
                    response({"success": False, "error": "provider failure"}),
                )
                with mock.patch.object(
                    firecrawl_scraper,
                    "urlopen_retry",
                    side_effect=[error, response(success)],
                ) as fetch:
                    result = service.run_scrape(
                        service.ScrapeRequest(url=URL, backends=["firecrawl"], output="json"),
                        keys={"firecrawl": keys},
                        config={},
                        state_store=self.store,
                        url_resolver=lambda _host: ["93.184.216.34"],
                    )["result"]

                self.assertEqual(fetch.call_count, 2)
                self.assertEqual(result["markdown"], "fixture body")
                failed = next(
                    row for row in self.manager.status_rows("firecrawl")
                    if row["key_id"] == candidates[0].key_id
                )
                self.assertEqual(failed["status"], expected_status)
                self.assertEqual(failed["last_error_type"], expected_type)
                self.assertNotEqual(result.get("error_origin"), "target")

    def test_unknown_codes_and_malformed_error_bodies_are_not_target(self):
        normal_payloads = (
            {"success": False, "code": "SCRAPE_SITE_ERROR", "error": "site error"},
            {"success": False, "error": "missing code"},
            {"success": False, "code": {"unexpected": True}, "error": "bad code"},
        )
        for payload in normal_payloads:
            with self.subTest(payload=payload):
                with mock.patch.object(
                    firecrawl_scraper, "urlopen_retry", return_value=response(payload),
                ):
                    result = firecrawl_scraper.scrape_url_firecrawl(URL, KEY)
                self.assertIn("error", result)
                self.assertNotEqual(result.get("error_origin"), "target")

        for body in (b"not json", json.dumps({"success": False, "error": "unknown"}).encode()):
            with self.subTest(body=body):
                error = HTTPError(
                    "https://api.firecrawl.dev/v2/scrape",
                    500,
                    "Internal Server Error",
                    {},
                    io.BytesIO(body),
                )
                with mock.patch.object(
                    firecrawl_scraper, "urlopen_retry", side_effect=error,
                ):
                    result = firecrawl_scraper.scrape_url_firecrawl(URL, KEY)
                self.assertIn("error", result)
                self.assertEqual(result["error_origin"], "provider")
                self.assertEqual(result["error_type"], "error")
                self.assertNotEqual(result.get("error_origin"), "target")

    def test_error_body_read_is_bounded_closed_and_redacted(self):
        body = RecordingBody(json.dumps({
            "success": False,
            "code": "SCRAPE_SSL_ERROR",
            "error": f"certificate detail contains {KEY}",
        }).encode())
        error = HTTPError(
            "https://api.firecrawl.dev/v2/scrape",
            500,
            "Internal Server Error",
            {},
            body,
        )
        with mock.patch.object(firecrawl_scraper, "urlopen_retry", side_effect=error):
            result = firecrawl_scraper.scrape_url_firecrawl(URL, KEY)

        self.assertEqual(result["error_origin"], "target")
        self.assertNotIn(KEY, json.dumps(result))
        self.assertEqual(body.read_sizes, [firecrawl_scraper._FIRECRAWL_ERROR_BODY_LIMIT])
        self.assertTrue(body.closed)

    def test_concurrent_target_error_keeps_rate_limit_cooldown(self):
        peer_url = URL + "/peer"
        target_entered = threading.Event()
        rate_recorded = threading.Event()

        def target_error(url):
            return HTTPError(
                "https://api.firecrawl.dev/v2/scrape",
                500,
                "Internal Server Error",
                {},
                response({
                    "success": False,
                    "code": "SCRAPE_SSL_ERROR",
                    "error": f"Page SSL certificate is invalid for {url}",
                }),
            )

        def provider_response(req, **_kwargs):
            requested_url = json.loads(req.data)["url"]
            if requested_url == URL:
                target_entered.set()
                if not rate_recorded.wait(5):
                    raise AssertionError("peer scrape did not record rate limit")
                raise target_error(requested_url)
            if not target_entered.wait(5):
                raise AssertionError("target scrape did not start")
            self.manager.record_result(
                "firecrawl",
                self.candidate,
                KeyOutcome(False, True, "rate_limit", "fixture HTTP 429"),
            )
            rate_recorded.set()
            raise target_error(requested_url)

        def scrape(url):
            return service.run_scrape(
                service.ScrapeRequest(url=url, backends=["firecrawl"], output="json"),
                keys=self.keys,
                config={},
                state_store=self.store,
                url_resolver=lambda _host: ["93.184.216.34"],
            )["result"]

        with mock.patch.object(
            firecrawl_scraper, "urlopen_retry", side_effect=provider_response,
        ) as fetch:
            with ThreadPoolExecutor(max_workers=2) as pool:
                target_future = pool.submit(scrape, URL)
                peer_future = pool.submit(scrape, peer_url)
                target_result = target_future.result(timeout=10)
                peer_result = peer_future.result(timeout=10)

        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(target_result["error_origin"], "target")
        self.assertEqual(peer_result["error_origin"], "target")
        row = self.manager.status_rows("firecrawl")[0]
        self.assertEqual(row["status"], COOLDOWN)
        self.assertEqual(row["rate_limit_count"], 1)
        self.assertEqual(row["failure_count"], 1)
        self.assertEqual(row["use_count"], 2)

    def test_successful_scrape_still_returns_markdown(self):
        payload = {
            "success": True,
            "data": {"markdown": "# Fixture", "metadata": {"title": "Fixture"}},
        }
        with mock.patch.object(
            firecrawl_scraper, "urlopen_retry", return_value=response(payload),
        ):
            result = firecrawl_scraper.scrape_url_firecrawl(URL, KEY)

        self.assertEqual(result["title"], "Fixture")
        self.assertEqual(result["markdown"], "# Fixture")
        self.assertEqual(result["length"], len("# Fixture"))
        self.assertEqual(result["via"], "firecrawl")


if __name__ == "__main__":
    unittest.main()
