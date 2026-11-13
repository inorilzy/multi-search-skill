"""Brave's prepaid Search plan: a $5 monthly free credit, no monthly request cap.

Its responses advertise ``X-RateLimit-Limit: 50, 0``: the monthly window is 0
because the plan bills credits, not requests. That 0 must not read as "0
requests left"; the free credit is estimated from local calls instead. All HTTP
here is fake.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.plugins import quota_record, usage_store
from multi_search_mcp.src.plugins.base import BalanceContext
from multi_search_mcp.src.plugins.builtin import brave as brave_plugin
from multi_search_mcp.src.plugins.cache import cache_key
from multi_search_mcp.src.search.searchers import brave as brave_searcher
from multi_search_mcp.src.state.key_state import key_fingerprint
from tests.test_balance_passive import BRAVE_PAYLOAD, FakeResponse, headers

# The headers a free-credit Search plan key returned on 2026-11-12.
CREDIT_HEADERS = {
    "X-RateLimit-Limit": "50, 0",
    "X-RateLimit-Policy": "50;w=1, 0;w=2592000",
    "X-RateLimit-Remaining": "49, 0",
    "X-RateLimit-Reset": "1, 1549024",
}
NO_HTTP = BalanceContext(http=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no HTTP")))


class BraveCreditPlanTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="brave-credit-")
        self.addCleanup(temporary.cleanup)
        home = Path(temporary.name)
        patcher = mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def search(self, values=CREDIT_HEADERS):
        response = FakeResponse(BRAVE_PAYLOAD, headers=headers(**values))
        with mock.patch.object(brave_searcher, "urlopen_retry", return_value=response):
            return brave_searcher.search_brave("quota", "brave-secret")

    def calls(self, n, *, failed=0, days_ago=0):
        moment = datetime.now().astimezone() - timedelta(days=days_ago)
        for index in range(n):
            usage_store.record_call("brave", "search", failed=index < failed, now=moment)

    def test_a_zero_monthly_window_is_the_free_credit_not_zero_requests_left(self):
        self.search()
        report = brave_plugin.balance_brave("brave-secret", NO_HTTP)
        self.assertEqual((report.status, report.unit, report.period), ("ok", "usd", "month"))
        self.assertEqual(report.limit, 5.0)
        self.assertNotEqual((report.remaining, report.limit), (0, 0))
        self.assertIn("免费额度", report.message)
        self.assertIn("每秒 50 次", report.message)
        self.assertIn("本机估算", report.message)

    def test_used_credit_is_successful_local_calls_times_the_request_price(self):
        self.calls(240, failed=40)  # 200 billable searches
        self.search()
        report = brave_plugin.balance_brave("brave-secret", NO_HTTP)
        self.assertAlmostEqual(report.used, 200 * brave_plugin.BRAVE_PRICE_PER_REQUEST)
        self.assertAlmostEqual(report.remaining, 5.0 - 1.0)

    def test_calls_before_the_current_window_are_not_counted(self):
        self.calls(100, days_ago=20)  # the window started ~12 days ago (reset in ~18 days)
        self.calls(10)
        self.search()
        report = brave_plugin.balance_brave("brave-secret", NO_HTTP)
        self.assertAlmostEqual(report.used, 10 * brave_plugin.BRAVE_PRICE_PER_REQUEST)

    def test_an_exhausted_credit_is_zero_remaining_and_says_searches_will_fail(self):
        self.calls(1200)
        self.search()
        report = brave_plugin.balance_brave("brave-secret", NO_HTTP)
        self.assertEqual(report.remaining, 0)
        self.assertGreater(report.used, report.limit)
        self.assertIn("已用完", report.message)

    def test_the_search_records_credit_history_not_a_zero_request_quota(self):
        self.search()
        rows = usage_store.read_usage("brave").history
        self.assertEqual([row["unit"] for row in rows], ["usd"])
        self.assertEqual(rows[0]["limit"], 5.0)
        entry = quota_record.read_quota()[cache_key("brave", key_fingerprint("brave-secret"))]
        self.assertEqual(entry["report"]["unit"], "usd")
        reset = datetime.fromisoformat(entry["report"]["resets_at"])
        expected = datetime.now(timezone.utc) + timedelta(seconds=1549024)
        self.assertLess(abs((reset - expected).total_seconds()), 60)

    def test_a_legacy_request_plan_keeps_its_monthly_request_quota(self):
        self.search({"X-RateLimit-Remaining": "1, 999", "X-RateLimit-Limit": "1, 15000",
                     "X-RateLimit-Reset": "1, 3600"})
        report = brave_plugin.balance_brave("brave-secret", NO_HTTP)
        self.assertEqual((report.unit, report.remaining, report.limit), ("requests", 999, 15000))


if __name__ == "__main__":
    unittest.main()
