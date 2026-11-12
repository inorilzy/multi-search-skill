"""T02 balance history through real adapters with fake HTTP and SQLite rows."""
from __future__ import annotations

import io
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from multi_search_mcp import cli
from multi_search_mcp.src.plugins import balance, quota_record, usage_store
from multi_search_mcp.src.plugins.base import BalanceReport
from multi_search_mcp.src.search.searchers import brave, stackoverflow
from multi_search_mcp.src.state.key_state import key_fingerprint
from tests.test_balance_passive import BRAVE_PAYLOAD, STACK_PAYLOAD, FakeResponse, headers


NOW = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)
TAVILY_PAYLOAD = {
    "key": {"usage": 25, "limit": 100},
    "account": {"plan_usage": 50, "plan_limit": 200},
}


class BalanceHistoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="balance-history-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        environment = mock.patch.dict(os.environ, {
            "HOME": str(self.home), "USERPROFILE": str(self.home),
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.path = self.home / ".multi-search" / "usage.sqlite"
        for module in (usage_store, brave):
            clock = mock.patch.object(module, "datetime", wraps=datetime)
            clock.start().now.return_value = NOW
            self.addCleanup(clock.stop)
        observed_clock = mock.patch.object(quota_record, "_now_iso", return_value=NOW.isoformat())
        observed_clock.start()
        self.addCleanup(observed_clock.stop)
        report_clock = mock.patch("multi_search_mcp.src.plugins.base.datetime", wraps=datetime)
        report_clock.start().now.return_value = NOW
        self.addCleanup(report_clock.stop)

    def history(self):
        snapshot = usage_store.read_usage(now=NOW + timedelta(days=1))
        self.assertIsNone(snapshot.usage_error)
        return snapshot.history

    def collect(self, providers=("tavily",), keys=None, payload=None, **kwargs):
        response = FakeResponse(TAVILY_PAYLOAD if payload is None else payload)
        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", return_value=response):
            return balance.collect_balances(
                provider_ids=providers,
                keys={"tavily": "fixture-key"} if keys is None else keys,
                now=NOW,
                **kwargs,
            )

    def run_cli(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(balance, "load_keys", return_value={"tavily": "fixture-key"}),
            mock.patch(
                "multi_search_mcp.src.support.http.urlopen_retry",
                return_value=FakeResponse(TAVILY_PAYLOAD),
            ),
        ):
            code = cli.main(
                ["balance", "--provider", "tavily", "--refresh"], stdout=stdout, stderr=stderr,
            )
        return code, stdout.getvalue(), stderr.getvalue()

    def run_search(self, provider, key="fixture-key"):
        if provider == "brave":
            response = FakeResponse(BRAVE_PAYLOAD, headers=headers(**{
                "X-RateLimit-Remaining": "1, 999",
                "X-RateLimit-Limit": "1, 15000",
                "X-RateLimit-Reset": "1, 3600",
            }))
            with mock.patch.object(brave, "urlopen_retry", return_value=response):
                return brave.search_brave("quota", key)
        with mock.patch.object(stackoverflow, "urlopen_retry", return_value=FakeResponse(STACK_PAYLOAD)):
            return stackoverflow.search_stackoverflow("quota", api_key=key)

    def block_writes(self):
        connection = sqlite3.connect(self.path)
        connection.execute("BEGIN IMMEDIATE")
        self.addCleanup(connection.close)
        return connection

    def test_each_fresh_ok_report_for_each_key_is_stored_with_matching_fields(self):
        payload = self.collect(keys={"tavily": ["first-key", "second-key"]})

        reports = payload["providers"][0]["reports"]
        self.assertEqual(len(reports), 4)
        rows = self.history()
        self.assertEqual(len(rows), 4)
        for report in reports:
            expected = {field: report[field] for field in rows[0]}
            expected["fetched_at"] = NOW.isoformat(timespec="microseconds")
            self.assertIn(expected, rows)

    def test_fresh_report_keeps_unknown_numbers_and_reset_time(self):
        payload = self.collect(
            providers=["firecrawl"], keys={"firecrawl": "fixture-key"},
            payload={"success": True, "data": {
                "remainingCredits": None,
                "planCredits": None,
                "billingPeriodEnd": "2026-12-01T00:00:00.000Z",
            }},
        )

        report = payload["providers"][0]["reports"][0]
        self.assertEqual(report["status"], "ok")
        self.assertEqual(self.history(), [{
            "provider": "firecrawl", "key_fingerprint": key_fingerprint("fixture-key"),
            "scope": "team", "unit": "credits", "remaining": None, "limit": None,
            "used": None, "resets_at": "2026-12-01T00:00:00.000000+00:00",
            "period": None, "fetched_at": NOW.isoformat(timespec="microseconds"),
        }])

    def test_cached_reports_do_not_repopulate_deleted_history(self):
        first = self.collect()
        self.assertEqual(len(self.history()), 2)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("DELETE FROM balance_history")
        with mock.patch(
            "multi_search_mcp.src.support.http.urlopen_retry",
            side_effect=AssertionError("cache hit must not send HTTP"),
        ):
            second = balance.collect_balances(
                provider_ids=["tavily"], keys={"tavily": "fixture-key"}, now=NOW,
            )

        self.assertEqual(second, first)
        self.assertEqual(self.history(), [])

    def test_forced_refresh_appends_new_observations(self):
        self.collect()
        later = NOW + timedelta(hours=1)
        with mock.patch("multi_search_mcp.src.plugins.base.datetime", wraps=datetime) as clock:
            clock.now.return_value = later
            self.collect(refresh=True)

        self.assertEqual(len(self.history()), 4)
        self.assertEqual(
            {row["fetched_at"] for row in self.history()},
            {moment.isoformat(timespec="microseconds") for moment in (NOW, later)},
        )

    def test_needs_credential_report_does_not_write_history(self):
        payload = self.collect(keys={})

        self.assertEqual(payload["providers"][0]["reports"][0]["status"], "needs_credential")
        self.assertEqual(self.history(), [])

    def test_unsupported_report_does_not_write_history(self):
        payload = self.collect(providers=["hackernews"], keys={})

        self.assertEqual(payload["providers"][0]["reports"][0]["status"], "unsupported")
        self.assertEqual(self.history(), [])

    def test_error_report_does_not_write_history(self):
        with mock.patch("multi_search_mcp.src.support.http.urlopen_retry", side_effect=OSError("offline")):
            payload = balance.collect_balances(provider_ids=["tavily"], keys={"tavily": "fixture-key"})

        self.assertEqual(payload["providers"][0]["reports"][0]["status"], "error")
        self.assertEqual(self.history(), [])

    def test_brave_search_writes_monthly_history_at_observation_time(self):
        observed = NOW - timedelta(hours=2)
        with mock.patch.object(quota_record, "_now_iso", return_value=observed.isoformat()):
            results = self.run_search("brave")

        self.assertEqual(results[0]["title"], "Example result")
        rows = self.history()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0], {
            "provider": "brave", "key_fingerprint": key_fingerprint("fixture-key"),
            "scope": "key", "unit": "requests", "remaining": 999, "limit": 15000,
            "used": None, "resets_at": (NOW + timedelta(hours=1)).isoformat(timespec="microseconds"),
            "period": "month",
            "fetched_at": observed.isoformat(timespec="microseconds"),
        })

    def test_stackexchange_search_writes_daily_history_at_observation_time(self):
        observed = NOW - timedelta(hours=1)
        with mock.patch.object(quota_record, "_now_iso", return_value=observed.isoformat()):
            results = self.run_search("stackexchange", key="")

        self.assertEqual(results[0]["title"], "How & why")
        self.assertEqual(self.history(), [{
            "provider": "stackexchange", "key_fingerprint": "anonymous",
            "scope": "key", "unit": "requests", "remaining": 2998, "limit": 10000,
            "used": None, "resets_at": None, "period": "day",
            "fetched_at": observed.isoformat(timespec="microseconds"),
        }])

    def test_reading_passive_balance_does_not_repopulate_history(self):
        for provider in ("brave", "stackexchange"):
            with self.subTest(provider=provider):
                self.run_search(provider)
                self.assertTrue(self.history())
                with closing(sqlite3.connect(self.path)) as connection, connection:
                    connection.execute("DELETE FROM balance_history")
                payload = self.collect(
                    providers=[provider], keys={provider: "fixture-key"}, refresh=True,
                )
                self.assertEqual(payload["providers"][0]["reports"][0]["status"], "ok")
                self.assertEqual(self.history(), [])

    def test_locked_usage_database_keeps_balance_cli_output_and_exit_code(self):
        expected = self.run_cli()
        self.assertEqual(expected[0], 0, expected[2])
        before = self.history()
        self.assertEqual(len(before), 2)
        lock = self.block_writes()
        actual = self.run_cli()
        lock.rollback()

        self.assertEqual(actual, expected)
        self.assertEqual(self.history(), before)

    def test_locked_usage_database_keeps_search_results(self):
        usage_store.append_balance(BalanceReport(provider="tavily", status="ok", fetched_at=NOW.isoformat()))
        for provider in ("brave", "stackexchange"):
            with self.subTest(provider=provider):
                with mock.patch.object(quota_record, "_now_iso", return_value=NOW.isoformat()):
                    expected = self.run_search(provider)
                before = self.history()
                lock = self.block_writes()
                with mock.patch.object(
                    quota_record, "_now_iso", return_value=(NOW + timedelta(hours=1)).isoformat(),
                ):
                    actual = self.run_search(provider)
                lock.rollback()
                lock.close()
                self.assertEqual(actual, expected)
                self.assertEqual(self.history(), before)


if __name__ == "__main__":
    unittest.main()
