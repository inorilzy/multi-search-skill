"""Keyed balance adapters: Tavily, Firecrawl, SerpAPI, Jina and GitHub (ticket 04).

Every request goes through an injected fake HTTP callable; the suite never
touches the network. Success payloads follow the examples in
``.scratch/provider-plugins/research-balance-apis.md``.
"""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from multi_search_mcp.src.plugins import balance as balance_module
from multi_search_mcp.src.plugins import registry
from multi_search_mcp.src.plugins.balance import collect_balances
from multi_search_mcp.src.plugins.base import BalanceContext
from multi_search_mcp.src.plugins.builtin import firecrawl, github, jina, serpapi, tavily

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class FakeResponse:
    """Minimal urllib response: context manager plus bounded ``read``."""

    def __init__(self, body):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.headers = {"Content-Length": str(len(self.body))}

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self, amount=None):
        if amount is None or amount < 0:
            return self.body
        return self.body[:amount]


class RecordingHTTP:
    """Fake ``BalanceContext.http`` that records each request."""

    def __init__(self, result):
        self.result = result
        self.requests = []

    def __call__(self, request, *, timeout, retries, deadline):
        self.requests.append(request)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def fake_context(result):
    http = RecordingHTTP(result)
    return BalanceContext(timeout=10, http=http), http


def http_error(status, body=b"", url="https://example.com/balance"):
    return urllib.error.HTTPError(url, status, "error", {}, io.BytesIO(body))


def serialized(report_or_reports):
    items = report_or_reports if isinstance(report_or_reports, list) else [report_or_reports]
    return json.dumps([report.to_dict() for report in items], ensure_ascii=False)


class KeyedBalanceTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="balance-keyed-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        patcher = mock.patch.dict(
            os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)}
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def collect(self, plugin, keys, fake_http, **kwargs):
        with (
            mock.patch.object(registry, "builtin_plugins", return_value=(plugin,)),
            mock.patch("multi_search_mcp.src.support.http.urlopen_retry", fake_http),
        ):
            return collect_balances(provider_ids=[plugin.id], keys=keys, **kwargs)


class TavilyBalanceTests(KeyedBalanceTestCase):
    PAYLOAD = {
        "key": {"usage": 250, "limit": 1000, "search_usage": 200},
        "account": {
            "current_plan": "Bootstrap",
            "plan_usage": 250,
            "plan_limit": 1000,
            "paygo_usage": 5,
            "paygo_limit": 100,
        },
    }

    def test_key_and_account_reports_use_usage_minus_limit(self):
        context, http = fake_context(FakeResponse(self.PAYLOAD))
        reports = tavily.balance_tavily("tvly-secret", context)

        request = http.requests[0]
        self.assertEqual(request.full_url, "https://api.tavily.com/usage")
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Authorization"), "Bearer tvly-secret")
        self.assertEqual(len(reports), 2)

        key_report, account_report = reports
        self.assertEqual((key_report.status, key_report.scope, key_report.unit), ("ok", "key", "credits"))
        self.assertEqual((key_report.remaining, key_report.limit, key_report.used), (750, 1000, 250))
        self.assertEqual((account_report.status, account_report.scope), ("ok", "account"))
        self.assertEqual((account_report.remaining, account_report.limit, account_report.used), (845, 1100, 255))
        self.assertIn("paygo", account_report.message)
        self.assertNotIn("tvly-secret", serialized(reports))

    def test_null_key_limit_leaves_remaining_null(self):
        context, _http = fake_context(FakeResponse({"key": {"usage": 42, "limit": None}}))
        reports = tavily.balance_tavily("tvly-secret", context)

        self.assertIsNone(reports[0].remaining)
        self.assertIsNone(reports[0].limit)
        self.assertEqual(reports[0].used, 42)
        self.assertIsNone(reports[1].remaining)
        self.assertIsNone(reports[1].limit)

    def test_missing_key_block_leaves_all_numbers_null(self):
        context, _http = fake_context(FakeResponse({"account": {}}))
        reports = tavily.balance_tavily("tvly-secret", context)

        self.assertIsNone(reports[0].remaining)
        self.assertIsNone(reports[0].limit)
        self.assertIsNone(reports[0].used)

    def test_401_is_invalid_and_does_not_echo_the_key(self):
        context, _http = fake_context(http_error(401, b'{"detail":"Invalid API key tvly-secret"}'))
        reports = tavily.balance_tavily("tvly-secret", context)

        self.assertEqual(reports[0].status, "error")
        self.assertEqual(reports[0].error_kind, "invalid")
        self.assertNotIn("tvly-secret", serialized(reports))

    def test_429_is_rate_limit(self):
        context, _http = fake_context(http_error(429, b'{"detail":"Too many requests"}'))
        reports = tavily.balance_tavily("tvly-secret", context)

        self.assertEqual((reports[0].status, reports[0].error_kind), ("error", "rate_limit"))

    def test_non_json_response_is_an_error(self):
        context, _http = fake_context(FakeResponse(b"<html>maintenance</html>"))
        reports = tavily.balance_tavily("tvly-secret", context)

        self.assertEqual((reports[0].status, reports[0].error_kind), ("error", "error"))

    def test_balance_ttl_respects_the_usage_rate_limit(self):
        self.assertGreaterEqual(tavily.PLUGIN.balance_ttl_seconds, 120)

    def test_collection_caches_key_and_account_reports_together(self):
        calls = []

        def fake_http(request, *, timeout, retries, deadline):
            calls.append(request.full_url)
            return FakeResponse(self.PAYLOAD)

        first = self.collect(tavily.PLUGIN, {"tavily": "tvly-secret"}, fake_http, now=NOW)
        second = self.collect(tavily.PLUGIN, {"tavily": "tvly-secret"}, fake_http, now=NOW)

        self.assertEqual(calls, ["https://api.tavily.com/usage"])
        self.assertEqual([report["scope"] for report in first["providers"][0]["reports"]], ["key", "account"])
        self.assertEqual(len(second["providers"][0]["reports"]), 2)


