"""T01 usage-store contract: real SQLite files, isolated homes, no network."""
from __future__ import annotations

import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.plugins import usage_store
from multi_search_mcp.src.plugins.base import BalanceReport
from multi_search_mcp.src.state.key_state import key_fingerprint


NOW = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)
LOGGER = "multi_search_mcp.src.plugins.usage_store"


def report(**overrides):
    values = {
        "provider": "tavily", "status": "ok", "scope": "key", "unit": "credits",
        "remaining": 90, "limit": 100, "used": 10,
        "key_fingerprint": key_fingerprint("fixture-key"),
        "resets_at": "2026-12-01T00:00:00Z", "period": "month",
        "fetched_at": NOW.isoformat(),
    }
    values.update(overrides)
    return BalanceReport(**values)


class UsageStoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="usage-store-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        environment = mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)})
        environment.start()
        self.addCleanup(environment.stop)
        self.path = self.home / ".multi-search" / "usage.sqlite"

    def read(self, provider=None, **kwargs):
        return usage_store.read_usage(provider, now=NOW, **kwargs)

    def append(self, observation=None, **kwargs):
        usage_store.append_balance(observation or report(), now=NOW, **kwargs)

    def call(self, provider="tavily", purpose="search", **kwargs):
        usage_store.record_call(provider, purpose, now=NOW, **kwargs)

    def test_home_resolution_is_dynamic_and_reads_do_not_create_files(self):
        self.assertEqual(usage_store.default_usage_path(), self.path)
        self.assertEqual(self.read(), usage_store.UsageSnapshot())
        self.assertFalse(self.path.parent.exists())
        self.append()
        other = self.home / "other"
        with mock.patch.dict(os.environ, {"HOME": str(other), "USERPROFILE": ""}):
            self.assertEqual(usage_store.default_usage_path(), other / ".multi-search" / "usage.sqlite")
            self.assertEqual(self.read(), usage_store.UsageSnapshot())
            self.call()
            self.assertTrue(usage_store.default_usage_path().exists())
        self.assertEqual(len(self.read().history), 1)
        self.assertFalse((self.path.parent / "state.sqlite").exists())
        self.assertEqual(
            usage_store.default_usage_path({"HOME": "/home", "USERPROFILE": "/profile"}),
            Path("/profile/.multi-search/usage.sqlite"),
        )

    def test_explicit_path_and_full_balance_shape_preserve_unknown_numbers(self):
        # URI-special characters must survive the sqlite file: URI; Windows forbids "?" in names.
        path = self.home / "custom" / ("usage%#.sqlite" if os.name == "nt" else "usage?#.sqlite")
        self.append(report(remaining=None, limit=None, used=None), path=path)
        result = self.read(path=path)
        self.assertIsNone(result.usage_error)
        self.assertEqual(result.daily, [])
        self.assertEqual(result.history, [{
            "provider": "tavily", "key_fingerprint": key_fingerprint("fixture-key"),
            "scope": "key", "unit": "credits", "remaining": None, "limit": None,
            "used": None, "resets_at": "2026-12-01T00:00:00.000000+00:00",
            "period": "month", "fetched_at": NOW.isoformat(timespec="microseconds"),
        }])
        self.assertFalse(self.path.exists())
        with closing(sqlite3.connect(path)) as conn:
            self.assertEqual(
                {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")},
                {"balance_history", "call_daily"},
            )

    def test_balance_identity_deduplicates_null_and_fingerprinted_keys(self):
        for fingerprint in (None, "anonymous", key_fingerprint("fixture-key")):
            observation = report(key_fingerprint=fingerprint)
            self.append(observation)
            self.append(replace(observation, remaining=1))
            self.append(replace(observation, fetched_at="2026-11-12T06:00:00-06:00"))
        rows = self.read().history
        self.assertEqual(len(rows), 3)
        self.assertEqual([row["remaining"] for row in rows], [90, 90, 90])
        for changes in (
            {"provider": "exa"}, {"scope": "account"}, {"unit": "usd"},
            {"fetched_at": (NOW - timedelta(hours=1)).isoformat()},
        ):
            self.append(report(**changes))
        self.assertEqual(len(self.read().history), 7)

    def test_non_ok_reports_do_not_create_a_database(self):
        for status in ("unsupported", "needs_credential", "error"):
            self.append(report(status=status))
        self.assertFalse(self.path.exists())

    def test_daily_counts_accumulate_by_plugin_purpose_and_local_day(self):
        self.call()
        self.call(failed=True)
        self.call(purpose="scrape", failed=True)
        self.call(provider="github")
        yesterday = NOW - timedelta(days=1)
        usage_store.record_call("tavily", "search", now=yesterday)
        rows = self.read().daily
        today = NOW.astimezone().date().isoformat()
        self.assertEqual(rows, [
            {"day": yesterday.astimezone().date().isoformat(), "provider": "tavily", "purpose": "search", "calls": 1, "failures": 0},
            {"day": today, "provider": "github", "purpose": "search", "calls": 1, "failures": 0},
            {"day": today, "provider": "tavily", "purpose": "scrape", "calls": 1, "failures": 1},
            {"day": today, "provider": "tavily", "purpose": "search", "calls": 2, "failures": 1},
        ])

    def test_local_date_uses_machine_timezone_not_timestamp_offset(self):
        # Select an instant just after local midnight, expressed in another zone.
        local = datetime(2026, 11, 12, 0, 15).astimezone()
        supplied = local.astimezone(timezone(timedelta(hours=-12)))
        usage_store.record_call("github", "search", now=supplied)
        result = usage_store.read_usage(now=supplied, days=1)
        self.assertEqual(result.daily[0]["day"], "2026-11-12")

    def test_provider_and_day_filters_apply_to_both_datasets(self):
        for days_ago in (6, 0, 7, 1):
            moment = NOW - timedelta(days=days_ago)
            for provider in ("tavily", "github"):
                usage_store.append_balance(report(provider=provider, fetched_at=moment.isoformat()), now=moment)
                usage_store.record_call(provider, "search", now=moment)
        result = self.read("github", days=7)
        self.assertEqual([row["provider"] for row in result.history], ["github"] * 4)
        self.assertEqual([row["provider"] for row in result.daily], ["github"] * 3)
        self.assertEqual(
            [row["fetched_at"] for row in result.history],
            [(NOW - timedelta(days=days)).isoformat(timespec="microseconds") for days in (7, 6, 1, 0)],
        )
        self.assertEqual(len(self.read(days=1).daily), 2)
        self.assertEqual(self.read("unknown"), usage_store.UsageSnapshot())
        self.assertEqual(self.read("github' OR 1=1 --"), usage_store.UsageSnapshot())

    def test_days_validation_is_explicit_and_has_no_file_side_effect(self):
        for days in (0, -1, 31, True, 1.5, "7", None):
            with self.subTest(days=days), self.assertRaises(ValueError):
                self.read(days=days)
        self.assertFalse(self.path.exists())

    def test_each_writer_prunes_both_tables_and_duplicate_writes_also_prune(self):
        self.assertEqual(usage_store.USAGE_RETENTION_DAYS, 30)
        for operation in ("balance", "call", "duplicate"):
            with self.subTest(operation=operation):
                path = self.home / operation / "usage.sqlite"
                for days_ago in (31, 30, 29):
                    moment = NOW - timedelta(days=days_ago)
                    usage_store.append_balance(report(fetched_at=moment.isoformat()), path=path, now=moment)
                    usage_store.record_call("tavily", "search", path=path, now=moment)
                if operation == "call":
                    self.call(provider="github", path=path)
                else:
                    age = 29 if operation == "duplicate" else 0
                    self.append(report(fetched_at=(NOW - timedelta(days=age)).isoformat()), path=path)
                with closing(sqlite3.connect(path)) as conn:
                    history = [row[0] for row in conn.execute("SELECT fetched_at FROM balance_history ORDER BY fetched_at")]
                    days = [row[0] for row in conn.execute("SELECT day FROM call_daily ORDER BY day")]
                expected_history_ages = (30, 29, 0) if operation == "balance" else (30, 29)
                self.assertEqual(history, [
                    (NOW - timedelta(days=age)).isoformat(timespec="microseconds") for age in expected_history_ages
                ])
                expected_day_ages = (29, 0) if operation == "call" else (29,)
                self.assertEqual(days, [
                    (NOW - timedelta(days=age)).astimezone().date().isoformat() for age in expected_day_ages
                ])

    def test_old_observation_is_not_reintroduced_and_reads_do_not_prune(self):
        old = NOW - timedelta(days=31)
        usage_store.append_balance(report(fetched_at=old.isoformat()), now=old)
        before = self.path.read_bytes()
        self.assertEqual(self.read(), usage_store.UsageSnapshot())
        self.assertEqual(self.path.read_bytes(), before)
        self.append(report(fetched_at=old.isoformat()))
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM balance_history").fetchone()[0], 0)

    def test_only_allowlisted_fields_and_fingerprints_reach_disk(self):
        secrets = ["fixture-raw-api-key", "Bearer fixture-token", "private@example.test", "private search words", "https://example.test/private"]
        self.append(report(message=" ".join(secrets), error_kind=secrets[0]))
        for secret in secrets:
            with self.assertLogs(LOGGER, level="DEBUG") as logs:
                self.append(report(key_fingerprint=secret))
            self.assertNotIn(secret, " ".join(logs.output))
        self.append(report(
            fetched_at=(NOW - timedelta(hours=1)).isoformat(),
            resets_at=secrets[-1], period=secrets[0], remaining=secrets[2], limit=True, used=float("nan"),
        ))
        self.call()
        payload = json.dumps(self.read().history)
        disk = self.path.read_bytes()
        for secret in secrets:
            self.assertNotIn(secret, payload)
            self.assertNotIn(secret.encode(), disk)
        first = self.read().history[0]
        self.assertEqual([first[name] for name in ("resets_at", "period", "remaining", "limit", "used")], [None] * 5)
        self.assertEqual(len(self.read().history), 2)

    def test_invalid_call_metadata_is_dropped_without_logging_payload(self):
        for provider, purpose, failed in (
            ("private@example.test", "search", False),
            ("tavily", "https://example.test/private", False),
            ("tavily", "search", "fixture-token"),
        ):
            with self.assertLogs(LOGGER, level="DEBUG") as logs:
                self.call(provider, purpose, failed=failed)
            self.assertEqual(logs.output, [f"DEBUG:{LOGGER}:failed to record usage call"])
        self.assertFalse(self.path.exists())

    def test_corrupt_and_empty_files_are_not_replaced_or_modified(self):
        self.path.parent.mkdir(parents=True)
        for data in (b"not a sqlite database\x00private fixture", b""):
            with self.subTest(data=data):
                self.path.write_bytes(data)
                before = self.path.stat().st_mtime_ns
                result = self.read()
                self.assertEqual(result, usage_store.UsageSnapshot(usage_error="unreadable"))
                with self.assertLogs(LOGGER, level="DEBUG"):
                    self.append()
                    self.call()
                self.assertEqual(self.path.read_bytes(), data)
                self.assertEqual(self.path.stat().st_mtime_ns, before)
                self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_incompatible_database_returns_no_partial_data_and_is_unchanged(self):
        self.append()
        self.call()
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("ALTER TABLE call_daily RENAME TO unknown_daily")
        before = self.path.read_bytes()
        self.assertEqual(self.read(), usage_store.UsageSnapshot(usage_error="unreadable"))
        self.append()
        self.call()
        self.assertEqual(self.path.read_bytes(), before)

    def test_unreadable_file_and_unwritable_parent_are_nonfatal(self):
        self.append()
        before = self.path.read_bytes()
        with mock.patch.object(usage_store.sqlite3, "connect", side_effect=PermissionError("fixture-secret")):
            with self.assertLogs(LOGGER, level="DEBUG") as logs:
                self.assertEqual(self.read(), usage_store.UsageSnapshot(usage_error="unreadable"))
                self.append()
                self.call()
            self.assertNotIn("fixture-secret", " ".join(logs.output))
        self.assertEqual(self.path.read_bytes(), before)
        blocked = self.home / "not-a-directory"
        blocked.write_text("fixture", encoding="utf-8")
        with self.assertLogs(LOGGER, level="DEBUG"):
            self.call(path=blocked / "usage.sqlite")
        self.assertEqual(blocked.read_text(encoding="utf-8"), "fixture")

    def test_unix_file_permissions_and_wal_mode(self):
        self.call()
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
            self.path.chmod(0o644)
            self.call()
            self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
            self.path.chmod(0)
            self.addCleanup(self.path.chmod, 0o600)
            with self.assertLogs(LOGGER, level="DEBUG"):
                self.assertEqual(self.read(), usage_store.UsageSnapshot(usage_error="unreadable"))
                self.call()
            self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0)

    def test_cross_process_lock_contention_drops_only_that_attempt(self):
        self.call()
        script = """
import logging
import sys
from datetime import datetime
from multi_search_mcp.src.plugins.usage_store import append_balance, record_call
from multi_search_mcp.src.plugins.base import BalanceReport
logging.basicConfig(level=logging.DEBUG)
now = datetime.fromisoformat(sys.argv[2])
append_balance(BalanceReport(provider='tavily', status='ok', fetched_at=now.isoformat()), path=sys.argv[1], now=now)
record_call('tavily', 'search', failed=True, path=sys.argv[1], now=now)
"""
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            child = subprocess.run(
                [sys.executable, "-c", script, str(self.path), NOW.isoformat()],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(child.returncode, 0, child.stderr)
            self.assertEqual(child.stderr.count("failed to write usage data"), 2)
            self.assertEqual(self.read().history, [])
            self.assertEqual(self.read().daily[0]["calls"], 1)
            conn.rollback()
        self.call(failed=True)
        self.assertEqual((self.read().daily[0]["calls"], self.read().daily[0]["failures"]), (2, 1))

    def test_concurrent_processes_do_not_lose_successful_increments(self):
        self.call()
        script = """
import logging
import sys
from datetime import datetime
from multi_search_mcp.src.plugins.usage_store import record_call
logging.basicConfig(level=logging.DEBUG)
for _ in range(12):
    record_call('tavily', 'search', failed=True, path=sys.argv[1], now=datetime.fromisoformat(sys.argv[2]))
"""
        children = [subprocess.Popen(
            [sys.executable, "-c", script, str(self.path), NOW.isoformat()],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        ) for _ in range(3)]
        dropped = 0
        try:
            for child in children:
                _, stderr = child.communicate(timeout=10)
                self.assertEqual(child.returncode, 0, stderr)
                dropped += stderr.count("failed to write usage data")
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                    child.communicate()
        row = self.read().daily[0]
        self.assertLess(dropped, 36)
        self.assertEqual((row["calls"], row["failures"]), (37 - dropped, 36 - dropped))


if __name__ == "__main__":
    unittest.main()
