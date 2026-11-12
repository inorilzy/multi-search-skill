"""Usage CLI views over disposable caches/stores with an injected fixed clock."""
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from multi_search_mcp import cli
from multi_search_mcp.src.plugins import balance, registry, usage_report, usage_store
from multi_search_mcp.src.plugins.base import BalanceReport, ProviderPlugin
from multi_search_mcp.src.plugins.cache import BalanceCache
from multi_search_mcp.src.state.key_state import key_fingerprint


NOW = datetime(2026, 3, 15, 12, tzinfo=timezone.utc)
FIRST_KEY = "fixture-first-credential"
SECOND_KEY = "fixture-second-credential"


def report(**overrides):
    values = dict(provider="fixture", status="ok", scope="key", unit="credits",
                  remaining=90, limit=100, key_fingerprint=key_fingerprint(FIRST_KEY),
                  fetched_at=NOW.isoformat(), resets_at=None, period=None)
    values.update(overrides)
    return BalanceReport(**values)


def plugin(plugin_id="fixture", **overrides):
    values = dict(id=plugin_id, label=plugin_id.upper(), key_provider=plugin_id,
                  balance=lambda credential, context: report(provider=plugin_id))
    values.update(overrides)
    return ProviderPlugin(**values)


class UsageCliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="usage-cli-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.plugins = [plugin()]
        self.keys = {"fixture": FIRST_KEY}

    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(registry, "builtin_plugins", return_value=tuple(self.plugins)),
            mock.patch.object(balance, "load_keys", return_value=self.keys),
            mock.patch.object(usage_report, "datetime", wraps=datetime) as clock,
        ):
            clock.now.return_value = NOW
            code = cli.main(["usage", *args], stdout=stdout, stderr=stderr)
        return code, stdout.getvalue(), stderr.getvalue()

    def payload(self, *args):
        code, stdout, stderr = self.invoke(*args)
        self.assertEqual(code, 0, stderr)
        self.assertEqual(stderr, "")
        return json.loads(stdout)

    def view(self, *args):
        return self.payload(*args)["providers"][0]

    def cache(self, *reports, cached_at=NOW):
        cache = BalanceCache()
        for row in reports:
            cache.put(row.provider, row, ttl_seconds=300, now=cached_at)
        cache.flush()

    def history(self, *points, **overrides):
        for hours_ago, remaining in points:
            usage_store.append_balance(report(
                fetched_at=(NOW - timedelta(hours=hours_ago)).isoformat(),
                remaining=remaining, **overrides,
            ), now=NOW)

    def pace(self):
        return self.view()["pace"][0]

    def test_json_contains_version_retention_and_spec_provider_fields(self):
        self.cache(report())
        self.history((2, 100), (0, 90))
        usage_store.record_call("fixture", "search", now=NOW)
        payload = self.payload()
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["retention_days"], 30)
        provider = payload["providers"][0]
        self.assertEqual(set(provider), {"id", "label", "balance_supported", "balance_note",
                                        "current", "history", "pace", "calls", "totals"})
        self.assertEqual(provider["current"], [report().to_dict()])
        self.assertEqual(set(provider["history"][0]),
                         {"key_fingerprint", "scope", "unit", "remaining", "limit", "fetched_at"})
        self.assertEqual(set(provider["pace"][0]), {"key_fingerprint", "scope", "unit", "rate_per_day",
                                                  "projected_empty_at", "lasts_until_reset", "reason"})

    def test_offline_current_reads_expired_cache_without_network(self):
        callback = mock.Mock(side_effect=AssertionError("offline query called provider"))
        self.plugins = [plugin(balance=callback)]
        self.cache(report(remaining=42), cached_at=NOW - timedelta(days=2))
        self.assertEqual(self.view()["current"][0]["remaining"], 42)
        callback.assert_not_called()

    def test_offline_cache_miss_does_not_query_or_create_files(self):
        callback = mock.Mock(side_effect=AssertionError("offline query called provider"))
        self.plugins = [plugin(balance=callback)]
        self.assertEqual(self.view()["current"], [])
        callback.assert_not_called()
        self.assertFalse((self.home / ".multi-search").exists())

    def test_refresh_fetches_missing_balance_once_then_reuses_cache(self):
        callback = mock.Mock(return_value=report(remaining=23))
        self.plugins = [plugin(balance=callback)]
        self.assertEqual(self.view("--refresh")["current"][0]["remaining"], 23)
        self.view("--refresh")
        self.assertEqual(callback.call_count, 1)

    def test_refresh_honors_each_plugins_ttl_instead_of_forcing_queries(self):
        short = mock.Mock(return_value=report(provider="short", remaining=12))
        long = mock.Mock(return_value=report(provider="long", remaining=34))
        self.plugins = [plugin("short", balance=short, balance_ttl_seconds=30),
                        plugin("long", balance=long, balance_ttl_seconds=300)]
        self.keys = {"short": FIRST_KEY, "long": FIRST_KEY}
        self.cache(report(provider="short"), report(provider="long"), cached_at=NOW - timedelta(seconds=60))
        views = self.payload("--refresh")["providers"]
        self.assertEqual([row["current"][0]["remaining"] for row in views], [12, 90])
        self.assertEqual(short.call_count, 1)
        long.assert_not_called()

    def test_repeatable_provider_filter_preserves_registry_order(self):
        self.plugins = [plugin("first", balance=None), plugin("second", balance=None), plugin("third", balance=None)]
        payload = self.payload("--provider", "third", "--provider", "first")
        self.assertEqual([row["id"] for row in payload["providers"]], ["first", "third"])

    def test_unknown_provider_returns_exit_code_two(self):
        code, stdout, stderr = self.invoke("--provider", "unknown")
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("unknown provider", stderr)

    def test_days_outside_one_to_thirty_returns_exit_code_two(self):
        for value in ("0", "31", "bad"):
            with self.subTest(days=value):
                code, stdout, stderr = self.invoke("--days", value)
                self.assertEqual(code, 2)
                self.assertEqual(stdout, "")
                self.assertIn("usage error", stderr)

    def test_days_limits_history_and_daily_without_truncating_seven_day_total(self):
        self.history((240, 100), (24, 95), (0, 90))
        usage_store.record_call("fixture", "search", now=NOW - timedelta(days=3))
        usage_store.record_call("fixture", "scrape", now=NOW)
        provider = self.view("--days", "1")
        self.assertEqual(len(provider["history"]), 2)
        self.assertEqual(len(provider["calls"]["daily"]), 1)
        self.assertEqual(provider["calls"]["last_7_days"]["search"], 1)

    def test_calls_aggregate_search_scrape_and_failures_by_local_day(self):
        for purpose, failed, days_ago in (("search", False, 0), ("search", True, 0),
                                          ("scrape", True, 0), ("search", True, 6), ("scrape", False, 7)):
            usage_store.record_call("fixture", purpose, failed=failed, now=NOW - timedelta(days=days_ago))
        calls = self.view()["calls"]
        self.assertEqual(calls["today"], {"search": 2, "scrape": 1, "failures": 2})
        self.assertEqual(calls["last_7_days"], {"search": 3, "scrape": 1, "failures": 3})
        self.assertEqual(calls["daily"][-1], {"day": NOW.astimezone().date().isoformat(),
                                             "search": 2, "scrape": 1, "failures": 2})

    def test_unreadable_usage_store_returns_zero_and_safe_error_without_replacing_file(self):
        path = usage_store.default_usage_path()
        path.parent.mkdir(parents=True)
        corrupt = b"invalid sqlite containing owner@example.com token=fixture-private"
        path.write_bytes(corrupt)
        self.cache(report())
        payload = self.payload()
        self.assertEqual(payload["usage_error"], "unreadable")
        self.assertEqual(payload["providers"][0]["history"], [])
        self.assertEqual(payload["providers"][0]["calls"], {"today": {}, "last_7_days": {}, "daily": []})
        self.assertEqual(path.read_bytes(), corrupt)
        self.assertNotIn("owner@example.com", json.dumps(payload))

    def test_text_has_one_chinese_paragraph_per_provider(self):
        self.plugins.append(plugin("local", balance=None, balance_note="不提供余额"))
        self.cache(report())
        self.history((2, 100), (0, 90))
        code, stdout, stderr = self.invoke("--format", "text")
        self.assertEqual(code, 0, stderr)
        paragraphs = stdout.strip().split("\n\n")
        self.assertEqual(len(paragraphs), 2)
        self.assertIn("剩余 90/100 credits", paragraphs[0])
        self.assertIn("配速", paragraphs[0])
        self.assertIn("本机调用（今天）", paragraphs[0])
        self.assertIn("仅本机统计：不提供余额", paragraphs[1])

    def test_text_displays_insufficient_data_in_chinese(self):
        self.history((0, 90))
        code, stdout, stderr = self.invoke("--format", "text")
        self.assertEqual(code, 0, stderr)
        self.assertIn("数据不足", stdout)

    def test_cached_messages_and_metadata_redact_keys_tokens_and_emails(self):
        leak = f"{FIRST_KEY} owner@example.com Authorization: Bearer fixture-bearer-token"
        self.plugins = [plugin(balance_note=leak)]
        self.cache(report(message=leak))
        for output_format in ("json", "text"):
            with self.subTest(output_format=output_format):
                code, stdout, stderr = self.invoke("--format", output_format)
                self.assertEqual(code, 0, stderr)
                for secret in (FIRST_KEY, "owner@example.com", "fixture-bearer-token"):
                    self.assertNotIn(secret, stdout + stderr)

    def test_configuration_read_failure_returns_nonzero(self):
        with mock.patch.object(balance, "load_keys", side_effect=ValueError("cannot read config")):
            with mock.patch.object(registry, "builtin_plugins", return_value=tuple(self.plugins)):
                stdout, stderr = io.StringIO(), io.StringIO()
                code = cli.main(["usage"], stdout=stdout, stderr=stderr)
        self.assertEqual(code, 1)
        self.assertIn("cannot read config", stderr.getvalue())

    def test_two_known_keys_are_added_in_totals_and_preserved_in_current(self):
        self.keys["fixture"] = [FIRST_KEY, SECOND_KEY]
        self.cache(report(remaining=20, limit=100), report(remaining=30, limit=200,
                                                       key_fingerprint=key_fingerprint(SECOND_KEY)))
        view = self.view()
        self.assertEqual(len(view["current"]), 2)
        self.assertEqual(view["totals"], [{"scope": "key", "unit": "credits", "remaining": 50,
                                          "limit": 300, "key_count": 2, "message": ""}])

    def test_any_unknown_key_value_makes_only_that_total_unknown(self):
        self.keys["fixture"] = [FIRST_KEY, SECOND_KEY]
        self.cache(report(remaining=20, limit=None), report(remaining=None, limit=200,
                                                         key_fingerprint=key_fingerprint(SECOND_KEY)))
        total = self.view()["totals"][0]
        self.assertIsNone(total["remaining"])
        self.assertIsNone(total["limit"])
        self.assertEqual(total["message"], "部分 Key 未知")

    def test_unknown_remaining_does_not_hide_known_limit_total(self):
        self.keys["fixture"] = [FIRST_KEY, SECOND_KEY]
        self.cache(report(remaining=None), report(key_fingerprint=key_fingerprint(SECOND_KEY)))
        total = self.view()["totals"][0]
        self.assertIsNone(total["remaining"])
        self.assertEqual(total["limit"], 200)

    def test_shared_team_and_account_reports_are_not_added(self):
        for scope in ("team", "account"):
            with self.subTest(scope=scope):
                self.keys["fixture"] = [FIRST_KEY, SECOND_KEY]
                self.cache(report(scope=scope), report(scope=scope, key_fingerprint=key_fingerprint(SECOND_KEY)))
                total = self.view()["totals"][0]
                self.assertEqual((total["remaining"], total["limit"]), (90, 100))

    def test_totals_keep_different_units_and_scopes_separate(self):
        cache = BalanceCache()
        cache.put("fixture", [report(), report(unit="requests", remaining=5), report(scope="account", remaining=8)],
                  ttl_seconds=300, now=NOW)
        cache.flush()
        self.assertEqual(len(self.view()["totals"]), 3)

    def test_pace_with_one_point_is_insufficient(self):
        self.history((0, 90))
        pace = self.pace()
        self.assertEqual(pace["reason"], "insufficient_data")
        self.assertIsNone(pace["rate_per_day"])

    def test_pace_with_less_than_one_hour_is_insufficient(self):
        self.history((0.5, 100), (0, 90))
        self.assertEqual(self.pace()["reason"], "insufficient_data")

    def test_pace_accepts_exactly_one_hour_span(self):
        self.history((1, 100), (0, 90))
        self.assertEqual(self.pace()["rate_per_day"], 240)

    def test_pace_restarts_after_remaining_increases(self):
        self.history((72, 100), (48, 50), (24, 200), (0, 180))
        self.assertEqual(self.pace()["rate_per_day"], 20)

    def test_pace_topup_at_latest_point_is_insufficient(self):
        self.history((24, 50), (0, 200))
        self.assertEqual(self.pace()["reason"], "insufficient_data")

    def test_pace_uses_calendar_month_cycle_and_excludes_older_points(self):
        self.history((24 * 20, 1000), (24 * 10, 100), (0, 90),
                     resets_at="2026-04-01T00:00:00+00:00", period="month")
        self.assertEqual(self.pace()["rate_per_day"], 1)

    def test_pace_uses_calendar_year_cycle(self):
        self.history((24 * 10, 100), (0, 90), resets_at="2027-01-01T00:00:00+00:00", period="year")
        self.assertEqual(self.pace()["rate_per_day"], 1)

    def test_pace_uses_hour_cycle(self):
        self.history((2, 100), (1, 95), (0, 90), resets_at=NOW.isoformat(), period="hour")
        self.assertEqual(self.pace()["reason"], "insufficient_data")

    def test_pace_with_unknown_period_falls_back_to_recent_seven_days(self):
        self.history((24 * 8, 1000), (24 * 2, 100), (0, 90), resets_at="2026-04-01T00:00:00+00:00")
        self.assertEqual(self.pace()["rate_per_day"], 5)

    def test_pace_with_no_reset_leaves_lasts_until_reset_null(self):
        self.history((24, 100), (0, 90))
        pace = self.pace()
        self.assertEqual(pace["rate_per_day"], 10)
        self.assertEqual(datetime.fromisoformat(pace["projected_empty_at"]), NOW + timedelta(days=9))
        self.assertIsNone(pace["lasts_until_reset"])

    def test_zero_rate_has_no_empty_date_and_lasts_until_reset(self):
        self.history((24, 100), (0, 100), resets_at="2026-04-01T00:00:00+00:00", period="month")
        pace = self.pace()
        self.assertEqual(pace["rate_per_day"], 0)
        self.assertIsNone(pace["projected_empty_at"])
        self.assertTrue(pace["lasts_until_reset"])

    def test_pace_predicts_enough_balance_until_reset(self):
        self.history((24, 100), (0, 99), resets_at="2026-04-01T00:00:00+00:00", period="month")
        self.assertTrue(self.pace()["lasts_until_reset"])

    def test_pace_predicts_exhaustion_before_reset(self):
        self.history((24, 100), (0, 50), resets_at="2026-04-01T00:00:00+00:00", period="month")
        self.assertFalse(self.pace()["lasts_until_reset"])

    def test_pace_with_unknown_latest_remaining_is_insufficient(self):
        self.history((48, 100), (24, 90), (0, None))
        self.assertEqual(self.pace()["reason"], "insufficient_data")

    def test_pace_keeps_keys_separate(self):
        self.history((24, 100), (0, 90))
        self.history((24, 200), (0, 150), key_fingerprint=key_fingerprint(SECOND_KEY))
        self.assertEqual([row["rate_per_day"] for row in self.view()["pace"]], [10, 50])


if __name__ == "__main__":
    unittest.main()