class FirecrawlBalanceTests(KeyedBalanceTestCase):
    PAYLOAD = {
        "success": True,
        "data": {
            "remainingCredits": 320,
            "planCredits": 1000,
            "billingPeriodStart": "2026-11-01T00:00:00.000Z",
            "billingPeriodEnd": "2026-12-01T00:00:00.000Z",
        },
    }

    def test_team_credit_usage_maps_to_a_team_report(self):
        context, http = fake_context(FakeResponse(self.PAYLOAD))
        report = firecrawl.balance_firecrawl("fc-secret", context)

        request = http.requests[0]
        self.assertEqual(request.full_url, "https://api.firecrawl.dev/v2/team/credit-usage")
        self.assertEqual(request.get_header("Authorization"), "Bearer fc-secret")
        self.assertEqual((report.status, report.scope, report.unit), ("ok", "team", "credits"))
        self.assertEqual((report.remaining, report.limit), (320, 1000))
        self.assertIsNone(report.used)
        self.assertEqual(report.resets_at, "2026-12-01T00:00:00.000Z")
        self.assertNotIn("fc-secret", serialized(report))

    def test_missing_credit_fields_are_null_not_zero(self):
        context, _http = fake_context(FakeResponse({"success": True, "data": {}}))
        report = firecrawl.balance_firecrawl("fc-secret", context)

        self.assertIsNone(report.remaining)
        self.assertIsNone(report.limit)
        self.assertIsNone(report.used)
        self.assertIsNone(report.resets_at)

    def test_402_is_quota_exhausted(self):
        context, _http = fake_context(http_error(402, b'{"error":"Insufficient credits"}'))
        report = firecrawl.balance_firecrawl("fc-secret", context)

        self.assertEqual((report.status, report.error_kind), ("error", "quota_exhausted"))

    def test_401_is_invalid_and_redacts_the_key(self):
        context, _http = fake_context(http_error(401, b'{"error":"bad key fc-secret"}'))
        report = firecrawl.balance_firecrawl("fc-secret", context)

        self.assertEqual(report.error_kind, "invalid")
        self.assertNotIn("fc-secret", serialized(report))

    def test_non_json_response_is_an_error(self):
        context, _http = fake_context(FakeResponse(b"not json"))
        report = firecrawl.balance_firecrawl("fc-secret", context)

        self.assertEqual((report.status, report.error_kind), ("error", "error"))


