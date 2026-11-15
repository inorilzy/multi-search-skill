"""Exa dashboard balances using synthetic responses with the observed API shape."""
from __future__ import annotations

import io
import json
import math
import os
import unittest
import urllib.error
from unittest import mock

from multi_search_mcp.src.plugins import oauth_store
from multi_search_mcp.src.plugins.base import BalanceContext
from multi_search_mcp.src.plugins.builtin import exa, exa_dashboard
from multi_search_mcp.src.state.key_state import key_fingerprint

COOKIE = "__Secure-next-auth.session-token=synthetic-session; team=synthetic-team"
REF = "oauth-login:exa_admin:synthetic-login"
# Synthetic values only; field names match the live read-only dashboard endpoints.
CREDITS = {
    "orbCreditsInCents": 1234.5,
    "orbInvoiceDebt": 234.5,
    "expiringCredits": [{"balanceCents": 200, "expiresAt": "2030-01-01T00:00:00Z"}],
}
PLAN = {"subscription": {"id": "synthetic-subscription", "status": "active",
                         "plan": {"external_plan_id": "search_api_payg_free"}}}


class FakeResponse:
    def __init__(self, data):
        self.body = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.headers = {"Content-Length": str(len(self.body))}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, amount=None):
        return self.body if amount is None else self.body[:amount]


class ExaDashboardTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {exa_dashboard.COOKIE_ENV: ""})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.record = {"cookie_header": COOKIE, "login_id": "synthetic-login"}
        patcher = mock.patch.object(oauth_store, "get_entry", return_value=self.record)
        self.get_entry = patcher.start()
        self.addCleanup(patcher.stop)
        self.requests = []
        self.options = []

    def context(self, credits=CREDITS, plan=PLAN):
        responses = [credits, plan]

        def http(request, **kwargs):
            self.requests.append(request)
            self.options.append(kwargs)
            value = responses.pop(0)
            if isinstance(value, BaseException):
                raise value
            return FakeResponse(value)

        return BalanceContext(timeout=7, http=http)

    def test_login_reference_reads_dashboard_with_cookie_and_stable_fingerprint(self):
        report = exa.balance_exa(REF, self.context())
        self.get_entry.assert_called_once_with("exa_admin")
        self.assertEqual((report.status, report.scope, report.unit), ("ok", "team", "usd"))
        self.assertEqual(report.remaining, 10)
        self.assertIsNone(report.used)
        self.assertIsNone(report.limit)
        self.assertEqual(report.key_fingerprint, key_fingerprint(REF))
        self.assertEqual([r.full_url for r in self.requests],
                         [exa_dashboard.CREDITS_URL, exa_dashboard.PLAN_URL])
        for request, options in zip(self.requests, self.options):
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(request.get_header("Cookie"), COOKIE)
            self.assertEqual(request.get_header("User-agent"), exa_dashboard.BROWSER_USER_AGENT)
            self.assertIsNone(request.get_header("X-api-key"))
            self.assertEqual(options["timeout"], 7)
            self.assertEqual(options["retries"], 0)
        rendered = json.dumps(report.to_dict())
        for secret in (COOKIE, "synthetic-session", "synthetic-team", "synthetic-subscription"):
            self.assertNotIn(secret, rendered)

    def test_enterprise_plans_clamp_credits_and_do_not_subtract_invoice_debt(self):
        for plan_id in ("search_api_enterprise", "search_websets"):
            for cents, expected in ((1234.5, 12.345), (-100, 0)):
                with self.subTest(plan=plan_id, cents=cents):
                    credits = {**CREDITS, "orbCreditsInCents": cents}
                    plan = {"subscription": {"plan": {"external_plan_id": plan_id}}}
                    report = exa.balance_exa(REF, self.context(credits, plan))
                    self.assertEqual(report.remaining, expected)

    def test_payg_can_report_negative_remaining_and_missing_debt_defaults_to_zero(self):
        for data, expected in (({"orbCreditsInCents": -50}, -0.5),
                               ({"orbCreditsInCents": 20, "orbInvoiceDebt": 50}, -0.3),
                               ({"orbCreditsInCents": 20, "orbInvoiceDebt": None}, 0.2)):
            with self.subTest(data=data):
                self.assertEqual(exa.balance_exa(REF, self.context(data)).remaining, expected)

    def test_env_cookie_can_be_used_for_a_single_direct_call_without_an_admin_key(self):
        with mock.patch.dict(os.environ, {exa_dashboard.COOKIE_ENV: COOKIE}):
            report = exa.balance_exa("", self.context())
        self.get_entry.assert_not_called()
        self.assertEqual((report.status, report.remaining), ("ok", 10))
        self.assertEqual(report.key_fingerprint, key_fingerprint(COOKIE))

    def test_env_overrides_store_for_a_login_reference(self):
        with mock.patch.dict(os.environ, {exa_dashboard.COOKIE_ENV: "session=synthetic-override"}):
            report = exa.balance_exa(REF, self.context())
        self.get_entry.assert_not_called()
        self.assertEqual(self.requests[0].get_header("Cookie"), "session=synthetic-override")
        self.assertEqual(report.key_fingerprint, key_fingerprint(REF))

    def test_plain_key_still_calls_only_the_existing_admin_api_even_with_env_cookie(self):
        with mock.patch.dict(os.environ, {exa_dashboard.COOKIE_ENV: COOKIE}):
            report = exa.balance_exa("synthetic-service-key", self.context({"credits_usd": 42.5}))
        self.get_entry.assert_not_called()
        self.assertEqual(report.remaining, 42.5)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0].full_url, exa.EXA_BALANCE_URL)
        self.assertEqual(self.requests[0].get_header("X-api-key"), "synthetic-service-key")
        self.assertIsNone(self.requests[0].get_header("Cookie"))

    def test_missing_or_malformed_login_does_not_fall_back_to_admin_api(self):
        for record in (None, {}, {"cookie_header": 12}, {"cookie_header": " "},
                       {"cookie_header": COOKIE, "login_id": "different-login"}):
            with self.subTest(record=record), mock.patch.object(oauth_store, "get_entry", return_value=record):
                report = exa.balance_exa(REF, self.context())
                self.assertEqual(report.status, "needs_credential")
        self.assertEqual(self.requests, [])

    def test_store_errors_use_a_fixed_message_without_secrets(self):
        with mock.patch.object(oauth_store, "get_entry", side_effect=oauth_store.OAuthStoreError(COOKIE)):
            report = exa.balance_exa(REF, self.context())
        self.assertEqual((report.status, report.error_kind), ("error", "internal"))
        self.assertNotIn("synthetic-session", json.dumps(report.to_dict()))
        self.assertEqual(self.requests, [])

    def test_auth_rate_limit_and_server_errors_do_not_expose_error_bodies_or_headers(self):
        for code, kind in ((401, "invalid"), (403, "invalid"), (429, "rate_limit"), (500, "error")):
            with self.subTest(code=code):
                error = urllib.error.HTTPError(exa_dashboard.CREDITS_URL, code, COOKIE,
                                               {"Secret": COOKIE}, io.BytesIO(COOKIE.encode()))
                report = exa.balance_exa(REF, self.context(error))
                self.assertEqual((report.status, report.error_kind), ("error", kind))
                self.assertNotIn("synthetic-session", json.dumps(report.to_dict()))

    def test_network_errors_do_not_expose_the_exception_message(self):
        for error in (urllib.error.URLError(COOKIE), TimeoutError(COOKIE), OSError(COOKIE)):
            with self.subTest(error=type(error).__name__):
                report = exa.balance_exa(REF, self.context(error))
                self.assertEqual(report.status, "error")
                self.assertNotIn("synthetic-session", json.dumps(report.to_dict()))

    def test_logged_out_html_malformed_json_and_oversized_responses_are_errors(self):
        for body in (b"<html>login</html>", b"{", b"[]", b"x" * (exa_dashboard.MAX_BYTES + 1)):
            with self.subTest(length=len(body)):
                report = exa.balance_exa(REF, self.context(body))
                self.assertEqual(report.status, "error")
                self.assertIsNone(report.remaining)

    def test_unknown_credit_shapes_and_nonfinite_or_boolean_values_are_errors(self):
        for data in ({}, {"error": COOKIE}, {"orbCreditsInCents": None},
                     {"orbCreditsInCents": "100"}, {"orbCreditsInCents": True},
                     {"orbCreditsInCents": math.nan}, {"orbCreditsInCents": math.inf},
                     {"orbCreditsInCents": 10, "orbInvoiceDebt": False},
                     {"orbCreditsInCents": 10, "orbInvoiceDebt": "1"}):
            with self.subTest(data=data):
                report = exa.balance_exa(REF, self.context(data))
                self.assertEqual(report.status, "error")
                self.assertIsNone(report.remaining)
                self.assertNotIn("synthetic-session", json.dumps(report.to_dict()))

    def test_unknown_plan_shapes_are_errors_instead_of_guessing_payg(self):
        for plan in ({}, [], {"error": COOKIE}, {"subscription": "unexpected"},
                     {"subscription": {"plan": {"external_plan_id": 123}}}):
            with self.subTest(plan=plan):
                report = exa.balance_exa(REF, self.context(plan=plan))
                self.assertEqual(report.status, "error")
                self.assertIsNone(report.remaining)

    def test_no_subscription_uses_the_observed_nonenterprise_formula(self):
        report = exa.balance_exa(REF, self.context(plan={"subscription": None}))
        self.assertEqual((report.status, report.remaining), ("ok", 10))

    def test_billing_exempt_account_does_not_report_a_fictitious_credit_balance(self):
        report = exa.balance_exa(REF, self.context({"orbBillingExempt": True}))
        self.assertEqual(report.status, "unsupported")
        self.assertIsNone(report.remaining)
        self.assertEqual(len(self.requests), 1)

    def test_cookie_with_newlines_is_rejected_without_http_or_echo(self):
        with mock.patch.dict(os.environ, {exa_dashboard.COOKIE_ENV: COOKIE + "\r\nInjected: secret"}):
            report = exa.balance_exa(REF, self.context())
        self.assertEqual(report.status, "error")
        self.assertEqual(self.requests, [])
        self.assertNotIn("synthetic-session", json.dumps(report.to_dict()))


if __name__ == "__main__":
    unittest.main()
