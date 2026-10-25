"""Causal generation: a late success must not clear a newer state verdict."""
import tempfile
import unittest
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.state import key_state
from multi_search_mcp.src.state.key_state import (
    ACTIVE,
    COOLDOWN,
    INVALID,
    QUOTA_EXHAUSTED,
    KeyOutcome,
    SQLiteKeyManager,
)
from multi_search_mcp.src.state.state_store import StateStore
from multi_search_mcp.src.search.search_runner import run_keyed_source


BASE = datetime(2026, 10, 22, 12, 0, 0, tzinfo=timezone.utc)
SUCCESS = KeyOutcome(True, False)
RATE_LIMITED = KeyOutcome(False, True, "rate_limit", "HTTP 429")
QUOTA = KeyOutcome(False, True, "quota_exhausted", "quota exhausted")
INVALID_OUTCOME = KeyOutcome(False, True, "invalid", "HTTP 401 unauthorized")
NEUTRAL = KeyOutcome(False, False, "timeout", "request timed out")


def _write_quota_in_child(path: str) -> None:
    """Separate process: write a strong verdict at BASE."""
    with mock.patch.object(key_state, "_now", return_value=BASE):
        manager = SQLiteKeyManager(StateStore(Path(path)))
        candidate = manager.candidates("exa", "key")[0]
        manager.record_result("exa", candidate, QUOTA)


class GenerationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "state.sqlite"
        self.clock = BASE
        patcher = mock.patch.object(key_state, "_now", side_effect=lambda: self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.manager = SQLiteKeyManager(StateStore(self.path))
        self.candidate = self.manager.candidates("exa", "key")[0]

    def record(self, outcome, started_at=None):
        self.manager.record_result(
            "exa", self.candidate, outcome, started_at=started_at,
        )
        return self.manager.status_rows("exa")[0]

    def test_late_success_preserves_quota_written_during_the_request(self):
        self.clock = BASE
        quota_row = self.record(QUOTA)
        self.clock = BASE + timedelta(seconds=2)
        row = self.record(SUCCESS, started_at=BASE - timedelta(seconds=1))
        self.assertEqual(row["status"], QUOTA_EXHAUSTED)
        self.assertEqual(row["exhausted_until"], quota_row["exhausted_until"])
        self.assertEqual(row["success_count"], 1)
        self.assertEqual(row["last_success_at"], (BASE + timedelta(seconds=2)).isoformat())

    def test_late_success_preserves_rate_limit_cooldown(self):
        self.clock = BASE
        cooldown_row = self.record(RATE_LIMITED)
        self.clock = BASE + timedelta(seconds=2)
        row = self.record(SUCCESS, started_at=BASE - timedelta(seconds=1))
        self.assertEqual(row["status"], COOLDOWN)
        self.assertEqual(row["cooldown_until"], cooldown_row["cooldown_until"])
        self.assertEqual(row["failure_count"], 1)

    def test_late_success_preserves_permanent_invalid_and_strikes(self):
        for offset in range(3):
            self.clock = BASE + timedelta(seconds=offset)
            self.record(INVALID_OUTCOME)
        self.clock = BASE + timedelta(seconds=5)
        row = self.record(SUCCESS, started_at=BASE - timedelta(seconds=1))
        self.assertEqual((row["status"], row["invalid_strikes"]), (INVALID, 3))
        self.assertEqual(self.manager.candidates("exa", "key"), [])

    def test_success_entered_after_the_failure_recovers_the_key(self):
        self.clock = BASE
        self.record(QUOTA)
        self.clock = BASE + timedelta(seconds=2)
        row = self.record(SUCCESS, started_at=BASE + timedelta(seconds=1))
        self.assertEqual(row["status"], ACTIVE)
        self.assertEqual(row["invalid_strikes"], 0)
        self.assertEqual(
            [item.key for item in self.manager.candidates("exa", "key")], ["key"],
        )

    def test_neutral_error_does_not_advance_the_state_generation(self):
        self.clock = BASE
        self.record(RATE_LIMITED)
        self.clock = BASE + timedelta(seconds=2)
        neutral_row = self.record(NEUTRAL)
        self.assertEqual(neutral_row["status"], COOLDOWN)
        self.clock = BASE + timedelta(seconds=3)
        # The request started after the cooldown but before the neutral error;
        # a neutral error must not turn into a causal blocker.
        row = self.record(SUCCESS, started_at=BASE + timedelta(seconds=1))
        self.assertEqual(row["status"], ACTIVE)
        self.assertEqual(row["failure_count"], 2)

    def test_usage_recording_does_not_advance_the_state_generation(self):
        self.clock = BASE
        self.record(QUOTA)
        self.clock = BASE + timedelta(seconds=1)
        self.manager.record_use("exa", self.candidate)
        self.clock = BASE + timedelta(seconds=2)
        row = self.record(SUCCESS, started_at=BASE - timedelta(seconds=1))
        self.assertEqual(row["status"], QUOTA_EXHAUSTED)
        self.assertEqual(row["use_count"], 1)

    def test_barrier_ordered_late_success_keeps_quota_committed_during_request(self):
        # Deterministic concurrent timeline: success enters first, a different
        # request commits QUOTA while it is in flight, then success records.
        import threading

        failure_done = threading.Event()
        success_entered = threading.Event()
        clock = {"now": BASE}

        def success_worker():
            started_at = BASE
            success_entered.set()
            self.assertTrue(failure_done.wait(5))
            clock["now"] = BASE + timedelta(seconds=2)
            self.manager.record_result(
                "exa", self.candidate, SUCCESS, started_at=started_at,
            )

        def failure_worker():
            self.assertTrue(success_entered.wait(5))
            clock["now"] = BASE + timedelta(seconds=1)
            self.record(QUOTA)
            failure_done.set()

        with mock.patch.object(key_state, "_now", side_effect=lambda: clock["now"]):
            threads = [threading.Thread(target=success_worker), threading.Thread(target=failure_worker)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)
                self.assertFalse(thread.is_alive())
        row = self.manager.status_rows("exa")[0]
        self.assertEqual(row["status"], QUOTA_EXHAUSTED)
        self.assertIsNotNone(row["exhausted_until"])
        self.assertEqual(row["success_count"], 1)

    def test_run_keyed_source_passes_its_request_start_generation(self):
        captured = {}
        original = self.manager.record_result

        def spy(provider, candidate, outcome, *, started_at=None):
            captured["started_at"] = started_at
            return original(provider, candidate, outcome, started_at=started_at)

        with mock.patch.object(self.manager, "record_result", side_effect=spy), mock.patch(
            "multi_search_mcp.src.search.search_runner._now", return_value=BASE,
        ):
            run_keyed_source(
                "exa", [self.candidate.key], lambda _key: [{"source": "exa", "url": "https://example.com"}],
                key_manager=self.manager,
            )
        self.assertEqual(captured["started_at"], BASE)
        self.assertEqual(self.manager.status_rows("exa")[0]["status"], ACTIVE)


class MultiProcessGenerationTests(unittest.TestCase):
    def test_late_success_in_parent_preserves_strong_state_from_child_process(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state.sqlite"
            with mock.patch.object(key_state, "_now", return_value=BASE - timedelta(seconds=5)):
                manager = SQLiteKeyManager(StateStore(path))
                candidate = manager.candidates("exa", "key")[0]
            with ProcessPoolExecutor(max_workers=1) as pool:
                list(pool.map(_write_quota_in_child, [str(path)]))
            with mock.patch.object(key_state, "_now", return_value=BASE + timedelta(seconds=5)):
                manager.record_result(
                    "exa", candidate, SUCCESS,
                    started_at=BASE - timedelta(seconds=1),
                )
                preserved = manager.status_rows("exa")[0]
            self.assertEqual(preserved["status"], QUOTA_EXHAUSTED)
            with mock.patch.object(key_state, "_now", return_value=BASE + timedelta(seconds=10)):
                manager.record_result(
                    "exa", candidate, SUCCESS,
                    started_at=BASE + timedelta(seconds=6),
                )
                recovered = manager.status_rows("exa")[0]
            self.assertEqual(recovered["status"], ACTIVE)


if __name__ == "__main__":
    unittest.main()
