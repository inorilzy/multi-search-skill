"""Brave's real monthly usage comes from its API dashboard, not a local estimate.

The dashboard's SvelteKit data endpoint (devalue-encoded, streamed in chunks)
carries each plan's monthly credit, this month's requests and cost, and the days
left in the cycle. It needs the dashboard's login cookie, which the desktop's
Brave login window captures into owner-only oauth.json (or the process supplies
BRAVE_DASHBOARD_COOKIE). All HTTP here is fake; the fixture is synthetic.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.plugins import accounts, oauth_store, usage_report
from multi_search_mcp.src.plugins.balance import collect_balances
from multi_search_mcp.src.plugins.base import BalanceContext
from multi_search_mcp.src.state.keys import load_keys
from multi_search_mcp.src.plugins.builtin import brave as brave_plugin
from multi_search_mcp.src.plugins.builtin import brave_dashboard

FIXTURE = (Path(__file__).parent / "fixtures" / "brave_dashboard_data.txt").read_text(encoding="utf-8")


class FakeResponse:
    def __init__(self, body: str, status: int = 200):
        self.body = body.encode()
        self.status = status
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, amount=None):
        return self.body if amount is None else self.body[:amount]


class BraveDashboardTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="brave-dashboard-")
        self.addCleanup(temporary.cleanup)
        patcher = mock.patch.dict(os.environ, {"HOME": temporary.name, "USERPROFILE": temporary.name}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop(brave_dashboard.COOKIE_ENV, None)

    def test_decodes_plans_usage_and_cycle(self):
        data = brave_dashboard.parse_dashboard(FIXTURE)
        self.assertEqual(data["days_left"], 18)
        self.assertEqual({plan["name"]: (plan["credit"], plan["requests"], plan["cost"]) for plan in data["plans"]},
                         {"Search": (5, 52, 0.26), "Answers": (5, 3, 0)})

    def test_balance_reports_the_real_monthly_spend_when_a_cookie_is_given(self):
        seen = []

        def http(request, **kwargs):
            seen.append(request)
            return FakeResponse(FIXTURE)

        with mock.patch.dict(os.environ, {brave_dashboard.COOKIE_ENV: "search_api_users_auth=synthetic"}):
            report = brave_plugin.balance_brave("brave-secret", BalanceContext(http=http))
        self.assertEqual((report.status, report.unit, report.scope), ("ok", "usd", "account"))
        self.assertEqual((report.limit, report.used), (5, 0.26))
        self.assertAlmostEqual(report.remaining, 4.74)
        self.assertIn("dashboard", report.message)
        self.assertIn("52 次", report.message)
        self.assertEqual(seen[0].full_url, brave_dashboard.DATA_URL)
        self.assertEqual(seen[0].get_header("Cookie"), "search_api_users_auth=synthetic")
        self.assertNotIn("synthetic", report.message)

    def test_without_a_cookie_no_dashboard_request_is_sent(self):
        report = brave_plugin.balance_brave(
            "brave-secret", BalanceContext(http=lambda *a, **k: self.fail("no dashboard without a cookie")),
        )
        self.assertNotEqual(report.scope, "account")

    def test_a_logged_out_dashboard_falls_back_to_the_local_estimate(self):
        def http(request, **kwargs):
            return FakeResponse('{"type":"redirect","location":"/login"}')

        with mock.patch.dict(os.environ, {brave_dashboard.COOKIE_ENV: "search_api_users_auth=expired"}):
            report = brave_plugin.balance_brave("brave-secret", BalanceContext(http=http))
        self.assertNotEqual(report.scope, "account")
        self.assertIn("dashboard 登录已失效", report.message)

    def test_saved_session_is_reusable_without_a_browser_and_not_a_search_key(self):
        oauth_store.set_entry("brave_dashboard", {"cookie_header": "search_api_users_auth=saved-fixture", "login_id": "fixture"})
        self.assertEqual(brave_dashboard.cookie_header(), "search_api_users_auth=saved-fixture")
        self.assertNotIn("brave_dashboard", load_keys())
        public = accounts.list_accounts("brave")
        self.assertIn("brave_dashboard", public["brave"][0]["balance_credentials"])
        self.assertNotIn("saved-fixture", json.dumps(public))
        self.assertIn("saved-fixture", oauth_store.secret_values())
        self.assertEqual(oauth_store.balance_credentials()["brave_dashboard"], "oauth-login:brave_dashboard:fixture")

    def test_real_balance_is_cached_and_retained_in_history_for_offline_views(self):
        with mock.patch.dict(os.environ, {brave_dashboard.COOKIE_ENV: "search_api_users_auth=synthetic"}), \
             mock.patch("multi_search_mcp.src.support.http.urlopen_retry", return_value=FakeResponse(FIXTURE)) as http:
            collect_balances(["brave"], refresh=True, keys={"brave": "search-key-fixture"})
            self.assertEqual(http.call_count, 1)
            view = usage_report.collect_usage(["brave"], keys={"brave": "search-key-fixture"})["providers"][0]
            self.assertEqual(http.call_count, 1, "an offline usage view must not contact the dashboard")
        self.assertAlmostEqual(view["total"]["remaining"], 4.74)
        self.assertEqual(view["current"][0]["scope"], "account")
        self.assertEqual(view["history"][0]["scope"], "account")
        self.assertNotIn("synthetic", json.dumps(view))

    def test_cycles_and_invalid_dashboard_shapes_are_rejected(self):
        cyclic = json.dumps({"type": "data", "nodes": [{"data": [{"daysLeftInCycle": 0}]}]})
        for text in ("not JSON", cyclic, '{"type":"data","nodes":[]}', '<!doctype html><html>Login</html>'):
            with self.subTest(text=text), self.assertRaises(brave_dashboard.DashboardUnavailable):
                brave_dashboard.parse_dashboard(text)

    def test_missing_search_usage_falls_back_instead_of_making_up_zeroes(self):
        lines = [json.loads(line) for line in FIXTURE.splitlines()]
        lines[1]["data"][1] = [2]  # Answers is a separate plan, never Search credit.
        text = "\n".join(json.dumps(line) for line in lines)
        with mock.patch.dict(os.environ, {brave_dashboard.COOKIE_ENV: "search_api_users_auth=synthetic"}):
            report = brave_plugin.balance_brave("search-key", BalanceContext(http=lambda *a, **k: FakeResponse(text)))
        self.assertNotEqual(report.scope, "account")
        self.assertIn("dashboard 暂不可用", report.message)

    def test_http_auth_rejection_and_network_errors_cannot_echo_the_cookie(self):
        for error in (urllib.error.HTTPError(brave_dashboard.DATA_URL, 401, "synthetic-secret", {}, None),
                      urllib.error.URLError("synthetic-secret")):
            with self.subTest(error=type(error).__name__), mock.patch.dict(os.environ, {
                brave_dashboard.COOKIE_ENV: "search_api_users_auth=synthetic-secret",
            }):
                report = brave_plugin.balance_brave("search-key", BalanceContext(http=mock.Mock(side_effect=error)))
            self.assertNotEqual(report.scope, "account")
            self.assertNotIn("synthetic-secret", report.message)

    def test_non_finite_missing_and_boolean_costs_are_not_real_balances(self):
        for invalid in (None, True, "0.26", float("nan"), float("inf")):
            lines = [json.loads(line) for line in FIXTURE.splitlines()]
            lines[1]["data"][27] = invalid
            text = "\n".join(json.dumps(line) for line in lines)
            with self.subTest(invalid=invalid), mock.patch.dict(os.environ, {
                brave_dashboard.COOKIE_ENV: "search_api_users_auth=synthetic",
            }):
                report = brave_plugin.balance_brave("search-key", BalanceContext(http=lambda *a, **k: FakeResponse(text)))
                self.assertNotEqual(report.scope, "account")

    def test_cookie_header_injection_is_rejected_before_any_request(self):
        with mock.patch.dict(os.environ, {brave_dashboard.COOKIE_ENV: "auth=x\r\nAuthorization: injected"}):
            report = brave_plugin.balance_brave("search-key", BalanceContext(http=lambda *a, **k: self.fail("invalid header")))
        self.assertNotEqual(report.scope, "account")


if __name__ == "__main__":
    unittest.main()