class SerpAPIBalanceTests(KeyedBalanceTestCase):
    PAYLOAD = {
        "api_key": "serp-secret",
        "account_email": "owner@example.com",
        "total_searches_left": 80,
        "searches_per_month": 100,
        "this_month_usage": 20,
        "plan_renewal_date": "2026-12-01",
    }

    def test_account_json_maps_to_a_monthly_search_report(self):
        context, http = fake_context(FakeResponse(self.PAYLOAD))
        report = serpapi.balance_serpapi("serp-secret", context)

        request = http.requests[0]
        self.assertEqual(request.get_method(), "GET")
        parts = urllib.parse.urlsplit(request.full_url)
        self.assertEqual(f"{parts.scheme}://{parts.netloc}{parts.path}", "https://serpapi.com/account.json")
        self.assertEqual(urllib.parse.parse_qs(parts.query)["api_key"], ["serp-secret"])
        self.assertEqual((report.status, report.scope, report.unit), ("ok", "key", "searches"))
        self.assertEqual((report.remaining, report.limit, report.used), (80, 100, 20))
        self.assertEqual(report.resets_at, "2026-12-01")
        self.assertEqual(report.period, "month")
        rendered = serialized(report)
        self.assertNotIn("serp-secret", rendered)
        self.assertNotIn("owner@example.com", rendered)

    def test_missing_quota_fields_are_null_not_zero(self):
        context, _http = fake_context(FakeResponse({"total_searches_left": None}))
        report = serpapi.balance_serpapi("serp-secret", context)

        self.assertIsNone(report.remaining)
        self.assertIsNone(report.limit)
        self.assertIsNone(report.used)

    def test_429_is_rate_limit(self):
        context, _http = fake_context(http_error(429, b'{"error":"Too many requests"}'))
        report = serpapi.balance_serpapi("serp-secret", context)

        self.assertEqual((report.status, report.error_kind), ("error", "rate_limit"))

    def test_401_error_body_key_is_redacted(self):
        context, _http = fake_context(http_error(401, b'{"error":"Invalid API key serp-secret"}'))
        report = serpapi.balance_serpapi("serp-secret", context)

        self.assertEqual(report.error_kind, "invalid")
        self.assertNotIn("serp-secret", serialized(report))

    def test_non_json_response_is_an_error(self):
        context, _http = fake_context(FakeResponse(b"<html>oops</html>"))
        report = serpapi.balance_serpapi("serp-secret", context)

        self.assertEqual((report.status, report.error_kind), ("error", "error"))


class JinaBalanceTests(KeyedBalanceTestCase):
    PAYLOAD = {
        "wallet": {
            "total_balance": 1234567,
            "regular_balance": 1234567,
            "trial_balance": 0,
            "trial_end": "2026-12-01T00:00:00+00:00",
        },
    }

    def test_wallet_total_balance_maps_to_a_key_token_report(self):
        context, http = fake_context(FakeResponse(self.PAYLOAD))
        report = jina.balance_jina("jina-secret", context)

        request = http.requests[0]
        parts = urllib.parse.urlsplit(request.full_url)
        self.assertEqual(
            f"{parts.scheme}://{parts.netloc}{parts.path}", "https://dash.jina.ai/api/v1/api_key/fe_user"
        )
        self.assertEqual(urllib.parse.parse_qs(parts.query)["api_key"], ["jina-secret"])
        self.assertEqual((report.status, report.scope, report.unit), ("ok", "key", "tokens"))
        self.assertEqual(report.remaining, 1234567)
        self.assertIsNone(report.limit)
        self.assertIsNone(report.used)
        self.assertIn("非公开接口", report.message)
        self.assertNotIn("jina-secret", serialized(report))

    def test_missing_wallet_balance_is_null(self):
        context, _http = fake_context(FakeResponse({"wallet": {}}))
        report = jina.balance_jina("jina-secret", context)

        self.assertIsNone(report.remaining)

    def test_401_is_invalid_and_redacts_the_url_key(self):
        context, _http = fake_context(http_error(401, b'{"detail":"Invalid API key jina-secret"}'))
        report = jina.balance_jina("jina-secret", context)

        self.assertEqual((report.status, report.error_kind), ("error", "invalid"))
        self.assertNotIn("jina-secret", serialized(report))

    def test_429_is_rate_limit(self):
        context, _http = fake_context(http_error(429, b"slow down"))
        report = jina.balance_jina("jina-secret", context)

        self.assertEqual(report.error_kind, "rate_limit")

    def test_non_json_response_is_an_error(self):
        context, _http = fake_context(FakeResponse(b"nope"))
        report = jina.balance_jina("jina-secret", context)

        self.assertEqual((report.status, report.error_kind), ("error", "error"))


