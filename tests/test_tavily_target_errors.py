import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError

from multi_search_mcp.src import service
from multi_search_mcp.src.scrape.scrapers import tavily as tavily_scraper
from multi_search_mcp.src.state.key_state import (
    ACTIVE,
    TRANSIENT_INVALID,
    KeyOutcome,
    SQLiteKeyManager,
    key_id_for,
)
from multi_search_mcp.src.state.state_store import StateStore


URL = "https://example.com/article"
KEYS = ["fixture-tavily-first", "fixture-tavily-second"]


def target_error(code: int, detail: str) -> dict:
    return {
        "results": [],
        "failed_results": [{
            "url": URL,
            "error": f"Target returned HTTP {code} {detail}",
        }],
    }


def response(payload: dict) -> io.BytesIO:
    return io.BytesIO(json.dumps(payload).encode())


class TavilyTargetErrorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="tavily-target-tests-")
        self.addCleanup(self.temp.cleanup)
        self.store = StateStore(Path(self.temp.name) / "state.sqlite")
        self.manager = SQLiteKeyManager(self.store)
        self.keys = {"tavily": KEYS}

    def scrape(self):
        return service.run_scrape(
            service.ScrapeRequest(url=URL, backends=["tavily"], output="json"),
            keys=self.keys,
            config={},
            state_store=self.store,
            url_resolver=lambda _host: ["93.184.216.34"],
        )["result"]

    def test_target_401_and_403_do_not_rotate_or_change_key_health(self):
        for code, detail in ((401, "Unauthorized"), (403, "Forbidden")):
            with self.subTest(code=code):
                store = StateStore(Path(self.temp.name) / f"state-{code}.sqlite")
                manager = SQLiteKeyManager(store)
                with mock.patch.object(
                    tavily_scraper,
                    "urlopen_retry",
                    side_effect=lambda *_args, _payload=target_error(code, detail), **_kwargs: response(_payload),
                ) as fetch:
                    result = service.run_scrape(
                        service.ScrapeRequest(url=URL, backends=["tavily"], output="json"),
                        keys=self.keys,
                        config={},
                        state_store=store,
                        url_resolver=lambda _host: ["93.184.216.34"],
                    )["result"]

                self.assertEqual(fetch.call_count, 2)
                self.assertIn(f"HTTP {code} {detail}", result["error"])
                self.assertEqual(result["error_origin"], "target")
                self.assertEqual(result["error_type"], "target")
                self.assertEqual(result["markdown"], "")
                self.assertEqual(result["length"], 0)
                self.assertEqual(result["via"], "tavily")
                self.assertEqual(len(manager.candidates("tavily", KEYS)), 2)
                rows = manager.status_rows("tavily")
                self.assertEqual(sum(row["use_count"] for row in rows), 1)
                for row in rows:
                    self.assertEqual(row["status"], ACTIVE)
                    self.assertEqual(row["invalid_strikes"], 0)
                    self.assertIsNone(row["cooldown_until"])
                    self.assertEqual(row["failure_count"], 0)
                    self.assertEqual(row["success_count"], 0)

    def test_advanced_and_basic_target_errors_keep_structured_origin_when_merged(self):
        with mock.patch.object(tavily_scraper, "urlopen_retry", side_effect=[
            response(target_error(401, "Unauthorized")),
            response(target_error(403, "Forbidden")),
        ]) as fetch:
            result = tavily_scraper.scrape_url_tavily(URL, KEYS[0])

        self.assertEqual(fetch.call_count, 2)
        self.assertIn("Tavily advanced:", result["error"])
        self.assertIn("Tavily basic:", result["error"])
        self.assertEqual(result["error_origin"], "target")
        self.assertEqual(result["error_type"], "target")

    def test_target_origin_survives_merge_with_unmarked_empty_fallback(self):
        with mock.patch.object(tavily_scraper, "urlopen_retry", side_effect=[
            response(target_error(403, "Forbidden")),
            response({"results": []}),
        ]):
            result = tavily_scraper.scrape_url_tavily(URL, KEYS[0])

        self.assertEqual(result["error_origin"], "target")
        self.assertEqual(result["error_type"], "target")

    def test_target_error_does_not_overwrite_existing_auth_failure(self):
        candidate = self.manager.candidates("tavily", KEYS)[0]
        before = []
        recorded = False

        def fetch(*_args, **_kwargs):
            nonlocal recorded
            if not recorded:
                self.manager.record_result(
                    "tavily",
                    candidate,
                    KeyOutcome(False, True, "invalid", "fixture provider failure"),
                )
                before.extend(self.manager.status_rows("tavily"))
                recorded = True
            return response(target_error(403, "Forbidden"))

        with mock.patch.object(tavily_scraper, "urlopen_retry", side_effect=fetch) as request:
            result = self.scrape()

        self.assertEqual(request.call_count, 2)
        self.assertEqual(result["error_origin"], "target")
        self.assertEqual(self.manager.status_rows("tavily"), before)
        row = next(row for row in before if row["key_id"] == candidate.key_id)
        self.assertEqual(row["status"], TRANSIENT_INVALID)
        self.assertEqual(row["invalid_strikes"], 1)

    def test_real_api_auth_error_still_rotates_to_next_key(self):
        success = {
            "results": [{"url": URL, "raw_content": "fixture body"}],
        }
        with mock.patch.object(tavily_scraper, "urlopen_retry", side_effect=[
            HTTPError("https://api.tavily.com/extract", 401, "Unauthorized", {}, None),
            response(success),
        ]) as fetch:
            result = self.scrape()

        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(result["markdown"], "fixture body")
        rows = {row["key_id"]: row for row in self.manager.status_rows("tavily")}
        failed = rows[key_id_for("tavily", KEYS[0])]
        self.assertEqual(failed["status"], TRANSIENT_INVALID)
        self.assertEqual(failed["invalid_strikes"], 1)
        self.assertEqual(failed["last_error_type"], "invalid")
        self.assertEqual([candidate.key for candidate in self.manager.candidates("tavily", KEYS)], [KEYS[1]])

    def test_target_error_redacts_key_while_preserving_status(self):
        detail = f"Forbidden while fetching with {KEYS[0]}"
        with mock.patch.object(
            tavily_scraper,
            "urlopen_retry",
            side_effect=lambda *_args, **_kwargs: response(target_error(403, detail)),
        ):
            result = self.scrape()

        self.assertNotIn(KEYS[0], json.dumps(result))
        self.assertIn("403", result["error"])
        self.assertEqual(result["error_origin"], "target")


if __name__ == "__main__":
    unittest.main()
