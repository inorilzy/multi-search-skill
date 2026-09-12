from contextlib import ExitStack
import io
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError

from multi_search_mcp.src import service
from multi_search_mcp.src.scrape.scrapers import tavily as extract_adapter
from multi_search_mcp.src.search.searchers import tavily as search_adapter
from multi_search_mcp.src.state.key_state import (
    COOLDOWN,
    QUOTA_EXHAUSTED,
    TRANSIENT_INVALID,
    key_id_for,
)
from multi_search_mcp.src.state.state_store import StateStore


URL = "https://example.com/article"
KEYS = ["fixture-tavily-first", "fixture-tavily-second"]


def response(payload):
    return io.BytesIO(json.dumps(payload).encode())


def quota_body(message="Plan usage limit exceeded"):
    return response({"detail": {"error": message}})


def http_error(url, code, reason="", body=None):
    return HTTPError(url, code, reason, {}, body)


class TrackingBody(io.BytesIO):
    def __init__(self, value):
        super().__init__(value)
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)


class TavilyQuotaErrorTests(unittest.TestCase):
    def setUp(self):
        self.network_guard = ExitStack()
        self.network_guard.enter_context(mock.patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("unexpected real HTTP request"),
        ))
        self.network_guard.enter_context(mock.patch(
            "socket.getaddrinfo",
            side_effect=AssertionError("unexpected real DNS lookup"),
        ))
        self.addCleanup(self.network_guard.close)

    def _call_adapter(self, operation, error):
        if operation == "search":
            with mock.patch.object(search_adapter, "urlopen_retry", side_effect=error):
                return search_adapter.search_tavily("fixture", KEYS[0], timeout=1)[0]
        with mock.patch.object(extract_adapter, "urlopen_retry", side_effect=error):
            return extract_adapter.scrape_url_tavily(URL, KEYS[0], timeout=1)

    def test_432_and_433_are_quota_errors_for_both_adapters(self):
        for operation in ("search", "extract"):
            for code in (432, 433):
                for reason in ("", "Forbidden", "quota exceeded"):
                    with self.subTest(operation=operation, code=code, reason=reason):
                        error = http_error(
                            f"https://api.tavily.com/{operation}",
                            code,
                            reason,
                            quota_body(),
                        )
                        result = self._call_adapter(operation, error)
                        self.assertEqual(result["error_origin"], "provider")
                        self.assertEqual(result["error_type"], "quota_exhausted")
                        self.assertIn(str(code), result["error"])
                        self.assertIn("Plan usage limit exceeded", result["error"])

    def test_status_code_classification_survives_empty_or_invalid_body(self):
        expected = {
            400: "error",
            401: "invalid",
            403: "invalid",
            429: "rate_limit",
            432: "quota_exhausted",
            433: "quota_exhausted",
        }
        for operation in ("search", "extract"):
            for code, error_type in expected.items():
                for body in (None, io.BytesIO(b""), io.BytesIO(b"not-json")):
                    with self.subTest(operation=operation, code=code, body=body is not None):
                        result = self._call_adapter(
                            operation,
                            http_error(
                                f"https://api.tavily.com/{operation}",
                                code,
                                "Forbidden quota",
                                body,
                            ),
                        )
                        self.assertEqual(result["error_origin"], "provider")
                        self.assertEqual(result["error_type"], error_type)

    def test_error_body_is_bounded_and_redacted(self):
        secret = KEYS[0]
        body = TrackingBody(
            json.dumps({"detail": {"error": f"quota {secret} " + "x" * 20_000}}).encode()
        )
        result = self._call_adapter(
            "search",
            http_error("https://api.tavily.com/search", 432, "", body),
        )
        self.assertTrue(body.read_sizes)
        self.assertGreater(body.read_sizes[0], 0)
        self.assertLessEqual(body.read_sizes[0], 4096)
        self.assertNotIn(secret, result["error"])

    def test_search_and_extract_rotate_keys_and_record_status_categories(self):
        cases = (
            (401, "invalid", TRANSIENT_INVALID),
            (403, "invalid", TRANSIENT_INVALID),
            (429, "rate_limit", COOLDOWN),
            (432, "quota_exhausted", QUOTA_EXHAUSTED),
            (433, "quota_exhausted", QUOTA_EXHAUSTED),
        )
        with tempfile.TemporaryDirectory(prefix="tavily-status-tests-") as temp:
            for operation in ("search", "extract"):
                for code, error_type, status in cases:
                    with self.subTest(operation=operation, code=code):
                        store = StateStore(Path(temp) / f"{operation}-{code}.sqlite")
                        calls = []

                        def fetch(req, *, _operation=operation, _code=code, **_kwargs):
                            key = req.get_header("Authorization").removeprefix("Bearer ")
                            calls.append(key)
                            if key == KEYS[0]:
                                raise http_error(req.full_url, _code, "", None)
                            if _operation == "search":
                                return response({
                                    "results": [{"title": "fixture", "url": URL, "content": "snippet"}],
                                })
                            return response({"results": [{"raw_content": "fixture body"}]})

                        if operation == "search":
                            with mock.patch.object(search_adapter, "urlopen_retry", side_effect=fetch):
                                result = service.run_search_web(
                                    service.SearchWebRequest(
                                        query="fixture", sources=["tavily"], count=1, timeout=5,
                                    ),
                                    keys={"tavily": KEYS}, config={}, state_store=store,
                                    scraper=lambda *_args, **_kwargs: {
                                        "markdown": "fixture body", "via": "fixture",
                                    },
                                    url_resolver=lambda _host: ["93.184.216.34"],
                                )
                            self.assertEqual(result["errors"], [])
                            self.assertEqual(result["results"][0]["url"], URL)
                        else:
                            with mock.patch.object(extract_adapter, "urlopen_retry", side_effect=fetch):
                                result = service.run_scrape(
                                    service.ScrapeRequest(
                                        url=URL, backends=["tavily"], timeout=5, output="json",
                                    ),
                                    keys={"tavily": KEYS}, state_store=store,
                                    url_resolver=lambda _host: ["93.184.216.34"],
                                )
                            self.assertEqual(result["result"]["markdown"], "fixture body")

                        self.assertEqual(calls, KEYS)
                        rows = {
                            row["key_id"]: row for row in store.rows(
                                "SELECT * FROM key_state WHERE provider = ?", ("tavily",)
                            )
                        }
                        failed = rows[key_id_for("tavily", KEYS[0])]
                        succeeded = rows[key_id_for("tavily", KEYS[1])]
                        self.assertEqual(failed["status"], status)
                        self.assertEqual(failed["last_error_type"], error_type)
                        self.assertEqual(failed["use_count"], 1)
                        self.assertEqual(failed["quota_error_count"], int(error_type == "quota_exhausted"))
                        self.assertEqual(succeeded["status"], "active")
                        self.assertEqual(succeeded["success_count"], 1)

    def test_ordinary_400_does_not_rotate_even_with_quota_words(self):
        with tempfile.TemporaryDirectory(prefix="tavily-400-tests-") as temp:
            for operation in ("search", "extract"):
                with self.subTest(operation=operation):
                    store = StateStore(Path(temp) / f"{operation}.sqlite")
                    calls = []

                    def fetch(req, **_kwargs):
                        calls.append(req.get_header("Authorization"))
                        raise http_error(
                            req.full_url,
                            400,
                            "Forbidden",
                            quota_body("quota exceeded"),
                        )

                    if operation == "search":
                        with mock.patch.object(search_adapter, "urlopen_retry", side_effect=fetch):
                            result = service.run_search_web(
                                service.SearchWebRequest(
                                    query="fixture", sources=["tavily"], count=1, timeout=5,
                                ),
                                keys={"tavily": KEYS}, config={}, state_store=store,
                                scraper=lambda *_args, **_kwargs: {
                                    "markdown": "fixture body", "via": "fixture",
                                },
                                url_resolver=lambda _host: ["93.184.216.34"],
                            )
                        self.assertTrue(result["errors"])
                    else:
                        with mock.patch.object(extract_adapter, "urlopen_retry", side_effect=fetch):
                            result = service.run_scrape(
                                service.ScrapeRequest(
                                    url=URL, backends=["tavily"], timeout=5, output="json",
                                ),
                                keys={"tavily": KEYS}, state_store=store,
                                url_resolver=lambda _host: ["93.184.216.34"],
                            )
                        self.assertEqual(result["result"]["error_type"], "error")

                    self.assertEqual(len(calls), 1)
                    rows = {
                        row["key_id"]: row for row in store.rows(
                            "SELECT * FROM key_state WHERE provider = ?", ("tavily",)
                        )
                    }
                    self.assertEqual(len(rows), 2)
                    first = rows[key_id_for("tavily", KEYS[0])]
                    second = rows[key_id_for("tavily", KEYS[1])]
                    self.assertEqual(first["status"], "active")
                    self.assertEqual(first["quota_error_count"], 0)
                    self.assertEqual(second["use_count"], 0)


if __name__ == "__main__":
    unittest.main()