class GitHubBalanceTests(KeyedBalanceTestCase):
    PAYLOAD = {
        "resources": {
            "search": {"limit": 30, "remaining": 25, "used": 5, "reset": 1765000000},
            "code_search": {"limit": 10, "remaining": 9, "used": 1, "reset": 1765000000},
        },
    }
    RESET_ISO = datetime.fromtimestamp(1765000000, tz=timezone.utc).isoformat()

    def test_anonymous_query_has_no_authorization_and_two_reports(self):
        context, http = fake_context(FakeResponse(self.PAYLOAD))
        reports = github.balance_github("", context)

        request = http.requests[0]
        self.assertEqual(request.full_url, "https://api.github.com/rate_limit")
        self.assertIsNone(request.get_header("Authorization"))
        self.assertEqual([report.status for report in reports], ["ok", "ok"])
        self.assertEqual([report.unit for report in reports], ["requests", "requests"])
        self.assertEqual([report.period for report in reports], ["hour", "hour"])

    def test_token_is_sent_as_bearer_and_search_quotas_are_reported(self):
        context, http = fake_context(FakeResponse(self.PAYLOAD))
        reports = github.balance_github("ghp-secret", context)

        self.assertEqual(http.requests[0].get_header("Authorization"), "Bearer ghp-secret")
        search, code_search = reports
        self.assertEqual((search.remaining, search.limit, search.used), (25, 30, 5))
        self.assertEqual((code_search.remaining, code_search.limit, code_search.used), (9, 10, 1))
        self.assertEqual(search.resets_at, self.RESET_ISO)
        self.assertEqual(code_search.resets_at, self.RESET_ISO)
        self.assertIn("search", search.message)
        self.assertIn("code_search", code_search.message)
        self.assertNotIn("ghp-secret", serialized(reports))

    def test_missing_resource_fields_are_null_not_zero(self):
        context, _http = fake_context(FakeResponse({"resources": {"search": {}}}))
        reports = github.balance_github("", context)

        self.assertIsNone(reports[0].remaining)
        self.assertIsNone(reports[0].limit)
        self.assertIsNone(reports[0].used)
        self.assertIsNone(reports[0].resets_at)

    def test_500_is_a_generic_error(self):
        context, _http = fake_context(http_error(500, b"boom"))
        reports = github.balance_github("ghp-secret", context)

        self.assertEqual((reports[0].status, reports[0].error_kind), ("error", "error"))

    def test_non_json_response_is_an_error(self):
        context, _http = fake_context(FakeResponse(b"<html>oops</html>"))
        reports = github.balance_github("ghp-secret", context)

        self.assertEqual((reports[0].status, reports[0].error_kind), ("error", "error"))

    def test_collection_reports_github_without_a_configured_key(self):
        def fake_http(request, *, timeout, retries, deadline):
            return FakeResponse(self.PAYLOAD)

        payload = self.collect(github.PLUGIN, {}, fake_http)

        provider = payload["providers"][0]
        self.assertTrue(provider["balance_supported"])
        self.assertEqual([report["status"] for report in provider["reports"]], ["ok", "ok"])
        self.assertIsNone(provider["reports"][0]["key_fingerprint"])

    def test_collection_uses_the_configured_github_token(self):
        seen = []

        def fake_http(request, *, timeout, retries, deadline):
            seen.append(request.get_header("Authorization"))
            return FakeResponse(self.PAYLOAD)

        payload = self.collect(github.PLUGIN, {"github": "ghp-secret"}, fake_http)

        self.assertEqual(seen, ["Bearer ghp-secret"])
        self.assertNotIn("ghp-secret", json.dumps(payload, ensure_ascii=False))

    def test_collection_reads_the_github_token_from_the_keys_store(self):
        seen = []

        def fake_http(request, *, timeout, retries, deadline):
            seen.append(request.get_header("Authorization"))
            return FakeResponse(self.PAYLOAD)

        with (
            mock.patch.object(registry, "builtin_plugins", return_value=(github.PLUGIN,)),
            mock.patch("multi_search_mcp.src.support.http.urlopen_retry", fake_http),
            mock.patch.object(
                balance_module, "load_keys", return_value={"github": "ghp-file-secret"}
            ),
        ):
            payload = collect_balances(provider_ids=["github"])

        self.assertEqual(seen, ["Bearer ghp-file-secret"])
        self.assertIsNotNone(payload["providers"][0]["reports"][0]["key_fingerprint"])


if __name__ == "__main__":
    unittest.main()
