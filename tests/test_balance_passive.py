"""Passive quota recording for Brave and Stack Exchange (ticket 05).

Both providers expose remaining quota only in a successful search response, so
the searchers persist it and their balance adapters read the record without any
HTTP request. Every HTTP call here is a fake response; the suite stays offline.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from email.message import Message
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.plugins import quota_record, registry
from multi_search_mcp.src.plugins.balance import collect_balances
from multi_search_mcp.src.plugins.base import BalanceContext
from multi_search_mcp.src.plugins.builtin import brave as brave_plugin
from multi_search_mcp.src.plugins.builtin import stackexchange as stackexchange_plugin
from multi_search_mcp.src.plugins.cache import cache_key
from multi_search_mcp.src.search.searchers import brave as brave_searcher
from multi_search_mcp.src.search.searchers import stackoverflow as stackoverflow_searcher
from multi_search_mcp.src.state.key_state import key_fingerprint

BRAVE_PAYLOAD = {
    "web": {
        "results": [{
            "title": "Example result",
            "url": "https://example.com/brave",
            "description": "A Brave result",
        }],
    },
}
STACK_PAYLOAD = {
    "items": [{
        "title": "How &amp; why",
        "link": "https://stackoverflow.com/q/1",
        "score": 3,
        "answer_count": 2,
        "view_count": 10,
        "is_answered": True,
        "tags": ["python"],
        "creation_date": 1765000000,
    }],
    "quota_remaining": 2998,
    "quota_max": 10000,
}


class FakeResponse:
    """Minimal urllib response with headers and a bounded ``read``."""

    def __init__(self, payload, headers=None):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.body = body
        self.headers = headers if headers is not None else Message()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self, amount=None):
        if amount is None or amount < 0:
            return self.body
        return self.body[:amount]


def headers(**values) -> Message:
    message = Message()
    for name, value in values.items():
        message[name] = value
    return message


class PassiveQuotaTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="balance-passive-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        patcher = mock.patch.dict(
            os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)}
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def entry(self, plugin_id: str, key: str):
        return quota_record.read_quota().get(cache_key(plugin_id, key_fingerprint(key) if key else "anonymous"))

    def run_brave(self, payload, headers=None):
        response = FakeResponse(payload, headers=headers)
        with mock.patch.object(brave_searcher, "urlopen_retry", return_value=response):
            return brave_searcher.search_brave("quota", "brave-secret")

    def run_stackexchange(self, payload, api_key=""):
        response = FakeResponse(payload)
        with mock.patch.object(stackoverflow_searcher, "urlopen_retry", return_value=response):
            return stackoverflow_searcher.search_stackoverflow("quota", api_key=api_key)


class BraveQuotaTests(PassiveQuotaTestCase):
    def test_successful_search_records_monthly_quota_and_balance_reads_it(self):
        before = datetime.now(timezone.utc) + timedelta(seconds=1419704)
        rows = self.run_brave(
            BRAVE_PAYLOAD,
            headers=headers(
                **{
                    "X-RateLimit-Remaining": "1, 999",
                    "X-RateLimit-Limit": "1, 15000",
                    "X-RateLimit-Reset": "1, 1419704",
                }
            ),
        )
        after = datetime.now(timezone.utc) + timedelta(seconds=1419704)

        self.assertEqual([(row["title"], row["url"]) for row in rows], [("Example result", "https://example.com/brave")])
        entry = self.entry("brave", "brave-secret")
        self.assertIsNotNone(entry)
        fields = entry["report"]
        self.assertEqual((fields["remaining"], fields["limit"]), (999, 15000))
        self.assertEqual((fields["unit"], fields["period"]), ("requests", "month"))
        resets_at = datetime.fromisoformat(fields["resets_at"])
        self.assertTrue(before <= resets_at <= after)
        self.assertTrue(entry["fetched_at"])

        report = brave_plugin.balance_brave(
            "brave-secret", BalanceContext(http=lambda *args, **kwargs: self.fail("balance must not send HTTP")),
        )
        self.assertEqual((report.status, report.unit, report.period), ("ok", "requests", "month"))
        self.assertEqual((report.remaining, report.limit), (999, 15000))
        self.assertEqual(report.fetched_at, entry["fetched_at"])

    def test_missing_rate_limit_headers_record_nothing(self):
        rows = self.run_brave(BRAVE_PAYLOAD)

        self.assertEqual(rows[0]["title"], "Example result")
        self.assertEqual(quota_record.read_quota(), {})

    def test_malformed_rate_limit_headers_record_nothing_without_error(self):
        rows = self.run_brave(
            BRAVE_PAYLOAD,
            headers=headers(**{"X-RateLimit-Remaining": "1", "X-RateLimit-Limit": "not-a-number"}),
        )

        self.assertEqual(rows[0]["title"], "Example result")
        self.assertEqual(quota_record.read_quota(), {})

    def test_record_write_failure_does_not_change_search_results(self):
        with (
            mock.patch.object(quota_record, "_atomic_write", side_effect=OSError("read-only home")),
            self.assertLogs("multi_search_mcp.src.plugins.quota_record", level="DEBUG") as logs,
        ):
            rows = self.run_brave(
                BRAVE_PAYLOAD,
                headers=headers(
                    **{"X-RateLimit-Remaining": "1, 999", "X-RateLimit-Limit": "1, 15000"},
                ),
            )

        self.assertEqual([row["title"] for row in rows], ["Example result"])
        self.assertTrue(any("failed to record brave quota" in line for line in logs.output))

    def test_balance_without_a_record_is_unsupported_and_says_search_once(self):
        report = brave_plugin.balance_brave("brave-secret", BalanceContext())

        self.assertEqual(report.status, "unsupported")
        self.assertEqual(report.message, "搜索一次后显示")

    def test_collected_balance_reads_the_record_written_by_search(self):
        self.run_brave(
            BRAVE_PAYLOAD,
            headers=headers(
                **{
                    "X-RateLimit-Remaining": "1, 999",
                    "X-RateLimit-Limit": "1, 15000",
                    "X-RateLimit-Reset": "1, 1419704",
                }
            ),
        )

        payload = collect_balances(provider_ids=["brave"], keys={"brave": "brave-secret"})

        report = payload["providers"][0]["reports"][0]
        self.assertEqual((report["status"], report["remaining"], report["limit"]), ("ok", 999, 15000))
        self.assertEqual((report["unit"], report["period"]), ("requests", "month"))


class StackExchangeQuotaTests(PassiveQuotaTestCase):
    def test_successful_search_records_daily_quota_and_balance_reads_it(self):
        rows = self.run_stackexchange(STACK_PAYLOAD, api_key="se-secret")

        self.assertEqual(rows[0]["title"], "How & why")
        entry = self.entry("stackexchange", "se-secret")
        self.assertIsNotNone(entry)
        fields = entry["report"]
        self.assertEqual((fields["remaining"], fields["limit"]), (2998, 10000))
        self.assertEqual((fields["unit"], fields["period"]), ("requests", "day"))
        self.assertTrue(entry["fetched_at"])

        report = stackexchange_plugin.balance_stackexchange(
            "se-secret", BalanceContext(http=lambda *args, **kwargs: self.fail("balance must not send HTTP")),
        )
        self.assertEqual((report.status, report.unit, report.period), ("ok", "requests", "day"))
        self.assertEqual((report.remaining, report.limit), (2998, 10000))
        self.assertEqual(report.fetched_at, entry["fetched_at"])

    def test_anonymous_search_records_quota_under_the_fixed_anonymous_fingerprint(self):
        rows = self.run_stackexchange(STACK_PAYLOAD)

        self.assertEqual(rows[0]["title"], "How & why")
        record = quota_record.read_quota()[cache_key("stackexchange", "anonymous")]
        self.assertEqual((record["key_fingerprint"], record["report"]["remaining"]), ("anonymous", 2998))

        report = stackexchange_plugin.balance_stackexchange("", BalanceContext())
        self.assertEqual((report.status, report.remaining), ("ok", 2998))
        self.assertEqual(report.key_fingerprint, "anonymous")

    def test_missing_quota_fields_record_nothing(self):
        rows = self.run_stackexchange({"items": []})

        self.assertEqual(rows, [])
        self.assertEqual(quota_record.read_quota(), {})

    def test_non_numeric_quota_fields_record_nothing(self):
        rows = self.run_stackexchange({"items": [], "quota_remaining": "300", "quota_max": "10000"})

        self.assertEqual(rows, [])
        self.assertEqual(quota_record.read_quota(), {})

    def test_record_write_failure_does_not_change_search_results(self):
        with (
            mock.patch.object(quota_record, "_atomic_write", side_effect=OSError("read-only home")),
            self.assertLogs("multi_search_mcp.src.plugins.quota_record", level="DEBUG") as logs,
        ):
            rows = self.run_stackexchange(STACK_PAYLOAD, api_key="se-secret")

        self.assertEqual(rows[0]["title"], "How & why")
        self.assertTrue(any("failed to record stackexchange quota" in line for line in logs.output))

    def test_balance_without_a_record_is_unsupported_and_says_search_once(self):
        report = stackexchange_plugin.balance_stackexchange("", BalanceContext())

        self.assertEqual(report.status, "unsupported")
        self.assertEqual(report.message, "搜索一次后显示")

    def test_collected_anonymous_balance_reads_the_record_written_by_search(self):
        self.run_stackexchange(STACK_PAYLOAD)

        payload = collect_balances(provider_ids=["stackexchange"], keys={})

        report = payload["providers"][0]["reports"][0]
        self.assertEqual((report["status"], report["remaining"], report["limit"]), ("ok", 2998, 10000))
        self.assertEqual((report["unit"], report["period"]), ("requests", "day"))


class QuotaRecordFileTests(PassiveQuotaTestCase):
    def test_record_file_lives_under_the_multi_search_home(self):
        self.assertEqual(
            quota_record.default_quota_path(),
            self.home / ".multi-search" / "quota-records.json",
        )

    def test_corrupt_record_file_reads_as_empty(self):
        path = quota_record.default_quota_path()
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")

        self.assertEqual(quota_record.read_quota(), {})


class UnsupportedBalanceNoteTests(unittest.TestCase):
    def test_providers_without_a_balance_api_explain_the_reason(self):
        expected = {
            "baidu": ("搜索 Key 无余额接口", "免费额度无查询接口", "AK/SK", "暂不支持"),
            "hackernews": ("Hacker News", "无配额查询接口"),
            "sov2ex": ("V2EX", "无配额查询接口"),
            "twitter": ("Twitter", "无余额查询接口"),
        }

        for plugin_id, phrases in expected.items():
            with self.subTest(plugin=plugin_id):
                plugin = registry.get_plugin(plugin_id)
                self.assertIsNone(plugin.balance)
                for phrase in phrases:
                    self.assertIn(phrase, plugin.balance_note)

    def test_brave_and_stackexchange_declare_the_passive_balance_reader(self):
        self.assertIs(registry.get_plugin("brave").balance, brave_plugin.balance_brave)
        self.assertIs(registry.get_plugin("stackexchange").balance, stackexchange_plugin.balance_stackexchange)


if __name__ == "__main__":
    unittest.main()
