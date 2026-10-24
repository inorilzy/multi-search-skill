import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.state.key_state import (
    ACTIVE, COOLDOWN, INVALID, QUOTA_EXHAUSTED, TRANSIENT_INVALID,
    KeyCandidate, KeyOutcome, SQLiteKeyManager, key_fingerprint, key_id_for,
)
from multi_search_mcp.src.state.state_store import SCHEMA, StateStore


class KeyStateConcurrencyTests(unittest.TestCase):
    @staticmethod
    def managers_for(manager, sharing, count):
        if sharing == "manager":
            return [manager] * count
        if sharing == "store":
            return [SQLiteKeyManager(manager.store) for _ in range(count)]
        return [SQLiteKeyManager(StateStore(manager.store.path)) for _ in range(count)]

    def test_three_concurrent_auth_failures_reach_invalid(self):
        for sharing in ("manager", "store", "database"):
            with self.subTest(sharing=sharing), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "state.sqlite"
                manager = SQLiteKeyManager(StateStore(path))
                candidate = manager.candidates("exa", "fixture-key")[0]
                managers = self.managers_for(manager, sharing, 3)
                outcome = manager.classify_result("exa", {"error": "HTTP 401 unauthorized"})
                updates_ready = threading.Barrier(3, timeout=5)
                execute = StateStore.execute

                def synchronized_update(store, query, params=()):
                    if "UPDATE key_state" in query and "failure_count" in query:
                        # Hold all writers after any pre-update reads, before SQL
                        # obtains its write lock. The database calls remain real.
                        updates_ready.wait()
                    return execute(store, query, params)

                with mock.patch.object(StateStore, "execute", synchronized_update):
                    with ThreadPoolExecutor(max_workers=3) as pool:
                        futures = [
                            pool.submit(worker.record_result, "exa", candidate, outcome)
                            for worker in managers
                        ]
                        for future in futures:
                            future.result(timeout=10)

                with mock.patch(
                    "multi_search_mcp.src.state.state_store.DEFAULT_STATE_PATH", path
                ):
                    row = SQLiteKeyManager(StateStore(path)).status_rows("exa")[0]
                self.assertEqual(
                    (row["failure_count"], row["invalid_strikes"], row["status"]),
                    (3, 3, INVALID),
                )
                self.assertEqual(row["success_count"], 0)
                self.assertEqual(row["status"], INVALID)
                self.assertIsNone(row["cooldown_until"])
                self.assertEqual(manager.candidates("exa", "fixture-key"), [])

    def test_concurrent_reset_and_auth_failure_follow_commit_order(self):
        invalid = KeyOutcome(False, True, "invalid", "HTTP 401 unauthorized")
        resets = (KeyOutcome(True, False), KeyOutcome(False, False, "timeout", "timed out"))
        for sharing in ("manager", "store", "database"):
            for reset in resets:
                for reset_first in (True, False):
                    with self.subTest(sharing=sharing, reset=reset, reset_first=reset_first):
                        with tempfile.TemporaryDirectory() as temp, mock.patch(
                            "multi_search_mcp.src.state.key_state._now",
                            return_value=datetime(2026, 9, 12, tzinfo=timezone.utc),
                        ):
                            manager = SQLiteKeyManager(StateStore(Path(temp) / "concurrent.sqlite"))
                            serial = SQLiteKeyManager(StateStore(Path(temp) / "serial.sqlite"))
                            candidate = manager.candidates("exa", "fixture-key")[0]
                            for target in (manager, serial):
                                for _ in range(2):
                                    target.record_result("exa", candidate, invalid)
                            outcomes = (reset, invalid) if reset_first else (invalid, reset)
                            for outcome in outcomes:
                                serial.record_result("exa", candidate, outcome)
                            managers = self.managers_for(manager, sharing, 2)
                            updates_ready = threading.Barrier(2, timeout=5)
                            first_committed = threading.Event()
                            worker = threading.local()
                            execute = StateStore.execute

                            def ordered_update(store, query, params=()):
                                if "UPDATE key_state" not in query:
                                    return execute(store, query, params)
                                updates_ready.wait()
                                if worker.index == 1:
                                    self.assertTrue(first_committed.wait(5))
                                execute(store, query, params)
                                if worker.index == 0:
                                    first_committed.set()

                            def record(index):
                                worker.index = index
                                managers[index].record_result("exa", candidate, outcomes[index])

                            with mock.patch.object(StateStore, "execute", ordered_update):
                                with ThreadPoolExecutor(max_workers=2) as pool:
                                    futures = [pool.submit(record, index) for index in range(2)]
                                    for future in futures:
                                        future.result(timeout=10)

                            row = manager.status_rows("exa")[0]
                            self.assertEqual(row, serial.status_rows("exa")[0])
                            self.assertEqual(row["failure_count"], 3 if reset.success else 4)
                            self.assertEqual(row["success_count"], int(reset.success))
                            if reset.success and reset_first:
                                self.assertEqual(row["invalid_strikes"], 1)
                                self.assertEqual(row["status"], TRANSIENT_INVALID)
                            elif reset.success:
                                self.assertEqual(row["invalid_strikes"], 0)
                                self.assertEqual(row["status"], ACTIVE)
                            else:
                                # The timeout is neutral: it neither resets the
                                # two existing strikes nor the stored verdict,
                                # so a 401 escalates the key in either order.
                                self.assertEqual(row["invalid_strikes"], 3)
                                self.assertEqual(row["status"], INVALID)

    def test_credential_results_update_state_and_neutral_errors_preserve_it(self):
        now = datetime(2026, 9, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp, mock.patch(
            "multi_search_mcp.src.state.key_state._now", return_value=now
        ):
            manager = SQLiteKeyManager(StateStore(Path(temp) / "state.sqlite"))
            candidate = manager.candidates("exa", "fixture-key")[0]
            invalid = KeyOutcome(False, True, "invalid", "HTTP 401 unauthorized")
            for _ in range(2):
                manager.record_result("exa", candidate, invalid)
            cases = (
                (KeyOutcome(False, True, "rate_limit", "429"), COOLDOWN,
                 0, 3, 0, 1, 0, (now + timedelta(minutes=15)).isoformat(), None),
                (KeyOutcome(False, True, "quota_exhausted", "quota"), QUOTA_EXHAUSTED,
                 0, 4, 0, 1, 1, None, (now + timedelta(hours=24)).isoformat()),
                (KeyOutcome(True, False), ACTIVE,
                 0, 4, 1, 1, 1, None, (now + timedelta(hours=24)).isoformat()),
                (invalid, TRANSIENT_INVALID,
                 1, 5, 1, 1, 1, (now + timedelta(minutes=15)).isoformat(), None),
                # A neutral timeout/network failure records the failure but must
                # not clear the stronger state another request just wrote.
                (KeyOutcome(False, False, "network", "connection error"), TRANSIENT_INVALID,
                 1, 6, 1, 1, 1, (now + timedelta(minutes=15)).isoformat(), None),
            )
            fields = ("status", "invalid_strikes", "failure_count", "success_count",
                      "rate_limit_count", "quota_error_count", "cooldown_until", "exhausted_until")
            for outcome, *expected in cases:
                with self.subTest(outcome=outcome):
                    manager.record_result("exa", candidate, outcome)
                    row = manager.status_rows("exa")[0]
                    self.assertEqual([row[field] for field in fields], expected)
                    self.assertEqual(row["last_error_type"], None if outcome.success else outcome.error_type)
                    self.assertEqual(row["last_failure_at"], now.isoformat())
                    self.assertEqual(bool(manager.candidates("exa", "fixture-key")), row["status"] == ACTIVE)

    def test_results_do_not_clear_manual_disable(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = SQLiteKeyManager(StateStore(Path(temp) / "state.sqlite"))
            candidate = manager.candidates("exa", "fixture-key")[0]
            manager.store.execute("UPDATE key_state SET manually_disabled = 1, status = 'disabled'")
            outcomes = (
                KeyOutcome(False, True, "invalid", "401"),
                KeyOutcome(False, True, "rate_limit", "429"),
                KeyOutcome(False, True, "quota_exhausted", "quota"),
                KeyOutcome(False, False, "error", "provider error"),
                KeyOutcome(True, False),
            )
            for outcome in outcomes:
                with self.subTest(outcome=outcome):
                    manager.record_result("exa", candidate, outcome)
                    self.assertEqual(manager.status_rows("exa")[0]["manually_disabled"], 1)
                    self.assertEqual(manager.candidates("exa", "fixture-key"), [])
            self.assertEqual(manager.reset("exa", candidate.key_id), 1)
            # Reset clears health state but must never re-enable a key the user
            # disabled by hand.
            self.assertEqual(manager.status_rows("exa")[0]["manually_disabled"], 1)
            self.assertEqual(manager.candidates("exa", "fixture-key"), [])

    def test_success_after_permanent_invalid_is_a_verified_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = SQLiteKeyManager(StateStore(Path(temp) / "state.sqlite"))
            candidate = manager.candidates("exa", "fixture-key")[0]
            invalid = KeyOutcome(False, True, "invalid", "HTTP 401 unauthorized")
            for _ in range(3):
                manager.record_result("exa", candidate, invalid)
            self.assertEqual(manager.status_rows("exa")[0]["status"], INVALID)
            manager.record_result("exa", candidate, KeyOutcome(True, False))
            row = manager.status_rows("exa")[0]
            self.assertEqual((row["status"], row["invalid_strikes"]), (ACTIVE, 0))
            self.assertEqual(
                [cand.key for cand in manager.candidates("exa", "fixture-key")],
                ["fixture-key"],
            )

    def test_concurrent_success_and_invalid_respects_causal_generation(self):
        # A success entered before the invalid failure may not clear it (the
        # failure happened while the request was in flight). Only the serial
        # order where the success starts after the failure recovers the key.
        invalid = KeyOutcome(False, True, "invalid", "HTTP 401 unauthorized")
        success = KeyOutcome(True, False)
        with tempfile.TemporaryDirectory() as temp:
            manager = SQLiteKeyManager(StateStore(Path(temp) / "state.sqlite"))
            candidate = manager.candidates("exa", "fixture-key")[0]
            manager.record_result("exa", candidate, invalid)
            manager.record_result("exa", candidate, invalid)

            # Every causally-consistent interleaving:
            #   failure commits during the success call -> INVALID 3 preserved;
            #   success starts after the failure -> normal recovery -> ACTIVE 0;
            #   success clears the seed strikes first, then a newer failure ->
            #   a fresh single strike -> TRANSIENT_INVALID 1.
            expected = {("invalid", 3), ("active", 0), ("transient_invalid", 1)}

            managers = [SQLiteKeyManager(manager.store), SQLiteKeyManager(manager.store)]
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(managers[0].record_result, "exa", candidate, success),
                    pool.submit(managers[1].record_result, "exa", candidate, invalid),
                ]
                for future in futures:
                    future.result(timeout=10)
            row = manager.status_rows("exa")[0]
            self.assertIn((row["status"], row["invalid_strikes"]), expected)

    def test_existing_database_without_strikes_migrates_and_preserves_counts(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "legacy.sqlite"
            key = "fixture-key"
            candidate = KeyCandidate(key, key_id_for("exa", key), key_fingerprint(key))
            with closing(sqlite3.connect(path)) as conn, conn:
                conn.execute("\n".join(line for line in SCHEMA[0].splitlines() if "invalid_strikes" not in line))
                conn.execute(
                    """INSERT INTO key_state
                    (provider, key_id, key_fingerprint, status, success_count, failure_count,
                     created_at, updated_at) VALUES (?, ?, ?, ?, 4, 5, ?, ?)""",
                    ("exa", candidate.key_id, candidate.fingerprint, ACTIVE, "legacy", "legacy"),
                )
            store = StateStore(path)
            manager = SQLiteKeyManager(store)
            self.assertEqual(manager.status_rows("exa")[0]["invalid_strikes"], 0)
            invalid = KeyOutcome(False, True, "invalid", "HTTP 401 unauthorized")
            for _ in range(3):
                manager.record_result("exa", candidate, invalid)
            reopened = SQLiteKeyManager(StateStore(path)).status_rows("exa")[0]
            self.assertEqual(reopened["status"], INVALID)
            self.assertEqual(reopened["invalid_strikes"], 3)
            self.assertEqual(reopened["failure_count"], 8)
            self.assertEqual(reopened["success_count"], 4)
            self.assertEqual(reopened["created_at"], "legacy")


if __name__ == "__main__":
    unittest.main()
