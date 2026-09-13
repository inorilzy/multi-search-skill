import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from multi_search_mcp.src import service
from multi_search_mcp.src.scrape.scrapers import exa as exa_scraper
from multi_search_mcp.src.state import key_state
from multi_search_mcp.src.state.key_state import (
    ACTIVE,
    COOLDOWN,
    INVALID,
    INVALID_COOLDOWN,
    KeyOutcome,
    QUOTA_EXHAUSTED,
    TRANSIENT_INVALID,
    SQLiteKeyManager,
)
from multi_search_mcp.src.state.state_store import StateStore


URL = "https://example.com/article"


def target_error():
    return {
        "results": [],
        "statuses": [{
            "id": URL,
            "status": "error",
            "error": {"tag": "SOURCE_NOT_AVAILABLE", "httpStatusCode": 403},
        }],
    }


class InvalidStreakTests(unittest.TestCase):
    def test_mixed_provider_results_break_the_invalid_streak(self):
        base = datetime(2026, 9, 13, tzinfo=timezone.utc)
        clock = [base]
        outcomes = (
            KeyOutcome(False, True, "invalid", "HTTP 401 unauthorized"),
            KeyOutcome(False, True, "rate_limit", "HTTP 429 rate limit"),
            KeyOutcome(False, True, "invalid", "HTTP 403 forbidden"),
            KeyOutcome(False, True, "quota_exhausted", "quota exhausted"),
            KeyOutcome(False, True, "invalid", "HTTP 401 unauthorized"),
        )
        expected_strikes = (1, 0, 1, 0, 1)

        with tempfile.TemporaryDirectory(prefix="invalid-streak-tests-") as temp:
            manager = SQLiteKeyManager(StateStore(Path(temp) / "state.sqlite"))
            candidate = manager.candidates("exa", "fixture-key")[0]
            with mock.patch.object(key_state, "_now", side_effect=lambda: clock[0]):
                for index, (outcome, expected) in enumerate(zip(outcomes, expected_strikes)):
                    if index:
                        previous = outcomes[index - 1].error_type
                        wait = timedelta(hours=24) if previous == "quota_exhausted" else INVALID_COOLDOWN
                        clock[0] = clock[0] + wait + timedelta(seconds=1)
                        self.assertEqual(manager.candidates("exa", "fixture-key"), [candidate])
                    manager.record_result("exa", candidate, outcome)
                    row = manager.status_rows("exa")[0]
                    self.assertEqual(row["invalid_strikes"], expected)

            self.assertEqual(row["failure_count"], len(outcomes))
            self.assertNotEqual(row["status"], INVALID)

    def test_each_non_invalid_provider_result_clears_invalid_strikes(self):
        cases = (
            ("success", KeyOutcome(True, False), ACTIVE),
            ("rate_limit", KeyOutcome(False, True, "rate_limit", "HTTP 429"), COOLDOWN),
            ("quota_exhausted", KeyOutcome(False, True, "quota_exhausted", "quota"), QUOTA_EXHAUSTED),
            ("other", KeyOutcome(False, False, "network", "connection error"), ACTIVE),
        )
        for name, outcome, expected_status in cases:
            with self.subTest(result=name), tempfile.TemporaryDirectory(prefix="invalid-streak-reset-") as temp:
                base = datetime(2026, 9, 13, tzinfo=timezone.utc)
                clock = [base]
                manager = SQLiteKeyManager(StateStore(Path(temp) / "state.sqlite"))
                candidate = manager.candidates("exa", "fixture-key")[0]
                with mock.patch.object(key_state, "_now", side_effect=lambda: clock[0]):
                    for _ in range(2):
                        manager.record_result(
                            "exa", candidate,
                            KeyOutcome(False, True, "invalid", "HTTP 401 unauthorized"),
                        )
                        clock[0] += INVALID_COOLDOWN + timedelta(seconds=1)
                    manager.record_result("exa", candidate, outcome)
                    row = manager.status_rows("exa")[0]
                self.assertEqual(row["invalid_strikes"], 0)
                self.assertEqual(row["status"], expected_status)

    def test_three_consecutive_invalid_results_still_escalate(self):
        base = datetime(2026, 9, 13, tzinfo=timezone.utc)
        clock = [base]
        invalid = KeyOutcome(False, True, "invalid", "HTTP 401 unauthorized")
        with tempfile.TemporaryDirectory(prefix="invalid-streak-threshold-") as temp:
            manager = SQLiteKeyManager(StateStore(Path(temp) / "state.sqlite"))
            candidate = manager.candidates("exa", "fixture-key")[0]
            with mock.patch.object(key_state, "_now", side_effect=lambda: clock[0]):
                for strike in (1, 2, 3):
                    manager.record_result("exa", candidate, invalid)
                    row = manager.status_rows("exa")[0]
                    self.assertEqual(row["invalid_strikes"], strike)
                    if strike < 3:
                        self.assertEqual(row["status"], TRANSIENT_INVALID)
                        clock[0] += INVALID_COOLDOWN + timedelta(seconds=1)
            self.assertEqual(row["status"], INVALID)
            self.assertEqual(manager.candidates("exa", "fixture-key"), [])

    def test_target_result_is_neutral_at_run_scrape_entry(self):
        base = datetime(2026, 9, 13, tzinfo=timezone.utc)
        clock = [base]
        with tempfile.TemporaryDirectory(prefix="invalid-streak-target-") as temp:
            store = StateStore(Path(temp) / "state.sqlite")
            manager = SQLiteKeyManager(store)
            candidate = manager.candidates("exa", "fixture-key")[0]
            before_target = []

            def fetch(*_args, **_kwargs):
                manager.record_result(
                    "exa", candidate,
                    KeyOutcome(False, True, "invalid", "fixture provider failure"),
                )
                before_target.extend(manager.status_rows("exa"))
                return io.BytesIO(json.dumps(target_error()).encode())

            with mock.patch.object(key_state, "_now", side_effect=lambda: clock[0]):
                with mock.patch.object(exa_scraper, "urlopen_retry", side_effect=fetch) as request:
                    result = service.run_scrape(
                        service.ScrapeRequest(url=URL, backends=["exa"], output="json"),
                        keys={"exa": [candidate.key]},
                        config={},
                        state_store=store,
                        url_resolver=lambda _host: ["93.184.216.34"],
                    )["result"]

            self.assertEqual(request.call_count, 1)
            self.assertEqual(result["error_origin"], "target")
            self.assertEqual(result["error_type"], "target")
            self.assertEqual(manager.status_rows("exa"), before_target)
            row = before_target[0]
            self.assertEqual(row["status"], TRANSIENT_INVALID)
            self.assertEqual(row["invalid_strikes"], 1)
            self.assertIsNotNone(row["cooldown_until"])

    def test_target_outcome_is_neutral_at_key_manager_boundary(self):
        base = datetime(2026, 9, 13, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory(prefix="invalid-streak-target-state-") as temp:
            manager = SQLiteKeyManager(StateStore(Path(temp) / "state.sqlite"))
            candidate = manager.candidates("exa", "fixture-key")[0]
            with mock.patch.object(key_state, "_now", return_value=base):
                manager.record_result(
                    "exa", candidate,
                    KeyOutcome(False, True, "invalid", "HTTP 401 unauthorized"),
                )
                before_target = manager.status_rows("exa")
                manager.record_result(
                    "exa", candidate,
                    KeyOutcome(False, False, "target", "target page unavailable"),
                )
            self.assertEqual(manager.status_rows("exa"), before_target)


if __name__ == "__main__":
    unittest.main()
