import asyncio
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError

from multi_search_mcp import cli, tools
from multi_search_mcp.server import mcp
from multi_search_mcp.src import service
from multi_search_mcp.src.scrape.scrapers import exa as exa_scraper
from multi_search_mcp.src.search.searchers import exa as exa_searcher
from multi_search_mcp.src.state.key_state import (
    ACTIVE, COOLDOWN, INVALID, TRANSIENT_INVALID, BasicKeyManager,
    KeyOutcome, SQLiteKeyManager, key_id_for,
)
from multi_search_mcp.src.state.state_store import StateStore
from multi_search_mcp.src.support.auth import is_key_retryable_error
from multi_search_mcp.src.support.models import normalize_scrape_result


URL = "https://example.com/article"
KEYS = ["fixture-exa-first", "fixture-exa-second"]


def target_error(code=403, detail="SOURCE_NOT_AVAILABLE"):
    return {"results": [], "statuses": [{
        "id": URL, "status": "error",
        "error": {"tag": detail, "httpStatusCode": code},
    }]}


def response(payload):
    return io.BytesIO(json.dumps(payload).encode())


class ExaTargetErrorTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="exa-target-tests-")
        self.addCleanup(temp.cleanup)
        self.store = StateStore(Path(temp.name) / "state.sqlite")
        self.manager = SQLiteKeyManager(self.store)
        self.keys = {"exa": KEYS}

    def scrape(self):
        return service.run_scrape(
            service.ScrapeRequest(url=URL, backends=["exa"], output="json"),
            keys=self.keys, config={}, state_store=self.store,
            url_resolver=lambda _host: ["93.184.216.34"],
        )["result"]

    def test_target_403_does_not_rotate_or_cool_keys(self):
        with mock.patch.object(exa_scraper, "urlopen_retry", side_effect=lambda *_a, **_k: response(target_error())) as fetch:
            result = self.scrape()
        self.assertIn("SOURCE_NOT_AVAILABLE (403)", result["error"])
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(result["error_origin"], "target")
        self.assertEqual(result["error_type"], "target")
        self.assertEqual(result["markdown"], "")
        self.assertEqual(result["length"], 0)
        self.assertEqual(result["via"], "exa")
        self.assertEqual(len(self.manager.candidates("exa", KEYS)), 2)
        self.assertEqual(sum(row["use_count"] for row in self.manager.status_rows("exa")), 1)
        for row in self.manager.status_rows("exa"):
            self.assertEqual(row["status"], ACTIVE)
            self.assertEqual(row["invalid_strikes"], 0)
            self.assertIsNone(row["cooldown_until"])
            self.assertEqual(row["failure_count"], 0)
            self.assertEqual(row["success_count"], 0)

    def test_target_failure_cannot_overwrite_in_flight_key_health(self):
        candidate = self.manager.candidates("exa", KEYS)[0]
        for status, error_type, repeats in (
            (TRANSIENT_INVALID, "invalid", 1),
            (INVALID, "invalid", 3),
            (COOLDOWN, "rate_limit", 1),
        ):
            with self.subTest(status=status):
                self.manager.reset("exa")
                # Use only this key so selection occurs before the other
                # in-flight request publishes its authentication failure.
                self.keys = {"exa": [candidate.key]}
                before = []

                def fetch(*_args, **_kwargs):
                    for _ in range(repeats):
                        self.manager.record_result("exa", candidate, KeyOutcome(
                            False, True, error_type, "fixture provider failure",
                        ))
                    before.extend(self.manager.status_rows("exa"))
                    return response(target_error())

                with mock.patch.object(exa_scraper, "urlopen_retry", side_effect=fetch) as request:
                    result = self.scrape()
                self.assertEqual(request.call_count, 1)
                self.assertIn("403", result["error"])
                self.assertEqual(self.manager.status_rows("exa"), before)
                row = next(row for row in before if row["key_id"] == candidate.key_id)
                self.assertEqual(row["status"], status)
                self.assertEqual(row["invalid_strikes"], repeats if error_type == "invalid" else 0)

    def test_per_url_errors_never_rotate_even_with_auth_or_quota_words(self):
        for code, detail in ((401, "unauthorized"), (403, "forbidden"), (429, "rate limit quota")):
            with self.subTest(code=code):
                with mock.patch.object(exa_scraper, "urlopen_retry", side_effect=lambda *_a, **_k: response(target_error(code, detail))) as fetch:
                    result = self.scrape()
                self.assertEqual(fetch.call_count, 1)
                self.assertIn(f"{detail} ({code})", result["error"])
                self.assertFalse(is_key_retryable_error(result))
                outcome = self.manager.classify_result("exa", result)
                self.assertFalse(outcome.success)
                self.assertFalse(outcome.retryable)
                self.assertEqual(outcome.error_type, "target")
        self.assertEqual(len(self.manager.candidates("exa", KEYS)), 2)

    def test_shared_search_can_use_both_keys_after_target_error(self):
        with mock.patch.object(exa_scraper, "urlopen_retry", side_effect=lambda *_a, **_k: response(target_error())):
            self.scrape()
        payload = {"results": [{"url": URL, "title": "Article", "highlights": ["Search excerpt"]}]}
        used = []

        def search(req, **_kwargs):
            used.append(req.get_header("X-api-key"))
            return response(payload)

        with mock.patch.object(exa_searcher, "urlopen_retry", side_effect=search):
            for _ in KEYS:
                result = service.run_search_web(
                    service.SearchWebRequest(query="fixture", sources=["exa"]),
                    keys=self.keys, config={}, state_store=self.store,
                    scraper=lambda *_a, **_k: {"markdown": "Fixture body", "via": "fixture"},
                    url_resolver=lambda _host: ["93.184.216.34"],
                )
                self.assertEqual(result["errors"], [])
                self.assertEqual(result["results"][0]["url"], URL)
        self.assertCountEqual(used, KEYS)

    def test_request_authentication_failure_still_rotates_and_cools(self):
        success = {"results": [{"url": URL, "title": "Article", "text": "Full body"}],
                   "statuses": [{"id": URL, "status": "success"}]}
        with mock.patch.object(exa_scraper, "urlopen_retry", side_effect=[
            HTTPError("https://api.exa.ai/contents", 401, "Unauthorized", {}, None),
            response(success),
        ]) as fetch:
            result = self.scrape()
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(result["markdown"], "Full body")
        rows = {row["key_id"]: row for row in self.manager.status_rows("exa")}
        failed = rows[key_id_for("exa", KEYS[0])]
        self.assertEqual(failed["status"], TRANSIENT_INVALID)
        self.assertEqual(failed["invalid_strikes"], 1)
        self.assertEqual(failed["last_error_type"], "invalid")
        self.assertEqual([c.key for c in self.manager.candidates("exa", KEYS)], [KEYS[1]])

    def test_request_status_is_classified_before_misleading_error_text(self):
        for code, expected, retryable in (
            (401, "invalid", True), (403, "invalid", True),
            (402, "quota_exhausted", True), (429, "rate_limit", True),
            (500, "error", False),
        ):
            with self.subTest(code=code):
                with mock.patch.object(exa_scraper, "urlopen_retry", side_effect=HTTPError(
                    "https://api.exa.ai/contents", code, "forbidden 401 quota", {}, None,
                )):
                    result = exa_scraper.scrape_url_exa(URL, KEYS[0])
                self.assertEqual(result["error_origin"], "provider")
                self.assertEqual(result["error_type"], expected)
                self.assertEqual(is_key_retryable_error(result), retryable)
                outcome = self.manager.classify_result("exa", result)
                self.assertEqual(outcome.error_type, expected)
                self.assertEqual(outcome.retryable, retryable)

    def test_normalization_preserves_only_safe_error_metadata(self):
        row = {"error": "forbidden 403", "error_origin": "target", "error_type": "target", "raw_provider_dump": "private"}
        normalized = normalize_scrape_result(row, url=URL, via="exa")
        self.assertEqual(normalized["error_origin"], "target")
        self.assertEqual(normalized["error_type"], "target")
        self.assertNotIn("raw_provider_dump", normalized)
        self.assertEqual(normalize_scrape_result(normalized), normalized)

    def test_target_error_does_not_contaminate_other_provider_errors(self):
        target = {"error": "forbidden 403 quota", "error_origin": "target", "error_type": "target"}
        for provider, expected, retryable in (
            ({"error": "timeout"}, "timeout", False),
            ({"error": "too many requests", "rate_limited": True}, "rate_limit", True),
            ({"error": "invalid key"}, "invalid", True),
        ):
            with self.subTest(provider=provider):
                for rows in ([target, provider], [provider, target]):
                    outcome = BasicKeyManager().classify_result("exa", rows)
                    self.assertEqual(outcome.error_type, expected)
                    self.assertEqual(outcome.retryable, retryable)
                    self.assertIn(target["error"], outcome.error_message)

    def test_target_error_redacts_credentials_without_removing_status(self):
        detail = f"forbidden with {KEYS[0]}"
        with mock.patch.object(exa_scraper, "urlopen_retry", side_effect=lambda *_a, **_k: response(target_error(403, detail))):
            result = self.scrape()
        serialized = json.dumps(result)
        self.assertNotIn(KEYS[0], serialized)
        self.assertIn("403", result["error"])
        self.assertIn("forbidden", result["error"])

    def test_target_error_without_state_still_does_not_rotate(self):
        payload = target_error()
        payload["statuses"][0]["error"] = "forbidden 401 / 403"
        with mock.patch.object(exa_scraper, "urlopen_retry", side_effect=lambda *_a, **_k: response(payload)) as fetch:
            result = service.run_scrape(
                service.ScrapeRequest(url=URL, backends=["exa"], output="json", use_state=False),
                keys=self.keys, config={}, url_resolver=lambda _host: ["93.184.216.34"],
            )
        self.assertEqual(fetch.call_count, 1)
        self.assertIn("forbidden 401 / 403", result["result"]["error"])

    def test_cli_and_mcp_fetch_keep_target_error_visible_and_redacted(self):
        def fetch_source(request):
            return service.run_fetch_source(
                request, keys=self.keys, config={}, state_store=self.store,
                url_resolver=lambda _host: ["93.184.216.34"],
            )

        # The current key is echoed by the simulated provider to test redaction
        # after LRU selection, across all public error presentation modes.
        def fetch(req, **_kwargs):
            return response(target_error(403, f"SOURCE_NOT_AVAILABLE {req.get_header('X-api-key')}"))

        with mock.patch.object(exa_scraper, "urlopen_retry", side_effect=fetch), \
                mock.patch.object(cli, "run_fetch_source", side_effect=fetch_source), \
                mock.patch.object(tools, "run_fetch_source", side_effect=fetch_source):
            for output_format in cli.OUTPUT_FORMATS:
                with self.subTest(output_format=output_format):
                    stdout, stderr = io.StringIO(), io.StringIO()
                    code = cli.main([
                        "fetch", "--url", URL, "--backend", "exa", "--format", output_format,
                    ], stdout=stdout, stderr=stderr)
                    self.assertNotEqual(code, 0)
                    output = stdout.getvalue() + stderr.getvalue()
                    self.assertIn("SOURCE_NOT_AVAILABLE", output)
                    self.assertIn("403", output)
                    for key in KEYS:
                        self.assertNotIn(key, output)
            result = asyncio.run(mcp.call_tool("fetch_source", {"url": URL, "backends": ["exa"]}))
            output = "\n".join(item.text for item in result if getattr(item, "type", None) == "text")
            self.assertIn("SOURCE_NOT_AVAILABLE", output)
            self.assertIn("403", output)
            self.assertEqual(json.loads(output)["error_type"], "invalid_request")
            for key in KEYS:
                self.assertNotIn(key, output)
        self.assertEqual(len(self.manager.candidates("exa", KEYS)), 2)

    def test_mcp_scrape_preserves_nested_error_metadata_in_all_modes(self):
        def scrape(request):
            return service.run_scrape(
                request, keys=self.keys, config={}, state_store=self.store,
                url_resolver=lambda _host: ["93.184.216.34"],
            )

        with mock.patch.object(exa_scraper, "urlopen_retry", side_effect=lambda *_a, **_k: response(target_error())), \
                mock.patch.object(tools, "run_scrape", side_effect=scrape):
            for mode in ("json", "markdown", "both"):
                with self.subTest(mode=mode):
                    result = asyncio.run(mcp.call_tool("scrape_url", {
                        "url": URL, "backends": ["exa"], "output": mode,
                    }))
                    output = "\n".join(item.text for item in result if getattr(item, "type", None) == "text")
                    payload = json.loads(output)
                    self.assertEqual(payload["result"]["error_origin"], "target")
                    self.assertEqual(payload["result"]["error_type"], "target")
                    self.assertIn("SOURCE_NOT_AVAILABLE (403)", payload["result"]["error"])
                    if mode != "json":
                        self.assertIn("SOURCE_NOT_AVAILABLE (403)", payload["markdown"])


if __name__ == "__main__":
    unittest.main()
